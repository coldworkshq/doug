# M3 Adjudicator Job and Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drain due `outcome_jobs` once per day through Doug's existing pure adjudicator and persist exactly one outcome per successfully classified job.

**Architecture:** A dedicated `doug.outcome_worker` process snapshots the repositories with due work, claims one repository's rows with `FOR UPDATE SKIP LOCKED`, and processes each repository at most once per invocation. Claims are leased and fenced like `review_jobs`; success writes outcomes and completes jobs in one transaction, while repository failures spend one of the pre-registered ten attempts and return the rows to `pending` for the next daily run. A Cloud Run Job uses the exact image deployed to `doug-api`; Cloud Scheduler invokes that Job daily.

**Tech Stack:** Python 3.14, SQLAlchemy 2, PostgreSQL/SQLite tests, GitHubKit, git treeless clones, pytest, Bash, gcloud Cloud Run Jobs and Cloud Scheduler.

## Global Constraints

- The pure classifier remains `doug.adjudicate.adjudicate`; no second revert detector is introduced.
- Every published outcome is keyed by installation, repository id, PR number, merge SHA, and window.
- A repository is processed at most once per scheduled invocation; `max_attempts = 10` therefore means ten daily opportunities, not ten immediate retries.
- Clone/API failures retry and can end as job status `failed`; they never become a `clean` outcome.
- Only durable `installations.state != active` or `installation_repos.state != active` evidence permits unreachable-repository censoring.
- Cloud Run Job configuration is 2Gi memory, one task, one CPU, 60-minute timeout, and zero platform retries.
- Cloud Scheduler cadence is `0 3 * * *` in `Etc/UTC`.
- Production code follows red-green-refactor: each behavioral change starts with a failing test that names the bug it prevents.
- No production deployment is performed from this worktree; delivery is code, tests, runbook, and PR.

---

### Task 1: Migration 007 and persisted adjudication identity

**Files:**
- Modify: `api/doug/store.py`
- Modify: `api/doug/migrations.py`
- Modify: `api/tests/test_migrations.py`
- Modify: `api/tests/test_coverage.py`
- Modify: `api/tests/test_store.py`

**Interfaces:**
- Produces: `outcomes.merge_commit_sha: str | None` and unique app-outcome index `uq_outcomes_job_identity`.
- Produces: `outcome_jobs.started_at`, `finished_at`, `error`, and `claim_generation` for leased claims.
- Produces: persisted `reads.changed_files` and `reads.files_dropped`, completing the already-shipped `Coverage` contract.

- [ ] **Step 1: Write migration drift tests that fail on the current schema**

Add literal expectations for migration 7:

```python
M7_COLUMNS = {
    "outcomes": {"merge_commit_sha"},
    "outcome_jobs": {"started_at", "finished_at", "error", "claim_generation"},
    "reads": {"changed_files", "files_dropped"},
}

def test_migration_007_declares_the_same_columns_as_their_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/decl7.db")
    store.metadata.create_all(engine)
    assert _statements_by_table(dict(migrations.MIGRATIONS)[7]) == M7_COLUMNS
    for table, columns in M7_COLUMNS.items():
        assert columns <= _columns(engine, table)
```

Also assert that migration 7 installs `uq_outcomes_job_identity` and that two non-null outcomes for the same job identity cannot be inserted.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd api
uv run pytest tests/test_migrations.py tests/test_coverage.py tests/test_store.py -q
```

Expected: failures name missing migration 7 columns and missing persisted coverage values.

- [ ] **Step 3: Add the minimal schema and migration**

Add the columns to their `Table` definitions and migration 7. The production index is partial so historical outcomes with no merge SHA remain legal:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_outcomes_job_identity
ON outcomes (installation_id, github_repo_id, pr_number, merge_commit_sha, window_days)
WHERE merge_commit_sha IS NOT NULL
```

Update `save_read` to write `cov.changed_files` and `cov.files_dropped`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the same focused command. Expected: all selected tests pass.

- [ ] **Step 5: Commit the schema unit**

```bash
git add api/doug/store.py api/doug/migrations.py api/tests/test_migrations.py api/tests/test_coverage.py api/tests/test_store.py
git commit -m "feat: add adjudication claim schema"
```

---

### Task 2: Due-row claim, lease, retry, and atomic settlement

**Files:**
- Create: `api/doug/outcome_queue.py`
- Create: `api/tests/test_outcome_queue.py`

**Interfaces:**
- Produces: `RepositoryKey(installation_id: int, github_repo_id: int)`.
- Produces: `ClaimedBatch(key, repo_full_name, permanently_unreachable, jobs)`.
- Produces: `due_repositories() -> list[RepositoryKey]`.
- Produces: `claim_repository(key: RepositoryKey) -> ClaimedBatch | None`.
- Produces: `reclaim_stalled(older_than_seconds: int = 7200) -> int`.
- Produces: `fail_batch(batch: ClaimedBatch, error: str, max_attempts: int = 10) -> int`.
- Produces: `settle_batch(batch, adjudication, repo_full_name, observed_at, prereg_hash) -> tuple[int, int]`, returning `(done, retried_or_failed)`.

- [ ] **Step 1: Write failing queue tests**

Use real SQLite rows for behavior and the PostgreSQL dialect for the emitted lock contract. Tests must prove:

```python
def test_due_repositories_excludes_future_done_failed_and_running_rows(...): ...
def test_claim_repository_marks_every_due_row_for_one_repo_running(...): ...
def test_claim_query_compiles_to_for_update_skip_locked(): ...
def test_reclaim_stalled_requeues_only_expired_claims(...): ...
def test_one_failure_spends_one_attempt_and_retries_on_the_next_run(...): ...
def test_the_tenth_failure_is_terminal(...): ...
def test_settlement_inserts_outcome_and_marks_the_matching_job_done_atomically(...): ...
def test_a_lost_claim_inserts_no_outcome(...): ...
def test_an_unparseable_revert_retries_only_its_job(...): ...
def test_removed_repo_is_censored_but_a_missing_registry_row_is_retried(...): ...
```

The lost-claim test changes `claim_generation` after claim and asserts both tables remain unchanged by settlement.

- [ ] **Step 2: Run the new test file and verify RED**

```bash
cd api
uv run pytest tests/test_outcome_queue.py -q
```

Expected: import failure for `doug.outcome_queue`.

- [ ] **Step 3: Implement the minimal queue**

Use database time (`clock_timestamp()` on PostgreSQL, aware UTC wall time on SQLite). Claim rows only where:

```python
status == "pending" and due_at <= db_now
```

On PostgreSQL, both the oldest-row selector and same-repository batch selector use `.with_for_update(skip_locked=True)`. Claim updates increment `claim_generation`; terminal writes require `status='running'` and the exact generation returned to the caller.

`settle_batch` preflights every fence before inserting anything. It serializes `Outcome.detail` with `prereg_hash`, inserts `source='git-labels'`, and updates successful jobs to `done` in the same transaction. Unadjudicable rows use the same SQL-side attempts expression as `ingest.fail` and never insert an outcome.

- [ ] **Step 4: Run queue plus migration/store tests and verify GREEN**

```bash
cd api
uv run pytest tests/test_outcome_queue.py tests/test_migrations.py tests/test_store.py -q
```

- [ ] **Step 5: Commit the queue unit**

```bash
git add api/doug/outcome_queue.py api/tests/test_outcome_queue.py
git commit -m "feat: add durable outcome job drain"
```

---

### Task 3: Repository evidence adapter and executable worker

**Files:**
- Modify: `api/doug/backtest/git_labels.py`
- Create: `api/doug/outcome_worker.py`
- Create: `api/tests/test_outcome_worker.py`
- Modify: `api/pyproject.toml`

**Interfaces:**
- Produces: `git_labels.find_reverted_prs_evidenced(owner, repo, cache_dir, token=None) -> dict[int, Commit]`.
- Produces: `outcome_worker.drain(*, prereg_hash: str, clone_root: Path) -> DrainSummary`.
- Produces CLI entry point `doug-adjudicate = "doug.outcome_worker:main"` and module execution via `python -m doug.outcome_worker`.

- [ ] **Step 1: Write failing adapter and orchestration tests**

Tests must prove these observable behaviors:

```python
def test_evidenced_loader_uses_the_shared_clone_and_parser(...): ...
def test_drain_processes_each_due_repository_once(...): ...
def test_drain_passes_the_installation_token_to_the_clone(...): ...
def test_durable_removed_repo_needs_no_github_call_and_becomes_censored(...): ...
def test_clone_failure_records_one_retry_without_storing_the_token(...): ...
def test_one_repository_failure_does_not_block_a_second_repository(...): ...
def test_no_due_work_needs_no_app_credentials_or_prereg_hash(...): ...
def test_due_work_fails_loud_before_claiming_when_prereg_hash_is_missing(...): ...
```

Mock only GitHub and git subprocess boundaries. Queue and adjudicator behavior stay real in integration tests against SQLite.

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
cd api
uv run pytest tests/test_outcome_worker.py -q
```

- [ ] **Step 3: Implement the minimal adapter and worker**

For active repositories:

1. Mint an installation token through `app_auth.app_client().rest.apps.create_installation_access_token`.
2. Read `default_branch` through `app_auth.installation_client(...).rest.repos.get`.
3. Build the evidenced revert map through the new public `git_labels` helper and `/tmp/doug-adjudicator/<installation>-<repo>`.
4. Call the existing pure `adjudicate` function.
5. Settle the batch through `outcome_queue`.

Never persist or print raw GitHub exceptions from clone/token operations because a `CalledProcessError` can contain the credential-bearing clone URL. Store a bounded message such as `repository clone failed (CalledProcessError)`.

Snapshot `due_repositories()` once per invocation, reclaim stale rows before that snapshot, and visit every key once. A repository-specific failure is recorded and the process continues; database/bootstrap failures escape so the Cloud Run execution is visibly failed.

- [ ] **Step 4: Run worker, queue, and adjudicator tests and verify GREEN**

```bash
cd api
uv run pytest tests/test_outcome_worker.py tests/test_outcome_queue.py tests/test_adjudicate.py -q
```

- [ ] **Step 5: Commit the worker unit**

```bash
git add api/doug/backtest/git_labels.py api/doug/outcome_worker.py api/tests/test_outcome_worker.py api/pyproject.toml api/uv.lock
git commit -m "feat: run due adjudications by repository"
```

---

### Task 4: Cloud Run Job, daily Scheduler, and continuous deployment

**Files:**
- Modify: `api/deploy/gcp.sh`
- Modify: `api/tests/test_deploy_gcp.py`
- Modify: `.github/workflows/deploy.yml`

**Interfaces:**
- Produces: `gcp.sh adjudicator`, deploying `doug-adjudicator` from the exact image serving `doug-api`.
- Produces: `gcp.sh schedule`, idempotently creating/updating `doug-adjudicator-daily`.
- Produces: narrow `gcp.sh adjudicator-setup` for `cloudscheduler.googleapis.com`,
  `doug-adjudicator-sa`, and `doug-scheduler-sa`; it must not rotate SQL credentials.
- Extends: API deployment workflow so a changed API deploys the worker image too.

- [ ] **Step 1: Write failing executable deployment tests**

Run `gcp.sh adjudicator` and `gcp.sh schedule` with a fake `gcloud` executable in `PATH` that records argv. Assert behavior, not source text:

```python
assert_job_args_include(
    "--memory", "2Gi", "--cpu", "1", "--tasks", "1",
    "--max-retries", "0", "--task-timeout", "3600s",
    "--command", "python", "--args", "-m,doug.outcome_worker",
)
assert_scheduler_args_include(
    "--schedule", "0 3 * * *", "--time-zone", "Etc/UTC",
    "--http-method", "POST",
)
```

Also assert the job image equals the fake API image returned by `gcloud run services describe`, and that the scheduler principal—not the runtime principal—gets `roles/run.invoker`.

- [ ] **Step 2: Run deployment tests and verify RED**

```bash
cd api
uv run pytest tests/test_deploy_gcp.py -q
```

- [ ] **Step 3: Implement setup, deploy, and schedule commands**

`adjudicator()` reads the deployed API image, calculates the SHA-256 of `../docs/design/outcome-loop/publication-preregistration.md`, and deploys:

```bash
gcloud run jobs deploy doug-adjudicator \
  --image "$API_IMAGE" \
  --command python --args=-m,doug.outcome_worker \
  --service-account "doug-adjudicator-sa@$PROJECT.iam.gserviceaccount.com" \
  --set-cloudsql-instances "$CONN" \
  --set-secrets "DATABASE_URL=doug-database-url:latest,GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest" \
  --set-env-vars "DOUG_GITHUB_APP_ID=4450932,DOUG_PREREG_HASH=$PREREG_HASH" \
  --memory 2Gi --cpu 1 --tasks 1 --max-retries 0 --task-timeout 3600s
```

`schedule()` creates or updates the v2 `:run` URI using OAuth from `doug-scheduler-sa`, then grants that principal `roles/run.invoker` on the Job. `deploy()` calls `adjudicator()` after the API candidate is promoted so both workloads use the same built image.

- [ ] **Step 4: Run deployment tests and verify GREEN**

```bash
cd api
uv run pytest tests/test_deploy_gcp.py -q
```

- [ ] **Step 5: Commit the deployment unit**

```bash
git add api/deploy/gcp.sh api/tests/test_deploy_gcp.py .github/workflows/deploy.yml
git commit -m "feat: schedule the M3 adjudicator job"
```

---

### Task 5: Operational truth, full verification, and PR delivery

**Files:**
- Modify: `docs/design/outcome-loop/ROADMAP.md`
- Modify: `docs/design/outcome-loop/architecture.md`
- Modify: `docs/design/outcome-loop/publication-preregistration.md`
- Modify: `HANDOFF.md`

**Interfaces:**
- Produces: exact first-deploy runbook: `setup`, merge/deploy, `schedule`, manual execution, row audit.
- Produces: corrected migration number 007 and removes the contradictory claim that `adjudicate.py` does not exist.

- [ ] **Step 1: Update only the state this slice changes**

Mark the Job/Scheduler roadmap item built in source but not production-verified. Record:

```bash
cd api
PROJECT=doug-prod0 REGION=us-central1 bash deploy/gcp.sh adjudicator-setup
# merge deploys API + Job from one image
PROJECT=doug-prod0 REGION=us-central1 bash deploy/gcp.sh schedule
gcloud run jobs execute doug-adjudicator --project doug-prod0 --region us-central1 --wait
```

The runbook must require checking that the first execution changes only due rows and that every `done` job has exactly one matching outcome identity. Do not claim the scheduler is live until those commands are actually run.

- [ ] **Step 2: Run focused verification**

```bash
cd api
uv run pytest tests/test_migrations.py tests/test_outcome_queue.py tests/test_outcome_worker.py tests/test_adjudicate.py tests/test_deploy_gcp.py -q
```

- [ ] **Step 3: Run the complete repository gates**

```bash
cd api
uv run ruff check .
uv run pytest
uv run python scripts/read_budget_gate.py
uv run python -m doug.findings_log check
cd ../web && npm run lint && npm run build
cd ../console && npm run lint && npm test -- --run && npm run build
```

Expected: all gates pass; the known Starlette deprecation warning must be reported rather than hidden.

- [ ] **Step 4: Review the diff and commit the documentation**

```bash
git diff --check
git status --short
git add HANDOFF.md docs/design/outcome-loop/ROADMAP.md docs/design/outcome-loop/architecture.md docs/design/outcome-loop/publication-preregistration.md docs/superpowers/plans/2026-08-06-m3-adjudicator-job-scheduler.md
git commit -m "docs: hand off the M3 adjudicator rollout"
```

- [ ] **Step 5: Push and open the PR**

```bash
git push -u origin m3-adjudicator-job
gh pr create --base main --head m3-adjudicator-job --title "Build the M3 adjudicator job and scheduler" --body-file /tmp/doug-m3-pr.md
```

The PR body distinguishes verified local behavior from unperformed production setup and names the exact operational commands still requiring a human principal.

---

## Self-review

- Spec coverage: claim cutoff, SKIP LOCKED, daily cadence, 2Gi job, same detector, base-ref censoring, ten-attempt retry, append-only outcomes, merge-SHA identity, prereg hash, IAM, and operational verification all map to a task above.
- Deliberate exclusions: receipts, check-run counters, public scoreboard, 60-day backfill, and Reader v2 are separately testable M3/follow-up slices and are not bundled here.
- No placeholders: every step names its files, behavior, command, and expected outcome.
- Type consistency: `RepositoryKey` and `ClaimedBatch` are produced by Task 2 and consumed unchanged by Task 3; settlement is the only writer of terminal outcome state.
