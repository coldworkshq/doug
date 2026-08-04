"""Pins the REVIEWING.md denominator schema and prospective-only rates."""

import json
from pathlib import Path

import pytest

from doug import findings_log as fl

REPO_LOG = Path(__file__).resolve().parents[2] / "docs" / "findings-log.jsonl"


def test_default_log_path_points_at_repo_docs():
    assert fl.default_log_path() == REPO_LOG
    assert REPO_LOG.is_file()


def test_checked_in_log_validates():
    rows = fl.check(REPO_LOG)
    assert len(rows) >= 12
    assert all(r.source in ("prospective", "backfill") for r in rows)


def test_rates_exclude_backfill():
    rows = [
        fl.FindingRow(
            date="2026-08-03",
            pr=1,
            layer="doug",
            rule="a",
            verdict="disproved",
            changed=False,
            settled_by="x",
            source="backfill",
        ),
        fl.FindingRow(
            date="2026-08-03",
            pr=2,
            layer="doug",
            rule="b",
            verdict="real",
            changed=True,
            settled_by="y",
            source="prospective",
        ),
        fl.FindingRow(
            date="2026-08-03",
            pr=3,
            layer="agent-reviewer",
            rule="c",
            verdict="adjacent",
            changed=False,
            settled_by="z",
            source="prospective",
        ),
    ]
    r = fl.rates(rows)
    assert r.n == 2
    assert r.by_verdict == {"real": 1, "adjacent": 1}
    assert r.changed_true == 1
    assert "disproved" not in r.by_verdict


def test_parse_row_rejects_collapsed_verdict_changed():
    with pytest.raises(fl.FindingsLogError, match="changed"):
        fl.parse_row(
            {
                "date": "2026-08-03",
                "pr": 1,
                "layer": "doug",
                "rule": "x",
                "verdict": "real",
                "changed": "yes",
                "settled_by": "here",
                "source": "prospective",
            }
        )


def test_append_writes_prospective_only(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text("")
    row = fl.append(
        pr=44,
        layer="doug",
        rule="reader:missing-import",
        verdict="disproved",
        changed=False,
        settled_by="api/doug/api.py:7 — already imported",
        note="first prospective row",
        when="2026-08-03",
        path=path,
    )
    assert row.source == "prospective"
    loaded = fl.check(path)
    assert len(loaded) == 1
    assert loaded[0].pr == 44
    assert json.loads(path.read_text())["source"] == "prospective"


def test_cli_check_ok():
    assert fl.main(["--path", str(REPO_LOG), "check"]) == 0


def test_cli_check_rejects_bad_line(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"date":"2026-08-03"}\n')
    assert fl.main(["--path", str(bad), "check"]) == 1
