# Tenant API keys — repo-selection model

**Date:** 2026-08-04 · **Status:** approved in-session (Andrew), pending final spec review
**Supersedes:** the single-token storage model of PR #48 (`installations.token_hash`); the
dispense *endpoint* and the two-token-class decision survive.
**Closes:** MT1, MT2, MT4, MT5. **Out of scope:** MT0 (operational), MT3 (worker scaling).

## 1. Context and problem

Doug's entire tenant-credential schema is one nullable column: `installations.token_hash`
(`api/doug/store.py:186`, on main since PR #48). One opaque token per
installation, bare unsalted sha256, rotate-by-remint, no scopes, no expiry, no
attribution, no record that a mint happened. ROADMAP § MT's open design question
(ROADMAP.md:332-341) already named the consequence: MT1, MT2 and MT5 are symptoms of that
shape, not independent bugs.

- **MT1** — `tenancy.verify_admin` proves admin on **one repo** (`tenancy.py:102-109`);
  `tenancy.mint` writes a token scoped to the **whole installation**
  (`tenancy.py:44-48`). On an org install, admin on 1 of N repos reads all N repos' PR
  titles, authors and reader rationales, and silently rotates the org's live token.
- **MT2** — `tenancy.resolve` matches `token_hash` and never reads `installations.state`;
  the uninstall webhook clears the repo list and leaves the hash. Uninstalling — the
  tenant-facing revocation gesture — revokes nothing.
- **MT5** — dispense is public and unthrottled; every re-mint destroys the live token, so
  repeated calls are a denial of service against the tenant's own integration.
- **MT4** (adjacent) — `?repo=` authorization reads `installation_repos.full_name`
  (annotated *display only*), row filtering reads `verdicts.installation_id`. Fails
  closed, but the two sources can disagree.

Evaluated before designing (per the 2026-08-04 decision): lema's `lema_live_` API-key
module (its ADR-0060, recoverable via
`git show 868de1c7^:docs/adr/0060-api-key-system-for-hosted-access.md` in lemahq/lema)
and industry practice — Sonar, Codecov, Sentry, Snyk, GitHub fine-grained PATs, GitHub's
token-format engineering post. Doug and lema stay separate products; this borrows
patterns, not code or coupling.

## 2. Decision

Replace the single-column token with an **`installation_tokens` table**: multiple keys
per installation, each bound to `installation_id` with a **repo selection** —
`all` or `selected` (+ junction table of repo **ids**) — plus scopes, expiry, soft
revocation, and mint attribution. Mint authority must cover the selection: org-admin
proof mints `all`; per-repo admin proof mints `selected`. At resolve time the key's
frozen selection is intersected against the **live ledger** (installation state, repo
states), so uninstall and repo-removal fail closed structurally.

This is the GitHub fine-grained-PAT shape (resource owner + all/selected repos +
permissions), which Sonar (project vs global analysis tokens) and Codecov (repo vs
org upload tokens) approximate at its two endpoints.

### Why the key is not user-bound

lema binds keys to `(org, user)` and re-derives the owner's live role scopes on every
request. Doug cannot copy this — there are no user accounts; the only identity proof is
a GitHub PAT presented at mint. The industry says this is fine: Sentry redesigned *away*
from user-bound CI tokens to organization tokens precisely because keys died when their
owner left. `minted_by` is recorded for audit and is **never authority**. Doug's
fails-closed analog of lema's live-role check is the live-ledger intersection (§7).

### Rejected alternatives

- **Two-class model** (installation-wide XOR single repo via nullable `github_repo_id`)
  — less code now; "these 5 repos" later means a schema migration or key sprawl. The
  migration is free *today* (prod has zero dispensed tokens; dispense 404s until MT0);
  it is never free again.
- **Lifecycle-only** (keys table but installation-wide scope, org-admin mint) — closes
  MT1 by raising the mint bar but leaves blast radius org-wide and repo teams unable to
  self-serve.
- **Per-repo only** — tightest blast radius, but the primary v1 consumer (a design
  partner reading their org's queue, later MCP) would need N keys per org.
- **Fixing MT1/MT2/MT5 as three patches on the single-column model** — the roadmap's
  open design question already argued this down; each patch re-implements a slice of a
  keys table.
- **WorkOS-minted tokens / DIY OAuth** — killed in design-lock.md:32 (no dashboard
  exists); unchanged here.

## 3. Schema (migration 006)

Follows existing conventions: no cross-table FKs, ids are authority, names are display.

**`installation_tokens`**

| column | type | notes |
|---|---|---|
| `id` | PK | |
| `installation_id` | BIGINT NOT NULL, indexed | joins `installations.installation_id` by convention |
| `token_lookup` | TEXT NOT NULL UNIQUE | 8 base62 chars, plaintext — O(1) btree resolve; safe in logs and list output |
| `token_hash` | TEXT NOT NULL | hex HMAC-SHA256(secret, pepper) |
| `hash_version` | SMALLINT NOT NULL DEFAULT 1 | selects the pepper; unknown version fails closed |
| `last4` | VARCHAR(4) NOT NULL | masked display |
| `label` | VARCHAR(100) | human name ("ci-grafana", "org-dashboard"); optional |
| `repo_selection` | VARCHAR(10) NOT NULL | `all` \| `selected` |
| `scopes` | JSON NOT NULL | v1 always `["queue:read"]`; receipts/MCP land as data, not migrations |
| `minted_by` | VARCHAR(200) NOT NULL | GitHub login of the PAT holder at mint; audit only |
| `created_at` | TIMESTAMP NOT NULL | `mint` finally records that a mint happened |
| `expires_at` | TIMESTAMP NULL | NULL = durable |
| `revoked_at` | TIMESTAMP NULL | soft revoke, `COALESCE`-idempotent |
| `last_used_at` | TIMESTAMP NULL | best-effort, throttled ≥60s between writes, never on the failure path |

**`installation_token_repos`** — `token_id` (indexed), `github_repo_id BIGINT NOT NULL`,
`UNIQUE(token_id, github_repo_id)`. Rows exist only for `selected` keys. Repo **ids**,
never names.

**Dropped:** `installations.token_hash` (column removed from the model; migration 006
drops it where present). Safe because no dispensed token exists in any environment —
MT0 means prod dispense has 404'd since the feature shipped.

## 4. Token format and hashing

`doug_live_<lookup>_<secret><crc>`

- `lookup` — 8 base62 chars, `secrets`-random, stored plaintext.
- `secret` — 43 base62 chars (256 bits), never stored.
- `crc` — CRC32(IEEE) over `lookup||secret`, base62, fixed 6 chars, zero-padded.
  Validated offline before any DB hit. Scanner-noise filter only; zero security weight.
- The `doug_live_` literal is hardcoded and greppable (secret-scanning per GitHub's
  token-format design). `doug_test_` is reserved and **rejected** by parse today so it
  can never fall through to another verifier. Legacy `doug_` tokens (PR #48 format) are
  rejected by the prefix check; none exist outside tests.

**Hashing** — HMAC-SHA256 with a server-side pepper, not bare sha256 (today's scheme)
and not bcrypt/argon2 (256-bit random secrets get security from entropy; a KDF only
taxes the hot path). The pepper exists because key hashes are effectively unsalted — a
DB-only breach must yield unusable hashes.

- `DOUG_TOKEN_PEPPER` — base64, decoded to exactly 32 bytes at startup, Secret
  Manager-backed (wired in `gcp.sh` alongside `doug-api-token`).
- **Rotation is rolling, not a flag-day** (lema's accepted single-pepper flag-day is
  the one part of its design we refuse): `hash_version` n verifies against
  `DOUG_TOKEN_PEPPER_V<n>` (`DOUG_TOKEN_PEPPER` ≡ V1); new mints always use the highest
  configured version; old keys verify under theirs until re-minted.
- Pepper unset → mint **and** resolve both 503. The system can never mint what it
  cannot verify.

## 5. Mint — `POST /v1/installations/token`

Stays public (no Doug token) and PAT-proof, per PR #48's design. Body:

```json
{"selection": "selected", "repos": ["acme/a", "acme/b"],
 "label": "ci-a-and-b", "expires_in_days": 90}
{"selection": "all", "owner": "acme", "label": "org-dashboard"}
```

`expires_in_days` 0/omitted = durable; range 0–366. Legacy body `{"repo": "acme/a"}`
is accepted as `{"selection": "selected", "repos": ["acme/a"]}` until PR #48's callers
are updated, then removed.

**Proof must cover the selection.** Caller-quota-first ordering is preserved on every
path — the PAT calls spend the caller's GitHub quota; the single app-JWT installation
lookup happens only after proof succeeds (the 2026-08-02 quota lesson; pinned by the
existing `test_non_admin_pat_never_spends_dougs_github_quota` and kept pinned).

- `selected` — for each repo (cap: 20/request): existing `verify_admin` check — PAT
  `repos.get` must show `permissions.admin`. All repos must resolve to the **same**
  installation, else 404.
- `all` — `installations.account_type == "Organization"`: PAT
  `GET /user/memberships/orgs/{owner}` must return `role: admin`. `account_type ==
  "User"`: PAT `GET /user` login must equal `owner`. Then the app-JWT
  `get_org_installation`/`get_user_installation` lookup.

Every failure is a uniform 404 (existing posture: admin-on-missing-repo and
no-permission are indistinguishable). `minted_by` comes from the PAT's `GET /user`
(caller quota). Response returns the full token **exactly once**:
`{token, token_id, installation_id, selection, repos, last4, expires_at}`. Handlers log
`{token_id, lookup, last4, installation_id, minted_by}` and never the token; a
deny-log test pins this.

**Mint appends; it never rotates.** A second mint is a second row. This alone deletes
the rotate-as-DoS half of MT5 and unblocks the CI/MCP key-sharing limit PR #48 recorded.

**Rate limiting (MT5's other half):** a per-installation daily mint counter in Postgres
(default 30/day), **fail-open** — a counter error logs and allows; availability of mint
is worth more than the cap. Anonymous callers cost Doug zero GitHub calls (PAT proof
fails first); callers who pass proof are legitimate admins bounded by the cap. No
dependency on `installation_repos` names — MT5 closes without touching MT4.

## 6. Resolve — the hot path

`tenancy.resolve(token)` returns a context, not a bare id:
`TokenContext{installation_id, token_id, scopes, repo_ids}` where `repo_ids` is `None`
for `all`-keys (meaning: filter by installation only) or the effective id set for
`selected`-keys.

Chain, cheapest first, uniform failure (401 at the route; the real reason logs at
debug):

1. Prefix check (`doug_live_`) — zero I/O, short-circuits non-key tokens.
2. Offline parse + CRC — zero I/O.
3. One indexed SELECT by `token_lookup`, joined to `installations.state`.
   **Lookup miss performs a dummy HMAC** against a fixed sentinel so a miss is
   timing-indistinguishable from a wrong secret.
4. `hmac.compare_digest` of HMAC-SHA256(secret, pepper[`hash_version`]).
5. `revoked_at IS NULL`, `expires_at` in the future (or NULL).
6. `installations.state == 'active'` — uninstalled and suspended installations fail
   here. **This is MT2, closed structurally.**
7. `selected` keys: effective repos = frozen `installation_token_repos` ∩ live
   `installation_repos` where `state == 'active'`. Empty intersection → fail. A repo
   removed from the installation vanishes from every key that named it, next request.

`last_used_at` updates after success, throttled, best-effort.

### Enforcement at `/v1/queue` (and every future tenant surface)

Row filtering becomes id-based end to end: `verdicts.installation_id ==
ctx.installation_id` AND, for `selected` keys, `verdicts.github_repo_id IN
ctx.repo_ids` — inside the grouped `max(id)` subquery like the existing installation
filter (`store.py:1197-1205`). The `?repo=` parameter resolves through **active
`installation_repos` rows to a `github_repo_id`** (404 if absent or outside
`ctx.repo_ids`), and filtering uses that id. `installation_repos` becomes the single
source of truth for repo authorization; `verdicts.repo` and
`installation_repos.full_name` are display-only everywhere. **This is MT4, closed as a
side effect.** Scope check: route requires `queue:read` ∈ `ctx.scopes` (trivially true
in v1; the gate exists so receipts/MCP get route-level scope checks for free).

## 7. Lifecycle

- **`GET /v1/installations/tokens`** — masked list (`token_id, lookup, label, last4,
  selection, repos, scopes, minted_by, created_at, expires_at, revoked_at,
  last_used_at`). Never a secret. Proof: org-admin (or account owner), same PAT
  mechanics as mint-`all`.
- **`DELETE /v1/installations/token/{token_id}`** — soft revoke, idempotent
  (`COALESCE(revoked_at, NOW())`). Proof: org-admin revokes anything; repo-admin proof
  revokes a `selected` key iff the proven repos cover the key's selection. Ownership
  check inside the WHERE — a foreign `token_id` is indistinguishable from a missing one
  (404).
- **Management endpoints never accept `X-Doug-Token`** — only PAT proof. lema's
  "keys cannot manage keys" (a leak never outruns revocation) holds by construction.
- **Uninstall webhook** (`deleted` branch of `_record_installation`, `api.py:757-764`)
  additionally bulk-sets `revoked_at` on the installation's keys — belt-and-braces on
  top of the live state check, and it leaves an audit trail. Suspend/unsuspend requires
  no key churn; step 6 of resolve handles it, and unsuspending restores service.
- **No rotate endpoint.** Rotation = mint new + revoke old (lema, Sonar, Snyk all
  landed here). Multiple live keys make this zero-downtime.
- **Break-glass:** operator revocation is a documented SQL one-liner in the runbook
  (`UPDATE installation_tokens SET revoked_at = NOW() WHERE installation_id = …`), not
  a new admin API.

## 8. What does not change

- `DOUG_API_TOKEN` remains the unscoped operator credential; `_operator_only` and
  `/v1/queue`'s dual-class check keep their shape (PR #48's settled two-class
  decision). If it leaks, everything still leaks — unchanged, acknowledged.
- `/v1/patterns` stays operator-only permanently (licensing; design-lock.md:71).
- `/v1/review`'s inline operator check (401-vs-404 divergence from `_operator_only`)
  is pre-existing cleanup, noted, not touched here.
- `/v1/score` stays unauthenticated; webhooks stay HMAC; `/openapi.json` deploy-gate
  hardening stays deferred (needs a replacement probe first).
- MT0 stays operational: redeliver the `installation` webhook. Every prod verification
  of this design depends on it.
- MT3 (reconcile fan-out) is a worker-scaling problem, untouched by credentials.

## 9. MT coverage

| Item | Status under this design |
|---|---|
| MT0 | Unchanged — operational fix; prerequisite for prod verification |
| MT1 | **Closed** — proof covers selection; a repo-admin can no longer mint installation-wide |
| MT2 | **Closed structurally** — resolve reads live `installations.state`; uninstall also bulk-revokes |
| MT3 | Out of scope |
| MT4 | **Closed** — authorization and filtering both keyed on `github_repo_id` via active `installation_repos` |
| MT5 | **Closed** — mint appends (no rotation DoS); PAT-first proof (no anonymous quota drain); fail-open daily mint cap |

## 10. Testing

Pins, beyond routine coverage:

- Resolve chain order and uniformity: revoked / expired / suspended / uninstalled /
  repo-removed / empty-intersection all fail identically at the route.
- Timing: dummy HMAC runs on lookup miss.
- Mint appends — a second mint never invalidates the first key.
- Caller-quota-first on **both** mint paths (extend the two existing quota tests to the
  `all` path).
- Proof coverage: repo-admin + `selection: all` → 404; org **member** (non-admin) +
  `all` → 404; `selected` repos spanning two installations → 404.
- MT4 consistency: the unfiltered queue never returns a row for a repo that `?repo=`
  would 404.
- Deny-log: mint/list handlers never log the token or secret.
- Cap fail-open: counter table unavailable → mint still succeeds, error logged.
- The REVIEWING.md § "A table only a webhook populates" lesson: a dispense-against-
  empty-ledger test (404s cleanly), plus a **startup drift warning** when
  `installations` is empty while `verdicts` references installation ids — the next
  MT0-class state becomes a loud log line instead of a silent structural no-op.

## 11. Migration and ops

- Migration 006: create `installation_tokens` + `installation_token_repos`, drop
  `installations.token_hash`. Additive-then-drop; no data migrates (no dispensed tokens
  exist anywhere — the free window MT0 created).
- Migration style: follow migrations 001–005's guard conventions; note the PR #48
  lesson — `ALTER TABLE` on a missing table raises `no such table`, which `_SATISFIED`
  does not swallow. Guards must tolerate fresh databases where `create_all()` already
  built the final shape.
- Ops: provision `doug-token-pepper` in Secret Manager; bind as `DOUG_TOKEN_PEPPER` in
  `gcp.sh` (api service only — doug-web keeps using the operator token). Document
  break-glass SQL and the rolling pepper-rotation procedure in the runbook.
- Rollout: keys are net-new; nothing existing breaks if the feature deploys dark.

## 12. Sequencing

1. **PR #48 merged** (2026-08-04, merge commit `ed5aa3e`) — this spec's implementation
   starts from that baseline; the branch carrying this spec is rebased on it.
2. Slice A — schema + format + mint/resolve swap (closes MT1, MT2, MT5).
3. Slice B — list/revoke endpoints + uninstall bulk-revoke.
4. Slice C — queue id-filtering + MT4 unification + drift warning.

Each slice lands green independently; A is the only one that must precede an outside
org install (with MT0 done and, per ROADMAP's exit gate, a second installation proven
to read only its own rows against the real ledger).

## 13. Defaults and tunables

| Knob | v1 default | Notes |
|---|---|---|
| Repos per `selected` mint | 20 | Bounds PAT-side GitHub calls per request |
| Mints per installation per day | 30 | Postgres counter, fail-open |
| `expires_in_days` | 0 (durable) | Range 0–366; no dashboard yet, so expiry-by-default would strand partners |
| Scope vocabulary | `queue:read` | Receipts/MCP add values, not columns |
| Pepper | 32 bytes, base64 env | `hash_version` → `DOUG_TOKEN_PEPPER_V<n>`, rolling rotation |
