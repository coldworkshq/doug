# Operations runbook

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
