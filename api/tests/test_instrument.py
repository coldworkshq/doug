"""The instrument snapshot is the publication query for Approach A.

N = count(outcome_jobs WHERE status='done') for one installation+repo.
M = count of jobs that are not done. Never count(outcomes): that table
multi-counts (design-lock.md) and would make the empty state a lie the
moment the first adjudication lands with two windows.
"""

import inspect
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


def test_instrument_snapshot_source_does_not_name_the_outcomes_table():
    """Behavioral 10-vs-2 above still goes green if the query JOINs
    outcomes and happens to return 2. The function body itself must not
    mention the outcomes table once outcome_jobs is stripped."""
    src = inspect.getsource(store.instrument_snapshot)
    assert "select_from(outcome_jobs)" in src
    assert "outcomes" not in src.replace("outcome_jobs", "")


def test_snapshot_for_repo_resolves_via_installation_repos(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALLATION_ID, "drewjst", "User", "active")
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, "drewjst/doug")], replace=True)
    _job(url, status="done", pr_number=1, window_days=14)
    _job(url, status="pending", pr_number=2, window_days=14)
    snap = store.instrument_snapshot_for_repo("drewjst/doug", now=NOW)
    assert snap is not None
    assert snap.adjudicated == 1
    assert snap.pending == 1


def test_snapshot_for_repo_prefers_the_install_that_has_jobs(tmp_path, monkeypatch):
    """A GitHub App reinstall mints a new installation_id. The old
    outcome_jobs stay on the previous one. Picking an arbitrary active
    row would publish a live 0/0 while clocks exist."""
    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(OTHER_INSTALL, "drewjst", "User", "active")
    store.set_installation_repos(OTHER_INSTALL, [(REPO_ID, "drewjst/doug")], replace=True)
    store.upsert_installation(INSTALLATION_ID, "drewjst", "User", "active")
    store.set_installation_repos(INSTALLATION_ID, [(REPO_ID, "drewjst/doug")], replace=True)
    _job(url, status="done", pr_number=1, window_days=14)
    _job(url, status="pending", pr_number=2, window_days=14)
    snap = store.instrument_snapshot_for_repo("drewjst/doug", now=NOW)
    assert snap is not None
    assert snap.adjudicated == 1
    assert snap.pending == 1


def test_snapshot_for_an_unknown_repo_is_the_empty_instrument(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    snap = store.instrument_snapshot_for_repo("nobody/nowhere", now=NOW)
    assert snap is not None
    assert snap.adjudicated == 0
    assert snap.pending == 0
    assert snap.deep_reads == 0



def test_verify_reads_never_move_the_customers_published_meter(tmp_path, monkeypatch):
    """The loud test. If anyone reroutes verify spend, this fails immediately.

    instrument_snapshot resolves its meter with installation_scope() and the
    check-run footer renders it as `deep reads N/200`, clamped at 200. A verify
    read charged to installation:<id> would therefore appear on the customer's
    check run as allowance they never spent — and at the clamp it reads as an
    exhausted plan. That is a pricing change disguised as a feature, on a public
    surface, which is exactly the class of defect PR #106 row 2 already caught
    once (meter rendered against 200 while spend enforced at 4000).

    Charging a different prefix makes it structurally impossible rather than a
    convention: installation_from_scope does not recognise "verify:", so a
    verify read names nobody and the snapshot cannot see it.
    """
    _db(tmp_path, monkeypatch)
    paid = reader.installation_scope(INSTALLATION_ID)
    verify = reader.verify_scope(INSTALLATION_ID)

    for _ in range(3):
        assert store.record_deep_read(paid, reader.cap_for(paid), now=NOW)
    for _ in range(7):
        assert store.record_deep_read(verify, reader.cap_for(verify), now=NOW)

    snap = store.instrument_snapshot(INSTALLATION_ID, REPO_ID, now=NOW)
    assert snap is not None
    assert snap.deep_reads == 3


def test_a_verify_scope_names_nobody(tmp_path, monkeypatch):
    """installation_from_scope is how a per-installation policy reads the SAME
    string the cap charges. A verify scope must not resolve to an installation,
    or verify traffic could inherit that installation's entitlements."""
    assert reader.installation_from_scope(reader.verify_scope(INSTALLATION_ID)) is None
    assert reader.installation_from_scope(reader.verify_scope(None)) is None
    assert reader.verify_scope(INSTALLATION_ID) != reader.installation_scope(INSTALLATION_ID)


def test_verify_spends_from_its_own_budget_and_is_bounded_per_review():
    """Two separate guards, and they are guarding different things.

    The monthly cap bounds a runaway install; the per-review ceiling bounds
    latency, because every verify read is a model call inside worker.drain's
    20-jobs-sequential loop on the pool /healthz shares. Raising the per-review
    number is a throughput change as much as a spend one.
    """
    verify = reader.verify_scope(INSTALLATION_ID)
    assert reader.cap_for(verify) == reader.VERIFY_MONTHLY_READ_CAP
    assert reader.cap_for(reader.SENTINEL_SCOPE) == reader.SENTINEL_MONTHLY_READ_CAP
    assert reader.cap_for(reader.installation_scope(INSTALLATION_ID)) == (
        reader.INSTALLATION_MONTHLY_READ_CAP
    )
    assert reader.MAX_VERIFY_READS_PER_REVIEW == 2
    assert reader.verify_timeout() < reader.read_timeout()
