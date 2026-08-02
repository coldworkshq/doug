"""What the reader saw, and what it did not.

Every case here is built from lemahq/lema#643 at the commit Doug actually
reviewed (a076c15d) — real filenames, real patch sizes. That PR cleared at
0.26 on 44% of its diff, and the tenancy leak a human found afterwards sat
in the part that was never sent. These tests exist so that read can never
again be indistinguishable from a whole one.
"""

from sqlalchemy import create_engine, select

from doug import patterns, reader, review, store

# Every paid read is charged to a scope (reader._charge). Nothing here is
# about spend, so these reads charge a scope of their own and run against
# no ledger, which leaves the cap a no-op.
SCOPE = reader.installation_scope(1)

# (path, chars including the "### path (status, +a/-d)\n" header) — measured
# from the GitHub compare API at a076c15d, in the order fetch_pr emits them.
PR643 = [
    ("apps/api/cmd/lema-api/main.go", 1_023),
    ("apps/api/internal/api/agent_sessions.go", 8_580),
    ("apps/api/internal/api/agent_sessions_db_test.go", 12_005),
    ("apps/api/internal/api/router.go", 2_062),
    ("apps/api/internal/repo/agent_sessions.go", 14_042),
    ("apps/api/internal/repo/agent_sessions_read_db_test.go", 14_846),
    ("apps/api/internal/repo/sessions.go", 5_214),
    ("apps/web/lib/api.ts", 3_588),
    ("docs/design/sessions-lens/progress.md", 7_054),
]


def _diff(files=PR643) -> str:
    """A diff in exactly the shape review.fetch_pr builds — through
    reader.diff_chunk()/CHUNK_SEPARATOR, the same builder production code
    uses, so this fixture can never drift from what coverage() parses."""
    chunks = []
    for path, size in files:
        base = reader.diff_chunk(path, "added", 1, 0, "")
        chunks.append(reader.diff_chunk(path, "added", 1, 0, "x" * (size - len(base))))
    return reader.CHUNK_SEPARATOR.join(chunks)


def _pr(files=PR643):
    from doug.models import PRMetadata

    return PRMetadata.model_validate(
        {"number": 643, "title": "the org-scoped read path", "author": "drewjst",
         "files": [f for f, _ in files]}
    )


def test_coverage_names_the_files_the_read_never_saw():
    """The failure in one assertion: the mutation-verified test file that
    would have deduped two findings was not sent, and the file holding the
    real bug was cut in half."""
    cov = reader.coverage(_diff())

    assert not cov.complete
    assert 0.43 < cov.fraction < 0.45
    assert cov.file_cut == "apps/api/internal/repo/agent_sessions.go"
    assert cov.files_unseen == [
        "apps/api/internal/repo/agent_sessions_read_db_test.go",
        "apps/api/internal/repo/sessions.go",
        "apps/web/lib/api.ts",
        "docs/design/sessions-lens/progress.md",
    ]
    assert cov.files_sent == 5


def test_a_whole_diff_reports_itself_whole():
    small = [("a.py", 400), ("b.py", 600)]
    cov = reader.coverage(_diff(small))

    assert cov.complete and cov.fraction == 1.0
    assert cov.files_unseen == [] and cov.file_cut is None
    assert reader.truncation_reason(cov) is None


def test_a_diff_exactly_at_the_budget_is_not_partial():
    """Off-by-one at the cut would file complete reads as truncated forever."""
    cov = reader.coverage(_diff([("a.py", reader.DIFF_BUDGET)]))
    assert cov.complete and reader.truncation_reason(cov) is None


def test_file_cut_is_none_when_the_budget_lands_between_files(monkeypatch):
    """Regression: coverage() used to name the *last file whose header
    arrived* as `file_cut` unconditionally, even when the budget ran out in
    the separator between two files rather than inside either one's
    content — so a file that was sent whole got blamed for the cut."""
    a_chunk = reader.diff_chunk("a.py", "added", 1, 0, "x" * 500)
    b_chunk = reader.diff_chunk("b.py", "added", 1, 0, "y" * 500)
    diff = a_chunk + reader.CHUNK_SEPARATOR + b_chunk
    monkeypatch.setattr(reader, "DIFF_BUDGET", len(a_chunk))

    cov = reader.coverage(diff)

    assert cov.sent_chars == len(a_chunk) == len(diff[: reader.DIFF_BUDGET])
    assert not cov.complete  # b.py genuinely never arrived
    assert cov.files_unseen == ["b.py"]
    # The bug: file_cut used to report "a.py" here, even though a.py's
    # entire chunk fit in `sent` and only the separator was withheld.
    assert cov.file_cut is None


def test_file_cut_names_the_file_actually_cut_mid_content(monkeypatch):
    a_chunk = reader.diff_chunk("a.py", "added", 1, 0, "x" * 500)
    b_chunk = reader.diff_chunk("b.py", "added", 1, 0, "y" * 500)
    diff = a_chunk + reader.CHUNK_SEPARATOR + b_chunk
    # Budget lands well inside b.py's content, not at any seam.
    monkeypatch.setattr(reader, "DIFF_BUDGET", len(a_chunk) + len(reader.CHUNK_SEPARATOR) + 50)

    cov = reader.coverage(diff)

    assert not cov.complete
    assert cov.file_cut == "b.py"
    assert cov.files_unseen == []  # b.py's header arrived; only its tail didn't


def test_the_notice_states_the_share_read_and_the_files_dropped():
    notice = reader.truncation_reason(reader.coverage(_diff()))

    assert notice is not None
    assert notice.rule == "read-truncated"
    assert "44%" in notice.label
    assert "agent_sessions_read_db_test.go" in notice.label
    # Four files were dropped and three are named; the count must not be
    # quietly rounded down to what fits.
    assert "+1 more" in notice.label
    # The claim that matters: a clear here is not a clean bill of health.
    assert "not evidence about the rest" in notice.label


def test_the_notice_is_never_counted_as_a_defect_pattern():
    """It shares the findings table with real patterns, so precision would
    silently absorb it if it were named `reader:*`. /v1/patterns divides by
    these counts."""
    assert patterns.from_rule("read-truncated") is None
    assert patterns.from_rule("reader:race-condition") == "race-condition"


def test_diff_chunk_and_file_header_agree_on_the_shape():
    """The regex coverage() parses with and the function review.py builds
    diffs with used to be three independently hand-written copies of the
    same format. Now there's one builder; this pins that its output is
    exactly what the parser expects, so a future edit to either breaks a
    test instead of silently zeroing out coverage."""
    chunk = reader.diff_chunk("a/b.py", "modified", 3, 1, "@@ -1 +1 @@\n-x\n+y\n")
    m = reader._FILE_HEADER.search(chunk)
    assert m is not None and m.group(1) == "a/b.py"


def test_a_partial_read_says_so_on_the_verdict(monkeypatch):
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setattr(
        reader, "read_diff",
        lambda pr, diff, *, scope: reader.ReaderVerdict.model_validate(
            {"risk_score": 26, "rationale": "Looks fine.", "findings": []}
        ),
    )
    tier, verdict, _, cov = review.score_one(_pr(), _diff(), scope=SCOPE)

    assert tier == "reader" and not cov.complete
    # 0.26 against a 0.30 threshold: #643's exact verdict. It still clears —
    # coverage qualifies the verdict, it does not overrule the score — but
    # the row can no longer present itself as a complete read.
    assert verdict.band.value == "cleared"
    assert [r.rule for r in verdict.reasons] == ["read-truncated"]


def test_the_deterministic_tier_reports_no_coverage(monkeypatch):
    """It never opens the diff, so "0% read" would be a false statement
    about a tier that makes no claim to have read anything."""
    monkeypatch.delenv("DOUG_READER", raising=False)
    tier, _, _, cov = review.score_one(_pr(), _diff(), scope=SCOPE)
    assert tier == "deterministic" and cov is None


def test_coverage_is_recorded_for_complete_reads_too(tmp_path, monkeypatch):
    """Absence of a row must not be the signal for "read it all" — that is
    indistinguishable from a verdict written before this table existed."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    whole = reader.coverage(_diff([("a.py", 400)]))
    vid = store.save_review("lemahq/lema", 643, "reader", _verdict(), coverage=whole)

    with create_engine(f"sqlite:///{tmp_path}/doug.db").connect() as conn:
        row = conn.execute(select(store.reads)).mappings().one()
        assert row["verdict_id"] == vid
        assert row["diff_chars"] == row["sent_chars"] == 400
        assert row["files_unseen"] == [] and row["file_cut"] is None


def test_save_review_without_coverage_writes_no_reads_row(tmp_path, monkeypatch):
    """The deterministic tier passes coverage=None; that must not produce a
    reads row that looks like a zero-length or empty read."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    store.save_review("o/r", 1, "deterministic", _verdict())

    with create_engine(f"sqlite:///{tmp_path}/doug.db").connect() as conn:
        assert conn.execute(select(store.reads)).mappings().all() == []


def test_save_read_is_a_no_op_without_a_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    assert store.save_read(None, reader.coverage(_diff())) == 0


def _verdict():
    from doug.models import Band, Verdict

    return Verdict(score=0.26, band=Band.CLEARED, threshold=0.30, reasons=[])


def test_the_intent_read_sees_exactly_what_the_risk_read_saw():
    """`coverage()` is a pure function of the diff, which is what lets the
    two reads share one stored Coverage row.

    review.IntentRead's docstring asserts this ("read_with_decisions()
    truncates the identical diff at the identical DIFF_BUDGET"), and
    worker.process_job's replay path now *depends* on it: only the risk
    read's coverage is persisted, so a replayed deviation section is
    hedged with that row. If the two reads could ever see different
    amounts, a replayed check run would misreport what the intent read
    was shown — the one thing this module exists to prevent — so the
    assumption gets a test rather than a comment.
    """
    from doug import reader

    diff = "### a.py (modified, +5/-1)\n" + ("x" * (reader.DIFF_BUDGET + 5_000))

    assert reader.coverage(diff) == reader.coverage(diff)
    # And the property that makes that true: nothing outside the diff feeds it.
    assert reader.coverage(diff) != reader.coverage(diff + "\n### b.py (added, +1/-0)\n")


# --- Coverage integrity: changed_files / files_dropped -------------------

def test_a_read_missing_no_files_is_complete_when_the_count_matches():
    """The baseline this whole feature protects: when every changed file
    made it into the diff and nothing was budget-cut, complete stays True
    exactly like before changed_files existed."""
    small = [("a.py", 400), ("b.py", 600)]
    cov = reader.coverage(_diff(small), changed_files=2)
    assert cov.complete
    assert cov.files_dropped == []


def test_a_read_is_incomplete_when_files_were_dropped_before_the_diff_was_built():
    """The bug this closes: a PR with files GitHub reported but that never
    got a patch (binary, or beyond an unpaginated list_files call) used to
    be invisible to coverage() entirely — files_sent/files_unseen only ever
    see files that had a header in the diff string. A 250-file PR reading
    100 files rendered as a complete read. changed_files + files_dropped
    are supplied by the caller (from the PR object), not derived here,
    because coverage() only ever sees the diff text, never the file list."""
    small = [("a.py", 400), ("b.py", 600)]  # both fully sent, budget not a factor
    cov = reader.coverage(_diff(small), changed_files=3, files_dropped=["c.bin"])
    assert not cov.complete
    assert cov.files_dropped == ["c.bin"]
    assert cov.changed_files == 3


def test_changed_files_unset_preserves_the_old_complete_rule():
    """Every existing caller (and every test above this one in this file)
    never passes changed_files. That must keep meaning "not tracked", not
    "zero known changed files" — which would make every untouched call site
    incomplete by accident."""
    cov = reader.coverage(_diff([("a.py", 400)]))
    assert cov.changed_files is None
    assert cov.complete


def test_the_notice_mentions_files_dropped_before_the_diff_even_when_nothing_was_cut():
    """A read that saw its whole diff string in full but never received
    every file must still say so — 'complete' would otherwise be a claim
    about characters sent, not about the PR."""
    cov = reader.coverage(
        _diff([("a.py", 400)]), changed_files=2, files_dropped=["b.bin"]
    )
    notice = reader.truncation_reason(cov)
    assert notice is not None
    assert "b.bin" in notice.label


def test_score_one_carries_the_prs_changed_files_and_dropped_list_into_coverage(monkeypatch):
    """meta already knows changed_files/files_dropped from fetch_pr —
    score_one must actually pass them to coverage() rather than leaving
    them at the defaults, or a dropped-binary-file PR still renders
    complete."""
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setattr(
        reader, "read_diff",
        lambda pr, diff, *, scope: reader.ReaderVerdict.model_validate(
            {"risk_score": 10, "rationale": "fine", "findings": []}
        ),
    )
    from doug.models import PRMetadata

    pr = PRMetadata.model_validate({
        "number": 1, "title": "t", "author": "a",
        "files": ["a.py"], "changed_files": 2, "files_dropped": ["b.bin"],
    })
    _tier, _verdict, _rv, cov = review.score_one(pr, _diff([("a.py", 400)]), scope=SCOPE)
    assert not cov.complete
    assert cov.files_dropped == ["b.bin"]


def test_a_mismatched_changed_files_count_alone_does_not_mark_a_read_incomplete():
    """changed_files is a display field (the receipt's "N of M"), not part
    of the completeness check — files_dropped is. A PR with a genuinely
    binary file (caught below) would otherwise be permanently incomplete:
    files_sent can never equal changed_files when one changed file never
    produces a diff header at all."""
    cov = reader.coverage(_diff([("a.py", 400)]), changed_files=5, files_dropped=[])
    assert cov.complete
