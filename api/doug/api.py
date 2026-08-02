"""HTTP surface. Routes stay thin: the product lives in features.py and scoring.py."""

import hmac
import json
import os
import sys
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from importlib import resources

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from githubkit.webhooks import verify as verify_webhook
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import __version__, app_auth, ingest, precision, reader, review, store, worker
from .models import (
    Band,
    PRMetadata,
    QueueItem,
    QueueResponse,
    QueueSummary,
    ReadScoreRequest,
    Reason,
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

    The gap that leaves: that pre-read is advisory, because verdicts carries
    no unique index on the identity it reads (roadmap M2, migration 003), so
    two workers racing the same reclaimed job can both pass it. The claim
    lease bounds that window rather than closing it.
    """
    try:
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


class ReviewRequest(BaseModel):
    repo: str  # owner/name
    pr_number: int
    # A deliberate rescore of an already-recorded commit. Without it, a
    # repeat request for the same head sha replays the recorded verdict.
    force: bool = False


class ReviewResponse(Verdict):
    """The risk verdict, plus the intent tier when it ran.

    Subclasses Verdict so the wire shape stays a superset: existing CI
    workflows parse band/score/threshold/reasons at the top level and keep
    working untouched. `deviations` is absent-or-empty for every repo that
    keeps no decision records, which is most of them.
    """

    deviations: list[reader.DeviationFinding] = []
    intent_alignment: int | None = None
    intent_refs: list[str] = []
    # read_with_decisions truncates the same diff at the same DIFF_BUDGET as
    # the risk read; set whenever that read ran partial, so a client
    # rendering `deviations` alone still knows to hedge them.
    intent_notice: str | None = None


@app.post("/v1/review")
def review_pr(
    req: ReviewRequest,
    x_doug_token: str = Header(""),
    x_github_token: str = Header(""),
) -> ReviewResponse:
    """CI-facing review: fetch the PR, score through the reader tier, persist.

    Auth is a shared token (DOUG_API_TOKEN); the GitHub token arrives
    per-request from the caller's CI so this service holds no repo
    credentials of its own. Unconfigured deployments refuse rather than
    run open.
    """
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if not hmac.compare_digest(x_doug_token, expected):
        raise HTTPException(status_code=401, detail="bad token")
    try:
        owner, name = req.repo.split("/", 1)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="repo must be owner/name") from e

    from githubkit import GitHub

    gh = GitHub(x_github_token or None)
    meta, diff = review.fetch_pr(gh, owner, name, req.pr_number)

    # Idempotency: a webhook redelivery or retried CI job for a commit this
    # ledger has already scored replays the recorded verdict — no second
    # paid read, no duplicate row for precision to double-count.
    if meta.head_sha and not req.force:
        # A read takes tens of seconds, so "already scored?" then "score"
        # is a wide-open check-then-act: two overlapping deliveries would
        # both miss the lookup and both pay. Serialise per (repo, pr, sha)
        # so the duplicate waits, then replays. In-process only — a
        # cross-instance duplicate stays possible and tolerated (consumers
        # key off max(verdict id)); a DB unique index isn't available
        # because create_all never alters live tables.
        with _inflight_review(req.repo, req.pr_number, meta.head_sha):
            if (replay := _replay_or_none(req, meta)) is not None:
                return replay
            return _score_and_persist(req, gh, owner, name, meta, diff)
    return _score_and_persist(req, gh, owner, name, meta, diff)


_inflight_guard = threading.Lock()
_inflight_locks: dict[tuple[str, int, str], threading.Lock] = {}


@contextmanager
def _inflight_review(repo: str, pr_number: int, head_sha: str):
    key = (repo, pr_number, head_sha)
    with _inflight_guard:
        lock = _inflight_locks.setdefault(key, threading.Lock())
    with lock:
        yield
    # Dropped after release, not refcounted: a waiter already holding this
    # lock object proceeds fine, and by the time a third request misses the
    # dict the verdict is durable, so its find_review hits.
    with _inflight_guard:
        _inflight_locks.pop(key, None)


def _replay_or_none(req: ReviewRequest, meta: PRMetadata) -> ReviewResponse | None:
    """The recorded verdict for this exact commit, or None to score fresh.

    Any lookup failure falls through to a fresh score: the worst case of a
    broken dedup read is one duplicate, never a failed CI.
    """
    try:
        prior = store.find_review(req.repo, req.pr_number, meta.head_sha)
    except Exception:  # noqa: BLE001
        prior = None
    if prior is None:
        return None
    reasons = [Reason(**r) for r in prior["reasons"]]
    reasons.append(
        Reason(
            rule="idempotent-replay",
            label=(
                f"Verdict for {meta.head_sha[:12]} was already recorded; "
                "replayed without a new read. POST force=true to rescore."
            ),
            weight=0.0,
        )
    )
    # intent_notice exists so a client rendering deviations alone knows the
    # read behind them was partial. Both reads truncate the same diff at the
    # same DIFF_BUDGET, so the stored risk-read coverage is also the intent
    # read's — replaying without this hedge would make truncated deviation
    # findings look complete on the second delivery of the same commit.
    intent_notice = None
    if prior["intent_alignment"] is not None and prior["coverage"] is not None:
        notice = reader.truncation_reason(reader.Coverage(**prior["coverage"]))
        intent_notice = notice.label if notice else None
    return ReviewResponse(
        score=prior["score"],
        band=Band(prior["band"]),
        threshold=prior["threshold"],
        reasons=reasons,
        deviations=[reader.DeviationFinding(**d) for d in prior["deviations"]],
        intent_alignment=prior["intent_alignment"],
        intent_refs=prior["intent_refs"],
        intent_notice=intent_notice,
    )


def _score_and_persist(
    req: ReviewRequest, gh, owner: str, name: str, meta: PRMetadata, diff: str
) -> ReviewResponse:
    tier, verdict, rv, cov = review.score_one(meta, diff)
    intent_read = review.read_intent(gh, owner, name, meta, diff)

    # save_review commits the verdict, its findings, and (when given) its
    # coverage row together — coverage is passed in rather than written by a
    # follow-up save_read() call, so it can never be the thing that
    # succeeds-then-silently-vanishes if this request dies mid-write.
    #
    # save_deviations is a genuinely separate write (ADR-0007), so it keeps
    # its own try: if save_review lands but save_deviations doesn't, the
    # verdict this response describes really is durable, and calling that
    # "ledger-unavailable" would be false.
    verdict_id = None
    try:
        verdict_id = store.save_review(
            req.repo, req.pr_number, tier, verdict, rv,
            model=reader.MODEL if tier == "reader" else None,
            pr_meta=meta.model_dump(mode="json"),
            coverage=cov,
            prompt_hash=reader.PROMPT_HASH if tier == "reader" else None,
        )
    except Exception as e:  # noqa: BLE001 — a down ledger must not fail CI
        verdict.reasons.append(
            Reason(rule="ledger-unavailable", label=str(e)[:200], weight=0.0)
        )
    else:
        if intent_read is not None:
            try:
                store.save_deviations(
                    verdict_id, intent_read.findings,
                    intent_read.refs, intent_read.alignment,
                )
            except Exception as e:  # noqa: BLE001 — the verdict is already saved
                verdict.reasons.append(
                    Reason(rule="deviations-unrecorded", label=str(e)[:200], weight=0.0)
                )

    intent_notice = (
        reader.truncation_reason(intent_read.coverage) if intent_read else None
    )
    return ReviewResponse(
        **verdict.model_dump(),
        deviations=intent_read.findings if intent_read else [],
        intent_alignment=intent_read.alignment if intent_read else None,
        intent_refs=intent_read.refs if intent_read else [],
        intent_notice=intent_notice.label if intent_notice else None,
    )


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
    a failure — it returns a verdict, same as /v1/review's score_one path —
    but it gets the same read-truncated reason so a caller of this endpoint
    isn't the one path left unable to tell a whole read from part of one.
    """
    # Third inlined copy of this gate (review_pr, queue, here). Deliberate:
    # review_pr dies with Task 9, and that is when the two survivors collapse
    # into one helper — extracting it now would edit endpoints a concurrent
    # session is reading.
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if not hmac.compare_digest(x_doug_token, expected):
        raise HTTPException(status_code=401, detail="bad token")
    if not reader.enabled():
        return score(req.pr)
    try:
        verdict = reader.verdict_from_reader(reader.read_diff(req.pr, req.diff))
        if notice := reader.truncation_reason(reader.coverage(req.diff)):
            verdict.reasons.append(notice)
        return verdict
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


@app.get("/v1/queue")
def queue(
    threshold: float | None = None,
    repo: str | None = None,
    x_doug_token: str = Header(""),
) -> QueueResponse:
    """The review queue. Token-gated on the same shared secret as
    /v1/review: these are real PR titles, authors and reader rationales,
    and the service is deployed --allow-unauthenticated.

    `repo` stays a caller-supplied parameter until sessions exist; the
    shared token stops anonymous reads, it does not separate tenants.
    """
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if not hmac.compare_digest(x_doug_token, expected):
        raise HTTPException(status_code=401, detail="bad token")
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
            for row in store.latest_reviews(repo=repo)
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

    Token-gated on the same shared secret as /v1/review: this is the
    unpublished half of the evidence base, and the caveat travels in the
    response body so a number cannot be lifted out of it by accident.
    """
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if not hmac.compare_digest(x_doug_token, expected):
        raise HTTPException(status_code=401, detail="bad token")
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
