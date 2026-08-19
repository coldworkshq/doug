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


# ---------------------------------------------------------------- repo field


def test_a_row_without_repo_defaults_to_doug():
    # The rows written before Doug reviewed anything but itself carry no repo
    # key. Absence has to keep meaning "doug", or adding the field invalidates
    # the denominator it exists to protect. Pinned on the property, not on the
    # file's current contents — external-repo rows are expected to land there.
    row = fl.parse_row(
        {
            "date": "2026-08-02",
            "pr": 28,
            "layer": "doug",
            "rule": "reader:missing-import",
            "verdict": "disproved",
            "changed": False,
            "settled_by": "api/doug/api.py:7",
            "source": "prospective",
        }
    )
    assert row.repo == "doug"


def test_external_rows_do_not_enter_dougs_denominator():
    # The reason the field exists. Doug's own rate must be identical whether or
    # not another repository's findings are in the file.
    rows = fl.check(REPO_LOG)
    doug_only = fl.rates(rows, repo="doug")
    assert doug_only.by_repo == {"doug": doug_only.n}
    assert doug_only.n == sum(1 for r in rows if r.source == "prospective" and r.repo == "doug")


def test_repo_must_be_a_slug():
    # A typo does not fail loudly on its own — it silently splits one
    # repository's rate into two — so the shape is pinned here.
    for bad in ("Coldworks", "cold works", "", "cold_works", 7):
        with pytest.raises(fl.FindingsLogError, match="repo"):
            fl.parse_row(
                {
                    "date": "2026-08-19",
                    "pr": 6,
                    "layer": "doug",
                    "rule": "x",
                    "verdict": "real",
                    "changed": True,
                    "settled_by": "here",
                    "source": "prospective",
                    "repo": bad,
                }
            )


def _row(repo: str, verdict: str = "real") -> fl.FindingRow:
    return fl.FindingRow(
        date="2026-08-19",
        pr=6,
        layer="doug",
        rule="r",
        verdict=verdict,
        changed=False,
        settled_by="s",
        source="prospective",
        repo=repo,
    )


def test_rates_scope_to_one_repo():
    rows = [_row("doug"), _row("doug", "disproved"), _row("coldworks")]
    everything = fl.rates(rows)
    assert everything.n == 3
    assert everything.by_repo == {"doug": 2, "coldworks": 1}

    # A share across two repositories describes neither, which is the whole
    # reason the field was added.
    scoped = fl.rates(rows, repo="doug")
    assert scoped.n == 2
    assert scoped.by_verdict == {"real": 1, "disproved": 1}
    assert fl.rates(rows, repo="coldworks").n == 1


def test_append_records_the_repo(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text("")
    fl.append(
        pr=6,
        layer="doug",
        repo="coldworks",
        rule="reader:dead-code",
        verdict="real",
        changed=True,
        settled_by="scripts/m4_battery.py:238",
        when="2026-08-19",
        path=path,
    )
    assert json.loads(path.read_text())["repo"] == "coldworks"
    assert fl.check(path)[0].repo == "coldworks"


def test_cli_append_requires_repo(tmp_path, capsys):
    path = tmp_path / "log.jsonl"
    path.write_text("")
    # argparse exits 2 on a missing required option; the point of the pin is
    # that a caller cannot omit the repository and land in doug's denominator.
    with pytest.raises(SystemExit):
        fl.main(
            [
                "--path",
                str(path),
                "append",
                "--pr",
                "6",
                "--layer",
                "doug",
                "--rule",
                "x",
                "--verdict",
                "real",
                "--changed",
                "--settled-by",
                "y",
            ]
        )
