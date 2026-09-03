"""Executable M3 worker over the real queue and pure adjudicator."""

import subprocess
import weakref
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from githubkit.exception import RequestError
from sqlalchemy import create_engine, delete, select, update

from doug import app_auth, outcome_worker, store
from doug.backtest import git_labels
from doug.backtest.git_labels import Commit

NOW = datetime.now(UTC)
INSTALLATION_ID = 150424894
PREREG_HASH = "f" * 64


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    assert store.enabled()
    return url


def _seed_repo(
    url: str,
    repo_id: int,
    full_name: str,
    prs: list[int],
    *,
    repo_state: str = "active",
) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        if not conn.execute(
            select(store.installations.c.id).where(
                store.installations.c.installation_id == INSTALLATION_ID
            )
        ).first():
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
        conn.execute(
            store.installation_repos.insert(),
            {
                "installation_id": INSTALLATION_ID,
                "github_repo_id": repo_id,
                "full_name": full_name,
                "state": repo_state,
                "updated_at": NOW,
            },
        )
        conn.execute(
            store.outcome_jobs.insert(),
            [
                {
                    "installation_id": INSTALLATION_ID,
                    "github_repo_id": repo_id,
                    "pr_number": pr,
                    "merge_commit_sha": f"{pr:040d}",
                    "merged_at": NOW - timedelta(days=20),
                    "base_ref": "main",
                    "window_days": 14,
                    "due_at": NOW - timedelta(days=6),
                    "status": "pending",
                    "attempts": 0,
                    "created_at": NOW - timedelta(days=20),
                }
                for pr in prs
            ],
        )


def _rows(url: str, table) -> list[dict]:
    with create_engine(url).connect() as conn:
        return [dict(row) for row in conn.execute(select(table).order_by(table.c.id)).mappings()]


def _github_ready(monkeypatch, *, token="installation-secret", branch="main"):
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(
        outcome_worker, "_github_context", lambda installation_id, repo: (token, branch)
    )


def test_evidenced_loader_uses_the_shared_clone_and_parser(tmp_path, monkeypatch):
    """Calling a second matcher instead of `parse_revert_targets_evidenced`
    would let live labels diverge from the validated detector."""
    commits = [Commit(sha="a" * 40, date="2026-01-02T00:00:00+00:00", subject="Revert #7")]
    seen = {}

    def clone(owner, repo, dest, token=None):
        seen.update(owner=owner, repo=repo, dest=dest, token=token)
        return dest

    def log_records(clone_dir, token=None):
        seen.update(log_token=token)
        return commits

    monkeypatch.setattr(git_labels, "clone_treeless", clone)
    monkeypatch.setattr(git_labels, "_log_records", log_records)

    result = git_labels.find_reverted_prs_evidenced(
        "drewjst", "doug", tmp_path, token="secret"
    )

    assert result == {7: commits[0]}
    assert seen == {
        "owner": "drewjst",
        "repo": "doug",
        "dest": tmp_path / "clones" / "drewjst-doug.git",
        "token": "secret",
        # The log reads with the credential that cloned (doug#270).
        "log_token": "secret",
    }


def test_github_context_mints_for_the_job_installation_and_reads_default_branch(monkeypatch):
    """A shared or App-level clone token crosses tenant boundaries; the
    context must mint for the claimed installation and read that repo."""
    calls = []
    app = SimpleNamespace(
        rest=SimpleNamespace(
            apps=SimpleNamespace(
                create_installation_access_token=lambda installation_id: (
                    calls.append(("mint", installation_id))
                    or SimpleNamespace(parsed_data=SimpleNamespace(token="secret"))
                )
            )
        )
    )
    installation = SimpleNamespace(
        rest=SimpleNamespace(
            repos=SimpleNamespace(
                get=lambda owner, repo: (
                    calls.append(("repo", owner, repo))
                    or SimpleNamespace(parsed_data=SimpleNamespace(default_branch="trunk"))
                )
            )
        )
    )
    monkeypatch.setattr(app_auth, "app_client", lambda: app)
    monkeypatch.setattr(app_auth, "installation_client", lambda installation_id: installation)

    assert outcome_worker._github_context(INSTALLATION_ID, "drewjst/doug") == (
        "secret",
        "trunk",
    )
    assert calls == [("mint", INSTALLATION_ID), ("repo", "drewjst", "doug")]


def test_drain_clones_once_for_every_due_job_in_one_repository(tmp_path, monkeypatch):
    """Iterating jobs instead of repository keys would clone the same history
    twice and defeat the batching contract."""
    url = _db(tmp_path, monkeypatch)
    _seed_repo(url, 1, "drewjst/doug", [1, 2])
    _github_ready(monkeypatch)
    calls = []

    def evidence(owner, repo, cache_dir, token=None):
        calls.append((owner, repo, cache_dir, token))
        return {}

    monkeypatch.setattr(git_labels, "find_reverted_prs_evidenced", evidence)

    summary = outcome_worker.drain(prereg_hash=PREREG_HASH, clone_root=tmp_path / "clones")

    assert (summary.repositories, summary.done, summary.retried, summary.failed_repositories) == (
        1,
        2,
        0,
        0,
    )
    assert len(calls) == 1
    assert calls[0][3] == "installation-secret"
    assert [row["status"] for row in _rows(url, store.outcome_jobs)] == ["done", "done"]
    assert len(_rows(url, store.outcomes)) == 2


def test_removed_repo_needs_no_github_call_and_becomes_censored(tmp_path, monkeypatch):
    """Durable removal is blindness, not a clone error and never a clean
    survival; it should still close the denominator without credentials."""
    url = _db(tmp_path, monkeypatch)
    _seed_repo(url, 1, "drewjst/doug", [3], repo_state="removed")
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(
        outcome_worker,
        "_github_context",
        lambda *args: pytest.fail("removed repository must not call GitHub"),
    )

    outcome_worker.drain(prereg_hash=PREREG_HASH, clone_root=tmp_path / "clones")

    [outcome] = _rows(url, store.outcomes)
    assert outcome["kind"] == "censored"
    assert "unreachable" in outcome["detail"]


def test_clone_failure_records_one_retry_without_storing_the_token(tmp_path, monkeypatch):
    """CalledProcessError renders argv, including the credential-bearing clone
    URL. Persisting `str(exc)` would put the installation token in Cloud SQL."""
    url = _db(tmp_path, monkeypatch)
    _seed_repo(url, 1, "drewjst/doug", [4])
    token = "github_pat_secret-material"
    _github_ready(monkeypatch, token=token)

    def fail_clone(*args, **kwargs):
        raise subprocess.CalledProcessError(
            128, ["git", "clone", f"https://x-access-token:{token}@github.com/drewjst/doug"]
        )

    monkeypatch.setattr(git_labels, "find_reverted_prs_evidenced", fail_clone)

    summary = outcome_worker.drain(prereg_hash=PREREG_HASH, clone_root=tmp_path / "clones")

    assert (summary.done, summary.retried, summary.failed_repositories) == (0, 1, 1)
    [job] = _rows(url, store.outcome_jobs)
    assert (job["status"], job["attempts"]) == ("pending", 1)
    assert token not in job["error"]
    assert job["error"] == "repository evidence failed (CalledProcessError)"


def test_github_request_failure_is_a_repository_retry(tmp_path, monkeypatch):
    """An installation-scoped API outage belongs to this repository attempt,
    not to the deterministic detector or ledger failure boundary."""
    url = _db(tmp_path, monkeypatch)
    _seed_repo(url, 1, "drewjst/doug", [12])
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(
        outcome_worker,
        "_github_context",
        lambda *a, **k: (_ for _ in ()).throw(RequestError(RuntimeError("network"))),
    )

    summary = outcome_worker.drain(prereg_hash=PREREG_HASH, clone_root=tmp_path / "clones")

    assert (summary.done, summary.retried, summary.failed_repositories) == (0, 1, 1)
    [job] = _rows(url, store.outcome_jobs)
    assert (job["status"], job["attempts"]) == ("pending", 1)
    assert job["error"] == "repository evidence failed (RequestError)"


def test_one_repository_failure_does_not_block_the_next_repository(tmp_path, monkeypatch):
    """Raising out of the first repository would leave unrelated due rows
    untouched until tomorrow."""
    url = _db(tmp_path, monkeypatch)
    _seed_repo(url, 1, "drewjst/broken", [5])
    _seed_repo(url, 2, "drewjst/healthy", [6])
    _github_ready(monkeypatch)

    def evidence(owner, repo, cache_dir, token=None):
        if repo == "broken":
            raise subprocess.CalledProcessError(128, ["git", "fetch"])
        return {}

    monkeypatch.setattr(git_labels, "find_reverted_prs_evidenced", evidence)

    summary = outcome_worker.drain(prereg_hash=PREREG_HASH, clone_root=tmp_path / "clones")

    assert (summary.repositories, summary.done, summary.retried) == (2, 1, 1)
    assert [(row["github_repo_id"], row["status"]) for row in _rows(url, store.outcome_jobs)] == [
        (1, "pending"),
        (2, "done"),
    ]


def test_detector_programming_failure_fails_the_execution_loudly(tmp_path, monkeypatch):
    """Repository/network failures are retryable; a defect in the shared
    deterministic detector is systemic and must make the Cloud Run Job red."""
    url = _db(tmp_path, monkeypatch)
    _seed_repo(url, 1, "drewjst/doug", [9])
    _github_ready(monkeypatch)
    monkeypatch.setattr(
        git_labels,
        "find_reverted_prs_evidenced",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("detector defect")),
    )

    with pytest.raises(RuntimeError, match="detector defect"):
        outcome_worker.drain(prereg_hash=PREREG_HASH, clone_root=tmp_path / "clones")

    [job] = _rows(url, store.outcome_jobs)
    assert (job["status"], job["attempts"]) == ("running", 0)


def test_missing_identity_retries_without_blocking_later_repositories(tmp_path, monkeypatch):
    """A deleted installation can outlive its registry rows. With no durable
    display identity Doug cannot publish a censoring receipt, but that one
    row must not strand the rest of the daily repository snapshot."""
    url = _db(tmp_path, monkeypatch)
    _seed_repo(url, 1, "drewjst/gone", [10])
    _seed_repo(url, 2, "drewjst/healthy", [11])
    with create_engine(url).begin() as conn:
        conn.execute(
            update(store.installations)
            .where(store.installations.c.installation_id == INSTALLATION_ID)
            .values(state="deleted")
        )
        conn.execute(
            delete(store.installation_repos).where(
                store.installation_repos.c.github_repo_id == 1
            )
        )
    _github_ready(monkeypatch)
    monkeypatch.setattr(git_labels, "find_reverted_prs_evidenced", lambda *a, **k: {})

    summary = outcome_worker.drain(prereg_hash=PREREG_HASH, clone_root=tmp_path / "clones")

    assert (summary.repositories, summary.done, summary.retried) == (2, 1, 1)
    assert [(row["github_repo_id"], row["status"]) for row in _rows(url, store.outcome_jobs)] == [
        (1, "pending"),
        (2, "done"),
    ]


def test_settlement_failure_escapes_without_spending_a_repository_attempt(
    tmp_path, monkeypatch
):
    """A ledger defect is systemic, not evidence that GitHub was unavailable.
    Swallowing it would burn attempts while every Cloud Run execution looked green."""
    url = _db(tmp_path, monkeypatch)
    _seed_repo(url, 1, "drewjst/doug", [8])
    _github_ready(monkeypatch)
    monkeypatch.setattr(git_labels, "find_reverted_prs_evidenced", lambda *a, **k: {})
    monkeypatch.setattr(
        outcome_worker.outcome_queue,
        "settle_batch",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database write failed")),
    )

    with pytest.raises(RuntimeError, match="database write failed"):
        outcome_worker.drain(prereg_hash=PREREG_HASH, clone_root=tmp_path / "clones")

    [job] = _rows(url, store.outcome_jobs)
    assert (job["status"], job["attempts"]) == ("running", 0)


def test_no_due_work_needs_no_app_credentials_or_prereg_hash(tmp_path, monkeypatch):
    """An empty daily run is success. Validating credentials before checking
    the queue would turn every idle day into a failed Cloud Run execution."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setattr(app_auth, "enabled", lambda: False)

    summary = outcome_worker.drain(prereg_hash=None, clone_root=tmp_path / "clones")

    assert summary.repositories == summary.done == summary.retried == 0


def test_due_work_refuses_missing_prereg_hash_before_claiming(tmp_path, monkeypatch):
    """An outcome without the governing document hash cannot be repaired after
    publication, so configuration failure must leave the row pending."""
    url = _db(tmp_path, monkeypatch)
    _seed_repo(url, 1, "drewjst/doug", [7])
    monkeypatch.setattr(app_auth, "enabled", lambda: True)

    with pytest.raises(RuntimeError, match="DOUG_PREREG_HASH"):
        outcome_worker.drain(prereg_hash=None, clone_root=tmp_path / "clones")

    [job] = _rows(url, store.outcome_jobs)
    assert (job["status"], job["attempts"]) == ("pending", 0)


class _WeaklyHeldNamespace:
    """githubkit's `.rest`, modelled at its one load-bearing property.

    `RestVersionSwitcher.__init__` stores `ref(github)` and `_github` raises
    when that weakref is dead — pinned against real githubkit by
    `test_app_auth.py`. Reproduced here because the real client cannot answer
    a mint without a network, and a stub that holds its client strongly (the
    kind every other test in this file uses, correctly, for other questions)
    is structurally incapable of failing on the defect this test exists for.
    """

    def __init__(self, client) -> None:
        self._ref = weakref.ref(client)

    def __getattr__(self, name):
        client = self._ref()
        if client is None:
            raise RuntimeError(
                "GitHub client has already been collected. "
                "Do not use the namespace after the client has been collected."
            )
        return getattr(client.namespaces, name)


class _WeaklyHeldClient:
    def __init__(self, **namespaces) -> None:
        self.namespaces = SimpleNamespace(**namespaces)

    @property
    def rest(self):
        return _WeaklyHeldNamespace(self)


def test_github_context_holds_each_client_alive_across_its_own_call(monkeypatch):
    """The clients are used once each and never named again, which is exactly
    the shape that invites `app_client().rest.apps.mint(...)` — and that shape
    ran red in production for two days from 2026-08-17 while this file was
    green. Unbind either client in `_github_context` and this fails with the
    production error; nothing else in the suite does."""

    def fresh_app():
        return _WeaklyHeldClient(
            apps=SimpleNamespace(
                create_installation_access_token=lambda installation_id: SimpleNamespace(
                    parsed_data=SimpleNamespace(token="minted")
                )
            )
        )

    def fresh_installation(installation_id):
        return _WeaklyHeldClient(
            repos=SimpleNamespace(
                get=lambda owner, repo: SimpleNamespace(
                    parsed_data=SimpleNamespace(default_branch="trunk")
                )
            )
        )

    # Returned, never stored: the caller's binding is the only strong
    # reference there is, which is the production lifetime exactly.
    monkeypatch.setattr(app_auth, "app_client", fresh_app)
    monkeypatch.setattr(app_auth, "installation_client", fresh_installation)

    assert outcome_worker._github_context(INSTALLATION_ID, "drewjst/doug") == (
        "minted",
        "trunk",
    )
