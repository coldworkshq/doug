"""Operator CLI contracts for the guarded 60-day outcome-job backfill."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import backfill_outcome_jobs


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _Engine:
    def __init__(self, connection: _Connection):
        self.connection = connection

    def connect(self) -> _Connection:
        return self.connection


@dataclass
class _JsonResult:
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return self.payload


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--dry-run", "--apply"],
        ["--apply"],
        ["--apply", "--expect-missing", "3"],
        ["--verify-manifest"],
        ["--verify-manifest", "--expect-count", "3"],
        ["--rollback"],
        ["--rollback", "--expect-count", "3"],
        ["--dry-run", "--expect-missing", "3"],
        ["--dry-run", "--expect-count", "3"],
        ["--dry-run", "--manifest", "/tmp/manifest.json"],
        ["--apply", "--expect-missing", "3", "--manifest", "manifest.json"],
    ],
)
def test_main_rejects_invalid_or_unsafe_mode_arguments(argv):
    """A write-capable command must not infer a mode or silently ignore its guards."""
    with pytest.raises(SystemExit, match="2"):
        backfill_outcome_jobs.main(argv)


def test_dry_run_delegates_to_inspect_and_prints_sorted_report(monkeypatch, capsys):
    """The preview is a read-only receipt from the core inspector, not CLI logic."""
    connection = _Connection()
    engine = _Engine(connection)
    report = _JsonResult({"missing": 3, "eligible_14": 4})
    calls = []
    monkeypatch.setattr(
        backfill_outcome_jobs.store, "_get_existing_schema_engine", lambda: engine
    )
    monkeypatch.setattr(
        backfill_outcome_jobs.outcome_backfill,
        "inspect",
        lambda actual_connection: calls.append(actual_connection) or report,
    )

    assert backfill_outcome_jobs.main(["--dry-run"]) == 0

    assert calls == [connection]
    assert capsys.readouterr().out == json.dumps(report.to_dict(), sort_keys=True) + "\n"


def test_dry_run_does_not_initialize_a_missing_schema(tmp_path, monkeypatch, capsys):
    """A wrong empty target must fail, not become a valid zero-row Doug database."""
    url = f"sqlite:///{tmp_path}/wrong.db"
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(OperationalError, match="no such table: outcome_jobs"):
        backfill_outcome_jobs.main(["--dry-run"])

    assert inspect(create_engine(url)).get_table_names() == []
    assert capsys.readouterr().out == ""


def test_apply_delegates_typed_guards_and_prints_result(monkeypatch, capsys):
    """Apply must pass the operator's count and absolute manifest unchanged to the engine."""
    connection = _Connection()
    engine = _Engine(connection)
    manifest = Path("/tmp/doug-60-day-test.json")
    result = _JsonResult({"inserted": 3, "manifest_path": str(manifest)})
    calls = []
    monkeypatch.setattr(
        backfill_outcome_jobs.store, "_get_existing_schema_engine", lambda: engine
    )
    monkeypatch.setattr(
        backfill_outcome_jobs.outcome_backfill,
        "apply",
        lambda actual_engine, **kwargs: calls.append((actual_engine, kwargs)) or result,
    )

    assert backfill_outcome_jobs.main(
        ["--apply", "--expect-missing", "3", "--manifest", str(manifest)]
    ) == 0

    assert calls == [(engine, {"expected_missing": 3, "manifest_path": manifest})]
    assert capsys.readouterr().out == json.dumps(result.to_dict(), sort_keys=True) + "\n"


@pytest.mark.parametrize(
    ("mode", "function_name", "receipt_key"),
    [
        ("--verify-manifest", "verify_manifest", "verified_untouched"),
        ("--rollback", "rollback", "rolled_back"),
    ],
)
def test_manifest_modes_delegate_typed_guards_and_print_receipts(
    mode, function_name, receipt_key, monkeypatch, capsys
):
    """Manifest operations expose only the exact verified or deleted row count."""
    connection = _Connection()
    engine = _Engine(connection)
    manifest = Path("/tmp/doug-60-day-test.json")
    calls = []
    monkeypatch.setattr(
        backfill_outcome_jobs.store, "_get_existing_schema_engine", lambda: engine
    )
    monkeypatch.setattr(
        backfill_outcome_jobs.outcome_backfill,
        function_name,
        lambda actual_engine, **kwargs: calls.append((actual_engine, kwargs)) or 3,
    )

    assert backfill_outcome_jobs.main(
        [mode, "--expect-count", "3", "--manifest", str(manifest)]
    ) == 0

    assert calls == [(engine, {"expected_count": 3, "manifest_path": manifest})]
    assert capsys.readouterr().out == json.dumps(
        {"manifest": str(manifest), receipt_key: 3}, sort_keys=True
    ) + "\n"


def test_main_reports_missing_database_url_to_stderr(monkeypatch, capsys):
    """An operator sees the opt-in store guard instead of a misleading empty report."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        backfill_outcome_jobs.store, "_get_existing_schema_engine", lambda: None
    )

    assert backfill_outcome_jobs.main(["--dry-run"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "DATABASE_URL not set\n"


def test_from_gcp_rewrites_the_secret_for_an_already_running_local_proxy(monkeypatch, capsys):
    """The CLI must use the operator-managed proxy, never manage one itself."""
    command = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://original")

    def read_secret(args, **kwargs):
        command.extend(args)
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        return SimpleNamespace(stdout="postgresql://user:pass@/doug?host=/cloudsql/prod\n")

    monkeypatch.setattr(backfill_outcome_jobs.subprocess, "run", read_secret)
    monkeypatch.setattr(
        backfill_outcome_jobs.store, "_get_existing_schema_engine", lambda: None
    )

    assert backfill_outcome_jobs.main(["--from-gcp", "doug-prod0", "--dry-run"]) == 1

    assert command == [
        "gcloud",
        "secrets",
        "versions",
        "access",
        "latest",
        "--secret=doug-database-url",
        "--project=doug-prod0",
    ]
    assert (
        backfill_outcome_jobs.os.environ["DATABASE_URL"]
        == "postgresql://user:pass@127.0.0.1:5433/doug"
    )
    assert capsys.readouterr().err == "DATABASE_URL not set\n"
