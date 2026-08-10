# Doug's front door: hosted site, WorkOS login, self-serve install

**Date:** 2026-08-08
**Branch:** `front-door-design` (off `origin/main` @ `7fa5869`)
**Status:** design, approved after a three-lens adversarial verification pass

## Goal

A stranger lands on Doug's site, signs in, installs the GitHub App on their
repo, and returns to a signed-in page showing their repos and first verdicts —
with no hand-holding at any step.

First real tenant: `coldworkshq/coldworks` — an **org** installation on a
**private** repo, with no Doug installation of any kind today.

## Why now, and what it overrides

This pulls M6's "Tenant dashboard (WorkOS, tenancy steps 3–4)" forward past its
stated trigger (>3 tenants or first tenant ask — neither has fired), and
reverses the 2026-08-06 decision that "WorkOS auth is a detour from the
dogfooding pain." Recorded as an override, not drifted into.

Two facts make it the right time anyway. First, the existing dogfood
installation **cannot** test this path: installation 150424894 was populated
operationally (MT0, by redelivering an `installation` webhook) and carries no
WorkOS identity, so the bind step is exactly the thing it cannot exercise.
Second, `coldworkshq` is an **org** install, and MT1 hid for a year precisely
because repo-admin and installation-wide scope are indistinguishable on a User
install.

## Decisions

1. **Success bar:** a stranger self-serves end to end.
2. **Entry order:** sign-in first is the designed path. Cold install-first
   arrivals resume through the same binding code path.
3. **Day-1 surface:** welcome/IOU + tenant-scoped queue + per-PR receipts.
4. **No custom domain yet.** Build against `*.run.app`; domain is Phase 3.
5. **Surface split:** WorkOS-gated routes inside the existing `web/` Next app,
   *not* a third Cloud Run service.
6. **Session auth:** WorkOS JWT verified by FastAPI against JWKS. It shares
   what is genuinely shareable with `tenancy.resolve` and no more (§4).

On (5), the console precedent does not transfer. That spec's argument is about
a **deployment-flag** boundary — "a single environment variable separates them"
(`2026-08-06-doug-console-design.md:75-77`) — which is literally true of
console, whose gate *is* `--no-allow-unauthenticated` and which "adds no
authentication code." A WorkOS session gate is code evaluated per request. A
third service would cost a third byte-identical Dockerfile, two more CI jobs, a
new service account, and a third copy of the shadcn/theme duplication the
console spec already grudged.

The strongest argument against (5), accepted with eyes open: `doug-web` is the
only service with staged traffic and `promote_if_healthy` on `/`
(`api/deploy/gcp.sh:448`, `:466`), so a broken cookie password or redirect URI
could take down the marketing homepage — a failure a separate service could not
produce. Mitigated by excluding `/` and `/queue` from the auth matcher (§1).

## 0. The gate — PASSED 2026-08-09

This section opened as the design's one unproven assumption: nothing in
WorkOS's or GitHub's documentation states end-to-end that the access token a
WorkOS GitHub **App** connection returns is a *user-to-server* token that
`GET /user/installations` answers for. It was probed against WorkOS
**production** with Doug's real App. **It holds**, and the proof is stronger
than a 200:

- `oauth_tokens.access_token` carries the prefix **`ghu_`** — GitHub's
  documented prefix for a user-to-server token. The inference is now a measured
  fact.
- `refresh_token` present, `expires_at` present — the user-to-server lifecycle.
- `GET /user/installations` → **HTTP 200**, returning two installations, both
  `app_id=4450932`.

Four results from that probe are requirements, not trivia, and each is carried
into the sections below:

1. **Email verification interrupts the first sign-in** (§3).
2. **The GitHub token lives ~8 hours** — measured, so the residual-revocation
   window is bounded rather than hand-waved (§2).
3. **`repository_selection` differs across real installations** — `drewjst` is
   `selected`, `lemahq` is `all` (§2).
4. **`org_id` was absent on the first sign-in**, so the fail-closed path is
   reachable on day one, not hypothetically (§2).

Supporting observation, empirical rather than documented: that endpoint returns
HTTP 403 — *"You must authenticate with an access token authorized to a GitHub
App in order to list installations"* — for a token not issued by a GitHub App.
Observed from a live `gh api` call, recorded as behaviour, not contract.

## 1. Surfaces

`doug-web` serves both, separated by a route matcher plus a verified session.

| Path | Gate |
|---|---|
| `/`, `/queue` | public — **explicitly excluded from the auth matcher** |
| `/dashboard`, `/dashboard/[installation]`, `/dashboard/[installation]/pr/[n]` | WorkOS session |
| `/auth/callback` | `handleAuth({ baseURL })` |
| `/install/start` | route handler, requires session |
| `/install/callback` | route handler, tolerates no session |

`doug-api` gains a public `GET /v1/showcase/queue`, a WorkOS-JWT auth path, and
a session branch on the tenant queue. `doug-console` is untouched — but note it
also holds `DOUG_API_TOKEN` (`gcp.sh:484`), so the operator credential still
lives on a second service after Phase 0. Out of scope here; recorded so nobody
reads Phase 0's exit as "the operator token is gone from the fleet."

### Next.js specifics, settled not variable

`web/` pins **next 16.2.12** (`web/package.json:16`), so it is **`proxy.ts`
with `authkitProxy()`** — not `middleware.ts`/`authkitMiddleware()`. Next 16
throws E900 if both files exist.

`handleAuth({ baseURL })` is **required** here: the SDK needs it wherever the
container hostname differs from the request host, which is Cloud Run exactly.
Omitting it makes callbacks redirect wrong.

Sign-out is a **POST server action**, never a GET route.

`@workos-inc/authkit-nextjs` is not currently a dependency
(`web/package.json:12-25`), and `web/Dockerfile` runs `npm ci` from the
lockfile — the lockfile must regenerate in the same PR or the `web-image` job
goes red. Verify the standalone trace (`web/next.config.ts:4`,
`Dockerfile:20-22` copy only `.next/standalone`, `.next/static`, `public`)
includes the proxy bundle before assuming the image is unchanged.

## 2. Identity, and the difference between visibility and authority

**Doug identity is provider-neutral.** WorkOS is the account and session
boundary; GitHub is one optional capability, not a prerequisite for holding a
Doug account. A person without GitHub can sign in and use present or future
non-repository capabilities (for example session-state management). Only the
act of connecting GitHub repositories requires a linked GitHub identity and
the narrower installer-authority proof below. Do not put a GitHub requirement
in the general AuthKit proxy, session verifier, or account model.

WorkOS AuthKit, GitHub connection configured against **Doug's own GitHub App**
(app id 4450932, `gcp.sh:379`, `:416`), "Return GitHub OAuth tokens" enabled,
and the App's **Email addresses** account permission set to read-only (the
integration requires it).

**"Request user authorization (OAuth) during installation" must be OFF.** With
it on, GitHub redirects the installer to *the first callback URL in the app
settings* — which must be WorkOS's — so users would never reach
`/install/callback`. WorkOS runs its own OAuth for sign-in regardless, so
turning it off costs nothing.

### The correction that matters most

`GET /user/installations` lists installations the user has **`:read`, `:write`
or `:admin`** on — not admin only. **It answers "what may this person see?",
never "what may this person control?"** Treating its response as the
entitlement would hand a read-only outside collaborator on one repo the whole
org's PR titles, authors, reader rationales and receipts.

Two rules follow, and they are the load-bearing ones in this document:

- **Per-repo, per-user scoping is mandatory.** The session context carries
  `repo_ids` derived from `GET /user/installations/{id}/repositories`,
  intersected with `store.active_repos`. It is **never** `None`. `None` means
  installation-wide (`tenancy.py:88-90`, expanded at `api.py:346` and `:720`),
  which is MT1 reintroduced — and worse, because MT1 required admin and this
  would require only read. MT1's closure lives at *mint* time ("proof covers
  selection"); a browser session has no mint step, so that closure does not
  reach it.
- **Binding requires authority, not visibility.** See §3.

### Per request

FastAPI verifies the AuthKit JWT against JWKS — obtain the URL from
`client.user_management.get_jwks_url()` rather than hardcoding it — and reads
`org_id`, which the token carries only when an organization was selected
(<https://workos.com/docs/authkit/sessions>). It maps `org_id` to
`installations.workos_org_id`, then applies liveness and the repo intersection.

**`org_id` absent means fail closed.** Never default to the first installation.
You will hit this on your first sign-in, holding two installations.

**AuthKit hosts its own organization picker** and auto-selects when there is a
single membership; `authkit-nextjs` surfaces no `pending_authentication_token`.
Do not hand-roll a picker.

The GitHub token is never the per-request authority. It computes membership and
repo scope at sign-in and at refresh; Postgres and the live ledger authorize
every call.

### Session scopes are enumerated, not synthesized

Receipts enforce a `receipt:read` scope (endpoint `api.py:656`, check
`api.py:711`), and the
recorded decision is *"receipt auth: tenant-token only."* A session has no
scopes, so it gets an explicit, enumerated set — `{queue:read, receipt:read}` —
pinned by a test asserting it cannot exceed that. Synthesizing scopes from
nothing is inventing authority; bypassing the check is drift. This is a
deliberate, narrow amendment to the tenant-token-only decision, recorded as
such.

### Revocation, stated accurately

An earlier draft claimed stale membership lasts "until their next sign-in."
That was false. "Ensure membership" is additive; nothing deletes a WorkOS
membership, and refresh re-mints indefinitely against membership no code path
removes. So this design must include teardown:

- `installation.deleted` / `suspend` → revoke WorkOS memberships for that org,
  not merely mark the ledger.
- Re-derive membership **and repo scope** on every token refresh, not only at
  sign-in.
- Uninstall/reinstall mints a *new* `installation_id`, so `gh-inst-<old>` must
  be torn down or it lingers with live members.

Residual gap, now stated with a number: a user who loses repo access without any
installation-level event keeps it until their next refresh. The probe measured
the GitHub token's lifetime at **~8 hours**, so that window is bounded at ~8h
rather than "until next sign-in" (false) or indefinite (also false, once
refresh-time re-derivation exists). **Re-derive repo scope on refresh, not only
at sign-in** — that is what makes the bound real.

### Per-user repo scope is not uniform

The probe found `repository_selection` differing across the two real
installations: `drewjst` is **`selected`**, `lemahq` is **`all`**. So
`GET /user/installations/{id}/repositories` returns a *subset* for a `selected`
install, and the session's `repo_ids` must come from that call intersected with
`store.active_repos` — never assumed to be everything the installation covers.

### A tenant you may not want to show

The probe confirmed **`lemahq` (installation 151500529) is visible to the
operator's GitHub user**, so a signed-in dashboard will list it as one of their
tenants. That is *correct* under this entitlement model — they do administer it
— but it collides with the standing decision that Doug and lema are separate
products and lema is never Doug's tenant. Decide deliberately whether the
dashboard shows it, hides it, or labels it. It must not appear by accident.

## 3. Install and bind

1. `/` → "Get started" → sign-in via the SDK's supported path. `getSignInUrl()`
   is safe in a Server Action or Route Handler; the README also shows it in a
   server component. Confirm against the installed SDK's README at
   implementation time and follow the README, not this paragraph.
2. Signed in with no installations → "Install Doug".
3. `/install/start` sets a **30-minute signed HttpOnly cookie** holding a
   single-use nonce bound to the WorkOS user, then redirects to
   `github.com/apps/<slug>/installations/new`.
4. GitHub → the App's **Setup URL** → `/install/callback?installation_id=…`

   **GitHub does not document propagating `state` to the Setup URL.** Its docs
   name exactly one parameter, `installation_id`, and warn outright that "bad
   actors can hit this URL with a spoofed `installation_id`"
   (<https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/about-the-setup-url>).
   `state` is documented only on the installation URL and has silently
   regressed before. The cookie in step 3 replaces it — and because the cold
   arrival path needs the same cookie anyway, the two entrances collapse into
   one code path.

5. **Consume the nonce** (single-use; burn its digest in API storage, not just
   compare it in web memory). Doug-web and doug-api share a dedicated install
   flow HMAC secret; it is not the AuthKit cookie key. The successful bind
   transaction inserts the consumption before its authority write, and both
   commit or roll back together. A same-flow retry may return idempotent
   success but must not repeat WorkOS or binding side effects.
6. **Prove authority, not visibility.** Match the signed-in WorkOS user's
   linked GitHub identity to `installations.installed_by_github_user_id`, the
   sender recorded by the `installation.created` webhook. Task 5 rejected the
   earlier `tenancy.verify_org_admin` proposal because its membership proof
   needs a GitHub organization permission Doug does not hold and would force
   existing installations to re-accept. `GET /user/installations` remains
   insufficient: an attacker with `:read` on one repo sees the victim's
   `installation_id`, and setup-URL parameters are attacker-supplied.
7. Ensure the WorkOS org under a **Postgres advisory lock** —
   `external_id` has no documented upsert and no documented conflict code, so
   find-or-create is not race-safe. Look it up via
   `GET /organizations/external_id/{external_id}`. Then redirect to
   `/dashboard/<installation_id>`.

**Cold arrival** (no session): stash `installation_id` in the same signed
cookie, bounce to sign-in, resume at step 5.

### The first sign-in is interrupted, and the flow must survive it

The probe hit this and every first-time Doug user will: WorkOS refuses to
complete a first authentication until email ownership is proven. It returns
HTTP 403 `email_verification_required` with a `pending_authentication_token`,
emails a one-time code, and completion requires a second call with
`grant_type: urn:workos:oauth:grant-type:email-verification:code` plus
`{code, pending_authentication_token}`.

That puts an **inbox round-trip** between "signed in with GitHub" and "a session
exists" — the user leaves the browser and comes back, possibly minutes later,
possibly in a new tab. **The signed bind cookie from step 3 must outlive that
gap**, or first-time self-serve installs break at exactly the moment the whole
design exists to make seamless. Its TTL is sized for a human checking email, not
for a redirect. AuthKit's hosted UI handles the verification screens; what this
design owns is not losing the pending installation across them.

**`setup_action` handling.** `update` fires whenever anyone edits repo
selection and is a second uninvited bind trigger — treat it as re-derive-scope,
never as bind. `request` (org admin must approve) produces **no installation at
all**: there is no `installation_id` to bind, and the user must land on an
explanatory "waiting for your org admin" state rather than an error.

Binding must be idempotent with respect to the `installation.created` webhook,
which already calls `reconcile_installation` (`api.py:1398`, defined at
`worker.py:384`) and is replayable via GitHub's Redeliver button.

## 4. What is actually shared with `tenancy.resolve`

An earlier draft claimed "one authorization core, two front-ends, they cannot
drift." That was overstated and is corrected here.

`tenancy.resolve` (`tenancy.py:98`) is **token-row-shaped**: it needs a
`keyformat`-parsable token (`:113`), an `installation_tokens` row (`:118`), and
checks `revoked_at`, `expires_at`, and `repo_selection` — none of which a
session has. Only two things genuinely generalize: the `installations.state`
liveness check (`:130`) and the live-repo set (`:135`). Note also that
`installations.state` liveness currently rides on the token JOIN
(`store.py:2497-2520`), and **no store function looks up an installation by
WorkOS org** — that query is new work.

So: extract the ~3 shareable lines into a small helper both paths call, add a
new session branch at `api.py:326`, and **do not claim more sharing than
exists**. The honest property is "both paths apply the same liveness and repo
intersection," not "they cannot disagree."

### `ctx is None` is the operator sentinel

`api.py:376` routes `?repo=` into `store.latest_reviews(repo=…)`, a name lookup
across every installation, when `ctx is None`. A session context that is not a
`TokenContext` would make that true — yielding an unscoped queue plus a
cross-tenant repo-name probe. **Introduce an explicit `is_operator: bool`
before any second credential type lands.** This is a prerequisite, not a
cleanup.

`_operator_only` (`api.py:270-300`) reads only `x_doug_token`, so a JWT in
`Authorization` cannot reach `/v1/runs` today — it fails closed *as written*.
That holds only while no route accepts both credentials, so pin it with a test
asserting a valid session JWT gets 401/404 on every operator route.

## 5. Data model

One new column: `installations.workos_org_id` (text, unique, nullable).
`installations` has six columns today and no WorkOS field (`store.py:183-192`).
No users table — WorkOS holds users and membership.

**The migration number is deliberately not written here.** The highest is
currently 8 (`migrations.py:233`, landed on main by PR #72). The next free
number is 9, but 9 is earmarked for MT3's `installations.reconciled_at`
(`ROADMAP.md:306`), which has not started. Read `MIGRATIONS` in
`migrations.py` at implementation time. This trap has fired three times.

## 6. Build order — three PRs

### Phase 0 — precondition. No user-visible change.

- Build `GET /v1/showcase/queue`: public, unauthenticated, pinned to a new
  `DOUG_SHOWCASE_REPO`, 404 when unset. **Already designed** at
  `2026-08-06-doug-console-design.md:57-61`, `:188-189` — this executes an
  existing item. It must **not** gate on `DOUG_API_TOKEN` the way `queue()`
  does (`api.py:317-322`). `store.latest_reviews(repo=…)`
  (`store.py:1795-1800`) already supports repo-only scoping, so this is
  assembly, not new SQL.
- It must return exactly what the pages dereference: `summary{open, flagged,
  cleared, threshold}` and `items[]{pr{number, title, author, author_type,
  additions, deletions, files[], approval_latency_s, url}, verdict{score, band,
  threshold, reasons[]{rule, label, weight, severity?}}}` (`web/lib/api.ts:39-42`,
  guard at `:57-82`). No pagination, no filtering; the score strip needs
  nothing extra and threshold is re-banded client-side.
- **Repoint `/` as well as `/queue`.** `web/app/page.tsx:73` also calls
  `getQueue()`. Miss this and the landing page silently serves the bundled
  fixture — and `promote_if_healthy` smokes `/` (`gcp.sh:466`), which returns
  200 either way, so the deploy gate cannot catch it.
- Drop `DOUG_API_TOKEN` from `doug-web`: the deploy flag (`gcp.sh:459`) *and*
  the `secretAccessor` binding (`gcp.sh:165-171`).
- Add `npm test` to the existing `web` CI job (`ci.yml:31-45`). **The job
  already exists; the missing line is `npm test`.** Note the current script is
  a silent no-op, not a failure: `sh` leaves `lib/*.test.mjs` unexpanded and
  node's `--test` matching nothing exits 0. A green check asserting nothing is
  worse than a red one — fix the glob and add real tests, or the added line
  inherits the same lie.
- Execute or explicitly record the never-run compute-SA `secretAccessor`
  removal (`gcp.sh:172-178`).
- Fix the stale comment at `gcp.sh:450` referring to "the dashboard's server
  component," which does not exist.

**Exit:** `doug-web` holds no `doug-api` credential; `/` and `/queue` both
render live data; the web CI job runs tests that actually execute.

### Phase 1 — auth, install, bind, and the tenant surface

Phases 1 and 2 of the earlier draft are merged: they were not separable.
`org_id → installations.workos_org_id` needs the column, and "org selection
works" needs orgs that only the bind step provisions.

- `proxy.ts` with `authkitProxy()`, matcher **excluding** `/` and `/queue`;
  callback route with `handleAuth({ baseURL })`; `AuthKitProvider` in layout;
  POST sign-out action; `@workos-inc/authkit-nextjs` added and the lockfile
  regenerated.
- New secrets: `WORKOS_API_KEY`, `WORKOS_COOKIE_PASSWORD`, `WORKOS_CLIENT_ID`,
  redirect URI. New Secret Manager entries, new `add-iam-policy-binding` for
  `doug-web-sa` (pattern at `gcp.sh:165-171`), new `--set-secrets` on `web()`.
  Phase 0's "holds no credential" exit is momentary by design.
- The migration; `is_operator: bool`; the shared liveness/repo-intersection
  helper; JWKS verification; the session branch at `api.py:326`; the new
  installation-by-org query.
- `/install/start`, `/install/callback`, signed single-use nonce cookie,
  org-admin proof, advisory-locked org ensure, membership provisioning and
  **teardown**.
- `/dashboard` with the welcome/IOU block, tenant-scoped queue, and receipts.

**Session fetch helpers must not reuse `web/lib/api.ts`.** `inflight` and
`last` (`:116-118`) are module-global and key-less — deliberately, for the
public page. Any tenant-scoped fetch sharing that module would serve one
tenant's queue to the next visitor. Session fetches are cacheless or keyed by
org, and a test pins it.

**Exit:** `coldworkshq/coldworks` installed cold through the front door, bound,
and rendering its own verdicts and receipts.

### Phase 2 — marketing and domain

CTA rework (three `/queue` CTAs today at `web/app/page.tsx:85,145,342`), copy,
Cloud Run domain mapping, re-point the WorkOS redirect URI and the App's
callback and setup URLs.

## 7. Exit gate

A sibling to `api/deploy/prove-isolation.sh`, executable against prod — that
script earned its place by catching the pepper-newline and GC'd-client defects
that unit tests could not.

1. Session with `coldworkshq` selected returns **only** coldworks rows.
2. Same session, `drewjst` selected, returns only drewjst rows.
3. **A member with access to one repo in an org sees only that repo's rows.**
   The earlier draft's gate omitted this and would have passed with the MT1
   regression present — items 1–2 test org-vs-org and never member-vs-member
   inside one org.
4. Orgless JWT → refused.
5. JWT for a suspended installation → refused on the next request (MT2 proven
   through the session path).
6. Tampered or expired JWT → refused.
7. `org_id` mapping to no installation → refused.
8. A valid session JWT gets 401/404 on every operator route.
9. A bind attempt for an installation the caller can read but not administer →
   refused.

## 8. Risks accepted

- AuthKit config errors could affect `doug-web`. Mitigated by the matcher
  exclusion and existing staged traffic.
- GitHub App settings changes are **production** config on a live App with a
  real installation.
- **No page-level or render test exists anywhere in this repo** — all six test
  files are console *lib* tests. Phase 0/1 are *inventing* that infrastructure,
  not copying console's. Console's Phase 1 found 13 defects, 12 real, mostly
  "the UI claiming to know something it did not"; a dashboard that makes
  entitlement claims is the same risk class with a worse blast radius.
- WorkOS becomes a dependency in the sign-in path. It is deliberately **not** a
  dependency in the authorization path.

## 9. Open question for the plan

**The welcome projection may not exist on day 1.** The IOU is meant to read "at
your merge volume, your first adjudication lands ~`<date>`," but a cold
installation has no merge history until reconcile runs, and `coldworks` is
private with no prior Doug data. The anti-disappointment device may be
unavailable at exactly the moment of disappointment. Options: derive from
GitHub commit history at bind time; show a rate-free message until the first
merges land; or accept an empty screen and say so plainly. Decide in the plan.

## Verification record

This design was rewritten after a three-lens adversarial pass (WorkOS/GitHub
platform mechanics against live docs; security; code reality). The passes
refuted, among others: that `state` propagates to the Setup URL; that
`GET /user/installations` implies authority; that binding was safe from a
read-only collaborator; that "until next sign-in" bounded stale membership;
that one authorization core was achievable; that `npm test` failed; that
receipts were unmerged; and that Phases 1 and 2 were separable. Every claim
above that cites a file:line was checked against the tree at `7fa5869`.
