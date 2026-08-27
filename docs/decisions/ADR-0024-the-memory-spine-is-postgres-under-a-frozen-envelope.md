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

The load is known. Doug's own repository merged 88 pull requests between
2026-08-01 and 2026-08-18, 4.9 per day. Two founder-owned tenants are
installed. A queue for that traffic is not a throughput problem; it is a
correctness problem — delivery is at-least-once, producers redeliver, and two
drains must never claim the same row.

lema already solved the correctness half in Go and paid for it twice. Its
`internal/jobs` claims with `FOR UPDATE SKIP LOCKED` and dedups on a
partial unique index. Its migration runner carries a boot-time `lock_timeout`
and bounded retry from a 2026-07-21 production incident where an `ALTER
TABLE` waited on a lock the previous revision held, and runs goose
`WithAllowOutofOrder(true)` because parallel agent worktrees authored
migrations that merged out of order on 2026-07-13. All of it ports.

## Decision

### The spine

The memory schema's spine is two tables: `memory.events`, append-only, and
`memory.jobs`, claimed with `FOR UPDATE SKIP LOCKED`. Producers write an
event; the store's own drains turn events into work; work writes records.
Nothing else is on the path. No message broker, no task queue, no second
datastore.

Producers are `doug-api` over an internal HTTP wire, the document-lane
ingester inside the store, and — at Stage 5 — the session adapter. Each is a
single writer of its own event types.

### Envelope v1, frozen at migration 1

Every event carries:

| Field | Rule |
|---|---|
| `event_type` | Closed vocabulary, registered per type. |
| `payload_version` | Per `event_type`. A reader that meets a version it does not know **parks** the event and raises an alert; it never fails the drain and never guesses. |
| `idempotency_key` | **Producer-computed**, with a per-`event_type` derivation rule recorded in the registry, and `UNIQUE`-indexed from the first migration. Re-posting the same event inserts once. |
| `tenant_id` | The internal `memory.tenants` id, never a raw `installation_id`. |
| `provenance` | ADR-0022's closed sum type, mandatory, repository-stamped. |
| `occurred_at` | Commitment time, mandatory. Orders everything. |
| `recorded_at` | Write time. Orders nothing. |
| `payload` | JSONB, validated against the registry entry for `(event_type, payload_version)`. Unknown fields are ignored by readers; that is the tolerant-reader rule. |

The registry is a table, not a document, so a producer cannot emit a
`(event_type, payload_version)` the store has not admitted.

### Ordering and delivery

Delivery is at-least-once and every consumer is idempotent on
`idempotency_key`. Ordering is per tenant by `occurred_at`; there is no global
order and nothing may depend on one. Two drains run concurrently and take
disjoint work, proven by a test that runs them in parallel against one queue.

### Migrations

goose, `WithAllowOutofOrder(true)`, the ported `lock_timeout` and retry at
boot. One open pull request holds a migration number at a time. A migration
that adds a foreign key to the `doug` schema fails a catalog test in CI.

### The swap trigger, recorded

Pub/Sub — or any broker — is admitted when **a named Postgres measurement
crosses a pre-registered threshold and stays there**: the oldest-pending-age
alert on `memory.jobs` (one of Gate A's three policies, applied to this
schema) firing for a sustained window that is written down before the
measurement exists, not after. When that happens, the broker replaces the
*transport* and nothing else. The envelope is the contract; a swap that
changes a field is a contract change and reopens Stage 0.

## Rejected

**Pub/Sub now.** Nothing is measured. A broker adds a component, a second
IAM surface, a dead-letter topic, and an ordering-key scheme — and still needs
the producer-computed idempotency key, because Pub/Sub is at-least-once too.
Every property the design wants from a broker is already a property of the
table, at 4.9 events per day.

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

**Unversioned payloads, or a version on the envelope rather than per type.**
A single envelope version bumps every producer at once. Per-type versions
let one producer evolve while the others stand still, and the registry makes
"which versions exist" a query rather than an archaeology.

**Failing the drain on an unknown version.** A drain that stops on the first
unfamiliar event stops for every tenant. Parking one event and alerting
stops for none.

## Consequences

- The envelope is part of the open conformance artifact. A change to it is a
  Stage-0 reopening with a new signature, the same as the wire (ADR-0022).
- Every display, recency, ranking, and supersedence decision anywhere in Doug
  that touches a memory record keys on `occurred_at`. A query ordering by
  `recorded_at` is a review finding.
- Consumers must tolerate replay. A backfill is a replay by construction and
  must produce zero new rows on a second run.
- The store's migration discipline is stricter than this repository's:
  out-of-order is allowed, so numbering is claimed, and a claimed number is
  released only by merge or by closing the pull request.
- The bottleneck measurement exists from Stage 1 because Gate A's alert
  policies are a precondition of Stage 1. If the alert never fires, the
  broker is never bought, and that is the intended outcome.
- If the swap trigger does fire, the work is a transport change inside the
  store, visible to no producer and no reader.
