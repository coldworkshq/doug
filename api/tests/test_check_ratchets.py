"""The ratchets fail on the regressions they exist for and pass their neighbours.

A ratchet that cannot fail reads as protection. Each check in
`.github/scripts/check_ratchets.py` is shown red here on a known-wrong input,
next to the nearest legitimate change it must let through.
"""

import sys
import tomllib
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".github" / "scripts"))

import check_ratchets as cr


def test_the_debt_table_is_one_sorted_entry_per_file() -> None:
    table = cr.minimal_debt([("b.py", "C901"), ("a.py", "S101"), ("b.py", "BLE001")])
    assert table == {"a.py": ["S101"], "b.py": ["BLE001", "C901"]}
    assert list(table) == ["a.py", "b.py"]


def test_a_fixed_violation_leaves_a_stale_entry_that_fails() -> None:
    problems = cr.debt_problems({"a.py": ["C901", "S101"]}, {"a.py": ["S101"]}, None)
    assert len(problems) == 1
    assert "stale" in problems[0] and "C901" in problems[0]


def test_a_violation_missing_from_the_table_fails() -> None:
    assert cr.debt_problems({}, {"a.py": ["BLE001"]}, None)


def test_the_table_may_not_grow_past_the_base() -> None:
    grown = {"a.py": ["C901"], "b.py": ["C901"]}
    problems = cr.debt_problems(grown, grown, {"a.py": ["C901"]})
    assert len(problems) == 1 and "C901 grew from 1 to 2" in problems[0]


def test_moving_a_module_keeps_its_debt_and_passes() -> None:
    """Growth is counted per rule, so a rename does not force paying the
    renamed file's debt in the same change."""
    moved = {"new.py": ["C901"]}
    assert cr.debt_problems(moved, moved, {"old.py": ["C901"]}) == []


def test_a_debt_run_that_sees_none_of_the_table_is_one_loud_failure() -> None:
    table = {"a.py": ["C901"], "b.py": ["S101"]}
    problems = cr.debt_problems(table, {}, table)
    assert len(problems) == 1 and "did not clear" in problems[0]


def test_the_type_baseline_may_not_grow_past_the_base() -> None:
    base = {"files": {"./doug/a.py": [{"code": "reportArgumentType"}]}}
    now = {
        "files": {
            "./doug/a.py": [{"code": "reportArgumentType"}],
            "./doug/b.py": [{"code": "reportArgumentType"}],
        }
    }
    problems = cr.grown(cr.baseline_counts(base), cr.baseline_counts(now), "type baseline")
    assert problems and "reportArgumentType grew from 1 to 2" in problems[0]


def test_a_shrunk_type_baseline_passes() -> None:
    before = Counter({"reportArgumentType": 3})
    assert cr.grown(before, Counter({"reportArgumentType": 2}), "type baseline") == []


def test_the_debt_block_is_replaced_in_place_and_idempotently() -> None:
    text = f'[a]\n{cr.BEGIN}\n"old.py" = ["E501"]\n{cr.END}\n[b]\n'
    rendered = cr.render_debt({"x.py": ["C901", "S101"]})
    out = cr.replace_debt(text, rendered)
    assert '"x.py" = ["C901", "S101"]' in out and "old.py" not in out
    assert out.endswith(f"{cr.END}\n[b]\n")
    assert cr.replace_debt(out, rendered) == out


def test_a_pyproject_without_the_markers_is_refused() -> None:
    with pytest.raises(SystemExit):
        cr.replace_debt("[tool.ruff]\n", cr.render_debt({}))


def test_the_debt_run_sees_what_the_committed_table_suppresses() -> None:
    """`lint.extend-per-file-ignores = {}` extends rather than replaces, and
    clearing that key once hid a whole debt table from this run (coldworks,
    2026-09-13). Against the real api/pyproject.toml and the real ruff."""
    config = tomllib.loads((cr.API / "pyproject.toml").read_text())
    committed = cr.pairs(cr.debt(config) or {})
    assert committed, "the committed debt table is empty or unreadable"
    assert committed & set(cr.ruff_violations())
