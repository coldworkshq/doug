from doug import patterns


def test_merge_map_is_pinned():
    """These pairs are the logged synonym merge behind the Phase-1
    distillability result (sentry 30.1% top-10 coverage). Changing them
    re-scores that experiment, so a change must break a test, not slip
    through as a refactor."""
    assert patterns.SLUG_MERGES == {
        "missing-error-handling": "error-handling-gap",
        "unhandled-exception": "error-handling-gap",
        "unhandled-io-error": "error-handling-gap",
        "behavior-regression": "behavior-change",
        "circular-import": "import-cycle",
        "import-cycle-risk": "import-cycle",
        "metric-cardinality": "metrics-cardinality",
        "unchecked-type-conversion": "type-coercion",
        "unsafe-type-coercion": "type-coercion",
        "dead-reference-after-module-removal": "dead-reference",
    }


def test_probe_and_ledger_share_one_map():
    """The probe grouped findings one way and the ledger must group them the
    same way, or per-pattern precision is not about the patterns the
    distillability bar was measured on."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from llm_probe import SLUG_MERGES

    assert SLUG_MERGES is patterns.SLUG_MERGES


def test_normalize_passes_through_unknown_slugs():
    assert patterns.normalize("race-condition") == "race-condition"
    assert patterns.normalize("unhandled-exception") == "error-handling-gap"


def test_from_rule_ignores_deterministic_reasons():
    """Deterministic-tier reasons live in the same table under a different
    vocabulary; pooling them into pattern precision would credit the reader
    for rules it never emitted."""
    assert patterns.from_rule("reader:unsafe-type-coercion") == "type-coercion"
    assert patterns.from_rule("size-large") is None
    assert patterns.from_rule("ledger-unavailable") is None


def test_two_spellings_of_one_defect_group_to_one_pattern():
    """#244. category_slug is free-form model output, and the production
    findings.rule column is written straight from it (reader.py), so the
    spelling is whatever the model chose that day. The grouping key folds
    the spelling; it does not fold the word.
    """
    spellings = (
        "missing-import",
        "Missing Import",
        "missing_import",
        " missing-import ",
        "MISSING--IMPORT",
    )
    for spelling in spellings:
        assert patterns.normalize(spelling) == "missing-import", spelling
    # The merge map still applies after the fold, so a shouted synonym
    # reaches the same canonical pattern as its kebab-case twin.
    assert patterns.normalize("Unhandled_Exception") == "error-handling-gap"
    assert patterns.from_rule("reader:Missing Import") == "missing-import"
    # Spelling folds; vocabulary does not. That judgement stays in SLUG_MERGES.
    assert patterns.normalize("missing-imports") != patterns.normalize("missing-import")
