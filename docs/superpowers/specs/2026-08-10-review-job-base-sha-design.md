# Review Job Base SHA Design

## Goal

Persist the base commit GitHub reported when Doug admitted review work so every new `review_jobs` row carries the event-time tuple `(installation_id, github_repo_id, pr_number, base_sha, head_sha)`.

This is a capture-only substrate. It does not change queue deduplication, verdict identity, diff construction, outcome joins, or publication behavior.

## Why this slice exists

Doug currently stores the reviewed head but discards the matching base. The head identifies the proposed tree; it does not identify the comparison GitHub presented when the work entered the queue. Recording the base now creates the substrate for later base-pinned ADR retrieval, frozen comparisons, instrument receipts, and model-garden evaluation without pretending those later mechanisms already exist.

Deriving the base later is invalid because the target branch can move. Expanding identity to `(base_sha, head_sha)` now is also invalid as a small change: queue uniqueness, App verdict uniqueness, replay, diff materialization, receipts, and outcome joins still use head-only identity. Changing only one of those would create contradictory evidence.

## Schema and migration

Add nullable `review_jobs.base_sha VARCHAR(64)` to SQLAlchemy metadata and migration 10.

The column is nullable only for historical compatibility. Existing rows are not backfilled because their event-time base is unknowable. New runtime enqueue calls must provide a non-null base SHA.

Migration 10 is intentional even though `origin/main` currently ends at migration 8. The separate `front-door-phase-1` branch already reserves migration 9 for installation ownership fields. Migration application does not require versions to be contiguous, so either merge order converges without renumbering an already reviewed branch.

The existing `uq_review_job` constraint remains exactly `(installation_id, github_repo_id, pr_number, head_sha)`.

## Data flow

### Webhook admission

For admitted `pull_request` events, `_enqueue_review` extracts both `pull_request.base.sha` and `pull_request.head.sha`. Missing or unusable base SHA follows the existing malformed-identity behavior: log the omitted field, return without enqueueing, and preserve the webhook's 202 response.

### Reconciliation

For each admitted open PR, `reconcile_installation` reads `p.base.sha` and passes it to `ingest.enqueue`. If the base SHA is absent or unusable, the PR is skipped with an operator-visible reason. Draft, fork, repository-identity, pagination, and cooloff behavior remain unchanged.

### Stale-head catch-up

`process_job` reads the current PR object once and obtains both current head and current base. If the head has moved, Doug requires both replacement SHAs before superseding the claimed job. An incomplete GitHub response raises before mutation so retry/reclaim cannot strand the PR without a replacement job.

If the head has not moved, the claimed row's recorded base is not compared with GitHub's current base. Capture-only does not turn base movement into new work.

### Queue lifecycle

`ingest.enqueue` takes required keyword-only `base_sha: str` and writes it on insert. `claim()` already returns the whole row, so the persisted value becomes available to workers without a second interface.

On a head-only uniqueness collision:

- `pending`, `running`, and `done` rows remain deduped and unchanged, including their original `base_sha`.
- A `failed` or `superseded` row that is revived updates `base_sha` to the value observed by the enqueue event that made it pending again.

This preserves current spend and replay semantics while making a revived unit describe the work it is now expected to perform.

## Explicit non-goals

- No `(base_sha, head_sha)` queue or verdict uniqueness.
- No base-pinned diff fetch or comparison API call.
- No change to `find_verdict_by_identity`, check-run identity, receipts, outcomes, or model-garden promotion.
- No historical base-SHA inference or backfill.
- No change to PR metadata unless a later consumer requires it.

## Verification contract

Caller-level tests must prove:

1. Migration 10 adds the nullable column to an older database and fresh metadata converges with the migration.
2. `enqueue` persists the base, `claim` exposes it, and revive replaces it.
3. A same-head/different-base duplicate remains one job under the unchanged head-only constraint.
4. Webhook admission persists `base.sha` and safely skips a payload that omits it.
5. Reconciliation persists `p.base.sha` and logs/skips an incomplete PR.
6. Stale-head catch-up enqueues the replacement with the current base and does not supersede when replacement identity is incomplete.
7. The focused API, ingest, migration, and worker suites pass, followed by the repository verification target.
