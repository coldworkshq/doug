# Doug vs Doug — PR #233 @ 8bcb26c

The second entry of this shape: Doug reviewing a change to Doug's own
check-run renderer. There is no external half, so the calibration signal is
the disposition alone — which of Doug's four findings survive contact with
the code they describe.

PR #233 closes #181. `check_run.SUMMARY_LIMIT`'s cut used to drop findings
behind an unqualified "truncated"; it now states how many it removed,
counted over exactly the population `_finding_counts` prints in the summary
table. It touches `check_run.py` and its test file, nothing else.

Doug read the diff (`validated diff reader`, risk 0.32, **Flagged**, two
medium, two low, no deviations, alignment 92/100).

**Headline: two of four are wrong, and both are wrong the same way — Doug
reasoned correctly from a premise the diff does not contain and the file
does not support.** That is #175 again, at `medium` rather than `high`. Of
the two that survive, one is a real defect fixed here, and the other is a
real defect that is not this PR's: filed as #234.

## Disposition

| # | rule | severity | verdict | outcome |
|---|------|----------|---------|---------|
| 1 | `reader:off-by-one` | low | **right, and narrower than stated** | Fixed. The backup is skipped when the cut already ended a line |
| 2 | `reader:count-mismatch` | medium | **wrong about the code, right about the tests** | No change. The gap it names is now pinned by a test |
| 3 | `reader:api-contract-change` | medium | **wrong** | No change. The string has no consumer outside this module |
| 4 | `reader:fragile-string-parsing` | low | **wrong about this PR, right about the codebase** | Filed as #234 |

## 1. The off-by-one is real, and Doug found it at the wrong end

Doug claimed that when the body fits within `cut`, backing up to
`kept.rfind("\n")` strips a line that did not need cutting. The stated
premise is unreachable: the branch only runs when
`len(body) + len(footer) > SUMMARY_LIMIT`, and `cut` is
`SUMMARY_LIMIT - reserved - len(footer)`, so `len(body) > cut` strictly
whenever the code executes at all.

The defect is real one case over. When `cut` lands **exactly on a
newline**, `body[:cut]` already ends on a whole line, and backing up to the
previous newline throws away a complete bullet that fit — a finding lost to
punctuation, and a shortfall of 1 the cap did not cause. Roughly a 1-in-450
chance per render at these line lengths.

The backup is now `_whole_lines(body, cut)`, which returns the prefix
unchanged when `body[cut]` is already a newline, and is tested directly on
all four of its cases rather than through a 60,000-character render.

Worth recording for the loop: **Doug was right that the guard was missing
and wrong about when it fires.** The consequence it described — a false
shortfall of one — is the consequence that actually exists. A reviewer
acting on this finding would have found the bug.

## 2. The count cannot mismatch, but nothing was proving it

Doug claimed the notice's `total` (`len(counted)`) and the table's Findings
cell can disagree, because `_finding_counts` sums severity buckets while
`counted` holds every countable bullet — so one finding with an
out-of-vocabulary severity would make the two unreconcilable, "precisely
the defect the change claims to close".

It cannot. `_finding_counts` has exactly three returns: `"none"`, severity
buckets **only when every grade is in vocabulary**, and otherwise a bare
`f"{len(countable)} findings"`. The degraded branch prints the same number
the notice subtracts from. `_triage` partitions `risks` without dropping
any, so `len(counted) == len(countable)` on both paths.

The second half of the finding is correct and is the useful half: *"Tests
only use fully graded fixtures."* They did. The degraded cell is now
covered by `test_the_shortfall_reconciles_with_a_degraded_findings_cell`,
which passes unchanged against the code Doug called broken — which is what
distinguishes a coverage gap from a defect.

## 3. The contract has no other party

Doug claimed that emitting something other than `TRUNCATION_NOTICE` will
silently break consumers — "e.g. pr_comment.py, which mirrors this summary
byte-for-byte, or downstream assertions/parsers matching
`summary.endswith(TRUNCATION_NOTICE)`".

`pr_comment.render` takes the summary as an opaque string, frames it, and
never parses it; that is the whole point of ADR-0014's byte-for-byte claim.
A repository-wide search for the constant and for its text finds no
reference outside `check_run.py` and the two assertions in
`test_check_run.py` that this PR updates in the same commit.

The finding names a real class of defect and asserts a fact about this
repository that is not true of it. Same failure as #1 and #2: sound
reasoning, invented premise.

## 4. Right about the codebase, wrong about the diff

Doug claimed `_trim_empty_fold` and `_close_details` are fragile because a
finding label containing a literal `<details>` would unbalance the tags.

For the new functions this does not hold. `_oneline` collapses whitespace,
so a label cannot begin a line, and `_trim_empty_fold` anchors on
`"\n<details>"` — only this module's own opener can match. `_close_details`
would append a closer for a tag the label opened, which is the correct
response to an unclosed tag, not an incorrect one.

But the premise is true, and it is worse than the consequence Doug drew
from it. `_oneline` neutralises `@`, `#`, `<!--`, `](` and `://`, and does
**not** neutralise a bare `<`. GitHub's sanitizer allows `details`, so a
model-authored label carrying one opens a real disclosure inline, and every
finding below it collapses behind a triangle — on the check run and in the
live PR comment both. Confirmed by rendering it through `check_run.render`.

That predates this PR and is not made worse by it, so it is filed rather
than fixed here: **#234**.

## What this says about the reader

Four findings, one useful. The three that failed all failed identically:
Doug reasoned soundly from a premise that was not in the diff and is not in
the file. #175 records this as *findings cite code doug never read*, and
this read is a cleaner instance than #229's was, because here the invented
premises are about **the same file the diff came from** — the three returns
of `_finding_counts`, the absence of a consumer, the anchor `_trim_empty_fold`
uses — all of them visible in context Doug was not sent.

The one finding that landed (#1) is also the one whose premise Doug got
wrong while getting the conclusion right. Grading it `low` was correct.
Grading the two inventions `medium` was not, and it is the same
amplification #229's write-up flagged: a hallucinated premise carries the
severity of the consequence it imagines.

## Round 2 @ 7363b4b — Cleared, 0.22, four low

Doug re-read the branch after the fixes above. **Cleared**, four `low`
findings, one unvalidated deviation. One is real.

| # | rule | verdict | outcome |
|---|------|---------|---------|
| 1 | `reader:boundary-condition` | **wrong on reachability** | No change |
| 2 | `reader:off-by-one` | **right** | Fixed: `edge >= 0`, pinned by a test |
| 3 | `reader:fragile-string-parsing` | **already filed** | No change — #234, which Doug cites |
| 4 | `reader:count-mismatch` | **a hypothetical, not a defect** | No change |
| D1 | `beyond-ticket` (deviation) | **fair, and answered below** | No change |

**2 is real and Doug is exactly right about it.** `_whole_lines` used
`if edge > 0`, so a prefix whose only newline sits at index 0 returned the
half-written trailing line — precisely the fragment the helper exists to
remove. Unreachable from `render`, whose body opens with a title line, but
the point stands on its own terms: this is now a small pure helper with a
stated contract and its own tests, and a contract that fails on one input
is a trap for the next caller. `>= 0` returns the empty string, which is
the honest answer for "no whole line survived".

**1 is unreachable twice over.** `cut` clamps to 0 only when
`reserved + len(footer) > SUMMARY_LIMIT`; `reserved` is ~140 bytes and
`_footer` is built from three integers and two dates, so the footer would
need to be ~59,900 characters. It also predates this PR, and `post` slices
`summary[:SUMMARY_LIMIT]` before the call, so an oversized body cannot
reach GitHub even if the arithmetic did.

**4 describes a future change, not this one.** `_shown_findings` relies on
`counted` being in render order, which the two `strict=True` zips
establish at the point the bullets are built. `_trim_empty_fold` removes an
opener only when no bullet follows it, so it cannot reorder anything below
a surviving bullet. The invariant is documented in the helper's docstring;
if a later section splices bullets out of order, that is the change that
has to answer for it.

**D1 is fair.** The PR does more than name the dropped findings: it backs
the cut up to a line boundary, closes an orphaned `<details>`, and splits
the constant into `TRUNCATION_LEAD` / `TRUNCATION_NOTICE`. All three exist
so the notice can be *read* — an unterminated disclosure hides the notice
itself, and a notice welded to a half-word reads as a rendering fault
rather than a stated limit. The mirror stays byte-for-byte, which is what
ADR-0014 constrains. Recorded rather than dismissed: the deviation
instrument has not passed its derangement check, so it enters no score, and
this note is the whole of its effect.

## Round 3 @ c395ebc — Cleared, 0.24, three low

| # | rule | verdict | outcome |
|---|------|---------|---------|
| 1 | `reader:fragile-string-parsing` | **right about the coupling** | Fixed: `_trim_empty_fold` reads structure, not bullet syntax |
| 2 | `reader:off-by-one` | **right that the arithmetic is unpinnable** | Fixed the right way: the invariant is now asserted on six shapes |
| 3 | `reader:positional-string-matching` | **right, and it was reachable** | Fixed: `_shown_findings` matches whole lines |

None of the three is a live defect, and all three are worth acting on. That
is a different and more useful kind of finding than rounds 1 and 2
produced, and it is the first read in this file where every finding
survives.

**1.** `_trim_empty_fold` decided a disclosure was empty by testing its
tail for `"\n- "`. That quietly required three things `_fold` happens to do
today: never indent, always emit bullets, always keep the exact prefix.
A `_fold` that ever wrapped its body would have stripped an opener above
surviving findings and dropped them from the display **with no notice at
all** — this module's own defect, committed by the code that fixes it. The
test is now structural: is there any non-blank text after the
`</summary>` line.

**2.** Doug is right that the cap holds through a chain — the reserve
covers the widest reachable notice *and* a closer for every fold — and
right that relaxing the length test from `==` to `<=` removed the only
thing watching it. Pinning the arithmetic would pin the wrong thing. The
invariant is what matters, and `test_no_shape_renders_a_summary_over_the_cap`
now asserts it on six shapes that reach the cut from different directions,
including an overrun below the findings list and labels carrying literal
`<details>` tags.

**3.** The strongest of the three. `_shown_findings` searched for each
bullet as a substring from a forward cursor, so a finding whose
model-authored sentence embedded another finding's rendered bullet could
advance the cursor past a finding that was never displayed — an
attacker-chosen number in the one line this PR added to be trusted. It
matches whole lines now, which a label cannot forge: `_oneline` collapses
every newline out of it.

### What #234 costs, measured

The same read prompted a check of the adversarial shape. 400 findings whose
labels each carry 60 literal `<details>` inflate the fold reserve past the
whole budget, and the summary collapses to its notice and footer:

```
len: 213   (cap 60,000)   balanced: True
"400 of 400 findings are missing from the list above."
```

Bounded and honest — under the cap, tags balanced, shortfall true — but a
repository's own diff should not get to decide how much of Doug's check run
renders. Recorded on #234, which already has the fix that closes it.

## Round 4 @ 182af56 — Flagged, 0.30, one medium and two low

| # | rule | verdict | outcome |
|---|------|---------|---------|
| 1 | `reader:untrusted-input-string-parsing` | **right, and already filed** | No change — #234, with this exact measurement on it |
| 2 | `reader:fragile-string-parsing` | **wrong that it is unenforced** | Test added at the level where a break would cost something |
| 3 | `reader:weakened-test-assertion` | **right** | The reserve's waste is now bounded, not just its overrun |

**1 is the same finding as round 3's third, promoted to `medium` and
re-derived independently** — including the "400 of 400" number, which
appears in this file and in the diff Doug read. It is what pushed the band
to **Flagged** at exactly the flag line. The grading is defensible: a diff
that can suppress a check run's whole findings list is the most
consequential thing in this file. It is still #234's, not this PR's, and
#234 carries the measurement.

**2 is wrong on its own terms.** Doug says `_trim_empty_fold`'s safety
"rests on a label being unable to start a line — a coupling that is not
enforced anywhere". It is enforced, in `_oneline`, by the
`" ".join(text.split())` on its first line, and it has been tested since
before this PR (`test_oneline_neutralises_the_forms_that_have_side_effects
_in_a_pr_comment` asserts `"line\nbreak"` collapses). What was missing is a
test that ties the two modules together where a break would cost something,
so `test_a_label_cannot_forge_a_fold_opener` now renders a finding whose
label carries a full fake opener and asserts the finding below it survives.

That test also demonstrates #234 from the other side, and the docstring
says so: the tags do **not** balance, because this render never truncates
and `_close_details` never runs. The ordinary path is the exposed one.

**3 is right and the fix is not a return to `==`.** Doug's point is that
`<=` would pass an off-by-many in the reserve arithmetic that silently cost
findings — and it would, because wasted budget *is* dropped findings.
`test_the_reserve_does_not_waste_the_budget` bounds the waste at 512 bytes
across four fixture/footer combinations (observed: 90–253). Per-fixture,
not universal: the line-boundary backup can legitimately cost as much as
the longest rendered line.

## Where this stops

Four rounds, thirteen findings, six real. The rate is what makes it worth
recording: rounds 1 and 2 produced three inventions between them, rounds 3
and 4 produced none — every finding described the code as it is. What
changed between them is the code itself. Rounds 1 and 2 read a diff whose
new helpers were entangled with `render`; rounds 3 and 4 read small pure
functions with stated contracts, and Doug reasoned about those correctly
every time.

The loop is stopped here deliberately, not because it converged. Round 4's
only medium is #234, which no commit on this branch can close, and its two
lows were both about test coverage rather than behaviour. A fifth read
would be reading a diff of test files.
