"""Contracts for the convergence evaluation script.

The script is pointed at the production ledger by an operator, so two things
are tested here without touching any database: that it cannot write, and that
the accounting the pre-registered bars are graded on is right. Everything that
touches a connection stays out of these tests by construction — the analysis
half takes rows, not a cursor.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import convergence_eval

SCRIPT = Path(convergence_eval.__file__)

FILE = "api/doug/api.py"


def _v(id, pr_number=49, scored_at="2026-08-01T00:00:00", **kw):
    row = {
        "id": id,
        "repo": "drewjst/doug",
        "pr_number": pr_number,
        "scored_at": scored_at,
        "head_sha": f"sha{id}",
        "installation_id": 11,
        "github_repo_id": 22,
    }
    row.update(kw)
    return row


def _f(verdict_id, rule="reader:error-handling-gap", file=FILE, label="x", severity="high"):
    return {
        "verdict_id": verdict_id,
        "rule": rule,
        "label": label,
        "file": file,
        "severity": severity,
        "weight": 0.0,
        "hunks": None,
    }


def _read(verdict_id, files_unseen=(), file_cut=None, files_dropped=(), changed_files=3):
    return {
        "verdict_id": verdict_id,
        "files_unseen": list(files_unseen),
        "file_cut": file_cut,
        "files_dropped": list(files_dropped),
        "changed_files": changed_files,
    }


# --- read-only ------------------------------------------------------------


def test_script_contains_no_write_path():
    """This runs against the production ledger. `engine.connect()` without
    `.begin()` is the read-only contract the plan asks for; the runtime
    `SET TRANSACTION READ ONLY` makes the server enforce it too.

    Code tokens only — the module docstring names the verbs it avoids, and a
    test that cannot tell prose from code would push that explanation out of
    the file to stay green."""
    import io
    import tokenize

    code = "".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(SCRIPT.read_text()).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    )
    for verb in (".begin(", ".commit(", ".insert(", ".update(", ".delete(", "create_all"):
        assert verb not in code, verb
    assert "SET TRANSACTION READ ONLY" in SCRIPT.read_text()


def test_script_refuses_to_run_until_the_floor_is_signed_off(capsys):
    """The plan gates Task 3 on the controller confirming bar 1's floor
    BEFORE the evaluation runs. A gate nobody can forget to check beats a
    sentence in a doc: the operator has to type the pre-registered floor, and
    it must be the one in the design note."""
    assert convergence_eval.main([]) == 2
    assert "0.90" in capsys.readouterr().err

    assert convergence_eval.main(["--signed-off-floor", "0.5"]) == 2
    assert "0.90" in capsys.readouterr().err


# --- pairing --------------------------------------------------------------


def test_pairs_are_consecutive_and_ordered_by_scored_at():
    """Out-of-order ids happen (a retry scored later carries a higher id but
    the pair must still read old -> new)."""
    rows = [
        _v(3, scored_at="2026-08-03T00:00:00"),
        _v(1, scored_at="2026-08-01T00:00:00"),
        _v(2, scored_at="2026-08-02T00:00:00"),
    ]
    pairs = convergence_eval.consecutive_pairs(rows)
    assert [(a["id"], b["id"]) for a, b in pairs] == [(1, 2), (2, 3)]


def test_single_verdict_prs_yield_no_pairs():
    assert convergence_eval.consecutive_pairs([_v(1)]) == []


def test_prs_are_grouped_by_app_identity_not_by_repo_string():
    """`repo` is a display string; two installations can carry the same one.
    Grouping by it would diff one tenant's verdict against another's."""
    a = _v(1, installation_id=11)
    b = _v(2, installation_id=99)
    assert convergence_eval.group_key(a) != convergence_eval.group_key(b)


def test_historical_rows_without_app_identity_fall_back_to_repo():
    """Rows scored before migration 002 carry NULL ids (store.py:82-88).
    Grouping them all under (None, None, pr_number) would pool unrelated
    repos that share a PR number."""
    a = _v(1, installation_id=None, github_repo_id=None, repo="drewjst/doug")
    b = _v(2, installation_id=None, github_repo_id=None, repo="getsentry/sentry")
    assert convergence_eval.group_key(a) != convergence_eval.group_key(b)
    assert convergence_eval.group_key(a)[0] == "repo"


# --- per-pair payload -----------------------------------------------------


def test_pair_payload_carries_what_a_labeller_needs_without_db_access():
    """The labeller grades resolved-precision from this JSON alone: which
    finding, in which file, and what the classifier called it."""
    payload = convergence_eval.pair_payload(
        _v(1),
        _v(2, scored_at="2026-08-02T00:00:00"),
        {1: [_f(1)], 2: []},
        {1: _read(1), 2: _read(2)},
    )
    assert payload["from_verdict_id"] == 1
    assert payload["to_verdict_id"] == 2
    assert (payload["from_head_sha"], payload["to_head_sha"]) == ("sha1", "sha2")
    # Replaced rule 5: these historical rows carry hunks=NULL, so the honest
    # classification is no-hunk-index — never the old rule's `resolved`.
    assert payload["report"]["resolved"] == 0
    assert payload["report"]["unknown"] == {"no-hunk-index": 1}
    assert payload["classifications"] == [
        {
            "side": "prior",
            "state": "unknown",
            "unknown_reason": "no-hunk-index",
            "rule": "reader:error-handling-gap",
            "label": "x",
            "file": FILE,
            "severity": "high",
            "hunks": None,
        }
    ]


def test_pair_payload_reports_a_missing_later_read_row():
    """`later_read=None` is the difference between "the file was clean" and
    "we have no idea what the later verdict saw"."""
    payload = convergence_eval.pair_payload(_v(1), _v(2), {1: [_f(1)], 2: []}, {1: _read(1)})
    assert payload["later_coverage"] is None
    assert payload["report"]["unknown"] == {"file-uncovered": 1}


def test_settlement_notices_reach_the_classifier():
    """Findings and reasons are one table (store.py:104-114); the script must
    hand the later verdict's rows in as both, or rule 4 never fires and the
    ledger evaluation silently skips bar 3."""
    notice = _f(
        2,
        rule="settled-missing-import",
        file=None,
        label=(
            "Dropped 1 finding(s) disproved by runtime import at head — "
            f"{FILE}: error-handling-gap (['threading'])"
        ),
    )
    payload = convergence_eval.pair_payload(
        _v(1), _v(2), {1: [_f(1)], 2: [notice]}, {1: _read(1), 2: _read(2)}
    )
    assert payload["report"]["unknown"] == {"settled": 1}


# --- the bars' exposures --------------------------------------------------


def test_summary_counts_labelable_pairs_by_the_notes_definition():
    """A labelable pair is one whose EARLIER verdict has a reader finding with
    a complete identity — the note's definition, and the <10 STOP counts it."""
    labelable = convergence_eval.pair_payload(
        _v(1), _v(2), {1: [_f(1)], 2: []}, {1: _read(1), 2: _read(2)}
    )
    empty = convergence_eval.pair_payload(
        _v(3), _v(4), {3: [], 4: [_f(4)]}, {3: _read(3), 4: _read(4)}
    )
    no_identity = convergence_eval.pair_payload(
        _v(5),
        _v(6),
        {5: [_f(5, file=None), _f(5, rule="size-large")], 6: []},
        {5: _read(5), 6: _read(6)},
    )
    summary = convergence_eval.summarize([labelable, empty, no_identity])
    assert summary["pairs"] == 3
    assert summary["labelable_pairs"] == 1


def test_summary_reports_zero_exposure_rather_than_implying_a_pass():
    """REVIEWING.md: a bar that never met a case it could fail on has no
    evidence behind it, and the results doc must say so."""
    clean = convergence_eval.pair_payload(
        _v(1), _v(2), {1: [_f(1)], 2: []}, {1: _read(1), 2: _read(2)}
    )
    summary = convergence_eval.summarize([clean])
    assert summary["exposures"]["findings_uncovered"] == 0
    assert summary["exposures"]["findings_settled"] == 0
    assert summary["bars_without_exposure"] == [
        "bar 2 (uncovered-file findings)",
        "bar 3 (settled findings)",
    ]


def test_summary_counts_each_bars_exposure():
    uncovered = convergence_eval.pair_payload(
        _v(1), _v(2), {1: [_f(1)], 2: []}, {1: _read(1), 2: _read(2, files_unseen=[FILE])}
    )
    notice = _f(
        4,
        rule="settled-schema-dependency",
        file=None,
        label=(
            "Dropped 1 finding(s) disproved by the live schema — "
            f"{FILE}: error-handling-gap ([('verdicts', 'id')])"
        ),
    )
    settled = convergence_eval.pair_payload(
        _v(3), _v(4), {3: [_f(3)], 4: [notice]}, {3: _read(3), 4: _read(4)}
    )
    summary = convergence_eval.summarize([uncovered, settled])
    assert summary["exposures"]["findings_uncovered"] == 1
    assert summary["exposures"]["pairs_with_uncovered"] == 1
    assert summary["exposures"]["findings_settled"] == 1
    assert summary["exposures"]["pairs_with_settled"] == 1
    assert summary["bars_without_exposure"] == []


def test_slug_drift_covariate_counts_raw_slugs_against_patterns():
    """The probe measured 276 raw slugs over 395 findings; identity groups by
    the canonical pattern, so the gap is how much work the merge map is doing
    in this sample."""
    pair = convergence_eval.pair_payload(
        _v(1),
        _v(2),
        {
            1: [_f(1, rule="reader:unhandled-exception"), _f(1, rule="reader:race-condition")],
            2: [_f(2, rule="reader:missing-error-handling")],
        },
        {1: _read(1), 2: _read(2)},
    )
    drift = convergence_eval.summarize([pair])["slug_drift"]
    assert drift["raw_slugs"] == 3
    assert drift["patterns"] == 2


def test_path_form_suspects_surface_the_exact_match_exposure():
    """Identity compares paths by exact string equality. If a finding's file
    and the read's coverage paths spell the same file differently, rule 3
    stops abstaining — the failure bar 2 exists to catch. Same basename,
    different path is the signal."""
    pair = convergence_eval.pair_payload(
        _v(1),
        _v(2),
        {1: [_f(1, file="api/doug/api.py")], 2: []},
        {1: _read(1), 2: _read(2, files_unseen=["doug/api.py"])},
    )
    assert pair["path_form_suspects"] == [["api/doug/api.py", "doug/api.py"]]
    assert convergence_eval.summarize([pair])["path_form_suspects"] == [
        ["api/doug/api.py", "doug/api.py"]
    ]


def test_identical_paths_are_not_suspects():
    pair = convergence_eval.pair_payload(
        _v(1),
        _v(2),
        {1: [_f(1, file="api/doug/api.py")], 2: []},
        {1: _read(1), 2: _read(2, files_unseen=["api/doug/api.py"])},
    )
    assert pair["path_form_suspects"] == []


# --- hunk emulation (Walked Out commit 6) -----------------------------------


def _tmp_repo(tmp_path):
    import subprocess

    def git(*args):
        subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True, capture_output=True, text=True,
            env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                 "PATH": "/usr/bin:/bin"},
        )

    git("init", "-q", "-b", "main")
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n")
    git("add", "a.py")
    git("commit", "-qm", "base")
    base = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    # The emulation resolves merge-base against origin/main; a local clone
    # under test provides the ref directly.
    git("update-ref", "refs/remotes/origin/main", base)
    (tmp_path / "a.py").write_text("one\nTWO\nthree\n")
    git("add", "a.py")
    git("commit", "-qm", "head")
    head = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    return base, head


def test_index_from_git_hashes_with_the_products_own_function(tmp_path):
    """The eval and the product must compute ONE function: the emulated
    index's hashes are doug.hunks over the same per-file diff text git
    prints, so a Phase-0 outcome re-derived here is an outcome the shipped
    classifier would produce from stored rows."""
    import subprocess

    from doug import hunks as hunks_mod

    _, head = _tmp_repo(tmp_path)
    index = convergence_eval.index_from_git(str(tmp_path), head)
    assert set(index) == {"a.py"}
    base = subprocess.run(
        ["git", "-C", str(tmp_path), "merge-base", "origin/main", head],
        capture_output=True, text=True,
    ).stdout.strip()
    patch = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--unified=3", "--no-color",
         "--no-ext-diff", base, head, "--", "a.py"],
        capture_output=True, text=True,
    ).stdout
    assert index["a.py"] == [hunks_mod.hash_hunk(h) for h in hunks_mod.split_hunks(patch)]
    assert convergence_eval.index_from_git(str(tmp_path), "0" * 40) is None


def test_emulated_pairs_carry_the_label_and_stored_pairs_do_not():
    """Every number derived through emulation must carry `hunk-emulated`
    (the pre-registered label); rows the ledger stored are `stored`; a pair
    with no index on a side is None and abstains upstream."""
    reads = {
        1: _read(1),
        2: _read(2),
    }
    reads[1]["hunks"] = {FILE: ["a" * 64]}
    reads[2]["hunks"] = {FILE: ["a" * 64]}
    stored = convergence_eval.pair_payload(
        _v(1), _v(2, scored_at="2026-08-02T00:00:00"), {1: [_f(1)], 2: []}, reads
    )
    assert stored["index_label"] == "stored"
    assert stored["report"]["persisted"] == 1  # by construction, carried

    emulated = convergence_eval.pair_payload(
        _v(1), _v(2, scored_at="2026-08-02T00:00:00"), {1: [_f(1)], 2: []}, reads,
        emulated_ids={2},
    )
    assert emulated["index_label"] == "hunk-emulated"

    bare = convergence_eval.pair_payload(
        _v(1), _v(2, scored_at="2026-08-02T00:00:00"), {1: [_f(1)], 2: []},
        {1: _read(1), 2: _read(2)},
    )
    assert bare["index_label"] is None
    assert bare["report"]["unknown"] == {"no-hunk-index": 1}


def test_file_grain_proxy_reported_beside_never_in_place():
    """The file-grain name-only result is a different function from the
    shipped rule (merge-from-main counts as touched in git and not in
    patches); it rides beside the classification and moves nothing."""
    reads = {1: _read(1), 2: _read(2)}
    reads[1]["hunks"] = {FILE: ["a" * 64]}
    reads[2]["hunks"] = {FILE: ["b" * 64]}
    payload = convergence_eval.pair_payload(
        _v(1), _v(2, scored_at="2026-08-02T00:00:00"), {1: [_f(1)], 2: []}, reads,
        grain_fn=lambda prior, later: ["x.py"],
    )
    assert payload["file_grain_touched"] == ["x.py"]
    assert payload["report"]["unknown"] == {"edited-not-verified": 1}
