# Operations runbook

## Tenant API keys

### Provisioning the pepper (one-time, BEFORE the first deploy)

`deploy()` binds `DOUG_TOKEN_PEPPER=doug-token-pepper:latest` in
`--set-secrets`, but only `setup()` creates that secret. Cloud Run refuses a
revision that references a missing secret, so a deploy in a project where
setup was never re-run after this feature landed **fails outright — the
revision never starts** (it does not degrade to 503; that failure mode only
applies when the secret exists but is empty/malformed). Run the gcp.sh setup
step once per project — or create the secret by hand:

    python3 -c "import base64,secrets;print(base64.b64encode(secrets.token_bytes(32)).decode())" \
      | gcloud secrets create doug-token-pepper --data-file=- --project "$PROJECT"

before the first deploy that includes the tenant-keys feature.

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
