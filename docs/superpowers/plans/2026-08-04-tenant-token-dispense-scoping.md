# Tenant Token Dispense + Scoped Reads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mint per-installation API tokens verified against GitHub, and scope `/v1/queue` to the minting installation so no tenant can read another tenant's rows.

**Architecture:** A new `doug/tenancy.py` owns mint / resolve / verify_admin with no FastAPI import, so the future MCP garden service (a separate Cloud Run service on the same image) can verify a token without importing the web app. `api.py` gains one endpoint and a shared operator-gate helper. `DOUG_API_TOKEN` survives unchanged as an unscoped operator credential; dispensed tokens are a second, narrower class that reaches `/v1/queue` only.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy Core, githubkit, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-08-04-tenant-token-dispense-scoping-design.md`
**Branch:** `tenant-token-dispense` (already exists, holds the design doc at `ec4a340`)

## Global Constraints

- **No migration.** `installations.token_hash` (`store.py:186`) already exists — it and the `installations` table shipped in the same commit (`6a1a213`), so `create_all()` built the column. Do not add a migration; do not add the column to `MIGRATIONS`.
- **Never `git add -A` at this repo's root.** `.claude/worktrees/` holds other sessions' untracked files. Stage explicit paths only, exactly as written in each Commit step.
- **404, never 403.** Cross-tenant repo, tenant token on an operator-only endpoint, Doug-not-installed, PAT-lacks-admin — all 404. An absent or unresolvable token is 401. Never return an empty list where 404 is meant: an empty list is indistinguishable from "no reviews yet".
- **Token format:** `doug_` + `secrets.token_urlsafe(32)`. The prefix is load-bearing for leaked-secret sweeps.
- **The plaintext token is returned exactly once and never logged.** Only `sha256(token)` is persisted.
- **Baseline:** 539 tests pass on `main` before this work (`make test`). Each task states its own expected total; a task's run must hit that number and must never fall below the previous task's. Tasks 1–5 add tests and so go up; **Task 6 is documentation-only and stays at 572** — an unchanged count there is correct, not a missing test.
- **Lint:** `cd api && uv run ruff check .` must be clean before every commit.
- All commands below run from the repo root unless the command itself contains `cd api`.

---

### Task 1: `doug/tenancy.py` — mint and resolve

The storage half of the token: generate, hash, persist, look back up. No GitHub calls in this task.

**Files:**
- Create: `api/doug/tenancy.py`
- Test: `api/tests/test_tenancy.py`

**Interfaces:**
- Consumes: `store._get_engine()`, `store.installations` (table), `store.upsert_installation(installation_id, account_login, account_type, state)`
- Produces:
  - `tenancy.TOKEN_PREFIX: str` = `"doug_"`
  - `tenancy.mint(installation_id: int) -> str | None` — returns plaintext once; `None` when storage is disabled or no `installations` row exists for that id
  - `tenancy.resolve(token: str) -> int | None` — returns `installation_id`, or `None` for empty / malformed / unknown / storage-disabled

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_tenancy.py`:

```python
import pytest

from doug import store, tenancy


def _db(tmp_path, monkeypatch):
    """Same shape as tests/test_store.py::_db — a throwaway sqlite ledger."""
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _install(installation_id: int = 150424894) -> None:
    store.upsert_installation(installation_id, "drewjst", "User", "active")


def test_mint_returns_a_prefixed_token_that_resolves(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _install()
    token = tenancy.mint(150424894)
    assert token is not None
    assert token.startswith(tenancy.TOKEN_PREFIX)
    assert tenancy.resolve(token) == 150424894


def test_plaintext_token_is_never_stored(tmp_path, monkeypatch):
    """The token is unrecoverable by construction, not by policy. If this
    fails, a ledger dump hands over every tenant's credential."""
    _db(tmp_path, monkeypatch)
    _install()
    token = tenancy.mint(150424894)
    engine = store._get_engine()
    with engine.connect() as conn:
        stored = conn.execute(
            store.installations.select().with_only_columns(store.installations.c.token_hash)
        ).scalar_one()
    assert stored != token
    assert token not in stored


def test_minting_again_invalidates_the_previous_token(tmp_path, monkeypatch):
    """Rotation is the whole recovery story for a lost token — there is no
    other path, so the old one has to die immediately."""
    _db(tmp_path, monkeypatch)
    _install()
    first = tenancy.mint(150424894)
    second = tenancy.mint(150424894)
    assert first != second
    assert tenancy.resolve(first) is None
    assert tenancy.resolve(second) == 150424894


def test_revocation_by_nulling_the_hash(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _install()
    token = tenancy.mint(150424894)
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.installations.update().values(token_hash=None))
    assert tenancy.resolve(token) is None


def test_resolve_rejects_junk_without_touching_storage(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _install()
    tenancy.mint(150424894)
    assert tenancy.resolve("") is None
    assert tenancy.resolve("not-a-doug-token") is None
    assert tenancy.resolve(tenancy.TOKEN_PREFIX + "wrong") is None


def test_mint_refuses_an_installation_that_does_not_exist(tmp_path, monkeypatch):
    """No row means Doug was never installed there. Minting anyway would
    create a token that resolves to an id with no tenancy behind it."""
    _db(tmp_path, monkeypatch)
    assert tenancy.mint(999) is None


def test_disabled_storage_mints_and_resolves_nothing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert tenancy.mint(150424894) is None
    assert tenancy.resolve("doug_anything") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_tenancy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'doug.tenancy'`

- [ ] **Step 3: Write the implementation**

Create `api/doug/tenancy.py`:

```python
"""Per-installation API tokens: mint, resolve, and the GitHub proof behind them.

Deliberately free of any FastAPI import. The v1.5 MCP garden is a separate
Cloud Run service running this same image (design-lock.md:31), and
design-lock.md:65 records that the token mint survived the tenant-page cut
"because its consumers are the API and later MCP" — so verification has to be
importable without dragging in the web app.

Only sha256(token) is ever persisted. The plaintext is returned once by mint()
and is unrecoverable afterwards, which makes "we cannot show you that token
again" a property of the schema rather than a policy someone can relax.
"""

import hashlib
import secrets

from sqlalchemy import select, update

from . import store

# Greppable in a leaked-secret sweep, and the shape GitHub's secret scanning
# would key on if Doug ever registers a pattern.
TOKEN_PREFIX = "doug_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint(installation_id: int) -> str | None:
    """Issue a token for an existing installation. Returns the plaintext
    exactly once, or None when storage is off or the installation is unknown.

    An UPDATE rather than an upsert on purpose: a token for an installation
    with no row would resolve to an id that no tenancy backs, so the absence
    of a row is a refusal, not something to paper over.
    """
    engine = store._get_engine()
    if engine is None:
        return None
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    with engine.begin() as conn:
        result = conn.execute(
            update(store.installations)
            .where(store.installations.c.installation_id == installation_id)
            .values(token_hash=_hash(token))
        )
    if result.rowcount == 0:
        return None
    return token


def resolve(token: str) -> int | None:
    """Map a presented token to its installation id, or None.

    The prefix check short-circuits before any query, so the operator token
    and ordinary junk never reach storage. Lookup is by digest: the compared
    value is already a hash, so an equality match leaks nothing a timing
    attack could use — an attacker would need a preimage, not a clock.

    token_hash is NULL until an installation mints, and SQL equality never
    matches NULL, so un-minted installations are unreachable by design.
    """
    if not token.startswith(TOKEN_PREFIX):
        return None
    engine = store._get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        return conn.execute(
            select(store.installations.c.installation_id).where(
                store.installations.c.token_hash == _hash(token)
            )
        ).scalar_one_or_none()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_tenancy.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Run the full suite and lint**

Run: `make test && cd api && uv run ruff check .`
Expected: 546 passed (539 + 7); ruff reports `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add api/doug/tenancy.py api/tests/test_tenancy.py
git commit -m "Mint and resolve per-installation tokens, hash-only

Only sha256(token) is persisted, so 'we cannot show you that token again'
is a property of the schema rather than a policy. Minting again overwrites
the hash, which makes rotation and lost-token recovery the same one-column
write. No migration: installations and token_hash shipped together in
6a1a213, so create_all built the column."
```

---

### Task 2: `tenancy.verify_admin` — the PAT-first two-call proof

Prove the caller administers a repo Doug is installed on. **The call order is the point of this task**, not an implementation detail.

**Files:**
- Modify: `api/doug/tenancy.py` (append)
- Test: `api/tests/test_tenancy.py` (append)

**Interfaces:**
- Consumes: `app_auth.enabled()`, `app_auth.app_client()` (returns a `githubkit.GitHub`)
- Produces: `tenancy.verify_admin(pat: str, owner: str, repo: str) -> int | None` — returns `installation_id` when both checks pass, `None` otherwise

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_tenancy.py`:

```python
from types import SimpleNamespace

from doug import app_auth


class _Boom(Exception):
    pass


def _caller(admin: bool):
    """A githubkit-shaped stub for the caller's PAT: GET /repos/{o}/{r}."""

    def _get(owner, repo):
        return SimpleNamespace(parsed_data=SimpleNamespace(permissions=SimpleNamespace(admin=admin)))

    return SimpleNamespace(rest=SimpleNamespace(repos=SimpleNamespace(get=_get)))


def _app(installation_id=150424894, calls=None):
    """A stub for the app JWT: GET /repos/{o}/{r}/installation."""

    def _get_repo_installation(owner, repo):
        if calls is not None:
            calls.append((owner, repo))
        if installation_id is None:
            raise _Boom("not installed")
        return SimpleNamespace(parsed_data=SimpleNamespace(id=installation_id))

    return SimpleNamespace(
        rest=SimpleNamespace(
            apps=SimpleNamespace(get_repo_installation=_get_repo_installation)
        )
    )


def test_verify_admin_returns_the_installation_id(monkeypatch):
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _caller(admin=True))
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app())
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") == 150424894


def test_non_admin_pat_never_spends_dougs_github_quota(monkeypatch):
    """The ordering test, and the reason this function exists in this shape.

    GitHub's REST quota is 5,000/hr and shared across every Doug session; it
    was exhausted twice on 2026-08-02. The app-JWT call spends DOUG'S quota,
    the PAT call spends the CALLER'S. This endpoint is public, so if the app
    call ran first an anonymous caller would have a loop that drains the
    quota the review path needs to mint installation tokens. Assert on the
    empty call list, not just the return value — a refactor that reorders
    the two calls still returns None here and would slip through.
    """
    app_calls = []
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _caller(admin=False))
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app(calls=app_calls))
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None
    assert app_calls == []


def test_unreadable_repo_never_spends_dougs_quota(monkeypatch):
    """A PAT that cannot see the repo at all takes the same early exit."""
    app_calls = []

    def _explode(pat):
        raise _Boom("404")

    monkeypatch.setattr(tenancy, "_caller_client", _explode)
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app(calls=app_calls))
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None
    assert app_calls == []


def test_admin_but_doug_not_installed(monkeypatch):
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _caller(admin=True))
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app(installation_id=None))
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None


def test_missing_permissions_block_is_not_admin(monkeypatch):
    """githubkit models an absent field as a sentinel, not None. Anything
    that is not exactly True is 'not admin' — the safe direction to be
    wrong in is refuse, the same choice worker._skip_reason makes for forks."""
    caller = SimpleNamespace(
        rest=SimpleNamespace(
            repos=SimpleNamespace(
                get=lambda owner, repo: SimpleNamespace(parsed_data=SimpleNamespace())
            )
        )
    )
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: caller)
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(app_auth, "app_client", lambda: _app())
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None


def test_app_path_disabled_verifies_nothing(monkeypatch):
    monkeypatch.setattr(tenancy, "_caller_client", lambda pat: _caller(admin=True))
    monkeypatch.setattr(app_auth, "enabled", lambda: False)
    assert tenancy.verify_admin("ghp_x", "drewjst", "doug") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_tenancy.py -v -k verify_admin or test_non_admin or test_unreadable or test_missing_permissions or test_app_path`
Expected: FAIL — `AttributeError: module 'doug.tenancy' has no attribute '_caller_client'`

- [ ] **Step 3: Write the implementation**

Append to `api/doug/tenancy.py` (and add `from githubkit import GitHub` plus `from . import app_auth, store` to the imports at the top, replacing the existing `from . import store`):

```python
def _caller_client(pat: str) -> GitHub:
    """A client authenticated as the caller, not as Doug. Its own name so
    tests can replace it without patching githubkit globally."""
    return GitHub(pat)


def verify_admin(pat: str, owner: str, repo: str) -> int | None:
    """Prove the caller administers a repo Doug is installed on.

    THE CALL ORDER IS LOAD-BEARING. Two GitHub calls happen here and they
    spend different quotas: the PAT call spends the CALLER'S, the app-JWT
    call spends DOUG'S — the shared 5,000/hr pool that the review path needs
    to mint installation tokens, and that was exhausted twice on 2026-08-02.
    Dispense is a public endpoint on an --allow-unauthenticated service, so
    doing the app call first would hand an anonymous caller a loop that
    drains Doug's quota. Checking the caller's own credential first means an
    attacker burns their own budget and reaches nothing of ours.

    Returns None for every failure, deliberately without distinguishing
    them: the endpoint renders all of these as 404, so a caller cannot use
    the difference to discover whether a private repo exists.
    """
    # 1. The caller's own credential and the caller's own quota.
    try:
        seen = _caller_client(pat).rest.repos.get(owner=owner, repo=repo)
    except Exception:  # noqa: BLE001 — any failure is "cannot prove it"
        return None
    permissions = getattr(seen.parsed_data, "permissions", None)
    # Only an explicit True proceeds. githubkit models an absent field as a
    # sentinel rather than None, so a truthiness test would admit it.
    if getattr(permissions, "admin", False) is not True:
        return None

    # 2. Doug's identity, and only now Doug's quota.
    if not app_auth.enabled():
        return None
    try:
        found = app_auth.app_client().rest.apps.get_repo_installation(owner=owner, repo=repo)
    except Exception:  # noqa: BLE001 — 404 here means Doug is not installed
        return None
    installation_id = getattr(found.parsed_data, "id", None)
    return installation_id if isinstance(installation_id, int) else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_tenancy.py -v`
Expected: PASS, 13 passed

- [ ] **Step 5: Run the full suite and lint**

Run: `make test && cd api && uv run ruff check .`
Expected: 552 passed; ruff clean

- [ ] **Step 6: Commit**

```bash
git add api/doug/tenancy.py api/tests/test_tenancy.py
git commit -m "Verify installation ownership PAT-first, app JWT second

The order is the feature. The app-JWT call spends Doug's shared 5,000/hr
REST quota — exhausted twice on 2026-08-02 — and dispense is public on an
--allow-unauthenticated service, so checking the caller's own credential
first denies an anonymous caller a drain loop. A test asserts the app call
list is empty on a failed PAT check, because a reordering refactor still
returns None and would otherwise pass."
```

---

### Task 3: `POST /v1/installations/token`

**Files:**
- Modify: `api/doug/api.py` (add `tenancy` to the `from . import ...` line at `api.py:18`; add the endpoint after the `/v1/queue` handler)
- Test: `api/tests/test_api.py` (append)

**Interfaces:**
- Consumes: `tenancy.verify_admin`, `tenancy.mint`, `store.enabled()`
- Produces: `POST /v1/installations/token` → `{"token": str, "installation_id": int, "repo": str}`

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_api.py`:

```python
def _tenancy_ok(monkeypatch, installation_id=150424894):
    monkeypatch.setattr(api.tenancy, "verify_admin", lambda pat, owner, repo: installation_id)


def test_dispense_returns_a_token_once(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    store.upsert_installation(150424894, "drewjst", "User", "active")
    _tenancy_ok(monkeypatch)
    r = client.post(
        "/v1/installations/token",
        json={"repo": "drewjst/doug"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["installation_id"] == 150424894
    assert body["repo"] == "drewjst/doug"
    assert body["token"].startswith("doug_")
    assert api.tenancy.resolve(body["token"]) == 150424894


def test_dispense_without_a_github_token_is_401(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    r = client.post("/v1/installations/token", json={"repo": "drewjst/doug"})
    assert r.status_code == 401


def test_dispense_hides_every_verification_failure_behind_404(tmp_path, monkeypatch):
    """403 would confirm the repo exists. So would a distinct message for
    'not installed' versus 'not an admin'. One shape for all of them."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    monkeypatch.setattr(api.tenancy, "verify_admin", lambda pat, owner, repo: None)
    r = client.post(
        "/v1/installations/token",
        json={"repo": "someone/private"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 404


def test_dispense_404s_a_malformed_repo_without_calling_github(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    calls = []

    def _spy(pat, owner, repo):
        calls.append((owner, repo))
        return 150424894

    monkeypatch.setattr(api.tenancy, "verify_admin", _spy)
    for bad in ("doug", "/doug", "drewjst/", ""):
        r = client.post(
            "/v1/installations/token",
            json={"repo": bad},
            headers={"X-GitHub-Token": "ghp_x"},
        )
        assert r.status_code == 404, bad
    assert calls == []


def test_dispense_404s_when_verification_passes_but_no_installation_row(tmp_path, monkeypatch):
    """verify_admin says GitHub knows about the installation but the ledger
    does not — mint refuses, and so must the endpoint."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    _tenancy_ok(monkeypatch, installation_id=999)
    r = client.post(
        "/v1/installations/token",
        json={"repo": "drewjst/doug"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 404


def test_dispense_without_a_ledger_is_503(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = client.post(
        "/v1/installations/token",
        json={"repo": "drewjst/doug"},
        headers={"X-GitHub-Token": "ghp_x"},
    )
    assert r.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_api.py -v -k dispense`
Expected: FAIL — `AttributeError: module 'doug.api' has no attribute 'tenancy'`

- [ ] **Step 3: Write the implementation**

In `api/doug/api.py`, change line 18 from:

```python
from . import __version__, app_auth, ingest, precision, reader, review, store, worker
```

to:

```python
from . import __version__, app_auth, ingest, precision, reader, review, store, tenancy, worker
```

Then add, immediately after the `/v1/queue` handler ends and before `@app.get("/v1/patterns")`:

```python
class TokenRequest(BaseModel):
    repo: str


class TokenResponse(BaseModel):
    token: str
    installation_id: int
    repo: str


@app.post("/v1/installations/token")
def dispense_token(
    body: TokenRequest,
    x_github_token: str = Header(""),
) -> TokenResponse:
    """Mint this installation's API token, proving ownership through GitHub.

    Deliberately public: the proof is the caller's own GitHub credential, so
    an operator token here would defeat self-service without adding safety.

    Every verification failure renders as 404 — not 403, which would confirm
    the repo exists, and not a distinct message per cause, which would let a
    caller separate "private repo I cannot administer" from "repo that does
    not exist". The token rides in the response body once; only its hash is
    stored, so this endpoint is also the rotation and lost-token path.
    """
    if not x_github_token:
        raise HTTPException(status_code=401, detail="X-GitHub-Token required")
    owner, _, name = body.repo.partition("/")
    # Parse before either GitHub call: a malformed repo cannot be anyone's,
    # so there is nothing to spend a quota proving.
    if not owner or not name or "/" in name:
        raise HTTPException(status_code=404, detail="not found")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    installation_id = tenancy.verify_admin(x_github_token, owner, name)
    if installation_id is None:
        raise HTTPException(status_code=404, detail="not found")
    token = tenancy.mint(installation_id)
    if token is None:
        # GitHub knows this installation; the ledger does not. Same shape as
        # every other failure — the caller learns nothing either way.
        raise HTTPException(status_code=404, detail="not found")
    return TokenResponse(token=token, installation_id=installation_id, repo=body.repo)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_api.py -v -k dispense`
Expected: PASS, 6 passed

- [ ] **Step 5: Run the full suite and lint**

Run: `make test && cd api && uv run ruff check .`
Expected: 558 passed; ruff clean

- [ ] **Step 6: Commit**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "Add POST /v1/installations/token

Public by design: the proof is the caller's own GitHub credential, so an
operator token would defeat self-service without adding safety. Every
verification failure renders 404 rather than 403 or a per-cause message,
so a caller cannot separate 'private repo I cannot administer' from 'repo
that does not exist'."
```

---

### Task 4: `latest_reviews(installation_id=…)` — filter inside the grouped subquery

The highest-risk change in the plan. `latest_reviews` picks `max(id) GROUP BY (repo, pr_number)` in a subquery, and its own docstring already documents this bug class for the `EXTERNAL_TIER` filter.

**Files:**
- Modify: `api/doug/store.py:1176-1210` (`latest_reviews`)
- Test: `api/tests/test_store.py` (append)

**Interfaces:**
- Produces: `store.latest_reviews(limit: int = 200, repo: str | None = None, installation_id: int | None = None) -> list[dict]` — `installation_id=None` keeps today's unfiltered behavior exactly

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_store.py`:

```python
def _scored(repo, pr, installation_id, score=0.5):
    """One verdict row, App-identified or CI-identified (installation None)."""
    return store.save_review(
        repo,
        pr,
        "reader",
        Verdict(score=score, band=Band.FLAGGED, threshold=0.30, reasons=[]),
        pr_meta=_pr().model_dump(),
        installation_id=installation_id,
        github_repo_id=1 if installation_id else None,
        head_sha=("a" * 40) if installation_id else None,
        source="app" if installation_id else "ci",
    )


def test_latest_reviews_scopes_to_one_installation(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _scored("drewjst/doug", 1, 150424894)
    _scored("someone/else", 2, 777)
    rows = store.latest_reviews(installation_id=150424894)
    assert [r["repo"] for r in rows] == ["drewjst/doug"]


def test_latest_reviews_unscoped_still_sees_everything(tmp_path, monkeypatch):
    """The operator path must not change at all — doug-web and the soak
    both read through it."""
    _db(tmp_path, monkeypatch)
    _scored("drewjst/doug", 1, 150424894)
    _scored("someone/else", 2, 777)
    assert len(store.latest_reviews()) == 2


def test_scoped_queue_falls_back_to_the_app_row_under_a_newer_ci_row(tmp_path, monkeypatch):
    """THE regression test for this change.

    latest_reviews picks max(id) GROUP BY (repo, pr_number) in a subquery.
    Filter installation_id OUTSIDE that subquery and the CI row — written
    second, so higher id, and carrying installation_id NULL — wins max(id)
    for the PR and is then dropped, so the PR VANISHES from the tenant's
    queue instead of falling back to their own App verdict. Disappearing is
    a strictly worse failure than the one being fixed, and the function's
    own docstring already records this exact trap for the external-tier
    filter. If this test fails, the filter moved outside the subquery.
    """
    _db(tmp_path, monkeypatch)
    app_id = _scored("drewjst/doug", 1, 150424894, score=0.61)
    ci_id = _scored("drewjst/doug", 1, None, score=0.42)
    assert ci_id > app_id, "the CI row must be the newer one for this test to mean anything"

    rows = store.latest_reviews(installation_id=150424894)
    assert len(rows) == 1, "the PR vanished — the filter is outside the subquery"
    assert rows[0]["id"] == app_id
    assert rows[0]["score"] == 0.61
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_store.py -v -k "scopes_to_one_installation or falls_back_to_the_app_row"`
Expected: FAIL — `TypeError: latest_reviews() got an unexpected keyword argument 'installation_id'`

- [ ] **Step 3: Write the implementation**

In `api/doug/store.py`, replace the signature and the `latest` subquery of `latest_reviews`. Change:

```python
def latest_reviews(limit: int = 200, repo: str | None = None) -> list[dict]:
```

to:

```python
def latest_reviews(
    limit: int = 200, repo: str | None = None, installation_id: int | None = None
) -> list[dict]:
```

and change:

```python
    latest = (
        select(func.max(verdicts.c.id).label("id"))
        .where(verdicts.c.tier != EXTERNAL_TIER)
        .group_by(verdicts.c.repo, verdicts.c.pr_number)
        .scalar_subquery()
    )
```

to:

```python
    # The tenant filter belongs INSIDE this subquery for exactly the reason
    # the external-tier filter does, spelled out above: a row excluded only
    # on the outer query can still win max(id) for its PR and then be
    # dropped, and the PR disappears instead of falling back. A CI row
    # (installation_id NULL) on a tenant's own PR is precisely that case.
    scoped = verdicts.c.tier != EXTERNAL_TIER
    if installation_id is not None:
        scoped = scoped & (verdicts.c.installation_id == installation_id)
    latest = (
        select(func.max(verdicts.c.id).label("id"))
        .where(scoped)
        .group_by(verdicts.c.repo, verdicts.c.pr_number)
        .scalar_subquery()
    )
```

Also extend the docstring's second paragraph, which currently reads "`repo` scopes the queue; without it the ledger's every repo mixes together, which is an all-repos admin view, not a dashboard." Append to it:

```
    `installation_id` scopes the queue to one tenant; without it this is the
    operator view. Both filters are inside the grouped subquery — see the
    comment there before moving either.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_store.py -v -k "scopes_to_one_installation or unscoped_still_sees or falls_back_to_the_app_row"`
Expected: PASS, 3 passed

- [ ] **Step 5: Run the full suite and lint**

Run: `make test && cd api && uv run ruff check .`
Expected: 561 passed; ruff clean

- [ ] **Step 6: Commit**

```bash
git add api/doug/store.py api/tests/test_store.py
git commit -m "Scope latest_reviews by installation, inside the grouped subquery

Filtering outside the max(id) GROUP BY subquery would let a CI row
(installation_id NULL, written later so higher id) win its PR and then be
dropped, making the PR vanish from the tenant's queue instead of falling
back to their own App verdict. The function's docstring already recorded
this trap for the external-tier filter; a test now pins it for this one."
```

---

### Task 5: Scope `/v1/queue` and gate the operator-only endpoints

**Files:**
- Modify: `api/doug/api.py` — `/v1/queue` (`:446`), `/v1/score/read` (`:355`), `/v1/patterns` (`:554`), `/v1/comparisons` (`:1135`)
- Test: `api/tests/test_api.py` (append)

**Interfaces:**
- Consumes: `tenancy.resolve`, `store.latest_reviews(installation_id=…)`, `store.active_repos(installation_id)`
- Produces: `api._operator_only(x_doug_token) -> None` — raises 503 / 404 / 401, returns None for the operator

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_api.py`:

```python
def _tenant(tmp_path, monkeypatch, installation_id=150424894, login="drewjst"):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    monkeypatch.setenv("DOUG_API_TOKEN", "operator-secret")
    store.upsert_installation(installation_id, login, "User", "active")
    return api.tenancy.mint(installation_id)


def test_tenant_token_sees_only_its_own_rows(tmp_path, monkeypatch):
    token = _tenant(tmp_path, monkeypatch)
    store.save_review(
        "drewjst/doug", 1, "reader", VERDICT_FOR_QUEUE, pr_meta=PR_META, installation_id=150424894
    )
    store.save_review(
        "someone/else", 2, "reader", VERDICT_FOR_QUEUE, pr_meta=PR_META, installation_id=777
    )
    r = client.get("/v1/queue", headers={"X-Doug-Token": token})
    assert r.status_code == 200
    # PRMetadata carries no `repo` field, so the returned row is identified by
    # the url _with_url back-fills from the ledger's repo + pr_number columns.
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["pr"]["url"] == "https://github.com/drewjst/doug/pull/1"


def test_operator_token_still_sees_every_row(tmp_path, monkeypatch):
    """No soak regression: doug-web and the dual-run comparison both read
    through this path with the operator token."""
    _tenant(tmp_path, monkeypatch)
    store.save_review(
        "drewjst/doug", 1, "reader", VERDICT_FOR_QUEUE, pr_meta=PR_META, installation_id=150424894
    )
    store.save_review(
        "someone/else", 2, "reader", VERDICT_FOR_QUEUE, pr_meta=PR_META, installation_id=777
    )
    r = client.get("/v1/queue", headers={"X-Doug-Token": "operator-secret"})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2


def test_cross_tenant_repo_is_404_not_an_empty_list(tmp_path, monkeypatch):
    """The M2 exit gate, pinned. An empty list would be indistinguishable
    from 'no reviews yet', which tells the caller their guess might be a
    real repo. 404 says nothing at all."""
    token = _tenant(tmp_path, monkeypatch)
    store.set_installation_repos(150424894, [(1, "drewjst/doug")], replace=True)
    r = client.get("/v1/queue", params={"repo": "someone/else"}, headers={"X-Doug-Token": token})
    assert r.status_code == 404


def test_in_scope_repo_filters_normally(tmp_path, monkeypatch):
    token = _tenant(tmp_path, monkeypatch)
    store.set_installation_repos(150424894, [(1, "drewjst/doug")], replace=True)
    store.save_review(
        "drewjst/doug", 1, "reader", VERDICT_FOR_QUEUE, pr_meta=PR_META, installation_id=150424894
    )
    r = client.get("/v1/queue", params={"repo": "drewjst/doug"}, headers={"X-Doug-Token": token})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


def test_unknown_token_is_401(tmp_path, monkeypatch):
    _tenant(tmp_path, monkeypatch)
    r = client.get("/v1/queue", headers={"X-Doug-Token": "doug_nope"})
    assert r.status_code == 401


@pytest.mark.parametrize("path", ["/v1/patterns", "/v1/comparisons", "/v1/score/read"])
def test_tenant_token_404s_on_operator_only_endpoints(tmp_path, monkeypatch, path):
    """A valid credential pointed at an endpoint that is not theirs learns
    only that there is nothing there — same no-existence-leak rule as a
    cross-tenant repo."""
    token = _tenant(tmp_path, monkeypatch)
    call = client.post if path == "/v1/score/read" else client.get
    # A VALID ReadScoreRequest body ({pr, diff}) — FastAPI validates the body
    # before the handler runs, so a malformed one 422s and the test would
    # never reach the auth gate it exists to check.
    body = {"pr": {"number": 1, "title": "x", "author": "dev"}, "diff": ""}
    kwargs = {"json": body} if path == "/v1/score/read" else {}
    r = call(path, headers={"X-Doug-Token": token}, **kwargs)
    assert r.status_code == 404


@pytest.mark.parametrize("path", ["/v1/patterns", "/v1/comparisons"])
def test_junk_token_is_still_401_on_operator_only_endpoints(tmp_path, monkeypatch, path):
    _tenant(tmp_path, monkeypatch)
    r = client.get(path, headers={"X-Doug-Token": "doug_nope"})
    assert r.status_code == 401


def test_queue_without_operator_token_configured_is_503(tmp_path, monkeypatch):
    """A missing operator secret is a deployment misconfiguration and must
    fail loudly, not be masked by tenant traffic that happens to work."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    store.upsert_installation(150424894, "drewjst", "User", "active")
    token = api.tenancy.mint(150424894)
    r = client.get("/v1/queue", headers={"X-Doug-Token": token})
    assert r.status_code == 503
```

Add these module-level fixtures near the top of `api/tests/test_api.py`, after the `client = TestClient(app)` line:

```python
from doug.models import Band, Reason, Verdict

VERDICT_FOR_QUEUE = Verdict(
    score=0.62,
    band=Band.FLAGGED,
    threshold=0.30,
    reasons=[Reason(rule="reader:race-condition", label="Unguarded write", weight=0.0)],
)
PR_META = {"number": 1, "title": "Add cache", "author": "dev", "files": ["cache.py"]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_api.py -v -k "tenant_token or cross_tenant or operator_token_still or in_scope_repo or junk_token"`
Expected: FAIL — the tenant token gets 401 from `/v1/queue` (it is not `DOUG_API_TOKEN`)

- [ ] **Step 3: Write the implementation**

In `api/doug/api.py`, add this helper immediately above the `/v1/queue` handler:

```python
def _operator_only(x_doug_token: str) -> None:
    """Gate an endpoint that no tenant may reach.

    Three outcomes, and the middle one is the point: a token that RESOLVES
    to an installation is a real credential aimed at the wrong door, so it
    gets 404 — the same no-existence-leak rule a cross-tenant repo gets.
    A token that resolves to nothing is 401, because nothing about it was
    ever valid.
    """
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if hmac.compare_digest(x_doug_token, expected):
        return
    if tenancy.resolve(x_doug_token) is not None:
        raise HTTPException(status_code=404, detail="not found")
    raise HTTPException(status_code=401, detail="bad token")
```

In `/v1/score/read` (`:381-385`), `/v1/patterns` (`:566-570`), and `/v1/comparisons` (`:1141-1145`), replace each of these three identical blocks:

```python
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if not hmac.compare_digest(x_doug_token, expected):
        raise HTTPException(status_code=401, detail="bad token")
```

with:

```python
    _operator_only(x_doug_token)
```

In `/v1/queue`, replace the same five-line block with:

```python
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        # A missing operator secret is a misconfigured deployment. A tenant
        # token does not depend on it and could be honoured anyway, but
        # letting tenant traffic paper over the gap would hide the fault.
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    installation_id: int | None = None
    if not hmac.compare_digest(x_doug_token, expected):
        installation_id = tenancy.resolve(x_doug_token)
        if installation_id is None:
            raise HTTPException(status_code=401, detail="bad token")
        if repo is not None and repo not in {
            full_name for _, full_name in store.active_repos(installation_id)
        }:
            # 404, never an empty list: an empty list reads as "no reviews
            # yet" and tells the caller their guess may be a real repo.
            raise HTTPException(status_code=404, detail="not found")
```

and replace the `store.latest_reviews(repo=repo)` call inside the `if store.enabled():` branch with:

```python
            for row in store.latest_reviews(repo=repo, installation_id=installation_id)
```

Finally, replace the `/v1/queue` docstring's second paragraph — currently "`repo` stays a caller-supplied parameter until sessions exist; the shared token stops anonymous reads, it does not separate tenants." — with:

```
    Two token classes reach this endpoint. DOUG_API_TOKEN is the operator's
    and is unscoped. A dispensed token resolves to one installation and sees
    only its rows, and `repo` becomes a filter WITHIN that scope rather than
    a selector across scopes.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_api.py -v -k "tenant_token or cross_tenant or operator_token_still or in_scope_repo or junk_token or unknown_token or without_operator_token"`
Expected: PASS, 11 passed

- [ ] **Step 5: Run the full suite and lint**

Run: `make test && cd api && uv run ruff check .`
Expected: 572 passed; ruff clean

- [ ] **Step 6: Commit**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "Scope /v1/queue to the minting installation; 404 cross-tenant

DOUG_API_TOKEN stays operator-grade and unscoped so doug-web and the soak's
dual-run comparison keep working unchanged. A dispensed token resolves to
one installation and sees only its rows, with repo demoted from selector to
in-scope filter. A tenant token aimed at an operator-only endpoint gets 404
rather than 403; a token that resolves to nothing still gets 401."
```

---

### Task 6: Document the two token classes in REVIEWING.md and the roadmap

The gate is only closed if the next reader can tell what shipped.

**Files:**
- Modify: `docs/design/outcome-loop/ROADMAP.md:212`
- Modify: `docs/REVIEWING.md` (append a section)

- [ ] **Step 1: Tick the roadmap item with what actually shipped**

In `docs/design/outcome-loop/ROADMAP.md`, replace line 212:

```markdown
- [ ] Per-installation token dispense endpoint (GitHub-token-verified); scoped `/v1/queue` + receipt reads; cross-tenant read attempt → 404 (test pinned)
```

with:

```markdown
- [x] Per-installation token dispense endpoint (GitHub-token-verified); scoped
  `/v1/queue`; cross-tenant read attempt → 404 (test pinned). **Two token
  classes, not one replaced:** `DOUG_API_TOKEN` survives as an unscoped
  *operator* credential — scoping everything would have deleted the CI half of
  `/v1/comparisons` mid-soak, and `doug-web` has no login to carry a tenant
  token (its dashboard is M6's gated track). Dispensed tokens resolve to one
  `installation_id` and reach `/v1/queue` alone.
  **`/v1/patterns` is operator-only permanently**, on licensing rather than
  scoping grounds: `design-lock.md:71` — nothing derived from the research
  corpus is servable across tenants, because the rationales quote
  getsentry/grafana source verbatim.
  Dispense verifies PAT-first, app-JWT-second, because the app call spends
  Doug's shared 5,000/hr REST quota on a public endpoint and the reverse order
  is an anonymous drain loop. Receipt reads are **not** in this item — they are
  M3's endpoint and inherit the same `tenancy.resolve`.
  **Honest limit:** the operator token remains superuser. M2's gate is "no
  cross-tenant read" and an operator is not a tenant, but "scoped reads" should
  not be read as more than shipped. One token per installation, too — the
  garden and a tenant's CI would share it; `installation_tokens` when that bites.
```

- [ ] **Step 2: Append the operator/tenant split to REVIEWING.md**

Append to `docs/REVIEWING.md`:

```markdown
## Two token classes

`DOUG_API_TOKEN` is the **operator** credential: unscoped, reaches every
endpoint, and is what `doug-web` sends server-side (`web/lib/api.ts`). Reviews
that assume "the token" is tenant-scoped are reading the wrong class.

A **tenant** token is dispensed by `POST /v1/installations/token`, stored only
as `sha256` in `installations.token_hash`, and resolves to exactly one
`installation_id`. It reaches `/v1/queue` and nothing else.

Three things a reviewer should check, because each has a failure that looks
fine in passing tests:

1. **Any new filter on `latest_reviews` goes inside the grouped subquery.**
   Outside, an excluded row can still win `max(id)` for its PR and then be
   dropped — the PR vanishes rather than falling back. Pinned by
   `test_scoped_queue_falls_back_to_the_app_row_under_a_newer_ci_row`.
2. **Cross-tenant is 404, never an empty list.** An empty list reads as "no
   reviews yet" and confirms the caller's guess might be real.
3. **New GitHub calls on public endpoints check the caller's credential
   first.** The shared 5,000/hr REST quota was exhausted twice on 2026-08-02;
   a public endpoint that spends Doug's quota before the caller's is a drain
   loop. Pinned by `test_non_admin_pat_never_spends_dougs_github_quota`.
```

- [ ] **Step 3: Verify nothing else claims the old behavior**

Run: `cd api && grep -rn "does not separate tenants" doug/ ../docs/ || echo "clean"`
Expected: `clean` — Task 5 replaced the one occurrence in `/v1/queue`'s docstring.

- [ ] **Step 4: Run the full suite and lint**

Run: `make test && cd api && uv run ruff check .`
Expected: 572 passed; ruff clean

- [ ] **Step 5: Commit**

```bash
git add docs/design/outcome-loop/ROADMAP.md docs/REVIEWING.md
git commit -m "Record the operator/tenant token split and what M2 actually closed

The roadmap item said 'scoped /v1/queue + receipt reads'; receipts are M3's
endpoint and did not ship here, so the tick says so. Also records the two
limits a future reader would otherwise have to rediscover: the operator token
is still superuser, and there is one token per installation."
```

---

## Self-Review

**Spec coverage.** Every section of the design maps to a task: two token classes → Tasks 1, 5; endpoint scope table → Task 5; `tenancy.py` module boundary → Task 1; PAT-first ordering → Task 2; dispense flow and lifecycle → Tasks 1, 3; scoped read and subquery placement → Tasks 4, 5; 404-not-403 → Tasks 3, 5; all eight listed tests → Tasks 1–5; stated limits → Task 6. Out-of-scope items (M3 receipts, garden endpoint, multi-token, spend cap, `design-lock.md:38` amendment) have no task, as intended.

**Type consistency.** `mint`/`resolve`/`verify_admin`/`_caller_client`/`TOKEN_PREFIX` are spelled identically in every task that uses them. `latest_reviews(limit, repo, installation_id)` matches its call site in Task 5. `_operator_only` is defined once and called at three sites.

**One gap found and closed while reviewing:** the spec's error-handling section says a tenant token on an operator-only endpoint returns 404, but the original endpoints only compare against `DOUG_API_TOKEN` and would return 401. That needed `resolve()` on those endpoints too, which is why `_operator_only` exists in Task 5 rather than the endpoints keeping their inline blocks.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-04-tenant-token-dispense-scoping.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration. Matches this repo's execution model (`HANDOFF.md`: fresh implementer from an extracted brief, then an independent reviewer, then a fix round).

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.
