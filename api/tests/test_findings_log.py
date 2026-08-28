"""Pins the REVIEWING.md denominator schema and prospective-only rates."""

import json
from pathlib import Path

import pytest

from doug import findings_log as fl
from doug import patterns

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
            rule="reader:a",
            verdict="disproved",
            changed=False,
            settled_by="x",
            source="backfill",
        ),
        fl.FindingRow(
            date="2026-08-03",
            pr=2,
            layer="doug",
            rule="reader:b",
            verdict="real",
            changed=True,
            settled_by="y",
            source="prospective",
        ),
        fl.FindingRow(
            date="2026-08-03",
            pr=3,
            layer="agent-reviewer",
            rule="reader:c",
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
                "rule": "reader:x",
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
                    "rule": "reader:x",
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
        rule="reader:r",
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
                "reader:x",
                "--verdict",
                "real",
                "--changed",
                "--settled-by",
                "y",
            ]
        )


def test_findings_log_and_patterns_name_the_reader_the_same_way():
    # The two modules slice on the same string. If one is retyped and the other
    # is not, `patterns.from_rule` and `rates(rule_prefix=...)` would disagree
    # about which rows are reader findings while both looked correct.
    assert fl.prefix_of("reader:missing-import") == patterns.RULE_PREFIX
    assert patterns.from_rule("reader:missing-import") == "missing-import"


def test_a_rule_must_name_the_instrument_that_raised_it():
    # Without a prefix a row lands in whatever share happens to be computed
    # next. `patterns.from_rule` already refuses to pool vocabularies; the
    # schema has to refuse to accept an untagged one in the first place.
    for bad in (
        "missing-import",
        ":missing-import",
        "reader:",
        "Reader:x",
        "read er:x",
        # The slug half is pinned for the same reason, and these are reachable:
        # `category_slug` is a free-form schema string, so the reader can emit
        # any of them, and `patterns.normalize` would group each as its own
        # pattern beside the kebab-case spelling of the same defect.
        "reader:Foo Bar",
        "reader: x",
        "reader:missing_import",
        "reader:missing-import ",
    ):
        with pytest.raises(fl.FindingsLogError, match="rule"):
            fl.parse_row(
                {
                    "date": "2026-08-27",
                    "pr": 235,
                    "layer": "doug",
                    "rule": bad,
                    "verdict": "real",
                    "changed": True,
                    "settled_by": "here",
                    "source": "prospective",
                }
            )


def _rule_row(rule: str, verdict: str = "real") -> fl.FindingRow:
    return fl.FindingRow(
        date="2026-08-27",
        pr=235,
        layer="doug",
        rule=rule,
        verdict=verdict,
        changed=False,
        settled_by="s",
        source="prospective",
    )


def test_rates_scope_to_one_rule_prefix():
    rows = [
        _rule_row("reader:missing-import", "disproved"),
        _rule_row("reader:unsafe-migration"),
        _rule_row("deviation:contradicts-ticket"),
    ]
    everything = fl.rates(rows)
    assert everything.n == 3
    # Unscoped, the split is always visible, so a pooled share cannot be quoted
    # unaware — the same guarantee `by_repo` gives.
    assert everything.by_rule_prefix == {"reader:": 2, "deviation:": 1}

    scoped = fl.rates(rows, rule_prefix="reader:")
    assert scoped.n == 2
    assert scoped.by_verdict == {"real": 1, "disproved": 1}
    assert fl.rates(rows, rule_prefix="deviation:").n == 1
    # A caller who drops the colon gets the rows, not a silent zero they would
    # read as a measurement.
    assert fl.rates(rows, rule_prefix="reader").n == 2


def test_a_foreign_prefix_row_cannot_move_the_reader_share():
    # The defect this pins (#235): `rates` split by verdict, layer and repo but
    # not by instrument, so the plan lane's deviation findings — which run at a
    # different real rate — were averaged into the reader's published share.
    rows = fl.check(REPO_LOG)
    before = fl.rates(rows, repo="doug", rule_prefix="reader:")
    after = fl.rates(
        [*rows, _rule_row("deviation:contradicts-ticket"), _rule_row("security:hardcoded-secret")],
        repo="doug",
        rule_prefix="reader:",
    )
    assert after.as_dict() == before.as_dict()
    # And the reverse: pooled, those two rows do move it, which is why the
    # scoped call is the one a published number comes from.
    pooled = fl.rates([*rows, _rule_row("deviation:x"), _rule_row("security:y")], repo="doug")
    assert pooled.as_dict() != fl.rates(rows, repo="doug").as_dict()


def test_the_committed_log_has_no_untagged_rules():
    # The 20 rows that predated the prefix requirement were reader findings
    # recorded without the tag (commits 7fa5869 and da43e13 for the prospective
    # nine, 3f7d156 for the backfill eleven). Leaving them untagged would have
    # traded a reader share inflated by foreign rows for one deflated by its
    # own.
    prefixes = {fl.prefix_of(r.rule) for r in fl.check(REPO_LOG)}
    assert fl.NO_PREFIX not in prefixes


def test_append_refuses_an_untagged_rule_before_writing(tmp_path):
    # append() re-parses through the same gate `check` uses, so the disposition
    # is refused rather than written and found later. It does not guess the
    # prefix: which instrument raised a finding is not derivable from its slug.
    path = tmp_path / "log.jsonl"
    path.write_text("")
    with pytest.raises(fl.FindingsLogError, match="rule"):
        fl.append(
            pr=235,
            layer="doug",
            repo="doug",
            rule="missing-import",
            verdict="real",
            changed=True,
            settled_by="here",
            path=path,
        )
    assert path.read_text() == ""
