"""Read-only structural audit for historical 60-day outcome-job coverage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.engine import Connection

from . import store


@dataclass(frozen=True)
class RepositoryCount:
    installation_id: int
    github_repo_id: int
    missing: int
    overdue: int


@dataclass(frozen=True)
class PairMismatch:
    job_14_id: int
    job_60_id: int
    fields: tuple[str, ...]


@dataclass(frozen=True)
class BackfillReport:
    eligible_14: int
    existing_60: int
    missing: int
    overdue: int
    orphan_60: int
    by_repository: tuple[RepositoryCount, ...]
    mismatches: tuple[PairMismatch, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible_14": self.eligible_14,
            "existing_60": self.existing_60,
            "missing": self.missing,
            "overdue": self.overdue,
            "orphan_60": self.orphan_60,
            "by_repository": [asdict(row) for row in self.by_repository],
            "mismatches": [asdict(row) for row in self.mismatches],
        }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _db_now(conn: Connection) -> datetime:
    if conn.dialect.name == "sqlite":
        return datetime.now(UTC)
    value = conn.execute(select(func.clock_timestamp())).scalar_one()
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return _as_utc(value)


def inspect(conn: Connection, *, now: datetime | None = None) -> BackfillReport:
    """Describe 14-day rows that have no structurally correct 60-day partner."""
    current = _as_utc(now) if now is not None else _db_now(conn)
    cutoff = current - timedelta(days=60)
    job_14 = store.outcome_jobs.alias("job_14")
    job_60 = store.outcome_jobs.alias("job_60")
    sibling = and_(
        job_14.c.installation_id == job_60.c.installation_id,
        job_14.c.github_repo_id == job_60.c.github_repo_id,
        job_14.c.pr_number == job_60.c.pr_number,
        job_14.c.merge_commit_sha == job_60.c.merge_commit_sha,
        job_14.c.window_days == 14,
        job_60.c.window_days == 60,
    )
    real_installation = exists(
        select(1).where(store.installations.c.installation_id == job_14.c.installation_id)
    )
    eligible = and_(job_14.c.window_days == 14, real_installation)
    has_sibling = exists(select(1).select_from(job_60).where(sibling))
    missing = ~has_sibling
    overdue = and_(missing, job_14.c.merged_at <= cutoff)

    counts = conn.execute(
        select(
            func.count().label("eligible_14"),
            func.sum(case((has_sibling, 1), else_=0)).label("existing_60"),
            func.sum(case((missing, 1), else_=0)).label("missing"),
            func.sum(case((overdue, 1), else_=0)).label("overdue"),
        ).select_from(job_14).where(eligible)
    ).one()

    orphan_real_installation = exists(
        select(1).where(store.installations.c.installation_id == job_60.c.installation_id)
    )
    orphan_60 = conn.execute(
        select(func.count())
        .select_from(job_60)
        .where(
            job_60.c.window_days == 60,
            orphan_real_installation,
            ~exists(select(1).select_from(job_14).where(sibling)),
        )
    ).scalar_one()

    repository_rows = conn.execute(
        select(
            job_14.c.installation_id,
            job_14.c.github_repo_id,
            func.sum(case((missing, 1), else_=0)).label("missing"),
            func.sum(case((overdue, 1), else_=0)).label("overdue"),
        )
        .where(eligible)
        .group_by(job_14.c.installation_id, job_14.c.github_repo_id)
        .order_by(job_14.c.installation_id, job_14.c.github_repo_id)
    ).all()

    pairs = conn.execute(
        select(
            job_14.c.id.label("job_14_id"),
            job_60.c.id.label("job_60_id"),
            job_14.c.merged_at.label("merged_at_14"),
            job_60.c.merged_at.label("merged_at_60"),
            job_14.c.base_ref.label("base_ref_14"),
            job_60.c.base_ref.label("base_ref_60"),
            job_60.c.due_at.label("due_at_60"),
        )
        .select_from(job_14.join(job_60, sibling))
        .where(eligible)
        .order_by(job_14.c.id, job_60.c.id)
    ).mappings()
    mismatches = []
    for pair in pairs:
        expected_due = _as_utc(pair["merged_at_14"]) + timedelta(days=60)
        fields = tuple(
            name
            for name, differs in (
                ("merged_at", _as_utc(pair["merged_at_14"]) != _as_utc(pair["merged_at_60"])),
                ("base_ref", pair["base_ref_14"] != pair["base_ref_60"]),
                ("due_at", expected_due != _as_utc(pair["due_at_60"])),
            )
            if differs
        )
        if fields:
            mismatches.append(
                PairMismatch(int(pair["job_14_id"]), int(pair["job_60_id"]), fields)
            )

    return BackfillReport(
        eligible_14=int(counts.eligible_14),
        existing_60=int(counts.existing_60 or 0),
        missing=int(counts.missing or 0),
        overdue=int(counts.overdue or 0),
        orphan_60=int(orphan_60),
        by_repository=tuple(
            RepositoryCount(
                installation_id=int(row.installation_id),
                github_repo_id=int(row.github_repo_id),
                missing=int(row.missing or 0),
                overdue=int(row.overdue or 0),
            )
            for row in repository_rows
        ),
        mismatches=tuple(mismatches),
    )
