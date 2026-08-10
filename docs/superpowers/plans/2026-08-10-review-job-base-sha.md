# Review Job Base SHA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Persist the event-time base SHA on every newly admitted review job without changing head-only queue or verdict identity.

**Architecture:** Migration 10 and SQLAlchemy metadata add a nullable historical column, while `ingest.enqueue` requires the value for all new work. Webhook, reconcile, and stale-head callers extract the base from the same GitHub PR representation that supplies the head; revive refreshes the recorded base, but ordinary head-only collisions remain deduped.

**Tech Stack:** Python 3.14, SQLAlchemy Core, FastAPI webhook handlers, GitHub SDK objects, pytest, SQLite/PostgreSQL-compatible migrations.

## Global Constraints

- Preserve `uq_review_job` and App verdict identity as head-only.
- Keep historical `review_jobs.base_sha` values NULL; never infer or backfill them.
- Use migration 10 because `front-door-phase-1` already reserves migration 9.
- Require `base_sha` at every new runtime `ingest.enqueue` call.
- Do not change diff construction, receipts, outcomes, check-run identity, or model-garden behavior.
- Do not supersede a stale-head job until both replacement SHAs are available.

---

### Task 1: Add the forward-only schema substrate

**Files:**
- Modify: `api/doug/store.py`
- Modify: `api/doug/migrations.py`
- Test: `api/tests/test_migrations.py`

**Interfaces:**
- Produces: nullable `store.review_jobs.c.base_sha` with `String(64)` and migration `(10, ("ALTER TABLE review_jobs ADD COLUMN base_sha VARCHAR(64)",))`.

- [x] **Step 1: Write the failing migration drift test**

  Add `M10_COLUMNS = {"review_jobs": {"base_sha"}}`, assert migration 10 declares exactly that mapping, assert the metadata column has length 64 and is nullable, and extend the older-schema convergence assertion with `base_sha`.

- [x] **Step 2: Run the migration test and verify RED**

  Run: `cd api && uv run pytest tests/test_migrations.py::test_migration_010_declares_the_same_columns_as_their_tables -q`

  Expected: FAIL because migration 10 and `review_jobs.base_sha` do not exist.

- [x] **Step 3: Add the minimal metadata and migration**

  Add `Column("base_sha", String(64))` immediately before `head_sha` and migration 10 after migration 8. Do not add `base_sha` to `uq_review_job`.

- [x] **Step 4: Verify GREEN and migration convergence**

  Run: `cd api && uv run pytest tests/test_migrations.py -q`

  Expected: all migration tests pass, including old-schema and fresh-schema application.

### Task 2: Persist and claim the base through queue lifecycle

**Files:**
- Modify: `api/doug/ingest.py`
- Modify: `api/tests/test_ingest.py`
- Modify: `api/tests/test_worker.py`
- Modify: `api/tests/test_api.py`
- Modify: `api/tests/test_store.py`

**Interfaces:**
- Produces: `enqueue(..., head_sha: str, *, base_sha: str, trigger: Trigger = "live") -> int | None`.
- Produces: `_revive(..., head_sha: str, base_sha: str, trigger: Trigger) -> int | None` that writes the new base only when revival succeeds.
- Consumes: `store.review_jobs.c.base_sha` from Task 1.

- [x] **Step 1: Write failing queue behavior tests**

  Add tests proving `enqueue(..., base_sha="b" * 40)` persists the value and `claim()` returns it; a same-head duplicate with a different base returns `None` and leaves the original base; and revival updates the base on the existing row.

- [x] **Step 2: Run the new queue tests and verify RED**

  Run: `cd api && uv run pytest tests/test_ingest.py -k 'base_sha' -q`

  Expected: FAIL because `enqueue` does not accept or write `base_sha`.

- [x] **Step 3: Implement the queue contract**

  Add required keyword-only `base_sha`, include it in the insert mapping, pass it into `_revive`, and add `base_sha=base_sha` to the successful revive update. Keep collision filters and the unique constraint unchanged.

- [x] **Step 4: Update existing enqueue fixtures and calls mechanically**

  Add a fixed base SHA to `JOB` and the ingest test constants. Update direct test calls to name `base_sha`; do not weaken the production signature with a default merely to preserve old tests.

- [x] **Step 5: Verify GREEN**

  Run: `cd api && uv run pytest tests/test_ingest.py -q`

  Expected: all ingest tests pass and the new tests pin capture-only collision semantics.

### Task 3: Capture the base at every production admission boundary

**Files:**
- Modify: `api/doug/api.py`
- Modify: `api/doug/worker.py`
- Test: `api/tests/test_api.py`
- Test: `api/tests/test_worker.py`

**Interfaces:**
- Webhook consumes: `pull_request.base.sha` and `pull_request.head.sha`.
- Reconcile consumes: `p.base.sha` and `p.head.sha`.
- Stale catch-up consumes: one `pulls.get(...).parsed_data` object containing `.base.sha` and `.head.sha`.
- All three produce: `ingest.enqueue(..., head_sha, base_sha=<observed base>)`.

- [x] **Step 1: Write failing webhook tests**

  Extend `_pr_payload` with `base_sha="b" * 40`. Assert the durable job stores it. Add a missing-base test asserting HTTP 202, no job, no drain kick, and an error mentioning `base.sha`.

- [x] **Step 2: Run webhook tests and verify RED**

  Run: `cd api && uv run pytest tests/test_api.py -k 'pull_request_event_enqueues_one_durable_job or missing_base_sha' -q`

  Expected: the persistence assertion fails and the missing-base payload still enqueues.

- [x] **Step 3: Implement webhook extraction**

  Keep the full base object long enough to validate `base.sha` with `_text(..., store.review_jobs.c.base_sha)`, include `base.sha` in the malformed identity log, and pass the value as the required keyword.

- [x] **Step 4: Write failing reconciliation and stale-head tests**

  Extend `_pull` with `base_sha`. Prove reconciliation persists it and missing base logs/skips. Extend `_gh` so `pulls.get` returns both SHAs; prove a moved head enqueues the fetched base, and a missing replacement base raises before the original job becomes superseded.

- [x] **Step 5: Run worker tests and verify RED**

  Run: `cd api && uv run pytest tests/test_worker.py -k 'base_sha or stale_head' -q`

  Expected: FAIL because worker callers do not pass a base and stale-head lookup reads only `.head.sha`.

- [x] **Step 6: Implement worker extraction and failure ordering**

  In reconcile, validate `p.base.sha`, log an explicit skip when absent, and enqueue with it. In `process_job`, retain the fetched PR object, validate both replacement SHAs before `supersede`, raise `RuntimeError` on incomplete replacement identity, and enqueue with the fetched base.

- [x] **Step 7: Verify production-path GREEN**

  Run: `cd api && uv run pytest tests/test_api.py tests/test_worker.py -q`

  Expected: both suites pass with the base captured on every production path.

### Task 4: Verify the boundary and prepare delivery

**Files:**
- Verify: `api/doug/store.py`
- Verify: `api/doug/migrations.py`
- Verify: `api/doug/ingest.py`
- Verify: `api/doug/api.py`
- Verify: `api/doug/worker.py`
- Verify: related tests and design documents.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: a PR-sized capture-only substrate with reproducible receipts.

- [x] **Step 1: Run focused verification**

  Run: `cd api && uv run pytest tests/test_ingest.py tests/test_api.py tests/test_worker.py tests/test_migrations.py tests/test_store.py -q`

  Expected: all focused tests pass with no skips or failures.

- [x] **Step 2: Scan every enqueue caller and identity constraint**

  Run: `rg -n 'ingest\.enqueue\(' api --glob '*.py'`

  Inspect every match: production calls and tests must supply `base_sha`. Confirm `uq_review_job` and `find_verdict_by_identity` remain head-only.

- [x] **Step 3: Run repository verification**

  Run: `make test`

  Expected: all API, console, and web test commands complete successfully; report any warning or skip instead of hiding it.

- [x] **Step 4: Run diff integrity checks**

  Run: `git diff --check && git status --short && git diff --stat`

  Expected: no whitespace errors and only the approved schema, queue, caller, test, spec, and plan files changed.

- [x] **Step 5: Commit the implementation**

  Run: `git add api/doug/store.py api/doug/migrations.py api/doug/ingest.py api/doug/api.py api/doug/worker.py api/tests/test_migrations.py api/tests/test_ingest.py api/tests/test_api.py api/tests/test_worker.py api/tests/test_store.py docs/superpowers/specs/2026-08-10-review-job-base-sha-design.md docs/superpowers/plans/2026-08-10-review-job-base-sha.md && git commit -m "feat: persist review job base sha"`

  Expected: one implementation commit with the design and verification receipts in its diff.
