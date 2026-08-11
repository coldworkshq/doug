"""Convergence — the finding-diff between two verdicts on the same PR.

The fix-loop halt signal: "is this PR converging?", beside the risk score's
"how hard should we look?". Pre-registered in
`docs/design/outcome-loop/convergence-design.md`; this module implements that
note and nothing else.

Two properties are load-bearing.

**It is pure.** A function of the rows it is handed — no store, no engine, no
clock, no network. That is what makes "convergence buys no new read" a fact
about the code rather than a promise about call sites, and it is why this
module never enters `score()` (spec §3, design-lock.md:75): a derived query-time
field is exempt from the 2.34x bar and ADR-0012 only for as long as it stays
derived.

**It abstains rather than guess.** Identity is `(pattern, file)` and the schema
carries no line numbers, so absence is weak evidence: `findings.file` can be
lost at write time (store.py:825-838), the later read may never have seen the
file, and `settle.py` drops findings Doug itself disproved between the two
reads. Each of those is an `unknown`, never a `resolved`, because the failure is
asymmetric — a false `resolved` tells an agent it is done when it is not.
`unknown` is reported alongside the counts and never folded into the ratio.
"""

from collections import Counter
from dataclasses import dataclass

from .patterns import from_rule, normalize

# settle.py's two weight-0 notices, appended to the later verdict's reasons
# when it disproved a finding rather than the author fixing it
# (settle.py:192, :291). Their label grammar is parsed below and pinned by
# tests/test_convergence.py against the real emitters.
SETTLEMENT_RULES = frozenset({"settled-missing-import", "settled-schema-dependency"})

IDENTITY_INCOMPLETE = "identity-incomplete"
FILE_UNCOVERED = "file-uncovered"
SETTLED = "settled"

_NOTICE_HEADER_SEP = " — "
_NOTICE_SEGMENT_SEP = "; "


@dataclass(frozen=True)
class ConvergenceReport:
    """Counts over one consecutive verdict pair. `unknown` carries only the
    non-zero abstention reasons; an empty dict means no abstentions, not that
    the reasons are unavailable."""

    resolved: int
    persisted: int
    new: int
    unknown: dict[str, int]

    @property
    def unknown_total(self) -> int:
        return sum(self.unknown.values())

    @property
    def ratio(self) -> float | None:
        """resolved / (resolved + persisted), or None when nothing is known.

        Abstentions are deliberately absent from both terms: an `unknown` that
        moved this number would let "we could not tell" masquerade as progress
        in either direction.
        """
        decided = self.resolved + self.persisted
        return None if decided == 0 else self.resolved / decided


def compare(
    prior_findings: list[dict],
    later_findings: list[dict],
    later_reasons: list[dict],
    later_read: dict | None,
) -> ConvergenceReport:
    """Classify every prior finding against the later verdict.

    `prior_findings`/`later_findings` are `findings` rows (`rule`, `label`,
    `file`, `severity`); `later_reasons` are the later verdict's rows from the
    same table, read only for settlement notices; `later_read` is its `reads`
    row (`files_unseen`, `file_cut`, `files_dropped`, `changed_files`) or None.
    """
    unknown: Counter[str] = Counter()
    prior = _identities(prior_findings, unknown)
    later = _identities(later_findings, unknown)

    resolved = persisted = 0
    for identity, count in prior.items():
        matched = min(count, later[identity])
        persisted += matched
        for _ in range(count - matched):
            reason = _abstention(identity, later_reasons, later_read)
            if reason is None:
                resolved += 1
            else:
                unknown[reason] += 1

    new = sum(max(0, count - prior[identity]) for identity, count in later.items())

    return ConvergenceReport(
        resolved=resolved,
        persisted=persisted,
        new=new,
        unknown=dict(unknown),
    )


def _identities(rows: list[dict], unknown: Counter[str]) -> Counter[tuple[str, str]]:
    """Reader findings as `(pattern, file)` counts.

    Non-reader rows (`from_rule` is None — the deterministic tier's own
    vocabulary sharing this table) are excluded outright. A row with no file
    has an incomplete identity: it takes no part in matching on either side,
    so it can neither absorb a prior finding into `persisted` nor inflate
    `new`.
    """
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        pattern = from_rule(row["rule"])
        if pattern is None:
            continue
        file = row["file"]
        if file is None:
            unknown[IDENTITY_INCOMPLETE] += 1
            continue
        counts[(pattern, file)] += 1
    return counts


def _abstention(
    identity: tuple[str, str],
    later_reasons: list[dict],
    later_read: dict | None,
) -> str | None:
    """The reason this prior finding's absence proves nothing, or None if the
    absence is real. Checked in the note's order — every abstention beats a
    false `resolved`."""
    if _uncovered(identity[1], later_read):
        return FILE_UNCOVERED
    if _settled(identity, later_reasons):
        return SETTLED
    return None


def _uncovered(file: str, later_read: dict | None) -> bool:
    """Did the later read fail to see this file?

    No read row at all counts as uncovered: only reader-tier verdicts get one
    (store.py:143-150), so its absence means we cannot say what was shown.
    `file_cut` is the single file the budget landed inside — seen in part,
    which cannot settle an absence (reader.py:429-431). Comparison is exact
    string equality; `findings.file` is model-emitted while these paths come
    from the diff headers, and a rule that guesses when two spellings mean one
    file can guess wrong toward `resolved`.
    """
    if later_read is None:
        return True
    if file in (later_read.get("files_unseen") or []):
        return True
    if file in (later_read.get("files_dropped") or []):
        return True
    return later_read.get("file_cut") == file


def _settled(identity: tuple[str, str], later_reasons: list[dict]) -> bool:
    """Did the later verdict disprove this finding instead of the author
    fixing it? Doug's own settlement is not the author's progress."""
    pattern, file = identity
    for row in later_reasons:
        if row.get("rule") not in SETTLEMENT_RULES:
            continue
        for noticed_file, noticed_slug in _notice_segments(row.get("label") or ""):
            if noticed_file == file and normalize(noticed_slug) == pattern:
                return True
    return False


def _notice_segments(label: str):
    """`(file, canonical-ready slug)` pairs named by a settlement notice.

    The grammar is settle.py's: a header, ` — `, then `"; "`-joined
    `f"{file}: {category_slug} ({claim})"` segments (settle.py:187-190,
    287-289). A label that does not parse yields nothing and therefore matches
    nothing — a silent match-everything would hide an emitter change behind a
    wall of `unknown`, where a match-nothing surfaces it as the pinning test
    in tests/test_convergence.py failing.

    The slug is the raw `category_slug`, which settle.py tolerates carrying a
    `reader:` prefix (settle.py:72, :208); the caller normalizes so rule 4
    compares canonical patterns, not raw spellings.
    """
    _, sep, segments = label.partition(_NOTICE_HEADER_SEP)
    if not sep:
        return
    for segment in segments.split(_NOTICE_SEGMENT_SEP):
        file, sep, rest = segment.partition(": ")
        if not sep:
            continue
        slug, sep, _ = rest.partition(" (")
        if not sep:
            continue
        yield file, slug.removeprefix("reader:")
