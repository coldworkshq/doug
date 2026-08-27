---
title: The memory spine is Postgres job tables under a frozen event envelope; Pub/Sub waits for a measured bottleneck
status: proposed
date: 2026-08-26
---

## Context

The outcome-loop design lock (`docs/design/outcome-loop/design-lock.md`)
rules: "No AlloyDB, BigQuery, Pub/Sub, or Cloud Tasks until a Postgres table
is measurably the bottleneck." The first product map (2026-08-19, v1) drew a
Pub/Sub spine between `doug-api` and the memory store anyway. The design
pass caught the contradiction and reversed it; this record is where the
reversal lives on paper, so the next diagram cannot quietly redraw it.

The load is known. This repository merged 101 pull requests between
2026-08-01 and 2026-08-18, 5.6 per day. Two founder-owned tenants are
installed. A queue for that traffic is not a throughput problem; it is a
correctness problem — delivery is at-least-once, producers redeliver, and two
drains must never claim the same row.

What ports from lema, and what does not, was checked on disk. lema's
`internal/jobs` launches work in-process and claims by compare-and-set
(`UPDATE jobs SET status = 'running' WHERE id = $1 AND status = 'queued'`,
`jobs.go:489-492`); it has no `SKIP LOCKED` claimer and no queue-level
idempotency index — its delivery idempotency lives on `settlement_events`'
unique `(org, repo, pr)` key (`0056:49`). What does port is the migration
discipline: a boot-time `lock_timeout` and bounded retry from a 2026-07-21
production incident where an `ALTER TABLE` waited on a lock the previous
revision held (`migrations.go:49, 58-61`), and goose `WithAllowOutofOrder(true)`
because parallel agent worktrees authored migrations that merged out of order
on 2026-07-13 (`migrations.go:132-145`). The concurrent-claim pattern this
record mandates already exists in this repository's own Python claimers
(`ingest.py:364`, `outcome_queue.py:92`, pinned by `test_outcome_queue.py:193`)
and in the design lock's item 3; on the Go side it is new code, owned by MS-6.

## Decision

### The spine

The memory schema's spine is two tables: `memory.events`, append-only, and
`memory.jobs`, claimed with `FOR UPDATE SKIP LOCKED`. Producers write an
event; the store's own drains turn events into work; work writes records.
Nothing else is on the path. No message broker, no task queue, no second
datastore.

The only external producer is `doug-api`, over an authenticated internal wire;
the document-lane ingester runs inside the store. Session events enter through
Doug's own session ingest (session-lane design §4) and reach the store as
`doug-api`-emitted events, so harness hooks never hold a store credential. The
registry binds each producer identity to the event types it may emit; "single
writer of its own event types" is a row, not prose.

### Envelope v1, frozen at migration 1

Every event carries:

| Field | Rule |
|---|---|
| `event_type` | Closed vocabulary, registered per type. Registering a new type is additive. |
| `payload_version` | Per `event_type`. A reader that meets a version it does not know **parks** the event: `parked` is a non-terminal `memory.jobs` status carrying the pair, re-claimed at every drain start by the binary that now knows it (lema's `SweepOrphans` arm, ported), and counted toward the oldest-pending-age alert. The drain never fails and never guesses. |
| `idempotency_key` | **Producer-computed**, with a per-`event_type` derivation rule recorded in the registry and published as fixture vectors in the conformance artifact, and `UNIQUE`-indexed from the first migration. Re-posting the same event inserts once; the rule for merge-derived events excludes `batch_id`. |
| `tenant_id` | **Store-resolved.** The wire carries `installation_id` and `github_repo_id`; the store resolves the internal `memory.tenants` id through `tenant_installations` and `tenant_repos` (ADR-0022) and refuses a body that names a `tenant_id` itself. |
| `github_repo_id` | Mandatory on every event. |
| `provenance` | ADR-0022's closed sum type, mandatory. Variants are registry rows; adding one is additive. |
| `occurred_at` | Commitment time, GitHub-clocked per ADR-0022, mandatory. Orders everything. Refused if later than `recorded_at` plus the skew allowance. |
| `recorded_at` | Write time. Orders nothing. |
| `payload` | JSONB, validated at write against a **closed** schema for `(event_type, payload_version)` — `additionalProperties: false`, the port of lema's `DisallowUnknownFields` decoder — with a `max_payload_bytes` per registry row. An unregistered field is refused, not stored. Tolerant reading means a newer reader accepts every registered older version; it never means a reader ignores what a writer smuggled. |

The registry is a table, not a document, so a producer cannot emit a
`(event_type, payload_version)` the store has not admitted. `decision.dismissed`
and `record.redacted` are registered event types from migration 1 with the
schemas ADR-0022 describes.

### Ordering and delivery

Delivery is at-least-once and every consumer is idempotent on
`idempotency_key`. Ordering is per tenant by `occurred_at`; there is no global
order and nothing may depend on one. Two drains run concurrently and take
disjoint work, proven by a test that runs them in parallel against one queue
seeded for two tenants, on a pool a tenant request has just used — that test
is MS-6's exit criterion.

### Migrations

goose, `WithAllowOutofOrder(true)`, the ported `lock_timeout` and retry at
boot, run by the migrator role, not the runtime role (ADR-0022). One open pull
request holds a migration number at a time. A migration that adds a foreign
key to the `doug` schema fails a catalog test in CI. Rollout order is store
before producer, so a new `payload_version` is admitted before anything emits
it.

### The swap trigger, recorded

Pub/Sub — or any broker — is admitted when **a named Postgres measurement
crosses a pre-registered threshold and stays there**: the oldest-pending-age
policy on `memory.jobs`, whose threshold and sustained window are committed in
the store's own pre-registration file before `memory.jobs` exists. That policy
is not one of Gate A's three — those are doug-lane policies and Gate A closes
before this schema exists. It is created by the store's own deploy in
`coldworkshq/memory-store` on a metric the Go drain exports, and Stage 1 does
not exit until the policy exists and has fired once against a deliberately
stalled job. When the trigger fires, the broker replaces the *transport* and
nothing else. The envelope is the contract; a swap that changes a field is a
contract change and reopens Stage 0.

## Rejected

**Pub/Sub now.** Nothing is measured. A broker adds a component, a second
IAM surface, a dead-letter topic, and an ordering-key scheme — and still needs
the producer-computed idempotency key, because Pub/Sub is at-least-once too.
Every property the design wants from a broker is already a property of the
table, at 5.6 events per day.

**Cloud Tasks.** Same as above with a per-task HTTP target, which puts the
drain behind a public-ish endpoint the store otherwise never exposes.

**A transactional outbox into a broker.** The outbox *is* `memory.events`.
Adding the broker behind it is the rejected item above with an extra hop.

**One events table shared by both schemas.** Two writers on one table is the
coupling the two-schema design exists to prevent, and RLS policy on a
shared table would have to know both tenancy models.

**Consumer-computed idempotency.** A redelivered body must be recognizable
before it is parsed. If the consumer derives the key, a parse error on a
redelivery is a fresh event.

**Producer-asserted tenancy.** A producer that names the tenant it writes
under chooses the RLS partition it lands in. The store resolves tenancy from
facts the producer cannot forge — the installation id GitHub signed and the
repository id it covers.

**Unversioned payloads, or a version on the envelope rather than per type.**
A single envelope version bumps every producer at once. Per-type versions
let one producer evolve while the others stand still, and the registry makes
"which versions exist" a query rather than an archaeology.

**Failing the drain on an unknown version.** A drain that stops on the first
unfamiliar event stops for every tenant. Parking one event and re-claiming it
at the next boot stops for none.

**Ignoring unknown payload fields at read.** Append-only plus replay means a
field nobody validated today is a field a future version may honor. Closed
schemas at write are the only reading of "tolerant" that survives replay.

**The session adapter as a direct store producer.** It would put a store
credential and a tenant partition in every harness hook and bypass the card
deriver and correlator that the session lane's design routes captures through.

## Consequences

- The envelope's fields are part of the open conformance artifact. A change to
  a field is a Stage-0 reopening with a new signature, the same as the wire
  (ADR-0022); a new event type, payload version, or provenance variant is a
  registry row and is not.
- Every display, recency, ranking, and supersedence decision anywhere in Doug
  that touches a memory record keys on `occurred_at`. A query ordering by
  `recorded_at` is a review finding.
- Consumers must tolerate replay. A backfill is a replay by construction and
  must produce zero new rows on a second run.
- The store's migration discipline is stricter than this repository's:
  out-of-order is allowed, so numbering is claimed, and a claimed number is
  released only by merge or by closing the pull request.
- The bottleneck measurement exists from Stage 1 because creating and
  test-firing the `memory.jobs` policy is a Stage-1 exit item. If the policy
  exists and never fires, the broker is never bought, and that is the intended
  outcome; if the policy does not exist, silence means nothing, and Stage 1
  has not exited.
- If the swap trigger does fire, the work is a transport change inside the
  store, visible to no producer and no reader.
