"""The statistics behind per-pattern precision.

These are the numbers that decide which patterns get distilled, so each
test pins *why* a number must come out the way it does, not just that the
arithmetic runs.
"""

import sys
from pathlib import Path

import pytest

from doug.precision import corpus_table, fold, wilson

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from pattern_precision import _pop_precision  # noqa: E402


def test_wilson_stays_inside_zero_one_at_the_extremes():
    """Sparse patterns land on k=0 and k=n constantly; the normal
    approximation returns impossible bounds there and would print an
    interval like [-8%, 34%] next to a precision claim."""
    lo, hi = wilson(0, 7)
    assert lo == 0.0 and 0 < hi < 1
    lo, hi = wilson(5, 5)
    assert 0 < lo < 1 and hi == 1.0


def test_wilson_narrows_with_evidence():
    narrow = wilson(50, 100)
    wide = wilson(5, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_fold_treats_any_non_clean_outcome_as_a_defect():
    """A PR can collect a clean label from one source and a revert from
    another. The revert is the fact; 'clean' only ever means 'nothing
    observed yet', so it must never overwrite an observed defect."""
    join = {
        "prs": [
            {"repo": "o/r", "pr_number": 1, "kind": "clean"},
            {"repo": "o/r", "pr_number": 1, "kind": "revert"},
        ],
        "hits": [],
    }
    is_defect, _ = fold(join)
    assert is_defect == {("o/r", 1): True}


def test_fold_merges_synonyms_without_double_counting_a_pr():
    """One PR emitting two slugs that merge to one pattern is one piece of
    evidence. Counting it twice would let the merge map manufacture the
    recurrence the distillability bar is supposed to measure."""
    join = {
        "prs": [{"repo": "o/r", "pr_number": 1, "kind": "revert"}],
        "hits": [
            {"repo": "o/r", "pr_number": 1, "rule": "reader:unhandled-exception"},
            {"repo": "o/r", "pr_number": 1, "rule": "reader:missing-error-handling"},
        ],
    }
    _, carriers = fold(join)
    assert carriers == {"error-handling-gap": {("o/r", 1)}}


def test_fold_drops_hits_on_prs_with_no_known_outcome():
    join = {
        "prs": [{"repo": "o/r", "pr_number": 1, "kind": "clean"}],
        "hits": [{"repo": "o/r", "pr_number": 2, "rule": "reader:race-condition"}],
    }
    _, carriers = fold(join)
    assert carriers == {}


def _corpus(n_prs: int, defects: set, carried: dict):
    is_defect = {("o/r", i): (i in defects) for i in range(n_prs)}
    carriers = {p: {("o/r", i) for i in prs} for p, prs in carried.items()}
    return is_defect, carriers


def test_corpus_lift_is_relative_to_the_ledgers_own_base_rate():
    """Precision alone is unreadable on an enriched corpus — 40% precision
    is signal at a 2% base rate and noise at a 40% one. Lift is the number
    that survives the enrichment."""
    is_defect, carriers = _corpus(10, {0, 1, 2, 3}, {"p": [0, 1, 4, 5]})
    rows, base = corpus_table(is_defect, carriers, min_prs=1)
    assert base == pytest.approx(0.4)
    assert rows[0]["precision"] == pytest.approx(0.5)
    assert rows[0]["lift"] == pytest.approx(1.25)


def test_corpus_flags_only_patterns_whose_interval_clears_the_base_rate():
    """Ranking by lift alone promotes 2-of-2 flukes to the top of the
    table. The star is what separates a pattern worth distilling from one
    that has simply not been observed enough."""
    is_defect, carriers = _corpus(
        100,
        set(range(20)),
        # 2 of 4 — twice the base rate, but four PRs cannot establish that.
        {"fluke": [0, 1, 50, 51], "real": list(range(0, 15)) + [50]},
    )
    rows, _ = corpus_table(is_defect, carriers, min_prs=2)
    by = {r["pattern"]: r for r in rows}
    assert by["fluke"]["lift"] > 1 and not by["fluke"]["clears_base"]
    assert by["real"]["clears_base"]
    # Lift alone would rank the fluke above a pattern with real evidence.
    assert by["fluke"]["lift"] > by["real"]["lift"] * 0.5


def test_corpus_min_prs_filters_the_long_tail():
    is_defect, carriers = _corpus(10, {0}, {"rare": [0], "common": [0, 1, 2]})
    rows, _ = corpus_table(is_defect, carriers, min_prs=3)
    assert [r["pattern"] for r in rows] == ["common"]


def test_population_precision_of_an_uninformative_pattern_equals_the_base_rate():
    """The load-bearing property of the reweight. A pattern appearing at the
    same rate on defects and cleans predicts nothing, so its population
    precision must collapse to pi no matter how enriched the sample was."""
    pi = 0.02
    assert _pop_precision(10, 100, 20, 200, pi) == pytest.approx(pi)


def test_population_precision_undoes_the_enrichment():
    """Corpus precision here is 50% (10 defect hits vs 10 clean hits), but
    the clean stratum is a 10x subsample of a population that is 98% clean.
    Reporting 50% would overstate the pattern by more than an order of
    magnitude."""
    corpus = 10 / (10 + 10)
    pop = _pop_precision(10, 100, 10, 200, 0.02)
    assert corpus == pytest.approx(0.5)
    assert pop == pytest.approx(0.02 * 0.1 / (0.02 * 0.1 + 0.98 * 0.05))
    assert pop < 0.05


def test_population_precision_is_one_when_no_clean_pr_carries_the_pattern():
    assert _pop_precision(5, 100, 0, 200, 0.02) == pytest.approx(1.0)


def test_population_precision_is_nan_on_an_empty_stratum():
    """Better an obvious NaN than a silent 0% for a repo whose strata were
    never populated."""
    assert _pop_precision(0, 0, 0, 10, 0.02) != _pop_precision(0, 0, 0, 10, 0.02)
