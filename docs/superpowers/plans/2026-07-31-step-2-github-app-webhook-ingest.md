# Step 2: GitHub App + Webhook Ingest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the CI-token ingest path with webhook-driven review through the installed GitHub App (`dougs-review`, App ID 4450932, installation 150424894), surfacing verdicts as a neutral check run.

**Architecture:** The webhook handler verifies, records installation state, and enqueues durable jobs in Postgres — never reviewing inline. A threadpool drain claims jobs (`FOR UPDATE SKIP LOCKED` on Postgres), runs the existing review pipeline via short-lived installation tokens, persists with App identity columns, and posts a neutral check run. Missed deliveries are healed by reconciling open PRs by head SHA at startup and on new installations, not by trusting redelivery.

**Tech Stack:** FastAPI (existing), githubkit `[auth-app]` extra (adds PyJWT + cryptography), SQLAlchemy Core over Postgres 18 / file-backed sqlite in tests (existing), Cloud Run (existing).

**Spec:** `docs/superpowers/specs/2026-07-30-github-app-tenancy-dashboard-design.md` — this plan implements its "Build order" step 2 only. Steps 3–4 (WorkOS tenancy, dashboard) are separate plans.

**Execution order — Tasks 6/7 interleave by design:** run Tasks 1–5, then **Task 7 Steps 1–3** (the reconcile functions), then **Task 6** in full (webhook + lifespan), then **Task 7 Step 4 onward** (startup wiring into the lifespan Task 6 created), then Tasks 8–10. Task 6's installation-created branch calls `worker.reconcile_installation` (exists after 7/Step 3); Task 7's Step 4 anchors inside the lifespan (exists after Task 6). Both drafts fail loudly — `AttributeError`, missing anchor — if executed strictly sequentially; that is deliberate, do not patch around it with stubs.

**Concurrent-work collision, read before executing:** branch `fix/reliability-review` (worktree `.claude/worktrees/reliability-fixes`, off `d51eec8`) is in flight with reliability fixes including `/v1/review` idempotency and `gcp.sh` traffic-migration changes. Task 9 *deletes* `/v1/review` and Task 10 rewrites `deploy()`. Whoever executes second must rebase deliberately: the idempotency fix dies with the endpoint (correct — its semantics move to the `review_jobs` unique index), and the gated-traffic deploy change must be merged INTO Task 10's version, not clobbered.

## Global Constraints

- **Never blocks:** every check run concludes `neutral`. No conclusion may ever be `failure`/`action_required`. (ADR-0003's replacement keeps its precision argument.)
- **Frozen bytes:** `reader.py` SYSTEM/SCHEMA/`DECISION_INTENT_SYSTEM`/`INTENT_SCHEMA`, `DIFF_BUDGET`, `MIN_RELEVANCE`/`RELATIVE_FLOOR` are untouched. Changing them is a new experiment, not engineering.
- **ADR-0007:** deviations never touch `verdicts.score`/`band`/`raw`. The check run renders them in a separate, clearly-advisory section; after the 2026-07-31 derangement-check FAIL (instrument invalid), that section must carry the label `unvalidated`.
- **Tier honesty:** a deterministic-fallback verdict must be visually distinct from a reader verdict in the check-run **title**, not a footnote (`review.py:118-142` falls back silently otherwise).
- **Tenancy identity:** all new writes carry `github_repo_id` (BIGINT, from the webhook payload / API, never parsed from the name); `repo` strings are display-only. Uniqueness key everywhere: `(installation_id, github_repo_id, pr_number, head_sha)`.
- **No migration framework exists before Task 2** (`store.py:13-17` — that paragraph is rewritten by Task 2 in the same commit that makes it false): `create_all()` adds missing tables only. New *tables* go in `store.metadata`; new *columns* on `verdicts` exist in BOTH the table definition (fresh databases) and migration 001 (existing databases), with a drift test pinning the two together. Never add a bare column — or a bare *index* — to an existing table outside a migration; it will exist in tests and silently not in production.
- **Unsigned-body handling is already fail-closed** (commit `0d58554`, `api.py:353-360`): nothing to delete. Task 6 keeps that 503 branch as defence in depth and adds the genuinely missing coverage (delivery with no signature header at all).
- **Fork PRs are skipped at enqueue** (`head.repo.id != base.repo.id`) — the raw diff enters the prompt (`_user_text`, `reader.py:179-187`), so outside contributors must not be able to drive spend.
- **`GITHUB_WEBHOOK_SECRET` is required at startup** (lifespan, Task 6). `gcp.sh:91` already ships it via `--set-secrets` (added by #14), so CI deploys preserve it — the prod pin to `:2` (set out-of-band 2026-07-31) reverts to `:latest` on the next deploy, which resolves to the same v2 value. What CI deploys DO wipe until Task 10 lands is the **App credentials** (`DOUG_GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` are absent from the current script): harmless by design — `app_auth.enabled()` → False, no paid reads — and healed by Task 7's startup reconcile once Task 10 makes them permanent.
- **Env names:** `DOUG_GITHUB_APP_ID` (plain env), `GITHUB_APP_PRIVATE_KEY` (PEM content via Secret Manager `doug-github-app-key`), `GITHUB_WEBHOOK_SECRET` (existing, `doug-webhook-secret:latest` = the stripped v2; v1 carries a trailing newline and gets disabled at cutover).
- **Python ≥3.14, ruff line-length 100, pytest from `api/`:** `cd api && uv run pytest -q` and `uv run ruff check .` must pass at every commit.
- **Commit style:** imperative subject, body explains why, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.

## File Structure

```
api/doug/app_auth.py        NEW — App JWT + installation tokens (githubkit auth strategies)
api/doug/migrations.py      NEW — minimal ordered-DDL runner + migration 001 (verdicts columns)
api/doug/ingest.py          NEW — review_jobs queue ops: enqueue/claim/release/complete/supersede/fail
api/doug/worker.py          NEW — drain loop, per-job pipeline, reconcile (startup + install)
api/doug/check_run.py       NEW — render + post the neutral check run
api/doug/store.py           MOD — new tables (installations, installation_repos, review_jobs),
                                  migrations hook, save_review identity kwargs, upsert/set/read helpers
api/doug/api.py             MOD — webhook rewrite + lifespan; DELETE /v1/review + ReviewResponse
api/deploy/gcp.sh           MOD — dedicated SA, new secrets/env, --no-cpu-throttling
api/deploy/doug-review.yml  DELETE — shared-token CI template retired
.github/workflows/doug-review.yml DELETE — this repo's own CI ingest (ADR-0008 correction in same commit)
docs/decisions/ADR-0010-surface-is-a-neutral-check-run.md NEW; ADR-0003 status → superseded;
docs/decisions/ADR-0008-*.md MOD — stop naming the retired workflow as the mechanism
api/tests/: test_app_auth.py, test_migrations.py, test_ingest.py, test_worker.py,
            test_check_run.py NEW; test_api.py, test_store.py MOD;
            test_workflow_summary.py DELETE (its subject is deleted in Task 9)
```

## Locked Interfaces

Task implementers: these signatures are the contract between tasks. Do not rename. (Three amendments vs. the original skeleton, all discovered in drafting or review and consistent across all task bodies: `set_installation_repos` gained the keyword-only `state` its own removal semantics required; `enqueue` raises rather than no-ops on a missing ledger; `release`/`supersede` were added so drain and the stale-head guard never spend an attempt or strand a SHA. One invariant is deliberately un-obvious: `supersede()` leaves the row in a status `enqueue` revives, so a force-push BACK to an old SHA re-queues it — pinned by a test; do not "tidy" it into its own status.)

```python
# app_auth.py
def enabled() -> bool                          # both env vars present
def app_client() -> GitHub                     # JWT-authed (AppAuthStrategy)
def installation_client(installation_id: int) -> GitHub  # AppInstallationAuthStrategy

# migrations.py
MIGRATIONS: list[tuple[int, tuple[str, ...]]]  # (version, DDL statements)
def apply(engine) -> list[int]                 # newly applied versions; idempotent; treats
                                               # "duplicate column" as satisfied (fresh DBs
                                               # already have the post-migration shape)

# store.py additions
installations       # Table: installation_id BIGINT UNIQUE, account_login, account_type,
                    #        state ('active'|'suspended'|'deleted'), updated_at
installation_repos  # Table: installation_id, github_repo_id BIGINT, full_name, state
                    #        ('active'|'removed'), updated_at; UNIQUE (installation_id, github_repo_id)
review_jobs         # Table: installation_id, github_repo_id, repo_full_name, pr_number,
                    #        head_sha, status ('pending'|'running'|'done'|'failed'|'superseded'),
                    #        attempts INT, enqueued_at, started_at, finished_at, error TEXT,
                    #        verdict_id ForeignKey("verdicts.id") NULLABLE — Postgres enforces it,
                    #        so complete() takes a real save_review id or None, never a placeholder;
                    #        UNIQUE (installation_id, github_repo_id, pr_number, head_sha)
def upsert_installation(installation_id, account_login, account_type, state) -> None
def set_installation_repos(installation_id: int, repos: list[tuple[int, str]], *,
                           replace: bool, state: str = "active") -> None
    # replace=True on installation created (authoritative full list);
    # replace=False merges deltas — 'removed' passes state="removed", rows are marked, never DELETEd
def save_review(..., github_repo_id=None, installation_id=None, head_sha=None, source=None)
# read helpers land in Task 7 (additive, agreed across drafts; narrow on purpose —
# reconcile needs ids and names, nothing else):
def active_installations() -> list[int]
def active_repos(installation_id: int) -> list[tuple[int, str]]   # (github_repo_id, full_name)

# ingest.py
def enqueue(installation_id: int, github_repo_id: int, repo_full_name: str,
            pr_number: int, head_sha: str) -> int | None
    # Collision on the unique index: if the existing row is 'failed' or 'superseded' it is
    #   REVIVED (status='pending', attempts=0, error=NULL, enqueued_at=now) and its id
    #   returned — this is how reconcile heals errored/stale work; bounded, a poison PR
    #   costs max_attempts per reconcile, never unbounded. pending/running/done collide
    #   to None (that IS the dedupe).
    # Supersede runs AFTER a successful insert, same transaction: flips still-pending jobs
    #   of the same (installation, repo, pr) with a different head_sha to 'superseded'. A
    #   replayed delivery collides first and supersedes nothing (out-of-order safety; the
    #   worker-side head guard in process_job is the other half).
    # RAISES RuntimeError when DATABASE_URL is unset — None already means "already queued",
    #   and a silent no-op would 202 every delivery while reviewing nothing.
def claim() -> dict | None                     # plain dict, PK under "id"; oldest first by
                                               # (enqueued_at, id); SKIP LOCKED on postgres;
                                               # None when empty OR storage disabled
                                               # (drain stays a safe startup no-op)
def complete(job_id: int, verdict_id: int | None) -> None
def release(job_id: int) -> None               # back to 'pending', started_at=NULL, NO attempt
                                               # spent — drain's seen-set uses it when it
                                               # re-claims a job re-pended this same run
def supersede(job_id: int) -> None             # status='superseded' + finished_at — the
                                               # worker's stale-head guard uses it
def fail(job_id: int, error: str, *, max_attempts: int = 3) -> None
    # attempts+1; back to 'pending' below the cap with enqueued_at bumped to now (sends the
    # retry to the back of the queue), 'failed' at the cap; error truncated to 500 chars

# worker.py
def process_job(job: dict) -> int | None       # full pipeline; returns verdict_id. Guards
                                               # stale heads: if the PR's CURRENT head sha
                                               # differs from job["head_sha"], the job is
                                               # superseded and the current head enqueued —
                                               # converges on the true head regardless of
                                               # delivery order.
def drain(max_jobs: int = 20) -> int           # claim loop; a failing job never stops the
                                               # loop; a seen-set stops re-claiming a job
                                               # re-pended within this same run
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
| `ping` | — | 202 (before the ledger guard, so an install's connectivity test always answers) |
| `installation` | created / deleted / suspend / unsuspend | upsert state; `created` also sets repos (replace=True) + reconciles in background |
| `installation_repositories` | added / removed | merge repo deltas (added → state="active", removed → state="removed") |
| `pull_request` | opened / synchronize / reopened / ready_for_review | gate: skip drafts, skip forks (`head.repo.id != base.repo.id`), then enqueue + kick drain |

Everything else: 202, ignored, without touching the store. The handler stays `async def` for `await request.body()` (signature needs raw bytes) but does **no** sync work inline: verify → parse → `run_in_threadpool` for DB writes → 202, with `BackgroundTasks` kicking `worker.drain` after the response (installation-created chains reconcile **then drain** in one background task). The 202 is sent only after the enqueue is durable. `if not store.enabled()`: 503 — scoped to the **three handled event types only**, not the lifespan and not unknown events, because ledger-less mode is a deliberate feature of the rest of the API (`store.py:9-11`) and pre-existing deliveries without an event header must keep answering 202.

---

## Tasks
### Task 1: App credentials (`api/doug/app_auth.py`)

**Files:**
- Modify: `api/pyproject.toml:10` (`    "githubkit>=0.16.0",` → the `[auth-app]` extra), `api/uv.lock` (regenerated)
- Create: `api/doug/app_auth.py`
- Test: `api/tests/test_app_auth.py`

**Interfaces:**
- Consumes: nothing from this repo. `githubkit.AppAuthStrategy(app_id, private_key, …)` and `githubkit.AppInstallationAuthStrategy(app_id, private_key, installation_id, …)` — both are exported from the `githubkit` top level in 0.16.0, and `GitHub(strategy).auth` is the strategy instance.
- Produces:
  ```python
  def enabled() -> bool
  def app_client() -> GitHub                                # AppAuthStrategy
  def installation_client(installation_id: int) -> GitHub   # AppInstallationAuthStrategy
  ```
  Task 5 (`worker.process_job`) and Task 7 (`reconcile_*`) call `installation_client`; Task 7's `reconcile_all` calls `app_client`.

- [ ] **Step 1: Add the dependency**

This comes before the test on purpose: the test generates its RSA key with `cryptography`, which arrives only as `pyjwt[crypto]`'s dependency under this extra. Without it Step 3 fails on a missing test-side import rather than on the missing module.

Edit `api/pyproject.toml:10`, replacing:
```toml
    "githubkit>=0.16.0",
```
with:
```toml
    "githubkit[auth-app]>=0.16.0",
```
Run: `cd api && uv sync`  Expected: installs `pyjwt` and `cryptography`; `uv.lock` updates.

- [ ] **Step 2: Write the failing test**

Create `api/tests/test_app_auth.py`:
```python
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from githubkit import AppAuthStrategy, AppInstallationAuthStrategy

from doug import app_auth

APP_ID = "4450932"
INSTALLATION_ID = 150424894


def _pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


# Generated once: key generation is the slowest thing in this file, and no
# test here needs a key that differs from any other. Nothing reaches GitHub —
# these assertions are about which credential a client carries, which is
# exactly the question a real App key must never be checked into a test to
# answer.
PEM = _pem()


def _configured(monkeypatch, pem: str = PEM) -> None:
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", pem)


def test_disabled_without_the_app_id(monkeypatch):
    """Half-configured is off, not degraded. A deployment holding the key but
    no app id cannot sign anything, and discovering that at the first webhook
    turns a config mistake into a paid-path outage."""
    monkeypatch.delenv("DOUG_GITHUB_APP_ID", raising=False)
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", PEM)
    assert not app_auth.enabled()


def test_disabled_without_the_private_key(monkeypatch):
    monkeypatch.setenv("DOUG_GITHUB_APP_ID", APP_ID)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    assert not app_auth.enabled()


def test_enabled_with_both(monkeypatch):
    _configured(monkeypatch)
    assert app_auth.enabled()


def test_app_client_carries_the_app_identity(monkeypatch):
    """The JWT strategy is what makes a call the App rather than a user. A
    client built with the wrong strategy fails at GitHub with a 401 that says
    nothing about which of the two credentials was missing."""
    _configured(monkeypatch)
    gh = app_auth.app_client()
    assert isinstance(gh.auth, AppAuthStrategy)
    assert str(gh.auth.app_id) == APP_ID


def test_installation_client_carries_the_installation(monkeypatch):
    """An installation token is scoped to one installation for one hour, so
    the installation id has to travel with the client rather than being
    remembered by the caller. Getting this wrong reads another tenant's
    repositories, which is the one failure mode with no safe degradation."""
    _configured(monkeypatch)
    gh = app_auth.installation_client(INSTALLATION_ID)
    assert isinstance(gh.auth, AppInstallationAuthStrategy)
    assert gh.auth.installation_id == INSTALLATION_ID
    assert str(gh.auth.app_id) == APP_ID


def test_each_installation_gets_its_own_client(monkeypatch):
    """No caching. The worker processes jobs from many installations through
    the same process, and a shared client would carry the first tenant's token
    into every job after it."""
    _configured(monkeypatch)
    a = app_auth.installation_client(1)
    b = app_auth.installation_client(2)
    assert a is not b
    assert (a.auth.installation_id, b.auth.installation_id) == (1, 2)


def test_an_escaped_pem_is_repaired(monkeypatch):
    """Secret Manager delivers real newlines; a PEM pasted into a shell env or
    a .env file arrives with them escaped, and PyJWT rejects that with an
    opaque key-format error at the first API call rather than at startup."""
    _configured(monkeypatch, PEM.replace("\n", "\\n"))
    gh = app_auth.app_client()
    assert gh.auth.private_key == PEM


def test_clients_refuse_when_unconfigured(monkeypatch):
    """enabled() is the check callers make; this is what happens when one
    forgets. Constructing a client with a None app id would defer the failure
    to a 401 from GitHub."""
    monkeypatch.delenv("DOUG_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DOUG_GITHUB_APP_ID"):
        app_auth.app_client()
    with pytest.raises(RuntimeError, match="DOUG_GITHUB_APP_ID"):
        app_auth.installation_client(INSTALLATION_ID)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_app_auth.py -q`
Expected: collection error — `ImportError: cannot import name 'app_auth' from 'doug'`.

- [ ] **Step 4: Write minimal implementation**

Create `api/doug/app_auth.py`:
```python
"""GitHub App credentials — the identity every App-driven call runs under.

Two secrets, both required together: DOUG_GITHUB_APP_ID (plain env) and
GITHUB_APP_PRIVATE_KEY (the PEM, from Secret Manager). Opt-in like
reader.enabled(): a deployment without both simply has no App path, and
callers check rather than catching.

Clients are built per call, not cached. githubkit's strategies mint and
refresh their own JWT / installation token, and an installation token is
scoped to one installation for one hour — a shared client would be the
wrong tenant's credential for every request after the first.
"""

import os

from githubkit import AppAuthStrategy, AppInstallationAuthStrategy, GitHub


def enabled() -> bool:
    return bool(os.environ.get("DOUG_GITHUB_APP_ID") and os.environ.get("GITHUB_APP_PRIVATE_KEY"))


def _credentials() -> tuple[str, str]:
    if not enabled():
        raise RuntimeError("DOUG_GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must both be set")
    # Secret Manager delivers real newlines, but a PEM pasted into a shell
    # env or a .env file arrives with them escaped, and PyJWT rejects that
    # with an opaque key-format error. Base64 never contains a backslash,
    # so this is safe on a well-formed key.
    key = os.environ["GITHUB_APP_PRIVATE_KEY"].replace("\\n", "\n")
    return os.environ["DOUG_GITHUB_APP_ID"], key


def app_client() -> GitHub:
    """App-level JWT client — installation discovery and token minting only."""
    app_id, key = _credentials()
    return GitHub(AppAuthStrategy(app_id=app_id, private_key=key))


def installation_client(installation_id: int) -> GitHub:
    """A client scoped to one installation's repositories."""
    app_id, key = _credentials()
    return GitHub(
        AppInstallationAuthStrategy(
            app_id=app_id, private_key=key, installation_id=installation_id
        )
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_app_auth.py -q && uv run pytest -q && uv run ruff check .`
Expected: 8 passed in the first run; the full suite green; ruff clean.

- [ ] **Step 6: Commit**

```
git add api/pyproject.toml api/uv.lock api/doug/app_auth.py api/tests/test_app_auth.py
git commit -m "Add GitHub App credential module" -m "The webhook path needs an identity of its own: the CI path took a caller-supplied token per request, and there is no caller to supply one when GitHub delivers an event. App JWT and per-installation tokens are the only credentials that work, and githubkit's [auth-app] extra already mints and refreshes both.

Clients are built per call rather than cached. An installation token is one tenant for one hour, so a module-level client would carry the first installation's credential into every job after it.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```

---

### Task 2: Migration runner + schema (`api/doug/migrations.py` + `store.py`)

**Files:**
- Create: `api/doug/migrations.py`
- Modify: `api/doug/store.py:13-17` (docstring paragraph), `:23-35` (imports), `:60-61` (verdicts columns), `:127-129` (three new tables), `:138-139` (migrations hook), `:154-156` + `:163-164` (save_review signature and docstring), `:183-184` (insert values), `:220-221` (new helpers before `save_read`)
- Test: `api/tests/test_migrations.py` (new), `api/tests/test_store.py:315` (appended)

**Interfaces:**
- Consumes: `store.metadata`, `store._get_engine()`, `store.save_review(...)` as they stand today.
- Produces:
  ```python
  # migrations.py
  MIGRATIONS: list[tuple[int, tuple[str, ...]]]
  schema_migrations              # Table on a private MetaData
  def apply(engine) -> list[int]

  # store.py
  installations, installation_repos, review_jobs      # Tables in store.metadata
  def upsert_installation(installation_id, account_login, account_type, state) -> None
  def set_installation_repos(installation_id, repos, *, replace, state="active") -> None
  def save_review(..., github_repo_id=None, installation_id=None, head_sha=None, source=None)
  ```
  Task 3 uses `store.review_jobs` and `store._get_engine`; Task 5 uses `save_review`'s identity kwargs; Task 6 uses both installation helpers. The read-side helpers `store.active_installations()` and `store.active_repos(installation_id)` are Task 7's, not this task's — this task writes those tables, Task 7 reads them.

- **Amended locked signature, ratified:** `set_installation_repos(installation_id: int, repos: list[tuple[int, str]], *, replace: bool, state: str = "active") -> None`. The original locked comment said removal "passes `state='removed'`" while its argument list had nowhere to pass it from; the keyword-only `state` closes that, after the existing `*`, leaving every other name and position untouched. Task 6's `installation_repositories` handler consumes exactly this shape — `replace=False` for the added delta, `replace=False, state="removed"` for the removed one. Rows are marked, never DELETEd.

#### Cycle A — the runner

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_migrations.py`:
```python
from sqlalchemy import create_engine, inspect, select

from doug import migrations, store

APP_COLUMNS = {"github_repo_id", "installation_id", "head_sha", "source"}


def _columns(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_apply_adds_the_columns_to_a_database_built_by_an_older_schema(tmp_path):
    """The case create_all() cannot handle, and the only reason this module
    exists. Production's `verdicts` was created before the App columns and
    create_all() adds missing tables, never missing columns.

    The table is built by hand rather than from store.metadata on purpose: a
    test that starts from today's metadata can only exercise the path that was
    never broken.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE verdicts (id INTEGER PRIMARY KEY, repo VARCHAR(200) NOT NULL)"
        )
    assert migrations.apply(engine) == [1]
    assert APP_COLUMNS <= _columns(engine, "verdicts")


def test_apply_on_a_freshly_created_schema_records_without_erroring(tmp_path):
    """The same divergence from the other side. A fresh database already has
    the App columns from create_all(), so migration 001 has nothing to do —
    and if "nothing to do" raised, every test run and every new deployment
    would die inside _get_engine on a statement that is only meaningful
    against the older production table.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/fresh.db")
    store.metadata.create_all(engine)
    assert APP_COLUMNS <= _columns(engine, "verdicts")

    assert migrations.apply(engine) == [1]
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(select(migrations.schema_migrations.c.version))]
    assert versions == [1]


def test_apply_reports_only_newly_applied_versions(tmp_path):
    """apply() runs on every engine creation, not once at deploy time, so a
    second call re-running migration 001 would raise on the duplicate column
    and take the process down at first ledger use."""
    engine = create_engine(f"sqlite:///{tmp_path}/twice.db")
    store.metadata.create_all(engine)
    assert migrations.apply(engine) == [1]
    assert migrations.apply(engine) == []


def test_migration_001_declares_the_same_columns_as_the_verdicts_table(tmp_path):
    """The App columns are written down twice — in store.verdicts, which is
    what a fresh database gets, and in migration 001, which is what production
    gets. Nothing else stops the two from drifting, and drift is invisible
    until a production INSERT names a column that is not there."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl.db")
    store.metadata.create_all(engine)
    altered = {s.split("ADD COLUMN ")[1].split()[0] for s in dict(migrations.MIGRATIONS)[1]}
    assert altered == APP_COLUMNS
    assert altered <= _columns(engine, "verdicts")


def test_get_engine_applies_migrations(tmp_path, monkeypatch):
    """The hook, not the runner: a migration nobody calls is a comment."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/hooked.db")
    engine = store._get_engine()
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(select(migrations.schema_migrations.c.version))]
    assert versions == [v for v, _ in migrations.MIGRATIONS]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_migrations.py -q`
Expected: collection error — `ImportError: cannot import name 'migrations' from 'doug'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/doug/migrations.py`:
```python
"""Ordered DDL for changes create_all() cannot make.

store.py's create_all() adds missing *tables* and never adds a column to a
table that already exists. Every new column on `verdicts` therefore has two
homes that must agree: the Table definition (which is what a fresh database
gets) and a migration here (which is what production's existing database
gets). apply() runs after create_all() on every engine, so both paths end at
the same schema instead of diverging into a green test suite and a broken
production write.

A statement that finds its work already done is satisfied, not failed: on a
fresh database create_all() has already produced the post-migration shape,
so migration 001's ALTERs are no-ops there and must not raise. Anything else
propagates.
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, select
from sqlalchemy.exc import DatabaseError

# Its own MetaData: this table has to exist before store.metadata is created
# and must never be dropped alongside it.
_meta = MetaData()

schema_migrations = Table(
    "schema_migrations",
    _meta,
    Column("version", Integer, primary_key=True, autoincrement=False),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)

# Plain DDL strings, valid on both sqlite and Postgres. No IF NOT EXISTS:
# sqlite rejects it on ADD COLUMN, so idempotency comes from the version
# table plus _SATISFIED below. No indexes here either — an index created by
# create_all() but not by a migration is the same divergence in a new place.
MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            "ALTER TABLE verdicts ADD COLUMN github_repo_id BIGINT",
            "ALTER TABLE verdicts ADD COLUMN installation_id BIGINT",
            "ALTER TABLE verdicts ADD COLUMN head_sha VARCHAR(64)",
            "ALTER TABLE verdicts ADD COLUMN source VARCHAR(20)",
        ),
    ),
]

_SATISFIED = ("duplicate column name", "already exists")


def _run(engine, statement: str) -> None:
    # One transaction per statement: on Postgres a failed statement poisons
    # the whole transaction, and the already-satisfied case has to leave the
    # connection usable for the rest of the migration.
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(statement)
    except DatabaseError as e:
        if not any(m in str(e).lower() for m in _SATISFIED):
            raise


def apply(engine) -> list[int]:
    """Run every unapplied migration in order. Returns the versions applied."""
    schema_migrations.create(engine, checkfirst=True)
    with engine.connect() as conn:
        done = {r[0] for r in conn.execute(select(schema_migrations.c.version))}
    applied: list[int] = []
    for version, statements in MIGRATIONS:
        if version in done:
            continue
        for statement in statements:
            _run(engine, statement)
        with engine.begin() as conn:
            conn.execute(
                schema_migrations.insert(),
                {"version": version, "applied_at": datetime.now(UTC)},
            )
        applied.append(version)
    return applied
```

- [ ] **Step 4: Run tests to verify they fail on the right thing now**

Run: `cd api && uv run pytest tests/test_migrations.py -q`
Expected: 2 passed, 3 failed. `test_apply_adds_the_columns_to_a_database_built_by_an_older_schema` and `test_apply_reports_only_newly_applied_versions` PASS — neither consults `store.verdicts`. The other three fail, in two different ways: the two that assert against `store.metadata` fail on `AssertionError: assert {'github_repo_id', 'installation_id', 'head_sha', 'source'} <= {...}` because `store.verdicts` does not declare the columns yet, and `test_get_engine_applies_migrations` fails on `sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: schema_migrations` because `_get_engine` does not call `apply` yet. Cycle B closes all three.

#### Cycle B — the schema and the hook

- [ ] **Step 5: Write the failing test**

Append to `api/tests/test_store.py` (after line 315):
```python

INSTALL = 150424894
REPO_ID = 900001


def test_save_review_records_app_identity(tmp_path, monkeypatch):
    """`repo` is a display string that changes the moment a repo is renamed,
    and every tenancy question this ledger will be asked — which installation,
    which repo, which commit — has to survive that rename. The identity
    columns are the only answer that does."""
    url = _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        model=reader.MODEL,
        github_repo_id=REPO_ID,
        installation_id=INSTALL,
        head_sha="a" * 40,
        source="app",
    )
    engine = create_engine(url)
    with engine.connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
    assert v["id"] == vid
    assert v["github_repo_id"] == REPO_ID and v["installation_id"] == INSTALL
    assert v["head_sha"] == "a" * 40 and v["source"] == "app"


def test_save_review_leaves_identity_null_for_the_ci_path(tmp_path, monkeypatch):
    """Every row written before the App existed has no installation, and the
    CLI still writes rows that never had one. Null has to mean that rather
    than being backfilled with a guess."""
    url = _db(tmp_path, monkeypatch)
    store.save_review("o/r", 7, "deterministic", VERDICT)
    with create_engine(url).connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
    assert v["installation_id"] is None and v["source"] is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_store.py -q`
Expected: FAIL — `TypeError: save_review() got an unexpected keyword argument 'github_repo_id'`.

- [ ] **Step 7: Write minimal implementation**

Replace `api/doug/store.py:13-17`:
```python
There is still no migration framework, which is a real constraint and not
just a deferral: create_all() adds missing *tables* and never adds a column
to a table that already exists. New facts therefore arrive as new tables
(see `reads`) until that changes. A column added to `verdicts` today would
appear in every test and in no production row.
```
with:
```python
create_all() adds missing *tables* and never adds a column to a table that
already exists, so several facts here live in tables of their own (see
`reads`) rather than as columns on `verdicts`. Columns that must go on an
existing table now go through migrations.apply(), which runs on the same
engine right after create_all(); a column added to the Table definition
alone would appear in every test and in no production row.
```

In the import block, add `BigInteger` after `JSON,` (line 24), and replace lines 32-37:
```python
    Table,
    Text,
    create_engine,
)

from .models import Verdict
```
with:
```python
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    select,
    update,
)

from . import migrations
from .models import Verdict
```
(`pattern_join` and `latest_reviews` keep their local `from sqlalchemy import func, select` — untouched, and legal alongside the module-level name.)

Replace lines 59-61:
```python
    # PR metadata as scored — the queue dashboard reads verdicts alone.
    Column("pr_meta", JSON),
)
```
with:
```python
    # PR metadata as scored — the queue dashboard reads verdicts alone.
    Column("pr_meta", JSON),
    # App identity. Added to an existing table, so these four are also
    # migration 001 — the two definitions must stay identical or a fresh
    # database and production diverge. Unindexed on purpose: create_all()
    # would build an index here that no migration builds there.
    Column("github_repo_id", BigInteger),
    Column("installation_id", BigInteger),
    Column("head_sha", String(64)),
    Column("source", String(20)),  # app | ci | cli
)
```

Insert the three tables between the end of `deviations` (line 127) and `_engine = None` (line 129):
```python
# Who installed Doug where. The webhook is the only writer; a row is never
# deleted, because "this installation was removed on the 3rd" is a fact the
# ledger's verdicts still refer to.
installations = Table(
    "installations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False, unique=True),
    Column("account_login", String(200)),
    Column("account_type", String(20)),  # User | Organization
    Column("state", String(20), nullable=False),  # active | suspended | deleted
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

installation_repos = Table(
    "installation_repos",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False, index=True),
    Column("github_repo_id", BigInteger, nullable=False),
    Column("full_name", String(200), nullable=False),  # display only
    Column("state", String(20), nullable=False),  # active | removed
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("installation_id", "github_repo_id", name="uq_installation_repo"),
)

# The durable gap between a delivery and a review. The unique constraint is
# the deduplication mechanism, not an integrity afterthought: two deliveries
# of one push race often enough that a check-then-insert would pay for the
# same model read twice.
review_jobs = Table(
    "review_jobs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False),
    Column("github_repo_id", BigInteger, nullable=False),
    Column("repo_full_name", String(200), nullable=False),  # display only
    Column("pr_number", Integer, nullable=False),
    Column("head_sha", String(64), nullable=False),
    # pending | running | done | failed | superseded
    Column("status", String(12), nullable=False, index=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("enqueued_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("error", Text),
    Column("verdict_id", Integer, ForeignKey("verdicts.id")),
    UniqueConstraint(
        "installation_id", "github_repo_id", "pr_number", "head_sha", name="uq_review_job"
    ),
)
```

Replace lines 138-139:
```python
        _engine = create_engine(url, pool_pre_ping=True)
        metadata.create_all(_engine)
```
with:
```python
        _engine = create_engine(url, pool_pre_ping=True)
        metadata.create_all(_engine)
        # create_all() cannot add a column to a table that already exists.
        # Production's `verdicts` predates the App columns, so the two paths
        # only agree if this runs on every engine, not just the new ones.
        migrations.apply(_engine)
```

Replace lines 154-156:
```python
    pr_meta: dict | None = None,
    coverage: Coverage | None = None,
) -> int | None:
```
with:
```python
    pr_meta: dict | None = None,
    coverage: Coverage | None = None,
    github_repo_id: int | None = None,
    installation_id: int | None = None,
    head_sha: str | None = None,
    source: str | None = None,
) -> int | None:
```

Replace lines 163-164:
```python
    about writing it needed to be a separate round trip.
    """
```
with:
```python
    about writing it needed to be a separate round trip.

    The identity kwargs are None for every pre-App row and for the CLI, which
    has no installation. `github_repo_id` is the only stable repo identity —
    `repo` is a display string that changes when a repo is renamed.
    """
```

Replace lines 183-184:
```python
                "pr_meta": pr_meta,
            },
```
with:
```python
                "pr_meta": pr_meta,
                "github_repo_id": github_repo_id,
                "installation_id": installation_id,
                "head_sha": head_sha,
                "source": source,
            },
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_migrations.py tests/test_store.py -q`
Expected: all pass — 5 migration tests, 22 store tests (20 pre-existing + the 2 just appended).

#### Cycle C — the installation helpers

- [ ] **Step 9: Write the failing test**

Append to `api/tests/test_store.py`:
```python


def test_upsert_installation_updates_state_in_place(tmp_path, monkeypatch):
    """Suspend and unsuspend arrive as repeated events for one installation.
    Inserting a second row would leave two answers to "is this tenant active"
    and no rule for picking one."""
    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALL, "drewjst", "User", "active")
    store.upsert_installation(INSTALL, "drewjst", "User", "suspended")
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.installations)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["state"] == "suspended" and rows[0]["account_login"] == "drewjst"


def test_installation_created_replaces_the_whole_repo_list(tmp_path, monkeypatch):
    """The installation payload carries the authoritative list. A reinstall
    that dropped a repo must not leave it active — Doug would keep reviewing a
    repo the customer removed it from."""
    url = _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALL, [(1, "o/a"), (2, "o/b")], replace=True)
    store.set_installation_repos(INSTALL, [(2, "o/b")], replace=True)
    with create_engine(url).connect() as conn:
        rows = {
            r["github_repo_id"]: r["state"]
            for r in conn.execute(select(store.installation_repos)).mappings()
        }
    assert rows == {1: "removed", 2: "active"}


def test_repo_deltas_merge_without_touching_the_rest(tmp_path, monkeypatch):
    """installation_repositories events are deltas, not snapshots. Treating
    one as authoritative would remove every repo it did not mention."""
    url = _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALL, [(1, "o/a"), (2, "o/b")], replace=True)
    store.set_installation_repos(INSTALL, [(3, "o/c")], replace=False)
    store.set_installation_repos(INSTALL, [(1, "o/a")], replace=False, state="removed")
    with create_engine(url).connect() as conn:
        rows = {
            r["github_repo_id"]: r["state"]
            for r in conn.execute(select(store.installation_repos)).mappings()
        }
    assert rows == {1: "removed", 2: "active", 3: "active"}


def test_a_removed_repo_keeps_its_row(tmp_path, monkeypatch):
    """Verdicts outlive access. Deleting the row would break the join that
    explains where a stored verdict came from, and uninstall-then-reinstall is
    a support case that needs the history."""
    url = _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALL, [(1, "o/a")], replace=True)
    store.set_installation_repos(INSTALL, [], replace=True)
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.installation_repos)).mappings().all()
    assert len(rows) == 1 and rows[0]["state"] == "removed"
```

- [ ] **Step 10: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_store.py -q`
Expected: FAIL — `AttributeError: module 'doug.store' has no attribute 'upsert_installation'`.

- [ ] **Step 11: Write minimal implementation**

Insert into `api/doug/store.py` immediately before `def save_read(` (line 221):
```python
def upsert_installation(
    installation_id: int, account_login: str, account_type: str, state: str
) -> None:
    """Record an installation's current state. Never deletes: a suspended or
    deleted installation is a state the verdicts it produced still point at."""
    engine = _get_engine()
    if engine is None:
        return
    values = {
        "account_login": account_login,
        "account_type": account_type,
        "state": state,
        "updated_at": datetime.now(UTC),
    }
    with engine.begin() as conn:
        row = conn.execute(
            select(installations.c.id).where(installations.c.installation_id == installation_id)
        ).scalar_one_or_none()
        if row is None:
            conn.execute(installations.insert(), {"installation_id": installation_id, **values})
        else:
            conn.execute(update(installations).where(installations.c.id == row).values(**values))


def set_installation_repos(
    installation_id: int,
    repos: list[tuple[int, str]],
    *,
    replace: bool,
    state: str = "active",
) -> None:
    """Record which repos an installation covers.

    `replace=True` treats `repos` as authoritative — anything else on this
    installation flips to 'removed'. That is the installation-created event,
    which carries the full list. `replace=False` merges a delta, and the
    caller says which delta it is: the `installation_repositories` webhook
    sends added and removed in one payload, so removals arrive as their own
    call with state='removed'.

    Rows are never DELETEd. A removed repo's verdicts stay in the ledger and
    the join that explains them has to keep resolving.
    """
    engine = _get_engine()
    if engine is None:
        return
    now = datetime.now(UTC)
    ids = [r[0] for r in repos]
    with engine.begin() as conn:
        if replace:
            stale = (
                update(installation_repos)
                .where(installation_repos.c.installation_id == installation_id)
                .values(state="removed", updated_at=now)
            )
            if ids:
                stale = stale.where(installation_repos.c.github_repo_id.notin_(ids))
            conn.execute(stale)
        known = {
            r.github_repo_id: r.id
            for r in conn.execute(
                select(installation_repos.c.id, installation_repos.c.github_repo_id).where(
                    installation_repos.c.installation_id == installation_id
                )
            )
        }
        for repo_id, full_name in repos:
            values = {"full_name": full_name, "state": state, "updated_at": now}
            if repo_id in known:
                conn.execute(
                    update(installation_repos)
                    .where(installation_repos.c.id == known[repo_id])
                    .values(**values)
                )
            else:
                conn.execute(
                    installation_repos.insert(),
                    {"installation_id": installation_id, "github_repo_id": repo_id, **values},
                )


```

- [ ] **Step 12: Run tests to verify they pass**

Run: `cd api && uv run pytest -q && uv run ruff check .`
Expected: full suite green (26 tests in `test_store.py`, 5 in `test_migrations.py`); ruff clean.

- [ ] **Step 13: Commit**

```
git add api/doug/migrations.py api/doug/store.py api/tests/test_migrations.py api/tests/test_store.py
git commit -m "Add a migration runner and the App schema" -m "store.py's create_all() adds missing tables and never adds a column to a table that already exists, so until now a new fact could only arrive as a new table. The App identity columns have to sit on verdicts — a row's installation is not a separate fact about it — and adding them to the Table definition alone would have created them in every test and in no production row.

Migration 001 and the verdicts definition therefore both declare the four columns, and a test asserts they still say the same thing. apply() treats an already-satisfied statement as done rather than as an error, because on a fresh database create_all() has already produced the post-migration shape.

review_jobs, installations and installation_repos are new tables, so create_all() is enough for them. Removal is a state, never a DELETE: verdicts outlive the access that produced them.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```

---

### Task 3: Queue ops (`api/doug/ingest.py`)

**Files:**
- Create: `api/doug/ingest.py`
- Test: `api/tests/test_ingest.py`

**Interfaces:**
- Consumes: `store.review_jobs` and `store._get_engine()` (Task 2), `store.save_review(..., source=...)` in the test only.
- Produces:
  ```python
  def enqueue(installation_id: int, github_repo_id: int, repo_full_name: str,
              pr_number: int, head_sha: str) -> int | None
  def claim() -> dict | None
  def release(job_id: int) -> None
  def complete(job_id: int, verdict_id: int | None) -> None
  def supersede(job_id: int) -> None
  def fail(job_id: int, error: str, *, max_attempts: int = 3) -> None
  ```
  Task 6's webhook handler calls `enqueue`. Task 5 calls the rest: `drain` uses `claim`/`release` (it claims before it can tell whether its seen-set already holds the job, so the claim has to be undoable without charging an attempt), and `process_job` uses `complete`/`supersede`/`fail` — `supersede` being the stale-head guard's terminal state, which is neither done nor failed. `claim()` returns a plain dict, not a Row, so the worker can hold it after the connection closes; it carries every `review_jobs` column, so `job["id"]` is the primary key Task 5 passes back to `complete`/`fail`.
- **`enqueue` returns `None` only when the SHA needs no new work.** The unique index carries no status column, so a row that ended `'failed'` or `'superseded'` collides exactly like a reviewed one. Colliding with either of those revives it — `status='pending'`, `attempts=0`, `error=NULL`, `enqueued_at=now` — and returns its existing id; `'pending'`, `'running'` and `'done'` still return `None`. Task 7's reconcile depends on this: without it a PR whose review failed could never be healed, on any restart. The bound on the bad case is `max_attempts` retries per reconcile, not unbounded retrying.
- **Supersede runs after the insert, inside the same transaction.** Nothing is superseded on the collision path. It is a spend optimisation for the ordinary in-order burst, not the mechanism that decides which SHA gets reviewed — Task 5's `process_job` re-checks the PR's real head before paying for a read, and re-enqueues (reviving, per above) when it differs.
- **`fail` bumps `enqueued_at` when it re-pends**, and `claim` orders by `(enqueued_at, id)`, so a re-pended job sorts behind existing work instead of ahead of it. That alone does not stop a drain from re-claiming the only pending row inside one pass; Task 5's `drain` keeps a seen-set for that. Both halves are needed and Task 5 verified the composition: with the seen-set but without this bump, its two-job test yields `drain() == 1` — the poison job is re-claimed at once, the seen-set breaks the loop, and the healthy second job never runs. Do not drop the bump as a redundant write.
- **`release` deliberately leaves `enqueued_at` alone**, unlike `fail`. Nothing was attempted, so the job keeps its place in the queue.
- **A revived job keeps its id** — `_revive` updates in place and never re-inserts. Task 5's `drain` bounds a supersede/revive ping-pong (its stale-head guard supersedes a job, `enqueue` revives it, neither makes progress) with a seen-set of job ids, and Task 5 mutation-checked it: with the seen-set the drain returns 2 and stops, without it 20, the `max_jobs` ceiling. The bound holds only because the id is stable, so a revival that allocated a fresh row would restore an unbounded loop inside a held instance without failing one test in this task.
- **One point the locked contract left open:** `enqueue` raises `RuntimeError` when `DATABASE_URL` is unset. `None` already means "already queued", so a no-op return would make an unconfigured deployment answer 202 to every delivery while reviewing nothing. In practice Task 6 guards this at the edge — `if not store.enabled(): raise HTTPException(503, "no ledger configured")`, placed after the ping early-return — so the raise here is a backstop, not the path a delivery normally takes. `claim()` keeps the no-op (returns `None`), which makes `drain` a safe no-op on a ledger-less deployment; Task 5 wraps it in no try/except for that reason.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_ingest.py`:
```python
import pytest
from sqlalchemy import create_engine, select

from doug import ingest, store
from doug.models import Band, Reason, Verdict

INSTALL = 150424894
REPO_ID = 900001
REPO = "drewjst/doug"

VERDICT = Verdict(
    score=0.4,
    band=Band.CLEARED,
    threshold=0.62,
    reasons=[Reason(rule="size", label="small change", weight=0.0)],
)


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _jobs(url: str) -> list[dict]:
    with create_engine(url).connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                select(store.review_jobs).order_by(store.review_jobs.c.id)
            ).mappings()
        ]


def test_enqueue_suppresses_a_redelivered_push(tmp_path, monkeypatch):
    """GitHub delivers at least once, not exactly once, and a duplicate that
    got through would buy a second model read of a diff already queued. The
    unique index is the guard; enqueue reports the suppression as None rather
    than inventing a job id."""
    url = _db(tmp_path, monkeypatch)
    first = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    assert first is not None
    assert ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40) is None
    assert [j["id"] for j in _jobs(url)] == [first]


def test_a_new_head_sha_supersedes_the_pending_job_it_replaces(tmp_path, monkeypatch):
    """A five-commit push burst is five deliveries for one PR. Reviewing every
    intermediate SHA costs five model reads to describe a tree nobody will
    merge, so only the newest pending SHA survives."""
    url = _db(tmp_path, monkeypatch)
    old = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    new = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "b" * 40)
    by_id = {j["id"]: j for j in _jobs(url)}
    assert by_id[old]["status"] == "superseded"
    assert by_id[new]["status"] == "pending"


def test_a_finished_job_is_never_superseded(tmp_path, monkeypatch):
    """Only pending work is cheap to discard. A done job has already been paid
    for and its verdict is in the ledger; rewriting its status would make the
    row lie about what happened."""
    url = _db(tmp_path, monkeypatch)
    done = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    ingest.complete(done, None)
    ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "b" * 40)
    assert {j["id"]: j["status"] for j in _jobs(url)}[done] == "done"


def test_claim_takes_the_oldest_pending_job_and_marks_it_running(tmp_path, monkeypatch):
    """Two drains must never take the same job, so a claim is a write, not a
    read. Oldest-first keeps one busy repo from starving another."""
    url = _db(tmp_path, monkeypatch)
    first = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    second = ingest.enqueue(INSTALL, REPO_ID, REPO, 8, "b" * 40)

    job = ingest.claim()
    assert job["id"] == first
    assert job["status"] == "running" and job["started_at"] is not None
    assert job["repo_full_name"] == REPO and job["head_sha"] == "a" * 40

    assert {j["id"]: j["status"] for j in _jobs(url)}[first] == "running"
    assert ingest.claim()["id"] == second


def test_claim_returns_none_when_nothing_is_pending(tmp_path, monkeypatch):
    """The drain loop's stop condition. An empty queue is the normal state."""
    _db(tmp_path, monkeypatch)
    assert ingest.claim() is None


def test_fail_re_pends_below_the_cap_and_gives_up_at_it(tmp_path, monkeypatch):
    """A model call that times out should be retried; one that fails three
    times is broken, and a job that retried forever would spend real money
    doing it."""
    url = _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)

    queued_at = {j["id"]: j for j in _jobs(url)}[job_id]["enqueued_at"]
    ingest.fail(job_id, "read timed out")
    row = {j["id"]: j for j in _jobs(url)}[job_id]
    assert row["status"] == "pending" and row["attempts"] == 1
    assert row["error"] == "read timed out"
    assert row["started_at"] is None  # re-pended, not still running
    # Behind the rest of the queue, not back at its head: claim() orders by
    # enqueued_at, so an untouched timestamp hands the job straight back and
    # burns all three attempts in one drain, in milliseconds.
    assert row["enqueued_at"] > queued_at

    ingest.fail(job_id, "read timed out")
    ingest.fail(job_id, "read timed out")
    row = {j["id"]: j for j in _jobs(url)}[job_id]
    assert row["status"] == "failed" and row["attempts"] == 3
    assert row["finished_at"] is not None


def test_fail_truncates_the_error(tmp_path, monkeypatch):
    """Anthropic and githubkit both raise exceptions carrying whole request
    bodies. One job must not be able to write a megabyte into the queue."""
    url = _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    ingest.fail(job_id, "x" * 5000)
    assert len({j["id"]: j for j in _jobs(url)}[job_id]["error"]) == 500


def test_complete_records_the_verdict_the_job_produced(tmp_path, monkeypatch):
    """The queue row is the only link from a delivery to the ledger row it
    caused; without it, "did this push get reviewed?" is unanswerable."""
    url = _db(tmp_path, monkeypatch)
    verdict_id = store.save_review(REPO, 7, "deterministic", VERDICT, source="app")
    job_id = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)

    ingest.complete(job_id, verdict_id)
    row = {j["id"]: j for j in _jobs(url)}[job_id]
    assert row["status"] == "done"
    assert row["verdict_id"] == verdict_id and row["finished_at"] is not None


def test_enqueue_without_a_ledger_refuses_loudly(tmp_path, monkeypatch):
    """Storage is optional everywhere else in this codebase — save_review
    no-ops without DATABASE_URL. It cannot be optional here: a silent no-op
    would return the same None that means "already queued", and every webhook
    on an unconfigured deployment would report success while reviewing
    nothing."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)


def test_a_failed_job_is_revived_by_a_later_enqueue(tmp_path, monkeypatch):
    """The unique index carries no status column, so a row that gave up blocks
    re-insertion exactly like a reviewed one. Reconcile exists to heal PRs
    whose review never landed — a deploy that wiped the App credentials, a
    provider outage — and if a collision with a 'failed' row returned None it
    would heal nothing, permanently, on that PR and every restart after."""
    url = _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    for _ in range(3):
        ingest.fail(job_id, "credentials missing")
    assert {j["id"]: j for j in _jobs(url)}[job_id]["status"] == "failed"

    assert ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40) == job_id
    row = {j["id"]: j for j in _jobs(url)}[job_id]
    assert row["status"] == "pending" and row["attempts"] == 0
    assert row["error"] is None and row["finished_at"] is None
    # One row, not two, and the same id. worker.drain bounds a
    # supersede/revive ping-pong with a seen-set of job ids, so a revival
    # that allocated a fresh id would quietly turn that bound back into an
    # unbounded loop.
    assert len(_jobs(url)) == 1


def test_a_superseded_job_is_revived_by_a_later_enqueue(tmp_path, monkeypatch):
    """GitHub does not order deliveries, so the SHA that lost the supersede
    race can be the PR's real head. The worker re-enqueues whatever head it
    finds, and that call has to be able to bring the row back."""
    url = _db(tmp_path, monkeypatch)
    first = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "b" * 40)
    assert {j["id"]: j for j in _jobs(url)}[first]["status"] == "superseded"

    assert ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40) == first
    assert {j["id"]: j for j in _jobs(url)}[first]["status"] == "pending"


def test_running_and_finished_jobs_are_never_revived(tmp_path, monkeypatch):
    """Only the two states that mean "queued and never reviewed" come back.
    Reviving in-flight or completed work is exactly the duplicate spend the
    unique index exists to prevent."""
    url = _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    ingest.claim()
    assert ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40) is None
    assert {j["id"]: j for j in _jobs(url)}[job_id]["status"] == "running"

    ingest.complete(job_id, None)
    assert ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40) is None
    assert {j["id"]: j for j in _jobs(url)}[job_id]["status"] == "done"


def test_a_replayed_older_delivery_leaves_the_newer_job_pending(tmp_path, monkeypatch):
    """Supersede runs after the insert lands, not before it. Running it first
    meant a redelivered older push superseded the newer pending job and then
    collided on its own row, leaving the PR with nothing pending and no
    further delivery coming to fix it."""
    url = _db(tmp_path, monkeypatch)
    ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    newer = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "b" * 40)

    ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)  # the replay
    assert {j["id"]: j["status"] for j in _jobs(url)}[newer] == "pending"


def test_release_returns_a_claimed_job_without_charging_an_attempt(tmp_path, monkeypatch):
    """drain has to claim a job before it can tell whether it already ran it
    this pass. Undoing that claim cannot cost an attempt — the job was never
    attempted, and charging it would retire a healthy PR after three drains
    that never touched it."""
    url = _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    queued_at = {j["id"]: j for j in _jobs(url)}[job_id]["enqueued_at"]
    ingest.claim()

    ingest.release(job_id)
    row = {j["id"]: j for j in _jobs(url)}[job_id]
    assert row["status"] == "pending" and row["attempts"] == 0
    assert row["started_at"] is None
    # Keeps its place, unlike a failure: nothing was attempted.
    assert row["enqueued_at"] == queued_at
    assert ingest.claim()["id"] == job_id


def test_supersede_retires_a_job_whose_sha_is_no_longer_the_head(tmp_path, monkeypatch):
    """The worker's stale-head guard needs a terminal state that is honest:
    not 'done', because no verdict exists, and not 'failed', because nothing
    went wrong. Revivable, so a force-push back to this SHA re-queues the row
    instead of colliding with it forever."""
    url = _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40)
    ingest.claim()

    ingest.supersede(job_id)
    row = {j["id"]: j for j in _jobs(url)}[job_id]
    assert row["status"] == "superseded" and row["finished_at"] is not None
    assert row["verdict_id"] is None

    assert ingest.enqueue(INSTALL, REPO_ID, REPO, 7, "a" * 40) == job_id
    assert {j["id"]: j for j in _jobs(url)}[job_id]["status"] == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_ingest.py -q`
Expected: collection error — `ImportError: cannot import name 'ingest' from 'doug'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/doug/ingest.py`:
```python
"""The review_jobs queue — the durable gap between a webhook and a review.

A delivery must be recorded and answered in milliseconds; a review takes a
model call. Everything between those two facts lives in this table: the
webhook enqueues and returns 202, a worker claims and runs. Nothing is held
in process memory, so a Cloud Run instance dying mid-review loses a claim,
not a review.

Uniqueness is (installation_id, github_repo_id, pr_number, head_sha) and it
is enforced by the database, not by a check-then-insert: two deliveries of
the same push arrive concurrently often enough that a race here would mean
paying for the same read twice.
"""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from . import store

# The two states a collision may revive. Both mean "this SHA was queued and
# never reviewed"; every other state means the work is queued, in flight, or
# already paid for.
REVIVABLE = ("failed", "superseded")


def _engine():
    engine = store._get_engine()
    if engine is None:
        raise RuntimeError("review_jobs requires DATABASE_URL")
    return engine


def _job_filter(installation_id: int, github_repo_id: int, pr_number: int):
    return (
        store.review_jobs.c.installation_id == installation_id,
        store.review_jobs.c.github_repo_id == github_repo_id,
        store.review_jobs.c.pr_number == pr_number,
    )


def enqueue(
    installation_id: int,
    github_repo_id: int,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
) -> int | None:
    """Queue one head SHA for review. None means this SHA needs no new work.

    A collision on the unique index is not automatically a duplicate. The
    index carries no status column, so a row that ended 'failed' or
    'superseded' blocks re-insertion exactly like a reviewed one — and those
    are the two states reconcile exists to repair. Colliding with one revives
    it rather than dropping the work; the cost of a permanently broken PR is
    therefore max_attempts per reconcile, which is bounded, instead of never
    being retried again on any restart.

    Superseding older pending SHAs happens after the insert lands and in the
    same transaction. Running it first meant a redelivered older push
    superseded the newer pending job and then collided on its own row,
    leaving the PR with nothing pending at all. It is a spend optimisation
    for the ordinary in-order burst, not the thing that decides which SHA
    gets reviewed: GitHub does not order deliveries, so worker.process_job
    re-checks the PR's real head before paying for a read.
    """
    engine = _engine()
    now = datetime.now(UTC)
    try:
        with engine.begin() as conn:
            job_id = int(
                conn.execute(
                    store.review_jobs.insert().returning(store.review_jobs.c.id),
                    {
                        "installation_id": installation_id,
                        "github_repo_id": github_repo_id,
                        "repo_full_name": repo_full_name,
                        "pr_number": pr_number,
                        "head_sha": head_sha,
                        "status": "pending",
                        "attempts": 0,
                        "enqueued_at": now,
                    },
                ).scalar_one()
            )
            conn.execute(
                update(store.review_jobs)
                .where(
                    *_job_filter(installation_id, github_repo_id, pr_number),
                    store.review_jobs.c.head_sha != head_sha,
                    store.review_jobs.c.status == "pending",
                )
                .values(status="superseded", finished_at=now)
            )
            return job_id
    except IntegrityError:
        return _revive(engine, installation_id, github_repo_id, pr_number, head_sha, now)


def _revive(
    engine,
    installation_id: int,
    github_repo_id: int,
    pr_number: int,
    head_sha: str,
    now: datetime,
) -> int | None:
    """Return a queued-but-unreviewed row to pending, or None if there is none.

    The status test lives in the UPDATE's WHERE rather than in a SELECT before
    it: a concurrent drain can claim or finish the row between the two, and a
    zero-row result is the only reliable way to find out that it did.

    The row is updated in place and keeps its id — never deleted and
    re-inserted. worker.drain bounds a supersede/revive ping-pong (its
    stale-head guard supersedes a job, which this then revives) with a
    seen-set of job ids, and a fresh id per revival would defeat it silently,
    turning the spin back into an unbounded loop inside a held instance.
    """
    with engine.begin() as conn:
        job_id = conn.execute(
            update(store.review_jobs)
            .where(
                *_job_filter(installation_id, github_repo_id, pr_number),
                store.review_jobs.c.head_sha == head_sha,
                store.review_jobs.c.status.in_(REVIVABLE),
            )
            .values(
                status="pending",
                attempts=0,
                error=None,
                enqueued_at=now,
                started_at=None,
                finished_at=None,
            )
            .returning(store.review_jobs.c.id)
        ).scalar_one_or_none()
    return int(job_id) if job_id is not None else None


def claim() -> dict | None:
    """Take the oldest pending job, or None. Marks it running before returning.

    Ordering is (enqueued_at, id), which is what makes fail()'s bump of
    enqueued_at put a re-pended job behind the rest of the queue rather than
    back at its head.

    On Postgres the select takes a row lock with SKIP LOCKED, so concurrent
    drains take different jobs instead of blocking on the same one. sqlite
    has one writer by construction, so the plain transaction is already the
    same guarantee.
    """
    engine = store._get_engine()
    if engine is None:
        return None
    pending = (
        select(store.review_jobs)
        .where(store.review_jobs.c.status == "pending")
        .order_by(store.review_jobs.c.enqueued_at, store.review_jobs.c.id)
        .limit(1)
    )
    if engine.dialect.name == "postgresql":
        pending = pending.with_for_update(skip_locked=True)
    now = datetime.now(UTC)
    with engine.begin() as conn:
        row = conn.execute(pending).mappings().first()
        if row is None:
            return None
        conn.execute(
            update(store.review_jobs)
            .where(store.review_jobs.c.id == row["id"])
            .values(status="running", started_at=now)
        )
        return {**row, "status": "running", "started_at": now}


def release(job_id: int) -> None:
    """Put a claimed job back without spending an attempt.

    drain claims a job before it can tell whether it has already run it this
    pass. Leaving the repeat 'running' strands it, and fail() would charge an
    attempt against work nobody attempted. enqueued_at is deliberately
    untouched — unlike a failure, nothing here justifies losing its place.
    """
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            update(store.review_jobs)
            .where(store.review_jobs.c.id == job_id)
            .values(status="pending", started_at=None)
        )


def complete(job_id: int, verdict_id: int | None) -> None:
    """Mark a job done. verdict_id is None when the review produced no ledger
    row — a skipped PR is finished, not failed."""
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            update(store.review_jobs)
            .where(store.review_jobs.c.id == job_id)
            .values(status="done", verdict_id=verdict_id, finished_at=datetime.now(UTC))
        )


def supersede(job_id: int) -> None:
    """Retire a job whose head SHA is no longer the PR's.

    Neither 'done' — there is no verdict — nor 'failed', since nothing went
    wrong. It lands in a revivable state on purpose: a force-push back to
    this SHA re-queues this row rather than being suppressed by it.
    """
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            update(store.review_jobs)
            .where(store.review_jobs.c.id == job_id)
            .values(status="superseded", finished_at=datetime.now(UTC))
        )


def fail(job_id: int, error: str, *, max_attempts: int = 3) -> None:
    """Record a failed attempt: back to pending below the cap, failed at it.

    started_at is cleared on the retry so a re-pended row is not reported as
    having been running since its first attempt.
    """
    engine = _engine()
    now = datetime.now(UTC)
    with engine.begin() as conn:
        attempts = (
            conn.execute(
                select(store.review_jobs.c.attempts).where(store.review_jobs.c.id == job_id)
            ).scalar_one()
            + 1
        )
        values = {"attempts": attempts, "error": error[:500], "started_at": None}
        if attempts >= max_attempts:
            values |= {"status": "failed", "finished_at": now}
        else:
            # Back of the queue, not the front. claim() orders by
            # (enqueued_at, id), so leaving enqueued_at alone hands the job
            # straight back to the next claim and burns every attempt in one
            # pass, before whatever was transient has any chance to clear.
            # This orders it behind existing work; worker.drain's seen-set is
            # what stops a re-claim when it is the only pending row.
            values |= {"status": "pending", "enqueued_at": now}
        conn.execute(
            update(store.review_jobs).where(store.review_jobs.c.id == job_id).values(**values)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_ingest.py -q && uv run pytest -q && uv run ruff check .`
Expected: 15 passed in `test_ingest.py`; full suite green; ruff clean.

- [ ] **Step 5: Commit**

```
git add api/doug/ingest.py api/tests/test_ingest.py
git commit -m "Add durable review_jobs queue operations" -m "A webhook has to be answered in milliseconds and a review takes a model call, so the two cannot be the same request. These four operations are the whole seam: the handler enqueues and returns 202, a worker claims, runs, and reports back.

Deduplication is the unique index rather than a check-then-insert, because two deliveries of one push do race and losing that race means paying for the same read twice. But the index carries no status, so a collision alone does not mean the work is done: a row that ended failed or superseded is exactly the work reconcile exists to recover, and colliding with one revives it instead of dropping it. Only pending, running and done suppress.

Supersede runs after the insert and in the same transaction. Running it first meant a redelivered older push superseded the newer pending job and then collided on its own row, leaving the PR with nothing pending and no further delivery coming. It is a spend optimisation for the ordinary burst; which SHA actually gets reviewed is decided by the worker re-checking the PR head, because GitHub does not order deliveries.

Claim is a write: on Postgres it takes the row with SKIP LOCKED so two drains never take the same job. A re-pended failure goes to the back of the queue rather than the front, so three retries cannot burn in one pass before whatever was transient has a chance to clear. Release is its inverse, for the drain that claims a job before it can tell it has already run it — undoing that claim must not spend an attempt on work nobody attempted. Supersede is the honest terminal state for a job whose SHA is no longer the PR head: no verdict exists, so it is not done, and nothing went wrong, so it is not failed.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```
### Task 4: Check run (`api/doug/check_run.py`)

**Files:**
- Create: `api/doug/check_run.py`
- Test: `api/tests/test_check_run.py`

**Interfaces:**
- Consumes: `doug.models.Verdict` (`score: float`, `band: Band`, `threshold: float`, `reasons: list[Reason]`; `Reason` = `rule/label/weight/severity|None`, `models.py:62-81`); `doug.reader.Coverage` + `doug.reader.truncation_reason(cov: Coverage) -> Reason | None` (`reader.py:223-304`); `doug.review.IntentRead` (`alignment: int`, `refs: list[str]`, `findings: list[reader.DeviationFinding]`, `coverage: Coverage` — `review.py:145-158`); `reader.DeviationFinding` (`type/description/severity`, `reader.py:336-339`); `gh.rest.checks.create(owner, repo, **body)` — verified signature `create(self, owner, repo, *, headers, stream, data=UNSET, **kwargs)`, so the body fields travel as kwargs.
- Produces: `render(tier: str, verdict: Verdict, intent_read: IntentRead | None, coverage: Coverage | None) -> tuple[str, str]`; `post(gh, owner: str, repo: str, head_sha: str, title: str, summary: str) -> None`; module constants `NAME = "Doug"`, `SUMMARY_LIMIT = 60_000`, `TITLE_LIMIT = 255`. Task 5's `process_job` calls both.

- [ ] **Step 1: Write the failing test — title honesty, neutral framing, findings, coverage**

Create `api/tests/test_check_run.py`:

```python
"""The check run is the only thing Doug writes to a pull request.

Three properties are load-bearing and every one of them has already been
got wrong somewhere in this codebase, so they are tested as defects:
a deterministic fallback must not read as a read (review.py:118-142 falls
back silently), a partial read must not read as a whole one, and nothing
here may ever conclude anything but neutral.
"""

from pathlib import Path
from types import SimpleNamespace

from doug import check_run, reader
from doug.models import Band, Reason, Verdict
from doug.review import IntentRead

FLAGGED = Verdict(
    score=0.62,
    band=Band.FLAGGED,
    threshold=0.30,
    reasons=[
        Reason(
            rule="reader:race-condition",
            label="Cache write is not guarded",
            weight=0.0,
            severity="high",
        )
    ],
)

WHOLE = reader.Coverage(diff_chars=400, sent_chars=400, files_sent=2, files_unseen=[])
PARTIAL = reader.Coverage(
    diff_chars=68_430,
    sent_chars=30_000,
    files_sent=3,
    files_unseen=["api/tenancy.py", "tests/test_tenancy.py"],
    file_cut="api/store.py",
)

DEVIATIONS = IntentRead(
    alignment=41,
    refs=["ADR-0002"],
    findings=[
        reader.DeviationFinding(
            type="contradicts-ticket",
            description="Edits the frozen reader prompt",
            severity="high",
        )
    ],
    coverage=WHOLE,
)


def test_reader_title_leads_with_the_band_and_score():
    title, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert title.lower().startswith("flagged")
    assert "0.62" in title
    assert not title.lower().startswith("deterministic")


def test_a_deterministic_fallback_announces_itself_in_the_title():
    """Tier honesty (Global Constraints). score_one falls back to the
    deterministic scorer whenever the reader is off or a read raised, and
    the Verdict it returns is shape-identical to a real read's. A footnote
    is not enough: the title is the only part of a check run visible from
    the PR's checks list, so that is where the difference has to be."""
    title, summary = check_run.render("deterministic", FLAGGED, None, None)
    assert title.lower().startswith("deterministic fallback")
    assert "0.62" in title and "flagged" in title.lower()
    assert "did not run" in summary


def test_a_reader_run_does_not_claim_a_fallback():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "did not run" not in summary


def test_the_summary_says_the_check_never_blocks():
    """ADR-0010: the surface is advisory. A reader who sees "Flagged" on a
    red-looking check and assumes it gated the merge has been misled about
    what this product does."""
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "never blocks" in summary
    assert "neutral" in summary


def test_findings_render_with_their_rule_and_label():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "reader:race-condition" in summary
    assert "Cache write is not guarded" in summary
    assert "high" in summary


def test_a_clean_verdict_renders_an_explicit_none():
    """An empty findings section and a missing one look the same to a
    reader; only one of them means "looked and found nothing"."""
    clean = FLAGGED.model_copy(update={"reasons": [], "band": Band.CLEARED, "score": 0.04})
    _, summary = check_run.render("reader", clean, None, WHOLE)
    assert "none" in summary.lower()


def test_a_partial_read_is_called_out_once_and_only_once():
    """score_one already appends the read-truncated Reason to the verdict
    (review.py:133-134), so rendering the coverage block naively duplicated
    it. The block is the better surface — it is above the findings, where a
    caveat about the findings has to be — so the reason is folded into it
    rather than printed twice."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    _, summary = check_run.render("reader", verdict, None, PARTIAL)
    assert summary.count("Partial read") == 1
    assert "api/tenancy.py" in summary
    assert "api/store.py" in summary


def test_a_truncation_reason_is_never_silently_dropped():
    """The fold above is conditional on the coverage block actually
    rendering. If a caller ever passes the reason without the coverage, the
    line still has to reach the PR — dropping it is the exact failure the
    coverage work existed to end."""
    verdict = FLAGGED.model_copy(deep=True)
    verdict.reasons.append(reader.truncation_reason(PARTIAL))
    _, summary = check_run.render("reader", verdict, None, None)
    assert "read-truncated" in summary


def test_a_whole_read_gets_no_coverage_notice():
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "Partial read" not in summary


def test_the_summary_is_truncated_below_githubs_cap():
    """GitHub rejects output.summary over 65535 chars. A PR with hundreds of
    findings must produce a shorter check run, not an API error that loses
    the whole verdict."""
    noisy = FLAGGED.model_copy(
        update={
            "reasons": [
                Reason(rule=f"reader:pattern-{i}", label="x" * 300, weight=0.0)
                for i in range(500)
            ]
        }
    )
    _, summary = check_run.render("reader", noisy, None, WHOLE)
    assert len(summary) == check_run.SUMMARY_LIMIT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_check_run.py -q`
Expected: FAIL — collection error, `ModuleNotFoundError: No module named 'doug.check_run'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/doug/check_run.py`:

```python
"""The check run — the one thing Doug writes to a pull request.

Advisory by construction: the conclusion is always neutral, so a Doug run
can never gate a merge. ADR-0010 replaces ADR-0003 and keeps its argument
intact — a router that blocks needs precision this evidence base does not
have, and the honest surface for a judgment that might be wrong is one
that costs nothing to ignore.

Two things this surface must never smooth over:

  * A deterministic fallback is not a read. review.score_one falls back
    silently when the reader is off or a read raised, and the Verdict is
    shape-identical either way — so the tier goes in the title, which is
    the only part visible from the PR's checks list.
  * Deviation findings come from the intent tier, whose derangement check
    did not pass (2026-07-31). The instrument is not validated, so they
    render in their own labelled section and never touch band or score
    (ADR-0007).
"""

import sys

from .models import Verdict
from .reader import Coverage, truncation_reason
from .review import IntentRead

NAME = "Doug"
# GitHub caps output.summary at 65535 chars and rejects the whole call over
# it. Leave headroom rather than discovering the cap on a 400-finding PR.
SUMMARY_LIMIT = 60_000
TITLE_LIMIT = 255

NEUTRAL_NOTE = (
    "Doug is advisory: this check is always neutral and never blocks a "
    "merge, whatever the band says."
)
FALLBACK_NOTE = (
    "**The validated diff-reader did not run.** This band and score come "
    "from the deterministic scorer, which never opens the diff — it scores "
    "PR shape (size, paths, authorship) alone. Read it as routing, not as "
    "a judgment about this change."
)
DEVIATION_HEADING = "### Decision deviations (unvalidated)"
DEVIATION_NOTE = (
    "The instrument behind this section has not passed its derangement "
    "check (2026-07-31), so these are unvalidated observations. They do "
    "not contribute to the band or score above (ADR-0007)."
)


def _headline(tier: str, verdict: Verdict) -> str:
    band = verdict.band.value
    if tier == "reader":
        return f"{band.capitalize()} · risk {verdict.score:.2f} · diff read"
    return f"Deterministic fallback · {band} · risk {verdict.score:.2f}"


def render(
    tier: str,
    verdict: Verdict,
    intent_read: IntentRead | None,
    coverage: Coverage | None,
) -> tuple[str, str]:
    """(title, summary_md) for one verdict."""
    title = _headline(tier, verdict)
    partial = truncation_reason(coverage) if coverage is not None else None

    lines = [
        f"**{title}**",
        "",
        f"Risk {verdict.score:.2f} against a flag line of {verdict.threshold:.2f}.",
        NEUTRAL_NOTE,
    ]
    if tier != "reader":
        lines += ["", FALLBACK_NOTE]
    if partial is not None:
        # The label already opens "Partial read:" — reader.truncation_reason
        # writes the whole sentence. Adding a heading of our own printed the
        # words twice and broke the caveat's own once-and-only-once rule.
        lines += ["", f"> {partial.label}"]

    # Folded into the block above, so it is stated once — but only when that
    # block rendered, so it can never be lost instead.
    skip = {"read-truncated"} if partial is not None else set()
    risks = [r for r in verdict.reasons if r.rule not in skip]
    lines += ["", "### Findings", ""]
    if risks:
        lines += [
            f"- `{r.rule}` — {r.label}" + (f" _({r.severity})_" if r.severity else "")
            for r in risks
        ]
    else:
        lines.append("- none")

    if intent_read is not None:
        lines += ["", DEVIATION_HEADING, "", DEVIATION_NOTE, ""]
        if intent_read.findings:
            lines += [
                f"- `{d.type}` — {d.description} _({d.severity})_"
                for d in intent_read.findings
            ]
        else:
            lines.append(f"- none (alignment {intent_read.alignment}/100)")
        lines += ["", f"Judged against: {', '.join(intent_read.refs) or 'no records'}."]

    return title[:TITLE_LIMIT], "\n".join(lines)[:SUMMARY_LIMIT]


def post(gh, owner: str, repo: str, head_sha: str, title: str, summary: str) -> None:
    """Create the check run. Never raises.

    This is an advisory surface hanging off work that is already durable —
    the verdict is in the ledger before this runs. A GitHub outage, a
    revoked installation or a force-pushed-away SHA must not turn a good
    verdict into a retried job.
    """
    try:
        gh.rest.checks.create(
            owner=owner,
            repo=repo,
            name=NAME,
            head_sha=head_sha,
            status="completed",
            conclusion="neutral",
            output={"title": title[:TITLE_LIMIT], "summary": summary[:SUMMARY_LIMIT]},
        )
    except Exception as e:  # noqa: BLE001 — advisory surface, never fails a job
        print(
            f"doug: check run not posted for {owner}/{repo}@{head_sha[:12]} "
            f"({type(e).__name__}: {e})",
            file=sys.stderr,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_check_run.py -q`
Expected: 10 passed.

- [ ] **Step 5: Write the failing test — deviations are labelled, separate, and inert**

Append to `api/tests/test_check_run.py`:

```python
def test_deviations_render_under_an_unvalidated_heading():
    """The derangement check FAILED on 2026-07-31 — this instrument has no
    validity evidence. Rendering its output beside reader findings, which
    do have some, would launder one into the other."""
    _, summary = check_run.render("reader", FLAGGED, DEVIATIONS, WHOLE)
    heading = next(ln for ln in summary.splitlines() if ln.startswith("### Decision"))
    assert "unvalidated" in heading.lower()
    assert "Edits the frozen reader prompt" in summary
    assert "ADR-0002" in summary


def test_deviations_move_neither_the_band_nor_the_score():
    """ADR-0007, enforced at the surface as well as in the ledger. The
    rendered title and risk line must be byte-identical with the intent
    read present and absent."""
    bare_title, bare = check_run.render("reader", FLAGGED, None, WHOLE)
    dev_title, dev = check_run.render("reader", FLAGGED, DEVIATIONS, WHOLE)
    assert bare_title == dev_title
    risk_line = "Risk 0.62 against a flag line of 0.30."
    assert risk_line in bare and risk_line in dev
    assert dev.startswith(bare[: bare.index("### Findings")])


def test_no_deviation_section_without_an_intent_read():
    """No read happened is not the same as a read that found nothing, and
    an empty labelled section would assert the second."""
    _, summary = check_run.render("reader", FLAGGED, None, WHOLE)
    assert "Decision deviations" not in summary
    assert "unvalidated" not in summary.lower()


def test_a_clean_intent_read_is_distinguishable_from_no_read():
    clean = DEVIATIONS.model_copy(update={"findings": [], "alignment": 92})
    _, summary = check_run.render("reader", FLAGGED, clean, WHOLE)
    assert "Decision deviations" in summary
    assert "alignment 92/100" in summary
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_check_run.py -q`
Expected: PASS — these four are covered by the Step 3 implementation. If any fails, the implementation drifted from the contract; fix `render` rather than the test.

- [ ] **Step 7: Write the failing test — `post` pins neutral and never raises**

Append to `api/tests/test_check_run.py`:

```python
class _Checks:
    def __init__(self, boom=None):
        self.calls = []
        self.boom = boom

    def create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise self.boom


def _gh(boom=None):
    checks = _Checks(boom)
    return SimpleNamespace(rest=SimpleNamespace(checks=checks)), checks


def test_post_creates_a_neutral_completed_check_run():
    gh, checks = _gh()
    check_run.post(gh, "drewjst", "doug", "b" * 40, "Flagged · risk 0.62", "body")
    (kw,) = checks.calls
    assert kw["owner"] == "drewjst" and kw["repo"] == "doug"
    assert kw["name"] == "Doug"
    assert kw["head_sha"] == "b" * 40
    assert kw["status"] == "completed"
    assert kw["conclusion"] == "neutral"
    assert kw["output"]["title"] == "Flagged · risk 0.62"
    assert kw["output"]["summary"] == "body"


def test_no_blocking_conclusion_string_exists_anywhere_in_the_module():
    """Global constraint: Doug never blocks. This greps the source rather
    than asserting on one call, because the risk is not this call — it is
    the second create() someone adds later behind a "just for high
    severity" branch, which a behavioural test on the current path would
    never see. The module may not even name another conclusion."""
    src = Path(check_run.__file__).read_text()
    assert 'conclusion="neutral"' in src
    for banned in ("failure", "action_required", "success", "cancelled", "timed_out", "stale"):
        assert banned not in src, f"{banned!r} must not appear in check_run.py"


def test_post_swallows_an_api_error_and_says_so_on_stderr(capsys):
    """The verdict is already in the ledger by the time this runs. A 403
    from a revoked installation must not fail the job and cause a retry
    that pays for the same read again — but it must not be silent either,
    or a permanently broken check run looks like a quiet repo."""
    gh, _ = _gh(boom=RuntimeError("403 Resource not accessible by integration"))
    assert check_run.post(gh, "o", "r", "c" * 40, "t", "s") is None
    err = capsys.readouterr().err
    assert "doug: check run not posted" in err
    assert "o/r" in err and "403" in err


def test_post_truncates_a_summary_that_would_be_rejected():
    gh, checks = _gh()
    check_run.post(gh, "o", "r", "d" * 40, "t", "x" * 90_000)
    assert len(checks.calls[0]["output"]["summary"]) == check_run.SUMMARY_LIMIT
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_check_run.py -q`
Expected: 18 passed. Then `cd api && uv run ruff check .` — clean.

- [ ] **Step 9: Run the full suite**

Run: `cd api && uv run pytest -q`
Expected: all green, no skips. Confirm the pre-existing count grew by exactly 18.

- [ ] **Step 10: Commit**

```bash
git add api/doug/check_run.py api/tests/test_check_run.py
git commit -m "Render the verdict as a neutral check run" \
  -m "The App path needs a surface, and the surface must not overstate what
produced it. Two things this codebase already gets wrong elsewhere are
pinned here as tests: a deterministic fallback is announced in the title
rather than a footnote, because score_one falls back silently and the
Verdict is shape-identical either way; and a partial read is stated once,
above the findings it qualifies, instead of being duplicated or dropped.

Deviations render in their own section labelled unvalidated — the
derangement check did not pass — and the tests assert the title and risk
line are byte-identical with and without them (ADR-0007).

The conclusion is hard-coded neutral and a test greps the module for any
other conclusion string, because the real risk is a second create() call
added later behind a severity branch, not this one." \
  -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```

---

### Task 5: Worker (`api/doug/worker.py`)

**Files:**
- Create: `api/doug/worker.py`
- Test: `api/tests/test_worker.py`

**Interfaces:**
- Consumes: `app_auth.installation_client(installation_id: int) -> GitHub` (Task 1); `store.save_review(..., github_repo_id=, installation_id=, head_sha=, source=)` — all keyword, all defaulting to `None` (Task 2); `store.save_deviations(verdict_id, findings, refs, alignment)` (`store.py:249`); `review.fetch_pr(gh, owner, repo, number) -> (PRMetadata, str)` (`review.py:86`); `review.score_one(meta, diff) -> (tier, Verdict, ReaderVerdict|None, Coverage|None)` (`review.py:118`); `review.read_intent(gh, owner, repo, meta, diff) -> IntentRead | IntentFailure | None` (`review.py:161`); `check_run.render/post` (Task 4); `reader.MODEL` (`reader.py:24`).
- Consumes from Task 3 (`ingest.py`), confirmed against its draft:
  - `claim() -> dict | None` — a **plain dict** (not a `Row`; the worker holds it after the connection closes) carrying every `review_jobs` column, primary key under `"id"`. Returns `None` when the ledger is unconfigured, so `drain` is a safe no-op on a ledger-less deployment — do **not** wrap it in try/except for that case.
  - `complete(job_id, verdict_id, *, claim_generation)`, `fail(job_id, error, *, claim_generation, max_attempts=3)`, `release(job_id, *, claim_generation)`, `supersede(job_id, *, claim_generation)` — all return `bool`. Terminals fence on `(status='running' AND claim_generation=<token>)` so a stale worker after reclaim cannot finish under someone else's claim. Pass `claim_generation=job["claim_generation"]` from every terminal call site. `started_at` remains the lease clock for `reclaim_stalled` only.
  - `fail(...)` — truncates `error` to 500 chars, clears `started_at`, and flips to `'failed'` at `attempts >= max_attempts`, so three attempts total. **It also sets `enqueued_at=now`**, which re-pends a job to the *back* of the queue.
  - `enqueue(...) -> int | None` — `None` on the unique-index duplicate; **raises `RuntimeError` when `DATABASE_URL` is unset** (see Task 6, which guards that at the edge).
  - `IntentFailure` from `read_intent` surfaces as a weight-0 `intent-unavailable` reason; score/band unchanged (ADR-0007).
- **The drain's retry behaviour is a two-part fix and neither half works alone.** `fail` re-pends a job, and `claim` takes the oldest pending, so a poison job is immediately re-claimed by the same pass: three attempts burn in under a second against a fault that has had no time to clear. Task 3's `enqueued_at=now` sends the re-pended job to the back so the drain reaches everything else first; Step 3's seen-set below stops the pass when it laps round to a job it already ran. Verified by running both: with the seen-set alone, `drain()` returns 1 instead of 2 on the two-job test and the second job never runs — the seen-set breaks the loop where the ordering change is what lets it get past.
- Produces: `process_job(job: dict) -> int | None`; `drain(max_jobs: int = 20) -> int`. Task 6 calls `drain` from a `BackgroundTasks` kick; Task 7 adds `reconcile_installation` / `reconcile_all` to this module.

**Fixture note:** DB tests use file-backed sqlite under `tmp_path` (`sqlite:///{tmp_path}/doug.db`), the pattern at `test_store.py:37-41`. Plain in-memory `sqlite://` gives each connection its own database, which breaks the moment `drain` runs from a background thread — verified: SQLAlchemy uses `QueuePool` for file sqlite and cross-thread writes work.

- [ ] **Step 1: Write the failing test — the pipeline persists with App identity**

Create `api/tests/test_worker.py`:

```python
"""One claimed job in, one check run out.

The webhook must never review inline, so everything expensive lives here.
These tests cut all five network seams (installation token, PR fetch,
scoring, intent read, check run) and assert on what survives in the
ledger, because the ledger row is the product — the check run is a copy.
"""

import os
from types import SimpleNamespace

from sqlalchemy import create_engine, select

from doug import app_auth, check_run, ingest, reader, review, store, worker
from doug.models import Band, PRMetadata, Reason, Verdict

JOB = dict(
    installation_id=150424894,
    github_repo_id=987,
    repo_full_name="drewjst/doug",
    pr_number=7,
    head_sha="a" * 40,
)

RV = reader.ReaderVerdict.model_validate(
    {
        "risk_score": 62,
        "rationale": "Unlocked cache write.",
        "findings": [
            {
                "category_slug": "race-condition",
                "description": "Cache write is not guarded",
                "file": "cache.py",
                "severity": "high",
            }
        ],
    }
)

VERDICT = Verdict(
    score=0.62,
    band=Band.FLAGGED,
    threshold=0.30,
    reasons=[
        Reason(rule="reader:race-condition", label="Cache write is not guarded", weight=0.0)
    ],
)

COV = reader.Coverage(diff_chars=400, sent_chars=400, files_sent=1, files_unseen=[])


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _pr() -> PRMetadata:
    return PRMetadata.model_validate(
        dict(number=7, title="Add cache", author="dev", files=["cache.py"])
    )


def _gh(heads: dict[int, str] | None = None):
    """A client whose pulls.get reports the PR's current head SHA.

    By default that is the head of the newest job queued for the PR — the
    branch has not moved since enqueue, which is the ordinary case and
    keeps every other test free of SHA bookkeeping. `heads` moves it, which
    is how a test simulates a push landing between enqueue and claim.
    """
    heads = heads or {}

    def _get(*, owner, repo, pull_number):
        sha = heads.get(pull_number)
        if sha is None:
            with create_engine(os.environ["DATABASE_URL"]).connect() as conn:
                sha = conn.execute(
                    select(store.review_jobs.c.head_sha)
                    .where(store.review_jobs.c.pr_number == pull_number)
                    .order_by(store.review_jobs.c.id.desc())
                    .limit(1)
                ).scalar_one()
        return SimpleNamespace(parsed_data=SimpleNamespace(head=SimpleNamespace(sha=sha)))

    return SimpleNamespace(rest=SimpleNamespace(pulls=SimpleNamespace(get=_get)))


def _wire(monkeypatch, *, tier="reader", intent=None, fetch=None, heads=None) -> list[dict]:
    """Cut every seam that would touch the network. Returns the posted
    check runs, which is what a caller of this pipeline can observe."""
    posted: list[dict] = []
    gh = _gh(heads)
    monkeypatch.setattr(app_auth, "installation_client", lambda i: gh)
    monkeypatch.setattr(review, "fetch_pr", fetch or (lambda gh, o, r, n: (_pr(), "+ x")))
    monkeypatch.setattr(
        review,
        "score_one",
        lambda meta, diff: (
            tier,
            VERDICT.model_copy(deep=True),
            RV if tier == "reader" else None,
            COV if tier == "reader" else None,
        ),
    )
    monkeypatch.setattr(review, "read_intent", lambda gh, o, r, m, d: intent)
    monkeypatch.setattr(
        check_run,
        "post",
        lambda gh, o, r, sha, title, summary: posted.append(
            dict(owner=o, repo=r, head_sha=sha, title=title, summary=summary)
        ),
    )
    return posted


def _rows(url, table):
    with create_engine(url).connect() as conn:
        return [dict(r) for r in conn.execute(select(table)).mappings()]


def test_process_job_persists_with_the_app_identity_columns(tmp_path, monkeypatch):
    """Tenancy identity (Global Constraints): every App-path write carries
    the installation, the numeric repo id and the head SHA. A row keyed
    only on "drewjst/doug" cannot be scoped to a customer and does not
    survive a repo rename — the name is display-only."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    job_id = ingest.enqueue(**JOB)
    verdict_id = worker.process_job(ingest.claim())

    (v,) = _rows(url, store.verdicts)
    (j,) = _rows(url, store.review_jobs)
    assert v["id"] == verdict_id
    assert v["source"] == "app"
    assert v["installation_id"] == JOB["installation_id"]
    assert v["github_repo_id"] == JOB["github_repo_id"]
    assert v["head_sha"] == JOB["head_sha"]
    assert v["repo"] == "drewjst/doug" and v["pr_number"] == 7
    assert v["tier"] == "reader" and v["model"] == reader.MODEL
    assert j["id"] == job_id and j["status"] == "done" and j["verdict_id"] == verdict_id


def test_the_reader_tier_records_the_coverage_it_read_at(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    (r,) = _rows(url, store.reads)
    assert r["diff_chars"] == 400 and r["sent_chars"] == 400


def test_the_deterministic_tier_claims_no_model_and_no_coverage(tmp_path, monkeypatch):
    """model is the reader's provenance. Stamping it on a fallback row
    would make the ledger claim opus-5 scored a PR whose diff was never
    opened, and every precision number computed over tier would be wrong."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch, tier="deterministic")
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    (v,) = _rows(url, store.verdicts)
    assert v["tier"] == "deterministic" and v["model"] is None
    assert _rows(url, store.reads) == []


def test_the_check_run_is_posted_against_the_jobs_head_sha(tmp_path, monkeypatch):
    """Not the PR's current SHA. A push burst means pulls.get already
    returns a newer commit than the one this job was enqueued for, and
    hanging this verdict on it would attach a read of one diff to a
    different one — while that newer SHA has a job of its own."""
    _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    assert posted[0]["head_sha"] == JOB["head_sha"]
    assert (posted[0]["owner"], posted[0]["repo"]) == ("drewjst", "doug")
    assert posted[0]["title"].lower().startswith("flagged")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_worker.py -q`
Expected: FAIL — collection error, `ModuleNotFoundError: No module named 'doug.worker'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/doug/worker.py`:

```python
"""The job pipeline — one claimed job in, one check run out.

Everything the webhook must not do inline lives here: minting an
installation token, fetching the PR, scoring it, persisting it, posting
the check run. The handler's whole job is to make the work durable and
return 202; a delivery must never wait on a paid model read.

Failure policy differs from the CI-token review path's on purpose.
There, a down ledger
must not fail somebody's CI, so save_review's exception becomes a reason
on the response and the review still "succeeds". Here the durable row IS
the deliverable — a job marked done having written nothing is a green
checkmark over an empty ledger — so save_review raising fails the job and
ingest.fail decides whether to retry. save_deviations keeps the swallow it
has in api.py:121-130: it is a genuinely separate write (ADR-0007) and the
verdict it hangs off is already durable by then.
"""

import sys

from . import app_auth, check_run, ingest, reader, review, store
from .models import Reason


def process_job(job: dict) -> int | None:
    """Run one job end to end and mark it done. Returns the verdict id."""
    gh = app_auth.installation_client(job["installation_id"])
    owner, name = job["repo_full_name"].split("/", 1)

    # Read the PR's current head before spending anything on it. A job can
    # sit in the queue behind a backlog, or be re-pended by a retry, long
    # enough for the branch to move — and fetch_pr would then read the NEW
    # diff while every identity column, the unique index and the check run
    # still said the old SHA. That mislabels a read rather than losing one,
    # which is worse: the verdict looks like evidence about a commit it
    # never saw. The SHA that overtook this one gets its own job.
    current = gh.rest.pulls.get(
        owner=owner, repo=name, pull_number=job["pr_number"]
    ).parsed_data.head.sha
    if current != job["head_sha"]:
        ingest.supersede(job["id"], claim_generation=job["claim_generation"])
        ingest.enqueue(
            job["installation_id"],
            job["github_repo_id"],
            job["repo_full_name"],
            job["pr_number"],
            current,
        )
        return None

    meta, diff = review.fetch_pr(gh, owner, name, job["pr_number"])
    tier, verdict, rv, cov = review.score_one(meta, diff)
    intent_result = review.read_intent(gh, owner, name, meta, diff)
    if isinstance(intent_result, review.IntentFailure):
        verdict.reasons.append(
            Reason(rule="intent-unavailable", label=intent_result.detail, weight=0.0)
        )
        intent_read = None
    else:
        intent_read = intent_result

    verdict_id = store.save_review(
        job["repo_full_name"],
        job["pr_number"],
        tier,
        verdict,
        rv,
        model=reader.MODEL if tier == "reader" else None,
        pr_meta=meta.model_dump(mode="json"),
        coverage=cov,
        github_repo_id=job["github_repo_id"],
        installation_id=job["installation_id"],
        head_sha=job["head_sha"],
        source="app",
    )
    if intent_read is not None:
        try:
            store.save_deviations(
                verdict_id,
                intent_read.findings,
                intent_read.refs,
                intent_read.alignment,
            )
        except Exception as e:  # noqa: BLE001 — the verdict is already saved
            verdict.reasons.append(
                Reason(rule="deviations-unrecorded", label=str(e)[:200], weight=0.0)
            )

    title, summary = check_run.render(tier, verdict, intent_read, cov)
    # complete before post: a lost claim must not emit a check run the
    # second holder will also post via identity replay. The job's head SHA,
    # never meta's: by now pulls.get may already be returning a newer commit.
    if not ingest.complete(
        job["id"], verdict_id, claim_generation=job["claim_generation"]
    ):
        return verdict_id  # claim lost — skip check run; second holder replays
    check_run.post(gh, owner, name, job["head_sha"], title, summary)
    return verdict_id


def drain(max_jobs: int = 20) -> int:
    """Claim and run up to max_jobs. Returns how many were attempted.

    Bounded because this runs inside a request's background task: an
    unbounded drain on a busy morning would hold a Cloud Run instance for
    minutes past the response it belongs to. The next delivery kicks it
    again, and reconcile catches anything neither ever reaches.

    One job's failure must not strand the queue behind it — the whole
    queue is FIFO-ish and a poison job would otherwise block every PR
    opened after it.
    """
    ingest.reclaim_stalled()
    attempted = 0
    seen: set[int] = set()
    while attempted < max_jobs:
        job = ingest.claim()
        if job is None:
            break
        if job["id"] in seen:
            # Lapped the queue: ingest.fail re-pends a job below the attempt
            # cap, so the only thing left to claim is something this pass
            # already failed. Retrying it here is not a retry — nothing has
            # had time to change — and it would burn the whole attempt
            # budget against one transient fault in under a second.
            ingest.release(job["id"], claim_generation=job["claim_generation"])
            break
        seen.add(job["id"])
        attempted += 1
        try:
            process_job(job)
        except Exception as e:  # noqa: BLE001 — ingest.fail decides retry vs give up
            print(
                f"doug: job {job['id']} failed ({type(e).__name__}: {e})",
                file=sys.stderr,
            )
            ingest.fail(job["id"], str(e), claim_generation=job["claim_generation"])
    return attempted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_worker.py -q`
Expected: 4 passed.

- [ ] **Step 5: Write the failing test — deviations and their isolation**

Append to `api/tests/test_worker.py`:

```python
def _intent(findings=None):
    return review.IntentRead(
        alignment=41,
        refs=["ADR-0002"],
        findings=findings
        if findings is not None
        else [
            reader.DeviationFinding(
                type="contradicts-ticket",
                description="Edits the frozen reader prompt",
                severity="high",
            )
        ],
        coverage=COV,
    )


def test_deviations_are_recorded_against_the_verdict(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch, intent=_intent())
    ingest.enqueue(**JOB)
    verdict_id = worker.process_job(ingest.claim())

    (d,) = _rows(url, store.deviations)
    assert d["verdict_id"] == verdict_id
    assert d["kind"] == "contradicts-ticket" and d["intent_alignment"] == 41
    (v,) = _rows(url, store.verdicts)
    assert v["score"] == 0.62 and v["band"] == "flagged"
    assert "unvalidated" in posted[0]["summary"].lower()


def test_a_failed_deviation_write_does_not_cost_the_verdict(tmp_path, monkeypatch):
    """ADR-0007 makes this a separate write, which is exactly why it must
    not be able to fail the job: retrying would re-run a paid read to
    recover a row the risk verdict does not depend on. It is reported on
    the check run instead of being swallowed silently."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch, intent=_intent())

    def _boom(*a, **k):
        raise RuntimeError("deviations table is gone")

    monkeypatch.setattr(store, "save_deviations", _boom)
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())

    (v,) = _rows(url, store.verdicts)
    (j,) = _rows(url, store.review_jobs)
    assert v["score"] == 0.62
    assert j["status"] == "done" and j["verdict_id"] == v["id"]
    assert "deviations-unrecorded" in posted[0]["summary"]


def test_no_intent_read_writes_no_deviation_row(tmp_path, monkeypatch):
    """"No read happened" and "read happened, found nothing" are different
    facts and store.save_deviations already encodes the second as a
    kind='none' row. The worker must not blur them by calling it anyway."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch, intent=None)
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    assert _rows(url, store.deviations) == []
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_worker.py -q`
Expected: 7 passed.

- [ ] **Step 7: Write the failing test — drain semantics**

Append to `api/tests/test_worker.py`:

```python
def test_drain_on_an_empty_queue_is_zero(tmp_path, monkeypatch):
    """Every delivery kicks a drain, including the ones that enqueue
    nothing. The common case must cost one claim and return."""
    _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    assert worker.drain() == 0


def test_drain_runs_the_queue_and_marks_each_job_done(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    ingest.enqueue(**JOB)
    ingest.enqueue(**{**JOB, "pr_number": 8, "head_sha": "b" * 40})
    assert worker.drain() == 2
    assert {r["status"] for r in _rows(url, store.review_jobs)} == {"done"}
    assert sorted(p["head_sha"] for p in posted) == ["a" * 40, "b" * 40]


def test_a_failing_job_does_not_strand_the_queue(tmp_path, monkeypatch):
    """A poison job — a deleted PR, a revoked token — is claimed before
    every PR opened after it. If its exception escaped the loop, one bad
    job would silently stop reviewing an entire installation."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)

    def _fetch(gh, owner, repo, number):
        if number == 7:
            raise RuntimeError("boom: 404 pull request not found")
        return _pr(), "+ x"

    monkeypatch.setattr(review, "fetch_pr", _fetch)
    ingest.enqueue(**JOB)
    ingest.enqueue(**{**JOB, "pr_number": 8, "head_sha": "b" * 40})

    assert worker.drain() == 2
    rows = {r["pr_number"]: r for r in _rows(url, store.review_jobs)}
    assert rows[7]["status"] == "pending" and rows[7]["attempts"] == 1
    assert "boom" in rows[7]["error"]
    assert rows[8]["status"] == "done"
    assert [p["head_sha"] for p in posted] == ["b" * 40]
    assert _rows(url, store.verdicts)[0]["pr_number"] == 8


def test_a_job_that_keeps_failing_stops_being_retried(tmp_path, monkeypatch):
    """Below the cap a failure is pending (transient: a 502, a token race).
    At the cap it is failed, because re-running a paid read against a PR
    that will never fetch is spend with no possible verdict."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)

    def _fetch(gh, owner, repo, number):
        raise RuntimeError("gone")

    monkeypatch.setattr(review, "fetch_pr", _fetch)
    ingest.enqueue(**JOB)
    for _ in range(3):
        worker.drain()
    (j,) = _rows(url, store.review_jobs)
    assert j["status"] == "failed" and j["attempts"] == 3


def test_drain_stops_at_max_jobs(tmp_path, monkeypatch):
    """The drain runs inside a request's background task. Unbounded, a
    backlog would hold the instance long past the response it belongs to —
    the next delivery kicks it again."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    for n in (7, 8, 9):
        ingest.enqueue(**{**JOB, "pr_number": n, "head_sha": f"{n}" * 40})
    assert worker.drain(max_jobs=2) == 2
    statuses = sorted(r["status"] for r in _rows(url, store.review_jobs))
    assert statuses == ["done", "done", "pending"]


def test_a_failed_job_is_not_retried_inside_the_same_pass(tmp_path, monkeypatch):
    """ingest.fail re-pends a job below the attempt cap, and the drain
    claims whatever is pending — so without a guard one poison job is
    claimed, failed, re-pended and re-claimed until its three attempts are
    gone, inside a single pass lasting under a second. That is not a retry
    policy; nothing has had time to change. Spreading the attempts across
    passes is what makes "transient" a hypothesis worth holding."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)

    def _fetch(gh, owner, repo, number):
        raise RuntimeError("502 from GitHub")

    monkeypatch.setattr(review, "fetch_pr", _fetch)
    ingest.enqueue(**JOB)

    assert worker.drain() == 1
    (j,) = _rows(url, store.review_jobs)
    assert j["attempts"] == 1
    # Released, not left running: the next pass has to be able to claim it.
    assert j["status"] == "pending" and j["started_at"] is None


def test_a_stale_head_is_superseded_and_the_current_one_requeued(tmp_path, monkeypatch):
    """A job can wait behind a backlog, or be re-pended by a retry, long
    enough for the branch to move. fetch_pr would then read the NEW diff
    while the identity columns, the unique index and the check run all
    still said the old SHA — a verdict labelled as evidence about a commit
    it never saw. Losing the read would be better than mislabelling it;
    doing neither is better still."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch, heads={7: "c" * 40})
    ingest.enqueue(**JOB)

    assert worker.process_job(ingest.claim()) is None

    jobs = {j["head_sha"]: j for j in _rows(url, store.review_jobs)}
    assert jobs["a" * 40]["status"] == "superseded"
    assert jobs["c" * 40]["status"] == "pending"
    # Nothing was paid for and nothing was published against the stale SHA.
    assert _rows(url, store.verdicts) == []
    assert posted == []


def test_a_force_push_ping_pong_cannot_spin_the_drain(tmp_path, monkeypatch):
    """The seen-set does double duty, and this is the second job.

    ingest.enqueue REVIVES a superseded row rather than inserting beside it
    (Task 3), so a branch flipping between two SHAs makes each job stale on
    arrival, supersede itself, and revive the other. The two hand the queue
    back and forth with no new rows and no progress — an unbounded spin
    inside a request's background task. Claiming a job this pass already
    ran is the signal that the queue has lapped, whatever the reason.

    The bound rests on _revive updating in place: the row keeps its id, so
    the seen-set recognises it. A revive written as a fresh insert — an
    equally natural way to write it, and one every Task 3 test still
    passes — would hand back a new id each time and quietly restore the
    unbounded loop. Two tasks, one mechanism.
    """
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    flip = iter(["c" * 40, "a" * 40] * 40)

    def _get(**kw):
        return SimpleNamespace(parsed_data=SimpleNamespace(head=SimpleNamespace(sha=next(flip))))

    monkeypatch.setattr(
        app_auth,
        "installation_client",
        lambda i: SimpleNamespace(rest=SimpleNamespace(pulls=SimpleNamespace(get=_get))),
    )
    ingest.enqueue(**JOB)

    # Two jobs touched, then the lap is detected — not max_jobs (20) spins.
    assert worker.drain() == 2
    statuses = {j["head_sha"]: j["status"] for j in _rows(url, store.review_jobs)}
    assert statuses == {"a" * 40: "pending", "c" * 40: "superseded"}
    # Nothing was read and nothing was published while the branch thrashed.
    assert _rows(url, store.verdicts) == []
    assert posted == []
```

Both new drain tests were mutation-checked by deleting the seen-set: `test_a_failed_job_is_not_retried_inside_the_same_pass` fails `assert 3 == 1` (all three attempts burned in one pass) and `test_a_force_push_ping_pong_cannot_spin_the_drain` fails `assert 20 == 2` (the spin, bounded only by `max_jobs`). Neither can pass against a drain without the guard.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_worker.py -q`
Expected: 15 passed (this task's whole contribution to the file). Then `cd api && uv run ruff check .` — clean. Task 7 adds its five reconcile tests to this same file later, taking it to 20 — so a count of 20 here means Task 7 has already landed, not that something is wrong.

`test_a_failing_job_does_not_strand_the_queue` is the one that fails if Task 3's `enqueued_at=now` bump in `fail` is missing: `drain()` returns 1 instead of 2 and the second job never runs. That is the intended signal, not a flaky test — do not weaken the assertion, land the Task 3 half.

- [ ] **Step 9: Run the full suite**

Run: `cd api && uv run pytest -q`
Expected: all green, no skips.

- [ ] **Step 10: Commit**

```bash
git add api/doug/worker.py api/tests/test_worker.py
git commit -m "Run claimed jobs through the review pipeline" \
  -m "The webhook may not review inline — a delivery would then wait on a paid
model read — so the whole pipeline moves here behind a claimable queue:
installation token, fetch, score, persist with App identity, check run.

Failure policy deliberately differs from /v1/review's. There a down ledger
must not fail somebody's CI, so save_review's exception becomes a reason.
Here the durable row is the deliverable, so save_review raising fails the
job and ingest.fail decides retry. save_deviations keeps the swallow: it
is a separate write (ADR-0007) and retrying it would re-run a paid read to
recover a row the risk verdict does not depend on.

A job whose head SHA is no longer the PR's is superseded and the current
one requeued, rather than read. Reading the new diff under the old SHA
would mislabel a verdict as evidence about a commit it never saw, which is
worse than not producing one; the check run is posted against the job's
SHA for the same reason.

drain is bounded, catches per job, and refuses to re-claim a job it
already failed this pass — with ingest.fail re-pending below the attempt
cap, one poison job would otherwise burn all three attempts in under a
second and call that a retry policy." \
  -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```

---

### Task 6: Webhook rewrite (`api/doug/api.py`)

**Deps: Task 7 must land before Step 11.** The `installation created` branch calls `worker.reconcile_installation`, and the test monkeypatches it without `raising=False` on purpose — if Task 7 has not run, Step 12 fails loudly with `AttributeError` rather than passing against a stub. Either implement Task 7 first or accept a red Task 6 until it does.

**Note on the plan skeleton's "delete the unsigned-body branch and its test":** that branch is already gone — commit `0d58554` replaced it with a fail-closed 503 and swapped its pinning test for four others. What remains to remove is nothing; what this task adds is the startup requirement that makes the 503 unreachable, plus the missing coverage for a delivery carrying *no* signature header at all (today only the wrong-digest case is tested). The 503 guard at `api.py:353-360` **stays** as defence in depth: `verify_webhook("", body, sig)` with an empty key is forgeable by anyone, and a lifespan can be bypassed (a sub-app mount, a `TestClient` not entered as a context manager). Dead code that costs three lines and closes a forgery hole is worth keeping.

**Files:**
- Create: none
- Modify: `api/doug/api.py:1-33` (imports + `FastAPI(...)` construction at `:26`), `api/doug/api.py:347-373` (the whole `github_webhook` handler)
- Test: `api/tests/test_api.py:1-6` (imports), append new tests after `:105`

**Interfaces:**
- Consumes: `ingest.enqueue(installation_id, github_repo_id, repo_full_name, pr_number, head_sha) -> int | None` — `None` on the duplicate suppressed by `UNIQUE (installation_id, github_repo_id, pr_number, head_sha)`, and **`RuntimeError` when `DATABASE_URL` is unset** (Task 3); `store.upsert_installation(installation_id, account_login, account_type, state)` and `store.set_installation_repos(installation_id, repos: list[tuple[int, str]], *, replace: bool, state: str = "active")` — the `state` kwarg extends the locked signature, which had nowhere to pass the `state='removed'` its own note requires (confirmed with Task 2); `store.enabled()` (`store.py:143`); `worker.drain()`, `worker.reconcile_installation(installation_id)`; `githubkit.webhooks.verify` (already imported at `api.py:10`); `starlette.concurrency.run_in_threadpool`.
- **Ledger-less deployments are refused at the edge, not at startup.** `enqueue` raises rather than no-opping without a database, which is right — `None` already means "already queued", so a silent no-op would 202 every delivery while reviewing nothing. But that exception must not reach the client as a 500, and `DATABASE_URL` must not join the lifespan check: `store.py:9-11` deliberately supports a ledger-less mode so local dogfooding and the open-source path need no database, and requiring it at startup would break `/v1/score` and the fixture-backed queue along with it. So the webhook alone refuses, with a 503 beside the secret guard. It covers the installation writes too, which would otherwise be silent no-ops.
- Produces: `POST /webhooks/github` returning 202 for everything it accepts and 401 for anything unverified; `lifespan` on the app object.

- [ ] **Step 1: Write the failing test — startup requires the secret, unsigned is rejected**

Edit `api/tests/test_api.py:1-6`. Replace:

```python
import hashlib
import hmac

from fastapi.testclient import TestClient

from doug.api import app
```

with:

```python
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from doug import store, worker
from doug.api import app
```

Then append to `api/tests/test_api.py`:

```python
def test_startup_refuses_to_run_without_a_webhook_secret(monkeypatch):
    """GITHUB_WEBHOOK_SECRET was set out-of-band in production and the
    current deploy() wipes it. A service that boots without it looks
    perfectly healthy while every delivery it accepts is unverifiable —
    and under the App, an accepted delivery is a paid model read that
    anyone who can POST gets to trigger. Refusing at startup is the only
    version of this that shows up in a deploy instead of a bill.

    Note: this only fires when the client is entered as a context manager,
    which is why the module-level `client` above keeps working."""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_WEBHOOK_SECRET"):
        with TestClient(app):
            pass


def test_startup_succeeds_once_the_secret_is_configured(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200


def test_webhook_rejects_a_delivery_with_no_signature_at_all(monkeypatch):
    """The wrong-digest case is covered above; this is the shape an
    attacker sends first, and nothing covered it."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    r = client.post(
        "/webhooks/github", content=b'{"zen":"x"}', headers={"X-GitHub-Event": "ping"}
    )
    assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_api.py -q -k "startup or no_signature"`
Expected: FAIL — `test_startup_refuses_to_run_without_a_webhook_secret` fails with `DID NOT RAISE <class 'RuntimeError'>` (there is no lifespan yet). The other two pass already.

- [ ] **Step 3: Write minimal implementation — the lifespan**

In `api/doug/api.py`, replace the imports at `:1-11`:

```python
"""HTTP surface. Routes stay thin: the product lives in features.py and scoring.py."""

import hmac
import json
import os
from importlib import resources

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from githubkit.webhooks import verify as verify_webhook
from pydantic import BaseModel
```

with:

```python
"""HTTP surface. Routes stay thin: the product lives in features.py and scoring.py."""

import hmac
import json
import os
import sys
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from githubkit.webhooks import verify as verify_webhook
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
```

Replace `api.py:13` :

```python
from . import __version__, precision, reader, review, store
```

with:

```python
from . import __version__, ingest, precision, reader, review, store, worker
```

Replace `api.py:26`:

```python
app = FastAPI(title="Doug", version=__version__)
```

with the following — note it needs **two** blank lines after `from .scoring import default_threshold, score`, not the one the replaced statement had. A decorated top-level function on one blank line is an `I001` from ruff, which is how this was caught:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Refuse to boot without the webhook secret.

    Production's secret was set out-of-band and the current deploy()
    wipes it on the next CI run (see Task 10 — the two must ship
    together). Without it the handler cannot verify anything, and an
    unverified delivery under the App is a paid model read triggered by
    anyone who can POST. A crash-looping revision is a visible failure;
    a running service accepting forged deliveries is not.
    """
    if not os.environ.get("GITHUB_WEBHOOK_SECRET"):
        raise RuntimeError(
            "GITHUB_WEBHOOK_SECRET is unset — refusing to serve /webhooks/github"
        )
    yield


app = FastAPI(title="Doug", version=__version__, lifespan=lifespan)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_api.py -q`
Expected: all pass, including the three new ones. `sys`, `BackgroundTasks`, `run_in_threadpool`, `ingest`, `worker` are unused until Step 7 — `uv run ruff check .` will flag F401 here, which is expected and cleared by Step 7. Do not delete them.

- [ ] **Step 5: Write the failing test — installation lifecycle**

Append to `api/tests/test_api.py`:

```python
SECRET = "s3cret"
INSTALLATION = {"id": 150424894, "account": {"login": "drewjst", "type": "User"}}


def _hook_env(tmp_path, monkeypatch) -> list:
    """Configure the webhook and cut the two background kicks.

    The kicks must be cut, not tolerated: TestClient waits for background
    tasks, so a real worker.drain would claim the job these tests just
    asserted on and run it against a monkeypatch-free pipeline."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    # Materialise the schema here rather than leaving it to whichever
    # request happens to write first. The tests that assert a delivery
    # wrote NOTHING (401s, ignored events, drafts, forks) never reach a
    # write, so without this _table() opens an empty sqlite file and the
    # assertion dies on "no such table" instead of passing.
    assert store.enabled()
    kicks: list = []
    monkeypatch.setattr(worker, "drain", lambda *a, **k: kicks.append("drain"))
    monkeypatch.setattr(worker, "reconcile_installation", lambda i: kicks.append(i))
    return kicks


def _webhook(event: str, payload: dict, secret: str = SECRET):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": _sig(secret.encode(), body, "sha256"),
        },
    )


def _table(tmp_path, table) -> list[dict]:
    with create_engine(f"sqlite:///{tmp_path}/doug.db").connect() as conn:
        return [dict(r) for r in conn.execute(select(table)).mappings()]


def test_installation_created_records_the_account_and_its_repos(tmp_path, monkeypatch):
    """The authoritative repo list arrives exactly once, on this event.
    Everything after it is a delta, so getting this write wrong means an
    installation whose repo set is never correct again."""
    kicks = _hook_env(tmp_path, monkeypatch)
    r = _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [
                {"id": 987, "full_name": "drewjst/doug"},
                {"id": 988, "full_name": "drewjst/other"},
            ],
        },
    )
    assert r.status_code == 202

    (inst,) = _table(tmp_path, store.installations)
    assert inst["installation_id"] == 150424894
    assert inst["account_login"] == "drewjst" and inst["account_type"] == "User"
    assert inst["state"] == "active"

    repos = {r["github_repo_id"]: r for r in _table(tmp_path, store.installation_repos)}
    assert set(repos) == {987, 988}
    assert repos[987]["full_name"] == "drewjst/doug"
    assert all(r["state"] == "active" for r in repos.values())
    # Reconcile is queued, not run inline: it lists open PRs over the
    # network and the 202 must not wait on it. The drain is chained behind
    # it inside the same task — see the dedicated test below.
    assert kicks == [150424894, "drain"]


def test_installation_deleted_flips_state_without_dropping_history(tmp_path, monkeypatch):
    """Uninstalling ends the permission, not the record. Deleting rows
    would take the tenancy context off every verdict already written, and
    reinstalling is the single most common thing a trialling team does."""
    _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [{"id": 987, "full_name": "drewjst/doug"}],
        },
    )
    assert _webhook(
        "installation", {"action": "deleted", "installation": INSTALLATION}
    ).status_code == 202

    (inst,) = _table(tmp_path, store.installations)
    assert inst["state"] == "deleted"
    assert len(_table(tmp_path, store.installation_repos)) == 1


def test_installation_suspend_and_unsuspend_round_trip(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    _webhook("installation", {"action": "created", "installation": INSTALLATION,
                              "repositories": []})
    _webhook("installation", {"action": "suspend", "installation": INSTALLATION})
    assert _table(tmp_path, store.installations)[0]["state"] == "suspended"
    _webhook("installation", {"action": "unsuspend", "installation": INSTALLATION})
    assert _table(tmp_path, store.installations)[0]["state"] == "active"


def test_installation_repositories_merges_both_deltas(tmp_path, monkeypatch):
    """One delivery can carry both lists. A removal marks state rather than
    deleting the row, so a verdict written while the repo was installed
    still resolves to the repo it was written about."""
    _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [{"id": 987, "full_name": "drewjst/doug"}],
        },
    )
    r = _webhook(
        "installation_repositories",
        {
            "action": "added",
            "installation": INSTALLATION,
            "repositories_added": [{"id": 988, "full_name": "drewjst/other"}],
            "repositories_removed": [{"id": 987, "full_name": "drewjst/doug"}],
        },
    )
    assert r.status_code == 202
    repos = {r["github_repo_id"]: r for r in _table(tmp_path, store.installation_repos)}
    assert repos[987]["state"] == "removed"
    assert repos[988]["state"] == "active"


def test_a_new_installation_reviews_its_backlog_without_waiting(tmp_path, monkeypatch):
    """reconcile_installation only enqueues. Chaining the drain behind it is
    what makes the cutover's "a check run appears within seconds of
    installing" true — otherwise a fresh install's whole backlog sits
    pending until somebody happens to open the next PR, which on a quiet
    repo can be days. Order matters: draining first would drain an empty
    queue."""
    kicks = _hook_env(tmp_path, monkeypatch)
    _webhook(
        "installation",
        {"action": "created", "installation": INSTALLATION, "repositories": []},
    )
    assert kicks == [150424894, "drain"]


def test_only_a_new_installation_kicks_reconcile(tmp_path, monkeypatch):
    """Suspend/unsuspend/delete change state and nothing else. Reconciling on
    them would list every open PR of an installation that just told us to
    stop looking at it."""
    kicks = _hook_env(tmp_path, monkeypatch)
    for action in ("suspend", "unsuspend", "deleted"):
        _webhook("installation", {"action": action, "installation": INSTALLATION})
    assert kicks == []
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_api.py -q -k installation`
Expected: FAIL — the handler still discards everything, so `_table(tmp_path, store.installations)` unpacks an empty list: `ValueError: not enough values to unpack (expected 1, got 0)`.

- [ ] **Step 7: Write minimal implementation — the handler and the gating table**

Replace `api/doug/api.py:347-373` in full — from `@app.post("/webhooks/github", status_code=202)` through the final `return Response(status_code=202)`, including the two stale comment blocks ("Phase 2 (the Live Gate) will parse pull_request events here…"):

```python
# Actions that mean "this PR's head changed, or is newly eligible". Anything
# else — closed, labeled, edited, review_requested — is not a new diff and
# must not buy a read.
PR_ACTIONS = frozenset({"opened", "synchronize", "reopened", "ready_for_review"})
INSTALLATION_STATES = {
    "created": "active",
    "deleted": "deleted",
    "suspend": "suspended",
    "unsuspend": "active",
}


def _record_installation(payload: dict, action: str) -> None:
    inst = payload["installation"]
    account = inst.get("account") or {}
    store.upsert_installation(
        inst["id"],
        account.get("login", ""),
        account.get("type", ""),
        INSTALLATION_STATES[action],
    )
    if action == "created":
        # The only authoritative repo list we are ever sent; everything
        # after this is a delta against it.
        store.set_installation_repos(
            inst["id"],
            [(r["id"], r["full_name"]) for r in payload.get("repositories", [])],
            replace=True,
        )


def _merge_installation_repos(payload: dict) -> None:
    inst_id = payload["installation"]["id"]
    for key, state in (("repositories_added", "active"), ("repositories_removed", "removed")):
        repos = [(r["id"], r["full_name"]) for r in payload.get(key, [])]
        if repos:
            # A removal marks state and never deletes: verdicts already
            # written must still resolve to the repo they describe.
            store.set_installation_repos(inst_id, repos, replace=False, state=state)


def _reconcile_then_drain(installation_id: int) -> None:
    """Heal the backlog, then actually review it.

    reconcile_installation only enqueues. Without the drain chained behind
    it, everything a new installation just discovered sits pending until
    some unrelated delivery happens to kick one — which on a quiet repo is
    the difference between "reviews appear within seconds of installing"
    and "reviews appear whenever someone next opens a PR". The cutover
    checklist in Task 10 asserts the first.
    """
    worker.reconcile_installation(installation_id)
    worker.drain()


def _enqueue_pull_request(payload: dict) -> int | None:
    """Gate then enqueue. None means deliberately skipped or a duplicate."""
    pr = payload["pull_request"]
    if pr.get("draft"):
        # Work in progress nobody has asked for review on. ready_for_review
        # is the event that admits it.
        return None
    base = pr["base"]["repo"]
    # head.repo is null when the fork was deleted, which fails this the same
    # way a fork does — correctly.
    head = pr["head"].get("repo") or {}
    if head.get("id") != base["id"]:
        # Fork PRs never enqueue: the raw diff enters the prompt
        # (reader._user_text, reader.py:179-187), so an outside contributor
        # opening PRs against a public repo could otherwise drive this
        # account's model spend at will.
        return None
    return ingest.enqueue(
        payload["installation"]["id"],
        base["id"],
        base["full_name"],
        pr["number"],
        pr["head"]["sha"],
    )


@app.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
) -> Response:
    """Verify, record, enqueue, 202. Never reviews inline.

    The 202 is sent only after the job is durable — GitHub does not
    redeliver on our schedule and a job held in memory dies with the
    instance. Everything expensive happens in worker.drain, kicked as a
    background task after the response.

    async only because the signature needs the raw body; every synchronous
    line below runs in the threadpool so a delivery burst cannot block the
    event loop.
    """
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        # Unreachable when the app booted through its lifespan, which
        # refuses without this. Kept because verify() with an empty key is
        # forgeable by anyone and a lifespan is bypassable (sub-app mount,
        # a TestClient not used as a context manager).
        raise HTTPException(status_code=503, detail="GITHUB_WEBHOOK_SECRET not configured")
    body = await request.body()
    # githubkit's verify() reads the digest from the signature prefix, not
    # from the header name, so an attacker-supplied "sha1=" would downgrade
    # the comparison. Pin it.
    if not x_hub_signature_256.startswith("sha256="):
        raise HTTPException(status_code=401, detail="bad signature")
    if not verify_webhook(secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        payload = json.loads(body)
    except ValueError:
        # Signed, so it came from someone holding the secret — but not
        # something we can act on. 202 rather than 4xx: a retry loop over a
        # body that will never parse helps nobody.
        print("doug: webhook body was signed but not JSON", file=sys.stderr)
        return Response(status_code=202)

    action = payload.get("action", "")
    # The gating table, evaluated once and before any guard that touches the
    # store. An event we do not handle — ping, push, an action outside the
    # table — must not depend on a ledger it never reaches. Scoping this
    # narrowly is load-bearing: the pre-existing
    # test_webhook_accepts_a_valid_sha256_signature posts a valid signature
    # with no event header and no database, and must still get its 202.
    handled = (
        (x_github_event == "installation" and action in INSTALLATION_STATES)
        or (x_github_event == "installation_repositories" and action in ("added", "removed"))
        or (x_github_event == "pull_request" and action in PR_ACTIONS)
    )
    if not handled:
        # Accepted and ignored, on purpose: a 4xx would put GitHub into a
        # redelivery loop over events we chose not to handle.
        return Response(status_code=202)
    if not store.enabled():
        # ingest.enqueue raises without a database rather than no-opping,
        # and store's installation writes would no-op silently. Either way
        # a 202 here would mean "queued" over an empty ledger. Refused at
        # this endpoint only: DATABASE_URL stays optional for the rest of
        # the service (store.py:9-11), so it cannot go in the lifespan.
        raise HTTPException(status_code=503, detail="no ledger configured")
    inst = payload.get("installation")
    if not isinstance(inst, dict) or not isinstance(inst.get("id"), int):
        # Defensive: App webhooks always carry this, and a ping never does.
        # Without it there is no tenant to attribute the work to and no
        # token to do it with. The id is checked here, not just the key,
        # because every branch below indexes installation["id"] — this is
        # what makes those indexes total instead of a KeyError 500 that
        # GitHub would redeliver into the same 500.
        return Response(status_code=202)

    if x_github_event == "installation":
        await run_in_threadpool(_record_installation, payload, action)
        if action == "created":
            # Heal what the App missed before it was installed. Queued, not
            # inline: it lists every open PR over the network.
            background.add_task(_reconcile_then_drain, inst["id"])
    elif x_github_event == "installation_repositories":
        await run_in_threadpool(_merge_installation_repos, payload)
    elif x_github_event == "pull_request":
        job_id = await run_in_threadpool(_enqueue_pull_request, payload)
        if job_id is not None:
            background.add_task(worker.drain)

    return Response(status_code=202)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_api.py -q -k installation`
Expected: 6 passed. Then `cd api && uv run ruff check .` — clean (the Step 4 F401s are now used).

- [ ] **Step 9: Write the failing test — pull_request gating**

Append to `api/tests/test_api.py`:

```python
def _pr_payload(action="opened", *, draft=False, head_repo_id=987, sha="a" * 40, number=7):
    head_repo = None if head_repo_id is None else {"id": head_repo_id}
    return {
        "action": action,
        "installation": INSTALLATION,
        "pull_request": {
            "number": number,
            "draft": draft,
            "head": {"sha": sha, "repo": head_repo},
            "base": {"repo": {"id": 987, "full_name": "drewjst/doug"}},
        },
    }


def test_a_pull_request_event_enqueues_one_durable_job(tmp_path, monkeypatch):
    """The 202 has to mean the work survives this instance. GitHub
    redelivers on its own terms and reconcile is the backstop — neither is
    a reason to answer 202 for a job held only in memory."""
    kicks = _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _pr_payload()).status_code == 202

    (j,) = _table(tmp_path, store.review_jobs)
    assert j["installation_id"] == 150424894
    assert j["github_repo_id"] == 987
    assert j["repo_full_name"] == "drewjst/doug"
    assert j["pr_number"] == 7 and j["head_sha"] == "a" * 40
    assert j["status"] == "pending"
    assert kicks == ["drain"]


def test_every_head_moving_action_enqueues(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    for i, action in enumerate(("opened", "synchronize", "reopened", "ready_for_review")):
        _webhook("pull_request", _pr_payload(action, sha=f"{i}" * 40))
    assert len(_table(tmp_path, store.review_jobs)) == 4


def test_a_draft_pull_request_is_not_enqueued(tmp_path, monkeypatch):
    """A read per push on a branch nobody has asked for review on is spend
    with no consumer. ready_for_review admits it later."""
    kicks = _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _pr_payload(draft=True)).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert kicks == []


def test_a_fork_pull_request_is_not_enqueued(tmp_path, monkeypatch):
    """The raw diff enters the prompt (reader._user_text). If forks
    enqueued, any GitHub user could drive this account's model spend by
    opening PRs against a public repo — no install, no relationship."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _pr_payload(head_repo_id=555)).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []


def test_a_pull_request_whose_fork_was_deleted_is_not_enqueued(tmp_path, monkeypatch):
    """head.repo is null once the fork is gone. It must fail the fork gate
    rather than raise — a KeyError here 500s and GitHub redelivers it."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("pull_request", _pr_payload(head_repo_id=None)).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []


def test_a_redelivery_of_the_same_head_sha_does_not_duplicate(tmp_path, monkeypatch):
    """GitHub redelivers on its own schedule, and 'opened' then
    'synchronize' for one push is normal. Two deliveries of one commit must
    be one review, not two paid reads."""
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request", _pr_payload("opened"))
    _webhook("pull_request", _pr_payload("synchronize"))
    assert len(_table(tmp_path, store.review_jobs)) == 1


def test_a_new_head_sha_enqueues_a_second_job(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    _webhook("pull_request", _pr_payload("opened"))
    _webhook("pull_request", _pr_payload("synchronize", sha="b" * 40))
    shas = sorted(j["head_sha"] for j in _table(tmp_path, store.review_jobs))
    assert shas == ["a" * 40, "b" * 40]
```

- [ ] **Step 10: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_api.py -q -k pull_request`
Expected: FAIL if Step 7 was skipped; with Step 7 in place these pass. Run them before Step 11 either way — a failure here is a gating bug, not a missing feature.

- [ ] **Step 11: Write the failing test — everything else is ignored**

Append to `api/tests/test_api.py`:

```python
def test_unhandled_pull_request_actions_are_accepted_and_ignored(tmp_path, monkeypatch):
    """closed/labeled/edited do not change the diff. A 4xx would put GitHub
    into a redelivery loop over events we chose not to handle, so they are
    202 — but they must not reach the queue."""
    kicks = _hook_env(tmp_path, monkeypatch)
    for action in ("closed", "labeled", "edited", "review_requested", "converted_to_draft"):
        assert _webhook("pull_request", _pr_payload(action)).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert kicks == []


def test_unhandled_events_are_accepted_and_ignored(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    for event in ("push", "check_suite", "issues", "installation_target"):
        r = _webhook(event, {"action": "created", "installation": INSTALLATION})
        assert r.status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert _table(tmp_path, store.installations) == []


def test_ping_is_accepted_without_an_installation(tmp_path, monkeypatch):
    """The App's first delivery, and the only one production has ever sent
    (2026-07-31 23:23:32) — it went through the discard path, so no handler
    that parses a body has ever seen it. Pinging from the App settings page
    rather than from an installation sends no installation key at all, so
    nothing downstream of here may reach for one."""
    _hook_env(tmp_path, monkeypatch)
    assert _webhook("ping", {"zen": "Non-blocking is better than blocking."}).status_code == 202


def test_a_payload_with_no_usable_installation_is_ignored(tmp_path, monkeypatch):
    """Every branch past the guard indexes installation["id"], so the guard
    checks the id and not just the key. Otherwise a malformed-but-signed
    payload is a KeyError 500, and GitHub redelivers it into the same 500.

    All three shapes are quiet 202s: absent, explicitly null, and present
    but id-less."""
    _hook_env(tmp_path, monkeypatch)
    for payload in (
        {"action": "opened"},
        {"action": "opened", "installation": None},
        {"action": "opened", "installation": {"account": {"login": "drewjst"}}},
    ):
        assert _webhook("pull_request", payload).status_code == 202
    assert _table(tmp_path, store.review_jobs) == []
    assert _table(tmp_path, store.installations) == []


def test_a_signed_body_that_is_not_json_is_ignored(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch)
    body = b"not json"
    r = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sig(SECRET.encode(), body, "sha256"),
        },
    )
    assert r.status_code == 202


def test_a_forged_signature_never_reaches_the_queue(tmp_path, monkeypatch):
    """The gating table is only worth anything behind verification. A
    valid-looking payload signed with the wrong key must 401 before any of
    it is parsed."""
    _hook_env(tmp_path, monkeypatch)
    r = _webhook("pull_request", _pr_payload(), secret="wrong-key")
    assert r.status_code == 401
    assert _table(tmp_path, store.review_jobs) == []


def test_the_webhook_refuses_when_there_is_no_ledger(tmp_path, monkeypatch):
    """A 202 means "queued". Without a database there is no queue: the
    installation writes would no-op silently and ingest.enqueue raises. The
    refusal is scoped to this endpoint because DATABASE_URL is optional for
    the rest of the service by design (store.py:9-11) — /v1/score and the
    fixture-backed queue must keep working without one."""
    _hook_env(tmp_path, monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _webhook("pull_request", _pr_payload()).status_code == 503


def test_ping_answers_even_without_a_ledger(monkeypatch):
    """The App's connectivity test is the first delivery a new install
    sends, and answering it 503 would read as "the webhook is broken" while
    pointing at the wrong thing."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _webhook("ping", {"zen": "Speak like a human."}).status_code == 202
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_api.py -q`
Expected: all pass — 24 tests added by this task, on top of the file's pre-existing ones. If `test_installation_created_records_the_account_and_its_repos` errors with `AttributeError: <module 'doug.worker'> has no attribute 'reconcile_installation'`, Task 7 has not landed — implement it first rather than adding `raising=False`.

- [ ] **Step 13: Run the full suite and the linter**

Run: `cd api && uv run pytest -q && uv run ruff check .`
Expected: all green, no skips, no lint findings. Three pre-existing tests must still pass **unchanged**, and each one pins something this task could have broken:

- `test_webhook_refuses_when_secret_unconfigured` and `test_webhook_refuses_signed_body_when_secret_unconfigured` (`test_api.py:66-81`) — the retained defence-in-depth 503. Not deleted.
- `test_webhook_accepts_a_valid_sha256_signature` (`test_api.py:97-105`) — a valid signature, **no** `X-GitHub-Event` header and **no** `DATABASE_URL`, expecting 202. This is why the no-ledger 503 is scoped to handled events only; an unscoped guard turns this green test red, which is exactly how the scoping bug was found. Note that `store.enabled()` caches its engine in a module global keyed on the URL (`store.py:129-140`), so run the file in one process rather than reasoning about test order: each `_hook_env` gets its own `tmp_path` URL and therefore its own engine.

- [ ] **Step 14: Commit**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "Ingest webhook deliveries as durable review jobs" \
  -m "The handler stops discarding everything and starts recording: installation
state and repos, and a queued job per PR head that moved. It still reviews
nothing inline — the 202 is returned once the job is durable, and
worker.drain runs behind it as a background task. All synchronous work
goes through run_in_threadpool so a delivery burst cannot block the loop.

Two gates keep spend attached to a relationship. Drafts are skipped
because nobody has asked for review yet; forks are skipped because the raw
diff enters the prompt, so an outside contributor could otherwise drive
this account's model spend by opening PRs against a public repo. Deleted
forks (head.repo null) fail the same gate rather than raising.

Startup now refuses without GITHUB_WEBHOOK_SECRET. Production's was set
out-of-band and the current deploy wipes it; a crash-looping revision is a
visible failure, a service accepting forged deliveries is not. The
request-time 503 stays as defence in depth, since verify() with an empty
key is forgeable and a lifespan can be bypassed.

A handled event with no ledger 503s, where a 202 would claim work was
queued into nothing. That check is scoped two ways: to this endpoint
rather than the lifespan, because DATABASE_URL is optional for the rest of
the service by design; and to the three handled event types, because an
event we ignore never touches the store and must not start depending on
one.

installation.created chains the drain behind reconcile in the same
background task. Reconcile only enqueues, so without it a new install's
backlog waits for an unrelated delivery to kick it — days, on a quiet
repo." \
  -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```
### Task 7: Reconcile (`api/doug/worker.py`)

**Files:**
- Modify: `api/doug/worker.py` (append after `drain`)
- Modify: `api/doug/store.py` (append after `latest_reviews`, ~`:387`)
- Modify: `api/doug/api.py` (inside the `lifespan` Task 6 adds, immediately after its `GITHUB_WEBHOOK_SECRET` check)
- Test: `api/tests/test_worker.py` (append)

**Interfaces:**
- Consumes: `app_auth.installation_client(installation_id) -> GitHub`; `ingest.enqueue(installation_id, github_repo_id, repo_full_name, pr_number, head_sha) -> int | None`; `worker.drain(max_jobs=20) -> int`; the `installations` / `installation_repos` tables from Task 2.
- Produces: `reconcile_installation(installation_id) -> int`, `reconcile_all() -> int` (locked); plus two new store readers:

```python
def active_installations() -> list[int]                        # NOT list[dict]
def active_repos(installation_id: int) -> list[tuple[int, str]]  # NOT list[dict]
```

  **These two are additions, not renames** — the locked block gives writers (`upsert_installation`, `set_installation_repos`) but no reader, and reconcile cannot work without one. Task 6 calls `reconcile_installation` on `installation.created`.

  **The types above are load-bearing; do not "correct" them to `list[dict]`.** `reconcile_installation` destructures the result directly — `for repo_id, full_name in store.active_repos(installation_id)` — which a list of dicts would not unpack, and `reconcile_all` iterates ids as bare ints. If the Locked Interfaces header block disagrees, the header is the stale copy: these signatures are the ones Task 7's tests exercise.

**On the `enqueue` dedupe claim (verified against the locked semantics, not assumed):** the unique index is `(installation_id, github_repo_id, pr_number, head_sha)` and carries **no status column**. So a job that already ran to `done` collides on insert exactly like a `pending` one, and `enqueue` returns `None`. That collision *is* the dedupe reconcile needs — a head SHA reviewed once is never reviewed again, and a restart against a repo with 40 quiet open PRs enqueues nothing and spends nothing. The `supersede` half of `enqueue` only touches still-`pending` jobs with a *different* head SHA, so it cannot resurrect finished work either.

- [ ] **Step 1: Write the failing tests.** Append to `api/tests/test_worker.py` (`SimpleNamespace`+`FakeGH` idiom follows `tests/test_review.py:21-46`):

```python
def _pull(number=1, head_sha="a" * 40, draft=False, head_repo_id=42, base_repo_id=42):
    return SimpleNamespace(
        number=number,
        draft=draft,
        head=SimpleNamespace(sha=head_sha, repo=SimpleNamespace(id=head_repo_id)),
        base=SimpleNamespace(repo=SimpleNamespace(id=base_repo_id, full_name="o/r")),
    )


class FakeListGH:
    """Only pulls.list — reconcile must never touch pulls.list_files."""

    def __init__(self, pulls):
        self.rest = SimpleNamespace(
            pulls=SimpleNamespace(list=lambda **kw: SimpleNamespace(parsed_data=pulls))
        )


def _installed(tmp_path, monkeypatch, *, repos=((42, "o/r"),)):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    store.upsert_installation(1, "o", "Organization", "active")
    store.set_installation_repos(1, list(repos), replace=True)


def test_reconcile_enqueues_open_prs_and_skips_drafts(tmp_path, monkeypatch):
    _installed(tmp_path, monkeypatch)
    gh = FakeListGH([_pull(number=1), _pull(number=2, draft=True)])
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)
    assert worker.reconcile_installation(1) == 1
    job = ingest.claim()
    assert job["pr_number"] == 1 and job["github_repo_id"] == 42
    assert ingest.claim() is None


def test_reconcile_skips_fork_prs(tmp_path, monkeypatch):
    """A fork's raw diff enters the prompt (_user_text, reader.py:179-187).
    An outside contributor must not be able to drive spend by opening a PR
    during the window when Doug is restarting and reconciling."""
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(head_repo_id=99)]),
    )
    assert worker.reconcile_installation(1) == 0
    assert ingest.claim() is None


def test_reconcile_does_not_requeue_a_reviewed_head_sha(tmp_path, monkeypatch):
    """The property that makes startup reconcile free rather than a full
    re-review: the unique index carries no status, so a head SHA already
    taken to 'done' collides on insert exactly like a pending one."""
    _installed(tmp_path, monkeypatch)
    job_id = ingest.enqueue(1, 42, "o/r", 1, "a" * 40)
    ingest.claim()
    ingest.complete(job_id, None)
    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(number=1, head_sha="a" * 40)]),
    )
    assert worker.reconcile_installation(1) == 0


def test_reconcile_all_covers_only_active_installations(tmp_path, monkeypatch):
    """A suspended or deleted installation still has rows in the table —
    reconciling it would mint tokens for an App the account revoked."""
    _installed(tmp_path, monkeypatch)
    store.upsert_installation(2, "gone", "User", "suspended")
    store.set_installation_repos(2, [(43, "gone/r")], replace=True)
    seen = []

    def client(installation_id):
        seen.append(installation_id)
        return FakeListGH([_pull(number=installation_id)])

    monkeypatch.setattr(worker.app_auth, "installation_client", client)
    assert worker.reconcile_all() == 1
    assert seen == [1]


def test_reconcile_all_survives_one_failing_installation(tmp_path, monkeypatch):
    """Reconcile runs at startup for every tenant at once, so one revoked or
    rate-limited installation raising would leave every other tenant's
    missed PRs unqueued until the next restart."""
    _installed(tmp_path, monkeypatch)
    store.upsert_installation(2, "ok", "User", "active")
    store.set_installation_repos(2, [(43, "ok/r")], replace=True)

    def client(installation_id):
        if installation_id == 1:
            raise RuntimeError("401 bad installation")
        return FakeListGH([_pull(number=5)])

    monkeypatch.setattr(worker.app_auth, "installation_client", client)
    assert worker.reconcile_all() == 1
```

Add `from doug import ingest, store, worker` and `from types import SimpleNamespace` to the imports if Task 5 did not already. Run `cd api && uv run pytest tests/test_worker.py -q` — expect `AttributeError: module 'doug.worker' has no attribute 'reconcile_installation'`.

- [ ] **Step 2: Add the two store readers.** Append to `api/doug/store.py`:

```python
def active_installations() -> list[int]:
    """Installation ids in state 'active'. [] when storage is disabled."""
    engine = _get_engine()
    if engine is None:
        return []
    from sqlalchemy import select

    with engine.connect() as conn:
        return [
            int(r.installation_id)
            for r in conn.execute(
                select(installations.c.installation_id).where(
                    installations.c.state == "active"
                )
            )
        ]


def active_repos(installation_id: int) -> list[tuple[int, str]]:
    """(github_repo_id, full_name) for this installation's active repos.

    A repo removed from an installation keeps state='removed' rather than
    being deleted, so this filters rather than trusting the table's
    contents — the history of what Doug was once installed on is worth
    keeping, and reviewing a removed repo is not.
    """
    engine = _get_engine()
    if engine is None:
        return []
    from sqlalchemy import select

    with engine.connect() as conn:
        return [
            (int(r.github_repo_id), r.full_name)
            for r in conn.execute(
                select(
                    installation_repos.c.github_repo_id,
                    installation_repos.c.full_name,
                ).where(
                    (installation_repos.c.installation_id == installation_id)
                    & (installation_repos.c.state == "active")
                )
            )
        ]
```

- [ ] **Step 3: Implement reconcile.** Append to `api/doug/worker.py` (needs `import sys`; the gate uses `isinstance` so githubkit's UNSET sentinel needs no import):

```python
def _skip_reason(p) -> str | None:
    """Why this open PR must not be enqueued, or None.

    The same gate the pull_request webhook applies in api.py. Duplicated
    rather than shared on purpose: the two callers hold different objects —
    a githubkit model here, a parsed webhook payload there — and githubkit
    models an absent field as the UNSET sentinel, not None, so `if p.draft`
    is not the same test as `p.draft is True`. If the webhook's gate
    changes, this changes with it.
    """
    if getattr(p, "draft", False) is True:
        return "draft"
    head_id = getattr(getattr(getattr(p, "head", None), "repo", None), "id", None)
    base_id = getattr(getattr(getattr(p, "base", None), "repo", None), "id", None)
    # A fork's raw diff enters the prompt (_user_text, reader.py:179-187),
    # so an outside contributor must not be able to drive spend. UNSET or
    # missing ids are treated as a fork: the safe direction to be wrong in
    # is "skip".
    if not isinstance(head_id, int) or not isinstance(base_id, int):
        return "fork"
    return "fork" if head_id != base_id else None


def reconcile_installation(installation_id: int) -> int:
    """Enqueue every reviewable open PR this installation can see.

    The healing path for missed deliveries. GitHub retries a *failed*
    delivery, but a delivery this service 202s and then loses to a restart
    is never retried, and the redelivery window is not a guarantee — so
    recovery does not trust webhooks at all, it re-derives the world from
    the API and lets the queue's unique index throw away what it already
    has.

    Deliberately pulls.list rather than review.fetch_open_prs: that helper
    also fetches per-PR files to build PRMetadata, which is one extra
    request per open PR for data reconcile never reads. The worker fetches
    the diff when the job actually runs.
    """
    gh = app_auth.installation_client(installation_id)
    count = 0
    for repo_id, full_name in store.active_repos(installation_id):
        owner, _, name = full_name.partition("/")
        try:
            pulls = gh.rest.pulls.list(
                owner=owner, repo=name, state="open", per_page=50
            ).parsed_data
        except Exception as e:  # noqa: BLE001 — one unreadable repo is not fatal
            print(
                f"doug: reconcile skipped {full_name} ({type(e).__name__}: {e})",
                file=sys.stderr,
            )
            continue
        for p in pulls:
            if _skip_reason(p) is not None:
                continue
            head_sha = getattr(getattr(p, "head", None), "sha", None)
            if not isinstance(head_sha, str):
                continue
            # Identity comes from the installation_repos row, not from
            # p.base.repo: it is the same repo either way, and the store row
            # is what the rest of the tenancy model keys on.
            #
            # enqueue returns None when this (installation, repo, pr,
            # head_sha) already exists. The unique index carries no status,
            # so a job already taken to 'done' collides exactly like a
            # pending one — which is precisely the dedupe reconcile wants.
            if ingest.enqueue(
                installation_id, repo_id, full_name, p.number, head_sha
            ) is not None:
                count += 1
    return count


def reconcile_all() -> int:
    """Reconcile every active installation. Returns total jobs enqueued."""
    total = 0
    for installation_id in store.active_installations():
        try:
            total += reconcile_installation(installation_id)
        except Exception as e:  # noqa: BLE001 — one bad tenant must not stop the rest
            print(
                f"doug: reconcile failed for installation {installation_id} "
                f"({type(e).__name__}: {e})",
                file=sys.stderr,
            )
    return total
```

Run `cd api && uv run pytest tests/test_worker.py -q` — expect all green.

- [ ] **Step 4: Wire it into startup.** In `api/doug/api.py`, inside the `lifespan` Task 6 added, immediately **after** its `GITHUB_WEBHOOK_SECRET` check (anchor on that check, not on a line number — Task 6 and Task 9 both move this file):

```python
def _startup_reconcile() -> None:
    try:
        n = worker.reconcile_all()
        print(f"doug: reconcile enqueued {n} job(s)", file=sys.stderr)
        worker.drain()
    except Exception as e:  # noqa: BLE001 — catch-up is best-effort, never fatal
        print(f"doug: startup reconcile failed ({type(e).__name__}: {e})", file=sys.stderr)
```

and in the lifespan body:

```python
    if app_auth.enabled() and store.enabled():
        # A thread, not an await and not inline: Cloud Run holds the revision
        # out of rotation until the lifespan yields, and this walks every open
        # PR of every installation and then runs paid model reads on the ones
        # it queued. Blocking startup on that fails the health check and the
        # revision never serves at all. daemon=True so a shutdown is never
        # held open waiting for it.
        threading.Thread(target=_startup_reconcile, daemon=True).start()
```

Add `import sys`, `import threading`, and `worker` / `app_auth` to the package imports. Both guards are off in tests (no `DATABASE_URL`, no App env), so `TestClient(app)` never spawns the thread.

- [ ] **Step 5: Verify.** `cd api && uv run pytest -q && uv run ruff check .` — expect all pass, no lint findings. Then confirm the reconcile path really does not fetch files: `cd api && uv run pytest tests/test_worker.py -q -k reconcile` passes with `FakeListGH`, which defines no `list_files` — an implementation that called it would `AttributeError`.

- [ ] **Step 6: Commit**

```bash
git add api/doug/worker.py api/doug/store.py api/doug/api.py api/tests/test_worker.py
git commit -m "$(cat <<'EOF'
Heal missed deliveries by reconciling open PRs at startup

A delivery this service 202s and then loses to a restart is never
retried by GitHub, so trusting redelivery leaves PRs silently
unreviewed. Reconcile re-derives open PRs from the API instead, and the
queue's unique index — which carries no status column — throws away
every head SHA already reviewed, so the catch-up costs one list call per
repo rather than a re-review.

Runs in a daemon thread: Cloud Run holds a revision out of rotation
until the lifespan yields, and blocking it on paid model reads fails the
health check.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task 8: ADR-0010 + supersede ADR-0003

**Files:**
- Create: `docs/decisions/ADR-0010-surface-is-a-neutral-check-run.md`
- Modify: `docs/decisions/ADR-0003-ci-surface-is-job-summary-only.md:1-5` (frontmatter only)
- Modify: `docs/decisions/ADR-0007-deviation-is-a-separate-stream.md:20-23`, `:25-27`, `:43-44` (surface references only; the decision is unchanged and it stays `accepted`)
- Test: `api/tests/test_intent.py:202` — the ADR-0003 flip changes what Doug's own selector returns, and this is the one test that reads the real records

**Interfaces:**
- Consumes: the frontmatter contract in `docs/decisions/README.md:17-38`, as actually parsed by `intent_providers.parse_record` (`api/doug/intent_providers.py:40-79`) — `status` and `title` are both required or the record returns `None` and is skipped silently; the `ADR-\d+` id comes from the filename stem (`intent_providers.py:68-71`), so the filename is part of the contract.
- Produces: an `accepted` record that Doug's own intent tier will read, and an ADR-0003 that it will not. `intent.select` filters on `d.status.lower() == BINDING` where `BINDING = "accepted"` (`api/doug/intent.py:48,111`) — this flip is the mechanism, not documentation of one.

**Why this ships in the same push as the check-run code:** while ADR-0003 stays `accepted`, it is fed to the reader as binding policy, and it says in as many words that Doug "never posts a check run". A PR adding `check_run.py` would then be flagged by Doug as deviating from Doug's own decisions — a confident false finding, which is the exact failure `docs/decisions/README.md:8-11` warns about.

The same argument applies to ADR-0007, which is why Step 3 is here rather than in a follow-up. ADR-0007 does not need superseding — deviations still never move the score — but it describes the job summary as the live rendering surface three times, and it is the record most likely to be retrieved on any PR touching `check_run.py` or `deviations`. Two records, two different fixes: ADR-0003's *decision* expired, so its status flips; ADR-0007's decision holds and only its prose is stale, so its status does not.

- [ ] **Step 1: Write ADR-0010.** Create `docs/decisions/ADR-0010-surface-is-a-neutral-check-run.md` with exactly this content:

```markdown
---
title: Doug's surface is a neutral check run posted by the App
status: accepted
date: 2026-07-31
supersedes: ADR-0003
---

## Context

ADR-0003 chose the job summary because Doug ran inside someone else's CI
job, and that job was the only surface it had. The GitHub App removes the
job. There is no workflow step, no `$GITHUB_STEP_SUMMARY` file, and no
runner — the review happens on Cloud Run in response to a webhook. The
job summary does not become less attractive under the App; it stops
existing.

The surfaces still reachable are the ones ADR-0003 already ranked: fail
the check, post a check run, comment on the PR. ADR-0003 rejected check
runs because they "imply a pass/fail semantic Doug does not have and does
not want". That objection is about the *conclusion* field, not about
check runs, and the conclusion field has a value for exactly this case:
`neutral`.

Nothing about confidence has improved since ADR-0003. Per-pattern
precision on the seed corpus still resolves to almost nothing once
reweighted to real base rates — one pattern clears the population base
rate on sentry, none on grafana — and the 2026-07-31 derangement check on
the deviation instrument returned FAIL, meaning that instrument is not
currently valid.

## Decision

The surface is one check run named `Doug`, posted against the pull
request's head SHA by the installation, and its conclusion is always
`neutral`. No code path may pass any other value, and `check_run.post`
takes no conclusion argument for a caller to get wrong.

The title states the tier honestly. A verdict produced by the
deterministic fallback says so in the title, not in a footnote further
down the summary. `review.score_one` falls back silently when a reader
call fails, and a fallback verdict rendered as though a model had read
the diff is the one misrepresentation this surface could make on its own.

Deviations render in their own section below the risk verdict, carry the
label `unvalidated`, and never touch `verdicts.score`, `band`, or `raw`
(ADR-0007).

A failure to post is swallowed and logged to stderr. The check run is the
output of a review, not a step in one.

## Rejected

**Keeping the job summary by keeping the workflow alongside the App.**
Two ingest paths, two auth models, two places a verdict can come from,
and a shared token in every adopting repo's settings — which is the thing
the App exists to remove.

**A `success` or `failure` conclusion, however generously thresholded.**
This is what ADR-0003 actually rejected and it stays rejected. A red
check is a merge gate in any repo with required checks turned on, and
Doug's precision does not support gating anything.

**PR comments.** Unchanged from ADR-0003: a wrong comment notifies every
subscriber and it persists.

**Holding the surface until a precision number is published**, which is
what ADR-0003's consequences asked for. That condition was written about
surfaces that can block or notify, and it still binds those. A neutral
check run does neither. Applying the condition here would have meant
shipping the App with no surface at all, which is not a more conservative
outcome, only a less useful one.

## Consequences

- ADR-0003 is superseded and stops being fed to the reader. Left
  `accepted`, it would make Doug's own check-run code read as a deviation
  from Doug's own decisions.
- Never-blocks becomes structural rather than procedural. It used to rest
  on `continue-on-error: true` in a YAML file the adopting repo owned and
  could edit; it now rests on a conclusion value GitHub does not treat as
  a gate.
- An admin can still add the `Doug` check to a branch's required checks.
  Nothing prevents that, and a neutral conclusion satisfies it — the
  check being *present* is all such a rule can demand of us.
- Visibility rises: the check appears in the PR's check list without
  anyone opening a summary. Wrong findings get seen more often too. That
  is the cost of the upgrade, and it is why the tier in the title and the
  `unvalidated` label on deviations are load-bearing rather than
  decoration.
- A Doug outage stays invisible to the repo, which is still correct: no
  check run posted is no signal, not a red one.
```

- [ ] **Step 2: Flip ADR-0003.** Replace `docs/decisions/ADR-0003-ci-surface-is-job-summary-only.md:1-5`, currently:

```markdown
---
title: Doug's CI surface is the job summary, never comments or checks
status: accepted
date: 2026-07-29
---
```

with:

```markdown
---
title: Doug's CI surface is the job summary, never comments or checks
status: superseded
superseded_by: ADR-0010
date: 2026-07-29
---
```

Nothing below the frontmatter changes. The record stays on disk in full — its precision argument is the reason ADR-0010's conclusion is `neutral`, and deleting it would erase why.

- [ ] **Step 3: Correct ADR-0007's surface references.** Same staleness class as the ADR-0008 correction in Task 9, and a worse instance of it: ADR-0007 stays `accepted` (correctly — deviations still never move the score), so it keeps reaching the reader, and it is the record most likely to score relevant on any PR touching `check_run.py` or `deviations`. It currently describes a job summary that Task 9 deletes. Three edits; the Decision, Rejected, and score-isolation content are untouched.

`docs/decisions/ADR-0007-deviation-is-a-separate-stream.md:20-23`, currently:

```markdown
Deviation findings and `intent_alignment` are written to their own
`deviations` table and never contribute to `risk_score` or `band`. They
render as a separate block in the CI job summary, each line carrying the
decision reference so the claim can be checked against the record.
```

becomes:

```markdown
Deviation findings and `intent_alignment` are written to their own
`deviations` table and never contribute to `risk_score` or `band`. They
render as a separate advisory section of the check run (ADR-0010), each
line carrying the decision reference so the claim can be checked against
the record.
```

`:25-27`, currently:

```markdown
The feature ships on from the first merge. There is no staged rollout,
because Doug never blocks and every verdict it emits is already
advisory — a deviation in a job summary cannot hurt anyone.
```

becomes:

```markdown
The feature ships on from the first merge. There is no staged rollout,
because Doug never blocks and every verdict it emits is already
advisory — a deviation on a neutral check run cannot hurt anyone.
```

`:43-44`, the first Consequences bullet, currently:

```markdown
- Two streams to reason about, and a reader of the job summary has to
  understand that one of them does not affect routing.
```

becomes:

```markdown
- Two streams to reason about, and a reader of the check run has to
  understand that one of them does not affect routing.
```

ADR-0007 keeps `status: accepted` and gets no `superseded_by`. Nothing about the decision expired — only the surface it was written against.

- [ ] **Step 4: Update the selection test the flip breaks.** `api/tests/test_intent.py:187-216` (`test_selection_on_dougs_own_records`) is the only test that reads the real `docs/decisions/` tree — `_real_records()` at `:175-184` is called from `:195` and nowhere else. Its line 202 asserts that a PR about posting verdicts as comments selects ADR-0003, which stops being true the moment ADR-0003 leaves the binding set. **This is the test doing its job, not collateral damage:** it exists to pin that the right record surfaces for a change, and the right record just changed.

Replace `api/tests/test_intent.py:202`, currently:

```python
    assert sent("Post Doug verdicts as PR comments", [".github/workflows/x.yml"])[0] == "ADR-0003"
```

with:

```python
    # ADR-0003 used to answer this and is now superseded by ADR-0010. A
    # superseded record must stop steering the reader: left binding, it
    # would have Doug flag its own check-run code as deviating from a rule
    # the team already dropped — the failure intent.BINDING exists to
    # prevent, and the reason the status flip ships with the code.
    comments = sent("Post Doug verdicts as PR comments", [".github/workflows/x.yml"])
    assert comments[0] == "ADR-0010"
    assert "ADR-0003" not in comments
```

The second assertion is the load-bearing one. Asserting only the new id would still pass if the status filter broke and both records came back, so it pins the exclusion directly.

**Verified empirically, not predicted** — running `intent.select` against the post-edit records gives `['ADR-0010', 'ADR-0008']`, with binding relevance ADR-0010 `0.667`, ADR-0008 `0.333`, everything else at or below `0.167`. ADR-0010 wins outright; ADR-0008 rides in under the `RELATIVE_FLOOR = 0.5` cutoff, which is why the assertion is `comments[0] ==` rather than `comments ==`. The same run confirms the test's other four assertions are untouched: the reader-prompt query still leads with ADR-0002, the lema query is still exactly `["ADR-0006"]`, both no-op queries still return `[]`, and both `len(...) <= 3` cases still hold (2 and 3). `len(docs) >= 8` becomes 10.

**This assertion is also stable across Task 9.** Task 9 rewords ADR-0008, which is in this result set — but the rewording leaves its score at `0.333` and the selection identical, so this test does not need touching again. Confirmed by materialising both the post-Task-8 and post-Task-9 record sets and running selection against each.

- [ ] **Step 5: Verify all three records parse and the binding set is right.** Run:

```bash
cd api && uv run python -c "
from pathlib import Path
from doug import intent, intent_providers as ip

d = Path('../docs/decisions')
def rec(name):
    return ip.parse_record(f'docs/decisions/{name}', (d / name).read_text())

new = rec('ADR-0010-surface-is-a-neutral-check-run.md')
old = rec('ADR-0003-ci-surface-is-job-summary-only.md')
dev = rec('ADR-0007-deviation-is-a-separate-stream.md')
assert new is not None, 'ADR-0010 frontmatter does not parse — it would be skipped silently'
assert old is not None, 'ADR-0003 frontmatter no longer parses'
assert dev is not None, 'ADR-0007 frontmatter no longer parses'
assert new.id == 'ADR-0010', new.id
assert new.status == 'accepted', new.status
assert old.status == 'superseded', old.status
# ADR-0007 stays binding: its decision did not expire, only its surface.
assert dev.status == 'accepted', dev.status
# The stale-prose check the parser cannot make: ADR-0007 must no longer
# present the job summary as the live mechanism. All three references go.
# ADR-0010 is deliberately NOT checked — it names the job summary
# throughout its Context and Rejected sections, which is correct and
# required: the record has to say what it replaced and why.
assert 'job summary' not in dev.body.lower(), 'ADR-0007 still describes the job summary'
# The predicate intent.select actually applies (intent.py:111).
binding = sorted(r.id for r in (new, old, dev) if r.status.lower() == intent.BINDING)
assert binding == ['ADR-0007', 'ADR-0010'], binding
print('ok', new.id, new.status, '|', old.id, old.status, '|', dev.id, dev.status)
print('binding:', binding)
"
```

Expected output, exactly:

```
ok ADR-0010 accepted | ADR-0003 superseded | ADR-0007 accepted
binding: ['ADR-0007', 'ADR-0010']
```

The `job summary` assertion is the one that would have caught this class of staleness on its own; ADR-0003 is exempt from it only because it is no longer binding and its whole subject *was* the job summary.

- [ ] **Step 6: Verify nothing else regressed.** `cd api && uv run pytest -q && uv run ruff check .` — expect all pass, no lint findings. This task adds no tests and removes none, so the total must match whatever Task 7 left it at; do not expect an absolute number here, because Tasks 1–7 add several new test modules on top of the 190 cases at HEAD today. Run the affected module explicitly first, since it is the one this task can break — its count *is* stable, as nothing in Tasks 1–7 touches it:

```bash
cd api && uv run pytest tests/test_intent.py -q
```
→ `25 passed` (19 test functions, 25 cases after parametrisation — measured at HEAD, not estimated).

- [ ] **Step 7: Commit**

```bash
git add docs/decisions/ADR-0010-surface-is-a-neutral-check-run.md \
        docs/decisions/ADR-0003-ci-surface-is-job-summary-only.md \
        docs/decisions/ADR-0007-deviation-is-a-separate-stream.md \
        api/tests/test_intent.py
git commit -m "$(cat <<'EOF'
Record the neutral check run as the surface, superseding ADR-0003

The App removes the CI job, so the job summary is not a surface Doug can
choose any more. ADR-0003's real objection was to a pass/fail
conclusion, not to check runs, and `neutral` is the value for that case;
its precision argument survives intact and is why the conclusion is
pinned.

The status flip is mechanism, not bookkeeping: intent.select feeds only
`accepted` records to the reader, so leaving ADR-0003 accepted would
have Doug flag its own check-run code as a deviation from its own
decisions.

ADR-0007's surface sentences move to the check run in the same commit,
for the same reason and without a status change: its decision —
deviations never move the score — is untouched and still binding, but it
described a job summary that no longer exists, and it is the record most
likely to be retrieved on any PR touching check_run.py or deviations.

test_intent.py's selection test moves with them. It asserted that a PR
about posting verdicts as comments selects ADR-0003; the flip makes
ADR-0010 the answer, which is the test working rather than breaking. It
now also asserts ADR-0003 is absent from the result, so a regression in
the status filter fails loudly instead of passing on the new id alone.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task 9: Retire the shared-token review path

**Three corrections to the plan skeleton, found by reading the files — the skeleton's `File Structure` block is incomplete here:**

1. **No `/v1/review` test lives in `api/tests/test_api.py`.** The three that exercise it are in `api/tests/test_store.py:72-101`.
2. **There are two `doug-review.yml` files, not one.** `api/deploy/doug-review.yml` (the template adopters copy) *and* `.github/workflows/doug-review.yml` (this repo's own, installed per ADR-0008). Both POST `/v1/review`. Deleting only the template leaves `drewjst/doug`'s own CI calling a route that no longer exists — on the very PR Task 10 uses to verify the check run.
3. **`api/tests/test_workflow_summary.py` parametrizes all three of its tests over both those paths** (`test_workflow_summary.py:16-19`). The whole module exists to protect the job-summary shell script, which is what this task deletes. The file goes with it.

After this deploys, `lemahq/lema`'s copy of the workflow gets a 404. It never reddens the PR either way — the step carries `continue-on-error: true` — and if lema holds the guarded template version it renders a "Doug: unavailable" summary block. Task 10's cutover checklist removes it from lema.

**Explicitly kept:** `/v1/queue` with its `DOUG_API_TOKEN` gate (interim until step 3 replaces it with WorkOS sessions), `/v1/score`, `/v1/score/read` (which now carries the same gate, for spend rather than for privacy), `/v1/patterns`, and the `doug-review` CLI (`doug/review.py:214-230`, `pyproject.toml:27`) — the CLI drives `githubkit` directly and never touched the endpoint.

**Files:**
- Modify: `api/doug/api.py:46-143` (delete), `:13` (import), `:151`, `:213-215`, `:323` (stale references)
- Delete: `api/deploy/doug-review.yml`
- Delete: `.github/workflows/doug-review.yml`
- Delete: `api/tests/test_workflow_summary.py`
- Modify: `api/tests/test_store.py:72-101` (delete three tests), `:4` (import)
- Modify: `docs/decisions/ADR-0008-doug-reviews-doug.md:19-24`, `:40-43`

**Line numbers above are as of the pre-Task-6 file.** Tasks 6 and 7 both edit `api.py` before this runs, so match on the quoted text, not on the numbers.

**Interfaces:**
- Consumes: nothing new.
- Produces: one ingest path (webhook → queue → worker) and one surface (check run). The service holds no per-request GitHub token from a caller's CI any more; every GitHub call goes through an installation token.

- [ ] **Step 1: Delete the route and its models.** In `api/doug/api.py`, delete lines 46–143 inclusive — from `class ReviewRequest(BaseModel):` through the blank lines after `review_pr`'s closing `)`. That leaves the two blank lines at 44–45 followed directly by `@app.post("/v1/score/read")`.

Then, on the package-import line: **remove the single name `review` from the list and leave every other name exactly as you find it.** Do not replace the whole line from a quoted "currently" text — by the time this task runs, Tasks 6 and 7 have both rewritten it, and the pre-Task-6 version (`from . import __version__, precision, reader, review, store`) no longer exists to match against. The symbol is the anchor, not the line.

For reference, after Tasks 6 and 7 the line reads:

```python
from . import __version__, app_auth, ingest, precision, reader, review, store, worker
```

so the result of this edit is:

```python
from . import __version__, app_auth, ingest, precision, reader, store, worker
```

`review` was used only inside `review_pr` (`api.py:95-97`), so it becomes an `F401` once the route is gone; `app_auth`, `ingest`, and `worker` are all live — the new handler and the lifespan reference them, and dropping any of them is a `NameError` at the first delivery or at startup. If the line you actually find differs from the reference above, still remove only `review`. Step 6's `ruff check` is the arbiter of whether the result is clean.

- [ ] **Step 2: Fix the comments that now point at a deleted route.** A dangling reference to `/v1/review` is worse than none: it describes an auth model no reader can go look at. Three exact replacements.

`api.py:151`, inside `score_pr_read`'s docstring —

```python
    a failure — it returns a verdict, same as /v1/review's score_one path —
```

becomes

```python
    a failure — it returns a verdict, same as the worker's score_one path —
```

`api.py:213-215`, opening `queue`'s docstring —

```python
    """The review queue. Token-gated on the same shared secret as
    /v1/review: these are real PR titles, authors and reader rationales,
    and the service is deployed --allow-unauthenticated.
```

becomes

```python
    """The review queue. Token-gated on the shared DOUG_API_TOKEN: these
    are real PR titles, authors and reader rationales, and the service is
    deployed --allow-unauthenticated. The token is the interim gate — step
    3 replaces it with per-tenant sessions.
```

`api.py:323`, inside `patterns_precision`'s docstring —

```python
    Token-gated on the same shared secret as /v1/review: this is the
```

becomes

```python
    Token-gated on the same DOUG_API_TOKEN as /v1/queue: this is the
```

Task 6 rewrites the webhook handler, so the comment at `api.py:355` ("Fail closed, matching /v1/review and /v1/patterns") may already be gone. If it survives, drop `/v1/review and ` from it.

- [ ] **Step 3: Delete the workflows and their test.**

```bash
git rm api/deploy/doug-review.yml .github/workflows/doug-review.yml api/tests/test_workflow_summary.py
```

- [ ] **Step 4: Delete the endpoint tests.** In `api/tests/test_store.py`, delete these three functions in full:

- `test_review_endpoint_requires_configuration` (`:72-75`)
- `test_review_endpoint_rejects_bad_token` (`:78-84`)
- `test_review_endpoint_scores_and_persists` (`:87-101`)

**Keep `_pr()` (`:66-69`)** — six queue tests still call it. Then fix the import at `:4`, currently:

```python
from doug import reader, review, store
```

to:

```python
from doug import reader, store
```

`review` was used only by `test_review_endpoint_scores_and_persists`'s `monkeypatch.setattr(review, "fetch_pr", ...)`.

None of these three tests has a replacement to write. They tested an auth model that no longer exists; the equivalents under the App are Task 6's signature tests and Task 3's queue tests.

- [ ] **Step 5: Correct ADR-0008, which now describes a workflow that is gone.** It is `status: accepted`, so it is fed to the reader as binding policy — a stale mechanism in it produces confident false findings (`docs/decisions/README.md:8-11`). Its actual decision (development goes through pull requests) is untouched; only the mechanism sentences are wrong. Replace `docs/decisions/ADR-0008-doug-reviews-doug.md:19-24` (the `## Decision` heading is line 19; line 18 is blank), currently:

```markdown
## Decision

Doug's development goes through pull requests. `doug-review.yml` is
installed on this repo with `DOUG_API_URL` and `DOUG_API_TOKEN`, and
`DOUG_INTENT=1` so Doug reads this decisions directory when reviewing
its own changes.
```

with:

```markdown
## Decision

Doug's development goes through pull requests. The `dougs-review` GitHub
App is installed on this repo, and the service runs with `DOUG_INTENT=1`
so Doug reads this decisions directory when reviewing its own changes.
```

and `:40-43` — the *second* Consequences bullet, the one about `reader.py`; lines 44-46 are a different bullet (about revert history) that must not be touched — currently:

```markdown
- A pull request that changes `reader.py` is scored by the *deployed*
  reader, not by itself, so the circularity is mild. Combined with
  `continue-on-error` and job-summary-only output, a broken reader cannot
  block its own fix.
```

with:

```markdown
- A pull request that changes `reader.py` is scored by the *deployed*
  reader, not by itself, so the circularity is mild. Combined with the
  always-`neutral` check-run conclusion (ADR-0010), a broken reader
  cannot block its own fix.
```

- [ ] **Step 6: Verify nothing references the retired path.** Run all four; each expected output is exact.

```bash
grep -rn "v1/review\|ReviewResponse\|ReviewRequest" api/ .github/ web/ \
  --include="*.py" --include="*.yml" --include="*.ts" --include="*.tsx"
```
→ no output, exit status 1.

```bash
ls api/deploy/doug-review.yml .github/workflows/doug-review.yml
```
→ `No such file or directory` for both, exit status non-zero.

```bash
git grep -n "doug-review" -- "*.py" "*.yml" "*.toml"
```
→ exactly four lines, all expected survivors of the CLI, and nothing else:
```
api/doug/review.py:3:`doug-review owner/repo` pulls the open PRs, scores each through the
api/doug/review.py:12:    uv run doug-review grafana/grafana --limit 10
api/doug/review.py:13:    DOUG_READER=1 uv run doug-review drewjst/doug
api/pyproject.toml:27:doug-review = "doug.review:main"
```

**Use `git grep`, not `grep -r .`, for this one.** An unscoped recursive grep from the repo root returns 20 lines today, 10 of them from `.claude/worktrees/reliability-fixes/` — a full second checkout of this repo for the in-flight `fix/reliability-review` branch, which is *not* gitignored (`.gitignore` has no `.claude` entry). Those 10 survive Task 9's deletions and make an exact expected count unattainable. `git grep` searches tracked files in this worktree only, so it sees neither the sibling worktree nor `.venv`. `grep -rn "doug-review" api/ .github/ web/ --include=…` is an equivalent alternative and returns the same four lines.

(`HANDOFF.md`, `docs/superpowers/specs/*`, and the plan itself also mention `doug-review`; they are narrative history and are excluded by the path filters above by design.)

```bash
cd api && uv run pytest -q && uv run ruff check .
```
→ all pass, no lint findings. The suite loses the three endpoint tests and `test_workflow_summary.py`'s three parametrized-by-two cases; every other test is unchanged.

- [ ] **Step 7: Commit**

```bash
git add -A api/doug/api.py api/tests/test_store.py docs/decisions/ADR-0008-doug-reviews-doug.md
git commit -m "$(cat <<'EOF'
Retire the shared-token review path

/v1/review took a caller's GitHub token per request and authenticated
with a token every adopting repo had to hold in its settings. The App
replaces both: installation tokens the service mints itself, no shared
secret in anyone's repo. Keeping the endpoint alongside it would mean
two ingest paths and two places a verdict can come from.

Both copies of doug-review.yml go, not just the template — this repo ran
its own, and it would call a 404 on the first PR after this deploys.
test_workflow_summary.py protected the job-summary shell script, which
no longer exists. ADR-0008 is corrected in the same commit because it is
`accepted` and therefore fed to the reader as policy; describing a
deleted workflow there produces false deviation findings.

/v1/queue keeps its DOUG_API_TOKEN gate until step 3 replaces it, and
the doug-review CLI is untouched — it never used the endpoint.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task 10: Deploy + cutover

**Files:**
- Modify: `api/deploy/gcp.sh:66-76` (setup: dedicated SA + secret bindings), `:86-93` (deploy: service account, secrets, env, CPU)
- Delete (operator, Step 4 — untracked and gitignored, so it is not part of any commit): `api/.backtest-cache/llm-probe/api-key`

**Interfaces:**
- Consumes: `DOUG_GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY` as read by `app_auth.enabled()` (Task 1); `GITHUB_WEBHOOK_SECRET` as required by the lifespan (Task 6); `/v1/score/read`, kept by Task 9, as the post-deploy credential probe — and therefore `DOUG_API_TOKEN`, which now gates it.
- Produces: a Cloud Run revision that can mint installation tokens and finish background work; a rotated `doug-anthropic-key`; an operator-run IAM prerequisite and an operator-run cutover.

**Read before starting — the gap this task closes is already open.** `DOUG_GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY` were set on prod out-of-band via `gcloud run services update` on 2026-07-31, and `deploy()` uses `--set-env-vars` / `--set-secrets`, which **replace** their whole blocks. Every push from Tasks 1–9 therefore deploys a revision with the App credentials wiped. That is survivable and is not a reason to reorder the plan: `app_auth.enabled()` returns `False` without them, so the App simply stays dormant — webhooks verify and enqueue, no tokens are minted, no paid reads happen from a half-built pipeline. Task 7's startup reconcile then picks up every PR missed during the gap on the first revision that has the credentials, which is the one this task ships. What is *not* survivable is landing this task and assuming prod was fine in between: check the logs at Step 6 rather than assuming.

- [ ] **Step 1: Give the service its own identity in `setup()`.** Replace `api/deploy/gcp.sh:66-76`, currently:

```bash
  SA=$(gcloud iam service-accounts list --project "$PROJECT" \
    --filter="displayName:'Default compute service account'" --format="value(email)")
  # NOTE for the GitHub App work: this binds secrets to the *default*
  # compute service account, so every workload in the project can read
  # them. Tolerable for these four; not tolerable for an App private key,
  # which needs a dedicated service account.
  for s in doug-database-url doug-api-token doug-anthropic-key doug-webhook-secret; do
    gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
      --member="serviceAccount:$SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null 2>&1 || true
  done
```

with:

```bash
  # A dedicated runtime identity, which is what the NOTE this replaces
  # asked for: the App private key mints installation tokens for every
  # repo Doug is installed on, and the default compute service account is
  # readable by every workload in the project.
  gcloud iam service-accounts create doug-api-sa \
    --display-name "doug-api runtime" --project "$PROJECT" 2>/dev/null \
    || echo "doug-api-sa exists; leaving it"
  SA="doug-api-sa@$PROJECT.iam.gserviceaccount.com"
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA" --role=roles/cloudsql.client >/dev/null 2>&1 || true
  for s in doug-database-url doug-api-token doug-anthropic-key \
           doug-webhook-secret doug-github-app-key; do
    gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
      --member="serviceAccount:$SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null 2>&1 || true
  done
  # The default compute SA keeps its existing bindings deliberately:
  # doug-web still runs as it and reads doug-api-token. Revoking them here
  # would break the dashboard on the next web deploy, not on this command,
  # which is the worst possible moment to find out.
```

`roles/cloudsql.client` is not optional — the default compute SA had it by inheritance and a fresh SA does not, so without it the ledger connection fails on the first request.

- [ ] **Step 2: Point `deploy()` at that identity and give it the App's credentials.** Replace `api/deploy/gcp.sh:86-93`, currently:

```bash
  gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --add-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,DOUG_API_TOKEN=doug-api-token:latest,ANTHROPIC_API_KEY=doug-anthropic-key:latest,GITHUB_WEBHOOK_SECRET=doug-webhook-secret:latest" \
    --set-env-vars "DOUG_READER=1,DOUG_INTENT=1" \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 300
```

with:

```bash
  # --no-cpu-throttling: the drain runs *after* the response is written
  # (BackgroundTasks) and again in the startup reconcile thread. Under
  # request-based throttling Cloud Run freezes the instance's CPU the
  # moment the response goes out, so a claimed job would sit half-run,
  # holding its row in 'running', until some unrelated request thawed the
  # instance. The queue would look alive and be stalled.
  gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --service-account "doug-api-sa@$PROJECT.iam.gserviceaccount.com" \
    --add-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,DOUG_API_TOKEN=doug-api-token:latest,ANTHROPIC_API_KEY=doug-anthropic-key:latest,GITHUB_WEBHOOK_SECRET=doug-webhook-secret:latest,GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest" \
    --set-env-vars "DOUG_READER=1,DOUG_INTENT=1,DOUG_GITHUB_APP_ID=4450932" \
    --no-cpu-throttling \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 300
```

- [ ] **Step 3: Smoke-test the script without running it.**

```bash
bash -n api/deploy/gcp.sh
```
→ no output, exit 0.

```bash
gcloud run deploy --help | grep -c "no-cpu-throttling"
```
→ a count of `1` or more, confirming the installed gcloud accepts the flag.

```bash
grep -c "doug-github-app-key" api/deploy/gcp.sh
```
→ `2` (the `setup()` binding loop and the `deploy()` `--set-secrets`).

- [ ] **Step 4: Pre-deploy IAM and key rotation — a human runs this once, BEFORE merging this task.** CI cannot: `deploy()` has no IAM rights by ADR-0009, and it will fail with an `iam.serviceaccounts.actAs` denial until the `actAs` binding below exists.

This block also carries the other half of the spec's key-custody item — the **App private key custody** bullet under "Open questions" in `specs/2026-07-30-github-app-tenancy-dashboard-design.md`, at `:254-259` as of this writing (the spec has uncommitted edits in flight above that point, so find it by heading rather than by line) — which the `gcp.sh` edits above do not address:

> `gcp.sh:66-72` grants `secretAccessor` to the default compute service account, so every workload in `doug-prod0` could read the key — a dedicated service account is required. The un-rotated key at `repo/api/.backtest-cache/llm-probe/api-key` should be rotated first.

Steps 1–2 did the dedicated service account. The rotation is the part that makes it worth doing: `api/.backtest-cache/llm-probe/api-key` exists in the working tree (108 bytes, dated 2026-07-29). It is untracked and covered by `.gitignore:25` (`.backtest-cache/`), so this is a working-tree exposure rather than a committed one — but scoping `doug-anthropic-key` down to a new service account protects nothing if the value it holds is one that has been sitting in a plaintext file. Rotate first, then narrow access to the credential that is actually current.

**Order the rotation so there is no outage.** Anthropic lets a new key exist before the old one is revoked, so: create the new key → add it as a `doug-anthropic-key` version → deploy (Step 5) → verify the reader answers (Step 6) → *only then* revoke the old key (cutover Step 8). Reversing that — revoking first — breaks the live reader for the whole interval between rotation and deploy, because the running revision holds the old secret version until it is replaced.

````
⚠️ NEVER run `gcp.sh setup` against doug-prod0. It regenerates DB_PASS with
   `openssl rand` and calls `gcloud sql users set-password` unconditionally
   (gcp.sh:52-56), then adds a new doug-database-url version. The running
   revision keeps its old, now-invalid password until the next deploy — so
   the ledger breaks silently, at a moment unconnected to the command that
   broke it. Run the commands below individually instead. The gcp.sh edits
   in Steps 1-2 exist so a future clean project gets this right, not so
   this project re-runs setup.

```bash
PROJECT=doug-prod0
SA="doug-api-sa@$PROJECT.iam.gserviceaccount.com"

# 0. Rotate the Anthropic key (spec, "App private key custody"). Create a NEW key in the
#    Anthropic console — console.anthropic.com -> API keys -> Create key —
#    and do NOT revoke the old one yet; that happens at cutover step 8,
#    after the deploy is verified.
#
#    Write it to a file rather than passing it inline: --data-file=- from a
#    heredoc or an echo puts the key in shell history, which is the exact
#    exposure being cleaned up here. gcp.sh:78-79 already prescribes the
#    file form for this secret.
#
#    printf '%s', never echo: doug-webhook-secret v1 carries a trailing
#    newline from exactly this mistake and has to be disabled at cutover.
umask 077
printf '%s' 'sk-ant-...' > /tmp/anthropic.key   # paste the new key here
gcloud secrets versions add doug-anthropic-key \
  --data-file=/tmp/anthropic.key --project "$PROJECT"
rm -P /tmp/anthropic.key

#    Now delete the plaintext copy that started this. It is untracked and
#    gitignored, so removing it needs no commit.
rm -P /Users/andrew/Projects/doughq/repo/api/.backtest-cache/llm-probe/api-key

#    Confirm the new version is live and the file is gone.
gcloud secrets versions list doug-anthropic-key --project "$PROJECT" --limit 3
test ! -e /Users/andrew/Projects/doughq/repo/api/.backtest-cache/llm-probe/api-key \
  && echo "plaintext key removed"

# 1. Prerequisite: the App private key must already be in Secret Manager.
#    Create it from the .pem downloaded from the App settings page — as a
#    file, for the same reason as above:
#      gcloud secrets create doug-github-app-key \
#        --data-file=/path/to/dougs-review.private-key.pem --project doug-prod0
gcloud secrets describe doug-github-app-key --project "$PROJECT" >/dev/null

# 2. The runtime identity.
gcloud iam service-accounts create doug-api-sa \
  --display-name "doug-api runtime" --project "$PROJECT"

# 3. Secret access — all five, including the two the App needs.
for s in doug-database-url doug-api-token doug-anthropic-key \
         doug-webhook-secret doug-github-app-key; do
  gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
    --member="serviceAccount:$SA" \
    --role=roles/secretmanager.secretAccessor
done

# 4. Cloud SQL, which the default compute SA had by inheritance and this
#    one does not. Without it every ledger write fails on the first request.
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$SA" --role=roles/cloudsql.client

# 5. Let the CI deployer run the service as this SA. Without this the next
#    merge to main fails with an iam.serviceaccounts.actAs denial.
DEPLOY_SA=$(gh variable get GCP_DEPLOY_SA --repo drewjst/doug)
echo "deployer: $DEPLOY_SA"
gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
  --member="serviceAccount:$DEPLOY_SA" \
  --role=roles/iam.serviceAccountUser

# 6. Verify before merging. Both must print a line containing doug-api-sa.
gcloud secrets get-iam-policy doug-github-app-key --project "$PROJECT" \
  --flatten="bindings[].members" --format="value(bindings.members)" | grep doug-api-sa
gcloud iam service-accounts get-iam-policy "$SA" --project "$PROJECT" \
  --flatten="bindings[].members" --format="value(bindings.members)" | grep "$DEPLOY_SA"
```
````

- [ ] **Step 5: Commit and let CI deploy.**

```bash
git add api/deploy/gcp.sh
git commit -m "$(cat <<'EOF'
Run doug-api as a dedicated SA with the App credentials

The App private key can mint installation tokens for every repo Doug is
installed on, and secrets were bound to the default compute service
account, which every workload in the project can read. A dedicated
doug-api-sa scopes that down.

--set-env-vars and --set-secrets replace their whole blocks, so the App
id and key set out-of-band on 2026-07-31 were wiped by every deploy
since; pinning them here is what makes the App actually work in prod.
--no-cpu-throttling because the drain runs after the response is
written, and request-based throttling would freeze a claimed job
mid-flight.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
git push
```

Watch it land: `gh run watch --repo drewjst/doug`. The deploy job ends with the `openapi.json` smoke test, which must return 200 — a lifespan that raises on a missing `GITHUB_WEBHOOK_SECRET` shows up here as a failed revision, not as a silent no-op.

- [ ] **Step 6: Confirm the revision came up with the App enabled.**

```bash
gcloud run services describe doug-api --project doug-prod0 --region us-central1 \
  --format="yaml(spec.template.spec.serviceAccountName, spec.template.spec.containers[0].env)"
```
Expect `serviceAccountName: doug-api-sa@doug-prod0.iam.gserviceaccount.com`, `DOUG_GITHUB_APP_ID: '4450932'`, and secret refs for both `GITHUB_WEBHOOK_SECRET` and `GITHUB_APP_PRIVATE_KEY`.

```bash
gcloud run services logs read doug-api --project doug-prod0 --region us-central1 --limit 50
```
Expect a `doug: reconcile enqueued N job(s)` line from the startup thread. `N` counts every open PR missed while the App credentials were absent. If the log reader is unavailable in your gcloud, use:
`gcloud logging read 'resource.labels.service_name="doug-api"' --limit 50 --freshness=1h --project doug-prod0`.

Then confirm the **rotated Anthropic key** actually works on this revision, before the old one is revoked. `/v1/score/read` survives Task 9, and it falls back loudly rather than erroring, which makes it the cheapest possible credential probe. It is **token-gated on `DOUG_API_TOKEN`** — every call buys a model read and doug-api is `--allow-unauthenticated`, so the probe reads back the same secret `deploy()` binds:

```bash
URL=$(gcloud run services describe doug-api --project doug-prod0 \
  --region us-central1 --format='value(status.url)')
TOKEN=$(gcloud secrets versions access latest --secret=doug-api-token \
  --project doug-prod0)
curl -sS -X POST "$URL/v1/score/read" -H 'content-type: application/json' \
  -H "x-doug-token: $TOKEN" \
  -d '{"pr":{"number":1,"title":"probe","author":"drewjst","files":["a.py"]},
       "diff":"--- a/a.py\n+++ b/a.py\n@@\n+x = 1\n"}' \
  | python3 -c 'import json,sys; v=json.load(sys.stdin); \
sys.exit(f"not a verdict (auth or config): {v}") if "reasons" not in v else None; \
rules=[r["rule"] for r in v["reasons"]]; print(v["threshold"], rules); \
sys.exit(1 if "reader-unavailable" in rules else 0)'
```

Exit 0 with `threshold` printed as `0.3` means the new key is live: the reader bands at 0.3 and the deterministic scorer at 0.62, so the threshold is the tier signal and — unlike a `reader:*` rule — it does not depend on the probe diff producing findings. This one produces none, so do **not** read an empty rule list as failure.

A `reader-unavailable` rule (exit 1) means `ANTHROPIC_API_KEY` is wrong on this revision — stop, fix the secret version, and do **not** revoke the old key. `not a verdict (auth or config)` means the request never reached the reader: a 401 is a wrong or missing `DOUG_API_TOKEN`, a 503 is that secret unbound on the revision. This costs one small model call.

- [ ] **Step 7: Cutover — operator steps, run in this order.**

````
Order matters: install on lema and confirm check runs appear BEFORE
removing lema's workflow. Reversed, lema has no reviewer at all in the
window between the two, and the workflow is the only thing that would
tell anyone.

```
1. Make the App installable outside this account.
   GitHub → Settings → Developer settings → GitHub Apps → dougs-review.
   Set "Where can this GitHub App be installed?" to "Any account" and
   save. On some accounts this is presented as a "Make public" button on
   the app's Advanced tab instead — same setting, either path.

2. Install it on lemahq/lema, repository-scoped (not "All repositories").
   No manual reconcile is needed: the installation.created webhook sets
   the repo list and reconciles that installation, so lema's open PRs are
   queued within seconds of the install.

3. Verify on lema before touching anything there. Open any lema PR and
   confirm a "Doug" check run appears with conclusion Neutral. If it does
   not, STOP and read the logs — steps 4 and 5 are the irreversible ones.

4. In the lemahq/lema repo (outside this repository), delete
   .github/workflows/doug-review.yml and remove the DOUG_API_URL and
   DOUG_API_TOKEN repository secrets. The workflow is calling a route
   that returns 404 as of Task 9; it cannot redden a PR
   (continue-on-error: true) but it is noise.

5. Disable the superseded webhook secret version. v1 carries a trailing
   newline and was replaced by the stripped v2; nothing should validate
   against it any more.
     gcloud secrets versions disable 1 --secret=doug-webhook-secret \
       --project doug-prod0
   Reversible with `versions enable 1` if deliveries start failing
   verification — check the App's Advanced → Recent Deliveries tab for
   401s before assuming it is unrelated.

6. Verify on this repo. Open a throwaway PR on drewjst/doug:
     git checkout -b cutover-check && git commit --allow-empty -m "check run smoke test"
     git push -u origin cutover-check && gh pr create --fill
   Expect within a minute:
     - a check run named "Doug", conclusion Neutral, on the PR's checks tab
     - its title naming the tier honestly ("reader" vs the deterministic
       fallback) — a fallback verdict rendered as a reader verdict is the
       one thing ADR-0010 says this surface must never do
     - no job summary anywhere: doug-review.yml is gone from this repo
   Then close and delete the branch.

7. Confirm the ingest path end to end in the logs:
     gcloud run services logs read doug-api --project doug-prod0 \
       --region us-central1 --limit 100
   Expect a POST /webhooks/github 202 for the pull_request delivery, and
   a job completing after it. A 202 with no job completion means the
   drain is not running — check --no-cpu-throttling actually landed on
   the serving revision (Step 6).

8. Close the key rotation. Only now, with the reader verified working on
   the new key at Step 6 and a real review completed at step 7, revoke
   the OLD Anthropic key in the console (console.anthropic.com -> API
   keys -> the pre-rotation key -> Delete). Doing this earlier would
   have broken the live reader for the interval between rotation and
   deploy; doing it never leaves a key that spent time in a plaintext
   file valid indefinitely.
   Then disable the superseded secret version so it cannot be rolled
   back to by accident — check the list first and disable the one BELOW
   the newest:
     gcloud secrets versions list doug-anthropic-key --project doug-prod0
     gcloud secrets versions disable <previous-version> \
       --secret=doug-anthropic-key --project doug-prod0
```
````

- [ ] **Step 8: Commit** — expect nothing to commit. The `gcp.sh` change went in at Step 5, and the only file Steps 4–7 touch in this repo is `api/.backtest-cache/llm-probe/api-key`, which is untracked and gitignored, so `git status --porcelain` stays empty. Confirm that rather than assuming it:

```bash
git status --porcelain
```
→ no output. If the cutover turned up a correction to the script, commit it now:

```bash
git add api/deploy/gcp.sh
git commit -m "$(cat <<'EOF'
Fix <what the cutover found> in the deploy script

<why it mattered — what the cutover observed that the script implied
would not happen>

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
git push
```
