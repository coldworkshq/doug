"""The check run is the only thing Doug writes to a pull request.

Three properties are load-bearing and every one of them has already been
got wrong somewhere in this codebase, so they are tested as defects:
a deterministic fallback must not read as a read (review.py:118-142 falls
back silently), a partial read must not read as a whole one, and nothing
here may ever conclude anything but neutral.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from doug import check_run, reader, store
from doug.models import Band, Reason
from doug.review import IntentRead
from doug.settle import SETTLED_REASON_CODES

# Built through the real producer rather than hand-constructed, so a
# regression in verdict_from_reader's severity handling (reader.py:407-419)
# can actually fail this suite instead of being masked by a fixture that
# sets severity="high" directly, bypassing the code path that is supposed
# to set it.
FLAGGED = reader.verdict_from_reader(
    reader.ReaderVerdict(
        risk_score=62,
        rationale="Concurrent writes to shared cache without a lock.",
        findings=[
            reader.ReaderFinding(
                category_slug="race-condition",
                description="Cache write is not guarded",
                file="cache.py",
                severity="high",
            )
        ],
    ),
    threshold=30,
)
FLAGGED_VERDICT = FLAGGED
CLEARED_VERDICT = FLAGGED.model_copy(update={"reasons": [], "band": Band.CLEARED, "score": 0.04})
# Cleared, and carrying a graded finding anyway — 0.26 against a flag line of
# 0.40. Not a contrived shape: it is the ordinary one, and it is the reason
# the alert is keyed to the band rather than to a severity.
CLEARED_WITH_A_MEDIUM = reader.verdict_from_reader(
    reader.ReaderVerdict(
        risk_score=26,
        rationale="Reservation is advanced before the write.",
        findings=[
            reader.ReaderFinding(
                category_slug="non-atomic-reservation",
                description="last_seq advances before the GitHub write",
                file="pr_comment.py",
                severity="medium",
            )
        ],
    ),
    threshold=40,
)

WHOLE = reader.Coverage(diff_chars=400, sent_chars=400, files_sent=2, files_unseen=[])
PARTIAL = reader.Coverage(
    diff_chars=68_430,
    sent_chars=30_000,
    files_sent=3,
    files_unseen=["api/tenancy.py", "tests/test_tenancy.py"],
    file_cut="api/store.py",
)
# A second, distinct partial coverage — used to prove the intent section's
# truncation notice is neither dropped when it matches the risk section's
# nor silently merged into it when it doesn't.
OTHER_PARTIAL = reader.Coverage(
    diff_chars=10_000, sent_chars=4_000, files_sent=1, files_unseen=["web/app.py"]
)

DEVIATIONS = IntentRead(
    alignment=41,
    refs=["ADR-0002"],
    findings=[
        reader.DeviationFinding(
            type="contradicts-ticket",
            description="Edits the frozen reader prompt",
            severity="high",
        )
    ],
    coverage=WHOLE,
)
DEVIATIONS_PARTIAL = DEVIATIONS.model_copy(update={"coverage": PARTIAL})


def test_reader_title_leads_with_the_band_and_score():
    title, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert title.lower().startswith("flagged")
    assert "0.62" in title
    assert not title.lower().startswith("deterministic")


def test_a_deterministic_fallback_announces_itself_in_the_title():
    """Tier honesty (Global Constraints). score_one falls back to the
    deterministic scorer whenever the reader is off or a read raised, and
    the Verdict it returns is shape-identical to a real read's. A footnote
    is not enough: the title is the only part of a check run visible from
    the PR's checks list, so that is where the difference has to be."""
    title, summary = check_run.render("deterministic", FLAGGED, None, None)
    assert title.lower().startswith("deterministic fallback")
    assert "0.62" in title and "flagged" in title.lower()
    assert "did not run" in summary


def test_a_reader_run_does_not_claim_a_fallback():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "did not run" not in summary


def test_the_band_capitalizes_the_same_way_on_both_tiers():
    """The title is PR-visible contract. 'Flagged' on the reader path and
    'flagged' on the fallback path would read as two check runs disagreeing
    about something — only the tier differs, not the band's own spelling."""
    reader_title, _ = check_run.render("reader", FLAGGED, None, WHOLE)
    fallback_title, _ = check_run.render("deterministic", FLAGGED, None, None)
    assert "Flagged" in reader_title
    assert "Flagged" in fallback_title
    assert "flagged" not in fallback_title


def test_the_summary_says_the_check_never_blocks():
    """ADR-0010: the surface is advisory. A reader who sees "Flagged" on a
    red-looking check and assumes it gated the merge has been misled about
    what this product does."""
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "never blocks" in summary
    assert "neutral" in summary


def test_the_summary_says_risk_is_shape_not_a_grade():
    """The number reads as a grade to anyone fresh — "0.52, we scored
    poorly" — and then fixing findings not moving it reads as a bug. It
    prices what the change touches, so the copy has to say so on BOTH
    tiers, or the first author to fix four findings and re-push concludes
    the tool is broken (that author was us, PR #50)."""
    _, reader_summary = check_run.render("reader", FLAGGED, None, WHOLE)
    _, fallback_summary = check_run.render("deterministic", FLAGGED, None, None)
    for summary in (reader_summary, fallback_summary):
        assert "not a grade" in summary
        assert "does not go down as findings are fixed" in summary


def test_findings_render_with_their_rule_and_label():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "reader:race-condition" in summary
    assert "Cache write is not guarded" in summary
    assert "high" in summary


def test_a_clean_verdict_renders_an_explicit_none():
    """An empty findings section and a missing one look the same to a
    reader; only one of them means "looked and found nothing". Asserting
    the literal "- none" line (not just the substring "none" anywhere in
    the summary) is the point — a finding label that merely contained the
    word "none" would pass a weaker check without the section actually
    being empty."""
    clean = FLAGGED.model_copy(update={"reasons": [], "band": Band.CLEARED, "score": 0.04})
    _, summary = check_run.render("reader", clean, None, WHOLE)
    assert "- none" in summary.splitlines()


def test_flagged_with_only_settlement_notices_does_not_read_as_a_remaining_defect():
    """settle.py drops disproved findings and leaves a weight-0 notice so
    the ledger stays honest. The check run used to list that notice under
    ### Findings beneath a Flagged title, which operators read as "Doug
    still found something" — the band is the risk score; nothing survived.
    """
    from doug.settle import SETTLED_REASON_CODES

    assert SETTLED_REASON_CODES == {
        "settled-missing-import",
        "settled-schema-dependency",
    }
    for rule in sorted(SETTLED_REASON_CODES):
        settled = FLAGGED.model_copy(
            update={
                "reasons": [
                    Reason(
                        rule=rule,
                        label=f"Dropped 2 finding(s) — {rule}",
                        weight=0.0,
                    )
                ]
            }
        )
        title, summary = check_run.render("reader", settled, None, WHOLE)
        assert title.lower().startswith("flagged")
        assert check_run.SETTLED_NOTE in summary
        assert "risk score" in summary.lower()
        assert rule in summary
        assert "- none" not in summary.splitlines()


def test_a_settled_prefix_near_miss_is_not_a_settlement_notice():
    """Prefix matching would treat any settled-* rule as the two producers
    in settle.py. A hand-written near-miss must still look like a remaining
    finding, not get SETTLED_NOTE."""
    near = FLAGGED.model_copy(
        update={
            "reasons": [
                Reason(
                    rule="settled-by-hand",
                    label="Someone labelled this settled",
                    weight=0.0,
                )
            ]
        }
    )
    _, summary = check_run.render("reader", near, None, WHOLE)
    assert check_run.SETTLED_NOTE not in summary
    assert "settled-by-hand" in summary


def test_a_truncated_read_never_claims_every_finding_was_disproved():
    """SETTLED_NOTE says "Every finding the read produced was disproved."
    On a partial read that sentence is not available: the read never saw
    the whole diff, so there is no "every". The truncation Reason is
    filtered out of `risks` before the all() runs, so without an explicit
    guard a truncated read renders the absolute claim directly beneath a
    blockquote that says a clear is not evidence about the rest — the two
    sentences contradict on the one surface that exists to be honest.
    """
    truncated = FLAGGED.model_copy(
        update={
            "reasons": [
                reader.truncation_reason(PARTIAL),
                Reason(
                    rule="settled-missing-import",
                    label="Dropped 2 finding(s) disproved by runtime import at head",
                    weight=0.0,
                ),
            ]
        }
    )
    _, summary = check_run.render("reader", truncated, None, PARTIAL)
    assert "a clear is not evidence about the rest" in summary
    assert check_run.SETTLED_NOTE not in summary
    # The settlement itself is still disclosed — suppressing the absolute
    # claim must not suppress the ledger line that says what was dropped.
    assert "settled-missing-import" in summary
    assert "- none" not in summary.splitlines()


def test_a_whole_read_still_gets_the_settled_note():
    """The guard above must not silence the note on the complete read it
    was built for — otherwise the fix trades one dishonesty for a regression.
    """
    settled = FLAGGED.model_copy(
        update={
            "reasons": [
                Reason(
                    rule="settled-missing-import",
                    label="Dropped 2 finding(s) disproved by runtime import at head",
                    weight=0.0,
                )
            ]
        }
    )
    _, summary = check_run.render("reader", settled, None, WHOLE)
    assert check_run.SETTLED_NOTE in summary


def test_a_partial_read_is_called_out_once_and_only_once():
    """score_one already appends the read-truncated Reason to the verdict
    (review.py:133-134), so rendering the coverage block naively duplicated
    it. The block is the better surface — it is above the findings, where a
    caveat about the findings has to be — so the reason is folded into it
    rather than printed twice."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    _, summary = check_run.render("reader", verdict, None, PARTIAL)
    assert summary.count("Partial read") == 1
    assert "api/tenancy.py" in summary
    assert "api/store.py" in summary


def test_a_truncation_reason_is_never_silently_dropped():
    """The fold above is conditional on the coverage block actually
    rendering. If a caller ever passes the reason without the coverage, the
    line still has to reach the PR — dropping it is the exact failure the
    coverage work existed to end."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    _, summary = check_run.render("reader", verdict, None, None)
    assert "read-truncated" in summary


def test_a_whole_read_gets_no_coverage_notice():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "Partial read" not in summary


def test_the_summary_is_truncated_below_githubs_cap():
    """GitHub rejects output.summary over 65535 chars. A PR with hundreds of
    findings must produce a shorter check run, not an API error that loses
    the whole verdict. The cut itself must say so — a summary truncated
    with no marker reads as complete, which is the same "partial looks
    whole" failure this module exists to keep out of the findings above
    it, one level up."""
    noisy = FLAGGED.model_copy(
        update={
            "reasons": [
                Reason(rule=f"reader:pattern-{i}", label="x" * 300, weight=0.0)
                for i in range(500)
            ]
        }
    )
    _, summary = check_run.render("reader", noisy, None, WHOLE)
    assert len(summary) <= check_run.SUMMARY_LIMIT
    assert summary.endswith("missing from the list above._")
    assert check_run.TRUNCATION_LEAD in summary


def test_truncation_keeps_the_instrument_footer():
    """The footer is why this increment exists. Cutting the summary from
    the front would drop it on the 400-finding PR — the one case the cap
    is sized for — and leave a check that never shows N/M."""
    noisy = FLAGGED.model_copy(
        update={
            "reasons": [
                Reason(rule=f"reader:pattern-{i}", label="x" * 300, weight=0.0)
                for i in range(500)
            ]
        }
    )
    _, summary = check_run.render(
        "reader", noisy, None, WHOLE, instrument=_snap()
    )
    assert len(summary) <= check_run.SUMMARY_LIMIT
    assert check_run.TRUNCATION_LEAD in summary
    assert summary.endswith("deep reads 0/200 this cycle")
    assert "adjudicated 0" in summary.split(check_run.TRUNCATION_LEAD, 1)[1]


def _oversized(n: int = 300, *, extra: list | None = None):
    """A verdict whose findings alone overrun SUMMARY_LIMIT.

    Graded high/low in alternation so the render exercises both halves of
    the triage — the leading list and the collapsed fold — on the one shape
    where the cut can reach either.
    """
    reasons = [
        Reason(
            rule=f"reader:pattern-{i}",
            label=f"{i} " + "x" * 400,
            weight=0.0,
            severity="high" if i % 2 else "low",
            file=f"api/doug/module_{i}.py",
        )
        for i in range(n)
    ]
    return FLAGGED.model_copy(update={"reasons": reasons + list(extra or [])})


def _shortfall(summary: str) -> tuple[int, int]:
    """(dropped, total) as the truncation notice states them."""
    m = re.search(r"(\d+) of (\d+) findings (?:is|are) missing", summary)
    assert m is not None, "the cut named no shortfall"
    return int(m.group(1)), int(m.group(2))


def test_the_cut_names_how_many_findings_it_removed():
    """#181. SUMMARY_LIMIT is the third place a finding can disappear, and
    it was the only one that disappeared them silently: settle.py's two
    rules each leave a weight-0 notice saying what they dropped and why,
    while this cut appended "truncated" and left the reader to believe the
    list was the whole list. A review that emits 12 findings and displays 8
    then reads, on the check run, as a review that found 8 — the emitted
    and displayed counts are both on the surface and there is nothing
    connecting them."""
    noisy = _oversized()
    _, summary = check_run.render("reader", noisy, None, WHOLE)

    dropped, total = _shortfall(summary)
    shown = sum(1 for r in noisy.reasons if check_run._bullet(r, None) in summary)
    assert dropped > 0, "this fixture must overrun the cap"
    assert total == len(noisy.reasons)
    assert shown + dropped == total


def test_the_stated_shortfall_reconciles_with_the_table():
    """The number the notice subtracts from has to be the number printed in
    the summary table, or naming the shortfall buys nothing: a reader who
    cannot do the arithmetic from the two figures in front of them is back
    where they started."""
    _, summary = check_run.render("reader", _oversized(), None, WHOLE)
    cell = [ln for ln in summary.splitlines() if ln.startswith("| **")][0]
    counted = sum(int(n) for n, _ in re.findall(r"(\d+) (high|medium|low)", cell))
    assert counted == _shortfall(summary)[1]


def test_settlement_notices_are_not_counted_as_lost_findings():
    """settle.py's notices mark findings that were DISPROVED, so
    `_finding_counts` excludes them from the table and the shortfall
    excludes them for the same reason. Counting one as a lost finding would
    report a missing defect where there was never a defect to miss — #109's
    misreading, reached through the truncation notice."""
    settled = [
        Reason(rule=code, label="Dropped 1 finding disproved at head", weight=0.0)
        for code in sorted(SETTLED_REASON_CODES)
    ]
    noisy = _oversized(extra=settled)
    _, summary = check_run.render("reader", noisy, None, WHOLE)
    assert _shortfall(summary)[1] == len(noisy.reasons) - len(settled)


def test_a_cut_that_reaches_no_finding_claims_no_shortfall():
    """The findings list renders near the top, so an overrun driven by the
    sections below it costs prose, not findings. "0 of 12 findings are
    missing" would send a reader hunting for one that is already on the
    page."""
    verdict = FLAGGED.model_copy(deep=True)
    huge = IntentRead(
        alignment=41,
        refs=["ADR-0002"],
        findings=[
            reader.DeviationFinding(
                type=f"contradicts-ticket-{i}",
                description="y" * 400,
                severity="high",
            )
            for i in range(200)
        ],
        coverage=WHOLE,
    )
    _, summary = check_run.render("reader", verdict, huge, WHOLE)
    assert len(summary) <= check_run.SUMMARY_LIMIT
    assert check_run.TRUNCATION_LEAD in summary
    assert "missing from the list above" not in summary
    for r in verdict.reasons:
        assert check_run._bullet(r, None) in summary


def test_severity_not_position_decides_what_survives_the_cut():
    """#181's second half. The cut is positional, so what it removes is
    decided entirely by the order the list renders in — and that order is
    `_by_severity`'s, not the read's. A high finding the model happened to
    emit last must still be on the page when 300 low ones are not."""
    reasons = [
        Reason(rule=f"reader:pattern-{i}", label=f"{i} " + "x" * 400, weight=0.0,
               severity="low", file=f"api/doug/module_{i}.py")
        for i in range(400)
    ]
    reasons[-1] = reasons[-1].model_copy(update={"severity": "high"})
    verdict = FLAGGED.model_copy(update={"reasons": reasons})
    _, summary = check_run.render("reader", verdict, None, WHOLE)

    assert _shortfall(summary)[0] > 0
    # Emitted last, rendered first: the one high finding leads the list.
    assert summary.split("### Findings")[1].lstrip().startswith(
        check_run._bullet(reasons[-1], None)
    )
    # Emitted second-to-last, rendered last, and cut: a low finding is what
    # the overrun costs, whatever position the read gave it.
    assert check_run._bullet(reasons[-2], None) not in summary


def test_the_cut_ends_on_a_whole_line():
    """A body sliced mid-word with an italic sentence bolted to its tail
    reads as a rendering fault rather than a stated limit, and the last
    half-bullet is a finding a reader may act on without its file, its
    severity or its verb. Backing up to the line boundary costs a few
    hundred of 60,000 characters."""
    _, summary = check_run.render("reader", _oversized(), None, WHOLE)
    body = summary.split(check_run.TRUNCATION_LEAD)[0].rstrip("\n_")
    last = body.splitlines()[-1]
    assert last.startswith("- ")
    assert last in [check_run._bullet(r, None) for r in _oversized().reasons]


def test_a_cut_that_lands_on_a_boundary_keeps_its_last_line():
    """Doug's own read of this change, finding 1. Backing up to the last
    newline is right when the cut split a line and wrong when it did not:
    a cut that already ends a line loses a whole finding to punctuation,
    and the notice then reports a shortfall the cap did not cause."""
    body = "- one\n- two\n- three"
    assert check_run._whole_lines(body, 12) == "- one\n- two"  # cut ON the newline
    assert check_run._whole_lines(body, 15) == "- one\n- two"  # cut mid-word
    assert check_run._whole_lines(body, len(body)) == body
    assert check_run._whole_lines(body, 999) == body
    # No whole line at all: the empty string, not the half-written one.
    # `> 0` here returned exactly the fragment this helper removes.
    assert check_run._whole_lines("\nhalf a bullet", 8) == ""


def test_the_shortfall_reconciles_with_a_degraded_findings_cell():
    """Doug's own read of this change, finding 2. `_finding_counts` stops
    naming severities the moment one finding carries a grade outside the
    vocabulary and prints a bare count instead. The notice's total has to
    reconcile with THAT number too — a reader cannot be asked to know which
    of the cell's two shapes they are looking at."""
    noisy = _oversized()
    noisy.reasons[0] = noisy.reasons[0].model_copy(update={"severity": "catastrophic"})
    _, summary = check_run.render("reader", noisy, None, WHOLE)
    cell = [ln for ln in summary.splitlines() if ln.startswith("| **")][0]
    assert f"{len(noisy.reasons)} findings" in cell
    assert _shortfall(summary)[1] == len(noisy.reasons)


def _cut_inside_the_fold():
    """A verdict whose leading findings fit and whose low ones do not, so
    the cut lands inside the collapsed disclosure."""
    reasons = [
        Reason(rule=f"reader:pattern-h{i}", label=f"h{i} " + "x" * 400, weight=0.0,
               severity="high", file=f"api/doug/high_{i}.py")
        for i in range(10)
    ] + [
        Reason(rule=f"reader:pattern-l{i}", label=f"l{i} " + "x" * 400, weight=0.0,
               severity="low", file=f"api/doug/low_{i}.py")
        for i in range(300)
    ]
    return FLAGGED.model_copy(update={"reasons": reasons})


def test_a_cut_inside_the_fold_closes_it():
    """An unterminated <details> swallows the rest of the document. The
    truncation notice and the instrument footer would both render inside a
    collapsed block, so the one line saying findings are missing would
    itself be hidden behind a triangle — #181's defect, one level out."""
    _, summary = check_run.render(
        "reader", _cut_inside_the_fold(), None, WHOLE, instrument=_snap()
    )
    assert summary.count("<details>") == summary.count("</details>") == 1
    assert len(summary) <= check_run.SUMMARY_LIMIT
    tail = summary.split("</details>", 1)[1]
    assert check_run.TRUNCATION_LEAD in tail
    assert "adjudicated 0" in tail


def test_a_fold_the_cut_emptied_is_dropped_rather_than_closed():
    """`_fold` writes four lines before its first bullet, so the cut can
    land between the disclosure and everything it hides. An empty triangle
    labelled "N low findings" sitting above a notice saying those findings
    are missing is two contradictory claims about one list."""
    kept = "### Findings\n\n- **high** `a.py` — one\n\n<details>\n<summary>3 low findings</summary>"
    assert check_run._trim_empty_fold(kept).endswith("— one")
    assert check_run._close_details(check_run._trim_empty_fold(kept)) == ""
    # A fold that kept at least one bullet is closed, not dropped.
    with_body = kept + "\n\n- **low** `b.py` — two"
    assert check_run._trim_empty_fold(with_body) == with_body
    assert check_run._close_details(with_body) == "\n</details>"


def test_a_half_written_bullet_counts_as_missing():
    """The cut lands mid-line far more often than on a boundary. A bullet
    the cut left half-written is not a finding a reader can act on, and
    counting it as shown would understate the shortfall by exactly the
    finding most likely to be misread."""
    kept = "- **high** `x` — the whole line\n- **high** `y` — half a li"
    bullets = ["- **high** `x` — the whole line", "- **high** `y` — half a line"]
    assert check_run._shown_findings(kept, bullets) == 1


def test_identical_findings_are_counted_once_each():
    """`_shown_findings` scans from a cursor that only moves forward. Two
    findings that render to the same bullet — same severity, same file,
    same sentence — must consume two matches, not match the one surviving
    line twice and report a shortfall smaller than the list."""
    bullet = "- **low** `api/doug/store.py` — the same sentence twice"
    assert check_run._shown_findings(bullet, [bullet, bullet]) == 1
    assert check_run._shown_findings(bullet + "\n" + bullet, [bullet, bullet]) == 2


def test_deviations_render_under_an_unvalidated_heading():
    """The derangement check FAILED on 2026-07-31 — this instrument has no
    validity evidence. Rendering its output beside reader findings, which
    do have some, would launder one into the other."""
    _, summary = check_run.render("reader", FLAGGED, DEVIATIONS, WHOLE)
    heading = next(ln for ln in summary.splitlines() if ln.startswith("### Decision"))
    assert "unvalidated" in heading.lower()
    assert "Edits the frozen reader prompt" in summary
    assert "ADR-0002" in summary


def test_deviations_move_neither_the_band_nor_the_score():
    """ADR-0007, enforced at the surface as well as in the ledger. The
    rendered title and risk line must be byte-identical with the intent
    read present and absent."""
    bare_title, bare = check_run.render("reader", FLAGGED, None, WHOLE)
    dev_title, dev = check_run.render("reader", FLAGGED, DEVIATIONS, WHOLE)
    assert bare_title == dev_title
    # The summary table is where the band, the score and the flag line are
    # stated. Asserting the whole ROW, byte-for-byte, is the point: a
    # deviation that nudged any one of the three would have to change this
    # line, and there is nowhere else for those numbers to hide.
    row = "| **0.62** | 0.30 | validated diff reader | 1 high |"
    assert row in bare and row in dev
    assert dev.startswith(bare[: bare.index("### Findings")])


def test_no_deviation_section_without_an_intent_read():
    """No read happened is not the same as a read that found nothing, and
    an empty labelled section would assert the second."""
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "Decision deviations" not in summary
    assert "unvalidated" not in summary.lower()


def test_a_clean_intent_read_is_distinguishable_from_no_read():
    clean = DEVIATIONS.model_copy(update={"findings": [], "alignment": 92})
    _, summary = check_run.render("reader", FLAGGED, clean, WHOLE)
    assert "Decision deviations" in summary
    assert "alignment 92/100" in summary


def test_a_whole_intent_read_gets_no_deviation_coverage_notice():
    _, summary = check_run.render("reader", FLAGGED, DEVIATIONS, WHOLE)
    assert "Partial read" not in summary


def test_a_partial_intent_read_is_called_out_in_the_deviation_section():
    """IntentRead carries its own coverage (review.py:149-153) because a
    deviation built from a truncated diff is exactly as unverifiable past
    the cut as a risk finding is — it just wasn't saying so. The risk
    coverage here is WHOLE (no risk-side notice), so the only source of a
    "Partial read" line is the deviation section itself."""
    _, summary = check_run.render("reader", FLAGGED, DEVIATIONS_PARTIAL, WHOLE)
    deviation_start = summary.index(check_run.DEVIATION_HEADING)
    assert "Partial read" in summary[deviation_start:]
    assert summary.count("Partial read") == 1


def test_an_identical_partial_notice_is_not_duplicated_across_sections():
    """The risk tier and the intent tier ordinarily read the same diff at
    the same DIFF_BUDGET, so their coverage objects usually agree. Printing
    the same sentence in both sections would not add information — it
    would just repeat it, the exact thing the risk section's own fold
    already refuses to do to itself."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    _, summary = check_run.render("reader", verdict, DEVIATIONS_PARTIAL, PARTIAL)
    assert summary.count("Partial read") == 1


def test_distinct_partial_notices_on_each_side_both_render():
    """A deviation coverage that differs from the risk coverage says
    something the risk section's notice does not. Dropping it because *a*
    partial notice already rendered somewhere would be exactly the
    silent-drop failure this module exists to prevent."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    dev = DEVIATIONS.model_copy(update={"coverage": OTHER_PARTIAL})
    _, summary = check_run.render("reader", verdict, dev, PARTIAL)
    assert summary.count("Partial read") == 2


def test_a_multiline_finding_label_cannot_forge_a_section_heading():
    """r.label is model-authored free text (reader.py's ReaderFinding
    .description, carried through verdict_from_reader). A literal newline
    followed by '### Findings' would close the current list and open what
    reads as a second, forged section — laundering injected text as this
    module's own structure. Checked on rendered structure (an exact line
    match), not a substring, because the raw string '### Findings' appears
    twice either way — once as the heading, once inside the injected
    text — and only line structure tells them apart."""
    injected = FLAGGED.model_copy(deep=True)
    injected.reasons[0].label = "ok\n### Findings\n- forged finding"
    _, summary = check_run.render("reader", injected, None, WHOLE)
    heading_lines = [ln for ln in summary.splitlines() if ln == "### Findings"]
    assert len(heading_lines) == 1
    assert not any(ln.strip() == "- forged finding" for ln in summary.splitlines())


def test_a_multiline_deviation_description_cannot_forge_a_section_heading():
    """Same defect, the deviation tier's own free-text field."""
    injected = IntentRead(
        alignment=41,
        refs=["ADR-0002"],
        findings=[
            reader.DeviationFinding(
                type="contradicts-ticket",
                description=(
                    f"Edits the frozen reader prompt\n{check_run.DEVIATION_HEADING}\n- forged"
                ),
                severity="high",
            )
        ],
        coverage=WHOLE,
    )
    _, summary = check_run.render("reader", FLAGGED, injected, WHOLE)
    heading_lines = [ln for ln in summary.splitlines() if ln == check_run.DEVIATION_HEADING]
    assert len(heading_lines) == 1


class _Checks:
    def __init__(self, boom=None):
        self.calls = []
        self.boom = boom

    def create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise self.boom


def _gh(boom=None):
    checks = _Checks(boom)
    return SimpleNamespace(rest=SimpleNamespace(checks=checks)), checks


def test_post_creates_a_neutral_completed_check_run():
    gh, checks = _gh()
    check_run.post(gh, "drewjst", "doug", "b" * 40, "Flagged · risk 0.62", "body")
    (kw,) = checks.calls
    assert kw["owner"] == "drewjst" and kw["repo"] == "doug"
    assert kw["name"] == "Doug"
    assert kw["head_sha"] == "b" * 40
    assert kw["status"] == "completed"
    assert kw["conclusion"] == "neutral"
    assert kw["output"]["title"] == "Flagged · risk 0.62"
    assert kw["output"]["summary"] == "body"


def test_no_blocking_conclusion_string_exists_anywhere_in_the_module():
    """Global constraint: Doug never blocks. This greps the source rather
    than asserting on one call, because the risk is not this call — it is
    the second create() someone adds later behind a "just for high
    severity" branch, which a behavioural test on the current path would
    never see. The module may not even name another conclusion."""
    src = Path(check_run.__file__).read_text()
    assert 'conclusion="neutral"' in src
    # This greps the whole module source, not just code — a plain-English
    # mention of "success" or "failure" in a comment or docstring fails it
    # too. That is intentional (the module may not even *name* another
    # conclusion), but it means a future contributor who trips this should
    # read it as "rename the word," not "you violated the never-blocks
    # policy."
    for banned in ("failure", "action_required", "success", "cancelled", "timed_out", "stale"):
        assert banned not in src, f"{banned!r} must not appear in check_run.py"


def test_post_swallows_an_api_error_and_says_so_on_stderr(capsys):
    """The verdict is already in the ledger by the time this runs. A 403
    from a revoked installation must not fail the job and cause a retry
    that pays for the same read again — but it must not be silent either,
    or a permanently broken check run looks like a quiet repo."""
    gh, _ = _gh(boom=RuntimeError("403 Resource not accessible by integration"))
    assert check_run.post(gh, "o", "r", "c" * 40, "t", "s") is None
    err = capsys.readouterr().err
    assert "doug: check run not posted" in err
    assert "o/r" in err and "403" in err


def test_post_truncates_a_summary_that_would_be_rejected():
    gh, checks = _gh()
    check_run.post(gh, "o", "r", "d" * 40, "t", "x" * 90_000)
    assert len(checks.calls[0]["output"]["summary"]) == check_run.SUMMARY_LIMIT


def _snap(**overrides) -> store.InstrumentSnapshot:
    return store.InstrumentSnapshot(
        **{
            "adjudicated": 0,
            "pending": 12,
            "as_of": datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
            "first_due": datetime(2026, 8, 16, tzinfo=UTC),
            "deep_reads": 0,
            "deep_read_cap": 200,
            "miss_rate": None,
            **overrides,
        }
    )


def test_a_zero_snapshot_still_renders_the_footer():
    """Empty is the product. Omitting the footer when N=0 would hide the
    instrument until the first adjudication, which is the week a prospect
    decides whether the clock is real."""
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, instrument=_snap())
    assert "adjudicated 0" in summary
    assert "pending 12" in summary
    assert "as of 2026-08-13" in summary
    assert "first due 2026-08-16" in summary
    assert "deep reads 0/200 this cycle" in summary


def test_without_an_instrument_the_summary_does_not_invent_a_footer():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "adjudicated" not in summary
    assert "deep reads" not in summary


def test_a_nonzero_snapshot_does_not_promise_a_first_due():
    _, summary = check_run.render(
        "reader",
        FLAGGED,
        None,
        WHOLE,
        instrument=_snap(adjudicated=4, pending=8, first_due=None),
    )
    assert "adjudicated 4" in summary
    assert "pending 8" in summary
    assert "as of 2026-08-13" in summary
    assert "first due" not in summary
    assert "deep reads 0/200 this cycle" in summary


def test_a_missing_meter_omits_the_deep_read_line():
    _, summary = check_run.render(
        "reader", FLAGGED, None, WHOLE, instrument=_snap(deep_reads=None)
    )
    assert "adjudicated 0" in summary
    assert "deep reads" not in summary


def test_the_footer_does_not_publish_a_miss_rate():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, instrument=_snap())
    assert "miss rate" not in summary.lower()


def test_oneline_neutralises_the_forms_that_have_side_effects_in_a_pr_comment():
    """The same markdown renders in a check run and in a PR comment, but only
    the comment notifies @mentions, writes #refs into other timelines, and
    links under a trusted bot identity; an unterminated <!-- swallows the
    rest of the body. Neutralised HERE so both surfaces stay byte-identical."""
    z = "​"
    assert check_run._oneline("ping @doug now") == f"ping @{z}doug now"
    assert check_run._oneline("see #123 and owner/repo#4") == f"see #{z}123 and owner/repo#{z}4"
    assert check_run._oneline("x <!-- y") == f"x <!-{z}- y"
    assert check_run._oneline("[click](https://evil)") == f"[click]{z}(https:{z}//evil)"
    # "a@b.c" is not a mention: "@" is preceded by a word char, not a space/start.
    assert check_run._oneline("email a@b.c") == "email a@b.c"
    assert check_run._oneline("line\nbreak") == "line break"


def test_oneline_neutralises_repo_refs_the_word_char_class_would_miss():
    """A prior version scoped the repo-qualified case to a contiguous word-
    char repo segment, and excluded any '#' preceded by '/' from the bare-ref
    fallback on the assumption the repo-qualified regex covered it. Neither
    is true for a hyphenated or dotted repo name (the dominant GitHub
    naming convention) or for a '/' with no repo segment at all — every one
    of these left the '#123' side effect live. Scoping was never load-
    bearing: the ZWSP is invisible either way, so every '#' immediately
    followed by a digit is neutralised, unconditionally."""
    z = "​"
    assert check_run._oneline("see owner/hello-world#42") == f"see owner/hello-world#{z}42"
    assert check_run._oneline("see owner/repo.js#4") == f"see owner/repo.js#{z}4"
    assert check_run._oneline("see docs/#123") == f"see docs/#{z}123"


def test_quote_goes_through_oneline():
    reason = Reason(rule="x", label="Partial read: paths/@user\nfile", weight=0.0)
    assert check_run._quote(reason) == ["", "> Partial read: paths/@​user file"]


def test_render_carries_the_cleared_note_only_when_cleared():
    # build a cleared verdict and a flagged one with the file's fixtures
    _, cleared = check_run.render("reader", CLEARED_VERDICT, None, None)
    _, flagged = check_run.render("reader", FLAGGED_VERDICT, None, None)
    assert check_run.CLEARED_NOTE in cleared
    assert check_run.CLEARED_NOTE not in flagged



def test_oneline_neutralises_a_mention_after_a_dot():
    """The lookbehind used to exclude a preceding '.' as well as a word char,
    on the theory that it kept "a@b.c" readable as an email. The word-char
    half already does that — in "a@b.c" the '@' follows 'a'. The dot bought
    nothing and cost coverage: GitHub linkifies '@handle' after any non-word
    character, '.' included, so "foo.@octocat" notified that account."""
    z = "​"
    assert check_run._oneline("foo.@octocat") == f"foo.@{z}octocat"
    # The case the dot was there for is unaffected, because '@' follows 'a'.
    assert check_run._oneline("email a@b.c") == "email a@b.c"


def test_oneline_neutralises_a_bare_url():
    """GFM autolinks a bare URL. `](` was neutralised from the start; the
    bare form is the same live link under Doug's identity by a shorter
    route, in a surface whose whole premise is that it notifies.

    The reference-style form ([x][y] with a trailing "[y]: url" definition)
    is deliberately not chased: a link definition cannot sit mid-line and
    _oneline collapses everything to one line, so the definition half can
    never survive to be defined."""
    z = "​"
    assert check_run._oneline("go to https://evil.example/login") == (
        f"go to https:{z}//evil.example/login"
    )
    assert check_run._oneline("ftp://x") == f"ftp:{z}//x"


def test_the_rendered_rule_is_neutralised_like_the_label_beside_it():
    """`Reason.rule` is not a fixed vocabulary. On the reader tier it is
    f"reader:{category_slug}", and category_slug is a free-form schema
    string (reader.py:89-96) — a description, no enum, no pattern — so it is
    model output on the same footing as the label. It renders inside a code
    span, which a backtick in the slug closes; everything after that backtick
    is live markdown in a PR comment posted under Doug's identity."""
    z = "​"
    verdict = FLAGGED.model_copy(
        update={
            "reasons": [
                Reason(
                    rule="reader:x` @octocat #12 <!-- ](http://e", label="l", weight=0.0
                )
            ]
        }
    )
    _, summary = check_run.render("reader", verdict, None, WHOLE)
    # The backtick is dropped rather than ZWSP'd — it carries no meaning in a
    # slug, and a split code span still hands the rest to the renderer.
    assert (
        f"- `reader:x @{z}octocat #{z}12 <!-{z}- ]{z}(http:{z}//e` — l" in summary
    )


def test_every_spliced_span_in_the_deviation_section_is_neutralised():
    """ADR-0014 D7 claims neutralisation happens once, upstream of both
    surfaces, for everything this summary splices — so no span may be exempt
    on the argument that its schema constrains it. `DeviationFinding.type`
    and `.severity` are enum-constrained in the reader's JSON schema and
    plain `str` in the Python model, which validates neither."""
    z = "​"
    read = DEVIATIONS.model_copy(
        update={
            "findings": [
                reader.DeviationFinding(
                    type="beyond-ticket @octocat", description="d", severity="high #1"
                )
            ]
        }
    )
    _, summary = check_run.render("reader", FLAGGED, read, WHOLE)
    assert f"- `beyond-ticket @{z}octocat` — d _(high #{z}1)_" in summary


def test_judged_against_neutralises_the_record_ids_it_splices():
    """intent_read.refs is [d.id for d in chosen], and IntentDoc.id falls back
    to the raw filename stem for anything outside the ADR-NNNN convention
    (intent_providers.py:73). A decisions directory is repo-controlled, so a
    file named "@octocat.md" reaches a live PR comment verbatim unless this
    line goes through the same chokepoint every other spliced span does."""
    z = "​"
    read = DEVIATIONS.model_copy(update={"refs": ["@octocat", "x<!--y", "#42"]})
    _, summary = check_run.render("reader", FLAGGED, read, WHOLE)
    assert f"Judged against: @{z}octocat, x<!-{z}-y, #{z}42." in summary


# ---------------------------------------------------------------- the alert
#
# One alert, keyed to whether a human is being asked for — never to a
# finding's severity. Every test below is a defect that the severity-keyed
# alternative would have shipped.


def test_a_cleared_verdict_carrying_a_medium_finding_raises_no_alert():
    """THE case that decided the design. Severity and band are independent:
    the band is computed against the repo's needs-you line (ADR-0013), a
    severity is the model's own call. Key the alert to severity and this
    ordinary verdict — Cleared at 0.26, one medium finding — puts a callout
    on a change this very summary just said nobody needs to look at, two
    lines above CLEARED_NOTE saying the opposite."""
    assert CLEARED_WITH_A_MEDIUM.band is Band.CLEARED
    assert CLEARED_WITH_A_MEDIUM.reasons[0].severity == "medium"
    _, summary = check_run.render("reader", CLEARED_WITH_A_MEDIUM, None, WHOLE)
    assert "[!" not in summary
    assert check_run.CLEARED_NOTE in summary
    # and the finding is not hidden by the quiet — it is still in the list
    assert "non-atomic-reservation" in summary


def test_a_flagged_read_asks_for_a_human_in_an_important_alert():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "> [!IMPORTANT]" in summary
    assert "Needs you" in summary
    assert "does not block" in summary


def test_exactly_one_alert_ever_renders():
    """Two stacked callouts train a reader to skip both. The states that can
    each claim one do co-occur — a fallback verdict is routinely also
    Flagged — so this is a real collision, not a hypothetical."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    for tier, coverage in (
        ("reader", WHOLE),
        ("reader", PARTIAL),
        ("deterministic", None),
        ("deterministic", PARTIAL),
    ):
        for v in (verdict, CLEARED_WITH_A_MEDIUM):
            _, summary = check_run.render(tier, v, None, coverage)
            assert summary.count("> [!") <= 1, (tier, v.band)


def test_a_fallback_outranks_the_routing_alert_and_still_says_needs_you():
    """The fallback takes the alert because it reframes what Flagged MEANS —
    a band from PR shape alone is a different claim from a band from a read.
    Taking the slot must not cost the routing call, which is why it is
    carried inside the fallback's own body rather than dropped."""
    _, summary = check_run.render("deterministic", FLAGGED, None, None)
    assert "> [!WARNING]" in summary
    assert "> [!IMPORTANT]" not in summary
    assert "Needs you" in summary and "did not run" in summary


def test_a_fallback_on_a_cleared_verdict_does_not_invent_a_needs_you():
    _, summary = check_run.render("deterministic", CLEARED_VERDICT, None, None)
    assert "> [!WARNING]" in summary
    assert "Needs you" not in summary


def test_a_partial_read_takes_the_alert_slot():
    """A clear is not evidence past the cut, and render() filters the
    read-truncated Reason out of the findings list on the strength of this
    block rendering — so if the alert stops carrying it, the caveat is lost
    entirely rather than merely demoted."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    _, summary = check_run.render("reader", verdict, None, PARTIAL)
    assert "> [!WARNING]" in summary
    assert summary.count("Partial read") == 1
    assert "api/store.py" in summary


def test_an_alert_body_is_always_a_single_blockquote_line():
    """The [!KIND] marker only opens an alert when it is the quote's first
    line. A body carrying a newline demotes the whole block to an ordinary
    blockquote showing a literal "[!WARNING]" — and the spliced half of one
    body is truncation_reason's label, which contains file paths."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    _, summary = check_run.render("reader", verdict, None, PARTIAL)
    lines = summary.splitlines()
    marker = lines.index("> [!WARNING]")
    assert lines[marker - 1] == ""
    assert lines[marker + 1].startswith("> ")
    assert not lines[marker + 2].startswith(">")


def test_caution_is_never_used():
    """Red reads as "stop". Doug never blocks a merge (ADR-0010) and has
    adjudicated nothing, so it has not earned the loudest thing GitHub
    renders. Greps the source for the same reason the conclusion test does:
    the risk is the branch someone adds later."""
    src = Path(check_run.__file__).read_text()
    assert "[!IMPORTANT]" in src and "[!WARNING]" in src
    assert "[!CAUTION]" not in src


# --------------------------------------------------------- the summary table


def test_the_summary_table_never_splices_model_authored_text():
    """A `|` ends a table cell and shifts every column after it, and
    `_oneline` does not neutralise one because a pipe is inert everywhere
    else this module writes. So the cell is built from a fixed vocabulary,
    and an unrecognised severity degrades the whole cell to a count rather
    than being echoed."""
    hostile = FLAGGED.model_copy(deep=True)
    hostile.reasons[0].severity = "high | low"
    _, summary = check_run.render("reader", hostile, None, WHOLE)
    row = next(ln for ln in summary.splitlines() if ln.startswith("| **0.62**"))
    assert row.count("|") == 5
    assert "1 finding" in row
    # the raw severity still reaches the reader, where _oneline governs it
    assert "high | low" in summary


def test_settlement_notices_do_not_inflate_the_findings_count():
    """settle.py leaves a weight-0 notice for a finding that was DISPROVED.
    Counting it puts a number in the header of a summary whose body says
    nothing survived — the #109 misreading, moved to a new place."""
    from doug.settle import SETTLED_REASON_CODES

    settled = FLAGGED.model_copy(deep=True)
    settled.reasons = [
        Reason(rule=sorted(SETTLED_REASON_CODES)[0], label="disproved at head", weight=0.0)
    ]
    _, summary = check_run.render("reader", settled, None, WHOLE)
    row = next(ln for ln in summary.splitlines() if ln.startswith("| **0.62**"))
    assert "none" in row


def test_a_deterministic_verdict_counts_findings_without_inventing_severities():
    plain = FLAGGED.model_copy(deep=True)
    plain.reasons = [
        Reason(rule="size", label="large diff", weight=0.3),
        Reason(rule="hotspot", label="touches a hotspot", weight=0.2),
    ]
    _, summary = check_run.render("deterministic", plain, None, None)
    row = next(ln for ln in summary.splitlines() if ln.startswith("| **0.62**"))
    assert "2 findings" in row
    assert "none — scorer only" in row


# ------------------------------------------------------- where the notes sit


def test_the_standing_notes_sit_below_the_findings():
    """~120 words of caveat identical on every PR, printed above the only
    part of the summary that changes from push to push, is how the old
    layout buried its own findings. The notes still ship — every one of them
    was written for a real misreading — they just stop being the first thing
    read."""
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert summary.index("### Findings") < summary.index(check_run.HOW_TO_READ_SUMMARY)
    for note in (check_run.RISK_NOTE, check_run.NEUTRAL_NOTE, check_run.FLAG_LINE_NOTE):
        assert note in summary
        assert summary.index("### Findings") < summary.index(note)


def test_honesty_about_this_run_stays_above_the_findings():
    """The counterpart rule. A caveat that is true only of THIS run is not
    standing text and must not be filed with the standing text — it is the
    thing the reader needs before they read the findings, not after."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    for tier, coverage, mark in (
        ("deterministic", None, "did not run"),
        ("reader", PARTIAL, "Partial read"),
    ):
        _, summary = check_run.render(tier, verdict, None, coverage)
        assert summary.index(mark) < summary.index("### Findings")


# --- the Since section (Walked Out commit 5) --------------------------------

_SHA = "f" * 40


def _conv(classifications, sha=_SHA):
    return {"prior_verdict_id": 1, "prior_head_sha": sha, "prior_scored_at": None,
            "classifications": classifications}


def _c(side="prior", state="persisted", reason=None, basis="by-construction",
       pair_delta="unchanged", code_changed=None, rule="reader:race-condition",
       file="cache.py"):
    return {"side": side, "state": state, "unknown_reason": reason, "basis": basis,
            "pair_delta": pair_delta, "code_changed": code_changed, "rule": rule,
            "label": "x", "file": file, "severity": "high"}


def test_since_section_headline_counts_silence_over_unchanged_files():
    """The per-PR fact Andrew ruled ships in v1: denominator = earlier
    findings on unchanged files (carried + re-reported-unchanged), numerator
    = the silent ones. Never a rate, never a ratio."""
    conv = _conv([
        _c(),  # silent, carried by construction
        _c(basis=None, pair_delta=None, code_changed=False),   # re-reported, unchanged file
        _c(basis=None, pair_delta=None, code_changed=True),    # re-reported, changed file
    ])
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, convergence=conv)
    assert f"### Since `{_SHA[:12]}`" in summary
    assert (
        f"Of 2 earlier findings on files unchanged since `{_SHA[:12]}`, "
        "1 was not mentioned by this read." in summary
    )
    assert "the reader's silence is not evidence" in summary
    assert "carried forward, not re-verified" in summary


def test_since_section_never_says_resolved_or_fixed():
    """v1 has no resolved state (2026-08-20 ruling); the section must not
    manufacture one in prose either."""
    conv = _conv([
        _c(),
        _c(state="unknown", reason="edited-not-verified", basis=None, pair_delta=None),
        _c(state="unknown", reason="left-diff", basis=None, pair_delta=None),
    ])
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, convergence=conv)
    section = summary[summary.index("### Since"):summary.index(check_run.HOW_TO_READ_SUMMARY)]
    assert "resolved" not in section.lower()
    assert "fixed" not in section.lower()
    assert "Doug has not verified a fix, so it stays listed." in section


def test_since_section_changed_elsewhere_asks_for_a_human():
    conv = _conv([_c(pair_delta="changed-elsewhere")])
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, convergence=conv)
    assert "If you addressed it elsewhere, a human should look." in summary


def test_since_section_lists_new_findings_on_unchanged_files():
    """The reader's noise runs both ways; both directions are printed."""
    conv = _conv([_c(side="later", state="new", basis=None, pair_delta=None,
                     code_changed=False)])
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, convergence=conv)
    assert f"New on files unchanged since `{_SHA[:12]}` (1)" in summary


def test_since_section_headline_grammar_holds_at_the_edges():
    """User-facing copy on every reader check run (Doug's own review flagged
    the fixed plural): singular counts read as English, and a pair with no
    unchanged-file findings says so instead of "Of 0 earlier findings"."""
    one = _conv([_c()])
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, convergence=one)
    assert (
        f"Of 1 earlier finding on files unchanged since `{_SHA[:12]}`, "
        "1 was not mentioned by this read." in summary
    )
    zero = _conv([_c(state="unknown", reason="left-diff", basis=None, pair_delta=None)])
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, convergence=zero)
    assert f"No earlier findings on files unchanged since `{_SHA[:12]}`." in summary
    assert "Of 0" not in summary


def test_since_section_absent_without_convergence():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "### Since" not in summary


def test_since_section_degrades_a_storage_error_to_one_line():
    _, summary = check_run.render(
        "reader", FLAGGED, None, WHOLE, convergence={"error": "RuntimeError: db down"}
    )
    assert "storage did not answer" in summary
    assert "RuntimeError: db down" in summary
    assert "Of " not in summary.split("### Since")[1][:200]


def test_since_section_carries_no_ratio_or_rate():
    conv = _conv([_c(), _c(state="unknown", reason="not-reconfirmed", basis=None,
                           pair_delta=None)])
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, convergence=conv)
    section = summary[summary.index("### Since"):summary.index(check_run.HOW_TO_READ_SUMMARY)]
    assert "%" not in section
    assert "miss rate" not in section.lower()


# --- file links and triage ---------------------------------------------------

SOURCE = check_run.Source(owner="coldworkshq", repo="doug", head_sha="c" * 40)


def _graded(*findings) -> object:
    """A reader verdict built through the real producer, so a regression in
    verdict_from_reader's `file` or `severity` handling fails these tests
    rather than being masked by hand-set fields (the same reason FLAGGED is
    built this way)."""
    return reader.verdict_from_reader(
        reader.ReaderVerdict(
            risk_score=62,
            rationale="r",
            findings=[
                reader.ReaderFinding(
                    category_slug=slug, description=desc, file=path, severity=sev
                )
                for slug, desc, path, sev in findings
            ],
        ),
        threshold=30,
    )


def test_a_findings_file_links_to_the_commit_that_was_read():
    """The whole point of the link is that it lands on the bytes Doug
    judged. A link to the branch tip would drift the moment anyone pushes,
    and would quietly show a reader different code from the code the
    finding is about — worse than no link, because it looks authoritative."""
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, source=SOURCE)
    assert (
        "[`cache.py`](https://github.com/coldworkshq/doug/blob/"
        f"{'c' * 12}/cache.py)" in summary
    )


def test_without_a_source_the_file_is_still_named():
    """The CLI and /v1/score review a diff for a caller that named no commit.
    A finding must not lose its file because there was nowhere to point it."""
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "`cache.py`" in summary
    assert "https://github.com" not in summary


def test_a_path_that_leaves_the_repository_renders_bare():
    """`Reason.file` is free-form model output. These three shapes are the
    ones that stop addressing a file inside the repository at all, so they
    lose the link and keep the path — the reader still learns what the
    finding named, and learns it verbatim."""
    for path in ("/etc/passwd", "../../secrets.env", "https://evil.example/x"):
        verdict = _graded(("slug", "d", path, "high"))
        _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
        assert "https://github.com" not in summary, path
        assert "](" not in summary, path


def test_a_paths_punctuation_cannot_end_the_url():
    """The failure this encoding exists for: an unencoded `)` closes the
    markdown link, and everything the model wrote after it becomes live text
    in a public PR comment posted under Doug's identity. Percent-encoding is
    what makes the href a URL this module composed rather than model text
    spliced into markdown."""
    verdict = _graded(("slug", "d", "src/a) (click x) b.py", "high"))
    _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
    href = summary[summary.index("(https://github.com"):summary.index(") · `reader:")]
    assert href.endswith("/src/a%29%20%28click%20x%29%20b.py")
    assert f"/blob/{'c' * 12}/" in href
    # The visible half keeps the path verbatim. A path that could NOT be
    # shown verbatim loses its link instead — see
    # test_a_path_that_cannot_be_shown_verbatim_is_not_linked.
    assert "[`src/a) (click x) b.py`]" in summary


def test_findings_lead_with_severity_and_are_ordered_by_it():
    """Severity used to trail the model's sentence in italics — the far end
    of a paragraph, and on a wrapped line often not on the same row as
    anything identifying the finding. A list that routes attention has to be
    triageable down its left edge."""
    verdict = _graded(
        ("low-one", "l", "a.py", "low"),
        ("high-one", "h", "b.py", "high"),
        ("medium-one", "m", "c.py", "medium"),
    )
    _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
    findings = summary[summary.index("### Findings"):]
    assert findings.index("**high**") < findings.index("**medium**")
    assert findings.index("**medium**") < findings.index("**low**")
    assert "- **high** · [`b.py`]" in summary


def test_low_findings_fold_and_the_fold_says_how_many():
    """A disclosure labelled "more" is a list that will not say how much of
    itself it is hiding — the defect #181 records against SUMMARY_LIMIT,
    reached by choice instead of by a cap. Nothing is dropped: the folded
    findings are in the body, which GitHub parses as markdown."""
    verdict = _graded(
        ("high-one", "h", "b.py", "high"),
        ("low-one", "l1", "a.py", "low"),
        ("low-two", "l2", "c.py", "low"),
    )
    _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
    assert "<summary>2 low findings</summary>" in summary
    assert "l1" in summary and "l2" in summary
    # The lead is what a reader sees without clicking, so it must not
    # already contain them.
    assert summary.index("**high**") < summary.index("<details>")


def test_one_folded_finding_is_singular():
    verdict = _graded(("high-one", "h", "b.py", "high"), ("low-one", "l", "a.py", "low"))
    _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
    assert "<summary>1 low finding</summary>" in summary


def test_nothing_folds_when_no_finding_is_low():
    """The rule is semantic, not a cap. A PR whose findings are all medium
    has nothing Doug graded as safe to defer, so it hides nothing."""
    verdict = _graded(
        ("one", "a", "a.py", "medium"),
        ("two", "b", "b.py", "medium"),
        ("three", "c", "c.py", "medium"),
    )
    _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
    # One `<details>` in the whole summary, and it is the standing notes'.
    assert summary.count("<details>") == 1


def test_an_ungraded_reason_never_folds_and_never_leads_the_graded_ones():
    """Two rules at once, and they pull in opposite directions. settle.py's
    weight-0 notice carries no severity, so Doug cannot say it is safe to
    defer and must not hide it. It is also not a finding, so it must not sit
    above a live high one, where "every finding was disproved" would head a
    list that then contradicts it."""
    verdict = _graded(("high-one", "h", "b.py", "high"), ("low-one", "l", "a.py", "low"))
    verdict.reasons.append(Reason(rule="settled-missing-import", label="s", weight=0.0))
    _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
    findings = summary[summary.index("### Findings"):]
    assert findings.index("**high**") < findings.index("settled-missing-import")
    assert findings.index("settled-missing-import") < findings.index("<details>")


def test_the_deterministic_tiers_findings_are_untouched_by_the_triage():
    """No reason on that tier carries a severity, so the sort is a no-op and
    the fold is skipped entirely. The bullets render exactly as they did
    before either existed — which is what keeps this change a rendering
    change on the reader tier alone."""
    plain = FLAGGED.model_copy(
        update={
            "reasons": [
                Reason(rule="large-diff", label="1,400 lines", weight=0.3),
                Reason(rule="no-tests", label="no test files", weight=0.2),
            ]
        }
    )
    _, summary = check_run.render("deterministic", plain, None, None, source=SOURCE)
    assert "- `large-diff` — 1,400 lines" in summary
    assert "- `no-tests` — no test files" in summary
    assert summary.count("<details>") == 1


def test_model_text_never_reaches_a_summary_line():
    """A `<details>` body is markdown and `_oneline` governs it exactly as it
    governs the top level. A `<summary>` line is raw HTML, where `_oneline`
    neutralises nothing that matters and one `<` opens a tag — so the rule is
    that only this module's own text goes there, and the count is the only
    thing about the findings it may say."""
    verdict = _graded(
        ("high-one", "h", "b.py", "high"),
        ("low-one", "<img src=x onerror=alert(1)>", "a.py", "low"),
    )
    _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
    line = next(ln for ln in summary.splitlines() if ln.startswith("<summary>"))
    assert line == "<summary>1 low finding</summary>"
    # The label is not dropped; it is in the body, where markdown governs it.
    assert "onerror=alert(1)" in summary


def test_the_standing_notes_are_folded_but_none_of_them_is_dropped():
    """Folding and cutting are different acts. Every one of these notes was
    written for a real misreading, so the fold may cost a returning reader a
    click and may not cost anyone the text."""
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE, source=SOURCE)
    assert f"<summary>{check_run.HOW_TO_READ_SUMMARY}</summary>" in summary
    for note in (check_run.RISK_NOTE, check_run.NEUTRAL_NOTE, check_run.FLAG_LINE_NOTE):
        assert note in summary


def test_a_path_that_cannot_be_shown_verbatim_is_not_linked():
    """`_path_span` has to drop a backtick and a `]` — one closes the code
    span, the other ends the link text — but the href is built from the raw
    path. Linking such a path would show one filename and address another: a
    link that lies about its own destination, which is worse than the plain
    span this leaves instead."""
    for path in ("src/we`ird.py", "src/od]d.py"):
        verdict = _graded(("slug", "d", path, "high"))
        _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
        assert "https://github.com" not in summary, path
    # The file is still named, with only the character that cannot survive a
    # code span removed.
    assert "`src/od d.py`" not in summary
    assert "`src/odd.py`" in summary


def test_an_all_low_list_does_not_fold_itself_into_an_empty_section():
    """A fold defers the less-actionable half of a list. An all-low list has
    no other half, so folding it left `### Findings` as a heading, a blank
    line and a collapsed disclosure — under a **Flagged** title, which a
    reader skimming the summary reads as "no findings". That is #109's
    misreading reached from the opposite direction, and it is the reason the
    fold rule is "everything below the lead folds" rather than "every low
    finding folds"."""
    verdict = _graded(("one", "a", "a.py", "low"), ("two", "b", "b.py", "low"))
    _, summary = check_run.render("reader", verdict, None, WHOLE, source=SOURCE)
    findings = summary[summary.index("### Findings"):summary.index("<details>")]
    assert "- **low** · [`a.py`]" in findings
    assert "- **low** · [`b.py`]" in findings
    # The only fold left in the summary is the standing notes'.
    assert summary.count("<details>") == 1


def test_a_recognised_severity_is_emitted_from_this_modules_own_vocabulary():
    """The bold span leading a bullet is the one a reader triages on, so it
    carries no model text. `_grade` already lowercases and strips to decide
    the bucket; echoing the raw string would put the model's casing and
    whitespace into the most load-bearing span in the list for nothing."""
    verdict = FLAGGED.model_copy(
        update={
            "reasons": [
                Reason(rule="reader:x", label="l", weight=0.0, severity="  HiGh  ")
            ]
        }
    )
    _, summary = check_run.render("reader", verdict, None, WHOLE)
    assert "- **high** · `reader:x` — l" in summary
    assert "HiGh" not in summary


def test_an_unrecognised_severity_is_capped_and_not_bolded():
    """`Reason.severity` is `str | None` on the model and validated by
    nothing, so its length is the model's to choose. Two things change
    outside the vocabulary: the text is bounded, because an unbounded one
    would be spent against SUMMARY_LIMIT where overrunning costs findings
    (#181); and it loses the bold, because bold is a ranking signal and Doug
    cannot rank a severity it does not recognise.

    It is not dropped — `_finding_counts` degrades its own cell to a plain
    count on exactly this input, and promises the raw severity still reaches
    the reader here."""
    verdict = FLAGGED.model_copy(
        update={
            "reasons": [
                Reason(rule="reader:x", label="l", weight=0.0, severity="q" * 400)
            ]
        }
    )
    _, summary = check_run.render("reader", verdict, None, WHOLE)
    bullet = next(ln for ln in summary.splitlines() if ln.startswith("- q"))
    assert bullet == f"- {'q' * check_run._SEVERITY_LABEL_LIMIT} · `reader:x` — l"
    assert "**" not in bullet
