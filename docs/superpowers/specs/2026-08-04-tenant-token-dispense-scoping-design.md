# Per-installation token dispense + tenant-scoped reads

**Status:** design approved (Andrew, 2026-08-04) · **Milestone:** M2, final item
**Closes:** ROADMAP.md:212 — "Per-installation token dispense endpoint
(GitHub-token-verified); scoped `/v1/queue` + receipt reads; cross-tenant read
attempt → 404 (test pinned)"

M2's exit gate is *safe to point at strangers*, and its remaining clause is "no
cross-tenant read". Today there is exactly one credential — a shared
`DOUG_API_TOKEN` — and `/v1/queue`'s own docstring admits what that means:
"the shared token stops anonymous reads, it does not separate tenants."

---

## Two token classes, not one replaced

`DOUG_API_TOKEN` **survives unchanged** as an operator credential. Dispensed
per-installation tokens are a second, narrower class.

| | Operator token | Tenant token |
|---|---|---|
| Source | `DOUG_API_TOKEN` secret | dispensed, hashed into `installations.token_hash` |
| Scope | none — sees every row | exactly one `installation_id` |
| Reaches | every endpoint | `/v1/queue` only (M3 receipts later) |
| Consumers | `doug-web`, operator curl, the deploy probe | tenant API access, later the MCP garden |

**Why not one scoped class for everyone.** Three reasons, in order of weight:

1. **It would regress the live soak.** `comparison_reviews` (`store.py:1285`)
   selects CI rows by `installation_id IS NULL AND github_repo_id IS NULL`.
   Scope everything by `installation_id` and the CI half of every comparison
   disappears — during the soak that exists to watch it.
2. **`doug-web` has no login.** `web/lib/api.ts:114,161` sends one server-side
   `process.env.DOUG_API_TOKEN`. There is no notion of who is looking. The
   tenant dashboard is an M6 gated track (">3 tenants or first tenant ask"),
   and `design-lock.md:65` already cut the tenant browser page while keeping
   the token mint.
3. Tenants have no UI to break, because they get API access and nothing else.

**The limit this leaves, stated rather than implied:** `DOUG_API_TOKEN` remains
a superuser credential. If it leaks, everything leaks. That is true today and
this work does not change it. M2's gate is "no cross-tenant read" — an operator
is not a tenant, so the gate closes honestly, but "scoped reads" must not be
read as more than ships.

---

## Which endpoints tenant tokens reach

**`/v1/queue` only.** The other three stay operator-only, and two of them
permanently:

- **`/v1/patterns` (`api.py:554`) — operator-only forever.** It computes
  precision over the **research corpus**, and `design-lock.md:71` is a
  licensing constraint, not a scoping preference: *"Nothing derived from the
  research corpus is servable across tenants (rationales quote getsentry/grafana
  source verbatim)."* There is no future version of this endpoint that becomes a
  tenant surface. Scoped per-tenant it would also be a precision figure computed
  over a handful of PRs — a number too small to mean anything, published from
  the endpoint whose docstring calls it "the unpublished half of the evidence
  base."
- **`/v1/comparisons` (`api.py:1135`) — operator-only.** It compares App vs CI.
  Tenants have no CI path; `doug-review.yml` is this repo's own dogfood workflow
  (ADR-0008). It has nothing to show a tenant, and M1 Task 9 eventually deletes
  half its inputs.
- **`/v1/score/read` (`api.py:355`) — operator-only.** The post-deploy
  credential probe. Operator by definition.

This still closes the gate: there is no endpoint at which a tenant token can
read another tenant's data, because there is one endpoint a tenant token opens
at all.

### What the future garden inherits

`design-lock.md:65` cut the tenant browser page and kept the token mint with
the reason attached: *"token mint survives — its consumers are the API and
later MCP."* `design-lock.md:31` kills the alternatives by name — *"WorkOS-minted
tokens (no dashboard exists); DIY OAuth."* So this token is the garden's auth
mechanism and no second one is coming.

The garden is a **separate Cloud Run service on the same image** (`:31`),
v1.5, serving adjudicated history with citations under a min-n floor — different
data from `/v1/patterns`, different store, different service. Three consequences
land on *this* design, all cheap now and expensive later:

1. **`doug/tenancy.py` is a module, not inline code in `api.py`.** A second
   service must verify a token without importing the FastAPI app. (It also
   keeps `api.py`, already 1158 lines, from absorbing another subsystem.)
2. **Verification is a DB read of `installations.token_hash`**, so a second
   service sharing the same Postgres authenticates with no new plumbing.
3. **The token resolves to `installation_id` and nothing broader** — `:71`'s
   no-cross-tenant-garden rule needs exactly the scope value we already mint.

**Not building a garden endpoint now.** Its trigger is "adjudicated rows ≥ min-n
on ≥1 tenant"; M3 has produced zero — `adjudicate.py` does not exist. `:31`:
*"shipping a refusing tool spends the honesty budget on theater."*

---

## Components — `doug/tenancy.py`

No FastAPI import.

| Function | Responsibility |
|---|---|
| `mint(installation_id) -> str` | Generate token, write `sha256` to `token_hash`, return plaintext **once** |
| `resolve(token) -> int \| None` | `sha256` → `installation_id`; constant-time compare |
| `verify_admin(pat, owner, repo) -> int` | The two-call proof; returns `installation_id` |

Token format: `doug_` + `secrets.token_urlsafe(32)`. The prefix makes it
greppable in a leaked-secret sweep and is what GitHub secret scanning would key
on later.

**No migration.** `installations` and `token_hash` were introduced in the same
commit (`6a1a213`, #18), so `create_all()` built the table with the column —
verified by pickaxe over `store.py`, not assumed. The column's own docstring
already promises this feature.

---

## Data flow — dispense

`POST /v1/installations/token`, body `{repo: "owner/name"}`, header
`X-GitHub-Token: <PAT>`.

**The call order is PAT-first, and that ordering is load-bearing.** HANDOFF
records a standing hazard: GitHub's 5,000/hr REST quota is shared across every
session and *was exhausted twice on 2026-08-02*. The app-JWT call spends
**Doug's** quota; the PAT call spends **the caller's**. On a public
`--allow-unauthenticated` service, doing the app call first hands an anonymous
caller a loop that drains the quota the review path needs to mint installation
tokens. So:

1. Caller's PAT → `GET /repos/{owner}/{repo}` → `permissions.admin` must be
   `true`. Fails → 404, **and no app-JWT call is made**.
2. App JWT → `GET /repos/{owner}/{repo}/installation` → `installation_id`
   (proves Doug is installed there).
3. Mint, store hash, return once.

Doug never stores the PAT — one request, then dropped.

**Known limit: repo-admin proves one repo, mint scopes the whole
installation.** `verify_admin` proves the caller administers exactly the repo
named in the request; `mint` then issues a token scoped to the entire
`installation_id`. On a User install these coincide — one account, one repo
surface, nothing to widen. On an Organization install covering multiple
repositories they do not: admin on any single repo is enough to mint a token
that reads every repo's PR titles, authors and reader rationales across the
whole org, and the same call silently rotates — and thereby invalidates — the
token every other consumer of that installation was using. Org installs are
where this bites; it is stated here as a known limit of the current design,
not fixed in this pass.

**Rejected: `GET /user/installations`.** One call instead of two, but that
endpoint is specified for user-access tokens; classic-PAT behavior is less
well-defined, which would make the auth story depend on a token type we cannot
check for. **Rejected: operator-minted only** — least code and it matches
hand-invoiced M5 exactly, but it keeps Andrew in the loop for every rotation
forever, and the roadmap line says "GitHub-token-verified".

### Lifecycle

- **Mint** — token returned in the response body **once**. Only `sha256(token)`
  is stored, so it can never be shown again by construction rather than policy.
- **Rotate** — call dispense again. New hash overwrites old; the old token dies
  instantly. One column write, so rotation is free rather than a feature.
- **Revoke** — operator sets `token_hash = NULL`.
- **Lost token** — identical to rotate. There is no recovery path and there
  should not be one.
- **Uninstall / suspend does not revoke.** `tenancy.resolve()` matches on
  `token_hash` alone and never reads `installations.state`. The webhook's
  uninstall path (`api.py`'s `_record_installation`, `deleted` branch) calls
  `upsert_installation(..., "deleted")` and clears the repo list via
  `set_installation_repos(inst["id"], [], replace=True)` — but never touches
  `token_hash`. A token minted before uninstall keeps resolving after it. The
  only real revocation is a manual `UPDATE installations SET token_hash =
  NULL`, which no code path performs today. This is stated as a limit rather
  than a cross-tenant hole — the token still only ever resolves to that same
  installation's own `installation_id`, never another tenant's — and checking
  `state` inside `resolve()` is a deliberate follow-up, not done here.

**Stated limit: one token per installation.** `token_hash` is a single column,
so when the MCP garden ships, an agent and a tenant's CI would share one token —
rotating for one silently breaks the other, and per-consumer usage cannot be
attributed. Acceptable now (one install, no garden until M3 produces adjudicated
rows). The upgrade is an `installation_tokens` table plus a migration, a path
this repo has walked five times.

---

## Data flow — scoped read

`GET /v1/queue` + `X-Doug-Token`:

- token == `DOUG_API_TOKEN` → operator; **no filter, byte-identical to today**.
- else `resolve(token)` → `installation_id` → `latest_reviews(installation_id=…)`.
- unresolvable → 401.

`repo` stays a caller-supplied parameter and becomes a **filter within scope**,
never a selector across scopes: a tenant naming one of their own repos filters
to it; a tenant naming any other repo gets 404 (below).

**When `DOUG_API_TOKEN` is unset the endpoint still 503s**, before any
resolution — unchanged from today. A tenant token is independent of that secret
and could in principle be honored without it, but a missing operator secret is a
deployment misconfiguration and should fail loudly rather than be masked by
tenant traffic that happens to work.

**The `installation_id` filter goes inside the grouped subquery.**
`latest_reviews` (`store.py:1194`) selects `max(id) GROUP BY (repo, pr_number)`
in a subquery, and its docstring already documents this exact bug class for the
`EXTERNAL_TIER` filter: filtering *outside* lets a row win `max(id)` for its PR
and then get dropped, so the PR **vanishes entirely** instead of falling back.
Same trap here — a CI row (`installation_id IS NULL`) with a higher id would
win, then be filtered, and the tenant's own App verdict would disappear from
their queue.

---

## Error handling

Everything that could confirm existence returns **404**: a cross-tenant `repo`,
a tenant token on an operator-only endpoint, Doug-not-installed at dispense, and
PAT-lacks-admin at dispense.

Not 403 — that confirms the thing exists. Not an empty list either: an empty
list is indistinguishable from "no reviews yet", which is a worse answer than
"no such thing". Absent or unresolvable token → 401. No ledger → 503. Missing
`DOUG_API_TOKEN` → 503. All unchanged where they already exist.

**Correction (2026-08-04, from the Task 5 review) — the endpoint half of that
claim does not hold at the deployment level, and this paragraph overstated it.**
FastAPI serves `/openapi.json` and `/docs` unauthenticated, and they enumerate
every route; the reviewer confirmed a plain `GET /openapi.json` returns 200
listing `/v1/patterns`, `/v1/comparisons`, `/v1/score/read`, and
`/v1/installations/token`. On an `--allow-unauthenticated` service, a stranger
already knows those endpoints exist, so 404-instead-of-403 conceals nothing
from a tenant that anyone can get for free.

Two things this does **not** change. **404 stays** — 403 would be strictly
worse, and the code is correct as written. And the **cross-tenant `repo` 404 is
unaffected**: repo names appear nowhere in the OpenAPI schema, so that one
leaks nothing and the M2 gate clause it serves stands.

What was wrong was the wording here, not the behaviour. Closing the gap for
real is **not** a one-liner. `openapi_url=None` is the FastAPI parameter that
actually does the work — it 404s `/openapi.json` itself (and, as a side
effect, `/redoc`, which also needs naming: `redoc_url=None`); `docs_url=None`
alone only hides Swagger UI at `/docs` and leaves `/openapi.json` reachable.
But `/openapi.json` is not just documentation in this deployment — it is the
health-check route three call sites depend on being reachable and
unauthenticated: `api/deploy/gcp.sh:241` (`promote_if_healthy "$SERVICE"
/openapi.json`), `api/deploy/gcp.sh:243` (the first-deploy smoke check), and
`.github/workflows/deploy.yml:127` (CI fails the deploy if it is not 200) —
all three exist because `/healthz` is intercepted by the Google frontend and
never reaches the app, which is why `/openapi.json` was chosen as the probe in
the first place. Setting `openapi_url=None` without also giving those three
call sites a replacement probe route that genuinely reaches the app would turn
every deploy red. The real follow-up is therefore: add a replacement probe
route, repoint `gcp.sh:241`, `gcp.sh:243`, and `deploy.yml:127` at it, and only
then set `openapi_url=None` (and `redoc_url=None`) in production — its own
task, tracked as a follow-up, deliberately not smuggled into this one.

---

## Testing

Tests encode why the behavior matters, not just that it happens.

1. **A PR with both a CI row (`installation_id` NULL, higher `id`) and an App
   row still appears in the tenant's queue, showing the App verdict.** This is
   the highest-value test in the set: it fails the moment someone moves the
   filter outside the grouped subquery, and it cannot pass by accident.
2. **Cross-tenant `repo` → 404** — the M2 exit gate itself, pinned.
3. **Operator-token behavior byte-identical to today** — no soak regression.
4. **Rotation** — mint twice; the first token 401s.
5. **Revocation** — `token_hash = NULL` → 401.
6. **Non-admin PAT → 404, and no token is minted.**
7. **A failed PAT check makes no app-JWT call** — pins the quota-safe ordering,
   which is otherwise invisible and easy to reverse in a later refactor.
8. **The token is returned exactly once and never logged.**

---

## Out of scope, deliberately

- **M3 receipts** (`GET /v1/prs/{n}/receipt`) do not exist yet. When built they
  are tenant-scoped through the same `tenancy.resolve`.
- **The MCP garden endpoint** — gated on adjudicated rows ≥ min-n.
- **Multi-token per installation** — the `installation_tokens` upgrade above.
- **Narrowing the spend cap.** Real per-read costs now exist ($0.093/read on
  `claude-opus-5`; 200 included reads = $18.66 COGS against $99), which makes
  the 4,000/installation cap a $373 exposure that is safe only when the
  hand-invoiced overage is actually billed. ROADMAP M2 says caps "are guesses
  until the cost lines below produce real numbers — M4 sets plan-shaped
  figures." That is an M4 item; recorded here so it is not rediscovered by a
  surprising invoice.
- **`design-lock.md:38` amendment** (bot authors metered, not excluded) — its
  own commit.
