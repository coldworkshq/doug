"""Cloud Run Job entrypoint for outcome-lane reconciliation."""

import pytest

from doug import app_auth, reconcile_worker, worker


def test_run_refuses_without_app_credentials(monkeypatch):
    monkeypatch.setattr(app_auth, "enabled", lambda: False)
    with pytest.raises(RuntimeError, match="DOUG_GITHUB_APP_ID"):
        reconcile_worker.run()


def test_run_reports_the_windows_reconcile_all_outcomes_enqueued(monkeypatch):
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(worker, "reconcile_all_outcomes", lambda: 7)
    summary = reconcile_worker.run()
    assert summary.windows_enqueued == 7


def test_main_prints_the_summary_as_json(monkeypatch, capsys):
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(worker, "reconcile_all_outcomes", lambda: 3)
    reconcile_worker.main()
    out = capsys.readouterr().out
    assert out.strip() == '{"windows_enqueued": 3}'
