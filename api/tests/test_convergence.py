"""Convergence finding-diff — the fix-loop halt signal.

Pre-registered in docs/design/outcome-loop/convergence-design.md. Every test
here names the note's rule it holds. The asymmetric failure the whole module is
shaped around: a false `resolved` tells an agent it is done when it is not, so
every abstention beats a wrong answer.
"""

import ast
from pathlib import Path

from doug import convergence

API = Path(__file__).resolve().parents[1]

FILE = "api/doug/api.py"


def _f(rule="reader:error-handling-gap", file=FILE, label="x", severity="high"):
    return {"rule": rule, "label": label, "file": file, "severity": severity}


def _read(files_unseen=(), file_cut=None, files_dropped=(), changed_files=3):
    return {
        "files_unseen": list(files_unseen),
        "file_cut": file_cut,
        "files_dropped": list(files_dropped),
        "changed_files": changed_files,
    }


def _reason(rule, label, weight=0.0, severity=None):
    return {"rule": rule, "label": label, "weight": weight, "severity": severity}


# --- the note's classification rules, in order -----------------------------


def test_absent_finding_with_covered_file_is_resolved():
    """Rule 5. The only path to `resolved`: the file was read and the finding
    is gone."""
    r = convergence.compare([_f()], [], [], _read())
    assert (r.resolved, r.persisted, r.new) == (1, 0, 0)
    assert r.unknown == {}


def test_present_identity_is_persisted():
    """Rule 1."""
    r = convergence.compare([_f()], [_f()], [], _read())
    assert (r.resolved, r.persisted, r.new) == (0, 1, 0)


def test_null_file_never_resolves():
    """Rule 2. store.py backfills `file` by exact description-match and can
    lose it (store.py:825-838); a lost file must not fabricate a resolution."""
    r = convergence.compare([_f(file=None)], [], [], _read())
    assert r.resolved == 0
    assert r.unknown == {"identity-incomplete": 1}


def test_null_file_on_the_later_side_is_not_new():
    """Rule 2, later side. A finding with no file can neither absorb a prior
    finding into `persisted` nor inflate `new` — it abstains."""
    r = convergence.compare([], [_f(file=None)], [], _read())
    assert (r.resolved, r.persisted, r.new) == (0, 0, 0)
    assert r.unknown == {"identity-incomplete": 1}


def test_uncovered_file_never_resolves():
    """Rule 3, files_unseen. The later read never saw the file, so its silence
    about the finding is not evidence."""
    r = convergence.compare([_f()], [], [], _read(files_unseen=[FILE]))
    assert r.resolved == 0
    assert r.unknown == {"file-uncovered": 1}


def test_cut_file_never_resolves():
    """Rule 3, file_cut — seen in part is not seen (reader.py:429-431)."""
    r = convergence.compare([_f()], [], [], _read(file_cut=FILE))
    assert r.resolved == 0
    assert r.unknown == {"file-uncovered": 1}


def test_dropped_file_never_resolves():
    """Rule 3, files_dropped — GitHub never handed the file over."""
    r = convergence.compare([_f()], [], [], _read(files_dropped=[FILE]))
    assert r.resolved == 0
    assert r.unknown == {"file-uncovered": 1}


def test_missing_read_row_never_resolves():
    """Rule 3, no read row. Only reader-tier verdicts get one (store.py:143-150);
    without it we cannot say what the later verdict was shown."""
    r = convergence.compare([_f()], [], [], None)
    assert r.resolved == 0
    assert r.unknown == {"file-uncovered": 1}


def test_null_files_dropped_column_is_not_coverage_evidence():
    """migration-007 columns are NULL on historical rows (store.py:161-164).
    "Not tracked" must not abstain by itself, and must not crash."""
    read = {"files_unseen": [], "file_cut": None, "files_dropped": None, "changed_files": None}
    r = convergence.compare([_f()], [], [], read)
    assert (r.resolved, r.unknown) == (1, {})


def test_settled_finding_never_resolves():
    """Rule 4. Doug disproved the finding between the two reads; nobody fixed
    anything, so it must not read as progress."""
    notice = _reason(
        "settled-missing-import",
        "Dropped 1 finding(s) disproved by runtime import at head — "
        f"{FILE}: error-handling-gap (['threading'])",
    )
    r = convergence.compare([_f()], [], [notice], _read())
    assert r.resolved == 0
    assert r.unknown == {"settled": 1}


def test_schema_settlement_notice_also_abstains():
    """Rule 4's second emitter — settle.py:291."""
    notice = _reason(
        "settled-schema-dependency",
        "Dropped 1 finding(s) disproved by the live schema — "
        f"{FILE}: error-handling-gap ([('verdicts', 'id')])",
    )
    r = convergence.compare([_f()], [], [notice], _read())
    assert r.unknown == {"settled": 1}


def test_settlement_notice_for_another_file_does_not_abstain():
    """Rule 4 keys on (file, slug), not on the notice's mere presence —
    otherwise one settled finding would silence the whole verdict."""
    notice = _reason(
        "settled-missing-import",
        "Dropped 1 finding(s) disproved by runtime import at head — "
        "api/doug/store.py: error-handling-gap (['threading'])",
    )
    r = convergence.compare([_f()], [], [notice], _read())
    assert (r.resolved, r.unknown) == (1, {})


def test_settlement_notice_slug_is_canonicalised_before_matching():
    """The notice carries the raw category_slug; identity carries the
    canonical pattern. Rule 4 must compare like with like or it silently
    stops abstaining for every merged synonym."""
    notice = _reason(
        "settled-missing-import",
        "Dropped 1 finding(s) disproved by runtime import at head — "
        f"{FILE}: unhandled-exception (['threading'])",
    )
    r = convergence.compare([_f(rule="reader:error-handling-gap")], [], [notice], _read())
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
    for notice in (settle.settlement_notice(dropped), settle.schema_settlement_notice(dropped)):
        assert notice is not None
        row = _reason(notice.rule, notice.label, notice.weight, notice.severity)
        r = convergence.compare([_f()], [], [row], _read())
        assert r.unknown == {"settled": 1}, notice.rule
        assert r.resolved == 0, notice.rule


def test_unparseable_settlement_label_does_not_silently_match():
    """An emitter that changes format must not abstain for everything — that
    would hide the drift behind a wall of `unknown`. It stops matching, and
    the pinning test above is what catches the drift."""
    notice = _reason("settled-missing-import", "Dropped 1 finding(s) — nothing parseable")
    r = convergence.compare([_f()], [], [notice], _read())
    assert (r.resolved, r.unknown) == (1, {})


def test_abstention_beats_resolution_when_rules_collide():
    """The note's ordering claim, tested directly: a finding that is both
    uncovered and otherwise-resolvable is uncovered."""
    r = convergence.compare([_f()], [], [], _read(files_unseen=[FILE]))
    assert r.resolved == 0


# --- vocabulary and counting ----------------------------------------------


def test_deterministic_reasons_are_excluded():
    """Deterministic-tier reasons share the findings table under a different
    vocabulary (patterns.py); pooling them would count a routing rule as a
    fixed defect."""
    r = convergence.compare([_f(rule="size-large")], [_f(rule="ledger-unavailable")], [], _read())
    assert (r.resolved, r.persisted, r.new) == (0, 0, 0)
    assert r.unknown == {}


def test_count_matching_two_before_one_after():
    """Identity is (pattern, file) with no line numbers, so duplicates within
    one verdict can only be matched by count."""
    r = convergence.compare([_f(), _f()], [_f()], [], _read())
    assert (r.resolved, r.persisted, r.new) == (1, 1, 0)


def test_new_findings_counted():
    r = convergence.compare([], [_f(), _f(file="api/doug/store.py")], [], _read())
    assert (r.resolved, r.persisted, r.new) == (0, 0, 2)


def test_slug_merge_map_applies():
    """patterns.SLUG_MERGES is the logged synonym merge; without it the same
    defect renamed by the model reads as one fix plus one regression."""
    r = convergence.compare(
        [_f(rule="reader:unhandled-exception")],
        [_f(rule="reader:missing-error-handling")],
        [],
        _read(),
    )
    assert (r.resolved, r.persisted, r.new) == (0, 1, 0)


def test_same_pattern_in_another_file_is_not_the_same_finding():
    r = convergence.compare([_f()], [_f(file="api/doug/store.py")], [], _read())
    assert (r.resolved, r.persisted, r.new) == (1, 0, 1)


# --- the report ------------------------------------------------------------


def test_ratio_none_on_empty_denominator():
    r = convergence.compare([], [], [], _read())
    assert r.ratio is None
    assert r.unknown_total == 0


def test_unknown_is_never_folded_into_the_ratio():
    """REVIEWING.md: a claim about an absence cannot be settled by looking at
    the same place the claim came from. An abstention is reported beside the
    ratio, never inside it — otherwise abstaining would move the number."""
    r = convergence.compare([_f(), _f(file=None)], [], [], _read())
    assert (r.resolved, r.persisted) == (1, 0)
    assert r.ratio == 1.0
    assert r.unknown == {"identity-incomplete": 1}
    assert r.unknown_total == 1


def test_report_is_frozen():
    """The receipt path (Task 4) hands these out per verdict pair; a mutable
    report is a shared-state bug waiting to happen."""
    import dataclasses

    import pytest

    r = convergence.compare([], [], [], _read())
    assert dataclasses.is_dataclass(r)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.resolved = 99


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
