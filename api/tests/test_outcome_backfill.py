"""Structural audit and guarded repair for legacy 14-day outcome rows."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.dialects import postgresql

from doug import outcome_backfill, store

NOW = datetime(2026, 8, 7, 18, 0, tzinfo=UTC)
OLD_MERGE = NOW - timedelta(days=90)
YOUNG_MERGE = NOW - timedelta(days=20)
ACTIVE_INSTALL = 101
SUSPENDED_INSTALL = 102
DELETED_INSTALL = 103
ORPHAN_INSTALL = 104


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    assert store.enabled()
    return url


def _job(
    installation_id: int,
    github_repo_id: int,
    pr_number: int,
    *,
    merged_at: datetime,
    window_days: int = 14,
    **overrides,
) -> dict:
    return {
        "installation_id": installation_id,
        "github_repo_id": github_repo_id,
        "pr_number": pr_number,
        "merge_commit_sha": f"{pr_number:040d}",
        "merged_at": merged_at,
        "base_ref": "main",
        "window_days": window_days,
        "due_at": merged_at + timedelta(days=window_days),
        "status": "pending",
        "attempts": 0,
        "created_at": merged_at,
    } | overrides


def _seed_population(url: str) -> tuple[int, int]:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            store.installations.insert(),
            [
                {
                    "installation_id": ACTIVE_INSTALL,
                    "account_login": "active",
                    "account_type": "Organization",
                    "state": "active",
                    "updated_at": NOW,
                },
                {
                    "installation_id": SUSPENDED_INSTALL,
                    "account_login": "suspended",
                    "account_type": "Organization",
                    "state": "suspended",
                    "updated_at": NOW,
                },
                {
                    "installation_id": DELETED_INSTALL,
                    "account_login": "deleted",
                    "account_type": "Organization",
                    "state": "deleted",
                    "updated_at": NOW,
                },
            ],
        )
        active_14 = conn.execute(
            store.outcome_jobs.insert().returning(store.outcome_jobs.c.id),
            _job(ACTIVE_INSTALL, 1001, 1, merged_at=OLD_MERGE),
        ).scalar_one()
        active_60 = conn.execute(
            store.outcome_jobs.insert().returning(store.outcome_jobs.c.id),
            _job(ACTIVE_INSTALL, 1001, 1, merged_at=OLD_MERGE, window_days=60),
        ).scalar_one()
        conn.execute(
            store.outcome_jobs.insert(),
            [
                _job(ACTIVE_INSTALL, 1001, 2, merged_at=YOUNG_MERGE),
                _job(SUSPENDED_INSTALL, 1002, 3, merged_at=OLD_MERGE),
                _job(DELETED_INSTALL, 1003, 4, merged_at=OLD_MERGE),
                _job(ORPHAN_INSTALL, 1004, 5, merged_at=OLD_MERGE),
            ],
        )
    return int(active_14), int(active_60)


def _rows(conn) -> list[dict]:
    statement = select(store.outcome_jobs).order_by(store.outcome_jobs.c.id)
    return [
        dict(row)
        for row in conn.execute(statement).mappings()
    ]


def _manifest_rows(path: Path) -> list[dict]:
    return json.loads(path.read_text())["rows"]


def _untouched(row: dict) -> bool:
    return (
        row["status"] == "pending"
        and row["attempts"] == 0
        and row["claim_generation"] == 0
        and row["started_at"] is None
        and row["finished_at"] is None
        and row["error"] is None
    )


def test_inspect_counts_registered_history_without_mutating_jobs(tmp_path, monkeypatch):
    """Filtering inactive registry rows would erase historical denominator votes."""
    url = _db(tmp_path, monkeypatch)
    _seed_population(url)

    with create_engine(url).connect() as conn:
        before = _rows(conn)
        report = outcome_backfill.inspect(conn, now=NOW)
        after = _rows(conn)

    assert report.eligible_14 == 4
    assert report.existing_60 == 1
    assert report.missing == 3
    assert report.overdue == 2
    assert report.orphan_60 == 0
    assert {row.installation_id for row in report.by_repository} == {
        ACTIVE_INSTALL,
        SUSPENDED_INSTALL,
        DELETED_INSTALL,
    }
    assert before == after


def test_inspect_reports_mismatched_sibling_fields_in_fixed_order(tmp_path, monkeypatch):
    """A 60-day sibling with changed merge facts cannot be safely backfilled or trusted."""
    url = _db(tmp_path, monkeypatch)
    job_14_id, job_60_id = _seed_population(url)

    with create_engine(url).begin() as conn:
        conn.execute(
            store.outcome_jobs.update()
            .where(store.outcome_jobs.c.id == job_60_id)
            .values(
                base_ref="release",
                due_at=(OLD_MERGE + timedelta(days=61)).replace(tzinfo=None),
            )
        )
    with create_engine(url).connect() as conn:
        report = outcome_backfill.inspect(conn, now=NOW)

    assert report.mismatches == (
        outcome_backfill.PairMismatch(job_14_id, job_60_id, ("base_ref", "due_at")),
    )


def test_inspect_counts_only_registered_60_day_orphans(tmp_path, monkeypatch):
    """Counting CLI-shaped rows as an orphan would turn an unknown population
    into a repair target.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_population(url)

    with create_engine(url).begin() as conn:
        conn.execute(
            store.outcome_jobs.insert(),
            [
                _job(ACTIVE_INSTALL, 1001, 6, merged_at=OLD_MERGE, window_days=60),
                _job(ORPHAN_INSTALL, 1004, 7, merged_at=OLD_MERGE, window_days=60),
            ],
        )
    with create_engine(url).connect() as conn:
        report = outcome_backfill.inspect(conn, now=NOW)

    assert report.orphan_60 == 1


def test_apply_inserts_only_missing_siblings_and_is_idempotent(tmp_path, monkeypatch):
    """A repair that rewrites sources, includes unregistered history, or resets
    an existing sibling would change the preregistered denominator.
    """
    url = _db(tmp_path, monkeypatch)
    _seed_population(url)
    engine = create_engine(url)
    manifest = tmp_path / "apply.json"

    with engine.connect() as conn:
        before = _rows(conn)
    result = outcome_backfill.apply(
        engine, expected_missing=3, manifest_path=manifest, now=NOW
    )
    with engine.connect() as conn:
        after = _rows(conn)

    assert result.inserted == 3
    assert result.manifest_path == str(manifest)
    assert result.report.missing == 0
    assert result.to_dict()["report"] == result.report.to_dict()
    assert json.loads(manifest.read_text())["version"] == 1
    inserted_ids = {row["id"] for row in _manifest_rows(manifest)}
    inserted = [row for row in after if row["id"] in inserted_ids]
    sources = {
        (
            row["installation_id"],
            row["github_repo_id"],
            row["pr_number"],
            row["merge_commit_sha"],
        ): row
        for row in before
        if row["window_days"] == 14
    }
    assert len(inserted) == 3
    assert {row["installation_id"] for row in inserted} == {
        ACTIVE_INSTALL,
        SUSPENDED_INSTALL,
        DELETED_INSTALL,
    }
    for row in inserted:
        source = sources[
            (
                row["installation_id"],
                row["github_repo_id"],
                row["pr_number"],
                row["merge_commit_sha"],
            )
        ]
        assert row["merged_at"] == source["merged_at"]
        assert row["base_ref"] == source["base_ref"]
        assert row["created_at"] == source["created_at"]
        assert row["window_days"] == 60
        assert row["due_at"] == source["merged_at"] + timedelta(days=60)
        assert _untouched(row)

    second_manifest = tmp_path / "apply-again.json"
    second = outcome_backfill.apply(
        engine, expected_missing=0, manifest_path=second_manifest, now=NOW
    )
    with engine.connect() as conn:
        repeated = _rows(conn)
    assert second.inserted == 0
    assert _manifest_rows(second_manifest) == []
    assert repeated == after


def test_apply_preserves_sqlite_microseconds_across_a_leap_year_boundary(
    tmp_path, monkeypatch
):
    """SQLite must add calendar days without truncating the source instant."""
    merged_at = datetime(2024, 1, 31, 23, 59, 58, 123456, tzinfo=UTC)
    expected_due_at = datetime(2024, 3, 31, 23, 59, 58, 123456, tzinfo=UTC)
    url = _db(tmp_path, monkeypatch)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            store.installations.insert(),
            {
                "installation_id": ACTIVE_INSTALL,
                "account_login": "active",
                "account_type": "Organization",
                "state": "active",
                "updated_at": NOW,
            },
        )
        conn.execute(
            store.outcome_jobs.insert(),
            _job(ACTIVE_INSTALL, 1001, 31, merged_at=merged_at),
        )
    manifest = tmp_path / "microseconds.json"

    result = outcome_backfill.apply(
        engine, expected_missing=1, manifest_path=manifest, now=NOW
    )

    with engine.connect() as conn:
        rows = _rows(conn)
        clean = outcome_backfill.inspect(conn, now=NOW)
    assert result.inserted == 1
    assert result.report == clean
    assert clean.missing == 0
    assert clean.mismatches == ()
    assert expected_due_at == merged_at + timedelta(days=60)
    assert rows[1]["merged_at"] == merged_at.replace(tzinfo=None)
    assert rows[1]["due_at"] == expected_due_at.replace(tzinfo=None)
    assert _manifest_rows(manifest) == [
        {
            "github_repo_id": 1001,
            "id": rows[1]["id"],
            "installation_id": ACTIVE_INSTALL,
            "merge_commit_sha": f"{31:040d}",
            "pr_number": 31,
            "window_days": 60,
        }
    ]
    assert outcome_backfill.verify_manifest(
        engine, manifest_path=manifest, expected_count=1
    ) == 1


def test_apply_refuses_a_stale_count_without_creating_a_manifest(tmp_path, monkeypatch):
    """A count captured before the write transaction must fence population drift."""
    url = _db(tmp_path, monkeypatch)
    _seed_population(url)
    engine = create_engine(url)
    manifest = tmp_path / "stale.json"

    with pytest.raises(
        outcome_backfill.BackfillInvariantError,
        match="expected 2 missing 60-day jobs; found 3",
    ):
        outcome_backfill.apply(
            engine, expected_missing=2, manifest_path=manifest, now=NOW
        )

    assert not manifest.exists()
    with engine.connect() as conn:
        assert len(_rows(conn)) == 6


def test_apply_rejects_a_relative_manifest_before_connecting():
    """A working-directory-relative audit artifact cannot safely name a repair."""

    class NoConnect:
        def connect(self):
            raise AssertionError("database connection opened")

    with pytest.raises(ValueError, match="manifest path must be absolute"):
        outcome_backfill.apply(
            NoConnect(),
            expected_missing=0,
            manifest_path=Path("relative-manifest.json"),
            now=NOW,
        )


def test_apply_refuses_mismatches_and_registered_orphans(tmp_path, monkeypatch):
    """Repair must expose existing corruption, not hide it behind conflict handling."""
    mismatch_url = _db(tmp_path, monkeypatch)
    _, job_60_id = _seed_population(mismatch_url)
    mismatch_engine = create_engine(mismatch_url)
    with mismatch_engine.begin() as conn:
        conn.execute(
            update(store.outcome_jobs)
            .where(store.outcome_jobs.c.id == job_60_id)
            .values(base_ref="release")
        )
    mismatch_manifest = tmp_path / "mismatch.json"

    with pytest.raises(outcome_backfill.BackfillInvariantError, match="mismatched"):
        outcome_backfill.apply(
            mismatch_engine,
            expected_missing=3,
            manifest_path=mismatch_manifest,
            now=NOW,
        )
    assert not mismatch_manifest.exists()
    with mismatch_engine.connect() as conn:
        assert len(_rows(conn)) == 6

    orphan_url = f"sqlite:///{tmp_path}/orphan.db"
    monkeypatch.setenv("DATABASE_URL", orphan_url)
    assert store.enabled()
    _seed_population(orphan_url)
    orphan_engine = create_engine(orphan_url)
    with orphan_engine.begin() as conn:
        conn.execute(
            store.outcome_jobs.insert(),
            _job(ACTIVE_INSTALL, 1001, 99, merged_at=OLD_MERGE, window_days=60),
        )
        assert outcome_backfill.inspect(conn, now=NOW).orphan_60 == 1
    orphan_manifest = tmp_path / "orphan.json"

    with pytest.raises(outcome_backfill.BackfillInvariantError, match="orphan"):
        outcome_backfill.apply(
            orphan_engine,
            expected_missing=3,
            manifest_path=orphan_manifest,
            now=NOW,
        )
    assert not orphan_manifest.exists()
    with orphan_engine.connect() as conn:
        assert len(_rows(conn)) == 7


def test_manifest_creation_failures_roll_back_the_insert(tmp_path, monkeypatch):
    """The database cannot commit unless its exclusive audit artifact is durable."""
    url = _db(tmp_path, monkeypatch)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            store.installations.insert(),
            {
                "installation_id": ACTIVE_INSTALL,
                "account_login": "active",
                "account_type": "Organization",
                "state": "active",
                "updated_at": NOW,
            },
        )
        conn.execute(
            store.outcome_jobs.insert(),
            _job(ACTIVE_INSTALL, 1001, 1, merged_at=OLD_MERGE),
        )
    with engine.connect() as conn:
        before = _rows(conn)
    manifest = tmp_path / "disk-full.json"

    def fail_manifest(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(outcome_backfill, "_write_manifest_new", fail_manifest)
    with pytest.raises(OSError, match="disk full"):
        outcome_backfill.apply(
            engine, expected_missing=1, manifest_path=manifest, now=NOW
        )
    with engine.connect() as conn:
        after = _rows(conn)
    assert after == before
    assert [row["window_days"] for row in after] == [14]


def test_manifest_directory_sync_failure_rolls_back_the_insert(tmp_path, monkeypatch):
    """A durable file without its new directory entry is not a durable manifest."""
    url = _db(tmp_path, monkeypatch)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            store.installations.insert(),
            {
                "installation_id": ACTIVE_INSTALL,
                "account_login": "active",
                "account_type": "Organization",
                "state": "active",
                "updated_at": NOW,
            },
        )
        conn.execute(
            store.outcome_jobs.insert(),
            _job(ACTIVE_INSTALL, 1001, 1, merged_at=OLD_MERGE),
        )
    real_fsync = outcome_backfill.os.fsync
    calls = 0

    def fail_directory_sync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory sync failed")
        return real_fsync(fd)

    monkeypatch.setattr(outcome_backfill.os, "fsync", fail_directory_sync)
    with pytest.raises(OSError, match="directory sync failed"):
        outcome_backfill.apply(
            engine,
            expected_missing=1,
            manifest_path=tmp_path / "directory-sync.json",
            now=NOW,
        )
    with engine.connect() as conn:
        rows = _rows(conn)
    assert calls == 2
    assert [row["window_days"] for row in rows] == [14]


def test_apply_refuses_an_existing_manifest_before_mutation(tmp_path, monkeypatch):
    """Exclusive creation prevents an older audit artifact from being overwritten."""
    url = _db(tmp_path, monkeypatch)
    _seed_population(url)
    engine = create_engine(url)
    manifest = tmp_path / "existing.json"
    manifest.write_text("preserve me")

    with pytest.raises(FileExistsError):
        outcome_backfill.apply(
            engine, expected_missing=3, manifest_path=manifest, now=NOW
        )

    assert manifest.read_text() == "preserve me"
    with engine.connect() as conn:
        assert len(_rows(conn)) == 6


def test_verify_manifest_independently_requires_exact_untouched_rows(
    tmp_path, monkeypatch
):
    """An identity list is not verified while a row is missing, started, or extra."""
    url = _db(tmp_path, monkeypatch)
    _seed_population(url)
    engine = create_engine(url)
    manifest = tmp_path / "verify.json"
    outcome_backfill.apply(engine, expected_missing=3, manifest_path=manifest, now=NOW)

    assert outcome_backfill.verify_manifest(
        engine, manifest_path=manifest, expected_count=3
    ) == 3
    with pytest.raises(outcome_backfill.BackfillInvariantError, match="expected 2"):
        outcome_backfill.verify_manifest(
            engine, manifest_path=manifest, expected_count=2
        )

    changed_id = _manifest_rows(manifest)[0]["id"]
    with engine.begin() as conn:
        conn.execute(
            update(store.outcome_jobs)
            .where(store.outcome_jobs.c.id == changed_id)
            .values(status="running", claim_generation=1, started_at=NOW)
        )
    with pytest.raises(outcome_backfill.BackfillInvariantError, match="untouched"):
        outcome_backfill.verify_manifest(
            engine, manifest_path=manifest, expected_count=3
        )
    with engine.connect() as conn:
        assert conn.execute(
            select(store.outcome_jobs.c.status).where(store.outcome_jobs.c.id == changed_id)
        ).scalar_one() == "running"


def test_rollback_deletes_every_exact_manifest_row_or_none(tmp_path, monkeypatch):
    """Rollback may remove only the inserted siblings and never their 14-day sources."""
    url = _db(tmp_path, monkeypatch)
    _seed_population(url)
    engine = create_engine(url)
    manifest = tmp_path / "rollback.json"
    outcome_backfill.apply(engine, expected_missing=3, manifest_path=manifest, now=NOW)
    manifest_ids = {row["id"] for row in _manifest_rows(manifest)}

    assert outcome_backfill.rollback(
        engine, manifest_path=manifest, expected_count=3
    ) == 3
    with engine.connect() as conn:
        remaining = _rows(conn)
    assert not manifest_ids & {row["id"] for row in remaining}
    assert [row["window_days"] for row in remaining].count(14) == 5
    assert [row["window_days"] for row in remaining].count(60) == 1


@pytest.mark.parametrize("changed", [False, True])
def test_rollback_refuses_wrong_counts_or_touched_rows(tmp_path, monkeypatch, changed):
    """A failed guard must leave every manifest sibling in place as one set."""
    url = _db(tmp_path, monkeypatch)
    _seed_population(url)
    engine = create_engine(url)
    manifest = tmp_path / f"rollback-refused-{changed}.json"
    outcome_backfill.apply(engine, expected_missing=3, manifest_path=manifest, now=NOW)
    manifest_ids = {row["id"] for row in _manifest_rows(manifest)}
    if changed:
        changed_id = next(iter(manifest_ids))
        with engine.begin() as conn:
            conn.execute(
                update(store.outcome_jobs)
                .where(store.outcome_jobs.c.id == changed_id)
                .values(status="running", claim_generation=1, started_at=NOW)
            )

    with pytest.raises(outcome_backfill.BackfillInvariantError):
        outcome_backfill.rollback(
            engine,
            manifest_path=manifest,
            expected_count=3 if changed else 2,
        )
    with engine.connect() as conn:
        assert manifest_ids <= {row["id"] for row in _rows(conn)}


def test_postgresql_insert_select_uses_exact_interval_and_conflict_target():
    """PostgreSQL must dedupe only the published identity and derive from merge time."""
    sql = str(
        outcome_backfill._insert_statement("postgresql").compile(
            dialect=postgresql.dialect()
        )
    )

    assert "INTERVAL '60 days'" in sql
    assert (
        "ON CONFLICT (installation_id, github_repo_id, pr_number, "
        "merge_commit_sha, window_days) DO NOTHING"
    ) in sql


@pytest.mark.parametrize(
    ("dialect_name", "expected_events"),
    [
        (
            "postgresql",
            [
                "begin",
                "lock",
                "lock",
                "inspect",
                "insert",
                "inspect",
                "manifest",
                "commit",
            ],
        ),
        (
            "sqlite",
            ["begin", "inspect", "insert", "inspect", "manifest", "commit"],
        ),
    ],
)
def test_apply_fences_postgresql_population_in_its_write_transaction(
    tmp_path, monkeypatch, dialect_name, expected_events
):
    """The structural audit is stale if another writer can change either table
    in its population after inspection; SQLite must retain its native transaction path.
    """
    events = []
    insert_statement = object()
    clean = outcome_backfill.BackfillReport(0, 0, 0, 0, 0, (), ())

    class RecordingResult:
        def mappings(self):
            return self

        def __iter__(self):
            return iter(())

    class RecordingTransaction:
        def __init__(self):
            self.is_active = True

        def commit(self):
            events.append(("commit", connection, self, self.is_active))
            self.is_active = False

        def rollback(self):
            events.append(("rollback", connection, self, self.is_active))
            self.is_active = False

    class RecordingConnection:
        dialect = SimpleNamespace(name=dialect_name)

        def __init__(self):
            self.transaction = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def begin(self):
            self.transaction = RecordingTransaction()
            events.append(("begin", self, self.transaction, self.transaction.is_active))
            return self.transaction

        def execute(self, statement):
            name = "insert" if statement is insert_statement else "lock"
            events.append(
                (name, self, self.transaction, self.transaction.is_active, str(statement))
            )
            return RecordingResult()

    class RecordingEngine:
        def connect(self):
            return connection

    connection = RecordingConnection()

    def record_inspect(conn, *, now):
        events.append(("inspect", conn, conn.transaction, conn.transaction.is_active))
        return clean

    def record_manifest(path, created_at, rows):
        events.append(
            (
                "manifest",
                connection,
                connection.transaction,
                connection.transaction.is_active,
            )
        )

    monkeypatch.setattr(outcome_backfill, "inspect", record_inspect)
    monkeypatch.setattr(
        outcome_backfill, "_insert_statement", lambda actual_dialect: insert_statement
    )
    monkeypatch.setattr(outcome_backfill, "_write_manifest_new", record_manifest)

    outcome_backfill.apply(
        RecordingEngine(),
        expected_missing=0,
        manifest_path=tmp_path / f"{dialect_name}-lock.json",
        now=NOW,
    )

    assert [event[0] for event in events] == expected_events
    transaction = events[0][2]
    assert all(event[1] is connection for event in events)
    assert all(event[2] is transaction for event in events)
    assert all(event[3] is True for event in events)
    lock_events = [event for event in events if event[0] == "lock"]
    if dialect_name == "postgresql":
        assert [event[4] for event in lock_events] == [
            "LOCK TABLE installations IN SHARE ROW EXCLUSIVE MODE",
            "LOCK TABLE outcome_jobs IN SHARE ROW EXCLUSIVE MODE",
        ]
    else:
        assert lock_events == []
