"""Cloud Run Job entrypoint for outcome-lane reconciliation."""

import pytest

from doug import app_auth, reconcile_worker, store, worker


def test_run_refuses_without_app_credentials(monkeypatch):
    monkeypatch.setattr(app_auth, "enabled", lambda: False)
    with pytest.raises(RuntimeError, match="DOUG_GITHUB_APP_ID"):
        reconcile_worker.run()


def test_run_refuses_without_a_ledger(monkeypatch):
    """A missing DATABASE_URL must turn the execution red, not report zero.

    Every store call answers as if the world were empty when the engine is
    None, so without this the Job exits 0 having healed nothing — the same
    silent gap in the outcome lane that this whole entrypoint exists to
    close, now wearing a green checkmark. Its DATABASE_URL binding is its
    own, separate from the API service's, so it can drift alone.
    """
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(store, "enabled", lambda: False)
    monkeypatch.setattr(worker, "reconcile_all_outcomes", lambda: 0)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        reconcile_worker.run()


def test_run_reports_the_windows_reconcile_all_outcomes_enqueued(monkeypatch):
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(store, "enabled", lambda: True)
    monkeypatch.setattr(worker, "reconcile_all_outcomes", lambda: 7)
    summary = reconcile_worker.run()
    assert summary.windows_enqueued == 7


def test_main_prints_the_summary_as_json(monkeypatch, capsys):
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(store, "enabled", lambda: True)
    monkeypatch.setattr(worker, "reconcile_all_outcomes", lambda: 3)
    reconcile_worker.main()
    out = capsys.readouterr().out
    assert out.strip() == '{"windows_enqueued": 3}'
