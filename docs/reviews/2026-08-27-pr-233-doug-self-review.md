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
