"""Durable claim and settlement boundary for M3 outcome jobs.

The Cloud Run Job processes one repository batch at a time. Claims are
short database transactions: rows move to ``running`` before the clone, a
lease makes crashed claims reclaimable, and ``claim_generation`` fences an
old holder after reclamation. Successful outcome inserts and job completion
share one transaction so the published numerator and denominator cannot
part company.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_, select, update

from . import store
from .adjudicate import Adjudication
from .store import _db_now

MAX_ATTEMPTS = 10
STALL_LEASE_SECONDS = 7200


class LostClaim(RuntimeError):
    """A reclaimed or terminal row no longer belongs to this worker."""


@dataclass(frozen=True)
class RepositoryKey:
    installation_id: int
    github_repo_id: int


@dataclass(frozen=True)
class ClaimedBatch:
    key: RepositoryKey
    repo_full_name: str | None
    permanently_unreachable: bool
    jobs: list[dict]
    evidence_installation_id: int | None = None

    @property
    def reader_installation_id(self) -> int:
        """The installation whose token can actually reach this repository.

        Normally the key's own. It differs only after a repository transfer,
        where the job was written under an installation that no longer covers
        the repo and `_repository_identity` re-resolved the live one. The
        outcome row still settles under `key.installation_id` — who paid for
        the verdict does not change because someone else can now read the
        git history.
        """
        return (
            self.key.installation_id
            if self.evidence_installation_id is None
            else self.evidence_installation_id
        )


def _engine():
    engine = store._get_engine()
    if engine is None:
        raise RuntimeError("outcome_jobs requires DATABASE_URL")
    return engine


def due_repositories() -> list[RepositoryKey]:
    """Repository identities with at least one mature pending job.

    This is an advisory invocation snapshot. ``claim_repository`` repeats
    the cutoff and status predicates under row locks; the snapshot decides
    only which repositories this daily execution will visit once.
    """
    engine = _engine()
    with engine.connect() as conn:
        now = _db_now(conn)
        rows = conn.execute(
            select(
                store.outcome_jobs.c.installation_id,
                store.outcome_jobs.c.github_repo_id,
                func.min(store.outcome_jobs.c.due_at).label("first_due"),
            )
            .where(
                store.outcome_jobs.c.status == "pending",
                store.outcome_jobs.c.due_at <= now,
            )
            .group_by(
                store.outcome_jobs.c.installation_id,
                store.outcome_jobs.c.github_repo_id,
            )
            .order_by("first_due", store.outcome_jobs.c.installation_id)
        ).all()
    return [RepositoryKey(int(row.installation_id), int(row.github_repo_id)) for row in rows]


def _claim_query(key: RepositoryKey, now: datetime):
    """The row-lock contract, exposed so its PostgreSQL SQL is testable."""
    return (
        select(store.outcome_jobs)
        .where(
            store.outcome_jobs.c.installation_id == key.installation_id,
            store.outcome_jobs.c.github_repo_id == key.github_repo_id,
            store.outcome_jobs.c.status == "pending",
            store.outcome_jobs.c.due_at <= now,
        )
        .order_by(store.outcome_jobs.c.due_at, store.outcome_jobs.c.id)
        .with_for_update(skip_locked=True)
    )


def _live_registration(conn, github_repo_id: int) -> tuple[int, str] | None:
    """The installation that covers this repository NOW, and its name.

    Keyed on `github_repo_id` alone, which is the only identity a GitHub
    repository transfer preserves (#218: "installation_id remains
    operational plumbing only"). Both states must be live — an active
    junction row under a deleted installation is stale registration
    history, not a reachable repo — and the newest row wins, matching
    `store.repo_id_for`'s resolution order so two call sites cannot
    disagree about who owns a repo.

    None when nothing active covers the id, which is the ordinary case: one
    installation, one registration, already the key's own.
    """
    row = conn.execute(
        select(
            store.installation_repos.c.installation_id,
            store.installation_repos.c.full_name,
        )
        .join(
            store.installations,
            store.installations.c.installation_id
            == store.installation_repos.c.installation_id,
        )
        .where(
            store.installation_repos.c.github_repo_id == github_repo_id,
            store.installation_repos.c.state == "active",
            store.installations.c.state == "active",
        )
        .order_by(store.installation_repos.c.id.desc())
        .limit(1)
    ).first()
    return (int(row.installation_id), str(row.full_name)) if row else None


def _repository_identity(conn, key: RepositoryKey) -> tuple[str | None, bool, int | None]:
    installation_state = conn.execute(
        select(store.installations.c.state)
        .where(store.installations.c.installation_id == key.installation_id)
        .limit(1)
    ).scalar_one_or_none()
    repo = conn.execute(
        select(store.installation_repos.c.full_name, store.installation_repos.c.state)
        .where(
            store.installation_repos.c.installation_id == key.installation_id,
            store.installation_repos.c.github_repo_id == key.github_repo_id,
        )
        .limit(1)
    ).first()

    # Durable ledger state is the only evidence strong enough to censor.
    # Missing registry rows are the known MT0/backfill shape and must retry.
    permanent = installation_state == "deleted" or (
        repo is not None and repo.state != "active"
    )

    # A transfer looks EXACTLY like an uninstall from inside the old
    # installation: its junction row goes 'removed' and its installation can
    # go 'deleted', so both clauses above fire while the repository is
    # perfectly readable under whoever holds it now. Censoring on that reads
    # a bookkeeping event as evidence of blindness — in the flattering
    # direction, since a censored PR leaves the risk set. So before
    # censoring, ask whether anything live still covers this repo id; the
    # answer is the same identity `store.repo_id_for` would give a reader.
    #
    # Only reached when `permanent` is already true. An installation that is
    # merely suspended, or a repo whose registry row is absent, keeps
    # retrying through its own key exactly as before — this widens nothing
    # about which jobs get adjudicated, only who reads the git history for
    # the ones that would otherwise be thrown away.
    if permanent and (live := _live_registration(conn, key.github_repo_id)) is not None:
        successor_id, successor_name = live
        if successor_id != key.installation_id:
            return successor_name, False, successor_id

    if repo is not None:
        return str(repo.full_name), permanent, None

    fallback = conn.execute(
        select(store.verdicts.c.repo)
        .where(
            store.verdicts.c.installation_id == key.installation_id,
            store.verdicts.c.github_repo_id == key.github_repo_id,
        )
        .order_by(store.verdicts.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return (str(fallback) if fallback is not None else None), permanent, None


def claim_repository(key: RepositoryKey) -> ClaimedBatch | None:
    """Lease every currently claimable row for one repository."""
    engine = _engine()
    with engine.begin() as conn:
        now = _db_now(conn)
        rows = conn.execute(_claim_query(key, now)).mappings().all()
        if not rows:
            return None
        ids = [int(row["id"]) for row in rows]
        claimed = conn.execute(
            update(store.outcome_jobs)
            .where(
                store.outcome_jobs.c.id.in_(ids),
                store.outcome_jobs.c.status == "pending",
            )
            .values(
                status="running",
                started_at=now,
                finished_at=None,
                error=None,
                claim_generation=store.outcome_jobs.c.claim_generation + 1,
            )
        )
        if claimed.rowcount != len(ids):
            raise LostClaim("one or more outcome rows changed during claim")
        current = [
            dict(row)
            for row in conn.execute(
                select(store.outcome_jobs)
                .where(store.outcome_jobs.c.id.in_(ids))
                .order_by(store.outcome_jobs.c.due_at, store.outcome_jobs.c.id)
            ).mappings()
        ]
        repo_full_name, permanent, evidence_id = _repository_identity(conn, key)
    return ClaimedBatch(key, repo_full_name, permanent, current, evidence_id)


def reclaim_stalled(older_than_seconds: int = STALL_LEASE_SECONDS) -> int:
    """Return expired running claims to pending without spending an attempt."""
    engine = _engine()
    with engine.begin() as conn:
        now = _db_now(conn)
        cutoff = now - timedelta(seconds=older_than_seconds)
        result = conn.execute(
            update(store.outcome_jobs)
            .where(
                store.outcome_jobs.c.status == "running",
                or_(
                    store.outcome_jobs.c.started_at.is_(None),
                    store.outcome_jobs.c.started_at < cutoff,
                ),
            )
            .values(status="pending", started_at=None)
        )
        return max(0, result.rowcount)


def _claims_are_current(conn, batch: ClaimedBatch) -> bool:
    expected = {int(job["id"]): int(job["claim_generation"]) for job in batch.jobs}
    rows = conn.execute(
        select(
            store.outcome_jobs.c.id,
            store.outcome_jobs.c.status,
            store.outcome_jobs.c.claim_generation,
        ).where(store.outcome_jobs.c.id.in_(expected))
    ).all()
    return len(rows) == len(expected) and all(
        row.status == "running" and int(row.claim_generation) == expected[int(row.id)]
        for row in rows
    )


def _fail_job(conn, job: dict, error: str, now: datetime, max_attempts: int) -> None:
    new_attempts = store.outcome_jobs.c.attempts + 1
    at_cap = new_attempts >= max_attempts
    result = conn.execute(
        update(store.outcome_jobs)
        .where(
            store.outcome_jobs.c.id == job["id"],
            store.outcome_jobs.c.status == "running",
            store.outcome_jobs.c.claim_generation == job["claim_generation"],
        )
        .values(
            status=case((at_cap, "failed"), else_="pending"),
            attempts=new_attempts,
            started_at=None,
            finished_at=case((at_cap, now), else_=None),
            error=error[:1000],
        )
    )
    if result.rowcount != 1:
        raise LostClaim(f"outcome job {job['id']} is no longer held")


def fail_batch(
    batch: ClaimedBatch, error: str, max_attempts: int = MAX_ATTEMPTS
) -> int:
    """Spend one attempt for every row in a repository batch."""
    engine = _engine()
    with engine.begin() as conn:
        if not _claims_are_current(conn, batch):
            raise LostClaim("one or more outcome claims were reclaimed")
        now = _db_now(conn)
        for job in batch.jobs:
            _fail_job(conn, job, error, now, max_attempts)
    return len(batch.jobs)


def _identity(row) -> tuple[int, str, int]:
    return (int(row["pr_number"]), str(row["merge_commit_sha"]), int(row["window_days"]))


def settle_batch(
    batch: ClaimedBatch,
    adjudication: Adjudication,
    *,
    repo_full_name: str,
    observed_at: datetime,
    prereg_hash: str,
) -> tuple[int, int]:
    """Append outcomes and terminally update their jobs in one transaction."""
    engine = _engine()
    jobs = {_identity(job): job for job in batch.jobs}
    classified = {
        (outcome.pr_number, outcome.merge_commit_sha, outcome.window_days): outcome
        for outcome in adjudication.outcomes
    }
    refused = {_identity(item.job): item for item in adjudication.unadjudicable}
    if set(jobs) != set(classified) | set(refused) or set(classified) & set(refused):
        raise ValueError("adjudication must account for every claimed job exactly once")

    with engine.begin() as conn:
        if not _claims_are_current(conn, batch):
            raise LostClaim("one or more outcome claims were reclaimed")
        now = _db_now(conn)
        for identity, outcome in classified.items():
            job = jobs[identity]
            detail = outcome.detail.model_dump(mode="json")
            detail["prereg_hash"] = prereg_hash
            conn.execute(
                store.outcomes.insert(),
                {
                    "repo": repo_full_name,
                    "pr_number": outcome.pr_number,
                    "kind": outcome.kind.value,
                    "observed_at": observed_at,
                    "source": "git-labels",
                    "github_repo_id": outcome.github_repo_id,
                    "installation_id": outcome.installation_id,
                    "window_days": outcome.window_days,
                    "merge_commit_sha": outcome.merge_commit_sha,
                    "detail": json.dumps(detail, sort_keys=True),
                },
            )
            result = conn.execute(
                update(store.outcome_jobs)
                .where(
                    store.outcome_jobs.c.id == job["id"],
                    store.outcome_jobs.c.status == "running",
                    store.outcome_jobs.c.claim_generation == job["claim_generation"],
                )
                .values(status="done", finished_at=now, error=None)
            )
            if result.rowcount != 1:
                raise LostClaim(f"outcome job {job['id']} is no longer held")
        for identity, item in refused.items():
            _fail_job(conn, jobs[identity], item.reason, now, MAX_ATTEMPTS)
    return len(classified), len(refused)
