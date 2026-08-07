"""HTTP surface. Routes stay thin: the product lives in features.py and scoring.py."""

import hmac
import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib import resources

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from githubkit.webhooks import verify as verify_webhook
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import __version__, app_auth, ingest, precision, reader, store, tenancy, worker
from .models import (
    Band,
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
    `/v1/comparisons` and `/v1/patterns`.
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
    if not hmac.compare_digest(x_doug_token, expected):
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
        items = [
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
            for row in store.latest_reviews(
                repo=repo if ctx is None else None,  # operator keeps the display filter
                installation_id=installation_id,
                repo_ids=repo_ids,
            )
            if row["pr_meta"]
        ]
    else:
        # No ledger configured — the fixture keeps the demo path alive.
        items = [QueueItem(pr=pr, verdict=score(pr, thr)) for pr in _load_fixture()]

    if threshold is None:
        # Report the line the rows were actually banded at, not the
        # deterministic default. Ledger rows carry the reader's threshold
        # (0.30); reporting 0.62 made the dashboard draw its cut line above
        # PRs it was simultaneously showing as flagged.
        thr = _banding_threshold(items, thr)
    else:
        # An explicit threshold has to re-band, or the parameter changes the
        # number in the summary while the rows keep contradicting it.
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
    validating None into PRMetadata instead of degrading. This falls back
    the same way _comparison_run does for the same shape of row.
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
    store.upsert_installation(
        inst["id"],
        _text(account.get("login"), store.installations.c.account_login) or "",
        _text(account.get("type"), store.installations.c.account_type) or "",
        INSTALLATION_STATES[action],
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
    base = _obj(_obj(pr.get("base")).get("repo"))
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
    head_sha = _text(head.get("sha"), store.review_jobs.c.head_sha)
    if not isinstance(number, int) or not full_name or not head_sha:
        # Signed, past both gates, and still missing something the job row
        # IS: which PR, which repo by name, which commit. Logged and 202'd
        # rather than raised, for the reason _record_merge gives below.
        print(
            f"doug: pull_request #{pr.get('number')} carried no usable "
            "number/base.repo.full_name/head.sha; not enqueued",
            file=sys.stderr,
        )
        return None
    return ingest.enqueue(
        payload["installation"]["id"],
        base_id,
        full_name,
        number,
        head_sha,
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
    store.enqueue_outcome_job(
        payload["installation"]["id"],
        repo_id,
        number,
        merge_sha,
        merged_at,
        base_ref,
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
