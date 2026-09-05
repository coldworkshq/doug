"""Post-read import settlements — REVIEWING.md resolution rule, no prompt edit."""

from doug import settle
from doug.reader import ReaderFinding, ReaderVerdict

FILE = """\
import threading
from pathlib import Path

def ready():
    threading.Thread(target=lambda: None).start()
    return Path('.')
"""

TYPE_CHECKING_ONLY = """\
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import threading

def ready():
    threading.Thread(target=lambda: None).start()
"""


def _f(slug="missing-import", desc="uses `threading` with no import", file="api.py"):
    return ReaderFinding(
        category_slug=slug, description=desc, file=file, severity="medium"
    )


def test_drops_missing_import_when_runtime_import_exists():
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[_f()])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: FILE)
    assert len(dropped) == 1
    assert out.findings == []


def test_keeps_type_checking_only_import():
    """REVIEWING.md residual-real: TYPE_CHECKING import + runtime use."""
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[_f()])
    out, dropped = settle.drop_disproved_import_findings(
        rv, lambda p: TYPE_CHECKING_ONLY
    )
    assert dropped == []
    assert len(out.findings) == 1


def test_does_not_settle_undefined_name_via_later_assign():
    """Use-before-assign must not be cleared by a later binding."""
    src = "x = 1\n"  # name bound, but slug is undefined-name — out of scope
    f = ReaderFinding(
        category_slug="undefined-name",
        description="`x` is used before it is defined",
        file="api.py",
        severity="medium",
    )
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: src)
    assert dropped == []
    assert out.findings == [f]


def test_a_prose_word_after_import_does_not_block_settlement():
    """PR #278, third read. The first two reads settled `sys` against head;
    the third phrased it as "a `sys` import being added" and the extractor
    claimed `being`, so the finding it had already disproved was published.
    Every claimed name must be imported, which makes one prose word a veto.
    """
    f = _f(
        desc=(
            "The new fallback print uses `file=sys.stderr` in api.py but the "
            "diff does not show a `sys` import being added. If `sys` is not "
            "already imported at module scope, the path raises NameError."
        )
    )
    assert settle.claimed_names(f) == ["sys"]
    src = "import sys\n\ndef f():\n    print('x', file=sys.stderr)\n"
    assert settle.settle_many([f], lambda p: src) == []


def test_a_dotted_root_corroborates_a_prose_import_claim_but_is_not_one():
    """`os.path.join` with "no import of os" claims `os`. `self.client.post`
    with the same sentence claims nothing for `self`: Doug's review of this
    change (`reader:over-broad-regex`) pointed out that a dotted root taken as
    a claim is a permanent veto — `self` is never imported — so a finding that
    settles on `requests` alone would be published instead.
    """
    f = _f(desc="calls `os.path.join` but there is no import os anywhere in the file")
    assert settle.claimed_names(f) == ["os"]
    f = _f(
        desc="calls `self.client.post` with `requests` never imported; import requests is absent"
    )
    assert settle.claimed_names(f) == ["requests"]
    src = "import requests\n\nclass C:\n    def go(self):\n        return self.client.post\n"
    assert settle.settle_many([f], lambda p: src) == []


def test_a_name_the_extractor_cannot_read_keeps_the_finding():
    """Doug's second read of #287 (`reader:logic-inversion-in-safety-claim`):
    settlement needs EVERY claimed name imported, so a claim the extractor
    misses makes settling easier, not harder. "uses `os` but does not import
    sys" must not settle on `os` alone while `sys` is genuinely absent.
    """
    f = _f(desc="uses `os` correctly but does not import sys anywhere")
    assert settle.claimed_names(f) == []
    src = "import os\n\nprint(os.getcwd(), file=sys.stderr)\n"
    assert settle.settle_many([f], lambda p: src) == [f]
    # The file at head resolves the ambiguity. Doug's third read
    # (`reader:over-conservative-early-return`): "does not import numpy" with
    # numpy never written as code must still settle when numpy IS imported,
    # and must still publish when it is not — which is the same sentence
    # settling on the truth of its claim rather than on its punctuation.
    f = _f(desc="calls `np.array` but does not import numpy")
    assert settle.settle_many([f], lambda p: "import numpy as np\nimport numpy\n") == []
    assert settle.settle_many([f], lambda p: "import os\n") == [f]
    assert settle.settle_many([f], lambda p: "import os\nimport sys\n") == [f]
    # The same sentence with `sys` written as code claims both, and settles
    # only when both are imported.
    f = _f(desc="uses `os` correctly but does not import `sys` anywhere")
    assert settle.claimed_names(f) == ["os", "sys"]
    assert settle.settle_many([f], lambda p: src) == [f]
    assert settle.settle_many([f], lambda p: "import os\nimport sys\n") == []


def test_the_prose_import_form_counts_only_when_the_name_is_also_code():
    """`import X` in prose is kept as a claim only when X is written as code
    elsewhere; otherwise a sentence like "the import statement is missing"
    would claim `statement`, and a true absence would never settle because
    `statement` is never imported.
    """
    assert settle.claimed_names(_f(desc="the import statement for `asyncio` is missing")) == [
        "asyncio"
    ]
    assert settle.claimed_names(_f(desc="no import of anything is shown")) == []
    # Nothing written as code: nothing claimed, nothing settled.
    f = _f(desc="uses threading with no import")
    assert settle.settle_many([f], lambda p: FILE) == [f]


def test_keeps_finding_when_name_truly_absent():
    f = _f(desc="uses `asyncio` with no import")
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: FILE)
    assert dropped == []
    assert out.findings == [f]


def test_keeps_finding_when_file_unreadable():
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[_f()])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: None)
    assert dropped == []
    assert len(out.findings) == 1


def test_does_not_touch_non_resolution_findings():
    f = ReaderFinding(
        category_slug="race-condition",
        description="shared state without a lock",
        file="api.py",
        severity="high",
    )
    rv = ReaderVerdict(risk_score=70, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: FILE)
    assert dropped == []
    assert out.findings == [f]


def test_settlement_notice_explains_empty_findings_list():
    notice = settle.settlement_notice([_f()])
    assert notice is not None
    assert notice.rule == "settled-missing-import"
    assert notice.weight == 0.0


def _sf(
    slug="unmigrated-column",
    desc="`installations.token_hash` has no migration and will raise on a deployed database",
    file="api/doug/store.py",
):
    return ReaderFinding(
        category_slug=slug, description=desc, file=file, severity="high"
    )


def test_claimed_columns_extracts_table_dot_column_from_backticks():
    assert settle.claimed_columns(_sf()) == [("installations", "token_hash")]


def test_claimed_columns_ignores_a_bare_table_name_with_no_column():
    f = _sf(desc="`deep_read_counters` looks unmigrated")
    assert settle.claimed_columns(f) == []


def test_claimed_columns_is_empty_when_a_bare_table_mention_accompanies_a_real_pair():
    """Doug's review of PR #49 (reader:overly-broad-regex-match): a
    whole-new-table claim (`deep_read_counters`, out of scope by design — no
    dot) must not be settled on an unrelated real `table.column` mentioned
    in the same description for context. The presence of ANY bare
    backtick-quoted name means we cannot tell which mention is the actual
    disputed claim, so we settle nothing rather than guess.
    """
    f = _sf(
        desc=(
            "`deep_read_counters` looks unmigrated; it extends verdicts.id "
            "via a foreign key and will raise on a deployed database"
        )
    )
    assert settle.claimed_columns(f) == []


def test_does_not_settle_a_whole_table_claim_via_an_incidental_column_mention():
    """Same case as above, through the public entry point."""
    f = _sf(
        desc=(
            "`deep_read_counters` looks unmigrated; it extends verdicts.id "
            "via a foreign key and will raise on a deployed database"
        )
    )
    rv = ReaderVerdict(risk_score=60, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_schema_findings(
        rv, lambda table: {"id"} if table == "verdicts" else None
    )
    assert dropped == []
    assert out.findings == [f]


def test_drops_schema_finding_when_column_exists_in_live_schema():
    rv = ReaderVerdict(risk_score=60, rationale="x", findings=[_sf()])
    out, dropped = settle.drop_disproved_schema_findings(
        rv, lambda table: frozenset({"id", "token_hash"})
    )
    assert len(dropped) == 1
    assert out.findings == []


def test_keeps_schema_finding_when_column_truly_absent():
    f = _sf()
    rv = ReaderVerdict(risk_score=60, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_schema_findings(
        rv, lambda table: frozenset({"id"})
    )
    assert dropped == []
    assert out.findings == [f]


def test_keeps_schema_finding_when_table_unresolvable():
    """None means "can't tell" (no DB, table not found) — never settle on that."""
    f = _sf()
    rv = ReaderVerdict(risk_score=60, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_schema_findings(rv, lambda table: None)
    assert dropped == []
    assert out.findings == [f]


def test_does_not_settle_non_schema_findings_via_schema_filter():
    f = ReaderFinding(
        category_slug="race-condition",
        description="shared state without a lock",
        file="api.py",
        severity="high",
    )
    rv = ReaderVerdict(risk_score=70, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_schema_findings(
        rv, lambda table: frozenset({"anything"})
    )
    assert dropped == []
    assert out.findings == [f]


def test_schema_settlement_notice_explains_empty_findings_list():
    notice = settle.schema_settlement_notice([_sf()])
    assert notice is not None
    assert notice.rule == "settled-schema-dependency"
    assert notice.weight == 0.0


def test_score_one_applies_schema_settlement_and_keeps_score(monkeypatch):
    from doug import reader, review
    from doug.models import AuthorType, Band, PRMetadata

    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setattr(reader, "enabled", lambda: True)
    monkeypatch.setattr(
        reader,
        "read_diff",
        lambda meta, diff, *, scope, client=None: ReaderVerdict(
            risk_score=60,
            rationale="x",
            findings=[_sf()],
        ),
    )
    meta = PRMetadata(
        number=1,
        title="t",
        author="a",
        author_type=AuthorType.HUMAN,
        additions=1,
        deletions=0,
        files=["api/doug/store.py"],
        approvals=0,
        approval_latency_s=None,
        days_since_last_human_commit=None,
        files_added=0,
        files_modified=1,
        url="https://example.test/1",
        head_sha="abc",
        changed_files=1,
        files_dropped=[],
    )
    tier, verdict, rv, _cov = review.score_one(
        meta,
        "+ x",
        scope=reader.SENTINEL_SCOPE,
        resolve_schema=lambda table: frozenset({"id", "token_hash"}),
    )
    assert tier == "reader"
    assert rv is not None
    assert rv.findings == []
    assert verdict.score == 0.6
    assert verdict.band is Band.FLAGGED
    assert any(r.rule == "settled-schema-dependency" for r in verdict.reasons)
    assert all(r.rule != "reader:unmigrated-column" for r in verdict.reasons)


def test_score_one_applies_settlement_and_keeps_score(monkeypatch):
    from doug import reader, review
    from doug.models import AuthorType, Band, PRMetadata

    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setattr(reader, "enabled", lambda: True)
    monkeypatch.setattr(
        reader,
        "read_diff",
        lambda meta, diff, *, scope, client=None: ReaderVerdict(
            risk_score=40,
            rationale="x",
            findings=[_f()],
        ),
    )
    meta = PRMetadata(
        number=1,
        title="t",
        author="a",
        author_type=AuthorType.HUMAN,
        additions=1,
        deletions=0,
        files=["api.py"],
        approvals=0,
        approval_latency_s=None,
        days_since_last_human_commit=None,
        files_added=0,
        files_modified=1,
        url="https://example.test/1",
        head_sha="abc",
        changed_files=1,
        files_dropped=[],
    )
    tier, verdict, rv, _cov = review.score_one(
        meta, "+ x", scope=reader.SENTINEL_SCOPE, resolve_file=lambda p: FILE
    )
    assert tier == "reader"
    assert rv is not None
    assert rv.findings == []
    # Score is the instrument's; we do not rewrite it after settlement.
    assert verdict.score == 0.4
    assert verdict.band is Band.FLAGGED
    assert any(r.rule == "settled-missing-import" for r in verdict.reasons)
    assert all(r.rule != "reader:missing-import" for r in verdict.reasons)


# ---------------------------------------------------------------------------
# Third class (#307): the falsifier had already run.

from doug import ci_evidence as ci  # noqa: E402
from doug.ci_evidence import CheckResult, Job, Step  # noqa: E402


def _ci(*jobs, red=()):
    """Evidence from jobs whose check runs all concluded success, except `red`."""
    checks = [
        CheckResult(
            name=j.check_name,
            conclusion="failure" if j.check_name in red else "success",
            app="github-actions",
        )
        for j in jobs
    ]
    return ci.evidence(list(jobs), checks)


RUFF_AT_ROOT = Job("lint", (Step("uv run ruff check .", ""),))
RUFF_IN_API = Job("api", (Step("uv run ruff check .", "api"),))
WEB_LINT = Job("web-lint", (Step("npm run lint --workspace=web", ""),))
WEB_BUILD = Job("web-build", (Step("npm run build --workspace=web", ""),))

BOUND_BY_ASSIGNMENT = "LIMIT = 3\n\ndef f():\n    return LIMIT\n"


def _undef(name="LIMIT", file="api/doug/x.py", slug="undefined-name", desc=None):
    return ReaderFinding(
        category_slug=slug,
        description=desc or f"`{name}` is referenced but never defined, so f() raises NameError",
        file=file,
        severity="high",
    )


def _build_break(file="web/app/page.tsx"):
    return ReaderFinding(
        category_slug="unused-import-build-break",
        description="`signOutAction` is imported but no longer used, so the build fails",
        file=file,
        severity="medium",
    )


def _settle_ci(findings, evidence, files):
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=list(findings))
    calls = []

    def resolve_ci():
        calls.append(1)
        return evidence

    out, dropped = settle.drop_disproved_ci_findings(rv, resolve_ci, files.get)
    return out.findings, dropped, len(calls)


def test_a_green_ruff_run_over_the_file_settles_an_undefined_name_claim():
    """PR 28 and #232: the NameError the finding predicts is ruff F821, and
    F821 ran green at head over this very file."""
    kept, dropped, calls = _settle_ci(
        [_undef()], _ci(RUFF_IN_API), {"api/doug/x.py": BOUND_BY_ASSIGNMENT}
    )
    assert (kept, len(dropped), calls) == ([], 1, 1)


def test_a_missing_import_bound_by_assignment_is_the_shape_only_ruff_can_settle():
    """The import settlement keeps this one (LIMIT is not imported); ruff
    green settles it (LIMIT is bound, and ruff checked)."""
    f = _undef(slug="missing-import", desc="uses `LIMIT` with no import of it")
    assert settle.settle_many([f], lambda p: BOUND_BY_ASSIGNMENT) == [f]
    kept, dropped, _ = _settle_ci([f], _ci(RUFF_IN_API), {"api/doug/x.py": BOUND_BY_ASSIGNMENT})
    assert (kept, len(dropped)) == ([], 1)


def test_ruff_that_did_not_run_over_the_file_settles_nothing():
    """ruff ran in api/; scripts/ was never checked. Same evidence, no reach."""
    f = _undef(file="scripts/probe.py")
    kept, dropped, _ = _settle_ci([f], _ci(RUFF_IN_API), {"scripts/probe.py": BOUND_BY_ASSIGNMENT})
    assert (kept, dropped) == ([f], [])
    # At the root it reaches everything.
    kept, dropped, _ = _settle_ci([f], _ci(RUFF_AT_ROOT), {"scripts/probe.py": BOUND_BY_ASSIGNMENT})
    assert (kept, len(dropped)) == ([], 1)


def test_a_red_or_absent_ruff_keeps_the_finding():
    f = _undef()
    files = {"api/doug/x.py": BOUND_BY_ASSIGNMENT}
    kept, dropped, _ = _settle_ci([f], _ci(RUFF_IN_API, red={"api"}), files)
    assert (kept, dropped) == ([f], [])
    kept, dropped, _ = _settle_ci([f], _ci(WEB_BUILD), files)
    assert (kept, dropped) == ([f], [])
    kept, dropped, calls = _settle_ci([f], None, files)
    assert (kept, dropped, calls) == ([f], [], 1)


def test_the_ruff_boundary_table_is_a_veto_each():
    """REVIEWING.md: TYPE_CHECKING-only binding, a silenced line, and
    use-before-assignment are where ruff stops — so green ruff says nothing."""
    ev = _ci(RUFF_IN_API)
    type_checking = (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    LIMIT = 3\n"
        "def f():\n    return LIMIT\n"
    )
    kept, dropped, _ = _settle_ci([_undef()], ev, {"api/doug/x.py": type_checking})
    assert (len(kept), dropped) == (1, [])
    silenced = "def f():\n    return LIMIT  # noqa\n"
    kept, dropped, _ = _settle_ci([_undef()], ev, {"api/doug/x.py": silenced})
    assert (len(kept), dropped) == (1, [])
    silenced = "def f():\n    return LIMIT  # noqa: F821\n"
    kept, dropped, _ = _settle_ci([_undef()], ev, {"api/doug/x.py": silenced})
    assert (len(kept), dropped) == (1, [])
    # An unrelated noqa on another rule is not a veto.
    other = "LIMIT = 3\ndef f():\n    return LIMIT  # noqa: E501\n"
    kept, dropped, _ = _settle_ci([_undef()], ev, {"api/doug/x.py": other})
    assert (kept, len(dropped)) == ([], 1)
    before = _undef(desc="`LIMIT` is read before it is assigned on the retry path")
    kept, dropped, _ = _settle_ci([before], ev, {"api/doug/x.py": BOUND_BY_ASSIGNMENT})
    assert (len(kept), dropped) == (1, [])


def test_a_name_the_file_never_reads_cannot_be_followed():
    """A claim about `LIMIT` in a file that never loads `LIMIT` is a claim we
    cannot map onto ruff's check, so it stays. And a finding with nothing in
    backticks claims nothing."""
    ev = _ci(RUFF_IN_API)
    kept, dropped, _ = _settle_ci([_undef()], ev, {"api/doug/x.py": "x = 1\n"})
    assert (len(kept), dropped) == (1, [])
    bare = _undef(desc="LIMIT is never defined so this raises NameError")
    kept, dropped, _ = _settle_ci([bare], ev, {"api/doug/x.py": BOUND_BY_ASSIGNMENT})
    assert (len(kept), dropped) == (1, [])
    kept, dropped, _ = _settle_ci([_undef()], ev, {})  # unreadable at head
    assert (len(kept), dropped) == (1, [])


def test_f821_must_be_selected_where_the_file_lives():
    ev = _ci(RUFF_IN_API)
    files = {
        "api/doug/x.py": BOUND_BY_ASSIGNMENT,
        "api/pyproject.toml": '[tool.ruff.lint]\nselect = ["E"]\n',
    }
    kept, dropped, _ = _settle_ci([_undef()], ev, files)
    assert (len(kept), dropped) == (1, [])
    files["api/pyproject.toml"] = '[tool.ruff.lint]\nselect = ["E", "F"]\n'
    kept, dropped, _ = _settle_ci([_undef()], ev, files)
    assert (kept, len(dropped)) == ([], 1)


def test_a_build_break_claim_needs_lint_and_build_both_green_over_the_file():
    """PRs 75 and 198: "unused import breaks the build" when lint and build
    both passed at head. Either alone is not enough — the claim names one
    gate loosely, and the settlement must never rest on a gate the repo
    does not run."""
    kept, dropped, _ = _settle_ci([_build_break()], _ci(WEB_LINT, WEB_BUILD), {})
    assert (kept, len(dropped)) == ([], 1)
    kept, dropped, _ = _settle_ci([_build_break()], _ci(WEB_BUILD), {})
    assert (len(kept), dropped) == (1, [])
    kept, dropped, _ = _settle_ci([_build_break()], _ci(WEB_LINT, WEB_BUILD, red={"web-lint"}), {})
    assert (len(kept), dropped) == (1, [])
    # console/ has no job of its own: web's green says nothing about it.
    kept, dropped, _ = _settle_ci(
        [_build_break(file="console/app/page.tsx")], _ci(WEB_LINT, WEB_BUILD), {}
    )
    assert (len(kept), dropped) == (1, [])


def test_evidence_is_fetched_once_and_only_when_a_candidate_exists():
    other = ReaderFinding(
        category_slug="error-handling-gap", description="x", file="api/doug/x.py", severity="low"
    )
    kept, dropped, calls = _settle_ci([other], _ci(RUFF_IN_API), {})
    assert (len(kept), dropped, calls) == (1, [], 0)
    files = {"api/doug/x.py": BOUND_BY_ASSIGNMENT}
    kept, dropped, calls = _settle_ci(
        [_undef(), _undef(name="LIMIT"), other], _ci(RUFF_IN_API), files
    )
    assert (kept, len(dropped), calls) == ([other], 2, 1)


def test_ci_notice_names_the_gate_that_answered():
    ev = _ci(RUFF_IN_API, WEB_LINT, WEB_BUILD)
    notice = settle.ci_settlement_notice([_undef(), _build_break()], ev)
    assert notice.rule == "settled-ci-green"
    assert notice.weight == 0.0
    assert "api/doug/x.py: undefined-name (['api'])" in notice.label
    assert "web/app/page.tsx: unused-import-build-break (['web-lint', 'web-build'])" in notice.label
    assert settle.ci_settlement_notice([], ev) is None
    assert "(['?'])" in settle.ci_settlement_notice([_undef()], None).label
