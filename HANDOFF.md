# HANDOFF — doug

State:    review
Next:     Both PRs pushed with review fixes applied. Merge #12 and #13;
          then queue-page rendering for `read-truncated`.
Blockers: Anthropic balance empty — no diff has been read since it ran out.
          Any reader re-run (prompt v2, budget experiment) waits on it.

Decisions this session:
- The lema#643 review feedback is a truncation bug, not a prompt bug — the
  reader was shown 30,000 of 68,430 chars (44%). The clamp that falsifies
  finding #1 sat 1,248 chars past the cut; the tenancy leak it missed sat
  2,266 past; the mutation-verified test file was never sent.
  — rejected: applying the pasted prompt patch as written, which would have
  told the model to "open the callee" and "read the tests" for code it never
  received — claimed compliance, not real compliance.
- Coverage is observed and recorded; nothing sent to the model changed.
  — why: DIFF_BUDGET and _user_text are frozen probe parameters (ADR-0002),
  and 11% of the sentry corpus / 21% of grafana were truncated at 30k, so
  raising the budget moves the input for ~1 read in 6 — a new experiment.
  — rejected: quietly raising DIFF_BUDGET.
- Coverage lands in a new `reads` table, not columns on `verdicts`.
  — why: create_all() adds tables, never columns; new columns would exist in
  tests and silently not in production. — rejected: ALTER-on-startup.
- The notice is `read-truncated`, outside the `reader:` namespace.
  — why: patterns.from_rule only canonicalises `reader:*`, so a meta-fact
  about the read can never be counted as a defect pattern by /v1/patterns.
- The workflow-summary test passed for the wrong reason — it fed python3 the
  YAML indentation the runner strips, which only 3.14 tolerates.
  — why fix rather than ignore: red locally (system python3 is 3.9.6), green
  in CI, which teaches you to ignore it. — rejected: dedent alone, which
  hides the deeper-indent case; raw indentation is now asserted separately
  and mutation-verified.
- Ran an xhigh code review against #12 and #13; 10/12 candidates confirmed.
  Fixed all 10 on read-coverage: /v1/score/read and the intent tier both
  bypassed coverage entirely (silent partial reads in exactly the two paths
  PR #12 exists to close); file_cut misattributed a fully-sent file when the
  budget landed on a file boundary (fixed by comparing against
  CHUNK_SEPARATOR, not just presence); a save_read failure after a
  successful save_review was reported as "ledger-unavailable" (fixed by
  folding coverage into save_review's existing transaction — now atomic,
  not two round trips); backfill_ledger.py left ~650 seed-corpus rows with
  no reads row — fixed exactly, not approximately, since HarvestedPR's
  cached file_details still carries every patch (verified: 0/10000 sentry
  rows missing it), so coverage for the whole corpus is reconstructed from
  the same harvest cache rf_kamei.load() already reads, not guessed.
  diff_chunk() is now the one place the "### path (status, +a/-d)" shape is
  built; review.py and reader.py both use it instead of two hand-written
  copies plus a third regex. 4 new regression tests, incl. the exact
  boundary-misattribution repro from the review.
  — rejected: a schema change to make Coverage.diff_chars nullable for the
  ~11-21% of backfilled PRs that were truncated with no way to recover the
  true original length — file_details being fully populated made this
  unnecessary; every backfilled row now has an exact reads row or none.
- Fixed #13's own review finding: its new indentation-fidelity test's regex
  stopped at the wrong closing quote (matched the `"` opening
  `"$GITHUB_STEP_SUMMARY"` instead of the -c block's real terminator) —
  passed only because the swallowed text happened to share the opener's
  indent. Both tests now share one `_SUMMARY_BLOCK` regex anchored past the
  correct ` >> "$GITHUB_STEP_SUMMARY"` terminator, so the two can't drift
  apart again. Mutation-verified: the fix still catches a 2-space
  re-indent; spot-checked the captured body no longer contains
  `GITHUB_STEP_SUMMARY`.

Pointers:
- `read-coverage` → PR #12: api/doug/{reader,store,review,api}.py,
  api/scripts/backfill_ledger.py, both doug-review.yml copies (render
  intent_notice) + api/tests/test_coverage.py (13 tests). Pushed.
- `workflow-summary-test-fidelity` → PR #13: api/tests/test_workflow_summary.py
  (_SUMMARY_BLOCK shared anchor). Pushed.
- Open PRs: #12, #13, both with their own xhigh-review findings fixed.
  (#9, #10, #11 merged.)
- doug-review on drewjst/doug succeeds; the summary step renders.
- Stashed: `git stash list` → repoint dashboard queue lemahq/lema →
  drewjst/doug (was uncommitted on queue-polish; includes
  docs/superpowers/plans/2026-07-30-close-live-auth-holes.md).
- Feedback items 3 and 4 (invariant-vs-mechanism; severity = impact ×
  confidence) are real and unbuilt — they need a frozen v2 prompt and a
  validation run, so they wait on credits.
- #643 had FOUR reader findings, not three: `reader:brittle-test-assertion`
  (low) is unscored in the feedback, and it is about a test file — evidence
  the reader does read tests it is given.
