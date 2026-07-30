"""Defect-pattern vocabulary — the distillation loop's grouping key.

The reader emits a free-form `category_slug` per finding. Synonyms are
inevitable ("unhandled-exception" vs "missing-error-handling"), and the
Phase-1 distillability bar explicitly allowed "manual merge of obvious
synonyms, logged" — this map IS that log, moved here verbatim from
scripts/llm_probe.py so the probe and the ledger group identically.

Merging is deliberately conservative: only slugs naming the same defect
mechanism merge. Anything requiring a judgement call about whether two
defects are "similar enough" stays separate, because a merge map that
grows to fit the data would manufacture the distillability it is
supposed to measure. tests/test_patterns.py pins these pairs.
"""

SLUG_MERGES = {
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

RULE_PREFIX = "reader:"


def normalize(slug: str) -> str:
    """Canonical pattern name for a raw category_slug."""
    return SLUG_MERGES.get(slug, slug)


def from_rule(rule: str) -> str | None:
    """Canonical pattern for a findings.rule, or None if not a reader finding.

    Deterministic-tier reasons share the findings table but are a different
    vocabulary; pattern analysis must not silently pool the two.
    """
    if not rule.startswith(RULE_PREFIX):
        return None
    return normalize(rule[len(RULE_PREFIX) :])
