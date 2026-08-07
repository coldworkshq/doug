"""Audit and guarded repair for historical 60-day outcome-job coverage."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, case, delete, exists, false, func, literal, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Engine

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


class BackfillInvariantError(RuntimeError):
    """The database or manifest no longer matches the guarded repair contract."""


@dataclass(frozen=True)
class ApplyResult:
    inserted: int
    manifest_path: str
    report: BackfillReport

    def to_dict(self) -> dict[str, object]:
        return {
            "inserted": self.inserted,
            "manifest_path": self.manifest_path,
            "report": self.report.to_dict(),
        }


_INSERT_COLUMNS = (
    "installation_id",
    "github_repo_id",
    "pr_number",
    "merge_commit_sha",
    "merged_at",
    "base_ref",
    "window_days",
    "due_at",
    "created_at",
)
_OUTCOME_IDENTITY = (
    store.outcome_jobs.c.installation_id,
    store.outcome_jobs.c.github_repo_id,
    store.outcome_jobs.c.pr_number,
    store.outcome_jobs.c.merge_commit_sha,
    store.outcome_jobs.c.window_days,
)
_MANIFEST_COLUMNS = (
    store.outcome_jobs.c.id,
    *_OUTCOME_IDENTITY,
)
_MANIFEST_ROW_KEYS = tuple(column.name for column in _MANIFEST_COLUMNS)


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


def _structural_population():
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
    return job_14, job_60, sibling, eligible, has_sibling


def inspect(conn: Connection, *, now: datetime | None = None) -> BackfillReport:
    """Describe 14-day rows that have no structurally correct 60-day partner."""
    current = _as_utc(now) if now is not None else _db_now(conn)
    cutoff = current - timedelta(days=60)
    job_14, job_60, sibling, eligible, has_sibling = _structural_population()
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


def _insert_statement(dialect_name: str):
    job_14, _, _, eligible, has_sibling = _structural_population()
    if dialect_name == "postgresql":
        due_at = job_14.c.merged_at + literal_column("INTERVAL '60 days'")
        statement = postgresql_insert(store.outcome_jobs)
    elif dialect_name == "sqlite":
        due_at = func.datetime(job_14.c.merged_at, "+60 days")
        statement = sqlite_insert(store.outcome_jobs)
    else:
        raise RuntimeError(f"unsupported outcome_jobs dialect: {dialect_name}")
    source_query = select(
        job_14.c.installation_id,
        job_14.c.github_repo_id,
        job_14.c.pr_number,
        job_14.c.merge_commit_sha,
        job_14.c.merged_at,
        job_14.c.base_ref,
        literal(60),
        due_at,
        job_14.c.created_at,
    ).where(eligible, ~has_sibling)
    return (
        statement.from_select(_INSERT_COLUMNS, source_query)
        .on_conflict_do_nothing(index_elements=_OUTCOME_IDENTITY)
        .returning(*_MANIFEST_COLUMNS)
    )


def _require_clean_before(report: BackfillReport, expected_missing: int) -> None:
    if report.mismatches:
        raise BackfillInvariantError(
            f"found {len(report.mismatches)} mismatched 14/60 job pairs"
        )
    if report.orphan_60:
        raise BackfillInvariantError(
            f"found {report.orphan_60} registered 60-day orphan jobs"
        )
    if report.missing != expected_missing:
        raise BackfillInvariantError(
            f"expected {expected_missing} missing 60-day jobs; found {report.missing}"
        )


def _untouched_predicate():
    return and_(
        store.outcome_jobs.c.status == "pending",
        store.outcome_jobs.c.attempts == 0,
        store.outcome_jobs.c.claim_generation == 0,
        store.outcome_jobs.c.started_at.is_(None),
        store.outcome_jobs.c.finished_at.is_(None),
        store.outcome_jobs.c.error.is_(None),
    )


def _require_clean_after(
    conn: Connection, report: BackfillReport, inserted_rows: list[dict]
) -> None:
    if report.missing:
        raise BackfillInvariantError(
            f"post-insert audit found {report.missing} missing 60-day jobs"
        )
    if report.mismatches:
        raise BackfillInvariantError(
            f"post-insert audit found {len(report.mismatches)} mismatched job pairs"
        )
    if report.orphan_60:
        raise BackfillInvariantError(
            f"post-insert audit found {report.orphan_60} registered 60-day orphan jobs"
        )
    ids = [int(row["id"]) for row in inserted_rows]
    if not ids:
        return
    untouched = conn.execute(
        select(func.count())
        .select_from(store.outcome_jobs)
        .where(store.outcome_jobs.c.id.in_(ids), _untouched_predicate())
    ).scalar_one()
    if int(untouched) != len(ids):
        raise BackfillInvariantError("one or more inserted jobs are not untouched")


def _write_manifest_new(
    manifest_path: Path, created_at: datetime, inserted_rows: list[dict]
) -> None:
    payload = {
        "version": 1,
        "created_at": _as_utc(created_at).isoformat(),
        "rows": [
            {key: row[key] for key in _MANIFEST_ROW_KEYS}
            for row in sorted(inserted_rows, key=lambda item: int(item["id"]))
        ],
    }
    with manifest_path.open("x", encoding="utf-8") as manifest:
        json.dump(payload, manifest, sort_keys=True)
        manifest.write("\n")
        manifest.flush()
        os.fsync(manifest.fileno())
    directory_fd = os.open(manifest_path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def apply(
    engine: Engine,
    *,
    expected_missing: int,
    manifest_path: Path,
    now: datetime | None = None,
) -> ApplyResult:
    """Insert missing 60-day siblings and durably name the exact inserted rows."""
    if not manifest_path.is_absolute():
        raise ValueError("manifest path must be absolute")
    if os.path.lexists(manifest_path):
        raise FileExistsError(f"manifest path already exists: {manifest_path}")

    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            effective_now = _as_utc(now) if now is not None else _db_now(conn)
            before = inspect(conn, now=effective_now)
            _require_clean_before(before, expected_missing)
            inserted_rows = [
                dict(row)
                for row in conn.execute(
                    _insert_statement(conn.dialect.name)
                ).mappings()
            ]
            if len(inserted_rows) != expected_missing:
                raise BackfillInvariantError(
                    f"expected to insert {expected_missing} 60-day jobs; "
                    f"inserted {len(inserted_rows)}"
                )
            after = inspect(conn, now=effective_now)
            _require_clean_after(conn, after, inserted_rows)
            _write_manifest_new(manifest_path, effective_now, inserted_rows)
            transaction.commit()
        except BaseException:
            if transaction.is_active:
                transaction.rollback()
            raise
    return ApplyResult(len(inserted_rows), str(manifest_path), after)


def _load_manifest(manifest_path: Path, expected_count: int) -> list[dict]:
    if not manifest_path.is_absolute():
        raise ValueError("manifest path must be absolute")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise BackfillInvariantError("manifest is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict) or type(payload.get("version")) is not int:
        raise BackfillInvariantError("manifest version 1 is required")
    if payload["version"] != 1:
        raise BackfillInvariantError("manifest version 1 is required")
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise BackfillInvariantError("manifest created_at is invalid")
    try:
        _as_utc(datetime.fromisoformat(created_at))
    except ValueError as error:
        raise BackfillInvariantError("manifest created_at is invalid") from error
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise BackfillInvariantError("manifest rows must be a list")
    if len(rows) != expected_count:
        raise BackfillInvariantError(
            f"expected {expected_count} manifest rows; found {len(rows)}"
        )

    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != set(_MANIFEST_ROW_KEYS):
            raise BackfillInvariantError("manifest row has invalid fields")
        integer_keys = {
            "id",
            "installation_id",
            "github_repo_id",
            "pr_number",
            "window_days",
        }
        if any(type(row[key]) is not int for key in integer_keys):
            raise BackfillInvariantError("manifest row has invalid integer identity")
        if not isinstance(row["merge_commit_sha"], str) or row["window_days"] != 60:
            raise BackfillInvariantError("manifest row has invalid outcome identity")
        identity = tuple(row[key] for key in _MANIFEST_ROW_KEYS)
        if identity in seen:
            raise BackfillInvariantError("manifest contains duplicate rows")
        seen.add(identity)
        normalized.append(dict(row))
    return normalized


def _manifest_predicate(rows: list[dict]):
    if not rows:
        return false()
    return or_(
        *(
            and_(
                store.outcome_jobs.c.id == row["id"],
                store.outcome_jobs.c.installation_id == row["installation_id"],
                store.outcome_jobs.c.github_repo_id == row["github_repo_id"],
                store.outcome_jobs.c.pr_number == row["pr_number"],
                store.outcome_jobs.c.merge_commit_sha == row["merge_commit_sha"],
                store.outcome_jobs.c.window_days == row["window_days"],
            )
            for row in rows
        )
    )


def _require_manifest_rows(
    conn: Connection, rows: list[dict], *, lock: bool = False
) -> None:
    statement = select(store.outcome_jobs.c.id).where(_manifest_predicate(rows))
    if lock:
        statement = statement.with_for_update()
    found = conn.execute(statement).scalars().all()
    if len(found) != len(rows):
        raise BackfillInvariantError(
            f"expected {len(rows)} exact manifest rows; found {len(found)}"
        )
    untouched = conn.execute(
        select(func.count())
        .select_from(store.outcome_jobs)
        .where(_manifest_predicate(rows), _untouched_predicate())
    ).scalar_one()
    if int(untouched) != len(rows):
        raise BackfillInvariantError("one or more manifest rows are not untouched")


def verify_manifest(
    engine: Engine, *, manifest_path: Path, expected_count: int
) -> int:
    """Check exact manifest identities and untouched state on a new connection."""
    rows = _load_manifest(manifest_path, expected_count)
    with engine.connect() as conn:
        _require_manifest_rows(conn, rows)
    return len(rows)


def rollback(engine: Engine, *, manifest_path: Path, expected_count: int) -> int:
    """Delete every exact untouched manifest row in one transaction, or none."""
    rows = _load_manifest(manifest_path, expected_count)
    with engine.begin() as conn:
        _require_manifest_rows(conn, rows, lock=True)
        result = conn.execute(
            delete(store.outcome_jobs).where(
                _manifest_predicate(rows), _untouched_predicate()
            )
        )
        if result.rowcount != len(rows):
            raise BackfillInvariantError(
                f"expected to delete {len(rows)} manifest rows; deleted {result.rowcount}"
            )
    return len(rows)
