"""The repair for censorings a repository transfer caused.

Every test here is about a discrimination: the repair must reach the rows a
transfer wrongly censored, and must not reach anything else. Censoring is
terminal and it lowers the published miss rate, so a repair that over-reaches
is a way to manufacture a flattering number.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select

from doug import store, transfer_repair

NOW = datetime.now(UTC)
OLD = 150424894
NEW = 153075663
REPO_ID = 1314318717


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    assert store.enabled()
    store._get_engine()
    return url


def _transferred_ledger(url: str) -> None:
    """The ledger shape a completed transfer leaves: old installation gone,
    new one active, `github_repo_id` unchanged across both."""
    store.upsert_installation(OLD, "drewjst", "User", "deleted")
    store.upsert_installation(NEW, "coldworkshq", "Organization", "active")
    store.set_installation_repos(OLD, [(REPO_ID, "drewjst/doug")], replace=False)
    store.set_installation_repos(NEW, [(REPO_ID, "coldworkshq/doug")], replace=False)
    store.set_installation_repos(OLD, [], replace=True)


def _outcome(
    url: str,
    *,
    pr_number: int,
    kind: str = "censored",
    reason: str | None = "unreachable",
    installation_id: int = OLD,
    github_repo_id: int = REPO_ID,
    window_days: int = 14,
) -> int:
    detail = {
        "anchor_sha": f"{pr_number:040d}",
        "window_starts_at": NOW.isoformat(),
        "window_ends_at": NOW.isoformat(),
    }
    if reason is not None:
        detail["censor_reason"] = reason
    with create_engine(url).begin() as conn:
        return int(
            conn.execute(
                store.outcomes.insert().returning(store.outcomes.c.id),
                {
                    "repo": "coldworkshq/doug",
                    "pr_number": pr_number,
                    "kind": kind,
                    "observed_at": NOW,
                    "source": "adjudicator",
                    "github_repo_id": github_repo_id,
                    "installation_id": installation_id,
                    "window_days": window_days,
                    "detail": json.dumps(detail),
                    "merge_commit_sha": f"{pr_number:040d}",
                },
            ).scalar_one()
        )


def _job(
    url: str,
    *,
    pr_number: int,
    installation_id: int = OLD,
    github_repo_id: int = REPO_ID,
    window_days: int = 14,
    status: str = "done",
) -> int:
    with create_engine(url).begin() as conn:
        return int(
            conn.execute(
                store.outcome_jobs.insert().returning(store.outcome_jobs.c.id),
                {
                    "installation_id": installation_id,
                    "github_repo_id": github_repo_id,
                    "pr_number": pr_number,
                    "merge_commit_sha": f"{pr_number:040d}",
                    "merged_at": NOW - timedelta(days=20),
                    "base_ref": "main",
                    "window_days": window_days,
                    "due_at": NOW - timedelta(days=6),
                    "status": status,
                    "attempts": 0,
                    "created_at": NOW - timedelta(days=20),
                    "finished_at": NOW,
                },
            ).scalar_one()
        )


def _jobs(url: str) -> list[dict]:
    with create_engine(url).connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                select(store.outcome_jobs).order_by(store.outcome_jobs.c.pr_number)
            ).mappings()
        ]


def _outcome_ids(url: str) -> list[int]:
    with create_engine(url).connect() as conn:
        return list(
            conn.execute(select(store.outcomes.c.id).order_by(store.outcomes.c.id)).scalars()
        )


def test_inspect_finds_only_the_transfer_censorings(tmp_path, monkeypatch):
    """Three near-misses share the repair's shape and must all be left alone:
    a base_ref censoring is a real evidence gap, a clean row is not a
    censoring at all, and a row whose own installation still covers the repo
    was never a transfer casualty."""
    url = _db(tmp_path, monkeypatch)
    _transferred_ledger(url)
    wrong = _outcome(url, pr_number=93)
    _outcome(url, pr_number=40, reason="base_ref")
    _outcome(url, pr_number=41, kind="clean", reason=None)
    _outcome(url, pr_number=243, installation_id=NEW)

    with create_engine(url).connect() as conn:
        report = transfer_repair.inspect(conn)

    assert [row.outcome_id for row in report.rows] == [wrong]
    assert report.rows[0].successor_installation_id == NEW
    assert (report.outcomes, report.prs) == (1, 1)


def test_a_repo_with_no_live_successor_is_left_censored(tmp_path, monkeypatch):
    """A real uninstall censors correctly. Without this check the repair
    would resurrect every genuinely unreachable PR into the risk set with no
    way to ever adjudicate it."""
    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(OLD, "drewjst", "User", "deleted")
    store.set_installation_repos(OLD, [(REPO_ID, "drewjst/doug")], replace=False)
    store.set_installation_repos(OLD, [], replace=True)
    _outcome(url, pr_number=93)

    with create_engine(url).connect() as conn:
        assert transfer_repair.inspect(conn).rows == ()


def test_a_successor_under_a_dead_installation_is_not_live(tmp_path, monkeypatch):
    """Matching outcome_queue._live_registration exactly: an active junction
    row under a deleted installation is stale registration history. If the
    two disagreed, the repair would requeue jobs the worker then censors
    again on the next drain."""
    url = _db(tmp_path, monkeypatch)
    _transferred_ledger(url)
    store.upsert_installation(NEW, "coldworkshq", "Organization", "deleted")
    _outcome(url, pr_number=93)

    with create_engine(url).connect() as conn:
        assert transfer_repair.inspect(conn).rows == ()


def test_apply_deletes_the_outcome_and_repends_its_job(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    _transferred_ledger(url)
    _outcome(url, pr_number=93)
    kept = _outcome(url, pr_number=40, reason="base_ref")
    _job(url, pr_number=93)
    _job(url, pr_number=40)
    manifest = tmp_path / "manifest.json"

    report = transfer_repair.apply(
        create_engine(url), expect_outcomes=1, manifest_path=manifest
    )

    assert (report.outcomes, report.jobs) == (1, 1)
    assert _outcome_ids(url) == [kept]
    by_pr = {row["pr_number"]: row for row in _jobs(url)}
    assert by_pr[93]["status"] == "pending"
    assert by_pr[93]["finished_at"] is None
    # attempts is untouched: the job completed with a wrong answer, it did
    # not fail an attempt, so it must not be handed a fresh budget.
    assert by_pr[93]["attempts"] == 0
    # The correctly censored PR keeps both its outcome and its settled job.
    assert by_pr[40]["status"] == "done"


def test_apply_aborts_when_the_population_is_not_what_the_operator_asserted(
    tmp_path, monkeypatch
):
    """The count comes from a prior --dry-run. If the set moved in between,
    the operator is repairing a population nobody looked at."""
    url = _db(tmp_path, monkeypatch)
    _transferred_ledger(url)
    _outcome(url, pr_number=93)
    _outcome(url, pr_number=94)
    _job(url, pr_number=93)
    manifest = tmp_path / "manifest.json"

    with pytest.raises(transfer_repair.RepairInvariantError, match="expected 1"):
        transfer_repair.apply(
            create_engine(url), expect_outcomes=1, manifest_path=manifest
        )

    assert len(_outcome_ids(url)) == 2
    assert not manifest.exists(), "an aborted apply must leave no manifest"


def test_apply_refuses_to_overwrite_an_existing_manifest(tmp_path, monkeypatch):
    """The manifest is the only record of what was deleted. Overwriting one
    would strand a prior apply with no way back."""
    url = _db(tmp_path, monkeypatch)
    _transferred_ledger(url)
    _outcome(url, pr_number=93)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]\n")

    with pytest.raises(transfer_repair.RepairInvariantError, match="already exists"):
        transfer_repair.apply(
            create_engine(url), expect_outcomes=1, manifest_path=manifest
        )


def test_rollback_restores_the_row_and_re_settles_its_job(tmp_path, monkeypatch):
    """A restored censoring with a pending job would be adjudicated a second
    time and write a duplicate, so the pair moves together in both
    directions."""
    url = _db(tmp_path, monkeypatch)
    _transferred_ledger(url)
    wrong = _outcome(url, pr_number=93)
    _job(url, pr_number=93)
    manifest = tmp_path / "manifest.json"
    transfer_repair.apply(create_engine(url), expect_outcomes=1, manifest_path=manifest)

    restored = transfer_repair.rollback(
        create_engine(url), manifest_path=manifest, expect_outcomes=1
    )

    assert restored == 1
    assert _outcome_ids(url) == [wrong]
    assert _jobs(url)[0]["status"] == "done"


def test_rollback_checks_the_manifest_against_the_asserted_count(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    _transferred_ledger(url)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]\n")

    with pytest.raises(transfer_repair.RepairInvariantError, match="holds 0 rows"):
        transfer_repair.rollback(
            create_engine(url), manifest_path=manifest, expect_outcomes=15
        )


def test_rollback_is_idempotent_over_rows_that_are_already_back(tmp_path, monkeypatch):
    """Re-running must not raise a duplicate-key error partway through and
    leave the ledger half restored."""
    url = _db(tmp_path, monkeypatch)
    _transferred_ledger(url)
    _outcome(url, pr_number=93)
    _job(url, pr_number=93)
    manifest = tmp_path / "manifest.json"
    transfer_repair.apply(create_engine(url), expect_outcomes=1, manifest_path=manifest)
    transfer_repair.rollback(create_engine(url), manifest_path=manifest, expect_outcomes=1)

    assert (
        transfer_repair.rollback(
            create_engine(url), manifest_path=manifest, expect_outcomes=1
        )
        == 0
    )
    assert len(_outcome_ids(url)) == 1
