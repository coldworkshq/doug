"""Read-only structural audit for legacy 14-day outcome rows."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select

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
