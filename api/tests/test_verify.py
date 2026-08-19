"""The verify predicate runner: ground a finding, or abstain with a reason.

Every test here is about the same boundary — what a citation is allowed to
establish. The runner may never raise and may never remove a finding; the only
two outcomes are "grounded" and "still published, still ungrounded".
"""

import pytest
from pydantic import ValidationError

from doug import verify
from doug.reader import VerifyCheck

FILE = (
    "import os\n"                 # 1
    "\n"                          # 2
    "CAP = 4000\n"                # 3
    "LIMIT = CAP\n"               # 4
    "NAME = os.getenv('n')\n"     # 5
    "\n"                          # 6
    "def f():\n"                  # 7
    "    return CAP\n"            # 8
)


def _check(**kw):
    return VerifyCheck(**{"file": "api/doug/reader.py", "predicate": "constant_value_is", **kw})


def _run(check, text=FILE):
    return verify.run_check(check, head_sha="a" * 40, resolve_file=lambda p: text)


def test_a_constant_definition_grounds_the_finding():
    """The shape this whole increment exists for.

    PR #106's second-most-valuable finding was a meter rendering against a cap of
    200 while spend was enforced at 4000 — invisible without reading a file that
    was not in the PR. This is that read, and the citation is what lets a reader
    check it without trusting Doug.
    """
    out = _run(_check(line_start=3, line_end=3, quoted_text="CAP = 4000"))
    assert out.grounded
    assert out.citation.locator() == f"api/doug/reader.py@{'a' * 40}#L3-L3"
    assert out.abstained_because is None


def test_a_byte_match_alone_does_not_ground_a_finding():
    """The test that separates a predicate from a citation gate.

    `LIMIT = CAP` is really at line 4, and quoting it byte-matches perfectly. A
    gate that honored byte-matches would ground on it. But the predicate claims
    the range binds a *literal value*, and this binds another name — so what the
    quote proves and what the predicate claims come apart, which is exactly how
    PR #107's refutation was true and wrong at the same time.

    If this ever passes, `constant_value_is` has silently become "the quote
    matched" and the design's central distinction is gone.
    """
    out = _run(_check(line_start=4, line_end=4, quoted_text="LIMIT = CAP"))
    assert not out.grounded
    assert "not exactly one constant definition" in out.abstained_because

    out = _run(_check(line_start=5, line_end=5, quoted_text="NAME = os.getenv('n')"))
    assert not out.grounded


def test_a_fabricated_quote_leaves_the_finding_ungrounded():
    """A hallucinated value must be a no-op, not a wrong receipt."""
    out = _run(_check(line_start=3, line_end=3, quoted_text="CAP = 200"))
    assert not out.grounded
    assert "does not match" in out.abstained_because


def test_an_off_by_one_range_leaves_the_finding_ungrounded():
    """Right file, right constant, wrong line. The receipt must not survive it."""
    out = _run(_check(line_start=4, line_end=4, quoted_text="CAP = 4000"))
    assert not out.grounded
    out = _run(_check(line_start=3, line_end=99, quoted_text="CAP = 4000"))
    assert not out.grounded
    assert "does not exist" in out.abstained_because


def test_an_unavailable_file_never_reads_as_settled():
    """None means "GitHub would not give us text", never "the claim holds".

    review.head_file_text returns None for missing, binary and unreadable files,
    and settle.py's docstring is explicit that this must not invent a settlement.
    The additive direction inherits the rule unchanged.
    """
    out = verify.run_check(
        _check(line_start=3, line_end=3, quoted_text="CAP = 4000"),
        head_sha="a" * 40,
        resolve_file=lambda p: None,
    )
    assert not out.grounded
    assert "unavailable" in out.abstained_because


def test_a_range_spanning_two_statements_abstains():
    """A claim about a region is not a claim about a value.

    This is how a universality claim ("this is the only cap") would try to reach
    the runner disguised as a constant check — by gesturing at an area rather
    than a binding. D3 rules that out: a citation shows one place out of a
    complement nobody enumerated, so a multi-statement range grounds nothing.
    """
    out = _run(_check(line_start=3, line_end=4, quoted_text="CAP = 4000\nLIMIT = CAP"))
    assert not out.grounded
    assert "not exactly one constant definition" in out.abstained_because


def test_a_non_python_file_abstains_rather_than_pattern_matching():
    """Doug's tenants are not all Python, and a regex that "mostly works" on Go
    or TypeScript is how a confident wrong answer ships. Unsupported abstains."""
    out = _run(
        VerifyCheck(
            file="web/lib/api.ts",
            predicate="constant_value_is",
            line_start=3,
            line_end=3,
            quoted_text="CAP = 4000",
        )
    )
    assert not out.grounded
    assert "only python" in out.abstained_because


def test_a_file_that_does_not_parse_abstains():
    """Head can be mid-refactor or truncated; that is not evidence of anything."""
    out = _run(_check(line_start=1, line_end=1, quoted_text="def ("), text="def (\n")
    assert not out.grounded


def test_run_check_never_raises():
    """The safety property, stated as a property.

    The model picks where to look. A bad pick has to leave the finding published
    and ungrounded — never fail the review. Anything that raises here converts a
    hallucinated line number into an outage.
    """
    hostile = [
        _check(line_start=1, line_end=1, quoted_text=""),
        _check(line_start=8, line_end=8, quoted_text="    return CAP"),
        _check(line_start=1, line_end=8, quoted_text=FILE),
    ]
    for check in hostile:
        for text in (FILE, "", "\n\n\n", "\x00binary"):
            out = verify.run_check(check, head_sha="a" * 40, resolve_file=lambda p, _t=text: _t)
            assert out.grounded or out.abstained_because


def test_the_runner_cannot_be_handed_an_unsupported_predicate():
    """Abstention is not the only guard — the vocabulary is closed at the type
    level, so a predicate the runner has no code for cannot be constructed."""
    with pytest.raises(ValidationError):
        _check(line_start=3, line_end=3, quoted_text="CAP = 4000", predicate="path_does_not_exist")
