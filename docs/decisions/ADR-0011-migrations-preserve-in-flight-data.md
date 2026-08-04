---
title: Schema changes that preserve in-flight data use the ordered migration list
status: accepted
date: 2026-08-03
---

## Context

ADR-0001 rejected a migration framework until a schema change needed to
preserve data in flight. That moment arrived with the App-path columns
(migrations 001–004) and again with migration 005: a unique index on
App-path verdict identity cannot be created while duplicate rows from the
advisory-only era still exist. Leaving the create to fail would brick
every cold start that runs `apply()`.

Separately, indexes that must exist in production but must not be declared
on SQLAlchemy `Table` objects (or `create_all` and production diverge) have
lived only in `migrations.py` since migration 003. That convention needed
a decision home.

## Decision

`doug/migrations.py` is the migration framework for this ledger. A
destructive cleanup that is a prerequisite for a constraint is allowed
when all three hold:

1. The closed set of foreign keys to the affected rows is named in the
   migration and cleared or re-pointed before the delete.
2. A test pins that closed set against `store.metadata`, so a new FK
   cannot land silently.
3. Survivors are deterministic (for migration 005: lowest `id` per
   App-identity group).

Partial unique indexes that would diverge if declared on `Table` continue
to live only in the migration list — same convention as migration 003.

## Rejected

**Fail the unique-index create and require manual ops cleanup.** Every
Cloud Run instance that cold-starts runs `apply()`; a failing migration
takes the ledger offline until someone SSHs in.

**Declare `uq_verdicts_app_identity` on the SQLAlchemy `Table`.**
`create_all()` would build it for fresh databases while production only
gets what migrations apply — the same green-test / broken-prod divergence
migration 003 already refused for the queue indexes.

**Skip dedupe and keep duplicates forever.** The published denominator is
the product promise; two App-path rows for one SHA make it a lie.

## Consequences

- ADR-0001's rejection of a migration framework is superseded for this
  class of change. The rest of ADR-0001 (Postgres, opt-in `DATABASE_URL`,
  JSONB raw column) stands.
- Adding a new `ForeignKey("verdicts.id")` requires updating migration
  005's dependent list *and* the pinning test in the same PR, or the next
  destructive cleanup will leave dangling rows or hit an FK violation.
- Same-SHA App-path re-scores are replays of the durable row, not new
  ledger events — that is the uniqueness contract, not an accidental
  behavior change.
