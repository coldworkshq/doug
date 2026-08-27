---
title: A merge may enqueue a derive job; the drain, not the merge, buys the model read
status: proposed
date: 2026-08-26
---

## Context

`_record_merge` at `api/doug/api.py:2503` opens with a law: "Start the
outcome-observation window on a merge, and nothing else. A merge must never
buy a model read: there is no new diff, and this is the one webhook branch
whose whole job is to note that the clock has started." The function checks
five facts — `merged_at`, `merge_commit_sha`, `base.ref`, `number`,
`base.repo.id` (the route has already refused a payload without an integer
`installation.id`) — and calls `store.enqueue_outcome_jobs`. A merge missing
any of the five is logged and answered `202`, because a `500` is a redelivery
loop over a body that will never carry them.

`_record_merge` is not the only writer of `outcome_jobs`. `worker.reconcile_outcomes`
exists because "a delivery this service 202s and then loses to a restart is
never retried," and it reaches the same `store.enqueue_outcome_jobs`
(`worker.py:1353`). `outcome_backfill` is not a third: it inserts 60-day
siblings for merges that already hold a 14-day row and never creates a merge
identity.

ADR-0022 makes a merge the event that creates a settled memory record. The
deriver that extracts the record needs to know a merge happened, needs the
diff, and needs a model. The law above says the webhook may do none of that,
and it is right: the webhook handler is latency-bound, redelivered on any
non-2xx, and shared with the review path that is Doug's production surface.

The integration plan budgets **two seam touches, ever**, on the review lane.
This record spends the first. The other is coldworks' dispatch call site
before `review.score_one`, at Stage 6.

## Decision

**The derive row is written where the outcome row is written.** The insert
lives inside `store.enqueue_outcome_jobs`'s transaction, so `_record_merge`
and `reconcile_outcomes` each produce an `outcome_jobs` row and a
`derive_jobs` row atomically, and the reconciler's docstring ("the ONLY other
path") is updated to say so. The row lives in the `doug` schema beside
`outcome_jobs`, keyed on the ledger's identity — `UNIQUE (github_repo_id,
pr_number, merge_commit_sha)`, the three columns of `uq_outcome_job` minus
`window_days` — with `installation_id` stored as a non-key column and
`merged_head_sha` nullable and non-key, exactly as on `outcome_jobs`. The
five-fact guard is shared by construction: a merge that cannot start the
outcome clock cannot start a derivation either. The row carries the claim
columns `review_jobs` and `outcome_jobs` already carry (`status`, `attempts`,
`started_at`, `finished_at`, `error`, `claim_generation`) and its own
`reclaim_stalled`, and a nullable `batch_id`.

**The row is not a read. The drain is.** A derive worker — a scheduled Cloud
Run Job from the promoted api image, like `outcome_worker`, never a webhook
background task — claims a bounded number of due rows per pass with `FOR
UPDATE SKIP LOCKED`, charges `reader._charge(installation_scope)` before
fetching the diff and parks the row on `SpendCapExceeded`, fetches the diff
with the installation token, calls the model with the diff delimited as
untrusted data, and emits `decision.derived` events into `memory.events` over
the producer wire (ADR-0024); the store materializes the records. The drain is
Python, in `doug-api`, because it calls a model and the language law puts
everything that calls a model in Python. The Go store never sees a diff. The
drain runs behind the review claim loop and `retry_unposted_comments`, for the
reason `api._startup_reconcile` gives: one installation-token limit, spent in
the order the lanes are worth. A rate-limited fetch is a transient the client
sleeps through (githubkit's default retry), distinct from the "diff
unavailable" record.

**The drain ships dark, and the eval comes before the seam.** The
pre-registered derivation eval is Gate B of Stage 0, run over this
repository's own merge history before any Stage 1 code exists (rule R2). The
seam pull request merges with the eval already green and an allowlist to flip;
the dark interval is the seam-to-flip window, not an unrun eval. While dark,
rows accumulate with `batch_id NULL`; the drain-on step stamps every
still-pending row with a batch id before the first claim, so the accumulated
rows drain as one batch, distinguishable from live derivations forever. The
stamp lives on `derive_jobs` only; a memory record joins to its batch on the
natural key, and the idempotency rule for merge-derived events excludes
`batch_id`. A merge that lands while the drain is dark costs exactly one
insert. The go-live flip is a founder-only item (rule R11) filed as a dated
issue when the seam pull request merges.

**Backfill means two things, and this record names both.** The dark-period
drain above is the first. The second is history: merges that predate the
migration or the installation are enumerated by `reconcile_outcomes` with a
lookback parameter (fixed at 14 days today, `worker.py:1177`) inserting
batch-stamped rows through the same shared path. Nothing polls GitHub for
merges outside that enumerator. Note that the reconciler heals nothing today —
102 startup runs, zero windows enqueued, because `pulls.get` returns no
`merge_commit_sha` for this repository's merges — so Gate A's "one healing
run" is also the first test of the shared path.

`_record_merge`'s docstring changes from "and nothing else" to "and one
derive row, which is not a read." The published denominator —
pre-registration §2.2's cleared-band join over `verdicts` and `outcome_jobs`,
for which `count(outcome_jobs WHERE status = 'done')` is the design-lock's
shorthand — is untouched: `derive_jobs` is its own table with its own status,
and a test pins §2.2's SQL against the schema and asserts it reads no column
of `derive_jobs`.

**This pull request is Stage 2's first item.** It merges only after Stage 1
exits and Gate A is green, in addition to Stage 1's contract-seam reviews.

## Rejected

**Deriving from `outcome_jobs` directly.** No new row, no seam touch. But
`outcome_jobs` is the published denominator, its status lifecycle is
pre-registered under a hash, and a `derived_at` column or a second status axis
on it is a change to the instrument that grades Doug. The clocks are separate
because the claims are.

**Inserting in the webhook function only.** The reconciler exists precisely
for the deliveries the webhook loses; a derive row written only on the live
path would leave every reconciled merge with an outcome clock and no
derivation, silently. One function, one transaction, both rows.

**Calling the model in the webhook.** The law forbids it for reasons that do
not soften: the handler is redelivered on any failure, so a model error
becomes a retry storm against a body that produces the same error; and a
reader call on the review path's thread is a review-path incident.

**Polling GitHub for merges.** The webhook already carries the five facts,
signed, and the reconciler already enumerates history. A poller is a second
source of the same event with its own failure modes and no delivery id to
dedup on.

**A Go drain.** The store is Go, so the drain could be. The language law says
no: the drain calls a model, and the thing that calls a model is the thing
that holds a graded roster row. The deriver's row is in Python's roster.

**A fork or bot gate on merges.** The review path gates *open* pull requests
from forks because anyone can open one. Nobody outside the tenant can merge
one; a merged fork or Dependabot pull request is the tenant's own commitment
under its own governance, and `_record_merge` applies no such gate by ruling
(pre-registration §2.4). Spend is bounded by the merge rate, the cap, and the
unique key, not by refusing to derive.

**Publishing a Pub/Sub message on merge.** ADR-0024 records why not: nothing
is measured, and the idempotency key the topic would need is the one the
table already has.

**Turning the drain on before the eval.** "It is only dogfood" is how a
0.463-precision instrument reaches a tenant. The eval is the gate, the
allowlist is the blast radius, and the batch stamp is the receipt.

## Consequences

- One of two seam touches is spent. The change is its own minimal pull
  request: the migration, the insert in `enqueue_outcome_jobs`, the docstrings,
  the denominator test, batched with nothing and rebased last. Andrew reviews
  it.
- A migration number is claimed at pull-request time — the next free after 17
  as of 2026-08-26, recomputed then. One open pull request holds a migration
  number at a time.
- A derive worker ships dark. A flag that is never flipped is a flag that is
  never tested, so the worker has a test that runs it against a fixture merge
  and asserts a `decision.derived` event to a fake producer wire, independent
  of the flag. A second test pins that every 14-day `outcome_jobs` row has a
  `derive_jobs` sibling.
- Redelivery is free: the second delivery of a merge conflicts on the unique
  index and no-ops, the same as `outcome_jobs`. A retried backfill inserts
  zero rows.
- Backfill is bounded by what the repositories still hold. A merge whose diff
  GitHub can no longer serve derives nothing and records why, as a distinct
  status from a transient rate limit.
- ADR-0004's ruling that the reader is in the scoring path is unchanged; this
  record adds a second model consumer charged against the same per-installation
  cap, and the cost-per-real-finding pilot (ADR-0018's unrun 20-PR baseline)
  must land before anyone claims what a derivation costs.
