"""The review_jobs queue — the durable gap between a webhook and a review.

A delivery must be recorded and answered in milliseconds; a review takes a
model call. Everything between those two facts lives in this table: the
webhook enqueues and returns 202, a worker claims and runs. Nothing is held
in process memory, so a Cloud Run instance dying mid-review strands its
claim rather than losing it cleanly: the row sits at 'running' forever,
because REVIVABLE deliberately excludes that status (reviving a 'running'
row out from under a worker that is still alive would pay for a second read
of the same SHA). reclaim_stalled() is the other half — it re-pends a
'running' claim once its lease has expired, and that is what actually turns
a crashed instance back into a review. The queue alone does not do this;
the caller (Task 5's drain loop or Task 7's reconcile) has to run it on a
cadence.

Uniqueness is (installation_id, github_repo_id, pr_number, head_sha) and it
is enforced by the database, not by a check-then-insert: two deliveries of
the same push arrive concurrently often enough that a race here would mean
paying for the same read twice.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from . import store

# The two states a collision may revive. Both mean "this SHA was queued and
# never reviewed"; every other state means the work is queued, in flight, or
# already paid for.
REVIVABLE = ("failed", "superseded")

# Why enqueue was called, which is what decides the terms a 'failed' row comes
# back on. 'live' means something happened to this PR just now: the drain
# re-queueing the SHA that overtook a stale job today, and Task 6's webhook
# handler next. 'reconcile' is the startup sweep re-deriving open PRs from the
# API — it runs whether or not anything changed, which makes it the only caller
# that repeats, and FAILED_REVIVE_COOLOFF_SECONDS is charged to that repetition
# rather than to the row.
Trigger = Literal["live", "reconcile"]

# How long a job that burned every attempt is left alone before the reconcile
# sweep will revive it. Without this, revival is per-restart: startup reconcile
# re-arms a permanently-broken PR, the drain burns max_attempts paid reads
# against it, and a Cloud Run service that cold-starts often pays that bill every
# time. Healing a genuinely transient failure (an outage, a wiped credential) is
# worth a retry an hour later; nothing is worth retrying every ninety seconds
# forever. Two exemptions, for the same reason — the wait is a brake on a machine
# repeating itself, never on a person. Superseded rows never wait: a force-push
# back to an older SHA is a live instruction to review that SHA now. Neither does
# a live enqueue of a failed row: a reopen or a force-push back to a SHA whose
# review failed is a user event, and answering it with silence for an hour is a
# PR that never gets reviewed.
FAILED_REVIVE_COOLOFF_SECONDS = 3600

# How long a claim may sit 'running' before reclaim_stalled treats it as
# abandoned rather than in flight. reader.read_timeout() bounds a single
# model call at 120s; 900s (15 minutes) leaves generous room for the GitHub
# API calls and retry backoff wrapped around that read, so a live worker is
# never reclaimed out from under itself, while a crashed instance's claim
# still comes back within one reconcile cycle instead of blocking that PR
# forever.
STALL_LEASE_SECONDS = 900

# Postgres names the violated constraint in the error text; sqlite instead
# lists the table and columns. Checking for either identifies exactly the
# review_jobs unique violation this path exists to handle — anything else
# (a real integrity problem this code did not cause) has to propagate
# rather than being silently read as "already queued".
_DEDUPE_COLLISION = ("uq_review_job", "unique constraint failed: review_jobs.")


def _is_dedupe_collision(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower()
    return any(marker in message for marker in _DEDUPE_COLLISION)


def _engine():
    engine = store._get_engine()
    if engine is None:
        raise RuntimeError("review_jobs requires DATABASE_URL")
    return engine


def _as_utc(value: datetime) -> datetime:
    """Normalise a DB timestamp to aware UTC.

    sqlite's CURRENT_TIMESTAMP is naive; Postgres timestamptz is aware.
    Claim holders compare the started_at they were handed against the row,
    so both sides of that equality have to share a timezone convention.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _db_now(conn) -> datetime:
    """The database's clock, not the caller's wall clock.

    Claim started_at and reclaim cutoffs must share one clock across Cloud
    Run instances; comparing one instance's datetime.now() to another's
    written started_at is how a skewed host reclaims a live worker.

    sqlite is the test path only and CURRENT_TIMESTAMP is second-precision,
    which would collapse distinct claim generations inside one second into
    the same started_at and make the fence useless in the suite. Wall clock
    keeps microsecond generation tokens there; Postgres uses now().
    """
    if conn.dialect.name == "sqlite":
        return datetime.now(UTC)
    value = conn.execute(select(func.now())).scalar_one()
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return _as_utc(value)


def _job_filter(installation_id: int, github_repo_id: int, pr_number: int):
    return (
        store.review_jobs.c.installation_id == installation_id,
        store.review_jobs.c.github_repo_id == github_repo_id,
        store.review_jobs.c.pr_number == pr_number,
    )


def enqueue(
    installation_id: int,
    github_repo_id: int,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
    *,
    trigger: Trigger = "live",
) -> int | None:
    """Queue one head SHA for review. None means this SHA needs no new work.

    A collision on the unique index is not automatically a duplicate. The
    index carries no status column, so a row that ended 'failed' or
    'superseded' blocks re-insertion exactly like a reviewed one — and those
    are the two states reconcile exists to repair. Colliding with one revives
    it rather than dropping the work, on terms `trigger` decides: a live
    caller (the default) revives either state at once, so the cost of a
    permanently broken PR is max_attempts per user event; the reconcile sweep
    passes trigger='reconcile' and revives a 'failed' row only once
    FAILED_REVIVE_COOLOFF_SECONDS has elapsed since it gave up, so a service
    that cold-starts every few minutes pays that bill per cooloff window
    instead of per restart. Either way the PR is never dead forever.

    Superseding older pending SHAs happens after the insert lands and in the
    same transaction. Running it first meant a redelivered older push
    superseded the newer pending job and then collided on its own row,
    leaving the PR with nothing pending at all. It is a spend optimisation
    for the ordinary in-order burst, not the thing that decides which SHA
    gets reviewed: GitHub does not order deliveries, so worker.process_job
    re-checks the PR's real head before paying for a read.
    """
    engine = _engine()
    try:
        with engine.begin() as conn:
            now = _db_now(conn)
            job_id = int(
                conn.execute(
                    store.review_jobs.insert().returning(store.review_jobs.c.id),
                    {
                        "installation_id": installation_id,
                        "github_repo_id": github_repo_id,
                        "repo_full_name": repo_full_name,
                        "pr_number": pr_number,
                        "head_sha": head_sha,
                        "status": "pending",
                        "attempts": 0,
                        "enqueued_at": now,
                    },
                ).scalar_one()
            )
            conn.execute(
                update(store.review_jobs)
                .where(
                    *_job_filter(installation_id, github_repo_id, pr_number),
                    store.review_jobs.c.head_sha != head_sha,
                    store.review_jobs.c.status == "pending",
                )
                .values(status="superseded", finished_at=now)
            )
            return job_id
    except IntegrityError as e:
        if not _is_dedupe_collision(e):
            raise
        return _revive(
            engine, installation_id, github_repo_id, pr_number, head_sha, trigger
        )


def _revive(
    engine,
    installation_id: int,
    github_repo_id: int,
    pr_number: int,
    head_sha: str,
    trigger: Trigger,
) -> int | None:
    """Return a queued-but-unreviewed row to pending, or None if there is none.

    A 'superseded' row revives on any caller's terms: a force-push back to an
    older SHA is an instruction to review that SHA now. A 'failed' row revives
    at once for a live caller too, and only the reconcile sweep makes it wait
    out FAILED_REVIVE_COOLOFF_SECONDS from finished_at — that sweep runs on
    every startup regardless of whether anything changed, so a
    permanently-broken PR would otherwise re-arm max_attempts paid reads on
    each cold start. Read off `trigger` rather than off the row, because the
    row cannot tell the two apart: 'failed' at this SHA looks identical
    whether a person just reopened the PR or a container just booted.

    The status test lives in the UPDATE's WHERE rather than in a SELECT before
    it: a concurrent drain can claim or finish the row between the two, and a
    zero-row result is the only reliable way to find out that it did.

    The row is updated in place and keeps its id — never deleted and
    re-inserted. worker.drain bounds a supersede/revive ping-pong (its
    stale-head guard supersedes a job, which this then revives) with a
    seen-set of job ids, and a fresh id per revival would defeat it silently,
    turning the spin back into an unbounded loop inside a held instance.
    """
    failed = store.review_jobs.c.status == "failed"
    with engine.begin() as conn:
        now = _db_now(conn)
        # Anything that is not the sweep gets the live terms. A mistyped trigger
        # therefore costs at most what this branch cost before the cooloff existed
        # (max_attempts, bounded), never a review that silently never happens —
        # and the sweep's own value is pinned behaviorally by
        # test_reconcile_all_revives_a_pr_that_burned_all_its_attempts.
        if trigger == "reconcile":
            failed = and_(
                failed,
                or_(
                    # NULL finished_at should not happen — fail() sets it at the
                    # cap — but if it ever does, heal rather than strand the PR
                    # forever behind a comparison it can never pass.
                    store.review_jobs.c.finished_at.is_(None),
                    store.review_jobs.c.finished_at
                    < now - timedelta(seconds=FAILED_REVIVE_COOLOFF_SECONDS),
                ),
            )
        job_id = conn.execute(
            update(store.review_jobs)
            .where(
                *_job_filter(installation_id, github_repo_id, pr_number),
                store.review_jobs.c.head_sha == head_sha,
                or_(store.review_jobs.c.status == "superseded", failed),
            )
            .values(
                status="pending",
                attempts=0,
                error=None,
                enqueued_at=now,
                started_at=None,
                finished_at=None,
                verdict_id=None,
            )
            .returning(store.review_jobs.c.id)
        ).scalar_one_or_none()
    return int(job_id) if job_id is not None else None


def claim() -> dict | None:
    """Take the oldest pending job, or None. Marks it running before returning.

    Ordering is (enqueued_at, id), which is what makes fail()'s bump of
    enqueued_at put a re-pended job behind the rest of the queue rather than
    back at its head.

    On Postgres the select takes a row lock with SKIP LOCKED, so concurrent
    drains take different jobs instead of blocking on the same one. sqlite
    has no equivalent and does not get the same guarantee: its transactions
    are deferred, so two racing claimers both read the same pending row, and
    the loser is stopped only when its UPDATE meets the file write lock and
    raises SQLITE_BUSY ('database is locked'). The row is never claimed
    twice, but the loser errors rather than waiting its turn. That is
    tolerable because sqlite is the test path only; if it ever becomes a
    real drain backend, this needs BEGIN IMMEDIATE, not a comment.
    """
    engine = store._get_engine()
    if engine is None:
        return None
    pending = (
        select(store.review_jobs)
        .where(store.review_jobs.c.status == "pending")
        .order_by(store.review_jobs.c.enqueued_at, store.review_jobs.c.id)
        .limit(1)
    )
    if engine.dialect.name == "postgresql":
        pending = pending.with_for_update(skip_locked=True)
    with engine.begin() as conn:
        row = conn.execute(pending).mappings().first()
        if row is None:
            return None
        now = _db_now(conn)
        result = conn.execute(
            update(store.review_jobs)
            .where(
                store.review_jobs.c.id == row["id"],
                store.review_jobs.c.status == "pending",
            )
            .values(status="running", started_at=now)
        )
        if result.rowcount == 0:
            # Lost a race after the SELECT (sqlite has no SKIP LOCKED).
            return None
        return {**row, "status": "running", "started_at": now}


def reclaim_stalled(older_than_seconds: int = STALL_LEASE_SECONDS) -> int:
    """Re-pend 'running' jobs whose claim has outlived the lease. Returns
    how many were reclaimed.

    A crashed instance leaves its claim behind at 'running' forever — no
    later enqueue can bring it back, because REVIVABLE deliberately excludes
    'running' (reviving it out from under a worker that is still alive would
    pay for a second model read of the same SHA). The lease is what tells a
    crashed claim apart from a live one: younger than `older_than_seconds`
    is treated as in flight and left strictly alone; older is treated as
    abandoned.

    Reclaiming does not spend an attempt, for the same reason release()
    doesn't: the instance died, not the job. enqueued_at is bumped to now so
    a job that keeps crashing workers falls to the back of the queue instead
    of head-of-line blocking every claim() until it burns through
    max_attempts.

    Storage-disabled is a no-op here like claim(), not a raise like the rest
    of this module — the caller (drain or reconcile) runs this
    unconditionally on a cadence and must not need a try/except around it.
    """
    engine = store._get_engine()
    if engine is None:
        return 0
    with engine.begin() as conn:
        now = _db_now(conn)
        cutoff = now - timedelta(seconds=older_than_seconds)
        result = conn.execute(
            update(store.review_jobs)
            .where(
                store.review_jobs.c.status == "running",
                # NULL started_at cannot satisfy `< cutoff` (unknown), and
                # would otherwise leave a running row immortal — the silent
                # never-reviewed failure reclaim exists to close.
                or_(
                    store.review_jobs.c.started_at.is_(None),
                    store.review_jobs.c.started_at < cutoff,
                ),
            )
            .values(status="pending", started_at=None, enqueued_at=now)
        )
        # rowcount is -1 on drivers that decline to report it. Callers log
        # this as "how many claims we found abandoned", and a negative count
        # there would read as a bug in the sweep rather than in the driver.
        return max(0, result.rowcount)


def _terminal_where(job_id: int, started_at: datetime):
    """Fence a claim-holder update to this exact claim generation.

    status='running' alone is not enough once reclaim has re-pended the row
    and a second worker has claimed it — both holders see 'running'. The
    started_at written at claim() is the generation token.
    """
    return (
        store.review_jobs.c.id == job_id,
        store.review_jobs.c.status == "running",
        store.review_jobs.c.started_at == _as_utc(started_at),
    )


def release(job_id: int, *, started_at: datetime) -> bool:
    """Put a claimed job back without spending an attempt.

    drain claims a job before it can tell whether it has already run it this
    pass. Leaving the repeat 'running' strands it, and fail() would charge an
    attempt against work nobody attempted. enqueued_at is deliberately
    untouched — unlike a failure, nothing here justifies losing its place.

    Returns False when this caller no longer holds the claim (reclaimed or
    finished by someone else) — a no-op, not an error.
    """
    engine = _engine()
    with engine.begin() as conn:
        applied = conn.execute(
            update(store.review_jobs)
            .where(*_terminal_where(job_id, started_at))
            .values(status="pending", started_at=None)
            .returning(store.review_jobs.c.id)
        ).scalar_one_or_none()
        return applied is not None


def complete(job_id: int, verdict_id: int | None, *, started_at: datetime) -> bool:
    """Mark a job done. verdict_id is None when the review produced no ledger
    row — a skipped PR is finished, not failed.

    error is cleared: a job that failed twice before succeeding must not
    land 'done' still carrying the error text from the attempt that didn't
    work, or the row misreports what happened to it.

    Returns False when this caller no longer holds the claim — see release().
    """
    engine = _engine()
    with engine.begin() as conn:
        applied = conn.execute(
            update(store.review_jobs)
            .where(*_terminal_where(job_id, started_at))
            .values(
                status="done",
                verdict_id=verdict_id,
                finished_at=_db_now(conn),
                error=None,
            )
            .returning(store.review_jobs.c.id)
        ).scalar_one_or_none()
        return applied is not None


def supersede(job_id: int, *, started_at: datetime) -> bool:
    """Retire a job whose head SHA is no longer the PR's.

    Neither 'done' — there is no verdict — nor 'failed', since nothing went
    wrong. It lands in a revivable state on purpose: a force-push back to
    this SHA re-queues this row rather than being suppressed by it.

    Returns False when this caller no longer holds the claim — see release().
    """
    engine = _engine()
    with engine.begin() as conn:
        applied = conn.execute(
            update(store.review_jobs)
            .where(*_terminal_where(job_id, started_at))
            .values(status="superseded", finished_at=_db_now(conn))
            .returning(store.review_jobs.c.id)
        ).scalar_one_or_none()
        return applied is not None


def fail(job_id: int, error: str, *, started_at: datetime, max_attempts: int = 3) -> bool:
    """Record a failed attempt: back to pending below the cap, failed at it.

    started_at is cleared on the retry so a re-pended row is not reported as
    having been running since its first attempt.

    attempts is incremented in the same UPDATE that reads it
    (review_jobs.c.attempts + 1), not read in Python and written back a
    statement later — two concurrent fails on the same row would otherwise
    both read N and both write N+1, losing an attempt and letting the job
    retry one more time than max_attempts allows. status, enqueued_at and
    finished_at are decided from that same SQL-side expression via CASE, so
    the whole row transitions atomically off one incremented value instead
    of a value this function briefly held in a local variable.

    Returns False when this caller no longer holds the claim — see release().
    """
    engine = _engine()
    new_attempts = store.review_jobs.c.attempts + 1
    at_cap = new_attempts >= max_attempts
    with engine.begin() as conn:
        now = _db_now(conn)
        applied = conn.execute(
            update(store.review_jobs)
            .where(*_terminal_where(job_id, started_at))
            .values(
                attempts=new_attempts,
                error=error[:500],
                started_at=None,
                status=case((at_cap, "failed"), else_="pending"),
                finished_at=case((at_cap, now), else_=store.review_jobs.c.finished_at),
                # Back of the queue, not the front, below the cap. claim()
                # orders by (enqueued_at, id), so leaving enqueued_at alone
                # hands the job straight back to the next claim and burns
                # every attempt in one pass, before whatever was transient
                # has any chance to clear. worker.drain's seen-set is what
                # stops a re-claim when it is the only pending row; this is
                # the other half. At the cap the job is 'failed', going
                # nowhere in the queue, so enqueued_at is left alone too.
                enqueued_at=case((at_cap, store.review_jobs.c.enqueued_at), else_=now),
            )
            .returning(store.review_jobs.c.id)
        ).scalar_one_or_none()
        return applied is not None
