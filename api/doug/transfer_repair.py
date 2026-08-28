"""Undo the censorings a repository transfer caused, and requeue their jobs.

Before `outcome_queue._live_registration` existed, a transfer looked exactly
like an uninstall from inside the old installation: its junction row went
'removed' and its installation could go 'deleted', so
`_repository_identity` returned `permanently_unreachable` for a repository
that was perfectly readable under its new owner. Every job that came due in
that state settled as `censored` / `unreachable` — terminally, since a
settled job is never retried — and a censored PR leaves the risk set, which
is the flattering direction.

This module names those rows precisely and puts them back. It repairs a row
only when all three hold, so a legitimate censoring can never be caught up
in it:

1. the outcome is `censored` with `censor_reason == 'unreachable'` — the
   other disjunct, `base_ref`, is a real evidence gap and stays;
2. its own installation no longer covers the repository; and
3. some OTHER installation actively does, right now — the same successor
   `outcome_queue` would adjudicate through today.

Point 3 is what makes this a repair rather than a re-roll: without a live
successor the censoring was correct and is left alone.

The manifest is the whole deleted row, not a list of ids, so `rollback`
restores exactly what was removed rather than a reconstruction of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import and_, delete, exists, select, update
from sqlalchemy.engine import Connection, Engine

from . import store

CENSOR_REASON_UNREACHABLE = "unreachable"


class RepairInvariantError(RuntimeError):
    """A precondition the operator asserted did not hold. Nothing was written."""


@dataclass(frozen=True)
class RepairRow:
    outcome_id: int
    installation_id: int
    github_repo_id: int
    pr_number: int
    window_days: int
    successor_installation_id: int
    job_id: int | None


@dataclass(frozen=True)
class RepairReport:
    rows: tuple[RepairRow, ...]

    @property
    def outcomes(self) -> int:
        return len(self.rows)

    @property
    def jobs(self) -> int:
        return sum(1 for row in self.rows if row.job_id is not None)

    @property
    def prs(self) -> int:
        return len({(row.github_repo_id, row.pr_number) for row in self.rows})


def _censor_reason(detail) -> str | None:
    """`outcomes.detail` is JSON on Postgres and TEXT on sqlite.

    Reading it in Python rather than with a `->>` operator keeps this file's
    one predicate valid on both backends, the same contract migrations.py
    holds itself to. The set is 15 rows on the deployment this was written
    for, so there is nothing to gain from pushing it into SQL.
    """
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            return None
    return detail.get("censor_reason") if isinstance(detail, dict) else None


def _live_installations(conn: Connection) -> dict[int, int]:
    """github_repo_id -> the installation that actively covers it now.

    Both states must be live, and ties break on `(updated_at, id)` — newest
    registration wins — because this must agree with
    `outcome_queue._live_registration` exactly. If the two disagreed, the
    repair would requeue jobs the very next drain censors again, and the
    manifest would record a repair that did not hold.
    """
    rows = conn.execute(
        select(
            store.installation_repos.c.github_repo_id,
            store.installation_repos.c.installation_id,
        )
        .join(
            store.installations,
            store.installations.c.installation_id
            == store.installation_repos.c.installation_id,
        )
        .where(
            store.installation_repos.c.state == "active",
            store.installations.c.state == "active",
        )
        .order_by(
            store.installation_repos.c.updated_at,
            store.installation_repos.c.id,
        )
    ).all()
    # Ascending order with a plain overwrite leaves the newest row winning,
    # which is `_live_registration`'s DESC-plus-LIMIT-1 read from the other
    # end.
    return {int(repo_id): int(installation_id) for repo_id, installation_id in rows}


def inspect(conn: Connection) -> RepairReport:
    """Every censoring this transfer repair would undo. Reads only."""
    live = _live_installations(conn)
    if not live:
        return RepairReport(())

    candidates = conn.execute(
        select(store.outcomes).where(
            store.outcomes.c.kind == "censored",
            store.outcomes.c.github_repo_id.in_(live),
            store.outcomes.c.installation_id.is_not(None),
        )
        .order_by(store.outcomes.c.github_repo_id, store.outcomes.c.pr_number)
    ).mappings().all()

    rows: list[RepairRow] = []
    for row in candidates:
        successor = live[int(row["github_repo_id"])]
        if successor == int(row["installation_id"]):
            # The installation that wrote it still covers the repo, so
            # whatever made this unreachable was not a transfer.
            continue
        if _censor_reason(row["detail"]) != CENSOR_REASON_UNREACHABLE:
            continue
        job_id = conn.execute(
            select(store.outcome_jobs.c.id).where(
                store.outcome_jobs.c.installation_id == row["installation_id"],
                store.outcome_jobs.c.github_repo_id == row["github_repo_id"],
                store.outcome_jobs.c.pr_number == row["pr_number"],
                store.outcome_jobs.c.window_days == row["window_days"],
            )
        ).scalar_one_or_none()
        rows.append(
            RepairRow(
                outcome_id=int(row["id"]),
                installation_id=int(row["installation_id"]),
                github_repo_id=int(row["github_repo_id"]),
                pr_number=int(row["pr_number"]),
                window_days=int(row["window_days"]),
                successor_installation_id=successor,
                job_id=None if job_id is None else int(job_id),
            )
        )
    return RepairReport(tuple(rows))


def _serialise(row) -> dict:
    """One outcomes row as JSON, with datetimes as ISO-8601 strings."""
    out = {}
    for key, value in dict(row).items():
        out[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


def apply(
    engine: Engine, *, expect_outcomes: int, manifest_path: Path
) -> RepairReport:
    """Delete the wrong censorings and re-pend their jobs, in one transaction.

    `expect_outcomes` is the operator's assertion from a prior --dry-run. It
    is checked inside the transaction, so a set that changed between the two
    runs aborts rather than repairing a population nobody looked at.
    """
    if manifest_path.exists():
        raise RepairInvariantError(f"manifest {manifest_path} already exists")

    with engine.begin() as conn:
        report = inspect(conn)
        if report.outcomes != expect_outcomes:
            raise RepairInvariantError(
                f"expected {expect_outcomes} censored outcomes, found {report.outcomes}"
            )
        if not report.rows:
            manifest_path.write_text(json.dumps([], indent=2) + "\n")
            return report

        ids = [row.outcome_id for row in report.rows]
        deleted = conn.execute(
            select(store.outcomes).where(store.outcomes.c.id.in_(ids))
        ).mappings().all()
        # The manifest lands BEFORE the delete: a crash between the two
        # leaves a manifest naming rows that still exist, which `rollback`
        # reports as already-present. The other order loses them outright.
        manifest_path.write_text(
            json.dumps([_serialise(row) for row in deleted], indent=2) + "\n"
        )

        conn.execute(delete(store.outcomes).where(store.outcomes.c.id.in_(ids)))

        job_ids = [row.job_id for row in report.rows if row.job_id is not None]
        if job_ids:
            # attempts is left alone: these jobs did not fail an attempt,
            # they completed with the wrong answer. Zeroing it would hand a
            # genuinely broken job a fresh budget of ten.
            conn.execute(
                update(store.outcome_jobs)
                .where(store.outcome_jobs.c.id.in_(job_ids))
                .values(
                    status="pending",
                    started_at=None,
                    finished_at=None,
                    error=None,
                )
            )
    return report


def rollback(engine: Engine, *, manifest_path: Path, expect_outcomes: int) -> int:
    """Put the censored outcomes back, exactly as the manifest recorded them.

    The outcome_jobs rows are re-settled as 'done' to match, so the pair
    cannot part company — a restored censoring with a pending job would be
    adjudicated a second time and write a duplicate.
    """
    rows = json.loads(manifest_path.read_text())
    if len(rows) != expect_outcomes:
        raise RepairInvariantError(
            f"manifest holds {len(rows)} rows, expected {expect_outcomes}"
        )
    if not rows:
        return 0

    from datetime import datetime

    restored = []
    for row in rows:
        row = dict(row)
        for key in ("observed_at",):
            if isinstance(row.get(key), str):
                row[key] = datetime.fromisoformat(row[key])
        restored.append(row)

    with engine.begin() as conn:
        present = set(
            conn.execute(
                select(store.outcomes.c.id).where(
                    store.outcomes.c.id.in_([row["id"] for row in restored])
                )
            ).scalars()
        )
        missing = [row for row in restored if row["id"] not in present]
        if missing:
            conn.execute(store.outcomes.insert(), missing)
        conn.execute(
            update(store.outcome_jobs)
            .where(
                exists(
                    select(1).where(
                        and_(
                            store.outcomes.c.installation_id
                            == store.outcome_jobs.c.installation_id,
                            store.outcomes.c.github_repo_id
                            == store.outcome_jobs.c.github_repo_id,
                            store.outcomes.c.pr_number
                            == store.outcome_jobs.c.pr_number,
                            store.outcomes.c.window_days
                            == store.outcome_jobs.c.window_days,
                            store.outcomes.c.id.in_([row["id"] for row in restored]),
                        )
                    )
                )
            )
            .values(status="done")
        )
    return len(missing)
