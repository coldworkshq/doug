# Task 6i report: bounded apply write-stall

Status: complete

## Delivered

Added one operator paragraph immediately between the final paused/quiescence
checks and the unchanged apply invocation in the active 60-day backfill
runbook. It records that merge-webhook database writes can wait while apply
holds its correctness locks, a timed-out request may be redelivered, and apply
must begin immediately after those checks during a low-traffic maintenance
window. It states that the locks protect the complete eligibility predicate and
must not be weakened, and directs any apply error to rollback and the existing
§5 failure classification.

The wording does not claim that the API service, webhook delivery system, or
whole database is paused.

## Verification

`git diff --check` completed without output before the documentation commit.
Self-review confirmed the paragraph is immediately before the apply command,
does not alter a runbook command, and covers each required contention and
recovery boundary.

Committed the runbook change as `f157643` (`docs: explain apply write stall`).
No production, command, PR, push, or external-system action occurred.

## Round 1: recovery-boundary correction

The apply paragraph now says that an exception while the guarded database
transaction is active rolls it back, while a failed or unverifiable apply may
nevertheless have committed. It preserves artifacts and directs the operator
to §5, which already distinguishes no-commit from committed-untouched states.
The apply command is unchanged.

`git diff --check` completed without output before committing the correction as
`013f339` (`docs: clarify apply recovery outcomes`).
