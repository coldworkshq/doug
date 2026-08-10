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

> **STRUCTURAL CHANGE, 2026-08-09 (Andrew).** The original plan had **Task 5**
> *consuming* a `workos_org_id` that only **Task 6** *produces*, so Task 5 as
> ordered could not work end to end. Worse, accepting a caller-supplied org id
> reopened a squatting attack: bind a victim's org id to your own installation
> before they bind, and Task 1's UNIQUE index then blocks their legitimate bind
> permanently. **Task 6 is therefore merged into this task**, and the request
> body carries **only `installation_id`** — the org id never crosses the wire,
> so the attack is removed rather than defended against.

**Files:**
- Modify: `api/doug/session_auth.py` (extract a claims-only verifier)
- Create: `api/doug/workos_client.py`
- Create: `api/tests/test_workos_client.py`
- Modify: `api/doug/store.py` (installer lookup + the bind write)
- Modify: `api/doug/api.py` (new `POST /v1/installations/bind`)
- Modify: `api/pyproject.toml` (declare `httpx` explicitly)
- Modify: `api/deploy/gcp.sh` + `api/tests/test_deploy_gcp.py` (`WORKOS_*` secrets on doug-api)
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 4.
- Produces: `POST /v1/installations/bind` taking `{"installation_id": int}` under a verified AuthKit JWT, returning 204.

**The attack this must refuse.** Setup-URL parameters are attacker-supplied and no GitHub redirect need ever occur. An attacker with `:read` on one repo sees a victim's `installation_id` in their own `GET /user/installations`, then posts it here. A membership check alone **passes** — the installation genuinely is in their list. Binding must therefore require proof of **authority**, not visibility.

**Why not org-admin.** `tenancy.verify_org_admin` (`tenancy.py:245`) takes a **PAT**, and it has two paths: a login match (caller *is* the account) which needs no extra permission but only fires for **User** installs, and an admin-membership hop (`orgs.get_membership_for_authenticated_user`) which for a user-to-server token requires the App to hold organization **Members: read**. Doug does not have it, and adding it would force **every existing installation to re-accept permissions**. `coldworkshq` is an **org** install, so it falls to the hop Doug cannot make. Rejected on evidence, not preference.

**The proof actually used: installer identity.** Task 1 captured the `installation` webhook's `sender.id` into `installations.installed_by_github_user_id` (written only on `action == "created"`, and never overwritten by a later suspend/redelivery). Bind requires the signed-in user's GitHub id to equal it. This proves something **narrower and more relevant** than org-admin — *you are the person who installed Doug here* — with no new App permission and no tenant disruption.

**Its limit is honest and must be stated in the code:** it only works for installations created **after** Task 1 shipped. Pre-existing ones — notably the operator's own `150424894`, populated by webhook redelivery under MT0 — have no recorded installer and **cannot self-bind**. They need a deliberate operator bind or a one-off backfill. `coldworkshq/coldworks` is a fresh install and fires a fresh webhook carrying its sender, so the phase target is unaffected.

**Bind cannot use `resolve_session`.** `resolve_session` maps `org_id` → installation, but at bind time there is **no org** — creating it is what bind does. Using it here would be circular and would always fail closed. Bind needs a strictly weaker primitive that proves *who is signed in* and asserts nothing about what they may see.

**`idp_id` is an UNRETIRED RISK.** WorkOS documents `idp_id` only as "a unique identifier from the external provider", with a **Microsoft** example; neither the identities reference nor the GitHub integration page states its format for GitHub. It could not be measured — the gate probe's credentials were deleted. The inference is that it is the numeric GitHub user id. **Do not paper over this**: compare as normalized strings, and when `idp_id` is non-numeric, refuse **and log the value received**, so the first real bind diagnoses it in one query instead of silently denying forever.

**Verified WorkOS endpoints** (checked against live docs 2026-08-09 — do not invent others). All take `Authorization: Bearer $WORKOS_API_KEY`:

| Purpose | Method + path |
|---|---|
| GitHub user id | `GET /user_management/users/{user_id}/identities` → `[].idp_id` |
| Find org | `GET /organizations/external_id/{external_id}` |
| Create org | `POST /organizations` `{name, external_id}` |
| Add member | `POST /user_management/organization_memberships` `{user_id, organization_id}` |

- [ ] **Step 1: Extract a claims-only verifier — pure refactor, no behaviour change**

In `session_auth.py`, split the signature/exp verification out of `resolve_session` so both callers share it:

```python
def verify_session_claims(bearer: str) -> dict | None:
    """Verify an AuthKit JWT's signature and expiry, and return its claims.

    Deliberately weaker than resolve_session: it proves WHO is signed in and
    says nothing about what they may see. Bind needs exactly this, because it
    runs BEFORE any organization exists — creating one is what bind does — so
    resolve_session (which fails closed without org_id) would be circular.
    Never use this for a data read; use resolve_session, which additionally
    resolves and live-intersects a tenant scope.
    """
```

`resolve_session` then calls it and keeps its own `org_id` handling. **Both existing log lines and their split must survive** (JWKS failure vs token failure stay distinguishable). The Task 4 tests are the proof: all 11 must pass unmodified.

- [ ] **Step 2: Write the failing tests — the first is the security test**

```python
def test_bind_refuses_an_installation_the_caller_can_read_but_not_administer():
    """The exact claimable-tenant attack. GET /user/installations answers on
    :read, so visibility is NOT authority. A caller whose GitHub id does not
    match installed_by_github_user_id must be refused even though the
    installation is genuinely visible to them."""


def test_bind_refuses_an_installation_with_no_recorded_installer():
    """Pre-Task-1 rows carry NULL. NULL must never compare equal to anything —
    a fail-open here would let ANY signed-in user claim every legacy tenant,
    including the operator's own 150424894."""


def test_bind_is_idempotent_for_the_same_org():
    """installation.created is replayable via GitHub's Redeliver button."""


def test_bind_refuses_to_move_an_installation_to_a_different_org():
    """Re-binding a live installation to another organization is a takeover,
    not an update."""


def test_bind_refuses_a_non_numeric_idp_id_and_says_so():
    """idp_id's GitHub format is undocumented and unmeasured. If it is not the
    numeric user id, bind must refuse AND log the value, so the first real
    attempt is diagnosable in one query rather than silently denying."""


def test_bind_never_calls_workos_when_the_installer_check_fails():
    """Authority first, side effects second: a refused caller must not create
    an organization or a membership. Same cheapest-first, spend-nothing-on-a-
    caller-who-proves-nothing posture as tenancy.verify_org_admin."""
```

Mock the WorkOS HTTP calls; **no test may reach the network** (Task 4 established the pattern and it was verified by re-running with proxies pointed at a dead address).

- [ ] **Step 3: Run, watch fail** — `cd api && uv run pytest tests/test_api.py tests/test_workos_client.py -k bind -v`

- [ ] **Step 4: Implement**

Order matters and is load-bearing — **prove authority before spending anything**:

1. `verify_session_claims(bearer)` → claims, else 401. A `SessionAuthNotConfigured` becomes **503**, matching `api.py:391`'s idiom.
2. `workos_client.github_user_id_for(claims["sub"])` → the identity hop.
3. Compare against `installations.installed_by_github_user_id` for the posted `installation_id`. **NULL refuses. Non-numeric `idp_id` refuses and logs.** Mismatch refuses.
4. Only now: `ensure_org` → `ensure_membership` → write `workos_org_id`.

`ensure_org` is get-or-create (`GET /organizations/external_id/gh-inst-<id>`, else `POST /organizations`) — inherently TOCTOU, so wrap the find-or-create **and** the bind write in a Postgres advisory lock keyed on the installation id. Under SQLite the lock is a no-op; **guard on dialect and say so in a comment**.

Idempotency and takeover are the same check: if the row already has a `workos_org_id`, return 204 when it equals the resolved org and **refuse** when it differs.

- [ ] **Step 5: Deploy config**

`WORKOS_API_KEY` and `WORKOS_CLIENT_ID` become Secret Manager entries with an `add-iam-policy-binding` for the api's service account in `setup()` (pattern at `gcp.sh:165-171`), plus `--set-secrets` on the **api** deploy. **Read the surrounding lines before editing** — a previous plan in this repo cited `gcp.sh:378` for `--set-secrets` when it was `:379`, and following it literally would have made gcloud resolve a Secret Manager entry named `drewjst/doug` and **fail the deploy**. Update `test_deploy_gcp.py`'s expectations rather than deleting them.

- [ ] **Step 6: Suite + lint + commit**

```bash
cd api && uv run pytest -q 2>&1 | tail -2 && uv run ruff check . && bash -n deploy/gcp.sh
```

---

### Task 6: WorkOS organization lifecycle — **MERGED INTO TASK 5**

`ensure_org` / `ensure_membership` ship inside Task 5's atomic bind, because bind
is their only caller and splitting them left Task 5 unbuildable (see Task 5's
structural note).

**What did NOT merge, and is still owed — teardown.** The design's earlier claim
that stale access ends "at next sign-in" was false: membership is additive and
nothing removes it. `installation.deleted` and `suspend` webhooks must revoke
memberships, and uninstall/reinstall mints a **new** `installation_id`,
orphaning `gh-inst-<old>` with live members. `revoke_memberships(org_id)` and
its webhook wiring are **deferred to Phase 1b** and must be listed in its plan —
they are a real hole, not a nicety, and Phase 1a's exit gate does not cover them.

---

### Task 7a: Entitlement derivation and storage (API side)

> **WHY THIS TASK EXISTS — a gap the original plan never addressed.** Verified
> against the installed SDK's README: `authkit-nextjs` exposes the provider's
> `oauthTokens` **only** inside `handleAuth`'s `onSuccess`, at sign-in.
> `withAuth()` does not return them and the session does not persist them. The
> dashboard runs on a *later* request, so the GitHub token is gone by the time
> the entitlement model needs it. The gate proved the token **works**; nobody
> checked it was still **reachable**.
>
> **DECIDED (Andrew, 2026-08-10): persist the derived scope, never the token**,
> and **do not narrow login to GitHub** — "at some point doug might have stuff
> that is more than just github". GitHub is today's *source* of entitlement,
> not an assumption baked into the session layer.

**Files:** `api/doug/entitlements.py` (new), `api/doug/store.py`, `api/doug/migrations.py`, `api/doug/api.py`, `api/tests/test_entitlements.py` (new), `api/tests/test_api.py`

**Interfaces:**
- Produces: `session_entitlements` rows; `entitlements.derive(provider, token)`; `POST /v1/sessions/entitlements`; `entitlements.is_stale(derived_at)`.

**Three properties that are the whole point:**

1. **Provider-neutral by construction.** Storage keys on the **WorkOS user id**, never a GitHub user id. Derivation dispatches on a provider name; GitHub is one deriver. Adding a second source later means adding a function, not reshaping sessions.
2. **No credential at rest.** The provider token arrives in the request, is used, and is discarded. It is never stored, never logged, never returned, and never placed in an exception message.
3. **Staleness has a hard ceiling.** `WORKOS_COOKIE_MAX_AGE` defaults to **~400 days**, so "bounded by session lifetime" is meaningless at the default. Scope carries `derived_at` and **expires after 8 hours** — matching the GitHub token TTL the gate measured, so this costs nothing in freshness versus storing the token.

**What is NOT stale, and must not be overstated in comments:** Task 3's `live_scope` still intersects every read against the live ledger, so a suspended installation or a removed repo is caught immediately. Only **GitHub-side access revocation** goes stale.

- [ ] **Step 1: Read the real migration number — do not trust this plan**

```bash
cd api && python3 -c "
import re; s=open('doug/migrations.py').read()
n=[int(m) for m in re.findall(r'^\s{4}\(\s*(\d+),', s, re.M)]
print('present:', sorted(n)); print('NEXT FREE:', max(n)+1)"
```

Task 1 took 9. **This trap has fired four times in this repo.** Use what it prints.

- [ ] **Step 2: Failing tests first**

```python
def test_entitlement_scope_is_keyed_on_the_workos_user_not_a_github_id():
    """Login is not necessarily GitHub. Keying storage on a provider's user id
    would have to be migrated the first time a second connection exists."""


def test_scope_older_than_the_ttl_is_stale():
    """WORKOS_COOKIE_MAX_AGE defaults to ~400 days, so the cookie cannot be the
    ceiling. 8h matches the measured GitHub token TTL."""


def test_derivation_with_no_github_identity_yields_no_tenants_and_does_not_raise():
    """Reachable the moment a second connection exists. A user who signed in
    without GitHub sees nothing; they must not get a 500."""


def test_selected_and_all_repository_selection_both_resolve_to_explicit_repo_ids():
    """Measured: drewjst=selected, lemahq=all. Never assume 'all'."""


def test_the_provider_token_is_never_stored_logged_or_returned():
    """Assert on the stored row, the response body, and captured stderr."""


def test_entitlements_are_written_for_the_jwt_subject_not_a_body_supplied_user():
    """The security test. A body-supplied user id would let any signed-in
    caller write another user's scope."""
```

No test may reach the network — stub the GitHub calls, following Task 4's pattern.

- [ ] **Step 3: Implement**

- Migration adds `session_entitlements`: `workos_user_id` (String(255), indexed), `installation_id` (BigInteger), `repo_ids` (TEXT holding a JSON array of ints — portable across SQLite and Postgres), `derived_at` (DateTime with timezone). **Unique on `(workos_user_id, installation_id)`**; re-deriving replaces rather than accumulates.
- `entitlements.derive(provider, token)` dispatches by provider name. The GitHub deriver calls `GET /user/installations` (keeping only Doug's `app_id`), then `GET /user/installations/{id}/repositories` per installation, **paginating**, and returns explicit repo ids for **both** `repository_selection` values. An unknown provider returns `[]` — never raises.
- `POST /v1/sessions/entitlements` authenticates with `session_auth.verify_session_claims` (**not** `resolve_session` — no org exists yet for a first-time user), takes `{"provider": str, "token": str}`, derives, and writes keyed on `claims["sub"]`. Returns 204. `SessionAuthNotConfigured` → named 503, per `api.py`'s idiom.

- [ ] **Step 4: Suite + lint + commit**

```bash
cd api && uv run pytest -q 2>&1 | tail -2 && uv run ruff check .
```

---

### Task 7b: AuthKit in `web/`

**Files:** `web/package.json`, `package-lock.json` (**repo root** — see below), `web/proxy.ts` (new), `web/app/auth/callback/route.ts` (new), `web/app/auth/actions.ts` (new), `web/app/layout.tsx`, `api/deploy/gcp.sh`, `api/tests/test_deploy_gcp.py`

**Post-merge layout facts — the plan predates `#76` and was wrong about these:**
- `web/package-lock.json` **no longer exists**. There is a **root** `package.json` with `workspaces: ["web", "console"]` and a **root** `package-lock.json`. Adding the dependency regenerates the **root** lockfile.
- `web/Dockerfile` now builds **from the repo root** and runs `npm ci` there. **No Dockerfile change is needed** — do not edit it.

**Non-negotiables, each already paid for once:**
- **Next 16.2.12 → `proxy.ts` with `authkitProxy()`.** `middleware.ts` is deprecated and Next 16 throws E900 if both exist. Read `node_modules/next/dist/docs/` after installing.
- **The matcher must EXCLUDE `/` and `/queue`.** Confirmed still true post-merge: `web()` ends with `promote_if_healthy "$WEB_SERVICE" /`, so a broken cookie password on `/` would **fail the deploy**.
- **`handleAuth({ baseURL })` is required** — Cloud Run's container hostname differs from the request host.
- **Sign-out is a POST server action** (`signOut()` inside a `'use server'` form action), never a GET route.
- **FOUR env vars, not three.** The plan omits one: `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, `WORKOS_COOKIE_PASSWORD`, **and `NEXT_PUBLIC_WORKOS_REDIRECT_URI`**.
- **Set `WORKOS_COOKIE_MAX_AGE` deliberately.** It defaults to ~400 days.
- **`onSuccess` posts the provider token to Task 7a's endpoint**, then discards it. It must **never** write it to a cookie, a log, or `localStorage`. A sign-in with no `oauthTokens` (no GitHub identity) proceeds normally with no tenants.
- **Invert, do not delete, the two web-secret pins.** `test_setup_creates_doug_web_sa_and_binds_it_no_secrets` and `test_web_deploy_carries_no_secrets` currently assert `--set-secrets` is absent from `web()`. They become "only the `WORKOS_*` secrets" — Phase 0 used exactly this inversion and a reviewer proved the pins non-vacuous by re-injecting each one.

- [ ] Steps: add the dep + regenerate the **root** lockfile; `proxy.ts` with the exclusion; callback route with `baseURL` + `onSuccess`; sign-out action; provider in layout; secrets in `setup()` and `web()`; invert both pins; `npm test` / `npm run lint` / `npm run build`; `bash -n deploy/gcp.sh`; commit.

---

### Task 8: `/install/start` and `/install/callback`

**Expanded 2026-08-10 after the security-boundary checkpoint.** The original
two-web-file scope was impossible: doug-web has no durable store in which to
burn a nonce. Andrew approved a purpose-scoped shared signing secret, an API
completion endpoint, and a durable consumed-flow table. This is not a second
account system. **WorkOS remains Doug identity; GitHub is an optional product
capability entered only through “Connect repositories.”** A WorkOS user with
no GitHub account still signs in and uses every non-GitHub surface. Binding a
GitHub installation is the narrower operation that requires a linked GitHub
identity matching the webhook-recorded installer.

**Files:**
- `api/doug/install_flow.py` (new)
- `api/doug/store.py`
- `api/doug/api.py`
- `api/tests/test_install_flow.py` (new)
- `api/tests/test_api.py`
- `api/tests/test_store.py`
- `web/lib/install-flow.ts` (new)
- `web/lib/install-flow.test.mjs` (new)
- `web/lib/node-next-loader.mjs`
- `web/app/install/start/route.ts` (new)
- `web/app/install/callback/route.ts` (new)
- `web/app/auth/callback/route.ts`
- `web/proxy.ts`
- `api/deploy/gcp.sh`
- `api/tests/test_deploy_gcp.py`

**Resolved mechanism:**
1. `DOUG_INSTALL_FLOW_SECRET` is a dedicated HMAC secret shared only by
   doug-web and doug-api. It is not `WORKOS_COOKIE_PASSWORD`, an operator/API
   token, or a provider credential. Missing or shorter-than-32-byte values are
   a named, token-safe configuration fault, not a forged-flow refusal.
   `DOUG_GITHUB_APP_SLUG=dougs-review` is a non-secret web setting.
2. `/install/start` requires a WorkOS session, creates 32 random bytes of
   nonce, and sets `doug_install_flow`: signed, HttpOnly, SameSite=Lax,
   production-Secure, path `/`, 30-minute max age. The root path is scoped to
   this one signed cookie so `/auth/callback` can recover an expired PKCE
   attempt; it does not widen AuthKit's own cookie. Its payload is
   versioned and carries `nonce`, `exp`, the WorkOS `sub`, and later the
   installation id, plus the exact boolean `pkce_retried` (initially `false`).
   Redirect to
   `https://github.com/apps/dougs-review/installations/new`; send no GitHub
   `state` parameter.
3. `/install/callback` is included in the AuthKit proxy matcher because the
   installed 4.3.1 SDK's `withAuth()` requires proxy-injected headers, but the
   route itself remains no-session tolerant for a GitHub-first install. It
   validates a positive integer installation id, puts it into the signed flow
   cookie, and, without a session, returns through AuthKit to the same
   callback. AuthKit's PKCE proof keeps its installed 600-second cap. A real
   `CallbackError` with `missing_pkce_cookie` may start a fresh PKCE attempt
   only when `/auth/callback` can verify the still-unexpired signed flow and
   its installation id. Recovery is one-shot: it refuses a flow whose signed
   `pkce_retried` is already `true`; otherwise it reseals the same nonce,
   expiry, subject, and installation id with the bit set and gives the root
   HttpOnly cookie only the remaining signed lifetime. All other errors are
   constant, non-looping failures.
4. With a session, the callback seals the current WorkOS `sub` into the flow
   and server-to-server POSTs `{installation_id, flow_token}` to the new API
   endpoint using the WorkOS access token. Neither token reaches browser JS,
   a URL, a log, or localStorage. The API route reads and JSON-parses the
   request itself so FastAPI/Pydantic cannot echo rejected token input, then
   sends its blocking database and WorkOS core through `run_in_threadpool`.
   It streams a hard maximum of 4,096 bytes before JSON parsing,
   authentication, or threadpool dispatch; byte 4,097 gets the same constant
   404 as every other malformed proof.
5. The API independently verifies the WorkOS JWT plus HMAC version,
   signature, expiry, subject, installation id, and nonce shape. It then
   reuses Task 5's exact installer-identity proof. A user with no linked
   GitHub identity gets the same non-enumerating authority refusal; the web
   renders it as an actionable **GitHub connection required for repository
   setup** state, never as a failure to hold a Doug account.
6. A new-table-only `consumed_install_flows` record stores the SHA-256 nonce
   digest, WorkOS user id, installation id, and consumed time; raw nonces are
   never stored. Before any WorkOS call, a purpose-built lock engine using the
   same `DATABASE_URL` reserves one connection (`pool_size=1`, no overflow,
   `pool_timeout=240`). The four-minute wait gives valid serialized WorkOS work
   headroom beyond SQLAlchemy's 30-second default while leaving 60 seconds in
   Cloud Run's 300-second API request envelope. Checkout exhaustion is
   translated narrowly to a constant, token-safe
   `503 install flow temporarily unavailable` before WorkOS or binding work;
   unrelated connection/programmer errors are not hidden.
   One AUTOCOMMIT connection acquires the negative nonce advisory key and then
   the positive installation key, releases them in reverse, and never touches
   the normal ledger pool. Body reads/writes and WorkOS-backed helpers continue
   to use the normal pool, avoiding nested-pool starvation. PostgreSQL provides
   cross-instance serialization; SQLite holds the lock engine's sole
   connection for bounded per-instance serialization. Under that combined
   lock, a successful bind performs idempotent WorkOS setup, then in one
   database transaction inserts consumption **before** the installation
   authority write. Both DB writes commit or roll back together. A
   same-user/same-install replay may return success but must execute no WorkOS
   or binding side effect; any mismatched replay is refused.
7. `setup_action=request` clears the flow and returns a calm waiting-for-admin
   state without calling bind. `setup_action=update` never calls bind: it
   clears the flow and sends the user through AuthKit with `prompt=consent`
   and `returnTo=/dashboard`, so Task 7b's callback re-derives GitHub scope.
8. Expand the proxy matcher to `/install/start` and `/install/callback`; `/`
   and `/queue` remain excluded. Expand the exact deploy allowlists so
   doug-web has its four AuthKit secrets plus only the flow secret, doug-api
   has the same flow secret, and the web receives the slug as plain env.

**The cookie must survive an inbox round-trip.** WorkOS refuses a first authentication until email is verified, so the user leaves for their inbox and returns — possibly minutes later, possibly in a new tab. A short redirect-scale TTL loses the pending installation and breaks first-time self-serve at the exact moment the design exists to make seamless. Size the TTL for a human checking email.

- **No `state` param.** GitHub does not document propagating `state` to a Setup URL — its docs name only `installation_id`, and warn that *"bad actors can hit this URL with a spoofed `installation_id`."* Use a signed HttpOnly cookie, which the cold-arrival path needs anyway, collapsing both entrances into one code path.
- **Nonce is single-use** — burn it in storage, not merely compare it. The earlier draft's nonce was decorative and replayable until `exp`.
- **The inbox window does not weaken PKCE.** AuthKit's verifier remains capped
  at 600 seconds; the signed 30-minute flow can authorize a fresh,
  provider-neutral sign-in attempt after the old verifier expires.
- `setup_action=update` fires whenever anyone edits repo selection: treat as re-derive-scope, **never** as bind.
- `setup_action=request` produces **no installation at all** (org admin must approve) — land on an explanatory "waiting for your admin" state, not an error.

- [ ] 1. Add failing cross-runtime HMAC fixture tests plus expiry, tamper,
      wrong-subject, wrong-installation, missing-secret, and secret-safe error
      tests; run them red.
- [ ] 2. Implement the flow codecs independently in Python and TypeScript;
      run the shared fixture and negative tests green.
- [ ] 3. Add failing store tests for atomic consume-before-bind, rollback on
      conflict, same-flow replay without a second authority write, mismatched
      replay refusal, and raw-nonce absence; run them red, implement, green.
- [ ] 4. Extract Task 5's session/authority/bind core without weakening its
      existing endpoint. Add failing caller-level API tests proving the new
      endpoint internally parses every body shape without token echo, moves
      blocking authority work off the event loop, uses every verification
      boundary, rejects streamed bodies beyond 4,096 bytes before JSON/auth,
      locks a nonce across installation ids before WorkOS without consuming a
      normal-pool connection, and that replay skips WorkOS; run red, implement,
      run the old and new bind suites green.
- [ ] 5. Add failing route tests for start, cold arrival/resume, subject
      mismatch, request, update, GitHub-identity-required, upstream outage,
      cookie attributes/TTL/root path, matcher exclusions, missing-PKCE
      recovery and its negative controls, configuration faults, token
      placement, and success redirect; run red, implement, green.
- [ ] 6. Add failing exact IAM/runtime/env deploy pins, run red, update setup
      and deploy, then run them green plus `bash -n api/deploy/gcp.sh`.
- [ ] 7. Mutate each load-bearing boundary independently: broaden matcher;
      shorten cookie to redirect scale; omit HMAC/subject/id/expiry checks;
      make nonce comparison-only; move consumption after the authority write;
      let replay call WorkOS; bind on `update` or `request`; put a token in a
      URL/browser-readable cookie; remove the global nonce lock; restore
      framework body validation; treat a missing signing secret as forged
      input; remove the signed one-shot PKCE bit; route locks through the main
      pool; restore the lock pool's default 30-second checkout or let its raw
      timeout escape; disable the 4,096-byte limit; make a tamper helper a
      no-op; grant either service an extra secret. Each named test must fail,
      then restore.
- [ ] 8. Run `cd api && uv run pytest && uv run ruff check .`, root deploy
      syntax, and `cd web && npm test && npm run lint && npm run build`; commit
      only explicit Task 8 paths.

---

### Task 9: `/dashboard` — the signed-in, session-scoped console

> **DESIGN LOCK, Andrew 2026-08-10.** WorkOS is the Doug account. GitHub is
> an optional repository connection, never a prerequisite for identity or a
> future non-repository workflow. One person may hold several GitHub App
> installations; one User or Organization installation may carry several
> repositories. Team-derived repository access is deferred, and when it lands
> it must still resolve to explicit repo ids. `lemahq` is shown, not hidden,
> with the exact label **"Lema — separate product"**. Lema and Doug PR histories
> never join unless a future, explicit repo-linking model is designed.
>
> **VISUAL LOCK, Andrew 2026-08-10.** Stay close to
> `workspace/mockups/console.html`: forensic-ledger paper surface, tight dot
> grid, sticky compact scope bar, mono controls, hairline rules, dense run
> table, and asymmetric evidence drill-down. Preserve its color semantics:
> flag `#c93a2b`, clear `#177a50`, chrome-only orange `#d1571e`, neutral
> coverage ramp, Bricolage headings, Geist body, Geist Mono data. The coverage
> ruler is the signature element. Do not turn this into rounded SaaS cards.

#### Why the original two-file task is unbuildable

The provider token exists only during AuthKit `onSuccess`. Task 7a deliberately
stores the derived scope and discards the token, so a later dashboard request
cannot call `GET /user/installations`; doing so would require persisting a live
GitHub user credential, which Andrew rejected. Task 4 also explicitly delivered
`session_auth.resolve_session` with **no route wiring**. Today `/v1/queue` and
the receipt route accept only operator/tenant keys. A page plus fetch helper has
no authenticated tenant data source.

Task 9 therefore includes the smallest API surface that makes the approved UI
truthful. It does not weaken the existing operator console routes.

#### Files

**API**

- Modify: `api/doug/session_auth.py`
- Modify: `api/doug/store.py`
- Modify: `api/doug/api.py`
- Modify: `api/tests/test_session_auth.py`
- Modify: `api/tests/test_store.py`
- Modify: `api/tests/test_api.py`

**Web**

- Create: `web/app/dashboard/page.tsx`
- Create: `web/app/dashboard/actions.ts`
- Create: `web/app/dashboard/dashboard.module.css`
- Create: `web/lib/session-api.ts`
- Create: `web/lib/session-api.test.mjs`
- Create: `web/lib/dashboard-model.ts`
- Create: `web/lib/dashboard-model.test.mjs`
- Create: `web/lib/dashboard-contract.test.mjs`

#### Authority model

1. Replace `resolve_session(bearer, claimed_repo_ids)` with
   `resolve_session(bearer)`. After verifying the JWT, it reads `sub` and
   `org_id`, maps the org to one installation, then looks up that WorkOS user's
   stored entitlement for that exact installation. The caller can no longer
   supply a repo claim. A missing, stale, empty, wrong-user, wrong-installation,
   inactive, or no-longer-live claim fails closed.
2. One browser session selects one WorkOS organization/installation. There is
   **no "tenant all"** state. Switching the tenant uses AuthKit's supported
   `switchToOrganization`/refresh-token path and a POST Server Action. The
   action re-reads the signed-in user's connection list before switching; a
   forged hidden `organization_id` is refused even though WorkOS also checks
   membership.
3. `repo=all` means all live repo ids in the selected user's stored claim for
   the selected installation. A named repo is a filter inside that set. It is
   never a selector across installations.
4. `GET /v1/sessions/connections` uses claims-only authentication because an
   orgless first session is expected. It returns only this WorkOS user's stored,
   fresh, live-intersected repository connections. Each connection carries:
   `provider=github`, installation id, WorkOS org id or null, account login,
   account type (`User` or `Organization`), and explicit repositories. Both
   GitHub `repository_selection=all` and `selected` were already normalized to
   explicit ids by Task 7a; this route never calls GitHub and never recreates an
   installation-wide sentinel.
5. An active entitlement whose installation is not yet WorkOS-bound may appear
   as `setup_required` with `organization_id=null`; it can be labelled but not
   selected. Suspended/deleted installations and removed/out-of-claim repos do
   not appear as readable connections.
6. A signed-in WorkOS user with no GitHub identity receives
   `{connections: []}`, not an authentication failure. The empty state says:
   **"You're in. Connect GitHub only when you want Doug to review
   repositories."** The CTA goes to `/install/start`.
7. Extend `/v1/queue` and `/v1/prs/{pr_number}/receipt` with an Authorization
   session branch. Credential precedence is exact operator token, then a
   non-empty WorkOS bearer, then a tenant key. A present-but-bad bearer cannot
   fall through to another credential. Existing operator behavior and uniform
   401/404 no-existence leaks stay unchanged.
8. Add separate session routes `GET /v1/sessions/runs` and
   `GET /v1/sessions/runs/{verdict_id}`. The existing `/v1/runs*` routes remain
   operator-only permanently. The store applies installation and repo-id
   predicates **inside** the history/detail query; it does not assemble another
   tenant's forensics and filter afterward. Missing and out-of-scope detail are
   the same 404/body.
9. Session list/detail models may reuse the operator run response shapes; the
   authority and route stay separate. Filters are URL state: repo, band, tier,
   low coverage, and error. Only repo is sent to the API; presentation filters
   reduce already-scoped rows locally.
10. Multi-install support must be reachable, not merely representable. A
    `Connect repositories` link to `/install/start` remains visible with zero,
    one, or many existing connections. Every `setup_required` connection is
    surfaced even while another connection is selected, with a POST Server
    Action that re-reads the signed-in user's connection list, accepts only an
    exact visible setup-required installation id, calls the authority-checked
    `/v1/installations/bind` route with the WorkOS bearer, re-reads the now-ready
    connection, and switches to its server-returned organization id. No caller
    supplies an organization id and no provider token reaches the browser.

#### Surface

```text
┌ doug  DASHBOARD ─ [tenant coldworkshq ▾] [repo all ▾] ───── account · sign out ┐
├ Queue ─ Repositories later ─ Evidence later                                    ┤
│ /runs  Verdict history for this connected space                                │
│ [all] [needs you] [cleared] [reader] [deterministic] [coverage < 50%]           │
│ score │ pull request                    │ band │ tier │ read │ outcome │ age      │
│  0.81 │ coldworkshq/coldworks #54 ...  │ ...                                  │
│ ...                                                                            │
│ /runs/1071  selected run evidence                                               │
│ timeline facts available │ coverage ruler + read + findings + outcomes          │
└─────────────────────────────────────────────────────────────────────────────────┘
```

- The selector lists several installations for one person and several repos
  inside one installation. It never offers a cross-installation aggregate.
- `Connect repositories` stays available in the dashboard chrome after the
  first connection. Setup-required rows remain visible beside a selected ready
  connection and carry an authority-checked `finish setup` POST action; they
  are never stranded as static labels.
- `lemahq` renders as its own selector entry with
  **"Lema — separate product"**. Selecting it changes the whole WorkOS tenant;
  its rows never sit beside another installation's rows.
- A User installation and an Organization installation use the same data
  shape. `account_type` supplies the honest label; no team semantics are
  inferred from an Organization row.
- The run table and evidence pane render only fields actually present. The
  reference mockup's illustrative job timeline, health numbers, or patch-char
  segment weights must not be fabricated when the session response lacks them.
- Desktop stays dense like the reference. Below 900px the table becomes a
  horizontally scrollable ledger and the evidence columns stack; controls
  remain keyboard-visible and reduced-motion disables row entrance animation.

#### TDD and verification

- [ ] 1. Write failing `session_auth` tests proving repo claims come only from
      `(JWT sub, selected installation)` storage, stale/wrong-user claims fail,
      and multiple installations for one user never union. Run red.
- [ ] 2. Implement the resolver change. Mutate it to use another user's row,
      ignore staleness, and union installations; each named test must fail.
- [ ] 3. Add failing connection-route tests for zero, one, and multiple
      installations; User and Organization accounts; multiple repos; selected
      vs all normalization; unbound label-only state; suspended/removed repos;
      and exact `lemahq` separation data. Implement store projection and route.
- [ ] 4. Add failing caller-level queue/receipt tests for one selected org,
      two repos, one-repo user scope, orgless, stale, suspended, forged, and
      cross-tenant existence parity. Implement the session branches.
- [ ] 5. Add failing session-run list/detail tests. Pin query-level
      installation/repo predicates, uniform 404, no `tenant all`, and unchanged
      refusal on operator `/v1/runs*`. Implement.
- [ ] 6. Add `session-api.ts` tests proving `cache: "no-store"`, WorkOS bearer
      placement, no fixture fallback, bounded timeout, exact shape rejection,
      and token-safe errors. It must not import or reuse `web/lib/api.ts`.
- [ ] 7. Add dashboard-model and source-contract tests for URL filters,
      percentage/ruler honesty, multi-installation/multi-repo selectors,
      POST-only switch/sign-out, provider-neutral empty copy, exact Lema label,
      absence of a cross-tenant `all` option, always-reachable new connection,
      and recovery of an exact visible setup-required installation without a
      caller-supplied org id. Run red, implement, green.
- [ ] 8. Render the console-derived surface. Run `npm test`, lint, build, then
      use the local browser at desktop and mobile widths. Compare screenshots
      against `workspace/mockups/console.html`; fix overflow, hierarchy, focus,
      empty, one-connection, multiple-connection, selected-run, and dark-theme
      failures. The dashboard itself remains the reference's light forensic
      ledger; no forced dark conversion.
- [ ] 9. Mutation proofs: caller-supplied repo ids; another user's entitlement;
      stale acceptance; `tenant all`; cross-installation history; detail
      post-filtering; global tenant cache; GET state change; hidden `lemahq`;
      mixed Lema/Doug rows; and fixture fallback. Restore after each.
- [ ] 10. Run `cd api && uv run pytest && uv run ruff check .`, root deploy
      syntax, and `cd web && npm test && npm run lint && npm run build`; commit
      only explicit Task 9 paths.

---

### Task 10: The exit gate

**Files:**

- `api/deploy/prove-session-isolation.sh` (new)
- `api/tests/test_prove_session_isolation_script.py` (new)

A sibling to `prove-isolation.sh`, executable against production. That older
script earned its place by catching pepper-newline and collected-client defects
that unit tests did not. This task builds and reviews the proof executable; it
does **not** deploy it or run it against production. Deployment, cold install,
WorkOS/GitHub setup, suspension, the model-spend authorization probe, the bind
authorization probe, and the proof run remain production mutations behind
Andrew's explicit confirmation.

#### Authority and fixtures

The script accepts short-lived WorkOS access tokens, never cookies or provider
tokens, through environment variables. It never prints them or writes them to
disk. All tenant requests send only `Authorization: Bearer ...`; using
`X-Doug-Token` here would test the old installation-key path instead of the
front door.

Required inputs, validated before the first HTTP request:

```
DOUG_URL                         https API origin, no trailing slash
A_SESSION_JWT                   one user with organization A selected
A_INSTALLATION_ID               A's live installation
B_SESSION_JWT                   the same user with organization B selected
B_INSTALLATION_ID               B's live installation; different from A
ONE_REPO_SESSION_JWT            another A member, explicit one-repo scope
ONE_REPO_ALLOWED                full name with at least one stored run
ONE_REPO_FORBIDDEN              other A repo with at least one stored run
ORGLESS_SESSION_JWT             valid WorkOS session with no org_id
EXPIRED_SESSION_JWT             genuinely expired WorkOS access token
UNMAPPED_ORG_SESSION_JWT        valid org_id with no Doug installation mapping
READ_ONLY_SESSION_JWT           can discover an active unbound installation,
                                 but is not its recorded installer
READ_ONLY_INSTALLATION_ID       that active unbound installation
DOUG_SESSION_PROOF_ACK          literal acknowledgement of the model-spend and
                                 disposable-bind probes for that installation
```

A is deliberately the multi-repo fixture: its token must see both
`ONE_REPO_ALLOWED` and `ONE_REPO_FORBIDDEN`. `ONE_REPO_SESSION_JWT` must have a
different `sub`, the same `org_id`, and an entitlement containing only the
allowed repo. A and B must decode to the same non-empty `sub` and different
non-empty `org_id` claims; the API, not the local decode, remains the authority
because both JWTs must also pass server verification and return scoped rows.

`READ_ONLY_INSTALLATION_ID` is a **disposable production fixture** and must
appear in the read-only user's claims-only
`/v1/sessions/connections` response as `setup_required`, with at least one
repository. That proves visibility before the refused bind and proves no Doug
binding occurred afterward. A pre-bound or empty connection is a fixture
error, never a pass. If the authorization boundary is broken, the probe may
create WorkOS state or bind this installation before it detects the failure;
there is no honest read-only way to test a mutating endpoint's denial. The
fixture therefore needs an operator-owned cleanup plan, and the script requires
the literal acknowledgement
`I ACCEPT SCORE SPEND AND DISPOSABLE BIND ${READ_ONLY_INSTALLATION_ID}` before
the first request. This acknowledgement does not replace Andrew's separate
approval to run against production.

#### Script mechanics and safety

- Use `set -u` plus `pipefail`, `curl`, `jq`, one `mktemp` response file, and an
  exact trap that removes only that file. Do not use a shared fixed `/tmp` path.
- Validate HTTPS origin, positive integer ids, JWT three-segment shape, required
  commands, distinct A/B installation ids, and every required value before any
  request. The test harness may still use an `https://*.test` origin.
- A request helper uses explicit connection and total timeouts and captures
  status/body without `set -e` aborting the remaining proof. Diagnostics print
  gate/status/reason only, never response bodies, headers, tokens, or
  caller-supplied secrets.
- Each numbered contract below contributes exactly one aggregate PASS/FAIL, so
  a successful run ends `9 passed, 0 failed`. Subchecks are not counted as
  extra gates. Any failure exits nonzero after safe restoration handling.
- The script never calls GitHub, WorkOS, a database, or a deployment API
  directly. It is nevertheless a **controlled-adversarial production probe**,
  not read-only: Gate 8 sends a valid body to the model-spending route, Gate 9
  calls bind expecting denial, and Gate 5 pauses for a human to make and later
  reverse the GitHub App suspension. The prompts require literal
  `SUSPENDED ${A_INSTALLATION_ID}` and `RESTORED ${A_INSTALLATION_ID}`
  confirmations. No callback or arbitrary shell hook may be accepted.
- Before typing the suspension confirmation, the operator must wait for the
  GitHub `installation.suspend` delivery to return 202. The script then makes
  exactly the next API read. Before the restore confirmation, the operator must
  wait for the `installation.unsuspend` delivery to return 202. The final 200,
  non-empty read is cleanup evidence and guards against an expired token being
  mistaken for isolation. Confirmation typos are retried. Once suspension is
  possible (before the script first instructs the human to act), conservatively
  arm restoration-required state. EOF exits immediately with that warning;
  INT/TERM do the same. Normal completion is impossible until restoration is
  both confirmed and observed as a non-empty A-only 200; failed restore checks
  loop back to the restore prompt. The pre-mutation warning must state the
  inherent limit: SIGKILL, terminal loss, or operator disappearance cannot be
  repaired by this shell process and require manual recovery.

#### Nine gates

1. `GET /v1/sessions/runs?repo=all` with A returns 200, a non-empty list, and
   every row names only `A_INSTALLATION_ID`.
2. The same read with B returns 200, a non-empty list, and only
   `B_INSTALLATION_ID`; A/B ids differ while decoded `sub` matches and `org_id`
   differs. No display-name heuristic is accepted.
3. A can read a non-empty `ONE_REPO_FORBIDDEN` result. The one-repo member's
   `repo=all` and explicit allowed result are non-empty and contain only A's
   installation plus `ONE_REPO_ALLOWED`; its explicit forbidden request is the
   same status **and canonical JSON body** as an absent repo. The member has A's
   org claim and a different user claim.
4. The orgless token proves it is structurally valid by receiving 200 from the
   claims-only connection discovery, then receives 401 on session run data.
5. A succeeds immediately before suspension. After the exact human confirmation
   described above, the next request is 401. After the exact restore
   confirmation, the same token again receives 200 with non-empty A-only rows.
6. A mechanically tampered copy of A's token and the independently captured
   expired token each receive 401. Tampering changes a significant signature
   character, not an unused base64 padding bit. Preflight requires the expired
   token to name A's same `sub` and `org_id` and carry a numeric `exp` earlier
   than the current time; an arbitrary three-segment junk value is not an
   expiration fixture.
7. The unmapped-org token receives 200 from claims-only connection discovery and
   401 from session run data. This distinguishes a verified-but-unmapped
   session from junk.
8. A's valid session receives only 401/404 from every current operator-only
   route: `POST /v1/score/read` with a valid request body, `GET /v1/runs`,
   `GET /v1/runs/1`, `GET /v1/health`, `GET /v1/jobs`, and
   `GET /v1/patterns`. A source-inventory test derives the `_operator_only`
   callers from `api.py` and fails when this list drifts.
9. Before bind, the read-only connection is visible, non-empty, and
   `setup_required`. `POST /v1/installations/bind` with exactly its installation
   id receives 404. The same connection remains `setup_required` afterward.

#### TDD and verification

- [ ] 1. Write a subprocess test harness that places a deterministic fake
      `curl` first on `PATH`, generates structurally valid dummy JWTs, feeds the
      two exact suspend/restore confirmations on stdin, and models the nine
      production boundaries. Run it red because the script does not exist.
- [ ] 2. Add a success test requiring exit 0, exactly nine PASS lines,
      `9 passed, 0 failed`, no token value in output, a suspend-before-refuse
      request and a restore-after-refuse request.
- [ ] 3. Parameterize nine hostile fake-server modes: A row leak, B row leak,
      one-repo leak, orgless data success, suspended next-read success,
      invalid-token success (both tampered and expired are wrongly accepted),
      unmapped-org success, one operator-route success, and bind success/state
      mutation. Each must make only its named gate fail and the script exit
      nonzero.
- [ ] 4. Add preflight tests proving a missing/malformed input makes zero HTTP
      calls, including wrong acknowledgement and wrong orgless/unmapped/expired
      claims. Add an output-safety test proving success and failure logs contain
      none of the supplied token strings or response bodies.
- [ ] 5. Parse `api.py` with Python AST in the inventory test. Collect decorated
      route functions whose body calls `_operator_only`; assert the exact
      method/path set equals the script's six-entry operator list. Public,
      dual-authority, GitHub-management, and session routes must not appear.
- [ ] 6. Implement the shell proof with exactly the mechanics and gates above.
      Add tests for forbidden/absent body equality, bounded curl arguments,
      confirmation typos, delayed restoration, EOF/signal restoration warnings,
      pre-confirmation EOF/INT/TERM, and the rule that no successful exit is
      possible while the fake remains suspended. Run `bash -n` and the focused
      test file green.
- [ ] 7. Mutation proof: independently weaken each numbered gate's decisive
      predicate/accepted status in the script, clear caches as relevant, and
      observe the corresponding hostile-mode test fail before restoring it.
      Do not count a fake-server violation test alone as mutation evidence.
- [ ] 8. Run `cd api && uv run pytest -q && uv run ruff check .`,
      `bash -n deploy/prove-session-isolation.sh`, root deploy syntax,
      `cd web && npm test && npm run lint && npm run build`, and
      `git diff --check`. Commit only the two Task 10 files after an independent
      review. Do not run the script against production in this task.

---

## Phase exit criteria

- [ ] `uv run pytest` green; `uv run ruff check .` clean; `bash -n deploy/gcp.sh` clean.
- [ ] `npm test` (reporting **>0 tests**), `npm run lint`, `npm run build` all pass.
- [ ] **`coldworkshq/coldworks` installed cold through the front door and bound** — an org install on a private repo, with no prior Doug installation. This is the only setup that tests the path a stranger takes.
- [ ] The orgless path exercised for real: the operator holds two installations, so the first sign-in has no `org_id`.
- [ ] `prove-session-isolation.sh` 9/9 against prod.
- [ ] A first-time user completing email verification still lands bound — the inbox round-trip did not lose the pending installation.

## Honest status of this plan — read before executing

**UPDATE 2026-08-09, during execution.** Tasks 1–4 are **built and reviewed**
(`50fc60b`, `9f3fac9`, `d523b47`, `6509b04`). Task 5 has been **rewritten and
expanded** to execution standard, absorbing Task 6 (see its structural note);
Task 6's teardown half is deferred to Phase 1b and recorded there. **Tasks 7–10
remain specified but not stepped** and are being expanded one at a time, just
before execution, as the section below instructs.

Four defects were found in Tasks 1–5 *before* writing code, three of which
would have shipped bugs: the `ctx is None` sentinel is only an operator test at
one of its three cited sites (replacing the other two would 500 on an
unresolvable token); routing `resolve()` through `live_scope` would have added
two DB queries per authenticated call; `live_scope` returning every repo on a
`None` claim was MT1 reintroduced; and Task 5 consumed an org id only Task 6
produced. The section below predicted this for 6–10. It was true of 1–5 too.

**Tasks 1–5 are execution-ready**: exact files, real code, runnable verification
commands. **Tasks 7–10 are specified but not stepped** — they state the
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
