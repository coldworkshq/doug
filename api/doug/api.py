"""HTTP surface. Routes stay thin: the product lives in features.py and scoring.py."""

import hashlib
import hmac
import json
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from githubkit.webhooks import verify as verify_webhook
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import (
    __version__,
    app_auth,
    entitlements,
    ingest,
    install_flow,
    outcome_queue,
    precision,
    reader,
    session_auth,
    store,
    tenancy,
    worker,
    workos_client,
)
from .models import (
    Band,
    HealthResponse,
    JobItem,
    JobListResponse,
    PRMetadata,
    QueueItem,
    QueueResponse,
    QueueSummary,
    ReadScoreRequest,
    Reason,
    RunCoverage,
    RunDetailJob,
    RunDetailResponse,
    RunDeviation,
    RunFindingCounts,
    RunJob,
    RunListResponse,
    RunOutcome,
    RunOutcomeJob,
    RunSummaryItem,
    Verdict,
)
from .scoring import default_threshold, score

# Named so it is identifiable in a thread dump or a py-spy trace of a
# revision that is busy at boot, and so tests can assert on the one thread
# startup is allowed to spawn.
STARTUP_THREAD_NAME = "doug-startup-reconcile"


def _startup_reconcile() -> None:
    """Heal the queue this instance came up to, then work it.

    Both halves belong to the same catch-up and in this order: reconcile_all
    only enqueues, so a drain running ahead of it would drain whatever the
    last delivery left and stop, leaving everything this sweep discovers
    waiting for a delivery that already went missing once.

    This runs on every cold start, which on a scale-to-zero deployment means
    often, and nothing here rate-limits it or elects a leader. What bounds
    the repeat cost lives in the schema and the worker instead. Re-enqueueing
    a head SHA the queue already reviewed collides on uq_review_job and
    ingest._revive returns None for a 'done' row, so a sweep that finds
    nothing new leaves nothing for the drain to claim. A job that is claimed
    is checked against store.find_verdict_by_identity before any paid read.
    Repeated sweeps therefore cost GitHub list calls, not model spend.

    The gap that leaves on spend: the pre-read is still advisory, so two
    workers racing the same reclaimed job can both pass it and both pay.
    Migration 005's unique index stops the second verdicts row; the claim
    fence stops a superseded holder finishing the job. Double-spend of the
    read is bounded by the spend cap, not by this path.

    Two drift checks run first, in their OWN try: they are diagnostic, and
    the sweep is the job. Sharing one try with the catch-up meant a
    diagnostic-only DB error landed in the except below and skipped
    reconcile_all for the whole cold start — the same silent-no-op class
    the diagnostics exist to detect. Doug's own review of PR #50 flagged
    exactly that.
    """
    try:
        try:
            if store.enabled() and not store.active_installations():
                referenced = store.count_installations_referenced_by_verdicts()
                if referenced:
                    print(
                        f"doug: DRIFT — verdicts reference {referenced} installation(s) but the "
                        "installations table is empty; reconcile_all and token dispense are "
                        "structural no-ops. Redeliver the installation webhook (ROADMAP MT0).",
                        file=sys.stderr,
                    )
            missing = store.count_verdict_repos_missing_from_ledger()
            if missing:
                print(
                    f"doug: DRIFT — {missing} repo(s) referenced by verdicts have no "
                    "installation_repos row; their tenants cannot see those verdicts. "
                    "Redeliver the installation_repositories webhook (ROADMAP MT0-class).",
                    file=sys.stderr,
                )
        except Exception as e:  # noqa: BLE001 — diagnostics never cost the sweep
            print(f"doug: drift check failed ({type(e).__name__}: {e})", file=sys.stderr)
        n = worker.reconcile_all()
        print(f"doug: reconcile enqueued {n} job(s)", file=sys.stderr)
        worker.drain()
    except Exception as e:  # noqa: BLE001 — catch-up is best-effort, never fatal
        print(f"doug: startup reconcile failed ({type(e).__name__}: {e})", file=sys.stderr)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Refuse to boot without the webhook secret, then start the catch-up sweep.

    The reason is not that a deploy would wipe it: deploy() has carried
    GITHUB_WEBHOOK_SECRET in --set-secrets since #14, and --set-env-vars
    replaces the env block without disturbing a secret binding. It is that
    every remaining way this can go missing is silent — a revision deployed
    by hand or by some path that is not deploy(), a new project whose
    Secret Manager entry does not exist yet, a local run. Without it the
    handler cannot verify anything, and an unverified delivery under the App
    is a paid model read triggered by anyone who can POST. A crash-looping
    revision is a visible failure; a running service accepting forged
    deliveries is not.

    DATABASE_URL is deliberately not checked alongside it, and the three
    postures here are one rule, not an inconsistency: a security control
    that fails open is worthless, so the secret fails closed at boot; a
    ledger is an optional feature rather than a guarantee — store.py's
    ledger-less mode is what local dogfooding and the open-source path run
    on — so the one endpoint that cannot work without it refuses per
    request with a 503 and the rest of the service keeps serving; and the
    sweep below needs the App *and* the ledger to do anything at all, so a
    deployment holding neither promise skips it silently and loses nothing
    it could have had.
    """
    if not os.environ.get("GITHUB_WEBHOOK_SECRET"):
        raise RuntimeError(
            "GITHUB_WEBHOOK_SECRET is unset — refusing to serve /webhooks/github"
        )
    if app_auth.enabled() and store.enabled():
        # A thread, not an await and not inline: Cloud Run holds the revision
        # out of rotation until the lifespan yields, and this walks every open
        # PR of every installation and then runs paid model reads on the ones
        # it queued. Blocking startup on that fails the health check and the
        # revision never serves at all. daemon=True so a shutdown is never
        # held open waiting for it.
        threading.Thread(
            target=_startup_reconcile, name=STARTUP_THREAD_NAME, daemon=True
        ).start()
    yield


app = FastAPI(title="Doug", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("DOUG_CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str | bool]:
    return {"ok": True, "version": __version__}


@app.post("/v1/score")
def score_pr(pr: PRMetadata) -> Verdict:
    return score(pr)



@app.post("/v1/score/read")
def score_pr_read(req: ReadScoreRequest, x_doug_token: str = Header("")) -> Verdict:
    """Reader-tier scoring: LLM diff-read when enabled, deterministic otherwise.

    Token-gated on the same shared secret as /v1/queue, for a different
    reason than /v1/queue's: this route spends money. Every call can buy a
    model read and the service is deployed --allow-unauthenticated, so
    without a gate the URL alone is authority to bill the account.
    DIFF_BUDGET bounds what one call costs; only the token bounds how many.

    A failed read never 500s — it falls back to the deterministic verdict
    and says so in the reasons, because a silent downgrade would corrupt
    any calibration built on this endpoint's output. A partial read is not
    a failure — it returns a verdict, same as the worker's score_one path —
    but it gets the same read-truncated reason so a caller of this endpoint
    isn't the one path left unable to tell a whole read from part of one.

    The token bounds who calls; the sentinel scope's monthly cap bounds how
    much they can spend. This probe is never tenanted — there is no
    installation in the request to charge — so it shares that ceiling with
    the CI review path rather than any customer's budget.
    """
    # The shared gate lives in _operator_only below; this route is one of
    # its callers. Task 9 (2026-08-05) deleted /v1/review, which carried the
    # last inline copy of this check — every operator route goes through the
    # shared gate now.
    _operator_only(x_doug_token)
    if not reader.enabled():
        return score(req.pr)
    try:
        verdict = reader.verdict_from_reader(
            reader.read_diff(req.pr, req.diff, scope=reader.SENTINEL_SCOPE)
        )
        if notice := reader.truncation_reason(reader.coverage(req.diff)):
            verdict.reasons.append(notice)
        return verdict
    except reader.SpendCapExceeded as e:
        # Ahead of the ReaderError clause below, which would otherwise
        # catch this subclass and report a spent budget as a broken reader.
        capped = score(req.pr)
        capped.reasons.append(Reason(rule="reader-capped", label=str(e), weight=0.0))
        return capped
    except reader.ReaderError as e:
        fallback = score(req.pr)
        fallback.reasons.append(
            Reason(rule="reader-unavailable", label=str(e), weight=0.0)
        )
        return fallback


def _load_fixture() -> list[PRMetadata]:
    raw = resources.files("doug").joinpath("fixtures/queue.json").read_text()
    return [PRMetadata.model_validate(item) for item in json.loads(raw)]


def _with_url(row: dict) -> PRMetadata:
    """PR metadata with a link back to the pull request.

    Rows written before `url` was captured — every backfilled probe row and
    everything scored up to now — have none. The ledger knows the repo and
    the number, which is all a GitHub PR URL needs, so they are repaired on
    read rather than by rewriting 654 rows.
    """
    meta = PRMetadata.model_validate(row["pr_meta"])
    if meta.url:
        return meta
    return meta.model_copy(
        update={"url": f"https://github.com/{row['repo']}/pull/{row['pr_number']}"}
    )


def _banding_threshold(items: list[QueueItem], fallback: float) -> float:
    """The line these rows were actually banded at.

    Rows can disagree — a reader row is banded at 0.30, a deterministic
    fallback row at 0.62 — in which case no single line is honest and the
    most common one is the least wrong. The per-item thresholds stay
    authoritative either way; this only decides where the dashboard draws.
    """
    if not items:
        return fallback
    seen: dict[float, int] = {}
    for i in items:
        seen[i.verdict.threshold] = seen.get(i.verdict.threshold, 0) + 1
    return max(seen, key=lambda t: (seen[t], -t))


def _operator_only(x_doug_token: str) -> None:
    """Gate an endpoint that no tenant may reach.

    Three outcomes, and the middle one is the point: a token that RESOLVES
    to an installation is a real credential aimed at the wrong door, so it
    gets 404 — the same no-existence-leak rule a cross-tenant repo gets.
    A token that resolves to nothing is 401, because nothing about it was
    ever valid.

    That no-existence-leak rule is about DATA, not about the route itself:
    this gate runs after FastAPI has already coerced the request's typed
    query and path params, so a malformed one (e.g. `?limit=abc`, or a
    non-integer `verdict_id`) 422s on a real operator route before this
    function ever runs, versus 404 on a route that doesn't exist at all —
    letting an unauthenticated caller distinguish the two. That is accepted,
    not a gap: routes are public by ADR-0008, this gate still fails closed
    on every credential it does see, no response body it produces ever
    contains data, and the same 422-vs-404 split pre-exists identically on
    `/v1/patterns` and `/v1/runs`.
    """
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if hmac.compare_digest(x_doug_token, expected):
        return
    try:
        if tenancy.resolve(x_doug_token) is not None:
            raise HTTPException(status_code=404, detail="not found")
    except tenancy.KeysNotConfigured as e:
        raise HTTPException(status_code=503, detail="token verification not configured") from e
    raise HTTPException(status_code=401, detail="bad token")


def _rows_to_items(rows: list[dict]) -> list[QueueItem]:
    """Ledger rows -> queue items. Rows without pr_meta are dropped: the
    queue renders PR titles and authors, and a row that has none would
    render as a blank card rather than a missing one."""
    return [
        QueueItem(
            pr=_with_url(row),
            verdict=Verdict(
                score=row["score"],
                band=Band(row["band"]),
                threshold=row["threshold"],
                reasons=[
                    Reason(
                        rule=f["rule"],
                        label=f["label"],
                        weight=f["weight"],
                        severity=f["severity"],
                    )
                    for f in row["findings"]
                ],
            ),
        )
        for row in rows
        if row["pr_meta"]
    ]


def _queue_response(
    items: list[QueueItem], threshold: float | None
) -> QueueResponse:
    """Band, sort and summarise. Shared by /v1/queue and
    /v1/showcase/queue so the two cannot drift on the banding rule —
    which is the one place this surface has already been wrong once
    (reporting 0.62 while showing rows flagged at 0.30)."""
    thr = default_threshold() if threshold is None else threshold
    if threshold is None:
        # Report the line the rows were actually banded at, not the
        # deterministic default.
        thr = _banding_threshold(items, thr)
    else:
        # An explicit threshold has to re-band, or the parameter changes
        # the summary while the rows keep contradicting it.
        items = [
            QueueItem(
                pr=i.pr,
                verdict=i.verdict.model_copy(
                    update={
                        "threshold": thr,
                        "band": Band.FLAGGED if i.verdict.score >= thr else Band.CLEARED,
                    }
                ),
            )
            for i in items
        ]

    items.sort(key=lambda i: i.verdict.score, reverse=True)
    flagged = sum(1 for i in items if i.verdict.band is Band.FLAGGED)
    return QueueResponse(
        summary=QueueSummary(
            open=len(items),
            flagged=flagged,
            cleared=len(items) - flagged,
            threshold=thr,
        ),
        items=items,
    )


@app.get("/v1/queue")
def queue(
    threshold: float | None = None,
    repo: str | None = None,
    x_doug_token: str = Header(""),
) -> QueueResponse:
    """The review queue: real PR titles, authors and reader rationales, on
    a service deployed --allow-unauthenticated, so this stays token-gated.

    Two token classes reach this endpoint. DOUG_API_TOKEN is the operator's
    and is unscoped. A dispensed token resolves to one installation and sees
    only its rows, and `repo` becomes a filter WITHIN that scope rather than
    a selector across scopes.
    """
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        # A missing operator secret is a misconfigured deployment. A tenant
        # token does not depend on it and could be honoured anyway, but
        # letting tenant traffic paper over the gap would hide the fault.
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    installation_id: int | None = None
    repo_ids: frozenset[int] | None = None
    ctx: tenancy.TokenContext | None = None
    # Operator identity is this comparison, explicitly — never inferred from
    # ctx staying None. A future session credential that never produces a
    # TokenContext must not silently inherit the operator's unscoped ?repo=
    # name lookup below just by also leaving ctx as None.
    is_operator = hmac.compare_digest(x_doug_token, expected)
    if not is_operator:
        try:
            ctx = tenancy.resolve(x_doug_token)
        except tenancy.KeysNotConfigured as e:
            raise HTTPException(status_code=503, detail="token verification not configured") from e
        if ctx is None:
            raise HTTPException(status_code=401, detail="bad token")
        # Scope gate: every key mints with queue:read today, but the scopes
        # column exists so a future receipts/MCP-only key does not silently
        # inherit queue access it was never granted. Same posture as an
        # unresolved token — 401, not 403 — so this route stays consistent
        # with itself.
        if "queue:read" not in ctx.scopes:
            raise HTTPException(status_code=401, detail="bad token")
        installation_id = ctx.installation_id
        live = {full_name: rid for rid, full_name in store.active_repos(installation_id)}
        # The key's effective scope, in ids: its frozen selection (already
        # live-intersected by resolve) or, for 'all', everything live NOW.
        # installation_repos is the ONE source of truth — verdicts.repo and
        # full_name are display everywhere (MT4).
        effective = ctx.repo_ids if ctx.repo_ids is not None else frozenset(live.values())
        if repo is not None:
            rid = live.get(repo)
            if rid is None or rid not in effective:
                # 404, never an empty list: an empty list reads as "no
                # reviews yet" and confirms the repo's existence.
                raise HTTPException(status_code=404, detail="not found")
            effective = frozenset({rid})
        repo_ids = effective
    thr = default_threshold() if threshold is None else threshold
    if store.enabled():
        items = _rows_to_items(
            store.latest_reviews(
                repo=repo if is_operator else None,  # operator keeps the display filter
                installation_id=installation_id,
                repo_ids=repo_ids,
            )
        )
    else:
        # No ledger configured — the fixture keeps the demo path alive.
        items = [QueueItem(pr=pr, verdict=score(pr, thr)) for pr in _load_fixture()]

    return _queue_response(items, threshold)


# In-process TTL cache for the showcase route ONLY. store.latest_reviews
# runs one findings query per row, up to limit=200 (store.py:1838) — and
# this route is public and unauthenticated, so a single caller can drive up
# to 201 queries per request against a scale-to-zero service. web/'s own
# micro-cache (web/lib/api.ts) does not help: anyone can call this API
# directly, bypassing doug-web entirely.
#
# A single slot, deliberately not a dict keyed on caller input: the route
# below takes NO caller input at all (see its docstring), so exactly one
# response can ever exist to cache. A dict keyed on anything a caller
# controls — threshold used to be exactly that — would let
# ?threshold=0.0001, 0.0002, ... grow this cache without bound on a public,
# scale-to-zero service: trading the DB-load amplifier this cache exists to
# fix for a memory-exhaustion one, which is a worse trade.
#
# 30s matches web/lib/api.ts's own cache of `/` — an established number,
# not a new one. time.monotonic() so a wall-clock step never falsely
# expires or extends the entry. A concurrent miss may recompute redundantly
# with another in-flight one; that race is cheap (one extra query burst,
# not unbounded) and benign, so there is deliberately no lock here.
_SHOWCASE_CACHE_TTL_S = 30.0
_showcase_cache: tuple[float, QueueResponse] | None = None


@app.get("/v1/showcase/queue")
def showcase_queue(response: Response) -> QueueResponse:
    """The public Doug-on-Doug queue, pinned to one repo by deployment.

    Unauthenticated by design (ADR-0008) and therefore NOT a selector: the
    repo comes from DOUG_SHOWCASE_REPO and never from the caller, so no
    request can widen it. It deliberately does NOT read DOUG_API_TOKEN —
    that independence is the whole reason this route exists, so doug-web
    can serve the public pages while holding no operator credential.

    Takes no caller input at all: `repo` is ignored (see
    test_showcase_queue_ignores_a_caller_supplied_repo) and so, deliberately,
    is `threshold` — the one real consumer, web/lib/api.ts's getQueue(),
    never sends it and re-bands client-side via applyThreshold instead. A
    server-side `threshold` param would only be attack surface here: a
    caller-controlled value with nothing to bound it, backed by the
    process-lifetime cache below. `?threshold=...` is simply ignored, same
    as `?repo=...` already is.

    Unset variable and no ledger both 404 rather than falling back to the
    bundled fixture: serving invented PRs from a PUBLIC url would be a
    confident false claim, and web/ already has its own labelled fixture
    fallback for the unreachable-API case.

    Cached briefly per `_showcase_cache` above, and marked cacheable by
    downstream infrastructure (CDN, browser) at the same TTL — the payload
    is deliberately public.
    """
    global _showcase_cache
    showcase = os.environ.get("DOUG_SHOWCASE_REPO")
    if not showcase or not store.enabled():
        raise _not_found()
    response.headers["Cache-Control"] = "public, max-age=30"
    now = time.monotonic()
    if _showcase_cache is not None and now - _showcase_cache[0] < _SHOWCASE_CACHE_TTL_S:
        return _showcase_cache[1]
    body = _queue_response(_rows_to_items(store.latest_reviews(repo=showcase)), None)
    _showcase_cache = (now, body)
    return body


# Rendered in words on EVERY merge, not only the one that governed.
#
# Exactly one merge of a PR carries publication_governing=True — the greatest
# merged_at — because pre-registration §2.2's ranking window has no job term:
# the published quarterly number designates one governing verdict per PULL
# REQUEST, not one per merge. A receipt shows every merge, each with its own
# governing verdict resolved at its own merged_at, so a bare boolean is not
# enough. A person reading the earlier merge after an incident sees a real
# verdict sitting beside a `false` and nothing at all connecting the two
# facts; the natural reading is that the verdict shown is the number that got
# published. It is not. These sentences are what say so.
PUBLICATION_GOVERNING_NOTE = (
    "This is the merge whose governing verdict the published quarterly "
    "statistic uses for this pull request."
)
NOT_PUBLICATION_GOVERNING_NOTE = (
    "This merge did not govern publication. The pull request merged again "
    "later, and the published quarterly statistic uses the verdict standing "
    "at that later merge. The verdict shown here is historical context — what "
    "was standing when THIS commit merged — and is not the published number."
)


class ReceiptRead(BaseModel):
    """What the reader was configured to see, as recorded on the verdict row.

    `recorded` is False whenever EITHER column is NULL, and that is the whole
    point of the field. Migration 008 started stamping these; every verdict
    scored before it legitimately has neither. A half-stamped pair describes
    no instrument either — a budget with no ordering does not say which part
    of the diff the model was given, an ordering with no budget does not say
    how much of it — so one boolean carries "these numbers mean something"
    and absence can never be read as a value.
    """

    diff_budget: int | None
    read_order: str | None
    recorded: bool


class ReceiptVerdict(BaseModel):
    """One verdict as evidence: what Doug said, and what instrument said it.

    `raw` is deliberately not here. It is the reader's full output kept for
    reprocessing, not a statement Doug made, and a receipt is the set of
    statements — see design-lock.md:15 on evidence versus judgment.
    """

    verdict_id: int
    scored_at: datetime
    tier: str
    source: str | None
    head_sha: str | None
    model: str | None
    # None means the row predates prompt-hash stamping on the worker path. It
    # is NOT a match against the frozen prompt and must never render as one —
    # same rule RunDetailResponse.prompt_hash carries.
    prompt_hash: str | None
    read: ReceiptRead
    score: float
    band: Band
    threshold: float
    risk_score: int | None
    rationale: str | None
    reasons: list[Reason]
    deviations: list[RunDeviation]
    intent_alignment: int | None
    intent_refs: list[str]
    coverage: RunCoverage | None


class ReceiptWindow(BaseModel):
    """One observation window of one merge.

    `status` is the JOB's (pending | running | done | failed) and `kind` is
    the ADJUDICATION's (revert | clean | censored). §6.2 keeps those two
    vocabularies apart on purpose, and this model does too: `kind` is None
    while the window is still open or the job never completed, which is not a
    clean result and is never substituted with one.
    """

    window_days: int
    status: str
    due_at: datetime
    kind: str | None
    observed_at: datetime | None
    source: str | None
    detail: dict | None
    # The pre-registration hash `settle_batch` stamped into `detail` at
    # adjudication time — read from THAT stamp, never from the environment.
    # None on a pending window: no adjudication has happened yet, so nothing
    # has been stamped. Render the receipt's top-level `preregistration`
    # block for what will govern it. A receipt must never substitute today's
    # env value here — that would claim a document governed a judgment it
    # never actually saw.
    prereg_hash: str | None


class ReceiptMerge(BaseModel):
    """One merge identity of this PR. A PR can carry several — uq_outcome_job
    includes merge_commit_sha, and a revert-and-reland is the ordinary case."""

    merge_commit_sha: str
    merged_at: datetime
    base_ref: str
    # NULL on merges recorded before migration 008, and on any payload that
    # carried no pull_request.head (a deleted fork branch) — see _record_merge.
    merged_head_sha: str | None
    governing_verdict: ReceiptVerdict | None
    publication_governing: bool
    publication_note: str
    adjudication: list[ReceiptWindow]


class ReceiptPreregistration(BaseModel):
    """The methodology document currently in force — not necessarily what
    governed any adjudicated window already on this receipt.

    Each ReceiptWindow carries its own `prereg_hash`, stamped at adjudication
    time, and that stamp is authoritative for that window forever. This block
    is for the windows that have none yet: a pending window has no stamp, and
    `in_force` names the document that WILL govern it once it closes.
    Reprinting this hash over an already-adjudicated window would manufacture
    a confident-but-derived claim about which document actually governed it —
    the one thing this design exists to prevent.

    `hash` is None and `in_force` is False whenever DOUG_PREREG_HASH is
    unset — local dev and the test suite never set it — rather than a crash
    or a fabricated value.
    """

    hash: str | None
    in_force: bool


class ReceiptResponse(BaseModel):
    """One PR's evidentiary record.

    `latest_verdict` and each merge's `governing_verdict` answer different
    questions and are never collapsed: the newest thing Doug has said about
    this PR, versus what was standing when a human chose to merge a
    particular commit. When they differ, work landed or the PR was rescored
    after the advice the merge actually happened on, and that gap is exactly
    what a reader of an incident review came for.
    """

    repo: str
    pr_number: int
    preregistration: ReceiptPreregistration
    latest_verdict: ReceiptVerdict | None
    merges: list[ReceiptMerge]


def _receipt_verdict(row: dict | None) -> ReceiptVerdict | None:
    """One store verdict dict as the wire model, honesty states rendered."""
    if row is None:
        return None
    budget, order = row["diff_budget"], row["read_order"]
    return ReceiptVerdict(
        verdict_id=row["id"],
        scored_at=row["scored_at"],
        tier=row["tier"],
        source=row["source"],
        head_sha=row["head_sha"],
        model=row["model"],
        prompt_hash=row["prompt_hash"],
        read=ReceiptRead(
            diff_budget=budget,
            read_order=order,
            # AND, not OR: see ReceiptRead's docstring — half a pair is not a
            # described read, and rendering it as one would let a consumer
            # quote a budget nothing was actually read under.
            recorded=budget is not None and order is not None,
        ),
        score=row["score"],
        band=Band(row["band"]),
        threshold=row["threshold"],
        risk_score=row["risk_score"],
        rationale=row["rationale"],
        reasons=[Reason(**r) for r in row["reasons"]],
        deviations=[RunDeviation(**d) for d in row["deviations"]],
        intent_alignment=row["intent_alignment"],
        intent_refs=row["intent_refs"],
        coverage=RunCoverage(**row["coverage"]) if row["coverage"] else None,
    )


def _receipt_response(repo: str, pr_number: int, data: dict) -> ReceiptResponse:
    """store.receipt()'s document as the response contract.

    Two things this layer adds rather than passes through. The publication
    note: store.receipt() sets the boolean; a boolean is a fact the ledger
    knows and a sentence is what makes it readable, so the words live here
    with the rest of the presentation. And the preregistration block: it
    reads the CURRENT deploy's DOUG_PREREG_HASH, which is what the top-level
    `in_force` value means and is why it is assembled here rather than in
    store.receipt() — that function reads the ledger, not the environment.
    """
    prereg_hash = os.environ.get("DOUG_PREREG_HASH")
    return ReceiptResponse(
        repo=repo,
        pr_number=pr_number,
        preregistration=ReceiptPreregistration(
            # Truthiness, not `is not None`: DOUG_PREREG_HASH="" must not
            # render as an in-force document with an empty hash. Not
            # reachable via gcp.sh (it runs `set -euo pipefail`), but a
            # local/manual deploy can still set an empty value.
            hash=prereg_hash, in_force=bool(prereg_hash)
        ),
        latest_verdict=_receipt_verdict(data["latest_verdict"]),
        merges=[
            ReceiptMerge(
                merge_commit_sha=m["merge_commit_sha"],
                merged_at=m["merged_at"],
                base_ref=m["base_ref"],
                merged_head_sha=m["merged_head_sha"],
                governing_verdict=_receipt_verdict(m["governing_verdict"]),
                publication_governing=m["publication_governing"],
                publication_note=(
                    PUBLICATION_GOVERNING_NOTE
                    if m["publication_governing"]
                    else NOT_PUBLICATION_GOVERNING_NOTE
                ),
                adjudication=[
                    # prereg_hash comes from the stamp inside `detail`, never
                    # from the environment — see ReceiptWindow's docstring.
                    ReceiptWindow(**a, prereg_hash=(a["detail"] or {}).get("prereg_hash"))
                    for a in m["adjudication"]
                ],
            )
            for m in data["merges"]
        ],
    )


@app.get("/v1/prs/{pr_number}/receipt")
def pr_receipt(
    pr_number: int,
    repo: str,
    x_doug_token: str = Header(""),
) -> ReceiptResponse:
    """One PR's evidentiary record.

    `repo` is required: a PR number alone is ambiguous across repositories.
    Scoping mirrors /v1/queue exactly — the operator token is unscoped, a
    dispensed token must carry receipt:read AND the repo must be inside its
    live-intersected selection.

    THE STATUS CODES ARE THE SECURITY CONTRACT, not error handling:

      503  no operator secret, or no ledger. Both are deployment faults and
           both are checked BEFORE the token, deliberately: without a ledger
           tenancy.resolve can read no key at all, so every dispensed token
           would come back 401 "bad token" and a customer would be told their
           credential is broken when what is broken is the deployment. A
           misconfiguration must not be reported as a credential failure.
      401  the token resolves to nothing, or resolves without receipt:read.
           Not 403 for the missing scope, matching /v1/queue: a scope a key
           does not hold is not a door it may knock on.
      404  everything else that refuses — a repo outside the caller's scope,
           a repo nobody has, a PR with no verdict and no merge.

    That last line is the one that matters. Out-of-scope and absent share a
    code AND a body, so a caller cannot tell "not yours" from "not there". A
    403 would confirm the repo exists; so would a distinct message; so would
    a 200 carrying an empty document, which is why the refusal is raised
    rather than returned. That would hand one customer a probe for another
    customer's private repository names — the same no-existence-leak rule
    /v1/queue's ?repo= filter, _operator_only and dispense_token all run.

    The two token paths resolve the repo through DIFFERENT functions and that
    asymmetry is the point: a tenant resolves via active_repos, which is
    scoped to their installation, and the id it returns is checked against
    the key's effective selection before any read happens. store.repo_id_for
    searches every installation and is unreachable from this branch.
    """
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")

    installation_id: int | None = None
    if not hmac.compare_digest(x_doug_token, expected):
        try:
            ctx = tenancy.resolve(x_doug_token)
        except tenancy.KeysNotConfigured as e:
            raise HTTPException(
                status_code=503, detail="token verification not configured"
            ) from e
        if ctx is None or "receipt:read" not in ctx.scopes:
            raise HTTPException(status_code=401, detail="bad token")
        installation_id = ctx.installation_id
        live = {full_name: rid for rid, full_name in store.active_repos(installation_id)}
        rid = live.get(repo)
        # The key's effective scope, in ids: its frozen selection (already
        # live-intersected by resolve) or, for 'all', everything live NOW.
        # installation_repos is the ONE source of truth — verdicts.repo and
        # full_name are display everywhere (MT4).
        effective = ctx.repo_ids if ctx.repo_ids is not None else frozenset(live.values())
        if rid is None or rid not in effective:
            raise _not_found()
        repo_id = rid
    else:
        resolved = store.repo_id_for(repo)
        if resolved is None:
            raise _not_found()
        installation_id, repo_id = resolved

    data = store.receipt(installation_id, repo_id, pr_number)
    if data is None:
        raise _not_found()
    return _receipt_response(repo, pr_number, data)


def _run_item(row: dict) -> RunSummaryItem:
    """One ledger row as a list item.

    `changed_files` travels separately from `coverage` because it is GitHub's
    own count on pr_meta, and it is the ONLY correct denominator for a
    coverage percentage — `len(files)` is the paginated list actually
    fetched and can be short on exactly the large PRs where coverage matters
    most. None here means the console renders "denominator unknown".

    `_with_url` assumes `pr_meta` is a dict — every /v1/queue row is filtered
    on that before it ever reaches _with_url. run_history carries every
    verdict, including rows saved with no pr_meta at all (save_review's
    `pr_meta` kwarg is optional), so a bare `_with_url(row)` call raises
    validating None into PRMetadata instead of degrading. _run_item instead
    synthesizes a title and URL from repo/pr_number and leaves changed_files
    None when pr_meta is missing.
    """
    pr_meta = row["pr_meta"]
    if isinstance(pr_meta, dict):
        meta = _with_url(row)
        title, url, changed_files = meta.title, meta.url, meta.changed_files
    else:
        title = f"PR #{row['pr_number']}"
        url = f"https://github.com/{row['repo']}/pull/{row['pr_number']}"
        changed_files = None
    return RunSummaryItem(
        verdict_id=row["id"],
        repo=row["repo"],
        installation_id=row["installation_id"],
        github_repo_id=row["github_repo_id"],
        pr_number=row["pr_number"],
        title=title,
        url=url,
        scored_at=row["scored_at"],
        tier=row["tier"],
        source=row["source"],
        score=row["score"],
        band=Band(row["band"]),
        threshold=row["threshold"],
        coverage=RunCoverage(**row["coverage"]) if row["coverage"] else None,
        changed_files=changed_files,
        finding_counts=RunFindingCounts(**row["finding_counts"]),
        job=RunJob(**row["job"]) if row["job"] else None,
        outcome_14=row["outcome_14"],
    )


@app.get("/v1/runs")
def runs(
    limit: int = 100,
    offset: int = 0,
    repo: str | None = None,
    installation_id: int | None = None,
    include_untenanted: bool = False,
    x_doug_token: str = Header(""),
) -> RunListResponse:
    """Verdict history for the operator console. Operator-only, permanently:
    this crosses every installation by design, which is exactly what no
    tenant credential may ever do."""
    _operator_only(x_doug_token)
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must not be negative")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    rows = store.run_history(
        limit=limit,
        offset=offset,
        repo=repo,
        installation_id=installation_id,
        include_untenanted=include_untenanted,
    )
    return RunListResponse(
        items=[_run_item(row) for row in rows], limit=limit, offset=offset
    )


@app.get("/v1/runs/{verdict_id}")
def run_detail(verdict_id: int, x_doug_token: str = Header("")) -> RunDetailResponse:
    """One run, end to end. Operator-only for the same reason /v1/runs is."""
    _operator_only(x_doug_token)
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    row = store.run_detail(verdict_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return RunDetailResponse(
        verdict_id=row["id"],
        repo=row["repo"],
        pr_number=row["pr_number"],
        installation_id=row["installation_id"],
        github_repo_id=row["github_repo_id"],
        # Guarded the same way _run_item guards it: run_detail's row, like
        # run_history's, can carry pr_meta=None (nullable column,
        # save_review's default), and _with_url assumes a dict. Nulled
        # rather than synthesized — see RunDetailResponse.pr's docstring.
        pr=_with_url(row) if isinstance(row["pr_meta"], dict) else None,
        scored_at=row["scored_at"],
        tier=row["tier"],
        prompt_hash=row["prompt_hash"],
        model=row["model"],
        source=row["source"],
        head_sha=row["head_sha"],
        risk_score=row["risk_score"],
        rationale=row["rationale"],
        score=row["score"],
        band=Band(row["band"]),
        threshold=row["threshold"],
        coverage=RunCoverage(**row["coverage"]) if row["coverage"] else None,
        reasons=[Reason(**r) for r in row["reasons"]],
        deviations=[RunDeviation(**d) for d in row["deviations"]],
        intent_alignment=row["intent_alignment"],
        intent_refs=row["intent_refs"],
        job=RunDetailJob(**row["job"]) if row["job"] else None,
        outcomes=[RunOutcome(**o) for o in row["outcomes"]],
        outcome_jobs=[RunOutcomeJob(**j) for j in row["outcome_jobs"]],
    )


@app.get("/v1/health")
def health(
    repo: str | None = None,
    installation_id: int | None = None,
    x_doug_token: str = Header(""),
) -> HealthResponse:
    """Both job lanes' health. Operator-only for the same reason /v1/runs is:
    it crosses every installation by design.

    The lane constants are passed in from the modules that enforce them, so
    the response reports what was actually measured with rather than a
    literal duplicated here.
    """
    _operator_only(x_doug_token)
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    data = store.job_health(
        review_lease_seconds=ingest.STALL_LEASE_SECONDS,
        review_max_attempts=ingest.MAX_ATTEMPTS,
        outcome_lease_seconds=outcome_queue.STALL_LEASE_SECONDS,
        outcome_max_attempts=outcome_queue.MAX_ATTEMPTS,
        repo=repo,
        installation_id=installation_id,
    )
    if data is None:
        raise HTTPException(status_code=503, detail="no ledger configured")
    return HealthResponse(**data)


# The stored statuses each lane's queue actually writes. 'stalled',
# 'retrying' and 'overdue' are deliberately absent: they are derived from
# started_at / attempts / due_at, and accepting them as a status would put
# the derivation somewhere /v1/health cannot see.
_REVIEW_STATUSES = frozenset({"pending", "running", "done", "failed", "superseded"})
_OUTCOME_STATUSES = frozenset({"pending", "running", "done", "failed"})

# Statuses that can never be unhealthy: nothing went wrong when a review job
# finishes ('done') or is superseded, and the same is true of a finished
# outcome job. status=<one of these> composed with the default view=unhealthy
# is empty by construction — store.job_rows' unhealthy_only clause excludes
# every row in this status regardless of what else is asked for — so it 422s
# instead of returning a silent empty list indistinguishable from "there are
# none".
_NEVER_UNHEALTHY = {
    "review": frozenset({"done", "superseded"}),
    "outcome": frozenset({"done"}),
}


@app.get("/v1/jobs")
def jobs(
    lane: str = "review",
    view: str = "unhealthy",
    status: str | None = None,
    repo: str | None = None,
    installation_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    x_doug_token: str = Header(""),
) -> JobListResponse:
    """Job rows for one lane. Operator-only for the same reason /v1/runs is.

    Read-only: nothing here requeues, retries or clears a job.
    """
    _operator_only(x_doug_token)
    if lane not in ("review", "outcome"):
        raise HTTPException(status_code=422, detail="lane must be review or outcome")
    if view not in ("unhealthy", "all"):
        raise HTTPException(status_code=422, detail="view must be unhealthy or all")
    allowed = _REVIEW_STATUSES if lane == "review" else _OUTCOME_STATUSES
    if status is not None and status not in allowed:
        raise HTTPException(
            status_code=422, detail=f"status must be one of {sorted(allowed)}"
        )
    if status is not None and view == "unhealthy" and status in _NEVER_UNHEALTHY[lane]:
        # Not silently forced to view=all: that would hide the caller's
        # contradiction instead of reporting it.
        raise HTTPException(
            status_code=422,
            detail=f"status={status} is never unhealthy; pass view=all",
        )
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must not be negative")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    lease = (
        ingest.STALL_LEASE_SECONDS
        if lane == "review"
        else outcome_queue.STALL_LEASE_SECONDS
    )
    rows = store.job_rows(
        lane=lane,
        lease_seconds=lease,
        unhealthy_only=view == "unhealthy",
        status=status,
        repo=repo,
        installation_id=installation_id,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        items=[JobItem(**row) for row in rows], limit=limit, offset=offset
    )


MAX_REPOS_PER_MINT = 20   # bounds PAT-side GitHub calls per request
MAX_MINTS_PER_DAY = 30    # per installation per UTC day; fail-open


class TokenRequest(BaseModel):
    selection: str | None = None          # "all" | "selected"
    owner: str | None = None              # required for selection="all"
    repos: list[str] | None = None        # required for selection="selected"
    repo: str | None = None               # legacy PR #48 body — one selected repo
    label: str | None = None
    expires_in_days: int = 0


class TokenResponse(BaseModel):
    token: str
    token_id: int
    installation_id: int
    selection: str
    repos: list[str]
    last4: str
    expires_at: datetime | None


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not found")


@app.post("/v1/installations/token")
def dispense_token(body: TokenRequest, x_github_token: str = Header("")) -> TokenResponse:
    """Mint a tenant API key, proving authority through GitHub.

    Deliberately public: the proof is the caller's own GitHub credential.
    PROOF MUST COVER THE SELECTION — org-admin (or the account owner, for a
    User install) for selection='all'; admin on EVERY named repo for
    selection='selected'. Every verification or validation failure is the
    same 404: a caller can never distinguish "exists but refused" from
    "does not exist".

    Mint APPENDS — it never rotates another key, so this endpoint is no
    longer a denial-of-service against the tenant's own integration (MT5).
    """
    if not x_github_token:
        raise HTTPException(status_code=401, detail="X-GitHub-Token required")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")

    # Normalize the legacy body before validating anything else.
    selection, repos, owner = body.selection, body.repos, body.owner
    if selection is None and body.repo is not None:
        selection, repos = "selected", [body.repo]

    if not (0 <= body.expires_in_days <= 366):
        raise _not_found()
    if body.label is not None and len(body.label) > 100:
        raise _not_found()

    if selection == "selected":
        if not repos or len(repos) > MAX_REPOS_PER_MINT:
            raise _not_found()
        if len({full.lower() for full in repos}) != len(repos):
            # GitHub treats repo names case-insensitively, so DrewJst/Doug
            # and drewjst/doug collide on the same junction row. Reject
            # before spending a single GitHub call proving either one —
            # letting a duplicate through would insert the key row and then
            # 500 on set_installation_token_repos' uq_installation_token_repo,
            # leaving that key row orphaned with zero repos attached.
            raise _not_found()
        parsed_repos: list[tuple[str, str]] = []
        for full in repos:
            repo_owner, _, name = full.partition("/")
            if not repo_owner or not name or "/" in name:
                raise _not_found()
            parsed_repos.append((repo_owner, name))
        installation_id = tenancy.verify_repos_admin(x_github_token, parsed_repos)
    elif selection == "all":
        if not owner or "/" in owner:
            raise _not_found()
        installation_id = tenancy.verify_org_admin(x_github_token, owner)
    else:
        raise _not_found()
    if installation_id is None:
        raise _not_found()

    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    minted_today = store.count_installation_tokens_minted_since(installation_id, midnight)
    if minted_today is not None and minted_today >= MAX_MINTS_PER_DAY:
        # None means "could not count" and ALLOWS — the cap is fail-open.
        raise _not_found()

    minted_by = tenancy.caller_login(x_github_token)
    if minted_by is None:
        raise _not_found()

    repo_ids: list[int] = []
    if selection == "selected":
        # Lowercased on both sides: GitHub logins and repo names are
        # case-insensitive, so a GitHub-proved admin must not 404 on a
        # ledger entry that merely differs in case.
        by_name = {
            full_name.lower(): rid for rid, full_name in store.active_repos(installation_id)
        }
        # The ledger may lag GitHub (MT0 taught how badly); GitHub already
        # proved these repos belong to this installation, so a name the
        # ledger has not heard of yet refuses the mint rather than minting
        # a key whose junction rows point at nothing.
        try:
            repo_ids = [by_name[full.lower()] for full in repos]
        except KeyError as exc:
            raise _not_found() from exc

    try:
        minted = tenancy.mint_key(
            installation_id,
            repo_selection=selection,
            repo_ids=repo_ids,
            label=body.label,
            expires_in_days=body.expires_in_days,
            minted_by=minted_by,
        )
    except tenancy.KeysNotConfigured as exc:
        raise HTTPException(status_code=503, detail="token minting not configured") from exc
    if minted is None:
        raise _not_found()
    # The token rides in the response ONCE. This log line is the only other
    # trace of the mint and carries the id, never the credential.
    print(
        f"doug: minted key id={minted.token_id} installation={installation_id} "
        f"selection={selection} last4={minted.last4} by={minted_by}",
        file=sys.stderr,
    )
    return TokenResponse(
        token=minted.token,
        token_id=minted.token_id,
        installation_id=installation_id,
        selection=selection,
        repos=repos if selection == "selected" else [],
        last4=minted.last4,
        expires_at=minted.expires_at,
    )


@app.get("/v1/installations/tokens")
def list_tokens(owner: str = "", x_github_token: str = Header("")) -> dict:
    """Masked key inventory. Org-admin (or account-owner) proof only — the
    list names every key's lookup/label/selection, which is exactly the map
    an attacker holding one repo's admin would want. X-Doug-Token is not
    accepted here or on revoke: keys cannot manage keys."""
    if not x_github_token:
        raise HTTPException(status_code=401, detail="X-GitHub-Token required")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    if not owner or "/" in owner:
        raise _not_found()
    installation_id = tenancy.verify_org_admin(x_github_token, owner)
    if installation_id is None:
        raise _not_found()
    rows = store.list_installation_tokens(installation_id)
    for row in rows:
        if row["repo_selection"] == "selected":
            row["repo_ids"] = sorted(store.installation_token_repo_ids(row["id"]))
    return {"tokens": jsonable_encoder(rows)}


@app.delete("/v1/installations/token/{token_id}")
def revoke_token(
    token_id: int,
    owner: str = "",
    repos: str = "",
    x_github_token: str = Header(""),
) -> dict:
    """Soft-revoke one key. Proof must cover the key's selection, mirroring
    mint: org-admin proof revokes anything; repo-admin proof revokes a
    'selected' key iff the proven repos cover every repo the key names."""
    if not x_github_token:
        raise HTTPException(status_code=401, detail="X-GitHub-Token required")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    if owner:
        # A present owner is authoritative. Malformed input refuses here
        # rather than falling through to the repos proof — otherwise
        # precedence would flip on a typo, and a mistyped org name would
        # hand the decision to whatever the repos param happens to prove.
        if "/" in owner:
            raise _not_found()
        installation_id = tenancy.verify_org_admin(x_github_token, owner)
        if installation_id is None or not store.revoke_installation_token(
            token_id, installation_id
        ):
            raise _not_found()
        return {"revoked": True}
    if repos:
        names = [r for r in repos.split(",") if r]
        if not names or len(names) > MAX_REPOS_PER_MINT:
            raise _not_found()
        parsed_repos = []
        for full in names:
            repo_owner, _, name = full.partition("/")
            if not repo_owner or not name or "/" in name:
                raise _not_found()
            parsed_repos.append((repo_owner, name))
        installation_id = tenancy.verify_repos_admin(x_github_token, parsed_repos)
        if installation_id is None:
            raise _not_found()
        # Lowercased on both sides, mirroring dispense_token's by_name map:
        # GitHub repo names are case-insensitive, so a proven owner/Repo must
        # not 404 against a ledger entry that merely differs in case.
        by_name = {
            full_name.lower(): rid for rid, full_name in store.active_repos(installation_id)
        }
        try:
            proven_ids = {by_name[full.lower()] for full in names}
        except KeyError as exc:
            raise _not_found() from exc
        key_repo_ids = store.installation_token_repo_ids(token_id)
        # Repo-admin proof reaches ONLY 'selected' keys it fully covers. An
        # 'all' key has no junction rows → empty set → refused here, which
        # is exactly the point: killing the org key takes org-admin proof.
        if not key_repo_ids or not key_repo_ids <= proven_ids:
            raise _not_found()
        if not store.revoke_installation_token(token_id, installation_id):
            raise _not_found()
        return {"revoked": True}
    raise _not_found()


class BindRequest(BaseModel):
    """The whole request body. ONE field, and that is the security property.

    An earlier design took a `workos_org_id` from the caller, which made org
    squatting possible: post a victim's org id against your own installation
    before they bind, and Task 1's UNIQUE index blocks their real bind
    permanently. The organization is now derived from the installation id
    (workos_client.external_id_for), so the attack has nothing to say rather
    than being defended against. Anything else a client sends is ignored.
    """

    installation_id: int


class CompleteInstallFlowRequest(BaseModel):
    """Only the installation and opaque flow proof cross the web/API seam.

    `Any` is deliberate here. Pydantic's 422 body can include rejected input;
    validating manually keeps an invalid flow token out of an echoed error.
    """

    installation_id: Any = None
    flow_token: Any = None


def _session_subject(authorization: str) -> str:
    try:
        claims = session_auth.verify_session_claims(authorization)
    except session_auth.SessionAuthNotConfigured as exc:
        raise HTTPException(status_code=503, detail="session auth not configured") from exc
    if claims is None:
        raise HTTPException(status_code=401, detail="bad session")
    workos_user_id = claims.get("sub")
    if not isinstance(workos_user_id, str) or not workos_user_id:
        raise HTTPException(status_code=401, detail="bad session")
    return workos_user_id


def _prove_installer(installation_id: int, workos_user_id: str) -> tuple[dict, str]:
    """Task 5's authority proof, shared by both bind entrances."""
    row = store.installation_bind_row(installation_id)
    if row is None or row["installed_by_github_user_id"] is None:
        raise _not_found()
    try:
        idp_id = workos_client.github_user_id_for(workos_user_id)
    except workos_client.WorkOSNotConfigured as exc:
        raise HTTPException(status_code=503, detail="workos not configured") from exc
    except workos_client.WorkOSError as exc:
        raise HTTPException(status_code=503, detail="workos unavailable") from exc
    if idp_id is None:
        raise _not_found()
    claimed = str(idp_id).strip()
    if not claimed.isdigit():
        print(
            f"doug: bind refused — WorkOS idp_id is not a numeric GitHub user id. "
            f"Received {claimed!r} for installation {installation_id}. If this is the "
            f"real GitHub identity format, the comparison in api._prove_installer "
            f"needs updating; nothing binds until it is.",
            file=sys.stderr,
        )
        raise _not_found()
    if claimed != str(row["installed_by_github_user_id"]).strip():
        raise _not_found()
    return row, claimed


def _current_proved_row(installation_id: int, row: dict, claimed: str) -> dict:
    current = store.installation_bind_row(installation_id) or row
    if claimed != str(current["installed_by_github_user_id"] or "").strip():
        raise _not_found()
    return current


def _ensure_workos_binding(
    installation_id: int, workos_user_id: str, current: dict
) -> str:
    external_id = workos_client.external_id_for(installation_id)
    bound = current["workos_org_id"]
    try:
        if bound is not None:
            organization_id = workos_client.find_organization(external_id)
            if organization_id != bound:
                raise HTTPException(
                    status_code=409,
                    detail="installation is bound to another organization",
                )
        else:
            organization_id = workos_client.ensure_organization(
                name=current["account_login"] or external_id, external_id=external_id
            )
        workos_client.ensure_membership(workos_user_id, organization_id)
    except workos_client.WorkOSNotConfigured as exc:
        raise HTTPException(status_code=503, detail="workos not configured") from exc
    except workos_client.WorkOSError as exc:
        raise HTTPException(status_code=503, detail="workos unavailable") from exc
    return organization_id


@app.post("/v1/installations/bind", status_code=204)
def bind_installation(body: BindRequest, authorization: str = Header("")) -> Response:
    """Bind a GitHub App installation to a WorkOS organization.

    THE PROOF IS AUTHORITY, NOT VISIBILITY, and the difference is the whole
    endpoint. Setup-URL parameters are attacker-supplied and no GitHub
    redirect need ever occur, so an attacker holding `:read` on one repo sees
    a victim's installation_id in their own GET /user/installations and can
    post it here. A membership check would PASS — the installation genuinely
    is in their list — and hand them the tenant.

    What is required instead is that the signed-in user's GitHub id equals
    `installations.installed_by_github_user_id`, the `sender.id` of the
    `installation.created` webhook (Task 1). That proves something narrower
    and more relevant than org-admin — *you are the person who installed Doug
    here* — with no new App permission and no re-acceptance by existing
    tenants. Org-admin was rejected on evidence, not preference:
    tenancy.verify_org_admin's membership hop needs organization Members:read
    for a user-to-server token, which Doug does not hold and cannot add
    without forcing every installation to re-accept permissions.

    ITS LIMIT IS REAL AND STATED HERE RATHER THAN PAPERED OVER: it only works
    for installations created after Task 1 shipped. Rows predating it carry
    NULL — including the operator's own 150424894, populated by webhook
    redelivery under MT0 — and they CANNOT self-bind. NULL never compares
    equal to anything here; a fail-open would let any signed-in stranger
    claim every legacy tenant at once. Those need a deliberate operator bind
    or a one-off backfill.

    THE ORDER BELOW IS LOAD-BEARING, same posture as tenancy.verify_admin's:
    the session, then the ledger row (free, local), then the identity hop
    (one WorkOS read), then the comparison — and only after all of that does
    anything get CREATED. A caller who proves nothing leaves no organization,
    no membership, and no row behind.

    Every authority failure is the same 404, mirroring dispense_token: a
    caller cannot tell "exists but refused" from "does not exist". The two
    exceptions are deployment faults (503, named, per api.py:391's idiom) and
    a live installation already bound elsewhere (409) — which is only ever
    seen by someone who has ALREADY proved they installed it.

    `installations.state` is deliberately not gated: binding a suspended or
    deleted installation grants nothing, because tenancy.live_scope refuses
    every read against one.
    """
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    workos_user_id = _session_subject(authorization)
    installation_id = body.installation_id
    row, claimed = _prove_installer(installation_id, workos_user_id)
    with store.installation_bind_lock(installation_id):
        current = _current_proved_row(installation_id, row, claimed)
        organization_id = _ensure_workos_binding(
            installation_id, workos_user_id, current
        )
        written = store.bind_installation_org(installation_id, organization_id)
        if written != organization_id:
            raise HTTPException(
                status_code=409, detail="installation is bound to another organization"
            )
    print(
        f"doug: bound installation {installation_id} to organization {organization_id}",
        file=sys.stderr,
    )
    return Response(status_code=204)


@app.post("/v1/installations/bind/complete", status_code=204)
def complete_install_flow(
    body: CompleteInstallFlowRequest, authorization: str = Header("")
) -> Response:
    """Spend a signed installation flow after independently proving authority."""
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    workos_user_id = _session_subject(authorization)
    installation_id = body.installation_id
    token = body.flow_token
    if (
        isinstance(installation_id, bool)
        or not isinstance(installation_id, int)
        or installation_id <= 0
        or not isinstance(token, str)
        or not token
    ):
        raise _not_found()
    try:
        flow = install_flow.verify_install_flow(
            token,
            expected_subject=workos_user_id,
            expected_installation_id=installation_id,
        )
    except install_flow.InstallFlowError as exc:
        raise _not_found() from exc
    nonce_digest = hashlib.sha256(flow.nonce).hexdigest()

    with store.installation_bind_lock(installation_id):
        consumed = store.install_flow_consumption(nonce_digest)
        if consumed is not None:
            if (
                consumed["workos_user_id"] == workos_user_id
                and consumed["installation_id"] == installation_id
            ):
                return Response(status_code=204)
            raise _not_found()

        row, claimed = _prove_installer(installation_id, workos_user_id)
        current = _current_proved_row(installation_id, row, claimed)
        organization_id = _ensure_workos_binding(
            installation_id, workos_user_id, current
        )
        result = store.consume_install_flow_and_bind(
            nonce_digest,
            workos_user_id,
            installation_id,
            organization_id,
        )
        if result == "mismatch":
            raise _not_found()
        if result == "conflict":
            raise HTTPException(
                status_code=409, detail="installation is bound to another organization"
            )
    print(
        f"doug: completed install flow for installation {installation_id} "
        f"and organization {organization_id}",
        file=sys.stderr,
    )
    return Response(status_code=204)


class EntitlementsRequest(BaseModel):
    """The provider that authenticated this sign-in, and the token it issued.

    NOTHING HERE NAMES A USER, and that is the security property — the same
    one BindRequest has for organization ids. The scope is written for the
    JWT's `sub`; a body-supplied user id would let any signed-in caller
    overwrite anyone else's entitlements, and since a scope is what a later
    read is checked against, that is writing yourself into their tenant.
    Extra fields are ignored (pydantic's default), so a body carrying one
    changes nothing.

    NEITHER FIELD IS REQUIRED, which is not laxity: it keeps the token out of
    a 422. FastAPI's validation error carries the offending input, and for a
    MISSING field pydantic reports the WHOLE BODY as that input — measured
    2026-08-10 — so a required `provider` would echo the token straight back
    to the caller in the error body. With defaults, no 'missing' error can
    fire, and the handler refuses an empty pair itself with a detail string
    built from nothing the caller sent.
    """

    provider: str = ""
    token: str = ""


@app.post("/v1/sessions/entitlements", status_code=204)
def record_entitlements(
    body: EntitlementsRequest, authorization: str = Header("")
) -> Response:
    """Derive what this signed-in user may see, and store the conclusion.

    WHY THIS ENDPOINT EXISTS AT ALL. `authkit-nextjs` hands the provider's
    `oauthTokens` to `handleAuth`'s `onSuccess` and nowhere else — `withAuth()`
    does not return them and the session does not carry them. The dashboard
    runs on a LATER request, when the GitHub token is gone. So the browser
    posts it here once, at sign-in, and what survives the request is the
    derived scope: `installation_id` plus explicit repo ids. THE TOKEN IS
    NEVER STORED, LOGGED, RETURNED, OR PLACED IN AN EXCEPTION MESSAGE
    (entitlements.py's property 2, tested end to end).

    AUTHENTICATED WITH verify_session_claims, NOT resolve_session, and the
    difference is what makes this reachable. resolve_session fails closed
    without an `org_id` claim, which a first-time user does not have — an
    organization is created when they bind, and binding is not what this is.
    The weaker check proves WHO is signed in, which is exactly and only what
    is needed to write a row keyed on them.

    A DERIVATION IS THE WHOLE ANSWER, NOT A DELTA. store.replace_session_
    entitlements deletes what was there first, so a scope can shrink when a
    tenant removes Doug from a repo. That is also why an upstream failure
    must never reach the write: an empty derivation is a legitimate answer
    that ERASES rows, so a rejected token (401 — the caller signs in again)
    and an outage (503 — the caller tries later) both raise past it rather
    than being read as "entitled to nothing".

    ITS LIMIT, stated rather than papered over: replacement is per USER, not
    per provider, because these rows carry no provider column. GitHub is the
    only source of tenants today, so nothing can be lost; the first time a
    second SOURCE of entitlement exists, this needs a provider column or one
    provider's derivation will erase another's.

    Stored scope is a claim, never authority. tenancy.live_scope intersects
    it against the live ledger on every read, so a suspended installation or
    a removed repo is refused immediately regardless of what is written here;
    entitlements.TTL bounds the rest.
    """
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")

    try:
        claims = session_auth.verify_session_claims(authorization)
    except session_auth.SessionAuthNotConfigured as exc:
        raise HTTPException(status_code=503, detail="session auth not configured") from exc
    if claims is None:
        raise HTTPException(status_code=401, detail="bad session")
    workos_user_id = claims.get("sub")
    if not isinstance(workos_user_id, str) or not workos_user_id:
        raise HTTPException(status_code=401, detail="bad session")

    if not body.provider or not body.token:
        raise HTTPException(status_code=400, detail="provider and token are required")

    try:
        tenants = entitlements.derive(body.provider, body.token)
    except entitlements.EntitlementsNotConfigured as exc:
        raise HTTPException(status_code=503, detail="github app not configured") from exc
    except entitlements.ProviderTokenRejected as exc:
        # Checked before ProviderError — it is a subclass, and the caller can
        # act on this one: sign in again, rather than try later.
        raise HTTPException(status_code=401, detail="provider token rejected") from exc
    except entitlements.ProviderError as exc:
        raise HTTPException(status_code=503, detail="provider unavailable") from exc

    store.replace_session_entitlements(workos_user_id, tenants)
    print(
        f"doug: recorded entitlements for {workos_user_id}: {len(tenants)} installation(s), "
        f"{sum(len(t.repo_ids) for t in tenants)} repo(s)",
        file=sys.stderr,
    )
    return Response(status_code=204)


class PatternRow(BaseModel):
    pattern: str
    prs: int
    defects: int
    precision: float
    ci_low: float
    ci_high: float
    lift: float
    clears_base: bool


class PatternsResponse(BaseModel):
    prs: int
    defects: int
    base_rate: float
    patterns_seen: int  # before the min_prs cut — the long tail's size
    rows: list[PatternRow]
    caveat: str


PATTERNS_CAVEAT = (
    "precision is within these ledger rows only. The seed corpus is an "
    "enriched sample (all known defects plus a clean subsample), so its base "
    "rate is far above any repo's true defect rate — compare lift, not "
    "precision. clears_base is uncorrected for multiplicity."
)


@app.get("/v1/patterns")
def patterns_precision(
    repo: str | None = None,
    min_prs: int = 5,
    x_doug_token: str = Header(""),
) -> PatternsResponse:
    """Per-pattern precision from the findings x outcomes join.

    Token-gated on the operator's shared secret: this is the
    unpublished half of the evidence base, and the caveat travels in the
    response body so a number cannot be lifted out of it by accident.
    """
    _operator_only(x_doug_token)
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")

    is_defect, carriers = precision.fold(store.pattern_join(repo=repo))
    rows, base = precision.corpus_table(is_defect, carriers, min_prs=min_prs)
    return PatternsResponse(
        prs=len(is_defect),
        defects=sum(is_defect.values()),
        base_rate=base,
        patterns_seen=len(carriers),
        rows=[PatternRow(**r) for r in rows],
        caveat=PATTERNS_CAVEAT,
    )


# Actions that mean "this PR's head changed, or is newly eligible". Anything
# else — labeled, edited, review_requested — is not a new diff and must not
# buy a read. 'closed' is handled too, but deliberately not from here: it
# starts the outcome clock on its own branch and never enqueues a review.
PR_ACTIONS = frozenset({"opened", "synchronize", "reopened", "ready_for_review"})
INSTALLATION_STATES = {
    "created": "active",
    "deleted": "deleted",
    "suspend": "suspended",
    "unsuspend": "active",
}


def _obj(raw) -> dict:
    """One of a payload's nested objects, or {} when it is absent, null, or
    not an object at all.

    Every handler below reaches through two or three of these. GitHub sends
    them today, but a delivery that arrives truncated, reshaped by a payload
    version bump, or replayed from an older one must not be one lookup away
    from a 500 — a 500 is what GitHub redelivers, and the redelivery has the
    same shape, so a single bad body becomes a loop that never ends and
    never reviews anything. Missing facts belong to the guard each handler
    already has, not to the lookup in front of it.
    """
    return raw if isinstance(raw, dict) else {}


def _text(raw, column=None) -> str | None:
    """A usable string from a payload, or None.

    None when the field is absent, null, empty, or not a string — the
    guards below all ask "is this fact usable", and None is the single
    answer they need for every way it can fail to be.

    With `column`, also None when the value is too long for that VARCHAR.
    Postgres answers an over-long INSERT with StringDataRightTruncation,
    which is a 500 and therefore the same redelivery loop the shape guards
    prevent; sqlite stores the long value happily, so a green local suite is
    not evidence about this. Too long is unusable rather than truncated: a
    cut SHA names a different commit and a cut full_name names a different
    repo.
    """
    if not isinstance(raw, str) or not raw:
        return None
    if column is not None and len(raw) > column.type.length:
        return None
    return raw


def _repo_list(raw) -> list[tuple[int, str]]:
    """The (id, full_name) pairs a repositories array actually carries.

    Entries that are not objects, carry a non-int id, or carry an unusable
    full_name are dropped — one bad entry costs itself, not the repos beside
    it, because the installation genuinely covers those and active_repos is
    what the healing path reads. github_repo_id is the column every job and
    verdict joins on and full_name is what reconcile splits into owner/name
    to call the API with, so a pair built from a default would be a
    tenancy record about a repo nobody named.
    """
    out = []
    for entry in raw if isinstance(raw, list) else []:
        repo_id = _obj(entry).get("id")
        full_name = _text(_obj(entry).get("full_name"), store.installation_repos.c.full_name)
        if isinstance(repo_id, int) and full_name:
            out.append((repo_id, full_name))
    return out


def _record_installation(payload: dict, action: str) -> None:
    inst = payload["installation"]
    account = _obj(inst.get("account"))
    # Only `created` names an installer — suspend/unsuspend/deleted name
    # whoever performed THAT action, which is a different fact and must not
    # overwrite it (store.upsert_installation already refuses to write a
    # None over an existing value, but this keeps a *wrong* id from ever
    # being offered in the first place). A missing or non-int sender
    # (older redeliveries, synthetic payloads) is recorded as None rather
    # than raised: an installation row is more important than who's on it.
    sender_id = _obj(payload.get("sender")).get("id")
    store.upsert_installation(
        inst["id"],
        _text(account.get("login"), store.installations.c.account_login) or "",
        _text(account.get("type"), store.installations.c.account_type) or "",
        INSTALLATION_STATES[action],
        installed_by_github_user_id=(
            sender_id if action == "created" and isinstance(sender_id, int) else None
        ),
    )
    if action == "created":
        # Marks what this installation covers and never un-marks. `created`
        # is replayable — the Redeliver button in the App's Advanced tab,
        # GitHub retrying a failed delivery, two deliveries arriving out of
        # order — and it carries the repo list as it was when GitHub
        # generated the event, not as it is now. Treating it as
        # authoritative at processing time flips back to 'removed' every
        # repo granted since; active_repos is what reconcile reads, so that
        # repo's backlog is then never healed again and no later event
        # restores it. Nothing surfaces that, because live pull_request
        # deliveries for it keep enqueueing.
        #
        # The opposite mistake a replay can now make is re-marking a repo
        # that was removed since. That costs one reconcile call that 403s on
        # a repo the installation token does not cover, logged and skipped —
        # noise rather than silence, and no spend. Uninstall-then-reinstall
        # still converges on the smaller set, because `deleted` below
        # cleared coverage first.
        store.set_installation_repos(
            inst["id"], _repo_list(payload.get("repositories")), replace=False
        )
    elif action == "deleted":
        # The uninstall is what ends coverage, and now the only thing that
        # does: an empty authoritative list marks every repo on this
        # installation 'removed'. Rows are not deleted — a verdict written
        # while the repo was installed still has to resolve to the repo it
        # describes — so a reinstall's `created` marks the newly granted
        # subset active again and the repos left out of it stay removed.
        store.set_installation_repos(inst["id"], [], replace=True)
        # The live state check already ends access; this stamp is the audit
        # trail AND the reinstall guard — 'created' flips state back to
        # active, and without revoked_at every pre-uninstall key would
        # quietly resurrect with it.
        n = store.revoke_all_installation_tokens(inst["id"])
        if n:
            msg = f"doug: uninstall revoked {n} key(s) for installation {inst['id']}"
            print(msg, file=sys.stderr)


def _merge_installation_repos(payload: dict) -> None:
    inst_id = payload["installation"]["id"]
    for key, state in (
        ("repositories_added", "active"),
        ("repositories_removed", "removed"),
    ):
        repos = _repo_list(payload.get(key))
        if repos:
            # A removal marks state and never deletes: verdicts already
            # written must still resolve to the repo they describe.
            store.set_installation_repos(inst_id, repos, replace=False, state=state)


def _reconcile_then_drain(installation_id: int) -> None:
    """Heal the backlog, then actually review it.

    reconcile_installation only enqueues. Without the drain chained behind
    it, everything a new installation just discovered sits pending until
    some unrelated delivery happens to kick one — which on a quiet repo is
    the difference between "reviews appear within seconds of installing"
    and "reviews appear whenever someone next opens a PR". The cutover
    checklist in Task 10 asserts the first.

    Asks for the sweep's terms explicitly. This lists every open PR of the
    installation whether or not anything about them changed, and
    installation.created is replayable — the Redeliver button in the App's
    Advanced tab, or GitHub retrying a delivery, both of which
    _record_installation above already treats as ordinary. On the live terms
    each replay would revive every 'failed' row at once and buy up to
    max_attempts model reads again for a PR that already burned them, so the
    repetition FAILED_REVIVE_COOLOFF_SECONDS brakes is this caller's as much
    as the startup sweep's. What a held-back PR costs instead is a wait, and
    reconcile_installation logs each one it is deliberately waiting on
    (ingest.cooloff_hold_remaining) so an operator who redelivered after
    fixing credentials can see why nothing happened.
    """
    worker.reconcile_installation(installation_id, trigger="reconcile")
    worker.drain()


def _enqueue_pull_request(payload: dict) -> int | None:
    """Gate then enqueue. None means deliberately skipped or a duplicate."""
    pr = _obj(payload.get("pull_request"))
    if pr.get("draft") is not False:
        # Work in progress nobody has asked for review on. ready_for_review
        # is the event that admits it. Only an explicit draft=False
        # proceeds: an absent or non-boolean draft is an unknown state and
        # the safe direction to be wrong in is "skip" — which is also the
        # answer worker._skip_reason gives the same PR, and its docstring
        # calls the two one gate. Reading a missing key as "not a draft"
        # made them disagree.
        return None
    base_ref = _obj(pr.get("base"))
    base = _obj(base_ref.get("repo"))
    head = _obj(pr.get("head"))
    base_id = base.get("id")
    # head.repo is null when the fork was deleted, which fails this the same
    # way a fork does — correctly.
    head_id = _obj(head.get("repo")).get("id")
    if not isinstance(base_id, int) or not isinstance(head_id, int) or head_id != base_id:
        # Fork PRs never enqueue: the raw diff enters the prompt
        # (reader._user_text), so an outside contributor opening PRs against
        # a public repo could otherwise drive this account's model spend at
        # will. Ids that are not both integers are a fork here rather than
        # something to compare — two absent ids compare equal, so an
        # unguarded `!=` passes a payload that names no repo at all straight
        # into the queue, where github_repo_id is NOT NULL and the insert
        # 500s. Same choice worker._skip_reason makes, for the same reason:
        # the safe direction to be wrong in is skip.
        return None
    number = pr.get("number")
    full_name = _text(base.get("full_name"), store.review_jobs.c.repo_full_name)
    base_sha = _text(base_ref.get("sha"), store.review_jobs.c.base_sha)
    head_sha = _text(head.get("sha"), store.review_jobs.c.head_sha)
    if not isinstance(number, int) or not full_name or not base_sha or not head_sha:
        # Signed, past both gates, and still missing something the job row
        # IS: which PR, which repo by name, which commit. Logged and 202'd
        # rather than raised, for the reason _record_merge gives below.
        print(
            f"doug: pull_request #{pr.get('number')} carried no usable "
            "number/base.repo.full_name/base.sha/head.sha; not enqueued",
            file=sys.stderr,
        )
        return None
    return ingest.enqueue(
        payload["installation"]["id"],
        base_id,
        full_name,
        number,
        head_sha,
        base_sha=base_sha,
    )


def _payload_timestamp(raw) -> datetime | None:
    """One of GitHub's ISO-8601 timestamps, or None if it is unusable.

    fromisoformat has accepted the trailing "Z" since 3.11. A naive result
    is read as UTC, which is what GitHub sends and what every DateTime
    column in the ledger stores.
    """
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _record_merge(payload: dict) -> None:
    """Start the outcome-observation window on a merge, and nothing else.

    A merge must never buy a model read: there is no new diff, and this is
    the one webhook branch whose whole job is to note that the clock has
    started. The adjudicator picks the row up once due_at passes.
    """
    pr = _obj(payload.get("pull_request"))
    if not pr.get("merged"):
        # Closed without merging. Nothing shipped, so there is no outcome to
        # observe — and a row here would put a PR that never landed into the
        # denominator of a claim about shipped code.
        return
    base = _obj(pr.get("base"))
    merged_at = _payload_timestamp(pr.get("merged_at"))
    merge_sha = _text(pr.get("merge_commit_sha"), store.outcome_jobs.c.merge_commit_sha)
    base_ref = _text(base.get("ref"), store.outcome_jobs.c.base_ref)
    number = pr.get("number")
    repo_id = _obj(base.get("repo")).get("id")
    if (
        merged_at is None
        or not merge_sha
        or not base_ref
        or not isinstance(number, int)
        or not isinstance(repo_id, int)
    ):
        # Signed, and a merge, but missing one of the five facts the row is
        # built from: when it shipped, what shipped, where, which PR, and
        # whose repo. Logged and 202'd rather than raised — a 500 is a
        # redelivery loop over a body that will never carry them, and a
        # half-row is worse than a missing one here: base_ref is what the
        # adjudicator censors on, and github_repo_id is the tenancy this
        # merge is counted under in a published denominator.
        print(
            f"doug: merged PR #{pr.get('number')} carried no usable "
            "merged_at/merge_commit_sha/base.ref/number/base.repo.id; "
            "outcome clock not started",
            file=sys.stderr,
        )
        return
    # Pre-registration §11 item 7, forward only. Deliberately read AFTER the
    # five-fact guard above and left out of it: merged_head_sha drives
    # neither censoring (base_ref) nor tenancy (github_repo_id), the two
    # things that guard protects. A payload missing pull_request.head — a
    # deleted fork branch, an older payload shape — must still start both
    # clocks; only this one column goes in NULL.
    merged_head_sha = _text(_obj(pr.get("head")).get("sha"), store.outcome_jobs.c.merged_head_sha)
    store.enqueue_outcome_jobs(
        payload["installation"]["id"],
        repo_id,
        number,
        merge_sha,
        merged_at,
        base_ref,
        merged_head_sha=merged_head_sha,
    )


# A submitted review that takes a position, mapped onto Doug's own bands.
# Keyed lowercase because that is the spelling the lookup is done in — see
# _record_external_review — not because it is the spelling GitHub sends.
REVIEW_BANDS = {"approved": Band.CLEARED, "changes_requested": Band.FLAGGED}

# The review states GitHub can carry that take no position on whether the
# change should land: a note, a retraction, a review not yet submitted.
# There is nothing to grade against an outcome, so there is no row.
#
# Written out rather than left as an absence from REVIEW_BANDS, and that is
# the whole point of it: skipping these is a decision, skipping a state
# nobody has ever seen is not, and only the second one logs. `commented` is
# by far the most common review state on GitHub and `dismissed` is routine,
# so logging them would fire on the normal case — and a line that fires on
# the normal case is one an operator learns to scroll past, which costs the
# signal the unrecognized-state line exists to carry.
#
# Whether `dismissed` should instead be banded is a live design question and
# is deliberately not settled here; this records today's answer.
REVIEW_STATES_WITHOUT_A_STANCE = frozenset({"commented", "dismissed", "pending"})


def _record_external_review(payload: dict) -> None:
    """Ingest a third-party review as a dated stance in Doug's ledger.

    The neutral-grader lane. Nothing is spent here: no model call, no
    metering, no check run, and deliberately no fork gate — that gate exists
    because a fork's raw diff would enter the prompt, and nothing here reads
    a diff. Bot reviewers are ingested like anyone else, because grading bot
    reviewers is the point of the lane.

    The state is matched lowercased. GitHub spells one state two ways —
    this webhook delivers `approved`, the REST reviews endpoint returns
    `APPROVED` for that same review, which is the spelling
    review._review_state matches — and nothing in a payload says which
    vocabulary produced it. Matching the delivered casing raw put a whole
    grading lane on that assumption, and got it wrong in the quietest
    possible way: an unmatched state writes no row and still 202s, so the
    lane would ingest nothing indefinitely with no error to notice it by.
    Lowercasing cannot band a state wrongly — no two GitHub review states
    differ only in case — so it strictly removes that failure without
    admitting anything new.
    """
    review_ = _obj(payload.get("review"))
    pr = _obj(payload.get("pull_request"))
    state = review_.get("state")
    normalized = state.lower() if isinstance(state, str) else None
    band = REVIEW_BANDS.get(normalized)
    if band is None:
        if normalized not in REVIEW_STATES_WITHOUT_A_STANCE:
            # Neither banded nor deliberately skipped: GitHub added a review
            # state, or this payload is not the shape it claims (a `review`
            # that is not an object lands here too, as a None state). No row
            # either way — a stance that cannot be read is not a gradable
            # claim — but this is the only drop on this path that nobody
            # chose, so it is the only one that gets to be loud. !r because
            # the state is a remote string and a bare newline in it would
            # otherwise forge a second log line.
            print(
                f"doug: review on PR #{pr.get('number')} carried unrecognized "
                f"state {state!r}; not ingested",
                file=sys.stderr,
            )
        return
    base_repo = _obj(_obj(pr.get("base")).get("repo"))
    scored_at = _payload_timestamp(review_.get("submitted_at"))
    head_sha = _text(review_.get("commit_id"), store.verdicts.c.head_sha)
    login = _text(_obj(review_.get("user")).get("login"))
    number = pr.get("number")
    repo_id = base_repo.get("id")
    repo = _text(base_repo.get("full_name"), store.verdicts.c.repo)
    # verdicts.source is String(64) for exactly this; GitHub logins run to 39
    # characters, which is a fact about GitHub and not a bound this code
    # enforces — so the composed value is what gets checked, not the login.
    source = _text(f"review:{login}", store.verdicts.c.source) if login else None
    if (
        scored_at is None
        or not head_sha
        or not source
        or not repo
        or not isinstance(number, int)
        or not isinstance(repo_id, int)
    ):
        # These are the row's identity and its dedup key. A stance that
        # cannot be attached to a commit, a time, a reviewer, a PR and a
        # repo is not a gradable claim, and storing it against a guess would
        # put an invented data point into a ledger whose whole product is
        # calibrated claims. Logged and 202'd rather than raised, for the
        # reason _record_merge gives: a 500 is a redelivery loop over a body
        # that will never carry what it is missing.
        print(
            f"doug: review on PR #{pr.get('number')} carried no usable "
            "commit_id/submitted_at/user.login/number/base repo; not ingested",
            file=sys.stderr,
        )
        return
    store.save_external_review(
        payload["installation"]["id"],
        repo_id,
        repo,
        number,
        head_sha,
        source,
        band,
        scored_at,
        raw={
            "review_id": review_.get("id"),
            "state": state,
            "submitted_at": review_.get("submitted_at"),
        },
    )


@app.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
) -> Response:
    """Verify, record, enqueue, 202. Never reviews inline.

    The 202 is sent only after the job is durable — GitHub does not
    redeliver on our schedule and a job held in memory dies with the
    instance. Everything expensive happens in worker.drain, which is kicked
    as a background task after the response and is best-effort by
    construction: Starlette runs background tasks after the response body is
    sent, so on Cloud Run's default request-based CPU allocation the kick
    can be throttled, and the instance can be scaled to zero out from under
    an in-flight drain. Losing a kick loses no work — the job row is
    already committed — it only delays it until something kicks a drain
    again. The durable backstop is the sweep lifespan() starts: on a
    deployment holding both the App and a ledger it reconciles and then
    drains on every cold start, so a row no later delivery kicks waits for
    the next revision rather than forever.

    async only because the signature needs the raw body. verify_webhook and
    json.loads run on the event loop thread deliberately: both are CPU-bound
    work on a body already in memory, and handing a few microseconds of
    HMAC to a worker thread would cost more than it saves. Everything that
    can touch the database — store.enabled() included, because on a cold
    engine it builds one, runs create_all() and applies migrations, all
    under a threading.Lock — goes through run_in_threadpool, so a delivery
    burst cannot block the event loop on a round trip.
    """
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        # Unreachable when the app booted through its lifespan, which
        # refuses without this. Kept because verify() with an empty key is
        # forgeable by anyone and a lifespan is bypassable (sub-app mount,
        # a TestClient not used as a context manager).
        raise HTTPException(status_code=503, detail="GITHUB_WEBHOOK_SECRET not configured")
    body = await request.body()
    # githubkit's verify() reads the digest from the signature prefix, not
    # from the header name, so an attacker-supplied "sha1=" would downgrade
    # the comparison. Pin it.
    if not x_hub_signature_256.startswith("sha256="):
        raise HTTPException(status_code=401, detail="bad signature")
    if not verify_webhook(secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        # Signed, so it came from someone holding the secret — but not
        # something we can act on. 202 rather than 4xx: a retry loop over a
        # body that will never parse helps nobody. A body that is valid JSON
        # but not an object — a list, a bare string, null — lands here too:
        # json.loads succeeds on it, so it never reaches the ValueError, and
        # every line below is a lookup on a dict it is not.
        print("doug: webhook body was signed but not a JSON object", file=sys.stderr)
        return Response(status_code=202)

    # Not payload.get("action", ""): the gating table below is a set
    # membership test, and an unhashable action (an object, an array) raises
    # TypeError there — a 500 on the dispatch itself, before any handler is
    # even chosen.
    action = _text(payload.get("action")) or ""
    # The gating table, evaluated once and before any guard that touches the
    # store. An event we do not handle — ping, push, an action outside the
    # table — must not depend on a ledger it never reaches. Scoping this
    # narrowly is load-bearing: the pre-existing
    # test_webhook_accepts_a_valid_sha256_signature posts a valid signature
    # with no event header and no database, and must still get its 202.
    handled = (
        (x_github_event == "installation" and action in INSTALLATION_STATES)
        or (x_github_event == "installation_repositories" and action in ("added", "removed"))
        or (
            x_github_event == "pull_request"
            and (action in PR_ACTIONS or action == "closed")
        )
        or (x_github_event == "pull_request_review" and action == "submitted")
    )
    if not handled:
        # Accepted and ignored, on purpose: a 4xx would put GitHub into a
        # redelivery loop over events we chose not to handle.
        return Response(status_code=202)
    if not await run_in_threadpool(store.enabled):
        # In the threadpool because this is not the cheap read it looks
        # like: on a cold engine store._get_engine() creates one, runs
        # create_all() and applies migrations — a full DDL round trip
        # against Cloud SQL — and it takes a threading.Lock on every call,
        # so the loop thread would also stall behind any worker already
        # inside it.
        #
        # ingest.enqueue raises without a database rather than no-opping,
        # and store's installation writes would no-op silently. Either way
        # a 202 here would mean "queued" over an empty ledger. Refused at
        # this endpoint only: DATABASE_URL stays optional for the rest of
        # the service (store.py's module docstring), so it cannot go in the
        # lifespan.
        raise HTTPException(status_code=503, detail="no ledger configured")
    inst = payload.get("installation")
    if not isinstance(inst, dict) or not isinstance(inst.get("id"), int):
        # Defensive: App webhooks always carry this, and a ping never does.
        # Without it there is no tenant to attribute the work to and no
        # token to do it with. The id is checked here, not just the key,
        # because every branch below indexes installation["id"] — this is
        # what makes those indexes total instead of a KeyError 500 that
        # GitHub would redeliver into the same 500.
        return Response(status_code=202)

    if x_github_event == "installation":
        await run_in_threadpool(_record_installation, payload, action)
        if action == "created":
            # Heal what the App missed before it was installed. Queued, not
            # inline: it lists every open PR over the network.
            background.add_task(_reconcile_then_drain, inst["id"])
    elif x_github_event == "installation_repositories":
        await run_in_threadpool(_merge_installation_repos, payload)
    elif x_github_event == "pull_request":
        if action == "closed":
            # Its own branch, never PR_ACTIONS: a merge starts the outcome
            # clock and must not buy a read. No drain is kicked, because
            # nothing reviewable was queued.
            await run_in_threadpool(_record_merge, payload)
        else:
            job_id = await run_in_threadpool(_enqueue_pull_request, payload)
            if job_id is not None:
                background.add_task(worker.drain)
    elif x_github_event == "pull_request_review":
        # A stance, not a review Doug pays for. No drain: nothing queued.
        await run_in_threadpool(_record_external_review, payload)

    return Response(status_code=202)
