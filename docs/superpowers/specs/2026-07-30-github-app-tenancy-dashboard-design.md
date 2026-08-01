# Doug as a GitHub App: tenancy, ingest, and the dashboard

**Date:** 2026-07-30
**Status:** approved, not yet built
**Conflicts with:** ADR-0003 (CI surface is job summary only) — must be superseded by a new ADR, see below
**Fulfils:** the design pass HANDOFF calls "the biggest single piece of work outstanding"

## Why

Doug's onboarding is the outlier for its category. Today a repo adopts Doug by
adding a workflow YAML and two secrets, one of which is a shared API token
common to every caller. Every pure PR-review product that could be sourced
requires zero repo configuration instead: Graphite ("no configuration
required"), Greptile ("No config files or CI workflows are required"),
CodeRabbit (App authorization only, YAML optional), Qodo Merge (App = "no
CI/CD configuration").

The products that require *both* an App and CI — Codecov, and SonarQube Cloud
for coverage — share one cause: the vendor needs an artifact only the
customer's build produces. Doug needs no build artifact. It reads the diff,
the title, and the file list. Nothing pins it to CI.

Two further facts make the App the unlock rather than a refactor. Doug flagged
its own integration for forwarding `github.token` to an external service; an
App removes that forwarding. And Doug has no repository index step, so unlike
Greptile's 1–2 hour wait, its first review can fire on the first PR after
install.

## Scope

In scope: a GitHub App, webhook-driven review, per-installation tenancy, an
authenticated dashboard with org → repo navigation, a triage view, a per-repo
control surface, and the neutral check run that replaces the job summary.

Out of scope: the evidence view (blocked — see below), per-PR forensics
(deferred), a lema-backed intent provider (lema is an unrelated product — ADR-0006), PR comments, and any change to the
frozen reader prompt or schema.

## What the review found, verified against the code

These constrain the design and several were re-checked directly rather than
taken on report.

**Live today, independent of this work.** Production runs with no webhook
secret: `deploy/gcp.sh:87` sets `DATABASE_URL`, `DOUG_API_TOKEN` and
`ANTHROPIC_API_KEY` and nothing else, while `api.py:284-292` returns 202 for an
*unsigned* body when `GITHUB_WEBHOOK_SECRET` is unset — a state pinned by
`tests/test_api.py:55`. Separately, `/v1/queue` (`api.py:159`) takes an
arbitrary `?repo=` with no authentication on an `--allow-unauthenticated`
service (`gcp.sh:83`). Under an App the first becomes attacker-triggered LLM
spend and forged ledger rows; the second becomes a cross-tenant read the moment
a second tenant exists.

**The repo string is not a safe tenancy key.** The 653 backfilled research rows
use real logins — `backfill_ledger.py:37-38` writes `getsentry/sentry` and
`grafana/grafana` verbatim. An earlier draft of this design proposed that a
repo with no live installation is simply invisible; that is not a protection.
If anyone at Sentry or Grafana installs Doug, their tenant inherits the probe
corpus, its reader rationales quoting their code, and 193 outcome rows. GitHub
logins are also reusable after rename or deletion, so claiming a freed login
inherits that string's entire history.

**Nothing writes outcomes except the backfill.** The only writers of the
`outcomes` table are `backfill_ledger.py:95` and `:184`. There is no live
outcome sync, so `pattern_join`'s inner join (`store.py:266-276`) returns empty
for any live repo.

## Decisions

### The installation is the tenant

Installing the App is the entire setup. The installation defines the tenant,
GitHub supplies the repo list, and install/uninstall webhooks keep it current.
This is the 1:1 industry mapping — SonarQube Cloud: "Each organization
represents an organization on the repository platform side… created by
importing and binding it to the DevOps platform organization."

An installation account carries `type: Organization | User`, which *is* the
org-or-user axis the dashboard navigates. Personal accounts are not a separate
concept and must not become one.

**Rejected:** WorkOS Organizations with manually claimed repos — a claim is
unverifiable, and nothing would stop someone claiming `getsentry/sentry`.
**Rejected:** pure verify-on-read against the viewer's GitHub token — accurate,
but yields no org object and does nothing for write-side tenancy. That check
survives as the auto-join mechanism, which is why there is no invite flow.

### Tenancy keys on `github_repo_id`, never on the repo string

`verdicts` gains a `github_repo_id` column and all scoping joins on it;
`verdicts.repo` becomes display-only. This closes login reuse and rename
splitting in one move, and removes the need for the alias table an earlier
draft proposed — an alias keyed on the old string could never repair
`verdicts.repo`, which is written at review time (`store.py:139`).

The research corpus is excluded by an explicit `source='research'` flag, not by
absence of an installation.

**Rejected:** a tenant column on `verdicts` — 653 of 654 rows are research data
that belongs to no tenant, and a tenant column forces them into one.

### Review is webhook-driven, and the ingest is a rewrite

This is the real work; the App registration is the easy part.

`pull_request` delivery must be answered within GitHub's timeout, and a
claude-opus-5 read of a 30k-character diff (`reader.py:23-27`) on
`--max-instances 2 --cpu 1` (`gcp.sh:91`) will not fit. The handler returns 202
and enqueues.

`save_review` inserts unconditionally with no uniqueness on `(repo, pr_number)`
(`store.py:135-152`), so every redelivery is a duplicate opus call, and
`synchronize` fires per push — a 20-push PR is 20 reads. A unique index on
`(installation_id, github_repo_id, pr_number, head_sha)` fixes duplicates,
replays, and out-of-order delivery together. Events missed while the service is
down are recovered by reconciling open PRs by head SHA — on service startup and
on each new installation — not by trusting redelivery.

`github_webhook` is `async def` (`api.py:279`) while the review path is sync;
running a review inside it blocks the event loop for the whole service.

Fork PRs default to off per repo. `doug-review.yml` skips them today only
because forks get no secrets; the App has no such accident, and `_user_text`
(`reader.py:169-176`) concatenates the raw diff into the prompt, so an outside
contributor could otherwise drive `risk_score` at the tenant's expense.

### The shared token path is removed outright

One ingest path, no migration mode. Only `lemahq/lema` — an unrelated product
that happens to have Doug wired into its CI, not a sibling or showcase tenant —
ingests today, so the flag-day cost is one repo, and it is the install target
for testing.

**Rejected:** running both paths during a migration — hedging against a
migration that does not exist. **Noted for later:** Qodo keeps a CI path
deliberately as its no-egress enterprise SKU. If that buyer appears, CI ingest
returns as a deliberate SKU authenticated by GitHub Actions OIDC — the
`repository` claim cryptographically binds an upload to its repo, which a
shared secret cannot — and never as a shared token.

### The surface becomes a neutral check run

ADR-0003 fixed the surface at job-summary-only and explicitly rejected check
runs as implying "a pass/fail semantic Doug does not have." But the job summary
exists only inside `deploy/doug-review.yml`; deleting CI deletes the only place
a verdict reaches a human. A check run with a neutral conclusion is the sole
remaining surface consistent with "routes, never blocks," and is what Sonar and
CodeRabbit use.

The check run must render the tier honestly. With the Anthropic balance empty,
`review.py:111-116` falls back to the deterministic tier; today that is visible
in the job summary, but behind a check run a deterministic verdict would
otherwise read as the validated reader.

ADR-0003 must be superseded in the same change. These records feed Doug's own
intent tier, so leaving it `accepted` while shipping a check run would make
Doug flag its own PR as contradicting a decision record.

**Rejected:** dashboard-only, which makes an advisory reviewer invisible.
**Rejected:** PR comments — ADR-0003's precision argument has not changed.

### WorkOS holds identity and the org shell; Postgres holds tenancy

A WorkOS Organization is created per installation, keyed
`external_id = "gh-inst-<installation_id>"`. Repo lists, installation state,
and all business tenancy stay in Doug's Postgres. Nothing else about GitHub's
structure is mirrored.

WorkOS earns its place narrowly: the session-scoped `org_id` / `role` /
`permissions` claims let FastAPI authorize statelessly, and SSO/SCIM come free
later.

Four constraints, all doc-sourced:

- `org_id` and `role` are present only "if an organization is selected." A user
  with several installations — the normal case — gets an **orgless token**. Use
  the organization-selection grant (`pending_authentication_token` →
  `grant_type: urn:workos:oauth:grant-type:organization-selection`) and switch
  with `refreshSession({ organizationId })`. **The API fails closed when
  `org_id` is absent** and never defaults to the first installation.
- Cross-origin: send the `accessToken` from `withAuth()` as
  `Authorization: Bearer`. Do not share cookies — that needs a common parent
  domain and an identical cookie password, and FastAPI cannot unseal a
  Node-sealed cookie. Verify against JWKS at
  `https://api.workos.com/sso/jwks/{client_id}` using PyJWT's `PyJWKClient`;
  no documented Python helper exists.
- `external_id` (64 chars, mutable) has no documented upsert and no documented
  conflict code, so find-or-create is **not** race-safe. Take a Postgres
  advisory lock and make handlers idempotent on the event id. `workos_org_id`
  is the source of truth; `external_id` is a recovery index.
- RBAC uses environment-level `admin`/`member` and checks `permissions`, not
  role slugs. The first org-scoped custom role permanently detaches that org
  from environment-level inheritance.

Membership auto-provisions via `POST /user_management/organization_memberships`,
which creates an active membership with no invitation. Removals are driven off
GitHub webhooks, not login — login-sync alone leaves revoked access live until
the user next signs in. Industry practice agrees: Sonar syncs org membership
but explicitly not permissions.

### Per-repo control needs a config seam

Every setting is a process-global env var read at call time — `DOUG_THRESHOLD`
(`scoring.py:22`), `DOUG_READER` / `DOUG_READER_THRESHOLD` (`reader.py:162,166`),
`DOUG_INTENT` (`intent.py:73` and again `reader.py:220`), `DOUG_ADR_PATH`
(`intent_providers.py:31`). Sync routes run in a threadpool, so mutating
`os.environ` per request is a cross-request race. A `RepoConfig` threads
through `score_one` / `read_diff` / `verdict_from_reader` instead.

What per-repo control may cover: threshold, intent tier on/off, ADR path, fork
PRs on/off. The frozen SYSTEM/SCHEMA bytes are untouched by all of these, and
per-row `verdicts.threshold` (`store.py:46`) keeps re-banding comparable.

What it may not: `MIN_RELEVANCE` / `RELATIVE_FLOOR` (`intent.py:41-42`).
Per-repo tuning of record *selection* changes what the read sees while the
derangement check is still unrun. `DOUG_ADR_PATH` is the borderline case — it
also changes the read's input, and is admitted only because a wrong path
yields no records rather than differently-weighted ones. Turning the reader off
silently disables intent (`review.py:136`); the UI must say so.

### The evidence view is cut from this scope

"Is Doug right here" cannot be answered for a live repo, because nothing
records whether a PR turned out to be a defect. This is not thin data; it is no
data source at all until an outcome writer exists.

`PATTERNS_CAVEAT` (`api.py:238-243`) is corpus copy and must not be served
per-repo — telling a customer their base rate is "an enriched sample… far above
any repo's true defect rate" is false about their own repo.

The evidence view returns once outcomes are written live, and renders nothing
when `base == 0`.

## Build order

1. **Close the two live holes.** Require `GITHUB_WEBHOOK_SECRET` at startup and
   delete the unsigned branch and its test; authenticate `/v1/queue` and derive
   the repo from the caller. Independent of every decision above.
2. **The App and webhook ingest.** Enqueue, uniqueness key, neutral check run,
   forks off, ADR-0003 superseded. Tested by installing on `lemahq/lema`.
3. **Tenancy and login.** `github_repo_id` scoping, `source='research'` flag,
   AuthKit with organization selection and fail-closed authorization.
4. **Dashboard.** Org → repo navigation, triage, control.
5. **Outcome writer, then the evidence view.** Outside this spec; needs its own
   design pass, because what counts as an outcome on a live repo is an open
   research question, not an engineering one.

Steps 1–4 are this spec's scope and should be planned separately rather than as
one plan: step 1 is a self-contained fix, step 2 is the ingest rewrite, and
steps 3–4 depend on step 2 landing.

## Open questions

- **App private key custody.** `/v1/review`'s docstring states the service
  "holds no repo credentials of its own"; minting installation tokens ends
  that. `gcp.sh:66-72` grants `secretAccessor` to the default compute service
  account, so every workload in `doug-prod0` could read the key — a dedicated
  service account is required. The un-rotated key at
  `repo/api/.backtest-cache/llm-probe/api-key` should be rotated first.
- **Webhook signature algorithm is client-chosen.** githubkit's `verify` selects
  sha1 or sha256 from the signature *prefix* rather than the header name, so
  `X-Hub-Signature-256: sha1=…` downgrades the comparison to HMAC-SHA1. Not
  currently exploitable; pin the prefix.
- **Queue semantics after the rewrite.** `latest_reviews` (`store.py:285`)
  returns the most recent verdict per PR from the ledger. Whether the triage
  queue should show only open PRs, and where "open" is sourced from once CI no
  longer drives ingest, is undecided.
