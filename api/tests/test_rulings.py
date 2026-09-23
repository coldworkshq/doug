"""The author's rulings block (ADR-0036, doug#369).

The block is untrusted author text that later reaches a model prompt, and a
ruling can collapse a finding on the check run. Every test here pins one way
the parser or the resolver refuses to guess, because a guessed ruling is a
finding hidden under a claim nobody made.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from doug import findings_log, review, rulings, store
from doug.models import Band, Reason, Verdict

SHA_A = "cf64285" + "a" * 33
SHA_B = "d61dc59" + "b" * 33
SHA_HEAD = "7f51299" + "c" * 33

JOURNAL = "packages/coldworks-local/src/coldworks_local/journal.py"


def _row(**over) -> str:
    base = {
        "read": "cf64285",
        "rule": "reader:quadratic-scaling",
        "file": JOURNAL,
        "verdict": "real",
        "changed": False,
        "ref": "coldworkshq/coldworks#106",
        "reason": "the full-chain scan is what refuses to extend a corrupt journal",
    }
    base.update(over)
    return json.dumps({k: v for k, v in base.items() if v is not ...})


def _desc(*rows: str, before: str = "Some PR text.\n\n", after: str = "\n\nMore text.") -> str:
    return before + "```doug-rulings\n" + "\n".join(rows) + "\n```" + after


# --- parse -------------------------------------------------------------------


def test_the_block_in_doug_369_parses_row_for_row():
    """The issue's own example is the contract authors copy. If it stopped
    parsing, every author following the spec would carry nothing and nobody
    would be told why."""
    desc = (
        "```doug-rulings\n"
        '{"read": "cf64285", "rule": "reader:quadratic-scaling", "file": '
        '"packages/coldworks-local/src/coldworks_local/journal.py", "verdict": "real", '
        '"changed": false, "ref": "coldworkshq/coldworks#106", "reason": "the full-chain '
        'scan is what refuses to extend a corrupt journal"}\n'
        '{"read": "cf64285", "rule": "reader:platform-portability", "file": '
        '"packages/coldworks-local/src/coldworks_local/journal.py", "verdict": "real", '
        '"changed": true, "reason": "scope declared in the package docstring"}\n'
        "```\n"
    )
    block = rulings.parse(desc)
    assert block is not None
    assert block.skipped == ()
    first, second = block.rulings
    assert first == rulings.Ruling(
        row=1,
        read="cf64285",
        rule="reader:quadratic-scaling",
        file=JOURNAL,
        verdict="real",
        changed=False,
        reason="the full-chain scan is what refuses to extend a corrupt journal",
        ref="coldworkshq/coldworks#106",
    )
    assert (second.rule, second.changed, second.ref) == ("reader:platform-portability", True, None)


@pytest.mark.parametrize(
    "description",
    [None, "", "No block here.", "```python\nprint('x')\n```", "```doug-rules\n{}\n```"],
)
def test_no_block_is_none_so_the_pass_does_not_run(description):
    """None is the one answer that means "do not call the model". A Block,
    even an empty one, would buy a paid pass on every PR with a description."""
    assert rulings.parse(description) is None


def test_a_malformed_row_is_skipped_and_named_and_its_neighbours_survive():
    """One bad row must not cost the good ones, and must not be repaired:
    the author gets told which row and why, by its line in the block."""
    desc = _desc(
        _row(),
        "not json at all",
        _row(verdict="fixed"),
        "",
        _row(read="CF64285"),
        _row(rule="quadratic-scaling"),
        _row(reason=...),
        _row(extra="x"),
        '["a", "list"]',
        _row(changed="false"),
        _row(reason="x" * (rulings.MAX_REASON_CHARS + 1)),
        _row(ref=""),
        _row(file="  "),
        _row(rule="reader:platform-portability"),
    )
    block = rulings.parse(desc)
    assert block is not None
    assert [r.row for r in block.rulings] == [1, 14]
    skipped = {s.row: s.reason for s in block.skipped}
    assert list(skipped) == [2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13]
    assert skipped[2].startswith("is not valid JSON")
    assert skipped[3] == "verdict must be one of adjacent, disproved, real"
    assert "lowercase hex" in skipped[5]
    assert "kebab-case" in skipped[6]
    assert skipped[7] == "is missing reason"
    assert skipped[8] == "has unknown keys extra"
    assert skipped[9] == "is not a JSON object"
    assert skipped[10] == "changed must be true or false"
    assert "longer than" in skipped[11]
    assert skipped[12] == "ref must be a non-empty string"
    assert "file must be" in skipped[13]


def test_two_blocks_read_as_no_rulings_and_say_so():
    """Merging two lists or picking one guesses which the author meant. No
    ruling carries, which renders every finding fresh: the safe direction."""
    desc = _desc(_row()) + "\n\n" + _desc(_row(rule="reader:symlink-handling"))
    block = rulings.parse(desc)
    assert block is not None
    assert block.rulings == ()
    (skip,) = block.skipped
    assert skip.row is None
    assert "2 doug-rulings blocks" in skip.reason


def test_an_unclosed_block_yields_no_rows():
    """An unclosed fence runs to the end of the description. Reading its
    lines as rows would treat prose the author wrote after it as rulings."""
    block = rulings.parse("Text\n```doug-rulings\n" + _row() + "\nand then prose\n")
    assert block is not None
    assert block.rulings == ()
    assert block.skipped == (rulings.Skipped(None, "the doug-rulings block is never closed"),)


@pytest.mark.parametrize(
    "inner",
    [
        "```doug-rulings\n{row}\n```",
        # A plain three-backtick fence inside the example closes nothing but
        # itself: a fence closes only on a run at least as long as its opener.
        "```python\nx = 1\n```\n```doug-rulings\n{row}\n```",
    ],
)
def test_a_block_shown_as_an_example_inside_a_longer_fence_is_not_a_block(inner):
    """doug#369 itself shows the block inside a four-backtick fence. A
    description that quotes the spec must not rule on anything."""
    desc = "Example:\n\n````\n" + inner.format(row=_row()) + "\n````\n"
    assert rulings.parse(desc) is None


def test_a_real_block_after_an_example_is_still_read():
    """The example fence closes on its own length, so a real block after it
    is the only block."""
    desc = "````\n```doug-rulings\n" + _row() + "\n```\n````\n\n" + _desc(_row())
    block = rulings.parse(desc)
    assert block is not None
    assert len(block.rulings) == 1


def test_rows_past_the_cap_are_not_read_and_the_cap_is_named():
    desc = _desc(*[_row() for _ in range(rulings.MAX_ROWS + 5)])
    block = rulings.parse(desc)
    assert block is not None
    assert len(block.rulings) == rulings.MAX_ROWS
    (skip,) = block.skipped
    assert skip.row == rulings.MAX_ROWS + 1
    assert str(rulings.MAX_ROWS) in skip.reason


def test_crlf_descriptions_parse_like_lf():
    """GitHub stores descriptions typed in its web editor with CRLF."""
    desc = _desc(_row()).replace("\n", "\r\n")
    block = rulings.parse(desc)
    assert block is not None
    assert len(block.rulings) == 1


@pytest.mark.parametrize(
    "rule",
    ["reader:quadratic-scaling", "reader:Quadratic", "quadratic", "reader:a_b", "x:y", ":y"],
)
def test_a_ruling_rule_is_valid_exactly_when_the_findings_log_accepts_it(rule):
    """A ruling moves into docs/findings-log.jsonl by transcription. A rule
    the log would refuse is refused here too, so no ruling carries under a
    rule that can never be logged."""
    log_row = {
        "date": "2026-09-23",
        "pr": 1,
        "layer": "doug",
        "rule": rule,
        "verdict": "real",
        "changed": False,
        "settled_by": "x",
        "source": "prospective",
    }
    try:
        findings_log.parse_row(log_row)
        log_ok = True
    except findings_log.FindingsLogError:
        log_ok = False
    block = rulings.parse(_desc(_row(rule=rule)))
    assert block is not None
    assert (len(block.rulings) == 1) is log_ok


# --- resolve -----------------------------------------------------------------


def _prior(rule="reader:quadratic-scaling", file=JOURNAL, label="Appending rescans the chain"):
    return rulings.PriorFinding(rule=rule, file=file, label=label)


def test_a_ruling_resolves_to_the_read_and_the_finding_doug_stored():
    """The resolved ruling carries Doug's own words for what it raised, so
    the pass compares Doug's text with Doug's text, not with the author's."""
    block = rulings.parse(_desc(_row()))
    assert block is not None
    out = rulings.resolve(block, {SHA_A: [_prior()], SHA_B: []})
    (r,) = out.rulings
    assert r.head_sha == SHA_A
    assert r.raised == ("Appending rescans the chain",)
    assert out.skipped == ()


def test_a_read_that_names_no_read_of_this_pr_is_skipped():
    """doug#369's fourth parser case. A sha from another PR, a typo, or the
    read being made right now is not a read this PR stored."""
    block = rulings.parse(_desc(_row(read="deadbee")))
    assert block is not None
    out = rulings.resolve(block, {SHA_A: [_prior()]})
    assert out.rulings == ()
    (skip,) = out.skipped
    assert skip.row == 1
    assert skip.reason == "read deadbee names no earlier read of this PR"


def test_an_ambiguous_prefix_is_skipped_not_picked():
    block = rulings.parse(_desc(_row(read="cf64285")))
    assert block is not None
    twin = "cf64285" + "f" * 33
    out = rulings.resolve(block, {SHA_A: [_prior()], twin: [_prior()]})
    assert out.rulings == ()
    assert "matches 2 reads" in out.skipped[0].reason


def test_a_ruling_on_a_finding_the_read_never_stored_is_skipped():
    """An author can only rule on what Doug raised. Without this, one row
    could name a rule and file Doug never flagged and collapse whatever the
    next read finds there."""
    block = rulings.parse(
        _desc(
            _row(rule="reader:sql-injection"),
            _row(file="other.py"),
            _row(),
        )
    )
    assert block is not None
    out = rulings.resolve(block, {SHA_A: [_prior()]})
    assert [r.ruling.row for r in out.rulings] == [3]
    reasons = {s.row: s.reason for s in out.skipped}
    assert reasons[1] == f"read {SHA_A[:12]} stored no reader:sql-injection finding on {JOURNAL}"
    assert reasons[2] == f"read {SHA_A[:12]} stored no reader:quadratic-scaling finding on other.py"


def test_only_reader_findings_carry():
    """The carry pass reads the risk read's findings only. A ruling on an
    intent deviation or a settlement notice has nothing to carry."""
    block = rulings.parse(_desc(_row(rule="intent:deviation")))
    assert block is not None
    out = rulings.resolve(block, {SHA_A: [_prior(rule="intent:deviation")]})
    assert out.rulings == ()
    assert "only reader: findings carry" in out.skipped[0].reason


def test_the_stored_slug_folds_its_spelling_but_not_its_word():
    """The stored slug is free-form model output and the ruled one was
    kebab-cased by hand, so `Quadratic Scaling` is `quadratic-scaling`. A
    different word is a different finding: merging names is a judgment the
    pass makes, not a lookup."""
    block = rulings.parse(_desc(_row()))
    assert block is not None
    spelled = rulings.resolve(block, {SHA_A: [_prior(rule="reader:Quadratic Scaling")]})
    assert len(spelled.rulings) == 1
    renamed = rulings.resolve(block, {SHA_A: [_prior(rule="reader:performance-regression")]})
    assert renamed.rulings == ()


def test_the_file_matches_across_a_path_prefix_but_not_a_name_suffix():
    block = rulings.parse(_desc(_row(file="coldworks_local/journal.py")))
    assert block is not None
    assert len(rulings.resolve(block, {SHA_A: [_prior()]}).rulings) == 1
    block = rulings.parse(_desc(_row(file="al.py")))
    assert block is not None
    assert rulings.resolve(block, {SHA_A: [_prior(file="journal.py")]}).rulings == ()


def test_parse_skips_come_through_resolve_first():
    block = rulings.parse(_desc("nope", _row(read="deadbee")))
    assert block is not None
    out = rulings.resolve(block, {SHA_A: []})
    assert [s.row for s in out.skipped] == [1, 2]


# --- the stored reads ------------------------------------------------------


def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")


def _save(sha, *, tier="reader", reasons=None, pr=7, installation=99, repo_id=1):
    return store.save_review(
        "o/r",
        pr,
        tier,
        Verdict(score=0.2, band=Band.CLEARED, threshold=0.3, reasons=reasons or []),
        github_repo_id=repo_id,
        installation_id=installation,
        head_sha=sha,
        source="app",
    )


def _finding(rule="reader:quadratic-scaling", file=JOURNAL, label="Appending rescans the chain"):
    return Reason(rule=rule, label=label, weight=0.0, severity="medium", file=file)


def test_a_read_is_checked_against_the_prs_stored_verdict_shas(tmp_path, monkeypatch):
    """The fourth case end to end: rulings resolve against what the ledger
    holds for THIS PR, so a read of another PR, another repository, another
    installation, a deterministic read, or the read being made names nothing."""
    _db(tmp_path, monkeypatch)
    _save(SHA_A, reasons=[_finding()])
    _save(SHA_B, reasons=[])
    other_pr = "a1ced4a" + "d" * 33
    _save(other_pr, pr=8, reasons=[_finding()])
    _save("df10f0e" + "e" * 33, tier="deterministic", reasons=[_finding()])
    _save("0badc0d" + "0" * 33, installation=100, reasons=[_finding()])
    _save("1badc0d" + "0" * 33, repo_id=2, reasons=[_finding()])
    _save(SHA_HEAD, reasons=[_finding()])

    reads = store.prior_reader_findings(99, 1, 7, current_head_sha=SHA_HEAD)
    assert reads is not None
    assert set(reads) == {SHA_A, SHA_B}
    assert reads[SHA_A] == [_prior()]
    assert reads[SHA_B] == []

    block = rulings.parse(
        _desc(
            _row(),
            _row(read="a1ced4a"),
            _row(read="df10f0e"),
            _row(read="0badc0d"),
            _row(read="1badc0d"),
            _row(read="7f51299"),
        )
    )
    assert block is not None
    out = rulings.resolve(block, reads)
    assert [r.ruling.row for r in out.rulings] == [1]
    assert [s.row for s in out.skipped] == [2, 3, 4, 5, 6]
    assert all("names no earlier read of this PR" in s.reason for s in out.skipped)


def test_prior_reader_findings_is_none_without_a_ledger(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.prior_reader_findings(99, 1, 7, current_head_sha=SHA_HEAD) is None


# --- the description stays off PRMetadata ----------------------------------


def test_the_description_is_read_on_its_own_and_never_reaches_pr_meta():
    """`pr_meta` is stored at every tier. The description is author text
    that reaches a prompt, and it has no business in that row."""
    desc = _desc(_row())
    p = SimpleNamespace(
        number=7,
        title="Add cache",
        body=desc,
        user=SimpleNamespace(login="dev", type="User"),
        head=SimpleNamespace(sha=SHA_HEAD),
        html_url="https://github.com/o/r/pull/7",
        changed_files=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    f = SimpleNamespace(
        filename="cache.py", status="modified", additions=1, deletions=0, patch="+x"
    )
    gh = SimpleNamespace(
        rest=SimpleNamespace(
            pulls=SimpleNamespace(
                get=lambda **kw: SimpleNamespace(parsed_data=p),
                list_files=lambda **kw: SimpleNamespace(parsed_data=[f]),
                list_reviews=lambda **kw: SimpleNamespace(parsed_data=[]),
            )
        )
    )
    meta, _diff = review.fetch_pr(gh, "o", "r", 7)
    assert "doug-rulings" not in json.dumps(meta.model_dump(mode="json"))
    assert review.pr_description(p) == desc


@pytest.mark.parametrize("body", [None, 7, object()])
def test_a_description_that_is_not_a_string_is_no_description(body):
    assert review.pr_description(SimpleNamespace(body=body)) is None
    assert review.pr_description(SimpleNamespace()) is None
