"""The author's rulings, read from a PR description (ADR-0036, doug#369).

The author keeps one fenced `doug-rulings` block in the PR description. Each
line is one JSON object whose fields match a findings-log row, naming a finding
Doug raised on an earlier read of the same PR and what the author ruled.

Two properties are load-bearing.

**It is pure.** A function of the text and rows it is handed: no store, no
network, no clock. The worker fetches the description and the PR's stored
reads; this module only reads them.

**It never guesses.** Author text is untrusted input to a later prompt, so
anything this module cannot read exactly is skipped and named, never repaired:

- A malformed row is skipped, and the skip carries its row number and reason.
- More than one block means no block. The author maintains one list, and
  both merging two lists and picking one of them are guesses about which the
  author meant. Reading none renders every finding fresh, which is the safe
  direction.
- A block that is never closed yields no rows.
- No block at all is `None`, and the carry pass does not run.

`resolve` then anchors each row to a finding Doug actually stored: its `read`
must be a prefix of exactly one stored head sha of this PR, and that read must
have stored a `reader:` finding with the same rule on the same file. A ruling
the store cannot anchor is skipped, so an author cannot rule on a finding Doug
never raised.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from .findings_log import VERDICTS, valid_rule
from .patterns import RULE_PREFIX, slugify

Verdict = Literal["real", "disproved", "adjacent"]

BLOCK_INFO = "doug-rulings"
# The weight-0 notice that says which rows, or which block, Doug did not read.
# A notice, never a finding: the check run counts it nowhere, and convergence
# excludes it because it is not a `reader:` rule.
SKIPPED_RULE = "rulings-skipped"
# Bounds on untrusted text. Each ruling can reach a model prompt and the check
# run, so a row that exceeds a bound is skipped rather than truncated: a cut
# reason is a reason the author did not write.
MAX_ROWS = 64
MAX_REASON_CHARS = 600
MAX_FILE_CHARS = 400
MAX_REF_CHARS = 200

_REQUIRED = frozenset({"read", "rule", "file", "verdict", "changed", "reason"})
_OPTIONAL = frozenset({"ref"})
# A head sha as Doug's comment names it: 7 to 40 lowercase hex characters.
# Lowercase only, because a stored sha is lowercase and a prefix match is
# case-sensitive; an uppercase spelling would silently match nothing.
_READ_RE = re.compile(r"^[0-9a-f]{7,40}$")
# A CommonMark fence opener: up to three spaces, then three or more backticks
# or tildes, then an info string. A backtick fence's info string cannot hold a
# backtick.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


@dataclass(frozen=True)
class Ruling:
    """One row of the block, as the author wrote it. `row` is 1-based within
    the block, counting blank lines, so it matches what the author sees."""

    row: int
    read: str
    rule: str
    file: str
    verdict: Verdict
    changed: bool
    reason: str
    ref: str | None = None


@dataclass(frozen=True)
class Skipped:
    """A row, or the whole block, that was not read, and why. `row` is None
    for a block-level skip."""

    row: int | None
    reason: str


@dataclass(frozen=True)
class Block:
    rulings: tuple[Ruling, ...]
    skipped: tuple[Skipped, ...]


@dataclass(frozen=True)
class PriorFinding:
    """One finding row Doug stored on an earlier read of this PR."""

    rule: str
    file: str | None
    label: str


@dataclass(frozen=True)
class ResolvedRuling:
    """A ruling anchored to what Doug stored. `head_sha` is the full sha of
    the ruled read, `file` is the path exactly as that read stored it, and
    `raised` is Doug's own label for every finding that read stored under
    this rule on that file."""

    ruling: Ruling
    head_sha: str
    file: str
    raised: tuple[str, ...]


@dataclass(frozen=True)
class Resolved:
    rulings: tuple[ResolvedRuling, ...]
    skipped: tuple[Skipped, ...]


def _blocks(description: str) -> tuple[list[list[str]], int, int]:
    """Every `doug-rulings` block's lines, how many blocks never closed, and
    how many an earlier unclosed fence swallowed.

    Fences are tracked the way CommonMark tracks them, so a `doug-rulings`
    block shown as an example inside a longer fence is example text, not a
    block. A fence closes on a line of the same character, at least as long
    as its opener, with nothing after it. An unclosed fence runs to the end
    of the description, as GitHub renders it; a `doug-rulings` opener inside
    one is counted as swallowed, so the author is told why nothing was read
    rather than seeing the pass silently not run.
    """
    blocks: list[list[str]] = []
    unclosed = 0
    swallowed = 0
    lines = description.splitlines()
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if m is None:
            i += 1
            continue
        fence, info = m.group(1), m.group(2).strip()
        if fence[0] == "`" and "`" in info:
            i += 1
            continue
        closer = re.compile(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*$")
        body: list[str] = []
        i += 1
        closed = False
        while i < len(lines):
            if closer.match(lines[i]):
                closed = True
                i += 1
                break
            body.append(lines[i])
            i += 1
        if info != BLOCK_INFO:
            if not closed and any(_opens_block(line) for line in body):
                swallowed += 1
            continue
        if closed:
            blocks.append(body)
        else:
            unclosed += 1
    return blocks, unclosed, swallowed


def _opens_block(line: str) -> bool:
    m = _FENCE_RE.match(line)
    return m is not None and m.group(2).strip() == BLOCK_INFO


def _text_error(name: str, value: object, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{name} must be a non-empty string"
    if len(value) > limit:
        return f"{name} is longer than {limit} characters"
    return None


def _value_error(obj: dict[str, object]) -> str | None:
    """The first field that is not exactly what the block allows, or None."""
    read, rule, verdict = obj["read"], obj["rule"], obj["verdict"]
    if not isinstance(read, str) or not _READ_RE.match(read):
        return "read must be 7 to 40 lowercase hex characters of a head sha"
    if not isinstance(rule, str) or not valid_rule(rule):
        return "rule must be <prefix>:<slug>, both kebab-case"
    if err := _text_error("file", obj["file"], MAX_FILE_CHARS):
        return err
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        return f"verdict must be one of {', '.join(sorted(VERDICTS))}"
    if not isinstance(obj["changed"], bool):
        return "changed must be true or false"
    if err := _text_error("reason", obj["reason"], MAX_REASON_CHARS):
        return err
    if "ref" in obj and (err := _text_error("ref", obj["ref"], MAX_REF_CHARS)):
        return err
    return None


def _row(raw: object, row: int) -> Ruling | Skipped:
    if not isinstance(raw, dict):
        return Skipped(row, "is not a JSON object")
    obj = cast(dict[str, object], raw)
    missing = _REQUIRED - obj.keys()
    if missing:
        return Skipped(row, f"is missing {', '.join(sorted(missing))}")
    unknown = set(obj) - _REQUIRED - _OPTIONAL
    if unknown:
        return Skipped(row, f"has unknown keys {', '.join(sorted(unknown))}")
    if err := _value_error(obj):
        return Skipped(row, err)
    ref = obj.get("ref")
    return Ruling(
        row=row,
        read=cast(str, obj["read"]),
        rule=cast(str, obj["rule"]),
        file=cast(str, obj["file"]).strip(),
        verdict=cast(Verdict, obj["verdict"]),
        changed=cast(bool, obj["changed"]),
        reason=cast(str, obj["reason"]).strip(),
        ref=ref.strip() if isinstance(ref, str) else None,
    )


def _unread_block(found: int, *, unclosed: int, swallowed: int) -> str | None:
    """Why the block that is present cannot be read, or None when it can."""
    if found > 1:
        return (
            f"the description has {found} doug-rulings blocks; "
            "keep one, and no ruling is read until then"
        )
    if swallowed:
        return (
            "an earlier code fence is never closed, so the doug-rulings block "
            "after it is read as code"
        )
    if unclosed:
        return "the doug-rulings block is never closed"
    return None


def parse(description: str | None) -> Block | None:
    """The description's rulings block, or None when it has none.

    None is the only answer that means "do not run the pass". A block that
    was present but unreadable returns a Block with no rulings and the reason
    in `skipped`, so the check run can say why nothing carried.
    """
    if not description:
        return None
    blocks, unclosed, swallowed = _blocks(description)
    found = len(blocks) + unclosed + swallowed
    if not found:
        return None
    if unread := _unread_block(found, unclosed=unclosed, swallowed=swallowed):
        return Block((), (Skipped(None, unread),))
    rulings: list[Ruling] = []
    skipped: list[Skipped] = []
    counted = 0
    for n, line in enumerate(blocks[0], start=1):
        if not line.strip():
            continue
        counted += 1
        if counted > MAX_ROWS:
            skipped.append(Skipped(n, f"rows past the first {MAX_ROWS} are not read"))
            break
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            skipped.append(Skipped(n, f"is not valid JSON ({e.msg})"))
            continue
        out = _row(raw, n)
        if isinstance(out, Skipped):
            skipped.append(out)
        else:
            rulings.append(out)
    return Block(tuple(rulings), tuple(skipped))


def same_path(a: str, b: str) -> bool:
    """One file, spelled from two places.

    The model writes a finding's path and the author copies it, so either can
    carry a prefix the other lacks (`doug/x.py` against `api/doug/x.py`).
    Equal, or one ends with `/` plus the other, the same rule
    `reader.Coverage.read_of` applies.
    """
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def _same_rule(stored: str, ruled: str) -> bool:
    """The stored rule and the ruled one name one reader finding.

    Only the spelling folds (`patterns.slugify`), because the stored slug is
    free-form model output and the ruled one was kebab-cased by hand. Two
    different words stay two rules; `patterns.SLUG_MERGES` is not applied,
    since merging slugs is a judgment and this is a lookup.
    """
    if not (stored.startswith(RULE_PREFIX) and ruled.startswith(RULE_PREFIX)):
        return False
    return slugify(stored[len(RULE_PREFIX) :]) == slugify(ruled[len(RULE_PREFIX) :])


def resolve(block: Block, reads: Mapping[str, Sequence[PriorFinding]]) -> Resolved:
    """Anchor each ruling to a finding this PR's stored reads contain.

    `reads` maps the full head sha of every earlier reader-tier read of this
    PR to the findings it stored. The read being made now is not in it,
    because it has not been stored yet.

    A ruling survives only when its `read` is a prefix of exactly one of
    those shas, its rule is a reader finding's, and that read stored a
    finding with the same rule on the same file. Every other ruling is
    skipped and named, and none is repaired.
    """
    kept: list[ResolvedRuling] = []
    skipped = list(block.skipped)
    for r in block.rulings:
        shas = [sha for sha in reads if sha.startswith(r.read)]
        if not shas:
            skipped.append(Skipped(r.row, f"read {r.read} names no earlier read of this PR"))
            continue
        if len(shas) > 1:
            skipped.append(
                Skipped(
                    r.row,
                    f"read {r.read} matches {len(shas)} reads of this PR; give more of the sha",
                )
            )
            continue
        if not r.rule.startswith(RULE_PREFIX):
            skipped.append(
                Skipped(r.row, f"only {RULE_PREFIX} findings carry, and {r.rule} is not one")
            )
            continue
        (sha,) = shas
        matches = [
            f
            for f in reads[sha]
            if _same_rule(f.rule, r.rule) and f.file is not None and same_path(f.file, r.file)
        ]
        files = sorted({f.file for f in matches if f.file is not None})
        if not files:
            skipped.append(
                Skipped(r.row, f"read {sha[:12]} stored no {r.rule} finding on {r.file}")
            )
            continue
        if len(files) > 1:
            # `util.py` against `a/util.py` and `b/util.py`: the ruling could
            # anchor to either file's finding, and picking one is a guess.
            skipped.append(
                Skipped(
                    r.row,
                    f"file {r.file} matches {len(files)} files read {sha[:12]} stored "
                    f"{r.rule} on; give the full path",
                )
            )
            continue
        (file,) = files
        raised = tuple(f.label for f in matches)
        kept.append(ResolvedRuling(ruling=r, head_sha=sha, file=file, raised=raised))
    return Resolved(tuple(kept), tuple(skipped))
