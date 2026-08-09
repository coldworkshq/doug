# Front Door Phase 1a — identity and binding

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stranger signs in with GitHub, installs Doug on a repo they administer, and lands on a signed-in page listing the installations they are entitled to see — with the entitlement derived live from GitHub, never assumed.

**Architecture:** AuthKit holds the session; GitHub holds the entitlement. FastAPI verifies the AuthKit JWT against JWKS, maps `org_id` → `installations.workos_org_id`, and scopes every read to the repos that user can actually see. Binding an installation requires proof of *authority* (org-admin), not merely *visibility*.

**Tech Stack:** FastAPI + SQLAlchemy + PyJWT (`api/`), Next.js 16.2.12 + `@workos-inc/authkit-nextjs` (`web/`), Cloud Run via `api/deploy/gcp.sh`.

## Why this plan stops where it does

The spec's Phase 1 covers identity, binding, *and* the tenant data surface. This plan covers **identity and binding only**. The data surface (tenant-scoped queue, receipts, the welcome/IOU block) is its own plan, `front-door-phase-1b`, written after this lands.

They split cleanly because this plan's exit is independently valuable and independently testable — a real stranger can sign in and bind a real installation — while 1b only adds rows to a page that already exists. What could *not* split, and is therefore all inside this plan, is auth-shell-without-binding: `org_id → workos_org_id` needs a column the bind step creates, and "org selection works" needs organizations only the bind step provisions.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-08-front-door-design.md`. Read §0, §2 and §3 before starting; §0's gate has **passed** and its four results are requirements here.
- **This repo has NO `conftest.py` and NO pytest fixtures.** The idiom is `tmp_path` + `monkeypatch` + the module's own `_db()` helper (`api/tests/test_api.py:2467`) + `TestClient(app)` built in-test.
- API from `api/`: `uv run pytest`, `uv run ruff check .`, `bash -n deploy/gcp.sh`. Web from `web/`: `npm test`, `npm run lint`, `npm run build`.
- **`web/AGENTS.md` applies**: this Next.js version has breaking changes from training data. Read `node_modules/next/dist/docs/` before writing Next code. It is **Next 16.2.12** → `proxy.ts` with `authkitProxy()`, never `middleware.ts`.
- **Follow the installed SDK's README over this plan** where they disagree — fetch `https://raw.githubusercontent.com/workos/authkit-nextjs/main/README.md` first. SDK APIs move; this plan does not.
- Do not touch `docs/design/outcome-loop/publication-preregistration.md` — LOCKED.
- Commit after every task. Never amend a commit from a previous task.

### Measured facts — do not re-derive, do not contradict

From the 2026-08-09 production probe (spec §0):

- The GitHub token is **user-to-server** (`ghu_` prefix), lifetime **~8 hours**.
- `GET /user/installations` answers on **`:read`, `:write` or `:admin`** — it reports what a user may **see**, never what they may **control**.
- `repository_selection` differs across real installations: `drewjst` = `selected`, `lemahq` = `all`.
- `org_id` is **absent** when no organization is selected. The operator holds two installations, so this is the *normal* first-sign-in state, not an edge case.
- WorkOS refuses a first authentication with `email_verification_required` + a `pending_authentication_token`, and emails a one-time code.

---

### Task 1: Migration — `installations.workos_org_id`

**Files:**
- Modify: `api/doug/store.py:183-192` (the `installations` table)
- Modify: `api/doug/migrations.py`
- Test: `api/tests/test_migrations.py`, `api/tests/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in ONE migration (see Task 5 for why the second column exists):
  - `installations.workos_org_id` — `String(255)`, nullable, **unique**. Tasks 4–8 depend on it.
  - `installations.installed_by_github_user_id` — `BigInteger`, nullable. Task 5 depends on it. Populated from the `installation` webhook's `sender.id`, which nothing records today (`grep sender api/doug/api.py` → nothing; `store.upsert_installation`, `store.py:736`, takes only four fields). Widening that writer is part of this task.

- [ ] **Step 1: Read the real migration number — do not trust this plan**

```bash
cd api && python3 -c "
import re; s=open('doug/migrations.py').read()
n=[int(m) for m in re.findall(r'^\s{4}\(\s*(\d+),', s, re.M)]
print('present:', sorted(n)); print('NEXT FREE:', max(n)+1)"
```

At the time of writing the next free number was **9**, and MT3's `installations.reconciled_at` was earmarked for 9 but never started. **This trap has fired four times in this repo.** Use whatever the command prints.

- [ ] **Step 2: Write the failing test**

Append to `api/tests/test_store.py`:

```python
def test_installations_carries_a_unique_workos_org_id(tmp_path, monkeypatch):
    """One WorkOS organization maps to exactly one installation. Without the
    unique constraint, two installations could claim the same org and a
    session would resolve to whichever row the database returned first."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    from doug import store
    store._reset_engine_for_tests() if hasattr(store, "_reset_engine_for_tests") else None
    cols = {c.name: c for c in store.installations.columns}
    assert "workos_org_id" in cols, "column missing"
    assert cols["workos_org_id"].unique is True, "must be unique"
    assert cols["workos_org_id"].nullable is True, "existing rows have no org yet"
```

If `store` has no engine-reset helper, drop that line — read the module first and follow whatever the neighbouring tests do.

- [ ] **Step 3: Run it, watch it fail**

```bash
cd api && uv run pytest tests/test_store.py -k workos_org_id -v
```
Expected: FAIL, `column missing`.

- [ ] **Step 4: Add the column and the migration**

In `store.py`, inside the `installations` Table, after `account_type`:

```python
    # The WorkOS Organization bound to this installation. NULL for every row
    # that predates the front door — including the operator's own install,
    # which was populated by webhook redelivery (MT0) and has no WorkOS
    # identity. Unique so a session's org_id resolves to exactly one tenant.
    Column("workos_org_id", String(255), nullable=True, unique=True),
```

In `migrations.py`, add the next free number following the existing entries' exact shape (read two neighbours first — do not invent a style):

```python
    (
        <NEXT>,
        (
            "ALTER TABLE installations ADD COLUMN workos_org_id VARCHAR(255)",
            "CREATE UNIQUE INDEX ix_installations_workos_org_id "
            "ON installations (workos_org_id)",
        ),
    ),
```

A unique **index** rather than a table constraint: SQLite (which the suite runs on) cannot add a UNIQUE column constraint via ALTER TABLE, and a partial-null unique index behaves the same on both engines for the NULLs this column will mostly hold.

- [ ] **Step 5: Run the full suite**

```bash
cd api && uv run pytest -q 2>&1 | tail -2 && uv run ruff check .
```
Expected: all pass (931 + your new test), ruff clean. `test_migrations.py` has parity checks between the table definition and the migration list — if they complain, the column and the migration disagree; fix the disagreement, do not weaken the test.

- [ ] **Step 6: Commit**

```bash
git add api/doug/store.py api/doug/migrations.py api/tests/test_store.py
git commit -m "feat: bind installations to a WorkOS organization"
```

---

### Task 2: Replace the `ctx is None` operator sentinel

**Security prerequisite. Do this before any second credential type exists.**

`api.py` uses `ctx is None` to mean "this caller is the operator" in three places (`:400`, `:428`, `:795`). `:428` is the dangerous one — it routes `?repo=` into `store.latest_reviews(repo=…)`, a name lookup across **every** installation. A session context that is not a `TokenContext` would make `ctx is None` true and hand an unscoped, cross-tenant query to a browser session.

**Files:**
- Modify: `api/doug/api.py` (`:400`, `:428`, `:795` and the surrounding handlers)
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an explicit `is_operator: bool` local in `queue()` and the receipt handler, replacing every `ctx is None` identity test. Task 4 relies on operator-ness never being inferred from a context's absence.

- [ ] **Step 1: Write the failing test**

```python
def test_queue_repo_filter_is_operator_only_by_explicit_flag(tmp_path, monkeypatch):
    """`?repo=` reaches store.latest_reviews(repo=...) — a name lookup across
    EVERY installation — and must be reachable only by a caller explicitly
    established as the operator. Inferring that from `ctx is None` means any
    future non-TokenContext caller silently inherits it."""
    _db(tmp_path, monkeypatch)
    import doug.api as api_mod
    src = inspect.getsource(api_mod.queue)
    assert "ctx is None" not in src, (
        "operator-ness must be an explicit flag, not the absence of a context"
    )
    assert "is_operator" in src
```

Add `import inspect` at the top of the test module if absent.

- [ ] **Step 2: Run it, watch it fail**

```bash
cd api && uv run pytest tests/test_api.py -k operator_only_by_explicit_flag -v
```
Expected: FAIL.

- [ ] **Step 3: Introduce the flag**

In `queue()`, immediately after the operator-token comparison succeeds, set `is_operator = True`; in the branch that resolves a tenant token, set `is_operator = False`. Then replace:

- `:400` `if ctx is None:` → `if is_operator:`
- `:428` `repo=repo if ctx is None else None` → `repo=repo if is_operator else None`

Do the same in the receipt handler at `:795`, where `ctx is None or "receipt:read" not in ctx.scopes` becomes an explicit non-operator check plus the scope check. **Read that handler fully before editing** — it 401s on an unresolved token and that behaviour must not change.

- [ ] **Step 4: Run the suite**

```bash
cd api && uv run pytest -q 2>&1 | tail -2 && uv run ruff check .
```
Expected: all pass. Existing tests already cover operator vs tenant queue behaviour in both directions; if any flips, the refactor changed behaviour — fix the code, not the test.

- [ ] **Step 5: Commit**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "refactor: make operator identity explicit, not the absence of a context"
```

---

### Task 3: The session context and the shared liveness core

**Files:**
- Modify: `api/doug/tenancy.py`
- Test: `api/tests/test_tenancy.py`

**Interfaces:**
- Consumes: Task 1's column.
- Produces:
  - `SessionContext` — frozen dataclass: `installation_id: int`, `repo_ids: frozenset[int]`, `scopes: tuple[str, ...]`. **`repo_ids` is never `None`.**
  - `live_scope(installation_id: int, claimed_repo_ids: frozenset[int] | None) -> frozenset[int] | None` — applies `installations.state == "active"` and intersects a claim against `store.active_repos`. Returns `None` when the installation is not live. Called by both `resolve()` and Task 4's session path.

- [ ] **Step 1: Write the failing tests**

```python
def test_session_context_repo_ids_is_never_none():
    """TokenContext allows repo_ids=None to mean installation-wide, because a
    key's selection was proved at mint time. A browser session has no mint
    step, so installation-wide would hand a user with :read on ONE repo the
    whole org's rows — MT1 reintroduced, and worse, since MT1 needed admin."""
    from doug import tenancy
    import dataclasses
    fields = {f.name: f for f in dataclasses.fields(tenancy.SessionContext)}
    assert "repo_ids" in fields
    ann = str(fields["repo_ids"].type)
    assert "None" not in ann and "Optional" not in ann, (
        f"repo_ids must not be optional on a session context, got {ann}"
    )


def test_live_scope_drops_repos_the_installation_no_longer_covers(tmp_path, monkeypatch):
    """The claim is what GitHub said; the ledger is the authority. A repo that
    left the installation must not survive in a session's scope."""
    # Seed an active installation with ONE active repo, claim TWO.
    # Follow the seeding idiom already used in test_tenancy.py.
    ...
```

Write the second test against the seeding helpers already present in `test_tenancy.py` — read that file first and reuse its idiom rather than inventing one.

- [ ] **Step 2: Run them, watch them fail**

```bash
cd api && uv run pytest tests/test_tenancy.py -k "session_context or live_scope" -v
```

- [ ] **Step 3: Implement**

```python
@dataclass(frozen=True)
class SessionContext:
    """What a signed-in browser session may see.

    Unlike TokenContext, repo_ids is NEVER None. A key's selection was proved
    at mint time ("proof covers selection", MT1); a session has no mint step,
    so there is nothing to license installation-wide access. The scope is
    always the explicit set GitHub reported for THIS user, intersected with
    the live ledger.
    """

    installation_id: int
    repo_ids: frozenset[int]
    scopes: tuple[str, ...]


def live_scope(
    installation_id: int, claimed_repo_ids: frozenset[int] | None
) -> frozenset[int] | None:
    """Intersect a claim against the live ledger, or None if not serviceable.

    This is the part `resolve` and the session path genuinely share: the
    installations.state check and the active-repo intersection. It is NOT the
    whole of resolve — revoked_at, expires_at and repo_selection are
    token-row-shaped and have no session analogue. Claiming one authorization
    core would overstate it; this is the honest, shared piece.
    """
    row = store.installation_state(installation_id)
    if row != "active":
        return None
    live = {rid for rid, _ in store.active_repos(installation_id)}
    if claimed_repo_ids is None:
        return frozenset(live)
    effective = frozenset(claimed_repo_ids) & live
    return effective or None
```

Add `store.installation_state(installation_id) -> str | None` if absent. Then refactor `resolve()` to call `live_scope` for its state check and repo intersection **without changing its behaviour** — the existing tenancy tests are the proof, so their count must not move.

- [ ] **Step 4: Suite + lint**

```bash
cd api && uv run pytest -q 2>&1 | tail -2 && uv run ruff check .
```

- [ ] **Step 5: Commit**

```bash
git add api/doug/tenancy.py api/doug/store.py api/tests/test_tenancy.py
git commit -m "feat: a session scope that is never installation-wide"
```

---

### Task 4: Verify the AuthKit JWT and resolve a session

**Files:**
- Create: `api/doug/session_auth.py`
- Modify: `api/pyproject.toml` (add `pyjwt[crypto]`)
- Test: `api/tests/test_session_auth.py`

**Interfaces:**
- Consumes: Task 1's column, Task 3's `SessionContext` / `live_scope`.
- Produces: `resolve_session(bearer: str, claimed_repo_ids: frozenset[int] | None) -> SessionContext | None`, and `SESSION_SCOPES: tuple[str, ...] = ("queue:read", "receipt:read")`.

- [ ] **Step 1: Write the failing tests** — each must be able to fail for its own reason

```python
def test_absent_org_id_fails_closed(monkeypatch):
    """org_id is present only when an organization was selected. The probe
    confirmed it is ABSENT on a normal first sign-in with two installations,
    so this is the common path, not an edge case. It must never default to
    'the first installation'."""

def test_unknown_org_id_is_refused(tmp_path, monkeypatch):
    """A well-formed token whose org maps to no installation gets nothing."""

def test_expired_or_tampered_token_is_refused(monkeypatch):
    """Signature and exp are checked, not just decoded."""

def test_session_scopes_cannot_exceed_the_enumerated_set():
    """A session has no scopes of its own. Synthesising them is inventing
    authority; the set is fixed and pinned."""
    from doug.session_auth import SESSION_SCOPES
    assert set(SESSION_SCOPES) <= {"queue:read", "receipt:read"}
```

Do **not** call the network in tests. Mint test JWTs locally with a generated RSA key and monkeypatch the JWKS client.

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/test_session_auth.py -v`

- [ ] **Step 3: Implement**

```python
"""Resolve a signed-in browser session to a tenant scope.

WorkOS holds identity; GitHub holds entitlement; Postgres arbitrates. This
module only turns a verified JWT into an installation_id — the scope itself
comes from tenancy.live_scope, so a session and a machine key apply the same
liveness and repo intersection.
"""

import os
import jwt
from jwt import PyJWKClient

from . import store, tenancy

SESSION_SCOPES: tuple[str, ...] = ("queue:read", "receipt:read")

_jwks_client: PyJWKClient | None = None


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        client_id = os.environ["WORKOS_CLIENT_ID"]
        _jwks_client = PyJWKClient(f"https://api.workos.com/sso/jwks/{client_id}")
    return _jwks_client


def resolve_session(
    bearer: str, claimed_repo_ids: frozenset[int] | None
) -> tenancy.SessionContext | None:
    if not bearer:
        return None
    token = bearer[7:] if bearer.lower().startswith("bearer ") else bearer
    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], options={"require": ["exp"]})
    except Exception:
        return None
    org_id = claims.get("org_id")
    if not org_id:
        # Absent when no organization was selected. Fail closed — NEVER
        # default to the first installation.
        return None
    installation_id = store.installation_id_for_workos_org(org_id)
    if installation_id is None:
        return None
    scope = tenancy.live_scope(installation_id, claimed_repo_ids)
    if scope is None:
        return None
    return tenancy.SessionContext(
        installation_id=installation_id, repo_ids=scope, scopes=SESSION_SCOPES
    )
```

Prefer the WorkOS SDK's `get_jwks_url()` over the hardcoded URL if the Python SDK is already a dependency — check before hardcoding.

- [ ] **Step 4: Add `store.installation_id_for_workos_org(org_id) -> int | None`** with its own test. No such query exists today.

- [ ] **Step 5: Suite + lint + commit**

```bash
git add api/doug/session_auth.py api/doug/store.py api/pyproject.toml api/tests/
git commit -m "feat: resolve a WorkOS session to a live tenant scope"
```

---

### Task 5: Bind an installation — authority, not visibility

**This is the task most likely to ship a vulnerability. Read the whole thing before writing code.**

**Files:**
- Modify: `api/doug/api.py` (new `POST /v1/installations/bind`)
- Modify: `api/doug/tenancy.py` (reuse `verify_org_admin`, `tenancy.py:245`)
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 4.
- Produces: `POST /v1/installations/bind` taking `{installation_id, workos_org_id}` under a verified session, returning 204 on success.

**The attack this must refuse.** Setup-URL parameters are attacker-supplied and no GitHub redirect need ever occur. An attacker with `:read` on one repo sees a victim's `installation_id` in their own `GET /user/installations`, then posts it here. A membership check alone **passes** — the installation genuinely is in their list. Binding must therefore require proof of **authority**, not visibility.

> **CORRECTION, 2026-08-09 — an earlier draft of this plan said to use
> `tenancy.verify_org_admin` (`tenancy.py:245`). That does not work here, and
> the reason matters.**
>
> `verify_org_admin(pat, owner)` takes a **PAT**. Its authority hop is
> `orgs.get_membership_for_authenticated_user`, which for a GitHub App
> *user-to-server* token requires the App to hold the organization
> **Members: read** permission. Doug is a code-review app and does not have it.
> Adding it would make GitHub require **every existing installation to
> re-accept permissions**, interrupting live tenants — a real cost, to ask for
> org membership data a code reviewer has no other use for.
>
> The obvious fallback is not available either: nothing records who performed
> an installation. `grep sender api/doug/api.py` returns nothing, and
> `store.upsert_installation` (`store.py:736`) takes only
> `(installation_id, account_login, account_type, state)`.

**Use the installer identity instead.** Capture `sender.id` from the
`installation` webhook into a new `installations.installed_by_github_user_id`
column (fold it into Task 1's migration — one migration, two columns), and
require the session's GitHub user id to equal it before binding.

This proves something **narrower and more relevant** than org-admin: you are
the person who actually installed Doug here. It needs no new App permission and
disrupts no existing tenant. Its limit is honest and must be stated in the
code: it only works for installations created **after** this ships. Pre-existing
ones — notably the operator's own `150424894`, populated by webhook redelivery
under MT0 — have no recorded installer and cannot self-bind. They need a
deliberate operator bind or a one-off backfill, which is acceptable because the
target of this phase, `coldworkshq/coldworks`, is a **fresh** install that fires
a fresh webhook carrying its sender.

Get the session's GitHub user id from the identity WorkOS already holds for the
user — do not call GitHub again for it, and do not trust any id supplied in the
request body.

- [ ] **Step 1: Write the failing tests — the first is the security test**

```python
def test_bind_refuses_an_installation_the_caller_can_read_but_not_administer():
    """The exact claimable-tenant attack. GET /user/installations answers on
    :read, so visibility is NOT authority. A caller who can merely see an
    installation must not be able to bind it to their own organization."""


def test_bind_is_idempotent_for_the_same_org():
    """installation.created is replayable via GitHub's Redeliver button."""


def test_bind_refuses_to_move_an_installation_to_a_different_org():
    """Re-binding a live installation to another organization is a takeover,
    not an update."""
```

- [ ] **Step 2: Run, watch fail.**

- [ ] **Step 3: Implement**, with a Postgres advisory lock around the find-or-create: `external_id` has no documented upsert and no documented conflict code, so it is **not** race-safe. Under SQLite the lock is a no-op — guard on dialect and say so in a comment.

- [ ] **Step 4: Suite + lint + commit.**

---

### Task 6: WorkOS organization lifecycle

**Files:** `api/doug/workos_client.py` (new), `api/tests/test_workos_client.py`

**Interfaces:**
- Produces: `ensure_org(installation_id, account_login) -> str` (returns `workos_org_id`, keyed `external_id="gh-inst-<id>"`), `ensure_membership(org_id, workos_user_id)`, `revoke_memberships(org_id)`.

**Teardown is not optional.** The design's earlier claim that stale access ends "at next sign-in" was false: membership is additive and nothing removes it. `installation.deleted` and `suspend` webhooks must revoke memberships, and uninstall/reinstall mints a **new** `installation_id`, orphaning `gh-inst-<old>` with live members.

- [ ] Steps: failing tests (including "uninstall revokes"), watch fail, implement against a mocked WorkOS API, wire the webhook handlers, suite, commit.

---

### Task 7: AuthKit in `web/`

**Files:** `web/package.json`, `web/proxy.ts` (new), `web/app/auth/callback/route.ts` (new), `web/app/layout.tsx`, `web/app/auth/actions.ts` (new), `api/deploy/gcp.sh`

**Non-negotiables, each already paid for once:**
- **Next 16.2.12 → `proxy.ts` with `authkitProxy()`.** `middleware.ts` is deprecated and Next 16 throws E900 if both exist.
- **The matcher must EXCLUDE `/` and `/queue`.** `doug-web` is the only service with staged traffic and `promote_if_healthy` on `/` (`gcp.sh:466`); a broken cookie password must not be able to take down marketing.
- **`handleAuth({ baseURL })` is required** — Cloud Run's container hostname differs from the request host, and without it callbacks redirect wrong.
- **Sign-out is a POST server action**, never a GET route.
- **`@workos-inc/authkit-nextjs` must be added and the lockfile regenerated**, or `web-image` goes red: `web/Dockerfile` runs `npm ci` from the lockfile.
- **New secrets** (`WORKOS_API_KEY`, `WORKOS_CLIENT_ID`, `WORKOS_COOKIE_PASSWORD`): Secret Manager entries, an `add-iam-policy-binding` for `doug-web-sa` in `setup()` (pattern at `gcp.sh:165-171`), and `--set-secrets` on `web()`. Phase 0 deliberately left `doug-web` holding nothing; this is the considered re-add, and `test_deploy_gcp.py`'s "no secrets" pin must be updated to "only the WORKOS_* secrets" rather than deleted.

- [ ] Steps: add deps + lockfile, proxy with the exclusion, callback route, provider, sign-out action, deploy config + test updates, `npm test`/`lint`/`build`, `bash -n`, commit.

---

### Task 8: `/install/start` and `/install/callback`

**Files:** `web/app/install/start/route.ts`, `web/app/install/callback/route.ts` (both new)

**The cookie must survive an inbox round-trip.** WorkOS refuses a first authentication until email is verified, so the user leaves for their inbox and returns — possibly minutes later, possibly in a new tab. A short redirect-scale TTL loses the pending installation and breaks first-time self-serve at the exact moment the design exists to make seamless. Size the TTL for a human checking email.

- **No `state` param.** GitHub does not document propagating `state` to a Setup URL — its docs name only `installation_id`, and warn that *"bad actors can hit this URL with a spoofed `installation_id`."* Use a signed HttpOnly cookie, which the cold-arrival path needs anyway, collapsing both entrances into one code path.
- **Nonce is single-use** — burn it in storage, not merely compare it. The earlier draft's nonce was decorative and replayable until `exp`.
- `setup_action=update` fires whenever anyone edits repo selection: treat as re-derive-scope, **never** as bind.
- `setup_action=request` produces **no installation at all** (org admin must approve) — land on an explanatory "waiting for your admin" state, not an error.

- [ ] Steps: failing route tests, watch fail, implement, verify the cold-arrival path resumes, commit.

---

### Task 9: `/dashboard`

**Files:** `web/app/dashboard/page.tsx`, `web/lib/session-api.ts` (both new)

**Never reuse `web/lib/api.ts` for tenant fetches.** Its `inflight`/`last` (`:116-118`) are module-global and key-less — deliberately, for the public page. A tenant fetch sharing that module would serve one tenant's data to the next visitor. Session fetches are cacheless or keyed by org, pinned by a test.

- Lists the user's installations from `GET /user/installations`, each with per-user `repo_ids` from `GET /user/installations/{id}/repositories`. **`repository_selection` varies** (`drewjst`=`selected`, `lemahq`=`all`) — handle both.
- **Decide what to do about `lemahq`.** It is visible to the operator and will appear as a tenant. Correct per the model, but it collides with "Doug and lema are separate products." Show, hide, or label — deliberately, and record the choice.
- Orgless state renders AuthKit's own organization picker. **Do not hand-roll one** — AuthKit hosts it and auto-selects on a single membership.

- [ ] Steps: render test, implement, `npm test`/`lint`/`build`, commit.

---

### Task 10: The exit gate

**Files:** `api/deploy/prove-session-isolation.sh` (new)

A sibling to `prove-isolation.sh`, executable against prod — that script earned its place catching the pepper-newline and GC'd-client defects unit tests could not.

- [ ] 1. A session with org A selected returns only A's rows.
- [ ] 2. Same session, org B selected, returns only B's rows.
- [ ] 3. **A member with access to ONE repo in an org sees only that repo's rows.** The earlier draft's gate omitted this and would have passed with the MT1 regression present — 1 and 2 test org-vs-org and never member-vs-member.
- [ ] 4. Orgless JWT → refused.
- [ ] 5. Suspended installation → refused on the **next** request.
- [ ] 6. Tampered/expired JWT → refused.
- [ ] 7. `org_id` mapping to no installation → refused.
- [ ] 8. A valid session JWT gets 401/404 on **every** operator route.
- [ ] 9. A bind attempt for an installation the caller can read but not administer → refused.

---

## Phase exit criteria

- [ ] `uv run pytest` green; `uv run ruff check .` clean; `bash -n deploy/gcp.sh` clean.
- [ ] `npm test` (reporting **>0 tests**), `npm run lint`, `npm run build` all pass.
- [ ] **`coldworkshq/coldworks` installed cold through the front door and bound** — an org install on a private repo, with no prior Doug installation. This is the only setup that tests the path a stranger takes.
- [ ] The orgless path exercised for real: the operator holds two installations, so the first sign-in has no `org_id`.
- [ ] `prove-session-isolation.sh` 9/9 against prod.
- [ ] A first-time user completing email verification still lands bound — the inbox round-trip did not lose the pending installation.

## Honest status of this plan — read before executing

**Tasks 1–5 are execution-ready**: exact files, real code, runnable verification
commands. **Tasks 6–10 are specified but not stepped** — they state the
requirements, the traps, and the exit conditions, but they do not yet carry
task-by-task code the way Tasks 1–5 do.

That is a real gap against this repo's own standard, and it is recorded rather
than disguised: a plan that *looks* complete but is half outline produces bad
execution, and the executing session would discover it at Task 6 instead of
now. **The first job of whoever executes this is to expand Tasks 6–10 to the
same standard as 1–5**, ideally one at a time, just before executing each —
their content depends on decisions Tasks 1–5 will settle (the exact
`SessionContext` shape, whether the WorkOS Python SDK is a dependency, what
`store.installation_id_for_workos_org` ends up looking like).

Also un-run: an independent review of this plan was dispatched and never
delivered. The Task 5 correction above was found by the controller reading
`verify_org_admin` directly, *after* the first draft was committed — which is
itself evidence that the parts of this plan not yet verified against real code
deserve suspicion, not trust.

## Deliberately out of scope

Tenant-scoped queue, receipts, and the welcome/IOU block — all `front-door-phase-1b`. The showcase endpoint keyed on `github_repo_id` rather than the display-only repo string, and a smoke test for it, remain recorded Phase 0 follow-ups.
