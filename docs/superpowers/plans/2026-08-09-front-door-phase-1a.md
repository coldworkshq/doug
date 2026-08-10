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
   same `DATABASE_URL` reserves one connection (`pool_size=1`, no overflow).
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
      pool; disable the 4,096-byte limit; make a tamper helper a no-op; grant
      either service an extra secret. Each named test must fail, then restore.
- [ ] 8. Run `cd api && uv run pytest && uv run ruff check .`, root deploy
      syntax, and `cd web && npm test && npm run lint && npm run build`; commit
      only explicit Task 8 paths.

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
