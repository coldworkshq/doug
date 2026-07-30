---
title: Keep the outcome ledger in Postgres
status: accepted
date: 2026-07-29
---

## Context

The distillation loop's central claim is that only findings which
predicted real outcomes get distilled. That claim is a join —
`findings x outcomes` — and it has to be cheap to run repeatedly. The
reader's output is also semi-structured and will change shape as the
schema evolves, so some of the store has to tolerate that.

## Decision

Postgres 18 on Cloud SQL. Three tables — `verdicts`, `findings`,
`outcomes` — created on first use by SQLAlchemy metadata. The reader's
full JSON output is kept verbatim in a JSONB column alongside the typed
columns, so the pipeline can reprocess reads for fields we did not think
to carry at write time.

Storage is opt-in via `DATABASE_URL`. Unset means every call is a cheap
no-op, so local dogfooding and the open-source path need no database.

## Rejected

**MongoDB.** The flexible half of the workload is real but small, and
JSONB covers it. The dominant workload is a relational join across three
tables, which is the thing document stores are worst at. Choosing Mongo
would have optimised for the minority of the workload.

**A migration framework.** Three tables do not need one yet. Revisit
when a schema change needs to preserve data in flight.

## Consequences

- ~$10/month standing cost.
- pgvector is available later without a second datastore.
- The auth proxy does not work from an IPv6-only network, so loading
  bulk data server-side (`--emit-sql` plus `gcloud sql import`) is the
  supported path, not a workaround.
