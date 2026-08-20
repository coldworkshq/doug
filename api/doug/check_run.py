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

# These two are STANDING text: identical on every PR, on both tiers. They
# render under HOW_TO_READ_HEADING, below the findings, because ~120 words of
# unconditional caveat above the first finding is how the old layout buried
# the only part of the summary that changes from push to push. Honesty about
# THIS run — the fallback, a partial read, the band — stays above, in the
# alert. Conditional above, unconditional below; that is the whole rule.
NEUTRAL_NOTE = (
    "**Doug never blocks a merge.** This check is always neutral, whatever "
    "the band says."
)
# The first author to fix four findings and re-push read the unchanged
# number as a bug (PR #50). The score prices the PR's shape — it routes
# attention; the findings are the judgment.
RISK_NOTE = (
    "**Risk is not a grade.** It prices what this change touches and how "
    "much of it, so a change of this shape earns the same look on every "
    "push. It does not go down as findings are fixed; the findings are the "
    "judgment."
)
FLAG_LINE_NOTE = "**The flag line is per repository**, set on the Doug dashboard."
HOW_TO_READ_HEADING = "### How to read this"

_FALLBACK_BODY = (
    "This band and score come from the deterministic scorer, which never "
    "opens the diff — it scores PR shape (size, paths, authorship) alone. "
    "Read it as routing, not as a judgment about this change."
)
FALLBACK_NOTE = "**The validated diff-reader did not run.** " + _FALLBACK_BODY
FALLBACK_FLAGGED_NOTE = (
    "**Needs you, but the validated diff-reader did not run.** " + _FALLBACK_BODY
)
# A Cleared band reads as "safe" to anyone skimming the checks list. It
# means Doug's read found nothing worth a human's time — it is not a
# statement about the change itself, and it must not be read as one.
CLEARED_NOTE = (
    "Cleared means Doug found nothing it wanted a human to look at; it is not a "
    "statement that the change is safe."
)
# The one question this surface exists to answer, and the only thing allowed
# to raise an alert.
#
# It is keyed to the BAND, never to a finding's severity. The band is
# computed against `installation_repos.needs_you_threshold` — a number the
# tenant set, per ADR-0013. A severity is the model's own call: the reader
# schema constrains it to low/medium/high (reader.py), the Python model types
# it `str | None` and validates nothing (models.py). The two are independent,
# and the case that decides it is ordinary rather than exotic: a Cleared
# verdict routinely carries a medium finding, so a severity-keyed alert would
# put a stop sign on a change this module just said nobody needs to look at,
# contradicting CLEARED_NOTE two lines above it.
NEEDS_YOU = (
    "**Needs you.** Risk is above this repository's flag line, so Doug is "
    "asking for a human read. It does not block: this check is neutral and "
    "the merge button is unchanged."
)
# GitHub renders these as themed callouts in a PR comment (pr_comment.py
# mirrors this summary verbatim). CAUTION is deliberately absent: red reads
# as "stop", and a surface that never blocks a merge and has adjudicated
# nothing has not earned it (ADR-0010).
_ALERT_IMPORTANT = "[!IMPORTANT]"
_ALERT_WARNING = "[!WARNING]"

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
# an intact one. r.rule, r.label and d.description are free-form model
# output (`reader:{category_slug}` is built from a schema field carrying no
# enum and no pattern), and the `Judged against:` line splices
# repo-controlled filenames; all four are attacker-influenceable via a
# public repo's diff or its decisions directory (truncation_reason also
# splices file paths), and
# `pr_comment.py` renders this same text live inside a PR conversation
# where those tokens are not inert. Neutralising here, at the one
# chokepoint every model-authored span already passes through, keeps the
# check run and the comment byte-identical instead of diverging at the
# surface that has to be safe.
_ZWSP = "\u200b"

# `@handle` notifies and subscribes that account in a PR comment. Exclude a
# preceding word char so `a@b.c` still reads as the email address it is, not
# a mention of `b` — in `a@b.c` the `@` follows `a`, which is all that case
# ever needed. An earlier version excluded a preceding `.` as well, on the
# same email rationale; the dot was pure loss, because GitHub linkifies
# `@handle` after any non-word character, `.` included, so `foo.@octocat`
# went out live. Same ruling as `_REF_RE` below: there is nothing to gain
# from scoping the match, because the ZWSP is invisible either way.
_MENTION_RE = re.compile(r"(?<!\w)@(?=\w)")
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
# GFM autolinks a bare `https://evil.example/login` with no `](` anywhere —
# the same live link by a shorter route. The reference-style form
# (`[text][id]` plus a trailing `[id]: url` definition) is deliberately not
# chased: a link definition cannot sit mid-line, and `_oneline` collapses
# everything to one line, so its definition half can never survive.
_URL_RE = re.compile(r"://")


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
    collapsed = _URL_RE.sub(f":{_ZWSP}//", collapsed)
    return collapsed


def _rule_span(rule: str) -> str:
    """A `Reason.rule` as it is rendered inside a code span.

    `rule` is not a fixed vocabulary. On the reader tier it is
    f"reader:{category_slug}" (reader.py:1349) and `category_slug` is a
    free-form schema string — a description, no enum, no pattern
    (reader.py:89-96) — so it is model output on exactly the same footing as
    the label beside it, and it goes through the same chokepoint. Used for
    the deviation `type` too: that one IS enum-constrained in the schema, but
    the Python model types it `str` and validates nothing, and honouring the
    rule everywhere costs nothing, while an exception in the middle of it is
    what a later reader has to re-derive. The
    backtick is dropped rather than split: it carries no meaning in a slug,
    and it is the one character that would close the code span and hand the
    rest of the rule to the markdown renderer as live text.
    """
    return _oneline(rule.replace("`", ""))


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


# The order counts render in, not a validation list — see _finding_counts for
# why an unrecognised severity falls back to a plain count instead of being
# escaped into a table cell.
_SEVERITY_ORDER = ("high", "medium", "low")


def _read_cell(tier: str) -> str:
    """The summary table's Read cell. Static strings on both branches."""
    return "validated diff reader" if tier == "reader" else "none — scorer only"


def _finding_counts(risks: list) -> str:
    """The summary table's Findings cell.

    NOTHING model-authored reaches this string, and that is a hard rule
    rather than a preference: a `|` inside a table cell ends the cell and
    shifts every column after it, which `_oneline` does not neutralise
    because a pipe is inert everywhere else this module writes. So the
    severity words are emitted from `_SEVERITY_ORDER`, never echoed from the
    verdict — the moment any finding carries a severity outside that
    vocabulary, the whole cell degrades to a count. The raw severity still
    reaches the reader in the findings list below, where `_oneline` already
    governs it.

    Settlement notices are excluded. They are weight-0 markers for findings
    that were DISPROVED (settle.py), so counting them would put a number in
    the header of a summary whose body says nothing survived — the same
    misreading SETTLED_NOTE exists to end (#109).
    """
    countable = [r for r in risks if r.rule not in SETTLED_REASON_CODES]
    if not countable:
        return "none"
    graded = [(r.severity or "").strip().lower() for r in countable]
    if all(g in _SEVERITY_ORDER for g in graded):
        buckets = {s: graded.count(s) for s in _SEVERITY_ORDER if s in graded}
        return " · ".join(f"{n} {s}" for s, n in buckets.items())
    return "1 finding" if len(countable) == 1 else f"{len(countable)} findings"


def _alert(tier: str, verdict: Verdict, partial) -> list[str]:
    """At most ONE alert, chosen by precedence. Never two.

    Two stacked callouts teach a reader to skip both, so the four run states
    that could each claim one are resolved here instead of each appending
    its own block:

      1. The reader did not run. This says the band is PR shape alone, which
         reframes what Flagged even MEANS, so it outranks the routing call
         and carries it inside its own body rather than losing it.
      2. The read was truncated. A clear is not evidence about anything past
         the cut, and `render` filters the matching Reason out of the
         findings list on the strength of this block rendering.
      3. Flagged on a clean read. The routing call, unqualified.
      4. Cleared on a clean read. Nothing. Quiet is the signal — an alert on
         every PR is an alert on none.

    Returns the lines to splice, blank-line-first, or [] for state 4.
    """
    flagged = verdict.band is Band.FLAGGED
    if tier != "reader":
        return _alert_block(
            _ALERT_WARNING, FALLBACK_FLAGGED_NOTE if flagged else FALLBACK_NOTE
        )
    if partial is not None:
        # `partial.label` is reader.truncation_reason's whole sentence and it
        # splices file paths, so it goes through the same chokepoint as every
        # other model- or repo-influenced span (D7).
        lead = "**Needs you.** " if flagged else ""
        return _alert_block(_ALERT_WARNING, lead + _oneline(partial.label))
    if flagged:
        return _alert_block(_ALERT_IMPORTANT, NEEDS_YOU)
    return []


def _alert_block(kind: str, body: str) -> list[str]:
    """One GitHub alert. `body` must already be a single physical line: the
    marker only opens an alert when it is the blockquote's first line, so a
    stray newline in the body would silently demote the whole block to an
    ordinary quote carrying a literal "[!WARNING]"."""
    return ["", f"> {kind}", f"> {body}"]


def _since_section(convergence: dict | None) -> list[str]:
    """The `### Since <sha12>` block, or nothing.

    Walked Out (docs/design/walked-out/): every reader-tier check run
    compares this read with Doug's previous one and says, per earlier
    finding, whether it is carried forward with evidence or cannot be
    judged, with the reason. The headline count is the first line — the per
    -PR fact Andrew ruled ships in v1 (2026-08-20). No rate, no ratio,
    nothing model-authored outside the sanitizer chokepoints, and never a
    claim that anything was fixed: v1 has no resolved state at all.
    """
    if convergence is None:
        return []
    if "error" in convergence:
        return [
            "",
            SINCE_HEADING_FALLBACK,
            "",
            "Doug could not compare with its last diff read; storage did not "
            f"answer ({_oneline(convergence['error'])}).",
        ]
    sha = convergence.get("prior_head_sha")
    label = f"`{_oneline(sha)[:12]}`" if sha else "the previous read"
    rows = convergence.get("classifications") or []
    prior = [c for c in rows if c["side"] == "prior"]
    carried = [c for c in prior if c["state"] == "persisted" and c["basis"] == "by-construction"]
    attributed = [c for c in prior if c["state"] == "persisted" and c["basis"] == "attributed-surviving"]
    unknowns = [c for c in prior if c["state"] == "unknown"]
    new_unchanged = [
        c for c in rows if c["side"] == "later" and c["state"] == "new" and c["code_changed"] is False
    ]
    # Headline: earlier findings on files unchanged between the reads =
    # silent-and-carried (by construction) plus re-reported findings whose
    # own file's delta did not move. The silent ones are the numerator.
    silent = len(carried)
    denominator = silent + sum(
        1
        for c in prior
        if c["state"] == "persisted" and c["basis"] is None and c["code_changed"] is False
    )
    out = [
        "",
        f"### Since {label}" if sha else SINCE_HEADING_FALLBACK,
        "",
        f"Of {denominator} earlier findings on files unchanged since {label}, "
        f"{silent} were not mentioned by this read.",
        "",
        f"Compared with Doug's last diff read at {label}. This section grades "
        "Doug's own reader, not your change; the reader's silence is not evidence.",
    ]

    def _line(c: dict, sentence: str) -> str:
        path = _oneline(c.get("file") or "(no file)")
        return f"- `{_rule_span(c.get('rule') or '')}` · {path} — {sentence}"

    if carried or attributed:
        out += ["", "**Still here**", ""]
        for c in carried:
            if c.get("pair_delta") == "changed-elsewhere":
                out.append(_line(
                    c,
                    f"cited file's diff is byte-unchanged since {label}; other "
                    "code in this PR changed. Carried forward, not re-verified. "
                    "If you addressed it elsewhere, a human should look.",
                ))
            else:
                out.append(_line(
                    c,
                    f"cited file's diff is byte-unchanged since {label}; "
                    "carried forward, not re-verified.",
                ))
        for c in attributed:
            out.append(_line(
                c,
                "the hunks this finding was attributed to are unchanged since "
                f"{label}; other parts of the file changed. Carried forward, "
                "not re-verified.",
            ))
    if unknowns:
        out += ["", "**Can't say**", ""]
        for c in unknowns:
            out.append(_line(c, _UNKNOWN_SENTENCES.get(
                c.get("unknown_reason") or "",
                "this read could not confirm or clear it.",
            ).format(label=label)))
    if new_unchanged:
        out += [
            "",
            f"**New on files unchanged since {label} ({len(new_unchanged)})** — "
            "this read reported findings on files whose diff did not change; "
            "the earlier read did not.",
            "",
        ]
        out += [_line(c, "new this read.") for c in new_unchanged]
    return out


# Sentences per abstention reason (product-spec.md "v1 check-run copy",
# updated by the 2026-08-20 demote ruling). {label} is the prior-read sha
# span. Everything else in these strings is fixed vocabulary.
_UNKNOWN_SENTENCES = {
    "edited-not-verified": (
        "the cited code changed since {label} and this read did not report it "
        "again; Doug has not verified a fix, so it stays listed."
    ),
    "not-reconfirmed": (
        "part of the cited file's diff changed since {label}; this read did "
        "not confirm or clear it, and Doug has no usable attribution for it."
    ),
    "no-hunk-index": (
        "Doug has no hunk record for one of the two reads, so it cannot compare."
    ),
    "file-uncovered": (
        "Doug did not read this file in one of the two reads (cut or unseen)."
    ),
    "left-diff": (
        "no longer in this PR's diff (reverted, renamed, or landed another "
        "way); Doug cannot tell which."
    ),
    "settled": (
        "Doug's own deterministic check disproved this finding at this head; "
        "not counted as your progress."
    ),
    "identity-incomplete": (
        "no file recorded for this finding, so Doug cannot compare it."
    ),
}

SINCE_HEADING_FALLBACK = "### Since the previous read"


def render(
    tier: str,
    verdict: Verdict,
    intent_read: IntentRead | None,
    coverage: Coverage | None,
    instrument: InstrumentSnapshot | None = None,
    convergence: dict | None = None,
) -> tuple[str, str]:
    """(title, summary_md) for one verdict."""
    title = _headline(tier, verdict)
    partial = truncation_reason(coverage) if coverage is not None else None

    # Folded into the alert below, so it is stated once — but only when that
    # alert renders, so it can never be lost instead. Computed BEFORE the
    # lines, because the summary table's Findings cell counts this list.
    skip = {"read-truncated"} if partial is not None else set()
    risks = [r for r in verdict.reasons if r.rule not in skip]

    # The numbers, as a table. Every cell is either a float this module
    # formatted or a string from a fixed vocabulary — see _finding_counts on
    # why nothing model-authored is allowed in here.
    lines = [
        f"**{title}**",
        "",
        "| Risk | Flag line | Read | Findings |",
        "|:--|:--|:--|:--|",
        f"| **{verdict.score:.2f}** | {verdict.threshold:.2f} "
        f"| {_read_cell(tier)} | {_finding_counts(risks)} |",
    ]
    lines += _alert(tier, verdict, partial)
    if verdict.band is Band.CLEARED:
        # A quote, not an alert. This defines what the band means; it does
        # not ask the reader for anything, and the one alert slot belongs to
        # the state that does.
        lines += ["", f"> {CLEARED_NOTE}"]
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
            f"- `{_rule_span(r.rule)}` — {_oneline(r.label)}"
            + (f" _({_oneline(r.severity)})_" if r.severity else "")
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
                f"- `{_rule_span(d.type)}` — {_oneline(d.description)} "
                f"_({_oneline(d.severity)})_"
                for d in intent_read.findings
            ]
        else:
            lines.append(f"- none (alignment {intent_read.alignment}/100)")
        # `refs` is [d.id for d in chosen], and IntentDoc.id falls back to the
        # raw filename stem outside the ADR-NNNN convention
        # (intent_providers.py:73) — a repo-controlled string, so it is
        # spliced through the same chokepoint as everything else here.
        joined = _oneline(", ".join(intent_read.refs)) or "no records"
        lines += ["", f"Judged against: {joined}."]

    lines += _since_section(convergence)

    lines += ["", HOW_TO_READ_HEADING, "", f"- {RISK_NOTE}", f"- {NEUTRAL_NOTE}",
              f"- {FLAG_LINE_NOTE}"]

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
