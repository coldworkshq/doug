# M3 60-day outcome backfill design

**Status:** Design approved; written spec awaiting Andrew's review  
**Branch:** `m3-60-day-backfill`  
**Governing contract:** `docs/design/outcome-loop/design-lock.md:47` and
`docs/design/outcome-loop/publication-preregistration.md`

## Goal

Make the 60-day outcome population complete without creating a permanent
operator dependency:

1. every future merged PR starts its 14- and 60-day clocks atomically; and
2. one guarded, idempotent production catch-up creates the missing 60-day
   sibling for every existing prospective 14-day job.

The slice is complete only when the permanent writer is live, the historical
catch-up passes its invariants, all overdue 60-day work has been manually drained
under observation, and every completed job still has exactly one matching outcome.

## Why this is not only a SQL statement

The live webhook currently calls `store.enqueue_outcome_job` once and therefore
writes only the default 14-day row. A one-time `INSERT ... SELECT` would repair the
rows that exist today but immediately drift again on the next merge. Calling the
single-row function twice is also insufficient: a failure between calls can commit
one clock without the other.

The chosen contract is a one-time catch-up plus a permanent atomic dual-writer.
The alternatives are rejected:

- A recurring operator backfill leaves correctness dependent on an external
  schedule and permits the 60-day denominator to lag silently.
- A database trigger gives strong pairing but hides a product rule in Postgres,
  diverges from the repository's SQLite test environment, and makes the webhook's
  behavior harder to understand.

`api/scripts/backfill_ledger.py` is unrelated. It loads the public research probe
corpus into verdict, outcome, and read tables; it must never be used for this
prospective tenant-job catch-up.

## Permanent writer

Add a store operation that accepts one merge identity and a fixed collection of
windows. `_record_merge` calls it with `(14, 60)`.

The operation builds both rows from the same values:

| Field | 14-day row | 60-day row |
|---|---|---|
| `installation_id` | copied from webhook | identical |
| `github_repo_id` | copied from webhook | identical |
| `pr_number` | copied from webhook | identical |
| `merge_commit_sha` | copied from webhook | identical |
| `merged_at` | copied from webhook | identical |
| `base_ref` | copied from webhook | identical |
| `window_days` | `14` | `60` |
| `due_at` | `merged_at + 14 days` | `merged_at + 60 days` |
| initial state | pending, zero attempts | pending, zero attempts |

Both inserts run in one transaction. The insert targets the existing unique
identity `(installation_id, github_repo_id, pr_number, merge_commit_sha,
window_days)` with conflict-specific `ON CONFLICT DO NOTHING`. It must not use an
untargeted conflict handler that could hide a different future integrity error.

This produces three required behaviors:

- a new merge commits both clocks or neither;
- a GitHub redelivery creates no duplicate rows; and
- a redelivery encountering a legacy 14-day-only row inserts the missing 60-day
  sibling, healing rather than preserving the partial state.

The existing single-window function may remain as a compatibility wrapper for
tests or other explicit callers, but the webhook must use the plural atomic
operation.

## Catch-up population

The source population is every `outcome_jobs` row where:

- `window_days = 14`;
- `installation_id` matches a row in `installations`; and
- no row exists with the same unique merge identity and `window_days = 60`.

Installation state does not narrow the population. Active, suspended, and deleted
installations all represent real prospective history. Excluding inactive records
would remove shipped work from the denominator after an uninstall.

Requiring registry membership excludes CLI, orphaned, and research/sentinel data
without trusting a display label or the currently undefined
`:RESEARCH_SENTINEL` placeholder. The pre-registration queries must adopt the same
structural real-installation predicate so the writer and publication population
cannot disagree.

The catch-up is one `INSERT ... SELECT` over stored merge facts. It copies the
source identity, `merged_at`, and `base_ref`; sets `window_days = 60`; computes
`due_at = merged_at + 60 days`; and initializes a pending, zero-attempt job. It does
not copy the 14-day status or mutate any existing job, verdict, or outcome.

## Operator command

Add a checked-in command dedicated to this operation, separate from the research
backfill. Its interface is intentionally two-phase:

```bash
uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --dry-run

uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --apply \
  --expect-missing <DRY_RUN_COUNT> \
  --manifest <ABSOLUTE_JSON_PATH>
```

`--from-gcp` follows the existing repository convention: the operator first runs a
Cloud SQL Auth Proxy on `127.0.0.1:5433`; the command reads the database secret and
rewrites its Cloud SQL socket URL to the proxy. A direct `DATABASE_URL` remains
available for tests and non-GCP environments.

Dry-run is read-only and reports:

- eligible 14-day rows;
- existing 60-day siblings;
- missing siblings;
- missing siblings whose 60-day due date has already elapsed;
- counts by installation and repository; and
- any existing pair whose `merged_at`, `base_ref`, or expected 60-day `due_at`
  disagrees.

Apply requires `--expect-missing`. It recomputes the count inside the write
transaction and aborts without mutation if the value has changed since dry-run.
The dual-writer must already be deployed, so normal new merges cannot increase the
missing count during this interval.

The command writes the exact inserted unique identities to the required manifest
and flushes the file before committing the database transaction. A manifest-write
failure therefore rolls back the insert. A failed database commit can leave a
harmless manifest naming rows that do not exist; the post-run audit distinguishes
that state. Apply refuses a manifest path that already exists, so an earlier audit
artifact can never be silently overwritten.

The command is idempotent. A second dry-run after success reports zero missing and
a repeated apply with expected zero inserts nothing.

## Transaction invariants

Before apply, fail if any existing registered-installation 14/60 pair disagrees on
`merged_at`, `base_ref`, or the derived 60-day due date. The catch-up must not hide
pre-existing corruption behind `ON CONFLICT DO NOTHING`.

After the insert and before commit, require all of the following:

1. Every eligible 14-day row has exactly one 60-day sibling.
2. Every registered-installation 60-day row has a 14-day sibling.
3. Paired rows have identical stored merge facts.
4. Every 60-day `due_at` is exactly `merged_at + 60 days`.
5. Every newly inserted row is pending with zero attempts, no lease timestamps, no
   error, and claim generation zero.

Any failure aborts the transaction and exits non-zero.

## Rollback boundary

Rollback is available only after catch-up commit and before the manual adjudicator
execution. It reads the exact manifest and may delete only rows that are still
untouched: `status = 'pending'`, `attempts = 0`, `claim_generation = 0`, and no
start, finish, or error fields. If any manifest row is missing or has changed, the
rollback refuses the entire operation rather than deleting a partial set.

The daily Scheduler must be paused before apply and confirmed paused before the
transaction begins. Otherwise it can claim an overdue inserted row between commit
and the rollback decision. The operator must close the maintenance window in one
of two ways: roll back the untouched manifest rows and resume the Scheduler, or
manually execute and audit the Job and then resume the Scheduler. There is no valid
handoff state with a committed catch-up, an unreviewed execution, and the Scheduler
still paused.

Once adjudication starts, the ledger is append-only operational evidence. A clone
or GitHub failure uses the existing retry/failure machinery; it is not a reason to
delete jobs or outcomes.

## Pre-registration lock

The current pre-registration is `DRAFT v7` and states that the live path writes
only 14-day rows while a second writer supplies 60-day rows. This slice changes
that mechanism and must update the document before it can be locked:

- future merges atomically receive both clocks;
- the one-time backfill supplies only the historical missing siblings;
- real-installation membership replaces the undefined research-sentinel
  placeholder in publication predicates; and
- the 60-day population remains an independent denominator, never summed with the
  14-day population.

After those changes, remove `DRAFT`, mark the pre-registration locked, and compute
its new SHA-256. `deploy/gcp.sh deploy` must promote the API and redeploy
`doug-adjudicator` from the exact same immutable image with that locked hash before
the catch-up or any real adjudication. The deployed `DOUG_PREREG_HASH` must be
verified directly before proceeding.

## Production runbook

The checked-in runbook uses this order:

1. Merge the dual-writer, command, locked pre-registration, and documentation.
2. From a clean checkout of that merged `origin/main` commit, deploy the API; allow
   `gcp.sh deploy` to redeploy the exact-image adjudicator.
3. Verify API and Job image equality and the Job's locked pre-registration hash.
4. Start a persistent Cloud SQL Auth Proxy session.
5. Run dry-run and preserve its complete output outside a temporary SQL session.
6. Review per-installation/repository counts and all disagreement checks.
7. Pause `doug-adjudicator-daily` and verify its state before apply.
8. Apply with the exact missing count and a new absolute manifest path.
9. Run the post-insert invariants independently; all must return zero violations.
10. Manually execute `doug-adjudicator --wait` so already-overdue rows drain while
   observed. The execution may also process other legitimately due pending work.
11. Preserve the execution summary and run the complete identity audit: every
    `done` job has exactly one matching outcome on installation, repository, PR,
    merge SHA, and window.
12. Confirm a second dry-run reports zero missing siblings.
13. Resume `doug-adjudicator-daily` and verify its enabled state.

Cloud SQL Studio temporary tables are forbidden for cross-command snapshots. It
does not guarantee backend-session reuse. The command manifest and durable output
are the audit artifacts.

## Tests

Tests encode the reason the population matters, not only the number of inserts.
They must prove:

- a merged webhook creates exactly one 14-day and one 60-day row with shared merge
  facts and exact due dates;
- redelivery creates no duplicates;
- redelivery heals a pre-existing 14-day-only row;
- an injected error while writing either window commits neither row;
- dry-run does not mutate the ledger;
- apply inserts only missing 60-day siblings for registered installations;
- active, suspended, and deleted installations are eligible;
- CLI, orphaned, and research-shaped rows are excluded;
- mismatched existing pairs fail loudly;
- repeated apply inserts nothing;
- stale `--expect-missing` aborts without mutation;
- manifest failure aborts the transaction;
- manifest rollback refuses a row that has started adjudication;
- overdue backfilled rows are immediately claimable while younger rows are not;
  and
- a mixed 14/60 repository batch preserves one completed-job-to-one-outcome
  identity.

The full API suite is the merge gate. The clean baseline for this branch is 785
passing tests and one existing Starlette deprecation warning.

## Documentation scope

The implementation PR updates only the documents whose claims change:

- the new production runbook;
- publication pre-registration;
- design lock;
- outcome-loop roadmap and architecture;
- reviewing guidance; and
- `HANDOFF.md`.

The PR must distinguish a prose correction from a decision change. Atomic
dual-write is a newly approved implementation decision that replaces the earlier
permanent 14-day-only live path; the two windows, independent denominators, and
historical `INSERT ... SELECT` remain unchanged product commitments.

## Completion criteria

The slice is complete only when:

- the full API suite passes with no skipped failures;
- the PR is merged;
- the API and adjudicator are deployed from the same immutable image;
- the adjudicator carries the verified locked pre-registration hash;
- catch-up dry-run, apply, and post-insert invariants are preserved;
- a manually observed Job execution drains the overdue population or reports an
  evidenced zero overdue count;
- every completed job has exactly one matching outcome;
- a final dry-run reports zero missing 60-day siblings;
- the daily Scheduler is verified enabled again; and
- the handoff records what was verified in production rather than predicting it.
