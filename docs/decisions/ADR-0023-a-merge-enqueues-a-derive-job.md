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
five facts — when it shipped, what shipped, where, which pull request, whose
repository — and enqueues one `outcome_jobs` row. A merge missing any of the
five is logged and answered `202`, because a `500` is a redelivery loop over a
body that will never carry them.

ADR-0022 makes a merge the event that creates a settled memory record. The
deriver that extracts the record needs to know a merge happened, needs the
diff, and needs a model. The law above says the webhook may do none of that,
and it is right: the webhook handler is latency-bound, redelivered on any
non-2xx, and shared with the review path that is Doug's production surface.

The integration plan budgets **two seam touches, ever**, on the review lane.
This record spends the first. The other is coldworks' dispatch call site
before `review.score_one`, at Stage 6.

## Decision

The `closed` branch of the webhook enqueues **one more row and nothing more**:
a `derive_jobs` row in the `doug` schema, beside `outcome_jobs`, keyed on the
same five facts plus `merged_head_sha`, with the same `UNIQUE
(installation_id, github_repo_id, pr_number, merge_commit_sha)` idempotency
shape. The five-fact guard is shared: a merge that cannot start the outcome
clock cannot start a derivation either. The row carries a `batch_id`, `NULL`
for live merges and stamped for backfill.

**The row is not a read. The drain is.** A worker claims due rows with `FOR
UPDATE SKIP LOCKED`, fetches the diff with the installation token, calls the
model, and writes the derived records to the memory store over ADR-0022's
wire. The drain is Python, in `doug-api`, because it calls a model and the
language law puts everything that calls a model in Python. The Go store never
sees a diff.

The drain is **dark until Stage 2's eval passes.** Rows accumulate; nothing
reads them; no tenant-visible record exists. When the pre-registered
derivation eval clears its bars, the drain turns on for the allowlist, and the
accumulated rows are drained as a batch-stamped backfill, distinguishable from
live derivations forever. A merge that lands while the drain is dark costs
exactly one insert.

`_record_merge`'s docstring changes from "and nothing else" to "and one
derive row, which is not a read." The published denominator — `count(outcome_jobs
WHERE status = 'done')`, pre-registration §2.2 — is untouched: `derive_jobs`
is its own table with its own status, and a test pins that the denominator
query reads no column of it.

## Rejected

**Deriving from `outcome_jobs` directly.** No new row, no seam touch. But
`outcome_jobs` is the published denominator, its status lifecycle is
pre-registered under a hash, and a `derived_at` column or a second status axis
on it is a change to the instrument that grades Doug. The clocks are separate
because the claims are.

**Calling the model in the webhook.** The law forbids it for reasons that do
not soften: the handler is redelivered on any failure, so a model error
becomes a retry storm against a body that produces the same error; and a
reader call on the review path's thread is a review-path incident.

**Polling GitHub for merges.** The webhook already carries the five facts,
signed. A poller is a second source of the same event with its own failure
modes and no delivery id to dedup on.

**A Go drain.** The store is Go, so the drain could be. The language law
says no: the drain calls a model, and the thing that calls a model is the
thing that holds a graded roster row. The deriver's row is in Python's roster.

**Publishing a Pub/Sub message on merge.** ADR-0024 records why not: nothing
is measured, and the idempotency key the topic would need is the one the
table already has.

**Turning the drain on before the eval.** "It is only dogfood" is how a
0.463-precision instrument reaches a tenant. The eval is the gate, the
allowlist is the blast radius, and the batch stamp is the receipt.

## Consequences

- One of two seam touches is spent. The change is its own minimal pull
  request: the migration, the insert, the docstring, the denominator test,
  batched with nothing and rebased last. Andrew reviews it although nothing
  else in Stage 1 needs founder review.
- A migration number is claimed at pull-request time — the next free after 17
  as of 2026-08-26, recomputed then. One open pull request holds a migration
  number at a time.
- The worker gains a drain that ships dark. A flag that is never flipped is a
  flag that is never tested, so the drain has a test that runs it against a
  fixture merge and asserts a write to a fake store, independent of the flag.
- Redelivery is free: the second delivery of a merge conflicts on the unique
  index and no-ops, the same as `outcome_jobs`.
- Backfill is bounded by what the repositories still hold. A merge whose diff
  GitHub can no longer serve derives nothing and records why.
- ADR-0004's ruling that the reader is in the scoring path is unchanged; this
  record adds a second model consumer with its own budget line, and the
  cost-per-real-finding pilot (ADR-0018's unrun 20-PR baseline) must land
  before anyone claims what a derivation costs.
