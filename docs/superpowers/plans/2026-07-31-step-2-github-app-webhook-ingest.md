# Step 2: GitHub App + Webhook Ingest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the CI-token ingest path with webhook-driven review through the installed GitHub App (`dougs-review`, App ID 4450932, installation 150424894), surfacing verdicts as a neutral check run.

**Architecture:** The webhook handler verifies, records installation state, and enqueues durable jobs in Postgres — never reviewing inline. A threadpool drain claims jobs (`FOR UPDATE SKIP LOCKED` on Postgres), runs the existing review pipeline via short-lived installation tokens, persists with App identity columns, and posts a neutral check run. Missed deliveries are healed by reconciling open PRs by head SHA at startup and on new installations, not by trusting redelivery.

**Tech Stack:** FastAPI (existing), githubkit `[auth-app]` extra (adds PyJWT), SQLAlchemy Core over Postgres 18 / sqlite-in-tests (existing), Cloud Run (existing).

**Spec:** `docs/superpowers/specs/2026-07-30-github-app-tenancy-dashboard-design.md` — this plan implements its "Build order" step 2 only. Steps 3–4 (WorkOS tenancy, dashboard) are separate plans.

## Global Constraints

- **Never blocks:** every check run concludes `neutral`. No conclusion may ever be `failure`/`action_required`. (ADR-0003's replacement keeps its precision argument.)
- **Frozen bytes:** `reader.py` SYSTEM/SCHEMA/`DECISION_INTENT_SYSTEM`/`INTENT_SCHEMA`, `DIFF_BUDGET`, `MIN_RELEVANCE`/`RELATIVE_FLOOR` are untouched. Changing them is a new experiment, not engineering.
- **ADR-0007:** deviations never touch `verdicts.score`/`band`/`raw`. The check run renders them in a separate, clearly-advisory section; after the 2026-07-31 derangement-check FAIL (instrument invalid), that section must carry the label `unvalidated`.
- **Tier honesty:** a deterministic-fallback verdict must be visually distinct from a reader verdict in the check-run **title**, not a footnote (`review.py:118-142` falls back silently otherwise).
- **Tenancy identity:** all new writes carry `github_repo_id` (BIGINT, from the webhook payload / API, never parsed from the name); `repo` strings are display-only. Uniqueness key everywhere: `(installation_id, github_repo_id, pr_number, head_sha)`.
- **No migration framework exists** (`store.py:13-17`): `create_all()` adds missing tables only. New *tables* go in `store.metadata`; new *columns* on `verdicts` require the migration runner Task 2 introduces. Never add a bare column to an existing table without a migration — it will exist in tests and silently not in production.
- **Fork PRs are skipped at enqueue** (`head.repo.id != base.repo.id`) — the raw diff enters the prompt (`reader.py:169-176`), so outside contributors must not be able to drive spend.
- **`GITHUB_WEBHOOK_SECRET` is required at startup** (spec build-order step 1 leftover). The `gcp.sh` change (Task 10) MUST land in the same push as the startup requirement: prod's secret was set out-of-band via `services update` (2026-07-31) and the current `deploy()`'s `--set-secrets` **wipes it on the next CI deploy**.
- **Env names:** `DOUG_GITHUB_APP_ID` (plain env), `GITHUB_APP_PRIVATE_KEY` (PEM content via Secret Manager `doug-github-app-key`), `GITHUB_WEBHOOK_SECRET` (existing, `doug-webhook-secret:latest` = the stripped v2).
- **Python ≥3.14, ruff line-length 100, pytest from `api/`:** `cd api && uv run pytest -q` and `uv run ruff check .` must pass at every commit.
- **Commit style:** imperative subject, body explains why, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer. Commit directly on `main`, push after each task's final step.

## File Structure

```
api/doug/app_auth.py        NEW — App JWT + installation tokens (githubkit auth strategies)
api/doug/migrations.py      NEW — minimal ordered-DDL runner + migration 001 (verdicts columns)
api/doug/ingest.py          NEW — review_jobs queue ops: enqueue/supersede/claim/complete/fail
api/doug/worker.py          NEW — drain loop, per-job pipeline, reconcile (startup + install)
api/doug/check_run.py       NEW — render + post the neutral check run
api/doug/store.py           MOD — new tables (installations, installation_repos, review_jobs),
                                  migrations hook in _get_engine, save_review identity kwargs
api/doug/api.py             MOD — webhook rewrite + lifespan; DELETE /v1/review + ReviewResponse
api/deploy/gcp.sh           MOD — dedicated SA, new secrets/env, --no-cpu-throttling
api/deploy/doug-review.yml  DELETE — shared-token CI path retired
docs/decisions/ADR-0010-*.md NEW — check-run surface; ADR-0003 status → superseded
api/tests/test_app_auth.py, test_migrations.py, test_ingest.py, test_worker.py,
api/tests/test_check_run.py NEW; test_api.py, test_store.py MOD
```

## Locked Interfaces

Task implementers: these signatures are the contract between tasks. Do not rename.

```python
# app_auth.py
def enabled() -> bool                          # both env vars present
def app_client() -> GitHub                     # JWT-authed (AppAuthStrategy)
def installation_client(installation_id: int) -> GitHub  # AppInstallationAuthStrategy

# migrations.py
MIGRATIONS: list[tuple[int, tuple[str, ...]]]  # (version, DDL statements)
def apply(engine) -> list[int]                 # returns newly applied versions, idempotent

# store.py additions
installations       # Table: installation_id BIGINT UNIQUE, account_login, account_type,
                    #        state ('active'|'suspended'|'deleted'), updated_at
installation_repos  # Table: installation_id, github_repo_id BIGINT, full_name, state
                    #        ('active'|'removed'), updated_at; UNIQUE (installation_id, github_repo_id)
review_jobs         # Table: installation_id, github_repo_id, repo_full_name, pr_number,
                    #        head_sha, status ('pending'|'running'|'done'|'failed'|'superseded'),
                    #        attempts INT, enqueued_at, started_at, finished_at, error TEXT,
                    #        verdict_id NULLABLE;
                    #        UNIQUE (installation_id, github_repo_id, pr_number, head_sha)
def upsert_installation(installation_id, account_login, account_type, state) -> None
def set_installation_repos(installation_id, repos: list[tuple[int, str]], *, replace: bool) -> None
    # replace=True on installation created (authoritative list);
    # False merges added/removed deltas — removal passes state='removed', never DELETE
def save_review(..., github_repo_id=None, installation_id=None, head_sha=None, source=None)

# ingest.py  (returns job ids; None = duplicate suppressed by the unique index)
def enqueue(installation_id: int, github_repo_id: int, repo_full_name: str,
            pr_number: int, head_sha: str) -> int | None
    # also flips still-pending jobs for the same (installation, repo, pr) with a
    # DIFFERENT head_sha to 'superseded' — a push burst costs one read, not N
def claim() -> dict | None                     # SKIP LOCKED on postgres; row -> 'running'
def complete(job_id: int, verdict_id: int | None) -> None
def fail(job_id: int, error: str, *, max_attempts: int = 3) -> None
    # attempts+1; back to 'pending' below the cap, 'failed' at it

# worker.py
def process_job(job: dict) -> int | None       # full pipeline; returns verdict_id
def drain(max_jobs: int = 20) -> int           # claim loop; returns processed count
def reconcile_installation(installation_id: int) -> int   # enqueue open PRs; returns count
def reconcile_all() -> int                     # every active installation

# check_run.py
def render(tier: str, verdict: Verdict, intent_read: IntentRead | None,
           coverage: Coverage | None) -> tuple[str, str]   # (title, summary_md)
def post(gh: GitHub, owner: str, repo: str, head_sha: str,
         title: str, summary: str) -> None     # name="Doug", conclusion="neutral", never raises
```

**Webhook event gating (Task 6):**

| event | actions handled | effect |
|---|---|---|
| `ping` | — | 202 |
| `installation` | created / deleted / suspend / unsuspend | upsert state; `created` also sets repos (replace=True) + reconciles |
| `installation_repositories` | added / removed | merge repo deltas |
| `pull_request` | opened / synchronize / reopened / ready_for_review | gate: skip drafts, skip forks (`head.repo.id != base.repo.id`), then enqueue + kick drain |

Everything else: 202, ignored. The handler stays `async def` for `await request.body()` (signature needs raw bytes) but does **no** sync work inline: verify → parse → `run_in_threadpool` for DB writes → 202, with `BackgroundTasks` kicking `worker.drain` after the response. The 202 is sent only after the enqueue is durable.

---

## Tasks

### Task 1: App credentials (`app_auth.py`)
Deps: `githubkit[auth-app]`. New module, three functions above. Test with a throwaway RSA key generated in the test.

### Task 2: Migration runner + schema
`migrations.py` runner + migration 001 (four `ALTER TABLE verdicts ADD COLUMN …`), three new tables in `store.metadata`, `_get_engine` applies migrations after `create_all`, `save_review` identity kwargs, `upsert_installation`/`set_installation_repos`.

### Task 3: Queue ops (`ingest.py`)
`enqueue` (+supersede), `claim`, `complete`, `fail` with the exact semantics above.

### Task 4: Check run (`check_run.py`)
`render` (tier-honest title, neutral framing, findings, `unvalidated`-labeled deviations, coverage notice) + `post` (never raises; failures print to stderr).

### Task 5: Worker (`worker.py`)
`process_job` (installation client → `fetch_pr` → `score_one` → `read_intent` → `save_review(source='app', …)` → `save_deviations` → check run → `complete`), `drain`, failure handling through `ingest.fail`.

### Task 6: Webhook rewrite (`api.py`)
Lifespan requiring `GITHUB_WEBHOOK_SECRET`; event gating table above; keep the sha256 prefix pin (`api.py:365`); delete the unsigned-body branch and its test.

### Task 7: Reconcile (`worker.py`)
`reconcile_installation` / `reconcile_all`; called from lifespan startup and installation-created.

### Task 8: ADR-0010 + supersede ADR-0003
New record: the surface is a neutral check run; flip ADR-0003 `status: superseded`.

### Task 9: Retire the shared-token path
Delete `/v1/review`, `ReviewResponse`, `deploy/doug-review.yml`, their tests. `/v1/queue` keeps its interim token gate (step 3 replaces it). The `doug-review` CLI is untouched (direct, not via the endpoint).

### Task 10: Deploy + cutover
`gcp.sh`: dedicated `doug-api-sa`, secret bindings, `--service-account`, `--no-cpu-throttling`, `GITHUB_WEBHOOK_SECRET`/`GITHUB_APP_PRIVATE_KEY`/`DOUG_GITHUB_APP_ID` in `deploy()`. Manual pre-deploy IAM checklist (CI must never run `gcp.sh setup` — it rotates the DB password). Cutover checklist: flip App to "Any account", install on `lemahq/lema`, remove lema's workflow+secrets, disable `doug-webhook-secret` v1, verify a check run on a real PR.

*(Task bodies with full TDD steps are being drafted; this skeleton locks the contracts.)*
