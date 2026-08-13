"""The instrument snapshot is the publication query for Approach A.

N = count(outcome_jobs WHERE status='done') for one installation+repo.
M = count of jobs that are not done. Never count(outcomes): that table
multi-counts (design-lock.md) and would make the empty state a lie the
moment the first adjudication lands with two windows.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine

from doug import reader, store

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
INSTALLATION_ID = 100
REPO_ID = 200
OTHER_INSTALL = 101
OTHER_REPO = 201


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    assert store.enabled()
    return url


def _job(
    url: str,
    *,
    status: str,
    window_days: int = 14,
    pr_number: int = 1,
    installation_id: int = INSTALLATION_ID,
    github_repo_id: int = REPO_ID,
    merged_at: datetime = NOW - timedelta(days=20),
    due_at: datetime | None = None,
) -> int:
    row = {
        "installation_id": installation_id,
        "github_repo_id": github_repo_id,
        "pr_number": pr_number,
        "merge_commit_sha": f"{pr_number:02d}{window_days:02d}" + "a" * 36,
        "merged_at": merged_at,
        "base_ref": "main",
        "window_days": window_days,
        "due_at": due_at or (merged_at + timedelta(days=window_days)),
        "status": status,
        "attempts": 0,
        "created_at": merged_at,
    }
    with create_engine(url).begin() as conn:
        return conn.execute(store.outcome_jobs.insert(), row).inserted_primary_key[0]


def test_no_ledger_returns_none(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.instrument_snapshot(INSTALLATION_ID, REPO_ID, now=NOW) is None


def test_empty_jobs_are_zero_and_zero(tmp_path, monkeypatch):
    """The empty state is the product. Inventing a missing scoreboard would
    be a confident false claim; rendering 0 adjudicated is the honest one."""
    _db(tmp_path, monkeypatch)
    snap = store.instrument_snapshot(INSTALLATION_ID, REPO_ID, now=NOW)
    assert snap is not None
    assert snap.adjudicated == 0
    assert snap.pending == 0
    assert snap.first_due is None
    assert snap.as_of == NOW
    assert snap.deep_reads == 0
    assert snap.deep_read_cap == store.PLAN_DEEP_READ_CAP == 200
    assert snap.miss_rate is None


def test_done_jobs_are_adjudicated_and_the_rest_are_pending(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    _job(url, status="done", pr_number=1, window_days=14)
    _job(url, status="done", pr_number=1, window_days=60)
    _job(url, status="pending", pr_number=2, window_days=14)
    _job(url, status="running", pr_number=3, window_days=14)
    _job(url, status="failed", pr_number=4, window_days=14)
    snap = store.instrument_snapshot(INSTALLATION_ID, REPO_ID, now=NOW)
    assert snap.adjudicated == 2
    assert snap.pending == 3


def test_other_installations_and_repos_do_not_vote(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    _job(url, status="done", pr_number=1)
    _job(url, status="done", pr_number=2, installation_id=OTHER_INSTALL)
    _job(url, status="done", pr_number=3, github_repo_id=OTHER_REPO)
    snap = store.instrument_snapshot(INSTALLATION_ID, REPO_ID, now=NOW)
    assert snap.adjudicated == 1
    assert snap.pending == 0


def test_first_due_is_the_earliest_pending_due_at(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    later = NOW + timedelta(days=40)
    earlier = NOW + timedelta(days=3)
    _job(url, status="pending", pr_number=1, due_at=later, window_days=60)
    _job(url, status="pending", pr_number=2, due_at=earlier, window_days=14)
    _job(url, status="done", pr_number=3, due_at=NOW - timedelta(days=1))
    snap = store.instrument_snapshot(INSTALLATION_ID, REPO_ID, now=NOW)
    assert snap.first_due == earlier


def test_deep_reads_come_from_the_installation_meter_for_this_month(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    store.record_deep_read(reader.installation_scope(INSTALLATION_ID), 200, now=NOW)
    store.record_deep_read(reader.installation_scope(INSTALLATION_ID), 200, now=NOW)
    store.record_deep_read(
        reader.installation_scope(OTHER_INSTALL), 200, now=NOW
    )
    # A read in another month must not appear on this cycle's meter.
    store.record_deep_read(
        reader.installation_scope(INSTALLATION_ID),
        200,
        now=datetime(2026, 7, 1, tzinfo=UTC),
    )
    snap = store.instrument_snapshot(INSTALLATION_ID, REPO_ID, now=NOW)
    assert snap.deep_reads == 2


def test_adjudicated_is_not_count_of_outcomes_rows(tmp_path, monkeypatch):
    """Mutation proof for design-lock.md: never count(outcomes).

    Ten outcome rows against two done jobs must still report adjudicated=2.
    A query that counted the outcomes table would go green on an empty
    ledger and lie the first week adjudications exist.
    """
    url = _db(tmp_path, monkeypatch)
    _job(url, status="done", pr_number=1, window_days=14)
    _job(url, status="done", pr_number=1, window_days=60)
    with create_engine(url).begin() as conn:
        for i in range(10):
            conn.execute(
                store.outcomes.insert(),
                {
                    "repo": "drewjst/doug",
                    "pr_number": i + 1,
                    "kind": "clean",
                    "observed_at": NOW,
                    "source": "git-labels",
                    "github_repo_id": REPO_ID,
                    "installation_id": INSTALLATION_ID,
                    "window_days": 14,
                    "merge_commit_sha": f"{i:040d}",
                },
            )
    snap = store.instrument_snapshot(INSTALLATION_ID, REPO_ID, now=NOW)
    assert snap.adjudicated == 2
    assert snap.adjudicated != 10
