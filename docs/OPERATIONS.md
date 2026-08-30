# Operations runbook

## Alerting

Doug's own silence is a defect, not a quiet day. From 2026-08-16 to 2026-08-18
the adjudicator was dead and every surface reported `adjudicated 0` — the
designed honest empty state, identical to the broken one. `doug-prod0` held no
alert policies and no notification channels, so nothing said anything; the
outage was found three days late by reading Cloud Run execution status by hand.
"Empty is the product" holds only while empty-because-broken is a different and
louder thing (#121).

### Check that the alerting is there

```
PROJECT=doug-prod0 api/deploy/monitoring.sh verify
```

Read-only, and non-zero on anything unmet. This is the check that would have
caught 2026-08-16 on day one, so run it after any project-level change and
whenever you are about to trust a green dashboard.

It requires seven things, and each is load-bearing:

| Requirement | What it catches |
|---|---|
| a notification channel that reaches a human | policies wired to nothing — the outage with extra steps |
| an uptime check polling `/healthz/queues` | nothing on its own; it is what the third policy watches |
| a log metric counting reader fallback lines | nothing on its own; it is what the `reader-fallback` policy watches |
| policy `job-failed` | an adjudicator or reconciler execution that ran and **failed** |
| policy `api-5xx` | doug-api serving 5xx — a tenant-visible incident under R1 |
| policy `queue-liveness` | work sitting past the point where its drain provably did not run |
| policy `reader-fallback` | an LLM read degrading to the deterministic score — the failure that is silent everywhere else |

`job-failed` and `queue-liveness` are not redundant. A Job that **never starts**
emits no failure metric at all, so `job-failed` cannot see it; `queue-liveness`
can, because it measures the age of the work rather than the result of a run.
That is the shape 2026-08-16 actually had.

Policies are matched by what they **watch**, never by their display name: a
renamed policy still pages, and a policy renamed to look right while watching
nothing is the exact failure this file exists to prevent. Each must also be
enabled and reach a live channel — "it exists" is the weakest of the three
conditions and the easiest to mistake for the whole answer.

### Create what is missing

```
PROJECT=doug-prod0 api/deploy/monitoring.sh apply
```

Creates only what is absent. It never modifies and never deletes, so a policy
someone deliberately retuned survives it.

It will not create the notification channel. An email channel needs a human to
confirm the address, which is founder-only, and every policy created without
one would fire into nothing:

```
gcloud beta monitoring channels create --project=doug-prod0 \
  --display-name="Andrew (founder)" --type=email \
  --channel-labels=email_address=<address>
```

Confirm the mail that follows, then run `apply`.

### Do not "fix" the queue-liveness condition

Its threshold reads `COMPARISON_GT` against `1` on `check_passed`, which is a
boolean — so out of context it looks like a condition that can never fire. It
is not. The aggregation is `REDUCE_COUNT_FALSE`, making the compared value the
number of checkers reporting failure; this is Cloud Monitoring's canonical
uptime shape and means "more than one checker sees it down". Changing it to
`COMPARISON_LT` silences the alert.

### When queue-liveness fires

`/healthz/queues` answers 503, so either a lane is genuinely behind or the API
cannot answer at all. Read the payload first — it names the lane, the age, and
the bar it was measured against:

```
curl -s https://<doug-api host>/healthz/queues | python3 -m json.tool
```

Then `GET /v1/health` (operator token) for the counts behind that age, and
`/jobs` in the console for the rows. **Mute nothing.** The one time this alert
has fired so far it was correct: 21 outcome jobs overdue behind a green daily
adjudicator, which is #261.

The bars live in `api/doug/api.py` beside the route that pages on them, and are
served in both `/healthz/queues` and `/v1/health` so the console grades rows
against the same numbers. Do not add a second copy anywhere.

### When reader-fallback fires

An LLM read degraded to the deterministic score. This is contracted behaviour
and therefore silent everywhere else: the check run renders, CI stays green,
and only a reasons row says the deep read is gone — which is exactly why it
pages (#274). Treat one firing as "the reader is down" until proven otherwise.

The cause is in the log line the metric counted — its tail carries the SDK
error verbatim:

```
gcloud logging read 'resource.labels.service_name="doug-api"
  AND textPayload:"reader fell back to deterministic"' \
  --project doug-prod0 --freshness 1d --format='value(textPayload)'
```

Read the error against the transport the service is actually on
(`DOUG_READER_TRANSPORT` on the running revision):

- **anthropic** — a billing error means the console balance hit zero; top it
  up. The balance is a clock, not a fault (ADR-0029).

  An *authentication* error is a federation failure, not a dead key: under
  ADR-0030 this service holds no key and proves its identity with a
  Google-signed token for `doug-api-sa`. Read the deny reason on the Console's
  **Workload identity → History** tab — it names the cause where the log line
  cannot. The usual suspects are a dropped `ANTHROPIC_FEDERATION_RULE_ID` (or
  its two siblings) on the revision, an archived rule or service account, and
  a rule edited so its `sub`/`email`/`audience` no longer match the workload.

  Emergency credential rollback, no deploy — the secret and its IAM binding are
  kept for this:

  ```
  gcloud run services update doug-api --project doug-prod0 --region us-central1 \
    --update-secrets ANTHROPIC_API_KEY=doug-anthropic-key:latest
  ```

  The key outranks federation in SDK precedence, so this takes effect on the
  next revision with no code change. Undo it with `--remove-secrets
  ANTHROPIC_API_KEY`; never by editing `deploy/gcp.sh`, whose *absence* of that
  mount is pinned by test.

  **This rollback is TEMPORARY, by design.** `deploy` passes `--set-secrets`,
  which is declarative and replaces the whole secret block, so the next deploy
  — including any merge to main — drops the mount and returns the service to
  federation. That is deliberate and is not a defect to fix: a mount preserved
  across deploys would be a key silently outranking federation forever, unseen
  in any diff, which is the exact hazard ADR-0030 exists to close. So treat the
  mount as an incident measure with a clock on it: fix the federation
  configuration, or re-apply the command after each deploy until you have.
  If a deploy lands while the mount is doing real work, the reader-fallback
  alert fires again rather than the reader going quiet.
- **vertex** — a 404 is the region not serving the model, a 429 is zero
  throughput quota (#274), a 400 on every read is the request shape (#275).
  Rollback is `DOUG_READER_TRANSPORT=anthropic` on the running service — an
  env change, no deploy — and it works only while the Anthropic key has
  balance.

The same `(paid read)` stderr lines that sit beside these carry per-read token
counts; they are the evidence the spend caps in `reader.py` are tuned from.

## Vertex capacity for the reader (Claude 5)

Recorded from #274 so nobody re-derives it. Model Garden access and throughput
quota are separate grants: access makes a model resolve (404 → 429), quota
makes it serve (429 → 200/400). `claude-opus-5` resolves for this project in
exactly `us-east5`, `us-central1`, `europe-west4`; `global` 404s. The console
shows **no quota rows at all** for 5-family base models, so the console's
"Edit quota" path cannot file the request — the Cloud Quotas API can, and it
accepts the 5-family dimensions:

```
gcloud beta quotas preferences create --project=doug-prod0 \
  --service=aiplatform.googleapis.com \
  --quota-id=OnlinePredictionInputTokensPerMinutePerRegionPerBaseModel \
  --dimensions=region=us-central1,base_model=anthropic-claude-opus-5 \
  --preferred-value=100000 --email=<founder email> \
  --justification="..." --preference-id=claude-opus-5-input-us-central1
```

The three quota IDs that matter (per region, per `base_model`, both
`anthropic-claude-opus-5` and `anthropic-claude-sonnet-5`):
`OnlinePredictionInputTokensPerMinutePerRegionPerBaseModel` (floor ~50k/min —
one read is ~30k input tokens), `OnlinePredictionOutputTokensPerMinutePerRegionPerBaseModel`
(floor ~6k/min — `MAX_TOKENS` is 6,000), and
`OnlinePredictionRequestsPerMinutePerProjectPerRegionPerBaseModel`.

Track with `gcloud beta quotas preferences list --project=doug-prod0`; a grant
shows as `grantedValue` moving off 0. Confirm on the wire with the empty-body
probe (`vertex_preflight` in `deploy/gcp.sh` is the same check): 429 means no
quota, 400 means quota landed and the deploy gate will pass.

## Hosted Example Pack cohort

This lane reuses the IAM-gated `doug-console` and the existing review worker. It
does not alter WorkOS, AuthKit, browser sessions, login redirects, or the public
web service. Every command below is explicit; normal `deploy`, `web`, and
`console` commands neither provision nor enable capture.

### One-time setup (requires explicit production approval)

Choose a globally unique bucket in the same region as the API, then run:

```bash
export PROJECT=doug-prod0
export REGION=us-central1
export DOUG_EXAMPLE_PACK_BUCKET=<private-bucket-name>
cd api
./deploy/gcp.sh example-pack-setup
```

This creates the purpose token if absent, creates or reuses the bucket only
after verifying its region, STANDARD storage class, uniform bucket-level
access, and enforced public-access prevention, then applies a 90-day lifecycle.
It grants `doug-api-sa` only object creator and viewer. It grants
`doug-console-sa` access to the purpose token, not to the bucket. Capture
remains off.

Before enabling, inspect the receipts rather than relying on command success:

```bash
gcloud storage buckets describe "gs://$DOUG_EXAMPLE_PACK_BUCKET" \
  --project "$PROJECT" --format=json
gcloud storage buckets get-iam-policy "gs://$DOUG_EXAMPLE_PACK_BUCKET" \
  --project "$PROJECT" --format=json
gcloud secrets get-iam-policy doug-example-pack-token \
  --project "$PROJECT" --format=json
```

Verify the location, uniform bucket-level access, public access prevention,
lifecycle rule, and exact principals. Google Cloud Data Access logs are
disabled by default for many services. Enabling them changes project-wide audit
policy, so `example-pack-setup` deliberately does not do it. Review and apply
that policy separately before the cohort if read/write audit queries are a
required receipt.

### Enable one bounded cohort

Use a clean checkout of the exact revision being evaluated. Set explicit
stable GitHub installation/repository IDs; names are not allowlist identity.

```bash
export DOUG_EXAMPLE_PACK_SOURCE_ROOT=/absolute/path/to/clean/checkout
export DOUG_APPLICATION_REVISION=$(git -C "$DOUG_EXAMPLE_PACK_SOURCE_ROOT" rev-parse HEAD)
export DOUG_EXAMPLE_PACK_BUCKET=<private-bucket-name>
export DOUG_EXAMPLE_PACK_COHORT=doug-dogfood-YYYY-MM
export DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT=YYYY-MM-DDTHH:MM:SSZ
export DOUG_EXAMPLE_PACK_CAPTURE_UNTIL=YYYY-MM-DDTHH:MM:SSZ
export DOUG_EXAMPLE_PACK_INSTALLATION_IDS=<numeric-id[,numeric-id]>
export DOUG_EXAMPLE_PACK_REPOSITORY_IDS=<numeric-id[,numeric-id]>
export DOUG_EXAMPLE_PACK_ADJUDICATOR=andrew
./deploy/gcp.sh example-pack-enable
```

The command rejects a dirty checkout, a revision mismatch, invalid IDs, or an
invalid/reversed UTC window before calling Cloud Run. It updates only the API
with capture configuration, while both API and console receive the separate
Example Pack token. The console gets no capture flag or storage permission.

An ordinary API deployment preserves an existing cohort's bucket, cohort ID,
adjudicator, and purpose-token binding; an ordinary console deployment
preserves only the purpose-token binding. Neither deploy carries capture
admission settings, so ordinary deploys close new evidence writes while stored
cohorts remain readable. If capture must continue inside the approved window,
re-run `example-pack-enable` with the full validated contract. Merge-to-main CI
still performs no bucket, IAM, secret creation, or audit-policy mutation.

Reach the hosted workbench through the existing IAM proxy:

```bash
gcloud run services proxy doug-console \
  --project "$PROJECT" --region "$REGION"
```

### Close and verify a cohort

At the window boundary, disable new capture, allow already admitted review jobs
to finish, and inspect cohort completeness in the console:

```bash
./deploy/gcp.sh example-pack-disable
```

Do not treat a scorecard as a cohort result until availability is `complete`
and both `missing` and `extra` are empty. The terminal-start-or-membership
boundary handles normal retries, but it cannot reconstruct an earlier failed
capture whose only terminal retry began after the window. Queue drain is the
operational closure for that edge.

If Data Access logging was separately enabled, preserve the cohort-window
object create/read query and its query parameters as a rollout receipt. Do not
claim an access-audit receipt from Admin Activity logs alone.

### Incident response

First stop new evidence writes with `example-pack-disable`. If containment
requires revocation, remove the two bucket roles from `doug-api-sa` and revoke
the purpose-token secret bindings. Preserve the bucket objects, Cloud Run
revision/configuration, and available audit logs for investigation. Deletion,
retention override, and legal hold are separate destructive decisions; no
Example Pack command automates them.

## Tenant API keys

### Provisioning the pepper (one-time, BEFORE the first deploy)

`deploy()` binds `DOUG_TOKEN_PEPPER=doug-token-pepper:latest` in
`--set-secrets`, but only `setup()` creates that secret. Cloud Run refuses a
revision that references a missing secret, so a deploy in a project where
setup was never re-run after this feature landed **fails outright — the
revision never starts** (it does not degrade to 503; that failure mode only
applies when the secret exists but is empty/malformed). Run the gcp.sh setup
step once per project — or create the secret by hand:

    python3 -c "import base64,secrets,sys;sys.stdout.write(base64.b64encode(secrets.token_bytes(32)).decode())" \
      | gcloud secrets create doug-token-pepper --data-file=- --project "$PROJECT"

before the first deploy that includes the tenant-keys feature.

Note the `sys.stdout.write` — a `print()` here stores its trailing newline
INSIDE the secret (45 bytes, not 44), and that is exactly how prod 503'd
every mint on 2026-08-05. The app now strips surrounding whitespace before
decoding, so a newline-bearing secret works — but cut them clean anyway,
and `gcloud secrets versions access latest --secret doug-token-pepper | wc -c`
answering 44 is the quick health check. Env-var secrets bound `:latest`
resolve at INSTANCE start, so after adding a version, roll a new revision
(or wait out scale-to-zero) before expecting the change.

### Break-glass: revoke a tenant's keys (operator, SQL)

Soft revoke — rows are audit history, never DELETE:

    UPDATE installation_tokens SET revoked_at = NOW()
    WHERE installation_id = <id> AND revoked_at IS NULL;

Effective on the tenant's next request (resolve has no cache).

### Pepper rotation (rolling — never a flag-day)

1. Create the next secret version: `DOUG_TOKEN_PEPPER_V2` (base64, exactly
   32 bytes), bind it in gcp.sh's --set-secrets alongside V1.
2. Deploy. New mints now write hash_version=2; existing keys keep verifying
   under V1.
3. When no live rows carry hash_version=1
   (`SELECT COUNT(*) FROM installation_tokens WHERE hash_version=1 AND revoked_at IS NULL`),
   drop the V1 binding.

Pepper versions must be configured contiguously: `_current_hash_version()`
scans up from 1 and stops at the first gap, silently — a V3 binding with no
V2 is never reached and is ignored, with no error raised anywhere.

Never remove a pepper version that live rows still reference — those keys
would die unverifiable (fail closed, not fail open).

### Exit gate: the second-account isolation proof

ROADMAP § MT's exit gate — "a second installation on a different account
reads only its own rows, proven against the real ledger" — is executable:
`api/deploy/prove-isolation.sh` (env vars documented in its header). Order
matters; each step depends on the one before it:

1. Pepper provisioned (section above) and the tenant-keys build deployed.
2. MT0 clean: redeliver the `installation` / `installation_repositories`
   events for the EXISTING installation; a cold start printing zero
   `doug: DRIFT` lines is the confirmation.
3. App visibility → public (App settings → Advanced), then install Doug on
   the second account, selecting at least one repo.
4. Review at least one PR on that repo (open one, or redeliver a recent
   `pull_request` event) — the proof refuses to pass on an empty queue,
   because an empty tenant view proves nothing about isolation.
5. Run the script. Every assertion must pass; the script revokes its own
   proof keys as its final assertions, so it leaves no live credentials.

### MT0-class drift

Startup logs one or both of these warnings; both mean a webhook never fired
and both are fixed the same way — redeliver the missing event (App settings
→ Advanced → Recent Deliveries). Do NOT uninstall/reinstall — GitHub mints a
new installation_id and orphans every verdict.

- `doug: DRIFT — verdicts reference N installation(s)...`: the `installation`
  webhook never populated the ledger. Redeliver `installation`.
- `doug: DRIFT — N repo(s) referenced by verdicts have no installation_repos
  row...`: the `installation_repositories` webhook never fired for those
  repos, so their tenant cannot see those verdicts. Redeliver
  `installation_repositories`.

## Service identities

Every workload in doug-prod0 runs as its own service account:

| Workload | Runs as |
|---|---|
| `doug-api` (Run service) | `doug-api-sa` |
| `doug-web` (Run service) | `doug-web-sa` |
| `doug-console` (Run service) | `doug-console-sa` |
| `doug-adjudicator`, `doug-outcome-reconciler` (Run jobs) | `doug-adjudicator-sa` |
| `doug-adjudicator-daily` (Scheduler) | `doug-scheduler-sa` |
| Cloud Build | the **default compute SA** — see #161 |

### Audit the default compute SA's secret access (repeatable)

The default compute SA holds `roles/editor` on doug-prod0, so anything that
inherits it inherits editor. `roles/editor` does not carry
`secretmanager.versions.access`, which is why the accessor bindings were
granted separately in the Task-10 era and had to be revoked separately too.

Run this sweep after any `gcp.sh setup`, and whenever a service changes
identity. It should print `clean:` for every secret:

    PROJECT=doug-prod0
    PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
    CSA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
    for s in $(gcloud secrets list --project "$PROJECT" --format='value(name.basename())'); do
      if gcloud secrets get-iam-policy "$s" --project "$PROJECT" \
           --format='value(bindings.members)' | grep -q "$CSA"; then
        echo "LEFTOVER: $s"
      else
        echo "clean: $s"
      fi
    done

`name.basename()` is not decoration. The API field is the **full resource
path** — `gcloud secrets list --format='json(name)'` returns
`projects/<number>/secrets/<id>` — and a bare `value(name)` prints the short id
only because `secrets list` applies a command-specific display transform. The
two are byte-identical on SDK 579.0.0; `basename()` is what keeps the loop from
feeding a resource path to `get-iam-policy` if that transform ever changes.

To remove one it finds:

    gcloud secrets remove-iam-policy-binding "$SECRET" --project "$PROJECT" \
      --member="serviceAccount:$CSA" \
      --role=roles/secretmanager.secretAccessor

Redeploy nothing — no Cloud Run service or job uses that identity. Confirm the
readers that remain still serve.

**Do not read an empty Secret Manager audit-log query as proof that a binding
is unused.** doug-prod0 sets no `auditConfigs`, so Data Access logging is off
and `AccessSecretVersion` never appears for any principal. The workload table
above is the evidence; the logs are not.

### Closed 2026-08-20 (#152)

The sweep was run against all eleven secrets. `doug-api-token` — the binding
this runbook used to chase — never held the default compute SA. Three others
did, and were revoked: `doug-anthropic-key`, `doug-database-url`,
`doug-webhook-secret`. `doug-web-sa`'s own accessor on `doug-api-token` went
with them, dead since Front Door Phase 0 dropped that secret from `web()`.

`doug-web` mounts five secrets, not none: the four AuthKit values plus
`doug-install-flow-secret`. An earlier draft of this section claimed it held
no secret at all, which stopped being true at Phase 0.

## Sign-in scope derivation

A repository scope is derived once, at sign-in, from the provider token
`authkit-nextjs` hands to `handleAuth`'s `onSuccess` and nowhere else
(`web/lib/entitlements.ts`). The token is used and discarded; the derived scope
carries `derived_at` and dies after `entitlements.TTL` — 8 hours
(`api/doug/entitlements.py:77`).

Two different failures leave a person with a stale scope and an expired-scope
dashboard, and they need different responses. Both are one structured line on
stderr, which Cloud Run parses into a structured entry.

| Event | Severity | Means |
|---|---|---|
| `entitlement_derivation_failed` | ERROR | Doug had a token, called the API, and gave up after two attempts. Usually a cold start or the API being down. |
| `entitlement_derivation_skipped` | WARNING | The sign-in carried no provider token at all, so nothing was attempted. |

### Read the skipped-derivation rate (repeatable)

A `Password` or other non-provider sign-in reaching the skip is correct and
expected, so the event alone is not actionable. **The signal is a `GitHubOAuth`
sign-in landing there** — that means the callback returned no `oauthTokens`,
and every affected person sees the expired-scope screen until something
changes:

    gcloud logging read \
      'resource.type="cloud_run_revision"
       resource.labels.service_name="doug-web"
       jsonPayload.event="entitlement_derivation_skipped"
       jsonPayload.provider="GitHubOAuth"' \
      --project doug-prod0 --freshness=24h \
      --format='value(timestamp, jsonPayload.workos_user_id)'

Any rows at all are worth acting on. Two causes produce them, and no file in
this repo can tell them apart:

1. **WorkOS did not round-trip the provider.** Confirmed to happen on a re-auth
   for an already-signed-in user — see #167. `prompt=consent` is honored at the
   WorkOS layer and never reaches GitHub, which accepts only
   `prompt=select_account`.
2. **The WorkOS GitHub connection has "Return GitHub OAuth tokens" turned off.**
   A dashboard toggle with no representation in code, so it has to be read by
   hand: **Authentication > OAuth providers > GitHub > Manage**, under
   **OAuth tokens**.

### The WorkOS GitHub connection, as configured

Read 2026-08-21 from the dialog above. Recorded here because none of it is
visible from any file in this repo, and #167 turned on knowing it:

| Field | Value |
|---|---|
| GitHub OAuth | Enabled |
| Return GitHub OAuth tokens | **Checked** |
| GitHub Client ID | begins `Iv23li` — a GitHub **App**, not an OAuth App |
| GitHub Client Secret | set |
| Scopes | `user:email` only |

**The Scopes field is expected to be inert, and that expectation is load-bearing
enough to write down.** Scopes apply only to GitHub OAuth Apps; a GitHub App
takes its permissions from the app itself
(https://workos.com/docs/integrations/github-oauth). The client ID's `Iv`
prefix marks a GitHub App, and the decisive evidence is internal:
`api/doug/entitlements.py` calls `GET /user/installations`, which an OAuth App
token answers with 403 — recorded at
`docs/superpowers/specs/2026-08-08-front-door-design.md:84-88`. Derivation
works, so the token in hand is a user-to-server GitHub App token.

If WorkOS ever routed this connection as an OAuth App, a `user:email`-only token
would fail that call for every user at once, and it would surface here as either
a derivation failure or the skip event above. Check the client ID prefix before
chasing anything else.

To confirm a specific sign-in did or did not refresh the scope, GitHub's own
security log is authoritative. A Doug user-token mint appears as a pair at the
same second — `oauth_access.create` with the user's IP, and
`GitHub System – oauth_access.regenerate` — under the Dougs Review GitHub App.
No pair means no token was minted, whatever the app believes.
