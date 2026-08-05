# Operations runbook

## Tenant API keys

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
