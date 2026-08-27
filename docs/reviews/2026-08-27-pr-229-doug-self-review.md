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
