"""Convergence finding-diff — the fix-loop halt signal.

Pre-registered in docs/design/outcome-loop/convergence-design.md, rule 5 as
replaced 2026-08-20 ("Rule 5 replaced"). Every test here names the rule it
holds. The asymmetric failure the whole module is shaped around: a false
`resolved` tells an agent it is done when it is not — and after bar 1 (silence
is not evidence) and Bar A(B) (an edit is not evidence either), v1 has no
`resolved` state at all. The strongest positive call is carried-forward.
"""

import ast
from pathlib import Path

from doug import convergence

API = Path(__file__).resolve().parents[1]

FILE = "api/doug/api.py"
OTHER = "api/doug/store.py"

H1, H2, H3 = "a" * 64, "b" * 64, "c" * 64


def _f(rule="reader:error-handling-gap", file=FILE, label="x", severity="high", hunks=None):
    return {"rule": rule, "label": label, "file": file, "severity": severity, "hunks": hunks}


def _read(files_unseen=(), file_cut=None, files_dropped=(), changed_files=3, hunks=None):
    return {
        "files_unseen": list(files_unseen),
        "file_cut": file_cut,
        "files_dropped": list(files_dropped),
        "changed_files": changed_files,
        "hunks": hunks,
    }


def _reason(rule, label, weight=0.0, severity=None):
    return {"rule": rule, "label": label, "weight": weight, "severity": severity}


# Both reads carry an index and FILE's delta is byte-unchanged between them —
# the baseline under which rules 1-4 behave exactly as before and rule 5's
# strongest call is carried-forward-by-construction.
def _pair(prior_hunks=None, later_hunks=None):
    prior = {FILE: [H1]} if prior_hunks is None else prior_hunks
    later = {FILE: [H1]} if later_hunks is None else later_hunks
    return _read(hunks=later), _read(hunks=prior)


# --- the note's classification rules, in order -----------------------------


def test_absence_is_not_evidence_an_unchanged_delta_carries_forward():
    """Replaced rule 5, the load-bearing change. The reader went silent and
    the cited file's delta is byte-unchanged: bar 1 proved that silence is
    nondeterminism, not a fix, so the finding is carried forward by
    construction — never resolved."""
    later_read, prior_read = _pair()
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert (r.resolved, r.persisted, r.new) == (0, 1, 0)
    assert r.unknown == {}
    (row,) = convergence.classify([_f()], [], [], later_read, prior_read)
    assert (row.state, row.basis, row.pair_delta) == ("persisted", "by-construction", "unchanged")


def test_present_identity_is_persisted():
    """Rule 1 — unchanged by the replacement."""
    later_read, prior_read = _pair()
    r = convergence.compare([_f()], [_f()], [], later_read, prior_read)
    assert (r.resolved, r.persisted, r.new) == (0, 1, 0)


def test_null_file_never_resolves():
    """Rule 2. store.py backfills `file` by exact description-match and can
    lose it (store.py:825-838); a lost file must not fabricate a resolution."""
    later_read, prior_read = _pair()
    r = convergence.compare([_f(file=None)], [], [], later_read, prior_read)
    assert r.resolved == 0
    assert r.unknown == {"identity-incomplete": 1}


def test_null_file_on_the_later_side_is_not_new():
    """Rule 2, later side. A finding with no file can neither absorb a prior
    finding into `persisted` nor inflate `new` — it abstains."""
    later_read, prior_read = _pair()
    r = convergence.compare([], [_f(file=None)], [], later_read, prior_read)
    assert (r.resolved, r.persisted, r.new) == (0, 0, 0)
    assert r.unknown == {"identity-incomplete": 1}


def test_uncovered_file_never_resolves():
    """Rule 3, files_unseen. The later read never saw the file, so its silence
    about the finding is not evidence."""
    later_read, prior_read = _pair()
    later_read["files_unseen"] = [FILE]
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert r.resolved == 0
    assert r.unknown == {"file-uncovered": 1}


def test_cut_file_never_resolves():
    """Rule 3, file_cut — seen in part is not seen (reader.py:429-431)."""
    later_read, prior_read = _pair()
    later_read["file_cut"] = FILE
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert r.unknown == {"file-uncovered": 1}


def test_dropped_file_never_resolves():
    """Rule 3, files_dropped — GitHub never handed the file over."""
    later_read, prior_read = _pair()
    later_read["files_dropped"] = [FILE]
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert r.unknown == {"file-uncovered": 1}


def test_missing_read_row_never_resolves():
    """Rule 3, no read row. Only reader-tier verdicts get one (store.py:143-150);
    without it we cannot say what the later verdict was shown."""
    r = convergence.compare([_f()], [], [], None, _read(hunks={FILE: [H1]}))
    assert r.resolved == 0
    assert r.unknown == {"file-uncovered": 1}


def test_null_files_dropped_column_is_not_coverage_evidence():
    """migration-007 columns are NULL on historical rows (store.py:161-164).
    "Not tracked" must not abstain as rule 3 by itself, and must not crash —
    the row still reaches rule 5, where its missing hunk index abstains as
    no-hunk-index (the honest reason: an old row, not an unseen file)."""
    read = {"files_unseen": [], "file_cut": None, "files_dropped": None,
            "changed_files": None, "hunks": None}
    r = convergence.compare([_f()], [], [], read, read)
    assert (r.resolved, r.unknown) == (0, {"no-hunk-index": 1})


def test_settled_finding_never_resolves():
    """Rule 4. Doug disproved the finding between the two reads; nobody fixed
    anything, so it must not read as progress."""
    notice = _reason(
        "settled-missing-import",
        "Dropped 1 finding(s) disproved by runtime import at head — "
        f"{FILE}: error-handling-gap (['threading'])",
    )
    later_read, prior_read = _pair()
    r = convergence.compare([_f()], [], [notice], later_read, prior_read)
    assert r.resolved == 0
    assert r.unknown == {"settled": 1}


def test_schema_settlement_notice_also_abstains():
    """Rule 4's second emitter — settle.py:291."""
    notice = _reason(
        "settled-schema-dependency",
        "Dropped 1 finding(s) disproved by the live schema — "
        f"{FILE}: error-handling-gap ([('verdicts', 'id')])",
    )
    later_read, prior_read = _pair()
    r = convergence.compare([_f()], [], [notice], later_read, prior_read)
    assert r.unknown == {"settled": 1}


def test_settlement_notice_for_another_file_does_not_abstain():
    """Rule 4 keys on (file, slug), not on the notice's mere presence —
    otherwise one settled finding would silence the whole verdict. The
    finding then falls through to rule 5 and carries forward."""
    notice = _reason(
        "settled-missing-import",
        "Dropped 1 finding(s) disproved by runtime import at head — "
        f"{OTHER}: error-handling-gap (['threading'])",
    )
    later_read, prior_read = _pair()
    r = convergence.compare([_f()], [], [notice], later_read, prior_read)
    assert (r.persisted, r.unknown) == (1, {})


def test_settlement_notice_slug_is_canonicalised_before_matching():
    """The notice carries the raw category_slug; identity carries the
    canonical pattern. Rule 4 must compare like with like or it silently
    stops abstaining for every merged synonym."""
    notice = _reason(
        "settled-missing-import",
        "Dropped 1 finding(s) disproved by runtime import at head — "
        f"{FILE}: unhandled-exception (['threading'])",
    )
    later_read, prior_read = _pair()
    r = convergence.compare(
        [_f(rule="reader:error-handling-gap")], [], [notice], later_read, prior_read
    )
    assert r.unknown == {"settled": 1}


def test_settlement_notice_grammar_is_pinned_to_settle_py():
    """settle.py owns the label format; convergence.py parses it. Nothing but
    a test holds those two together, so this builds the notices with the real
    emitters rather than a copy of their strings."""
    from doug import settle
    from doug.reader import ReaderFinding

    dropped = [
        ReaderFinding(
            category_slug="unhandled-exception",
            description="uses `threading` with no import",
            file=FILE,
            severity="high",
        )
    ]
    later_read, prior_read = _pair()
    for notice in (settle.settlement_notice(dropped), settle.schema_settlement_notice(dropped)):
        assert notice is not None
        row = _reason(notice.rule, notice.label, notice.weight, notice.severity)
        r = convergence.compare([_f()], [], [row], later_read, prior_read)
        assert r.unknown == {"settled": 1}, notice.rule
        assert r.resolved == 0, notice.rule


def test_unparseable_settlement_label_does_not_silently_match():
    """An emitter that changes format must not abstain for everything — that
    would hide the drift behind a wall of `unknown`. It stops matching (the
    finding carries forward under rule 5), and the pinning test above is what
    catches the drift."""
    notice = _reason("settled-missing-import", "Dropped 1 finding(s) — nothing parseable")
    later_read, prior_read = _pair()
    r = convergence.compare([_f()], [], [notice], later_read, prior_read)
    assert (r.persisted, r.unknown) == (1, {})


def test_abstention_order_rule_3_beats_rule_5():
    """The note's ordering claim, tested directly: a finding whose file is
    both uncovered and edited is uncovered — the earlier abstention wins."""
    later_read, prior_read = _pair(later_hunks={FILE: [H2]})
    later_read["files_unseen"] = [FILE]
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert r.unknown == {"file-uncovered": 1}


# --- the replaced rule 5's own branches ------------------------------------


def test_no_hunk_index_on_either_side_abstains():
    """Pre-migration rows and deploy-overlap rows have hunks=NULL; the
    classifier must read that as cannot-compare, never as unchanged."""
    for later_hunks, prior_hunks in (({FILE: [H1]}, None), (None, {FILE: [H1]})):
        r = convergence.compare(
            [_f()], [], [], _read(hunks=later_hunks), _read(hunks=prior_hunks)
        )
        assert r.unknown == {"no-hunk-index": 1}, (later_hunks, prior_hunks)


def test_file_absent_from_the_prior_index_is_uncovered():
    """Rule 3 extended to the prior side: an absent key is not an empty set.
    The prior read never sent the file (or the path is model text that was
    never in a patch), so nothing about its delta is known."""
    later_read, prior_read = _pair(prior_hunks={OTHER: [H1]})
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert r.unknown == {"file-uncovered": 1}


def test_an_edit_is_not_fix_evidence():
    """Every prior hash gone, file still in the diff. The old design called
    this resolved(hunk-edited); Phase 0's hand-check falsified it (4/6 such
    calls false — a 5-line comment block re-hashes a hunk;
    phase0-results.md). Demoted to an abstention by Andrew's 2026-08-20
    ruling: the finding stays listed."""
    later_read, prior_read = _pair(later_hunks={FILE: [H2]})
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert (r.resolved, r.persisted) == (0, 0)
    assert r.unknown == {"edited-not-verified": 1}


def test_left_diff_never_resolves():
    """Every prior hash gone and the file is gone from the later patch:
    reverted to base, pure rename (review.py:108 drops nothing for +0/-0),
    or absorbed into base — Doug cannot tell which, so it abstains."""
    later_read, prior_read = _pair(later_hunks={OTHER: [H3]})
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert r.unknown == {"left-diff": 1}


def test_by_construction_requires_strict_multiset_equality():
    """prior ⊂ later is NOT by-construction: the added hunk in the same file
    may be the fix attempt, so the honest answer is not-reconfirmed."""
    later_read, prior_read = _pair(later_hunks={FILE: [H1, H2]})
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert r.unknown == {"not-reconfirmed": 1}


def test_partial_survival_without_attribution_abstains():
    later_read, prior_read = _pair(
        prior_hunks={FILE: [H1, H2]}, later_hunks={FILE: [H1, H3]}
    )
    r = convergence.compare([_f()], [], [], later_read, prior_read)
    assert r.unknown == {"not-reconfirmed": 1}


def test_pair_delta_names_movement_elsewhere():
    """The cited file is byte-unchanged but another file's delta moved: the
    check run's changed-elsewhere sentence ("if you addressed it elsewhere, a
    human should look") reads this field."""
    later_read, prior_read = _pair(
        prior_hunks={FILE: [H1], OTHER: [H2]},
        later_hunks={FILE: [H1], OTHER: [H3]},
    )
    (row,) = convergence.classify([_f()], [], [], later_read, prior_read)
    assert (row.state, row.basis, row.pair_delta) == (
        "persisted", "by-construction", "changed-elsewhere",
    )


# --- the attribution refinement (span-verification.md, ADR-0014) -----------


def test_attributed_surviving_carries_forward():
    """Partial file edit, but every hunk THIS finding was attributed to is
    byte-unchanged: carried forward at hunk grain. This is the branch that
    turned the killer case (#50 input-validation, defect verbatim at the
    later head) from a false resolved into a correct carry."""
    later_read, prior_read = _pair(
        prior_hunks={FILE: [H1, H2]}, later_hunks={FILE: [H1, H3]}
    )
    (row,) = convergence.classify(
        [_f(hunks=[H1])], [], [], later_read, prior_read
    )
    assert (row.state, row.basis) == ("persisted", "attributed-surviving")


def test_attributed_edited_is_still_not_fix_evidence():
    """Every attributed hunk was edited — Phase 0 falsified this as
    fix-evidence too (2/5 false). Demoted with the same ruling."""
    later_read, prior_read = _pair(
        prior_hunks={FILE: [H1, H2]}, later_hunks={FILE: [H2, H3]}
    )
    r = convergence.compare([_f(hunks=[H1])], [], [], later_read, prior_read)
    assert r.unknown == {"edited-not-verified": 1}


def test_attribution_that_mismatches_the_stored_index_abstains():
    """An attribution naming a hash the prior index never had cannot refine
    anything — it is model output that failed its validation contract."""
    later_read, prior_read = _pair(
        prior_hunks={FILE: [H1, H2]}, later_hunks={FILE: [H1, H3]}
    )
    r = convergence.compare([_f(hunks=[H3])], [], [], later_read, prior_read)
    assert r.unknown == {"not-reconfirmed": 1}


def test_mixed_attribution_survival_abstains():
    later_read, prior_read = _pair(
        prior_hunks={FILE: [H1, H2, H3]}, later_hunks={FILE: [H1, "d" * 64, "e" * 64]}
    )
    r = convergence.compare([_f(hunks=[H1, H2])], [], [], later_read, prior_read)
    assert r.unknown == {"not-reconfirmed": 1}


# --- v1 never resolves (Andrew's 2026-08-20 ruling) ------------------------


def test_no_input_yields_a_resolved_state_in_v1():
    """The pin the build plan names. Every rule-5 branch across index
    configurations, with and without attribution: nothing resolves. Doug
    never stops carrying a finding on its own inference in v1;
    verify-at-resolve (v1.1, its own prereg) is the only path back."""
    indexes = [
        None,
        {},
        {FILE: []},
        {FILE: [H1]},
        {FILE: [H1, H2]},
        {FILE: [H2]},
        {FILE: [H2, H3]},
        {OTHER: [H1]},
    ]
    attributions = [None, [H1], [H1, H2], [H3]]
    for prior_hunks in indexes:
        for later_hunks in indexes:
            for attribution in attributions:
                r = convergence.compare(
                    [_f(hunks=attribution)], [], [],
                    _read(hunks=later_hunks), _read(hunks=prior_hunks),
                )
                assert r.resolved == 0, (prior_hunks, later_hunks, attribution)


def test_resolved_is_never_constructed_in_the_source():
    """Structural half of the same pin: no code path in convergence.py builds
    a Classification carrying RESOLVED. The constant may exist (the report
    field keeps its shape); constructing it is what the ruling forbids."""
    tree = ast.parse((API / "doug" / "convergence.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Classification":
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                assert not (isinstance(arg, ast.Name) and arg.id == "RESOLVED")


# --- vocabulary and counting ----------------------------------------------


def test_deterministic_reasons_are_excluded():
    """Deterministic-tier reasons share the findings table under a different
    vocabulary (patterns.py); pooling them would count a routing rule as a
    fixed defect."""
    later_read, prior_read = _pair()
    r = convergence.compare(
        [_f(rule="size-large")], [_f(rule="ledger-unavailable")], [], later_read, prior_read
    )
    assert (r.resolved, r.persisted, r.new) == (0, 0, 0)
    assert r.unknown == {}


def test_count_matching_two_before_one_after():
    """Identity is (pattern, file) with no line numbers, so duplicates within
    one verdict can only be matched by count. The surplus row runs rules 3-5:
    with a byte-unchanged delta it carries forward by construction."""
    later_read, prior_read = _pair()
    r = convergence.compare([_f(), _f()], [_f()], [], later_read, prior_read)
    assert (r.resolved, r.persisted, r.new) == (0, 2, 0)


def test_new_findings_counted_and_graded_against_the_indexes():
    """`new` carries code_changed from the same indexes: the check run's "new
    on files unchanged since <sha12>" bucket is how the reader's noise in the
    other direction gets printed rather than hidden."""
    later_read, prior_read = _pair(
        prior_hunks={FILE: [H1], OTHER: [H2]},
        later_hunks={FILE: [H1], OTHER: [H3]},
    )
    rows = convergence.classify(
        [], [_f(), _f(file=OTHER)], [], later_read, prior_read
    )
    assert [(c.state, c.code_changed) for c in rows] == [("new", False), ("new", True)]
    rows = convergence.classify([], [_f()], [], _read(hunks=None), _read(hunks=None))
    assert [(c.state, c.code_changed) for c in rows] == [("new", None)]


def test_slug_merge_map_applies():
    """patterns.SLUG_MERGES is the logged synonym merge; without it the same
    defect renamed by the model reads as one fix plus one regression."""
    later_read, prior_read = _pair()
    r = convergence.compare(
        [_f(rule="reader:unhandled-exception")],
        [_f(rule="reader:missing-error-handling")],
        [],
        later_read,
        prior_read,
    )
    assert (r.resolved, r.persisted, r.new) == (0, 1, 0)


def test_same_pattern_in_another_file_is_not_the_same_finding():
    later_read, prior_read = _pair()
    r = convergence.compare([_f()], [_f(file=OTHER)], [], later_read, prior_read)
    assert (r.resolved, r.persisted, r.new) == (0, 1, 1)


# --- the report ------------------------------------------------------------


def test_ratio_none_on_empty_denominator():
    later_read, prior_read = _pair()
    r = convergence.compare([], [], [], later_read, prior_read)
    assert r.ratio is None
    assert r.unknown_total == 0


def test_unknown_is_never_folded_into_the_ratio():
    """REVIEWING.md: a claim about an absence cannot be settled by looking at
    the same place the claim came from. An abstention is reported beside the
    ratio, never inside it — otherwise abstaining would move the number."""
    later_read, prior_read = _pair()
    r = convergence.compare([_f(), _f(file=None)], [], [], later_read, prior_read)
    assert (r.resolved, r.persisted) == (0, 1)
    assert r.ratio == 0.0
    assert r.unknown == {"identity-incomplete": 1}
    assert r.unknown_total == 1


def test_report_is_frozen():
    """The receipt path (Task 4) hands these out per verdict pair; a mutable
    report is a shared-state bug waiting to happen."""
    import dataclasses

    import pytest

    later_read, prior_read = _pair()
    r = convergence.compare([], [], [], later_read, prior_read)
    assert dataclasses.is_dataclass(r)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.resolved = 99


# --- per-finding classification (the note's amendment) ---------------------


def test_classify_labels_every_row_on_both_sides():
    """The evaluation hand-labels these entries; counts cannot be labelled."""
    later_read, prior_read = _pair()
    prior = [_f(), _f(rule="size-large")]
    later = [_f(file=OTHER)]
    rows = convergence.classify(prior, later, [], later_read, prior_read)
    assert [(c.side, c.state, c.unknown_reason) for c in rows] == [
        ("prior", "persisted", None),
        ("prior", "excluded", None),
        ("later", "new", None),
    ]
    assert rows[0].finding is prior[0]
    assert rows[0].basis == "by-construction"


def test_classify_reports_the_abstention_reason_per_row():
    later_read, prior_read = _pair()
    later_read["files_unseen"] = [FILE]
    rows = convergence.classify([_f(), _f(file=None)], [], [], later_read, prior_read)
    assert [(c.state, c.unknown_reason) for c in rows] == [
        ("unknown", "file-uncovered"),
        ("unknown", "identity-incomplete"),
    ]


def test_classify_and_compare_are_one_classification():
    """Two implementations would let the evaluation grade labels the shipped
    counts never produced, and the bar would say nothing about the receipt."""
    notice = _reason(
        "settled-missing-import",
        "Dropped 1 finding(s) disproved by runtime import at head — "
        "api/doug/worker.py: error-handling-gap (['threading'])",
    )
    prior = [
        _f(), _f(), _f(file="api/doug/worker.py"), _f(file=None), _f(rule="size-large"),
        _f(file="api/doug/reader.py"),
    ]
    later = [_f(), _f(file=OTHER)]
    later_read = _read(
        files_unseen=["api/doug/settle.py"],
        hunks={FILE: [H2], OTHER: [H3], "api/doug/worker.py": [H1]},
    )
    prior_read = _read(
        hunks={FILE: [H1], "api/doug/worker.py": [H1], "api/doug/reader.py": [H2]}
    )
    rows = convergence.classify(prior, later, [notice], later_read, prior_read)
    report = convergence.compare(prior, later, [notice], later_read, prior_read)

    states = [c.state for c in rows]
    assert states.count("resolved") == report.resolved == 0
    assert states.count("persisted") == report.persisted
    assert states.count("new") == report.new
    reasons = [c.unknown_reason for c in rows if c.state == "unknown"]
    assert sorted(reasons) == sorted(
        reason for reason, n in report.unknown.items() for _ in range(n)
    )


def test_duplicate_identity_persists_the_earlier_row():
    """Arbitrary but fixed: with two indistinguishable prior rows and one
    later, the same ledger must always yield the same labels. The surplus row
    runs rule 5 and, on an unchanged delta, carries by construction."""
    later_read, prior_read = _pair()
    prior = [_f(label="first"), _f(label="second")]
    rows = convergence.classify(prior, [_f(label="still-here")], [], later_read, prior_read)
    assert [(c.finding["label"], c.state, c.basis) for c in rows] == [
        ("first", "persisted", None),
        ("second", "persisted", "by-construction"),
        # counted nowhere — the finding it matches is counted once, on the
        # prior side
        ("still-here", "matched", None),
    ]


# --- invariants ------------------------------------------------------------


def test_convergence_is_not_in_the_scoring_path():
    """Spec §3 / design-lock.md:75: convergence never enters score()
    (doug/scoring.py:138) — that is what exempts it from the 2.34x bar and
    ADR-0012. Task 4 wires convergence into the RECEIPT path in store.py, and
    amends this test to allow exactly that importer; the scorer and the worker
    stay forbidden either way."""
    import doug.convergence  # noqa: F401 — the module must import standalone

    importers = []
    for path in sorted((API / "doug").glob("*.py")):
        if path.name == "convergence.py":
            continue
        src = path.read_text()
        if any(
            token in src
            for token in (
                "import convergence",
                "from doug import convergence",
                "from . import convergence",
            )
        ):
            importers.append(path.name)
    assert importers == [], importers


def test_convergence_is_pure():
    """No store, no engine, no clock, no network: the module is a function of
    rows it is handed. Anything else makes it a second read path, and the
    no-new-paid-read invariant would then be enforced by nothing."""
    tree = ast.parse((API / "doug" / "convergence.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    assert imported <= {"dataclasses", "collections", "collections.abc", "typing", ".patterns"}, (
        imported
    )


def test_settlement_rules_match_the_producer():
    """convergence.py cannot import settle.py (purity). The two copies of
    the producer codes must still be the same set, or a new settle notice
    would be invisible to the finding-diff."""
    from doug.settle import SETTLED_REASON_CODES

    assert convergence.SETTLEMENT_RULES == SETTLED_REASON_CODES
