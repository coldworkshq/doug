# WorkOS Login Entry Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the approved sign-in-first front door so a person can create a Doug account without GitHub, reach hosted WorkOS AuthKit, and enter a protected dashboard without a Next.js render-time cookie failure.

**Architecture:** A dedicated `GET /sign-in` Route Handler owns the PKCE-producing `getSignInUrl()` call because Next.js 16.3 permits cookie mutation there but not during Server Component rendering. The dashboard uses read-only `withAuth()` and sends an unauthenticated request to the local sign-in handler. The handler canonicalizes the request origin to the configured callback origin before creating PKCE state, so Cloud Run's two hostnames cannot split the verifier cookie from the callback.

**Tech Stack:** Next.js 16.3 App Router, `@workos-inc/authkit-nextjs`, React 19, Node test runner, GitHub Actions, Google Cloud Run.

## Global Constraints

- WorkOS remains the provider-neutral account boundary; GitHub is optional and is requested only by **Connect GitHub**.
- `/` and `/queue` remain public and outside the AuthKit proxy matcher.
- `getSignInUrl()` may run only inside a Route Handler or Server Action.
- Auth initiation and `/auth/callback` must use the same canonical `*.run.app` origin.
- No token, API key, cookie password, PKCE state, or upstream error body may enter HTML, logs, or test output.
- Preserve the existing landing-page typography, color tokens, motion, and rounded-control vocabulary; this is an entry-point repair, not a redesign.
- Production deployment remains gated on explicit user approval after the corrective PR merges.

---

### Task 1: Lock the Missing Runtime Contract

**Files:**
- Create: `web/lib/auth-entry.integration.test.mjs`
- Create: `web/scripts/smoke-auth-entry.sh`
- Modify: `api/tests/test_deploy_gcp.py`

**Interfaces:**
- Consumes: a real local Next production server, a controlled HTTP server for smoke-script cases, and the production deploy workflow call site.
- Produces: caller-level regression contracts for canonical sign-in, dashboard redirect ownership, landing-page entry controls, and deploy-time AuthKit reachability.

- [ ] **Step 1: Add a failing local Next integration test**

Build and start the real Next app with non-secret test configuration on loopback. Prove:

```js
assert.equal(root.status, 200);
assert.match(await root.text(), /href="\/sign-in"[^>]*>Sign in</);
assert.match(rootHtml, /href="\/sign-in"[^>]*>Get started</);
assert.equal(dashboard.status, 307);
assert.equal(dashboard.headers.get("location"), `${origin}/sign-in`);
assert.equal(signIn.status, 307);
assert.match(signIn.headers.get("location"), /^https:\/\/api\.workos\.com\/user_management\/authorize\?/);
assert.match(signIn.headers.get("set-cookie"), /wos-auth-verifier=/);
```

Send a request with an alternate `Host` header and prove `/sign-in` first redirects to the configured canonical origin rather than minting PKCE on the alternate host. Add missing/invalid redirect configuration cases that return a constant 503 response without a WorkOS redirect.

- [ ] **Step 2: Add failing executable smoke-script tests**

Use a controlled HTTP server to run `web/scripts/smoke-auth-entry.sh` against: (a) root 200, dashboard 307 to same-origin `/sign-in`, and sign-in 307 to WorkOS; and (b) the currently insufficient root-only 200 behavior. Assert (a) exits 0 without printing the WorkOS query string and (b) exits nonzero.

- [ ] **Step 3: Add a failing deployment smoke-contract test**

Extend `api/tests/test_deploy_gcp.py` to require the web deployment workflow to invoke the tested smoke script after resolving the promoted service URL. The script itself checks all three receipts:

```text
/ -> 200
/dashboard -> 307 with same-origin /sign-in location
/sign-in -> 307 with https://api.workos.com/ or https://authkit.app/ authorization location
```

The test must reject a workflow that checks only `/`.

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```bash
npm test --workspace=web -- --test-name-pattern='sign-in|landing|dashboard'
cd api && uv run pytest -q tests/test_deploy_gcp.py
```

Expected: the real Next integration fails on missing `/sign-in`, absent landing actions, and the dashboard's 200 error shell; smoke-script tests fail because the script is absent; the wiring pin fails because the workflow does not invoke it.

### Task 2: Add the Canonical WorkOS Entry and Safe Dashboard Guard

**Files:**
- Create: `web/app/sign-in/route.ts`
- Modify: `web/app/dashboard/page.tsx`

**Interfaces:**
- Consumes: `NEXT_PUBLIC_WORKOS_REDIRECT_URI`, `getSignInUrl({ returnTo: "/dashboard" })`, `withAuth()`, and Next's `redirect()`.
- Produces: `GET /sign-in` and a dashboard guard that never mutates cookies during Server Component rendering.

- [ ] **Step 1: Implement the minimal sign-in Route Handler**

Read the redirect URI at request time with bracket access. Parse its origin; return `503 Sign-in is temporarily unavailable.` for missing or invalid configuration. If the request origin differs, return a 307 to `<canonical-origin>/sign-in` before calling AuthKit. On the canonical origin, call `getSignInUrl({ returnTo: "/dashboard" })` and redirect to the returned WorkOS URL.

- [ ] **Step 2: Replace render-time sign-in with a local redirect**

Change the dashboard from:

```ts
const auth = await withAuth({ ensureSignedIn: true });
```

to read-only `withAuth()`. If `user` or `accessToken` is absent, call `redirect("/sign-in")` before any session API request. Do not catch the redirect.

- [ ] **Step 3: Run the focused tests and verify GREEN**

Run the Task 1 focused commands. Expected: the sign-in and dashboard tests pass; the deployment workflow contract remains red until Task 4.

### Task 3: Expose Sign In Without Redesigning the Landing Page

**Files:**
- Modify: `web/app/page.tsx`

**Interfaces:**
- Consumes: the existing `Link`, nav pill, hero action row, and shared design tokens.
- Produces: a nav **Sign in** action and hero **Get started** primary action, both targeting `/sign-in`.

- [ ] **Step 1: Add the two entry controls**

Add **Sign in** to the nav pill. Replace the hero's primary **See the queue** action with **Get started** targeting `/sign-in`; retain **See the queue** as the secondary hero action. Keep GitHub available from the nav and remove no public evidence surface.

- [ ] **Step 2: Verify accessibility and responsive behavior**

Use links rather than click handlers, retain visible focus behavior from the existing control styles, and confirm the nav remains usable at narrow width without introducing a new CSS system.

- [ ] **Step 3: Run web tests, lint, and build**

```bash
npm test --workspace=web
npm run lint --workspace=web
npm run build --workspace=web
```

Expected: 0 failures, lint exit 0, build exit 0, and `/sign-in` listed as a dynamic route.

### Task 4: Make Deployment Prove the Login Entry

**Files:**
- Modify: `.github/workflows/deploy.yml`
- Create: `web/scripts/smoke-auth-entry.sh`

**Interfaces:**
- Consumes: the promoted Cloud Run service URL and `curl` response code/location output.
- Produces: deployment failure when the public site is healthy but sign-in or dashboard auth is broken.

- [ ] **Step 1: Extend the post-promotion web check**

Implement the already-tested script: request `/`, `/dashboard`, and `/sign-in` without following redirects; require root 200, dashboard 307 to `${url}/sign-in`, and sign-in 307 to a WorkOS-owned HTTPS authorization URL. Print only status and origin/path-safe receipt text; do not print query strings because they contain PKCE state. Replace the workflow's root-only curl with `bash web/scripts/smoke-auth-entry.sh "$url"`.

- [ ] **Step 2: Run the deployment contract and shell/YAML checks**

```bash
cd api && uv run pytest -q tests/test_deploy_gcp.py
bash -n api/deploy/gcp.sh
```

Expected: the focused deploy test and shell parse pass.

### Task 5: Full Verification and Delivery

**Files:**
- Verify only; no planned production-code changes.

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: a reviewable corrective PR with reproducible receipts.

- [ ] **Step 1: Run the full repository gates**

```bash
npm test --workspace=web
npm run lint --workspace=web
npm run build --workspace=web
cd api && uv run pytest -q
uv run ruff check .
bash -n deploy/gcp.sh
```

- [ ] **Step 2: Run a local production-server smoke test**

Start the built Next server with non-secret test credentials and a loopback redirect URI. Verify `/` returns 200, `/dashboard` redirects to `/sign-in`, and `/sign-in` redirects to a real WorkOS authorization URL without logging the URL query.

- [ ] **Step 3: Review the exact diff and secret boundary**

Confirm no secrets or token-shaped fixtures entered the diff; verify `git diff --check`; inspect every changed caller and test.

- [ ] **Step 4: Commit, push, and open the corrective PR**

Use a concise commit and PR body that includes the production error, why the previous build-only gate missed it, the red/green regression receipts, and the explicit statement that GitHub remains optional.

- [ ] **Step 5: Wait for CI and stop before production mutation**

Do not merge or redeploy without Andrew's explicit approval. After approval, deploy web and verify the promoted service using the workflow receipts plus an interactive cold-user WorkOS login.
