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


def _inline(*entries: tuple[str, str, int]) -> cr.Suppressions:
    return Counter({(path, rule): n for path, rule, n in entries})


def test_a_new_inline_suppression_fails_against_the_base() -> None:
    """The hole this ratchet closes: a `# noqa` never entered the debt table,
    so the blind-except count went from 39 to 69 under a green ratchet."""
    base = _inline(("a.py", "noqa: BLE001", 1))
    now = _inline(("a.py", "noqa: BLE001", 1), ("b.py", "noqa: BLE001", 1))
    assert cr.suppression_problems(now, base) == [
        "inline `noqa: BLE001` grew from 1 to 2 in b.py; fix the code instead of silencing it"
    ]


def test_a_suppression_under_a_new_rule_counts_as_growth() -> None:
    base = _inline(("a.py", "noqa: BLE001", 1))
    now = _inline(("a.py", "noqa: BLE001", 1), ("a.py", "type: ignore[index]", 1))
    assert cr.suppression_problems(now, base)


def test_moving_a_suppression_between_files_passes() -> None:
    """Counted per rule, like the debt table, so a refactor that moves a
    silenced line does not have to fix it in the same change."""
    base = _inline(("old.py", "noqa: BLE001", 2))
    now = _inline(("old.py", "noqa: BLE001", 1), ("new.py", "noqa: BLE001", 1))
    assert cr.suppression_problems(now, base) == []


def test_paying_one_down_passes_and_needs_nothing_regenerated() -> None:
    base = _inline(("a.py", "noqa: BLE001", 3))
    assert cr.suppression_problems(_inline(("a.py", "noqa: BLE001", 2)), base) == []


def test_each_code_in_a_type_comment_is_one_suppression() -> None:
    source = (
        "a = f()  # pyright: ignore[reportA, reportB]\n"
        "b = g()  # type: ignore[index]\n"
        "c = h()  # type: ignore\n"
    )
    assert sorted(cr.type_suppressions(source)) == [
        "pyright: ignore[reportA]",
        "pyright: ignore[reportB]",
        "type: ignore",
        "type: ignore[index]",
    ]


def test_suppression_text_inside_a_string_is_not_counted() -> None:
    """A test or a docstring that quotes the syntax silences nothing."""
    assert list(cr.type_suppressions('s = "x  # type: ignore[index]"\n')) == []


def test_a_file_comment_that_loosens_pyright_counts_and_strict_does_not() -> None:
    source = "# pyright: basic\n# pyright: reportAny=false\n# pyright: strict\n"
    assert list(cr.type_suppressions(source)) == ["pyright: basic", "pyright: reportAny=false"]


def test_the_noqa_count_is_what_ruff_honours(tmp_path: Path) -> None:
    """Against the real ruff: a used noqa and a file-level one count once
    each; a dead noqa, an unsilenced violation, and the same text in a
    string count nothing (RUF100 fails the dead one instead)."""
    (tmp_path / "pyproject.toml").write_text('[tool.ruff.lint]\nselect = ["BLE001", "F401"]\n')
    (tmp_path / "a.py").write_text(
        "try:\n"
        "    pass\n"
        "except Exception:  # noqa: BLE001 - counted\n"
        "    pass\n"
        "x = 1  # noqa: BLE001 - dead, silences nothing\n"
        "try:\n"
        "    pass\n"
        "except Exception:\n"
        "    pass\n"
        's = "# noqa: BLE001"\n'
    )
    (tmp_path / "b.py").write_text("# ruff: noqa: F401\nimport os\n")
    assert cr.inline_suppressions(tmp_path) == _inline(
        ("a.py", "noqa: BLE001", 1), ("b.py", "noqa: F401", 1)
    )


def test_the_base_tree_is_its_own_files_and_config(tmp_path: Path) -> None:
    """The base is counted from the merge base's api/ tree, never the working
    tree, and with the base's own ruff config: without api/pyproject.toml
    ruff would lint the base with its defaults and miscount it."""
    cr.extract_tree("HEAD", tmp_path)
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    listed = cr._git("ls-tree", "-r", "--name-only", "HEAD").stdout.split()
    expected = {p for p in listed if cr.LINTED.search(p)}
    assert "api/pyproject.toml" in expected
    assert written == expected
