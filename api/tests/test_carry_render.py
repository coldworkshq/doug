"""Rendering a carried finding (ADR-0036, doug#369).

A carried finding is collapsed under the author's word, so the rendering is
where a false carry would hide a defect. These tests pin that it never does:
a carried finding is always in the output, labeled as the author's claim; a
finding that repeats a ruling but did not carry renders fresh with a label;
and anything the check run cannot read renders fresh.
"""

import json
from types import SimpleNamespace

import pytest

from doug import check_run, pr_comment, reader, review, rulings, store, worker
from doug.models import Band, PRMetadata, Reason, Verdict

SHA = "cf64285" + "a" * 33


def _finding(label="Every append rescans the whole chain", severity="medium", carry=None):
    r = Reason(
        rule="reader:performance-regression",
        label=label,
        weight=0.0,
        severity=severity,
        file="journal.py",
    )
    r.carry = carry
    return r


def _decision(state=reader.CARRIED, **over):
    base = {
        "state": state,
        "read": SHA,
        "rule": "reader:quadratic-scaling",
        "verdict": "real",
        "changed": state == reader.RAISED_AGAIN,
        "reason": "the full-chain scan is what refuses to extend a corrupt journal",
        "ref": "coldworkshq/coldworks#106",
        "prompt_hash": reader.CARRY_PROMPT_HASH,
    }
    base.update(over)
    return base


def _render(*reasons):
    verdict = Verdict(score=0.41, band=Band.FLAGGED, threshold=0.3, reasons=list(reasons))
    _title, summary = check_run.render("reader", verdict, None, None)
    return summary


def _cell(summary: str) -> str:
    row = next(line for line in summary.splitlines() if line.startswith("| **"))
    return row.rstrip(" |").rsplit("| ", 1)[1]


# --- a carried finding -----------------------------------------------------------


def test_a_carried_finding_is_in_the_output_collapsed_and_labeled():
    """Never absent: the finding's own bullet is in the summary, inside a
    fold, with the author's ruling beneath it and the note that Doug did not
    verify it."""
    summary = _render(
        _finding(label="Two writers can interleave appends", severity="high"),
        _finding(carry=_decision()),
    )
    assert "Every append rescans the whole chain" in summary
    assert "<summary>1 finding the author already ruled on</summary>" in summary
    fold = summary.split("<summary>1 finding the author already ruled on</summary>", 1)[1]
    fold = fold.split("</details>", 1)[0]
    assert "Every append rescans the whole chain" in fold
    assert (
        f"  Settled on read `{SHA[:12]}` as **real**: the full-chain scan is what refuses to "
        "extend a corrupt journal (coldworkshq/coldworks#​106). "
        f"{check_run.CARRIED_NOTE}"
    ) in fold
    # The fresh finding stays outside the fold.
    assert "Two writers can interleave appends" not in fold


def test_carried_findings_are_counted_apart_and_never_as_none():
    """The count is the findings Doug stands behind, and then the ones the
    author settled. A read whose findings all carried is not `none`."""
    both = _render(_finding(severity="high"), _finding(carry=_decision()))
    assert _cell(both) == "1 high · 1 carried"
    only = _render(_finding(carry=_decision()), _finding(carry=_decision()))
    assert _cell(only) == "2 carried"
    assert "- none" not in only
    assert "<summary>2 findings the author already ruled on</summary>" in only


def test_a_carried_finding_is_not_read_as_nothing_surviving():
    """SETTLED_NOTE says every finding was disproved. With a carried finding
    beside the settled notices, one survived, collapsed, and the note would
    say otherwise."""
    settled = Reason(rule="settled-missing-import", label="settled", weight=0.0)
    summary = _render(settled, _finding(carry=_decision()))
    assert check_run.SETTLED_NOTE not in summary
    assert check_run.SETTLED_NOTE in _render(settled)


def test_the_sticky_comment_carries_the_same_section():
    """ADR-0014: the comment is the check run's summary, byte for byte."""
    summary = _render(_finding(carry=_decision()))
    body = pr_comment.render(summary, head_sha="b" * 40, seq=1, links=None)
    assert summary in body


# --- findings that render fresh --------------------------------------------------


def test_a_finding_the_author_marked_fixed_renders_fresh_and_says_so():
    """`changed: true` never carries. The finding leads the list like any
    live finding, counts as one, and says it came back after the fix."""
    summary = _render(_finding(carry=_decision(reader.RAISED_AGAIN)))
    assert _cell(summary) == "1 medium"
    assert "already ruled on" not in summary
    (line,) = [ln for ln in summary.splitlines() if "Every append rescans" in ln]
    assert line.startswith("- **medium**")
    assert f"_raised again after the author's fix at `{SHA[:12]}`_" in line
    # The author's reason did not settle a live finding, so it is not shown.
    assert "corrupt journal" not in summary


def test_a_changed_basis_renders_fresh_and_says_so():
    summary = _render(_finding(carry=_decision(reader.BASIS_CHANGED)))
    assert _cell(summary) == "1 medium"
    assert "already ruled on" not in summary
    assert f"the author ruled on this at `{SHA[:12]}`; the code it rested on has changed" in (
        summary
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"read": "cf64285"},
        {"read": "Z" * 40},
        {"verdict": "fixed"},
        {"reason": "   "},
        {"reason": 7},
        {"state": "resolved"},
    ],
)
def test_a_stored_decision_this_module_cannot_read_renders_fresh(bad):
    """Never hide a finding on a record that fails validation, and never
    label it with a ruling this module could not read."""
    summary = _render(_finding(carry=_decision(**bad)))
    assert _cell(summary) == "1 medium"
    assert "already ruled on" not in summary
    assert "Every append rescans the whole chain" in summary
    assert "the author ruled on this" not in summary
    assert "raised again" not in summary


def test_a_failed_pass_renders_every_finding_fresh(monkeypatch):
    """End to end: the carry pass stops on max_tokens, so no finding carries
    and the check run is the check run the read would have had without it."""
    diff = reader.diff_chunk("journal.py", "modified", 1, 1, "@@ -1,1 +1,1 @@\n-a\n+b\n")
    risk = {
        "risk_score": 41,
        "rationale": "r",
        "findings": [
            {
                "category_slug": "performance-regression",
                "description": "Every append rescans the whole chain",
                "file": "journal.py",
                "severity": "medium",
            }
        ],
    }

    def _create(**request):
        risky = request["system"] == reader.SYSTEM
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(risk if risky else {}))],
            stop_reason="end_turn" if risky else "max_tokens",
            usage=None,
        )

    client = SimpleNamespace(messages=SimpleNamespace(create=_create))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setattr(reader, "_client", lambda: client)
    monkeypatch.setattr(reader, "_verify_client", lambda: client)
    monkeypatch.setenv(reader.CARRY_ALLOWLIST_ENV, "99")
    ruling = rulings.Ruling(
        1, "cf64285", "reader:quadratic-scaling", "journal.py", "real", False, "x"
    )
    carry = rulings.Resolved((rulings.ResolvedRuling(ruling, SHA, "journal.py", ("y",)),), ())
    meta = PRMetadata.model_validate(
        {"number": 7, "title": "t", "author": "dev", "files": ["journal.py"]}
    )
    tier, verdict, _rv, cov = review.score_one(meta, diff, scope="installation:99", carry=carry)
    assert tier == "reader"
    assert all(r.carry is None for r in verdict.reasons)
    _title, summary = check_run.render(tier, verdict, None, cov)
    assert "already ruled on" not in summary
    assert "carried" not in _cell(summary)
    assert "Every append rescans the whole chain" in summary


# --- author text -----------------------------------------------------------------


def test_the_authors_reason_cannot_forge_structure_or_ping_anyone():
    """The reason is author text mirrored into a PR comment. It stays on its
    one line, and mentions, issue refs, tags, and links go inert."""
    hostile = "ok\n### Findings\n- **high** fake <details> @octocat #12 [x](https://evil.test)"
    summary = _render(_finding(carry=_decision(reason=hostile, ref="@octocat")))
    assert "\n### Findings\n- **high** fake" not in summary
    # The words survive, inert on the reason's own line; no line opens a heading.
    assert [ln for ln in summary.splitlines() if ln.startswith("###")] == ["### Findings"]
    assert summary.count("<details>") == 2  # the carried fold and "How to read this"
    assert "@octocat" not in summary
    assert "#12" not in summary
    assert "](https://" not in summary


# --- the skip notice -------------------------------------------------------------


def test_the_skip_notice_is_a_note_and_never_a_finding():
    notice = review.rulings_skipped_notice(
        (rulings.Skipped(2, "is not valid JSON (Expecting value)"), rulings.Skipped(None, "x"))
    )
    assert notice is not None
    summary = _render(_finding(), notice)
    assert _cell(summary) == "1 medium"
    assert "> Rulings Doug did not read — row 2: is not valid JSON (Expecting value); x" in summary
    assert not any(ln.startswith("- ") and "Rulings Doug" in ln for ln in summary.splitlines())
    only = _render(notice)
    assert _cell(only) == "none"


def test_the_skip_notice_names_a_bounded_number_of_rows():
    many = tuple(rulings.Skipped(n, "bad") for n in range(1, 21))
    notice = review.rulings_skipped_notice(many)
    assert notice is not None
    assert notice.label.count("bad") == review.MAX_SKIPS_NAMED
    assert notice.label.endswith(f"and {20 - review.MAX_SKIPS_NAMED} more")
    assert review.rulings_skipped_notice(()) is None


def _score_with(monkeypatch, carry, allow):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setenv(reader.CARRY_ALLOWLIST_ENV, allow)
    monkeypatch.setattr(
        reader,
        "read_diff",
        lambda meta, diff, *, scope, client=None: reader.ReaderVerdict(
            risk_score=10, rationale="r", findings=[]
        ),
    )
    meta = PRMetadata.model_validate({"number": 7, "title": "t", "author": "d", "files": []})
    _tier, verdict, _rv, _cov = review.score_one(meta, "", scope="installation:99", carry=carry)
    return [r.rule for r in verdict.reasons]


def test_the_notice_is_appended_only_where_the_pass_is_on(monkeypatch):
    """Off the allowlist the block is never read, so it must say nothing."""
    carry = rulings.Resolved((), (rulings.Skipped(1, "bad"),))
    assert rulings.SKIPPED_RULE in _score_with(monkeypatch, carry, "99")
    assert rulings.SKIPPED_RULE not in _score_with(monkeypatch, carry, "5")
    assert rulings.SKIPPED_RULE not in _score_with(monkeypatch, None, "99")


# --- the replay path -------------------------------------------------------------


def test_a_replayed_check_run_renders_the_stored_carry(tmp_path, monkeypatch):
    """The replay path renders from stored rows and never buys the pass
    again, so the decision must come back from the ledger intact."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    reasons = [_finding(severity="high", label="fresh one"), _finding(carry=_decision())]
    verdict = Verdict(score=0.41, band=Band.FLAGGED, threshold=0.3, reasons=reasons)
    vid = store.save_review(
        "o/r",
        7,
        "reader",
        verdict,
        github_repo_id=1,
        installation_id=99,
        head_sha="b" * 40,
        source="app",
    )
    assert vid is not None
    bundle = store.find_verdict_by_id(vid)
    assert bundle is not None
    job = {"id": 1, "installation_id": 99, "github_repo_id": 1}
    _t, replayed = worker._render_recorded(job, bundle)
    _t, live = check_run.render("reader", verdict, None, None, instrument=worker._instrument(job))
    section = "<summary>1 finding the author already ruled on</summary>"
    assert section in replayed
    assert (
        replayed.split("### Findings", 1)[1].split("<summary>How to read", 1)[0]
        == (live.split("### Findings", 1)[1].split("<summary>How to read", 1)[0])
    )


def test_the_decision_never_reaches_the_wire(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    verdict = Verdict(
        score=0.41, band=Band.FLAGGED, threshold=0.3, reasons=[_finding(carry=_decision())]
    )
    vid = store.save_review(
        "o/r", 7, "reader", verdict, github_repo_id=1, installation_id=99, head_sha="b" * 40
    )
    assert vid is not None
    bundle = store.find_verdict_by_id(vid)
    assert bundle is not None
    rebuilt = Reason(**bundle["reasons"][0])
    assert rebuilt.carry == _decision()
    assert "carry" not in rebuilt.model_dump()
