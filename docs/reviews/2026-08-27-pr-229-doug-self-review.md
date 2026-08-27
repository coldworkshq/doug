# Doug vs Doug — PR #229 @ 3eb5776

A calibration record of an unusual shape: Doug reviewing a change to Doug's
own check-run renderer. The prior entries in this directory compare an
external review with Doug's; this one has no external half, so the training
signal is the disposition alone — which of Doug's five findings survive
contact with the code they describe.

PR #229 gives each reader finding a link to the file it names, orders the
findings list by severity, and folds `low` findings and the standing notes
behind `<details>`. It touches `check_run.py`, `worker.py`, `store.py`, and
two test files.

Doug read the diff (`validated diff reader`, risk 0.42, **Flagged**, one
high, two medium, two low, plus one unvalidated deviation).

**Headline: the one `high` is a false positive, and it is a textbook
instance of #175 — a finding about code Doug never received.** Of the
remaining four, three were real and are fixed here; one is real, bounded,
and accepted with the reasoning recorded.

## Disposition

| # | rule | severity | verdict | outcome |
|---|------|----------|---------|---------|
| 1 | `reader:missing-column-in-query` | high | **wrong** | No change. The SELECT is whole-table; a comment now says so |
| 2 | `reader:unverified-external-rendering` | medium | **right** | Accepted, with a documented chain and a two-line revert path |
| 3 | `reader:api-contract-change` | medium | **right** | The unguarded boundary is now pinned by a test |
| 4 | `reader:link-target-mismatch` | low | **right** | Such paths are no longer linked at all |
| 5 | `reader:stale-derived-identifier` | low | **half right** | The silent drop now logs; the stale slug is #228's, not this PR's |
| D1 | `missing-from-pr` (deviation) | low | **right, already disclosed** | No change. Filed as #230 before the read ran |

## 1. The high finding is wrong, and predictably so

Doug claimed `_verdict_bundle` reads `r["file"]` while the diff changes no
SELECT, and concluded `KeyError` on every receipt, run detail, and repair
render.

The query is `select(findings)` — the whole table. Every column is
projected, `file` included, and has been since the column was added:

```
['id', 'verdict_id', 'rule', 'label', 'weight', 'file', 'severity', 'hunks']
```

The reasoning was sound and the premise was invented. Doug was sent a diff,
the diff contains the new key and no SELECT, and the true statement — "the
SELECT four lines above this hunk names no columns" — is in the file rather
than in the diff. This is exactly the failure #175 records: *findings cite
code doug never read*. It earns a `high` because the consequence Doug
imagined is severe, which is how a hallucinated premise gets amplified
rather than damped by severity grading.

Worth noting for the loop: **no test could have caught this, because there
was nothing to catch.** 1,674 tests passed on the code Doug called broken.
A reviewer acting on the finding would have gone looking for a bug that
does not exist. The fix is therefore not to the code but to the next
reader: the projection now says out loud that it is whole-table, so the
natural misreading of the diff is answered where the misreading happens.

## 2. The rendering risk is real and is accepted, not resolved

Doug is right that the `<details>` folds are unverified on the check-run
surface, and right that the handoff said so. It cannot be verified before
merge: the check run only exists once this deploys, and a read-only sweep
of `dorny/test-reporter`, `mikepenz/action-junit-report`,
`EnricoMi/publish-unit-test-result-action`, and eight large repositories
turned up no live check run carrying `<details>` to inspect.

What supports it is a documented chain rather than an anecdote:

1. GitHub's REST documentation for a check run's `output.summary` says it
   *"Can contain Markdown."*
2. GitHub renders Markdown through GFM plus its own sanitization allowlist,
   and `details` and `summary` are on that allowlist — GitHub's stylesheets
   ship a `cursor: pointer` rule for `summary`.
3. `dorny/test-reporter` composes its check-run output with
   `<details><summary>Expand for details</summary>` and caps it at 65535
   bytes, which is `output.summary`'s own limit. It is posting that HTML
   through the Checks API at scale.

The bounded downside is what makes acceptance reasonable rather than
optimistic. If the tags render literally, the PR comment — the surface
ADR-0014 treats as primary — is unaffected, the check run degrades
cosmetically without losing information, and the revert is the two `_fold`
calls in `render`. The deploy settles it.

## 3. The contract finding found a genuinely unguarded boundary

Doug is right that adding `file` to the bundle dict rests on every consumer
wrapping it in a `Reason`, where `exclude=True` keeps it off the wire, and
that a consumer serialising the dict directly would publish an extra key
that a strict client rejects.

The finding is right and its scope was worth checking. Only one client
validates exactly: `web/lib/session-api.ts` checks a reason against an exact
key set, and run detail has been pinned against it since the field existed.
The receipt's client (`web/lib/receipt-shape.ts`) types reasons as
`unknown[]`, so an extra key there would have shipped in silence — the
worse of the two, and the unguarded one.

`test_receipt_reason_carries_exactly_the_keys_run_detail_does` now pins it.
Both guards were mutation-checked: removing `exclude=True` from
`Reason.file` fails both. The `VERDICT` fixtures in `test_api.py` and
`test_worker.py` now carry a `file` and a `severity`, so the guards exercise
a real value rather than passing over a `None`.

## 4. The link/text mismatch was real

`_path_span` must drop a backtick and a `]` — one closes the code span, the
other ends the link text — while the href was built from the raw path. For
such a path a reader would have been shown one filename and sent to another.

Those paths are no longer linked at all. A link that lies about its own
destination is worse than the plain span that replaces it.

The same finding's second half — that `_UNLINKABLE_PATH` admits
backslash-bearing paths and yields 404 links — is declined, and the reason
is in the code. A backslash is legal in a POSIX filename, git reports paths
with forward slashes on every platform, and a 404 inside the reader's own
repository at the commit Doug read is the documented floor of the whole
function, visible rather than silent.

## 5. The stale-identifier finding is half right

The silent half was correct and is fixed: `_source` returning `None` dropped
every link on a summary without a word, which looks identical to a read that
named no files. It now writes a stderr line naming the job and the
unusable slug.

The stale half is real but is not this PR's. `_source` derives the slug from
whatever the webhook delivered for that job, so a fresh read always links the
current name; only a repair long after a transfer links the old one and leans
on GitHub's redirect. That is the same reliance `pr_comment`'s receipt links
already carry, and it is #228's subject rather than a defect introduced here.
The docstring now says so and names the issue.

## What this says about the instrument

Two things, both worth carrying into the loop:

- **Severity amplified a hallucination.** The single `high` was the single
  wrong finding, and it was wrong about a premise rather than about a
  judgment. A severity is a claim about consequence-if-true, and nothing in
  the pipeline discounts it by how much of the cited code the reader
  actually saw. #175 is the standing issue; this is a clean instance of it
  on a diff Doug was not truncated on, which makes it a stronger data point
  than a truncated read would be.
- **The three low-and-medium findings were all worth acting on**, and two of
  them named things the author had considered and left implicit. Doug is
  better here at finding unstated reasoning than at finding defects.

## Round two — Doug reading the fixes @ 5983ef9

The fixes were themselves reviewed. Risk fell 0.42 → 0.32, and the read
returned three medium and one low. Two were the already-dispositioned #2 and
#3 above, unchanged. The two new ones split the same way the first round did:
one hallucinated premise, one real defect.

| # | rule | severity | verdict | outcome |
|---|------|----------|---------|---------|
| 6 | `reader:missing-import` | medium | **wrong** | No change. `import sys` is at `worker.py:23` |
| 7 | `reader:empty-visible-section` | low | **right, and mine** | An all-low list no longer folds |

### 6 is the same false positive as 1, in a different file

Doug claimed `_source` writes to `sys.stderr` while the diff adds no
`import sys` to `worker.py`, and concluded `NameError` on the degraded path.
`import sys` is at line 23, outside the diff. `worker.py` has been printing
to stderr for its whole life.

Two rounds, two `medium`-or-higher findings, both from the same mechanism:
a true statement about the diff, an invented statement about the file, and
a severity priced on the invented one. Both would also have been caught by
tooling that already runs — the first by 1,674 passing tests, the second by
`ruff`'s F821, which fails CI on an undefined name. That is a sharper
version of #175 than "cites code it never read": **the reader is reporting
conditions that the repository's own gates make unreachable**, and it has no
way to know a gate exists.

### 7 is a real defect, and the best finding of either round

When every finding is graded `low`, `_triage` returned an empty lead, so
`### Findings` rendered as a heading, a blank line, and a collapsed
disclosure — beneath a **Flagged** title. A reader skimming that sees a
Findings section with nothing in it.

This is #109's misreading reached from the opposite direction: that one put
a "nothing survived" notice under a Flagged title and it read as a live
defect; this one puts live defects under a Flagged title and they read as
nothing. It was introduced by the fold in this PR, it was not caught by any
of the eleven tests written for the fold, and the author considered the
all-low case while writing `_triage` and judged it acceptable. Doug was
right and the author was wrong.

The rule is now "everything below the lead folds" rather than "every low
finding folds": a fold defers the less-actionable half of a list, and an
all-low list has no other half to defer to.

### What round two adds to the instrument's record

The first round's headline — that severity amplified a hallucination — holds
with a second instance and gains a sharper form: both wrong findings
described states that CI or the test suite makes impossible, which is a
class of false positive a diff-only reader cannot self-check for. Filed as
#232, because a paragraph here is not a tracker.

Against that, finding 7 is the strongest argument in this document for the
instrument. It is a defect in new code, invisible to the tests written for
that code, in a module whose whole subject is how a summary is misread — and
it was found by the reader, in the same read that invented a `NameError`.

## Round three — Doug reading the fixes @ 58261b3

**No false positives.** The two the previous rounds produced did not recur,
`reader:empty-visible-section` is gone (fixed), and the two new findings are
both real and both low. Risk held at 0.32; the deviation tier repeated the
already-disclosed line-links gap and named #230 itself.

| # | rule | severity | verdict | outcome |
|---|------|----------|---------|---------|
| 8 | `reader:unvalidated-model-text-in-markup` | low | **right** | In-vocabulary severities are emitted from `_SEVERITY_ORDER`; the rest are capped and unbolded |
| 9 | `reader:output-size-budget` | low | **right, and quantified** | The link carries `head_sha[:12]`, not 40 |

### 8 — the bold span was the one place model text still led

`_bullet` rendered `reason.severity` verbatim inside `**...**`, with
`_oneline` sanitisation and no cap, while paths beside it were capped at 400
characters. `Reason.severity` is `str | None` on the model and validated by
nothing, so its length was the model's to choose.

Two changes, and they are separate arguments:

- **In vocabulary, nothing is echoed.** `**high**` is now emitted from
  `_SEVERITY_ORDER`. `_grade` had already lowercased and stripped the value
  to pick the bucket, so echoing the raw string only carried the model's
  casing and whitespace into the most load-bearing span in the list.
- **Out of vocabulary, the text is capped at 24 characters and loses the
  bold.** It is not dropped: `_finding_counts` degrades its own cell to a
  plain count on exactly this input and promises the raw severity still
  reaches the reader in the list. Bold is a ranking signal, and Doug cannot
  rank a severity it does not recognise, so keeping the emphasis would have
  claimed more than the read established.

### 9 — the size finding is right, and smaller than it reads

Doug is right in direction: every finding now carries a URL that did not
exist before, and those bytes are spent against `SUMMARY_LIMIT`, where
overrunning costs findings (#181). The magnitude is worth stating rather
than leaving to intuition. For a representative finding — a 33-character
rule, a 24-character path, a 180-character label:

| | bytes |
|---|---|
| Old bullet | 232 |
| New bullet, 40-char SHA | 373 |
| New bullet, 12-char SHA | 345 |
| Delta per finding, as shipped | **+113** |
| Findings before the delta alone consumes `SUMMARY_LIMIT` | ~530 |

So the regression is real and the practical exposure is small: a read
returning tens of findings spends single-digit kilobytes of a 60,000-byte
budget. The 28 bytes the abbreviated SHA saves are not the difference
between fitting and not — they are taken because they are free. GitHub
resolves any unambiguous prefix, `_since_section` already identifies a read
by `sha[:12]` and `pr_comment` by `[:7]`, so the full 40 was the odd one out
on a surface that never displays more than 12.

What this does not fix is #181 itself: an overrun still drops findings
without naming how many. That is unchanged by this PR and is the issue to
act on if the budget ever binds.

### Where the three rounds leave the instrument

Nine findings across three reads of one PR:

| | count |
|---|---|
| Real, acted on | 5 |
| Real, accepted with reasons recorded | 1 |
| Half right | 1 |
| **False positives** | **2** |

Both false positives came from the same mechanism and are #232. Both
appeared in the first two rounds; the third round, reading the largest diff
of the three, produced none. One finding — `reader:empty-visible-section` —
was a defect in new code that eleven tests written for that code did not
catch and that the author had explicitly considered and waved through. On
this PR the instrument paid for itself on that one finding alone.
