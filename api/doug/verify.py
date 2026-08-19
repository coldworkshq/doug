"""Run a verify check against head, or abstain.

The model names a location (reader.VerifyCheck); this module decides whether the
bytes there actually support the one predicate it is allowed to ask for. Pure —
`resolve_file` is injected, exactly as settle.py injects its resolvers, so the
whole of the outside world in a test is `lambda p: FILE`.

The rule this module exists to hold: **a byte-match is not a predicate.** Quoting
text that really is at a location proves only that the model did not invent the
file. `constant_value_is` claims something stronger — that the range *defines a
named constant* and that it *holds the value shown* — so the check parses the
range and confirms it is exactly one simple binding of a literal. Without that
step the predicate degenerates into "the quote matched", which is the failure
that killed the subtractive version of this gate: on PR #107 a true, byte-
matching, grep-re-derivable quote carried a false conclusion.

Every uncertainty abstains. settle.py:239 already wrote the reason — "we cannot
tell which mention is the real claim, so we settle neither rather than guess" —
and here the stakes point the same way: abstaining leaves the finding published
and ungrounded, while guessing publishes a hash next to a claim it does not
support. Only Python constants are supported today; every other language
abstains rather than pattern-matching its way to a confident wrong answer.
"""

import ast

from .reader import Citation, VerifyCheck, cite


class CheckOutcome:
    """Either a citation, or the reason there isn't one. Never an exception."""

    __slots__ = ("citation", "abstained_because")

    def __init__(self, citation: Citation | None = None, abstained_because: str | None = None):
        self.citation = citation
        self.abstained_because = abstained_because

    @property
    def grounded(self) -> bool:
        return self.citation is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        if self.citation is not None:
            return f"CheckOutcome(grounded={self.citation.locator()})"
        return f"CheckOutcome(abstained={self.abstained_because!r})"


def _abstain(reason: str) -> CheckOutcome:
    return CheckOutcome(abstained_because=reason)


def _is_single_constant_binding(text: str, line_start: int, line_end: int) -> bool:
    """True only when the range is exactly one binding of a literal to a name.

    "Exactly" is doing the work. A range covering two statements, or half of one,
    or a binding whose value is a call or a name, is not a constant definition —
    it is a region the model gestured at. Those abstain, because a claim about a
    region is the shape D3 rules out: it shows one place out of a complement
    nobody enumerated.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False

    spanning = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and getattr(node, "lineno", None) == line_start
        and getattr(node, "end_lineno", None) == line_end
    ]
    if len(spanning) != 1:
        return False

    node = spanning[0]
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return False
    elif not isinstance(node.target, ast.Name):
        return False

    return isinstance(node.value, ast.Constant)


def run_check(check: VerifyCheck, *, head_sha: str, resolve_file) -> CheckOutcome:
    """Ground `check` against head, or abstain with a reason.

    resolve_file(path) -> str | None, the same contract review.head_file_text
    already satisfies: None means "GitHub would not give us text", which must
    never read as "the claim is settled".
    """
    text = resolve_file(check.file)
    if text is None:
        return _abstain("file unavailable at head")

    citation = cite(
        path=check.file,
        head_sha=head_sha,
        text=text,
        line_start=check.line_start,
        line_end=check.line_end,
    )
    if citation is None:
        return _abstain("line range does not exist in the file at head")

    lines = text.splitlines(keepends=True)
    actual = "".join(lines[check.line_start - 1 : check.line_end])
    if actual.strip() != check.quoted_text.strip():
        return _abstain("quoted text does not match the bytes at head")

    if not check.file.endswith(".py"):
        return _abstain("only python constant definitions are supported")

    if not _is_single_constant_binding(text, check.line_start, check.line_end):
        return _abstain("range is not exactly one constant definition")

    return CheckOutcome(citation=citation)
