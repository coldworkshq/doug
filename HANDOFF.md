# HANDOFF — doug

State:    review
Next:     Merge #9, #11, #12; then the queue-page rendering for `read-truncated`
          (deferred out of #12 to avoid stacking on #11).
Blockers: Anthropic balance empty — no diff has been read since it ran out.
          Any re-run of the reader (prompt v2, budget experiment) waits on it.

Decisions this session:
- The lema#643 review feedback is a truncation bug, not a prompt bug — the
  reader was shown 30,000 of 68,430 chars (44%). The clamp that falsifies
  finding #1 sat 1,248 chars past the cut; the tenancy leak it missed sat
  2,266 past; the mutation-verified test file was never sent.
  — rejected: applying the pasted prompt patch as written, which would have
  instructed the model to "open the callee" and "read the tests" for code it
  never received, producing claimed compliance instead of real compliance.
- Coverage is observed and recorded, but nothing sent to the model changed.
  — why: DIFF_BUDGET and _user_text are frozen probe parameters (ADR-0002);
  11% of the sentry corpus and 21% of grafana were truncated at 30k, so
  raising the budget moves the input for ~1 in 6 reads and is a new
  experiment, not a tweak. — rejected: quietly raising DIFF_BUDGET.
- Coverage lands in a new `reads` table, not columns on `verdicts`.
  — why: create_all() adds tables, never columns; new columns would exist in
  tests and silently not in production. — rejected: ALTER-on-startup.
- The notice is `read-truncated`, outside the `reader:` namespace.
  — why: patterns.from_rule only canonicalises `reader:*`, so a meta-fact
  about the read can never be counted as a defect pattern in /v1/patterns.

Pointers:
- branch `read-coverage` → PR #12. api/doug/{reader,store,review,api}.py,
  api/tests/test_coverage.py (9 tests, built from #643 at a076c15d).
- Open PRs: #9 (WIF propagation retry), #11 (queue links + severity), #12.
- PRE-EXISTING BREAK on main: tests/test_workflow_summary.py 2 failures —
  the embedded summary script in both doug-review.yml files has an
  IndentationError, so that CI step is broken now. Not mine, not fixed.
- Stashed: `git stash list` → repoint dashboard queue lemahq/lema →
  drewjst/doug (was uncommitted on queue-polish, includes docs/superpowers/plans/).
- Feedback items 3 and 4 (invariant-vs-mechanism, severity = impact ×
  confidence) are real and unbuilt — they need a frozen v2 prompt and a
  validation run, so they wait on credits.
