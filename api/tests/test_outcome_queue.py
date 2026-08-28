"""Durable database boundary for the scheduled outcome adjudicator."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.dialects import postgresql

from doug import outcome_backfill, outcome_queue, store
from doug.adjudicate import adjudicate
from doug.backtest.git_labels import Commit

NOW = datetime.now(UTC)
INSTALLATION_ID = 150424894
REPO_ID = 987654
REPO = "drewjst/doug"


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    assert store.enabled()
    return url


def _job(*, repo_id=REPO_ID, pr_number=1, window_days=14, **overrides):
    row = {
        "installation_id": INSTALLATION_ID,
        "github_repo_id": repo_id,
        "pr_number": pr_number,
        "merge_commit_sha": f"{pr_number:040d}",
        "merged_at": NOW - timedelta(days=20),
        "base_ref": "main",
        "window_days": window_days,
        "due_at": NOW - timedelta(days=6),
        "status": "pending",
        "attempts": 0,
        "created_at": NOW - timedelta(days=20),
    }
    return row | overrides


def _seed(url: str, *jobs: dict, repo_state: str | None = "active") -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            store.installations.insert(),
            {
                "installation_id": INSTALLATION_ID,
                "account_login": "drewjst",
                "account_type": "User",
                "state": "active",
                "updated_at": NOW,
            },
        )
        if repo_state is not None:
            conn.execute(
                store.installation_repos.insert(),
                {
                    "installation_id": INSTALLATION_ID,
                    "github_repo_id": REPO_ID,
                    "full_name": REPO,
                    "state": repo_state,
                    "updated_at": NOW,
                },
            )
        if jobs:
            conn.execute(store.outcome_jobs.insert(), list(jobs))


def _rows(url: str, table) -> list[dict]:
    with create_engine(url).connect() as conn:
        return [dict(row) for row in conn.execute(select(table).order_by(table.c.id)).mappings()]


def test_due_repositories_excludes_future_and_nonpending_rows(tmp_path, monkeypatch):
    """Removing either cutoff would adjudicate an immature window; removing
    the status filter would give a completed or failed job another vote."""
    url = _db(tmp_path, monkeypatch)
    _seed(
        url,
        _job(pr_number=1),
        _job(pr_number=2, due_at=NOW + timedelta(days=1)),
        _job(pr_number=3, status="done"),
        _job(pr_number=4, status="failed"),
        _job(pr_number=5, status="running"),
    )

    assert outcome_queue.due_repositories() == [
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    ]


def test_claim_repository_marks_all_due_rows_for_one_repo_running(tmp_path, monkeypatch):
    """Claiming one row instead of the due repository batch would buy one
    treeless clone per PR and leave same-repo work needlessly pending."""
    url = _db(tmp_path, monkeypatch)
    _seed(
        url,
        _job(pr_number=1),
        _job(pr_number=2, window_days=60),
        _job(pr_number=3, due_at=NOW + timedelta(days=1)),
    )

    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )

    assert [job["pr_number"] for job in batch.jobs] == [1, 2]
    assert all(job["status"] == "running" for job in batch.jobs)
    assert all(job["claim_generation"] == 1 for job in batch.jobs)
    rows = _rows(url, store.outcome_jobs)
    assert [row["status"] for row in rows] == ["running", "running", "pending"]


def test_backfilled_overdue_job_is_claimed_and_settled_with_its_window_identity(
    tmp_path, monkeypatch
):
    """The repair is useful only if an overdue 60-day sibling joins the real
    repository batch and produces its own exact published outcome.
    """
    old_pr = 41
    young_pr = 42
    effective_now = datetime(2026, 8, 7, 18, 0, tzinfo=UTC)
    old_merge = datetime(2026, 5, 9, 18, 0, tzinfo=UTC)
    young_merge = datetime(2026, 7, 18, 18, 0, tzinfo=UTC)
    monkeypatch.setattr(outcome_queue, "_db_now", lambda conn: effective_now)
    url = _db(tmp_path, monkeypatch)
    _seed(
        url,
        _job(
            pr_number=old_pr,
            merged_at=old_merge,
            due_at=old_merge + timedelta(days=14),
            created_at=old_merge,
        ),
        _job(
            pr_number=young_pr,
            merged_at=young_merge,
            due_at=young_merge + timedelta(days=14),
            created_at=young_merge,
        ),
    )
    engine = create_engine(url)
    outcome_backfill.apply(
        engine,
        expected_missing=2,
        manifest_path=tmp_path / "claimable.json",
        now=effective_now,
    )

    assert outcome_queue.due_repositories() == [
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    ]
    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )
    assert [(job["pr_number"], job["window_days"]) for job in batch.jobs] == [
        (old_pr, 14),
        (old_pr, 60),
        (young_pr, 14),
    ]

    result = adjudicate(batch.jobs, {}, default_branch="main")
    assert outcome_queue.settle_batch(
        batch,
        result,
        repo_full_name=REPO,
        observed_at=NOW,
        prereg_hash="f" * 64,
    ) == (3, 0)

    jobs = _rows(url, store.outcome_jobs)
    outcomes = _rows(url, store.outcomes)
    assert [row["status"] for row in jobs] == ["done", "done", "done", "pending"]
    assert len(outcomes) == 3
    for job in jobs:
        if job["status"] != "done":
            continue
        matches = [
            row
            for row in outcomes
            if row["installation_id"] == job["installation_id"]
            and row["github_repo_id"] == job["github_repo_id"]
            and row["pr_number"] == job["pr_number"]
            and row["merge_commit_sha"] == job["merge_commit_sha"]
            and row["window_days"] == job["window_days"]
        ]
        assert len(matches) == 1


def test_claim_query_compiles_to_for_update_skip_locked():
    """Without SKIP LOCKED, two manually overlapping executions block on the
    same due repository instead of dividing work safely."""
    query = outcome_queue._claim_query(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID), NOW
    )
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql


def test_reclaim_stalled_requeues_only_expired_claims(tmp_path, monkeypatch):
    """A crash must not strand a row forever, while reclaiming a live claim
    would let two workers publish the same job concurrently."""
    url = _db(tmp_path, monkeypatch)
    _seed(
        url,
        _job(
            pr_number=1,
            status="running",
            started_at=NOW - timedelta(hours=3),
            claim_generation=1,
        ),
        _job(
            pr_number=2,
            status="running",
            started_at=datetime.now(UTC),
            claim_generation=1,
        ),
    )

    assert outcome_queue.reclaim_stalled(older_than_seconds=7200) == 1
    assert [row["status"] for row in _rows(url, store.outcome_jobs)] == [
        "pending",
        "running",
    ]


def test_one_failure_spends_one_attempt_and_retries_next_run(tmp_path, monkeypatch):
    """A repository failure below the ceiling goes pending once; an inner
    retry loop would burn all ten daily opportunities in one execution."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=1), _job(pr_number=2))
    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )

    assert outcome_queue.fail_batch(batch, "repository clone failed") == 2
    rows = _rows(url, store.outcome_jobs)
    assert [(row["status"], row["attempts"]) for row in rows] == [
        ("pending", 1),
        ("pending", 1),
    ]


def test_the_tenth_failure_is_terminal(tmp_path, monkeypatch):
    """Changing >= to > would grant an eleventh attempt and violate the
    pre-registered denominator rule."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=1, attempts=9))
    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )

    outcome_queue.fail_batch(batch, "still unreachable")

    [row] = _rows(url, store.outcome_jobs)
    assert (row["status"], row["attempts"]) == ("failed", 10)
    assert row["finished_at"] is not None


def test_settlement_inserts_one_outcome_and_marks_job_done_atomically(tmp_path, monkeypatch):
    """Dropping the outcome insert or the terminal job update would make the
    published numerator and denominator disagree."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=7))
    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )
    result = adjudicate(batch.jobs, {}, default_branch="main")

    assert outcome_queue.settle_batch(
        batch,
        result,
        repo_full_name=REPO,
        observed_at=NOW,
        prereg_hash="f" * 64,
    ) == (1, 0)

    [job] = _rows(url, store.outcome_jobs)
    [outcome] = _rows(url, store.outcomes)
    assert job["status"] == "done"
    assert outcome["kind"] == "clean"
    assert outcome["merge_commit_sha"] == job["merge_commit_sha"]
    detail = json.loads(outcome["detail"])
    assert detail["anchor_sha"] == job["merge_commit_sha"]
    assert detail["prereg_hash"] == "f" * 64


def test_a_lost_claim_inserts_no_outcome(tmp_path, monkeypatch):
    """Status='running' alone cannot fence a reclaimed holder; generation
    mismatch must abort before any append-only outcome is written."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=7))
    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )
    with create_engine(url).begin() as conn:
        conn.execute(
            update(store.outcome_jobs)
            .where(store.outcome_jobs.c.id == batch.jobs[0]["id"])
            .values(claim_generation=2)
        )
    result = adjudicate(batch.jobs, {}, default_branch="main")

    with pytest.raises(outcome_queue.LostClaim):
        outcome_queue.settle_batch(
            batch,
            result,
            repo_full_name=REPO,
            observed_at=NOW,
            prereg_hash="f" * 64,
        )

    assert _rows(url, store.outcomes) == []


def test_an_unparseable_revert_retries_only_its_job(tmp_path, monkeypatch):
    """One malformed commit date must not fail unrelated jobs or silently
    turn the affected PR into a clean outcome."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=1), _job(pr_number=2))
    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )
    result = adjudicate(
        batch.jobs,
        {1: Commit(sha="a" * 40, date="2026-08-01T00:00:00+24:00", subject="Revert #1")},
        default_branch="main",
    )

    assert outcome_queue.settle_batch(
        batch,
        result,
        repo_full_name=REPO,
        observed_at=NOW,
        prereg_hash="f" * 64,
    ) == (1, 1)

    rows = _rows(url, store.outcome_jobs)
    assert [(row["pr_number"], row["status"], row["attempts"]) for row in rows] == [
        (1, "pending", 1),
        (2, "done", 0),
    ]
    assert [row["pr_number"] for row in _rows(url, store.outcomes)] == [2]


def test_removed_repo_is_permanent_but_missing_registry_is_not(tmp_path, monkeypatch):
    """Absence of a tenancy row is not evidence of an uninstall. Treating it
    as permanent would censor an MT0/backfill gap in the flattering direction."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=1), repo_state="removed")
    removed = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )
    assert removed.repo_full_name == REPO
    assert removed.permanently_unreachable is True

    other_url = f"sqlite:///{tmp_path}/missing.db"
    monkeypatch.setenv("DATABASE_URL", other_url)
    assert store.enabled()
    _seed(other_url, _job(pr_number=1), repo_state=None)
    missing = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )
    assert missing.permanently_unreachable is False
    assert missing.repo_full_name is None


def test_suspended_installation_retries_instead_of_censoring(tmp_path, monkeypatch):
    """GitHub can unsuspend an installation. Calling that permanent blindness
    would remove its jobs from the risk set in the flattering direction."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=9))
    with create_engine(url).begin() as conn:
        conn.execute(
            update(store.installations)
            .where(store.installations.c.installation_id == INSTALLATION_ID)
            .values(state="suspended")
        )

    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )

    assert batch.permanently_unreachable is False


SUCCESSOR_ID = 153075663
SUCCESSOR_REPO = "coldworkshq/doug"


def _transfer(url: str, *, old_installation_state: str, junction_state: str) -> None:
    """Put the ledger in the shape a repository transfer leaves behind.

    The repo id never moves; the registration does. `_seed` has already
    written the old installation and its junction row, so this only ages
    those and adds the live pair.
    """
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            update(store.installations)
            .where(store.installations.c.installation_id == INSTALLATION_ID)
            .values(state=old_installation_state)
        )
        conn.execute(
            update(store.installation_repos)
            .where(store.installation_repos.c.installation_id == INSTALLATION_ID)
            .values(state=junction_state)
        )
        conn.execute(
            store.installations.insert(),
            {
                "installation_id": SUCCESSOR_ID,
                "account_login": "coldworkshq",
                "account_type": "Organization",
                "state": "active",
                "updated_at": NOW,
            },
        )
        conn.execute(
            store.installation_repos.insert(),
            {
                "installation_id": SUCCESSOR_ID,
                "github_repo_id": REPO_ID,
                "full_name": SUCCESSOR_REPO,
                "state": "active",
                "updated_at": NOW,
            },
        )


def test_a_transferred_repository_is_adjudicated_not_censored(tmp_path, monkeypatch):
    """A transfer leaves the old installation looking exactly like an
    uninstall — junction 'removed', installation 'deleted' — while the
    repository stays perfectly readable under its new owner. Censoring on
    that empties the risk set in the flattering direction, which is what
    happened to PRs 93-107 of this repo after the 2026-08-26 org move.
    """
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=1))
    _transfer(url, old_installation_state="deleted", junction_state="removed")

    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )

    assert batch.permanently_unreachable is False
    assert batch.repo_full_name == SUCCESSOR_REPO
    # The token is minted for whoever can actually reach the repo...
    assert batch.reader_installation_id == SUCCESSOR_ID
    # ...but the job, and the outcome it will settle into, still belong to
    # the installation that paid for the verdict.
    assert batch.key.installation_id == INSTALLATION_ID


def test_an_uninstalled_repository_with_no_successor_still_censors(tmp_path, monkeypatch):
    """The redirect must not become a way to never censor anything. With no
    other live registration for the id, a real uninstall is still permanent
    blindness and its jobs must leave the risk set."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=1), repo_state="removed")
    with create_engine(url).begin() as conn:
        conn.execute(
            update(store.installations)
            .where(store.installations.c.installation_id == INSTALLATION_ID)
            .values(state="deleted")
        )

    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )

    assert batch.permanently_unreachable is True
    assert batch.reader_installation_id == INSTALLATION_ID


def test_a_successor_registration_under_a_dead_installation_is_not_live(
    tmp_path, monkeypatch
):
    """An active junction row under a deleted installation is stale
    registration history, not a reachable repository. Reading it as a
    successor would mint a token GitHub refuses and retry forever."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=1), repo_state="removed")
    _transfer(url, old_installation_state="deleted", junction_state="removed")
    with create_engine(url).begin() as conn:
        conn.execute(
            update(store.installations)
            .where(store.installations.c.installation_id == SUCCESSOR_ID)
            .values(state="deleted")
        )

    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )

    assert batch.permanently_unreachable is True
    assert batch.reader_installation_id == INSTALLATION_ID


def test_a_live_installation_never_consults_the_successor_lookup(tmp_path, monkeypatch):
    """The redirect is reached only when the row would otherwise be censored.
    A healthy installation keeps adjudicating through its own token even when
    another installation also registers the same repo id — which is the
    during-transfer overlap, where both are briefly active."""
    url = _db(tmp_path, monkeypatch)
    _seed(url, _job(pr_number=1))
    _transfer(url, old_installation_state="active", junction_state="active")

    batch = outcome_queue.claim_repository(
        outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
    )

    assert batch.permanently_unreachable is False
    assert batch.repo_full_name == REPO
    assert batch.reader_installation_id == INSTALLATION_ID
