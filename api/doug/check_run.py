"""The check run — the one thing Doug writes to a pull request.

Advisory by construction: the conclusion is always neutral, so a Doug run
can never gate a merge. ADR-0010 replaces ADR-0003 and keeps its argument
intact — a router that blocks needs precision this evidence base does not
have, and the honest surface for a judgment that might be wrong is one
that costs nothing to ignore.

Three things this surface must never smooth over:

  * A deterministic fallback is not a read. review.score_one falls back
    silently when the reader is off or a read raised, and the Verdict is
    shape-identical either way — so the tier goes in the title, which is
    the only part visible from the PR's checks list.
  * A partial read must never render as a whole one — on either side.
    IntentRead carries its own `coverage` (review.py:149-153) precisely
    because a deviation built from a truncated diff is exactly as
    unverifiable past the cut as a risk finding is; it just wasn't saying
    so. This module surfaces both cuts, folding the two together only
    when they say the same thing.
  * Deviation findings come from the intent tier, whose derangement check
    did not pass (2026-07-31). The instrument is not validated, so they
    render in their own labelled section and never touch band or score
    (ADR-0007).

`pr_comment.py` mirrors this summary byte-for-byte inside a PR comment; anything
that must not reach a comment must be neutralised here, not there.
"""

import re
import sys

from .models import Band, Verdict
from .reader import Coverage, truncation_reason
from .review import IntentRead
from .settle import SETTLED_REASON_CODES
from .store import InstrumentSnapshot

NAME = "Doug"
# GitHub caps output.summary at 65535 chars and rejects the whole call over
# it. Leave headroom rather than discovering the cap on a 400-finding PR.
SUMMARY_LIMIT = 60_000
TITLE_LIMIT = 255

NEUTRAL_NOTE = (
    "Doug is advisory: this check is always neutral and never blocks a "
    "merge, whatever the band says."
)
# The first author to fix four findings and re-push read the unchanged
# number as a bug (PR #50). The score prices the PR's shape — it routes
# attention; the findings are the judgment.
RISK_NOTE = (
    "Risk is not a grade and does not go down as findings are fixed: it "
    "prices what this change touches and how much of it, so a change of "
    "this shape earns the same look on every push. What the read actually "
    "found is below."
)
FALLBACK_NOTE = (
    "**The validated diff-reader did not run.** This band and score come "
    "from the deterministic scorer, which never opens the diff — it scores "
    "PR shape (size, paths, authorship) alone. Read it as routing, not as "
    "a judgment about this change."
)
# A Cleared band reads as "safe" to anyone skimming the checks list. It
# means Doug's read found nothing worth a human's time — it is not a
# statement about the change itself, and it must not be read as one.
CLEARED_NOTE = (
    "Cleared means Doug found nothing it wanted a human to look at; it is not a "
    "statement that the change is safe."
)
DEVIATION_HEADING = "### Decision deviations (unvalidated)"
DEVIATION_NOTE = (
    "The instrument behind this section has not passed its derangement "
    "check (2026-07-31), so these are unvalidated observations. They do "
    "not contribute to the band or score above (ADR-0007)."
)
# settle.py drops disproved findings and leaves a weight-0 notice. Listing
# that notice under ### Findings beneath a Flagged title reads as a remaining
# defect. The band is the risk score; nothing survived.
SETTLED_NOTE = (
    "The band is the risk score, not a remaining finding. Every finding "
    "the read produced was disproved at head or against the live schema."
)
# Appended, replacing whatever the cut removed, when the rendered body would
# still exceed SUMMARY_LIMIT. A silent [:SUMMARY_LIMIT] slice reads as a
# complete summary that happens to stop mid-sentence — the same "partial
# reads as whole" problem this module exists to keep out of the findings.
TRUNCATION_NOTICE = "\n\n_Truncated: this check run exceeded GitHub's summary limit._"


def _date(value) -> str:
    return value.strftime("%Y-%m-%d")


def _footer(instrument: InstrumentSnapshot) -> list[str]:
    line = (
        f"adjudicated {instrument.adjudicated} · pending {instrument.pending} "
        f"· as of {_date(instrument.as_of)}"
    )
    if instrument.adjudicated == 0 and instrument.first_due is not None:
        line += f" · first due {_date(instrument.first_due)}"
    # Two leading empties -> a blank line before the footer. The body's last
    # line is a list item (or the Judged-against paragraph); one newline
    # after a list item is a GFM lazy continuation, which would glue these
    # lines into that bullet instead of rendering them as their own block.
    lines = ["", "", line]
    if instrument.deep_reads is not None:
        lines.append(
            f"deep reads {instrument.deep_reads}/{instrument.deep_read_cap} this cycle"
        )
    return lines


def _headline(tier: str, verdict: Verdict) -> str:
    band = verdict.band.value.capitalize()
    if tier == "reader":
        return f"{band} · risk {verdict.score:.2f} · diff read"
    return f"Deterministic fallback · {band} · risk {verdict.score:.2f}"


# Zero-width space. Invisible wherever this markdown renders, but it splits
# a token in two so the tokeniser that would otherwise fire a side effect —
# a mention, a cross-reference, a live link, an HTML comment — never sees
# an intact one. r.label and d.description are free-form model output,
# attacker-influenceable via a public repo's diff (Reason.label is the
# reader's own description; truncation_reason splices file paths), and
# `pr_comment.py` renders this same text live inside a PR conversation
# where those tokens are not inert. Neutralising here, at the one
# chokepoint every model-authored span already passes through, keeps the
# check run and the comment byte-identical instead of diverging at the
# surface that has to be safe.
_ZWSP = "\u200b"

# `@handle` notifies and subscribes that account in a PR comment. Exclude a
# preceding word char or dot so `a@b.c` still reads as the email address it
# is, not a mention of `b`.
_MENTION_RE = re.compile(r"(?<![\w.])@(?=\w)")
# `#123` writes a cross-reference into that issue's timeline, whether bare
# or repo-qualified (`owner/repo#4`). Earlier drafts tried to tell the two
# apart by what precedes the `#` (a word char/`/` meant "already covered by
# the repo-qualified case") and by requiring a contiguous `\w+/\w+` repo
# segment — both gaps: a hyphenated or dotted repo name (`hello-world`,
# `repo.js`, the GitHub-common case) isn't `\w+`, so the digits after its
# `#` fell through both regexes untouched, and a `/` with no repo segment
# at all (`docs/#123`) fell through the same way. A ZWSP is invisible in
# rendered markdown either way, so there is nothing to gain from trying to
# scope the match to "real" refs: every `#` immediately followed by a
# digit gets one, unconditionally.
_REF_RE = re.compile(r"#(?=\d)")
# An unterminated `<!--` opens an HTML comment that swallows the rest of
# the comment body.
_COMMENT_OPEN_RE = re.compile(r"<!--")
# `[text](url)` is a live, clickable link rendered under a bot identity
# users are taught to trust.
_LINK_RE = re.compile(r"\]\(")


def _oneline(text: str) -> str:
    """Collapse model-authored text to one physical line and neutralise the
    GitHub/markdown tokens that are inert here but have side effects when
    this same text is mirrored into a PR comment (pr_comment.py).

    r.label and d.description are free-form model output. A literal
    newline followed by '### Findings' or '### Decision deviations' would
    close the current list and open what reads as a second, forged section
    boundary — laundering injected text as this module's own structure.
    Collapsing whitespace keeps every finding inside its own list item.
    """
    collapsed = " ".join(text.split())
    collapsed = _MENTION_RE.sub(f"@{_ZWSP}", collapsed)
    collapsed = _REF_RE.sub(f"#{_ZWSP}", collapsed)
    collapsed = _COMMENT_OPEN_RE.sub(f"<!-{_ZWSP}-", collapsed)
    collapsed = _LINK_RE.sub(f"]{_ZWSP}(", collapsed)
    return collapsed


def _quote(reason) -> list[str]:
    # The label already opens "Partial read:" — reader.truncation_reason
    # writes the whole sentence. Adding a heading of our own printed the
    # words twice and broke the caveat's own once-and-only-once rule.
    #
    # Routed through _oneline: this label also splices file paths
    # (truncation_reason, reader.py), which may themselves contain `@` or a
    # newline. An unescaped newline here breaks out of the blockquote and
    # lands at the top level of a public PR comment.
    return ["", f"> {_oneline(reason.label)}"]


def render(
    tier: str,
    verdict: Verdict,
    intent_read: IntentRead | None,
    coverage: Coverage | None,
    instrument: InstrumentSnapshot | None = None,
) -> tuple[str, str]:
    """(title, summary_md) for one verdict."""
    title = _headline(tier, verdict)
    partial = truncation_reason(coverage) if coverage is not None else None

    lines = [
        f"**{title}**",
        "",
        (
            f"Risk {verdict.score:.2f} against a flag line of {verdict.threshold:.2f}. "
            "The flag line is set per repository on the Doug dashboard."
        ),
        RISK_NOTE,
        NEUTRAL_NOTE,
    ]
    if verdict.band is Band.CLEARED:
        lines += ["", CLEARED_NOTE]
    if tier != "reader":
        lines += ["", FALLBACK_NOTE]
    if partial is not None:
        lines += _quote(partial)

    # Folded into the block above, so it is stated once — but only when that
    # block rendered, so it can never be lost instead.
    skip = {"read-truncated"} if partial is not None else set()
    risks = [r for r in verdict.reasons if r.rule not in skip]
    # `partial is None` is load-bearing, not defensive. SETTLED_NOTE reads as
    # "nothing survived"; on a KNOWN-partial read that claim sits directly
    # beneath the blockquote saying a clear is not evidence about the rest, and
    # the two contradict. The truncation Reason is filtered out of `risks` two
    # lines up, so without this guard the pair renders together.
    #
    # Deliberately NOT `coverage is not None and partial is None`. `partial` is
    # also None when coverage was never recorded (worker.py:100, replaying a
    # row with no stored coverage), and the note DOES render there, unqualified.
    # That is intended: settle.py's notices are appended only in review.py's
    # reader branch, immediately before a real coverage is computed and
    # returned (review.py:367-376), so reasons-all-settled with absent coverage
    # is unreachable on the live path — legacy replays only — and the note's
    # claim is about the findings the read produced, which stays true whatever
    # the coverage. Tightening this to require known-complete coverage would
    # buy nothing and would reintroduce #109's misreading (a settled notice
    # listed under "Findings" beneath a Flagged title, reading as a remaining
    # defect) for every replayed check run.
    only_settled = (
        partial is None
        and bool(risks)
        and all(r.rule in SETTLED_REASON_CODES for r in risks)
    )
    lines += ["", "### Findings", ""]
    if only_settled and verdict.band == Band.FLAGGED:
        lines += [SETTLED_NOTE, ""]
    if risks:
        lines += [
            f"- `{r.rule}` — {_oneline(r.label)}" + (f" _({r.severity})_" if r.severity else "")
            for r in risks
        ]
    else:
        lines.append("- none")

    if intent_read is not None:
        # IntentRead reads the same diff at the same DIFF_BUDGET the risk
        # tier did, but it is not guaranteed to be the same call — so its
        # own coverage is checked independently rather than assumed to
        # match `coverage` above.
        intent_partial = truncation_reason(intent_read.coverage)
        lines += ["", DEVIATION_HEADING, "", DEVIATION_NOTE]
        if intent_partial is not None and (
            partial is None or intent_partial.label != partial.label
        ):
            lines += _quote(intent_partial)
        lines += [""]
        if intent_read.findings:
            lines += [
                f"- `{d.type}` — {_oneline(d.description)} _({d.severity})_"
                for d in intent_read.findings
            ]
        else:
            lines.append(f"- none (alignment {intent_read.alignment}/100)")
        lines += ["", f"Judged against: {', '.join(intent_read.refs) or 'no records'}."]

    footer = "\n".join(_footer(instrument)) if instrument is not None else ""
    body = "\n".join(lines)
    combined = body + footer
    if len(combined) > SUMMARY_LIMIT:
        # Keep the instrument lines (and the truncation marker) as a
        # reserved tail. Cutting from the front would drop the footer on
        # the oversized-findings case the cap is sized for.
        reserved = TRUNCATION_NOTICE + footer
        cut = max(0, SUMMARY_LIMIT - len(reserved))
        combined = body[:cut] + reserved
    return title[:TITLE_LIMIT], combined


def post(gh, owner: str, repo: str, head_sha: str, title: str, summary: str) -> None:
    """Create the check run. Never raises.

    This is an advisory surface hanging off work that is already durable —
    the verdict is in the ledger before this runs. A GitHub outage, a
    revoked installation or a force-pushed-away SHA must not turn a good
    verdict into a retried job.
    """
    try:
        gh.rest.checks.create(
            owner=owner,
            repo=repo,
            name=NAME,
            head_sha=head_sha,
            status="completed",
            conclusion="neutral",
            output={"title": title[:TITLE_LIMIT], "summary": summary[:SUMMARY_LIMIT]},
        )
    except Exception as e:  # noqa: BLE001 — advisory surface, never fails a job
        print(
            f"doug: check run not posted for {owner}/{repo}@{head_sha[:12]} "
            f"({type(e).__name__}: {e})",
            file=sys.stderr,
        )
