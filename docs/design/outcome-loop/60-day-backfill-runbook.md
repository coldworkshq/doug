# Production runbook — 60-day outcome-job catch-up

**Status:** EXECUTED IN PRODUCTION 2026-08-11 (Task 7) — success path §1-§4,
§6-§9; receipt `workspace/research/task7-receipt-20260811T224751Z`. Two §6
attempts aborted before psql ran (psql missing from PATH; artifacts preserved
as `*.attempt1-no-psql`). Kept for any future environment; a re-run needs its
own authorization and a fresh receipt directory.

This is the one-time repair for historical registered-installation merges that
have a 14-day `outcome_jobs` row but no 60-day sibling. Future merges receive
both rows atomically from merge ingestion. The repair copies the stored merge
facts, sets `window_days = 60`, and derives `due_at` from `merged_at`; it does
not change the publication metric, windows, censoring, cadence, or denominator.

Every `bash` block below starts its own `set -euo pipefail` context. Run all
operator blocks except §2 in one primary terminal, in order. Do not close that
terminal or unset its variables. A new terminal must initialize fail-fast mode
again and must not reconstruct receipt paths from memory. The Cloud SQL proxy
has its own explicitly labeled terminal in §2 and runs no operator commands.

Do not use Cloud SQL Studio temporary tables. The SQL audit is a durable file
run in a fresh `psql` session before and after the Job. Keep the proxy running
until the final audit and Scheduler check are complete.

Success means all of the following are true:

- the checkout is clean and the API and Job use the same immutable image;
- the Job carries the hash of the committed `LOCKED` pre-registration;
- the dry-run reports no mismatched pairs and no registered 60-day orphans;
- the Scheduler is paused and no `doug-adjudicator` execution is nonterminal
  before the insert-select;
- the manifest names exactly the inserted, untouched rows before adjudication;
- all three pair-violation queries and the complete-identity audit return zero
  rows before and after the manual Job;
- the final CLI audit reports zero missing rows, mismatches, and orphans; and
- the Scheduler is restored to `ENABLED`, `0 3 * * *`, `Etc/UTC`.

## 1. Initialize the primary operator terminal and deploy from `main`

Use the normal checkout, not an implementation worktree. The receipt directory
is unique and must never be reused. Every artifact path for this attempt lives
under it, including a failed or partial apply artifact.

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo

PROJECT=doug-prod0
REGION=us-central1
API_SERVICE=doug-api
ADJUDICATOR_JOB=doug-adjudicator
SCHEDULER_JOB=doug-adjudicator-daily

git fetch origin main
git switch main
git pull --ff-only origin main
test -z "$(git status --short)"
DEPLOYED_COMMIT=$(git rev-parse HEAD)

RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
RECEIPT_DIR="/tmp/doug-60-day-backfill-$RUN_ID"
test ! -e "$RECEIPT_DIR"
mkdir -m 700 "$RECEIPT_DIR"

COMMIT_RECEIPT_PATH="$RECEIPT_DIR/commit.txt"
DEPLOY_OUTPUT_PATH="$RECEIPT_DIR/deploy.log"
JOB_CONFIG_PATH="$RECEIPT_DIR/deployed-job.json"
DEPLOY_IDENTITY_PATH="$RECEIPT_DIR/deploy-identity.json"
DRY_REPORT_PATH="$RECEIPT_DIR/dry-run.json"
APPLY_OUTPUT_PATH="$RECEIPT_DIR/apply-output.log"
BACKFILL_MANIFEST_PATH="$RECEIPT_DIR/manifest.json"
MANIFEST_VERIFY_PATH="$RECEIPT_DIR/manifest-verification.json"
AUDIT_SQL_PATH="$RECEIPT_DIR/outcome-audit.sql"
PRE_JOB_SQL_RECEIPT_PATH="$RECEIPT_DIR/pre-job-sql.log"
EXECUTION_RESOURCE_PATH="$RECEIPT_DIR/job-execution.json"
EXECUTION_NAME_PATH="$RECEIPT_DIR/job-execution-name.txt"
EXECUTION_COMMAND_OUTPUT_PATH="$RECEIPT_DIR/job-execute-stdout.json"
EXECUTION_COMMAND_ERROR_PATH="$RECEIPT_DIR/job-execute-stderr.log"
ROLLBACK_FORBIDDEN_PATH="$RECEIPT_DIR/rollback-forbidden"
DRAIN_SUMMARY_PATH="$RECEIPT_DIR/drain-summary.json"
POST_JOB_SQL_RECEIPT_PATH="$RECEIPT_DIR/post-job-sql.log"
FINAL_REPORT_PATH="$RECEIPT_DIR/final-dry-run.json"
FINAL_SCHEDULER_PATH="$RECEIPT_DIR/final-scheduler.json"

DEPLOY_VERIFIED=0
QUIESCENCE_VERIFIED=0
APPLY_STATE=not-run
RECOVERY_STATE=not-classified
PRE_JOB_AUDIT_VERIFIED=0
ROLLBACK_FORBIDDEN=0
JOB_EXECUTION_VERIFIED=0
POST_JOB_AUDIT_VERIFIED=0

printf '%s\n' "$DEPLOYED_COMMIT" | tee "$COMMIT_RECEIPT_PATH"

cd api
PROJECT="$PROJECT" REGION="$REGION" bash deploy/gcp.sh deploy \
  2>&1 | tee "$DEPLOY_OUTPUT_PATH"

API_IMAGE=$(gcloud run services describe "$API_SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --format='value(spec.template.spec.containers[0].image)')
gcloud run jobs describe "$ADJUDICATOR_JOB" \
  --project "$PROJECT" --region "$REGION" \
  --format=json > "$JOB_CONFIG_PATH"
JOB_IMAGE=$(jq -er \
  '.spec.template.spec.template.spec.containers[0].image' \
  "$JOB_CONFIG_PATH")
LOCAL_PREREG_HASH=$(python3 -c \
  "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('../docs/design/outcome-loop/publication-preregistration.md').read_bytes()).hexdigest())")
JOB_PREREG_HASH=$(jq -er \
  '.spec.template.spec.template.spec.containers[0].env[] | select(.name=="DOUG_PREREG_HASH") | .value' \
  "$JOB_CONFIG_PATH")
test "$API_IMAGE" = "$JOB_IMAGE"
test "$LOCAL_PREREG_HASH" = "$JOB_PREREG_HASH"

jq -n \
  --arg commit "$DEPLOYED_COMMIT" \
  --arg api_image "$API_IMAGE" \
  --arg job_image "$JOB_IMAGE" \
  --arg prereg_hash "$JOB_PREREG_HASH" \
  '{commit: $commit, api_image: $api_image, job_image: $job_image,
    prereg_hash: $prereg_hash}' > "$DEPLOY_IDENTITY_PATH"
DEPLOY_VERIFIED=1
```

Any failure above ends the attempt before pause or apply. Do not continue with
a dirty checkout, failed deploy, different image, or different lock hash.

## 2. Start the Cloud SQL proxy in a separate proxy terminal

This is a new terminal, so it initializes its own fail-fast context and only
runs the proxy. Do not paste any later operator block into this terminal.

```bash
set -euo pipefail
PROJECT=doug-prod0
REGION=us-central1
INSTANCE=doug-ledger
cloud-sql-proxy "$PROJECT:$REGION:$INSTANCE" --port 5433
```

Leave that process running. Return to the primary operator terminal for every
remaining section.

## 3. Dry-run, pause, and prove Job quiescence

The captured `EXPECTED_MISSING` is the write guard; do not edit it after the
dry-run. From pause through the final resume, no operator may manually invoke
`doug-adjudicator`; stop if that maintenance boundary cannot be guaranteed. The
loop preserves every execution-list response. It never cancels an execution:
if one is pending or running, wait for it to complete or interrupt the loop and
stop with the Scheduler paused.

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo/api
test "$DEPLOY_VERIFIED" = 1
test -d "$RECEIPT_DIR"
test ! -e "$DRY_REPORT_PATH"
test ! -e "$BACKFILL_MANIFEST_PATH"

uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp "$PROJECT" --dry-run | tee "$DRY_REPORT_PATH"
EXPECTED_MISSING=$(jq -er '.missing' "$DRY_REPORT_PATH")
test "$EXPECTED_MISSING" -ge 0
test "$(jq -er '.mismatches | length' "$DRY_REPORT_PATH")" = 0
test "$(jq -er '.orphan_60' "$DRY_REPORT_PATH")" = 0

test "$(gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" --format='value(state)')" = ENABLED
gcloud scheduler jobs pause "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION"

PAUSED_SCHEDULER_PATH="$RECEIPT_DIR/paused-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$PAUSED_SCHEDULER_PATH"
test "$(jq -er '.state' "$PAUSED_SCHEDULER_PATH")" = PAUSED
test "$(jq -er '.schedule' "$PAUSED_SCHEDULER_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$PAUSED_SCHEDULER_PATH")" = Etc/UTC

while true; do
  QUIESCENCE_JSON_PATH="$RECEIPT_DIR/quiescence-executions-$(date -u +%Y%m%dT%H%M%SZ).json"
  test ! -e "$QUIESCENCE_JSON_PATH"
  gcloud run jobs executions list \
    --job "$ADJUDICATOR_JOB" \
    --project "$PROJECT" --region "$REGION" \
    --format=json > "$QUIESCENCE_JSON_PATH"
  test "$(jq -r 'type' "$QUIESCENCE_JSON_PATH")" = array
  NONTERMINAL_EXECUTIONS=$(jq \
    '[.[] | select(.status.completionTime == null)] | length' \
    "$QUIESCENCE_JSON_PATH")
  if [ "$NONTERMINAL_EXECUTIONS" -eq 0 ]; then
    break
  fi
  printf 'Scheduler is PAUSED; waiting for %s nonterminal execution(s). Do not cancel automatically.\n' \
    "$NONTERMINAL_EXECUTIONS" >&2
  sleep 30
done
QUIESCENCE_VERIFIED=1
```

The selected `QUIESCENCE_JSON_PATH` is the final zero-nonterminal receipt;
earlier loop receipts remain in the same directory.

## 4. Recheck PAUSED, apply, and verify the manifest

This block deliberately catches the apply pipeline status so its output and
any manifest artifact survive for classification. `pipefail` makes a failing
CLI fail the pipeline even though `tee` succeeds. A failed or invalid apply is
never retried at the same manifest path.

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo/api
test "$QUIESCENCE_VERIFIED" = 1
test ! -e "$APPLY_OUTPUT_PATH"
test ! -e "$BACKFILL_MANIFEST_PATH"

PRE_APPLY_QUIESCENCE_PATH="$RECEIPT_DIR/pre-apply-executions.json"
test ! -e "$PRE_APPLY_QUIESCENCE_PATH"
gcloud run jobs executions list \
  --job "$ADJUDICATOR_JOB" \
  --project "$PROJECT" --region "$REGION" \
  --format=json > "$PRE_APPLY_QUIESCENCE_PATH"
test "$(jq -r 'type' "$PRE_APPLY_QUIESCENCE_PATH")" = array
test "$(jq '[.[] | select(.status.completionTime == null)] | length' \
  "$PRE_APPLY_QUIESCENCE_PATH")" = 0

PRE_APPLY_SCHEDULER_PATH="$RECEIPT_DIR/pre-apply-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$PRE_APPLY_SCHEDULER_PATH"
test "$(jq -er '.state' "$PRE_APPLY_SCHEDULER_PATH")" = PAUSED
test "$(jq -er '.schedule' "$PRE_APPLY_SCHEDULER_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$PRE_APPLY_SCHEDULER_PATH")" = Etc/UTC
```

Run apply immediately after those final `PAUSED` and zero-nonterminal checks,
in a low-traffic maintenance window; do not pause after the checks. While apply
holds its locks, merge-webhook database writes can wait and an HTTP request that
times out may be redelivered. Those locks fence the complete eligibility
predicate and must not be removed or weakened. An exception while the guarded
database transaction is active rolls it back, but a failed or unverifiable
apply may nevertheless have committed; preserve its artifacts and follow the
failure classification in §5.

```bash

APPLY_COMMAND_OK=0
if uv run python scripts/backfill_outcome_jobs.py \
    --from-gcp "$PROJECT" --apply \
    --expect-missing "$EXPECTED_MISSING" \
    --manifest "$BACKFILL_MANIFEST_PATH" \
    2>&1 | tee "$APPLY_OUTPUT_PATH"; then
  APPLY_COMMAND_OK=1
fi

APPLY_STATE=needs-recovery
if [ "$APPLY_COMMAND_OK" -eq 1 ] \
  && test "$(jq -er '.inserted' "$APPLY_OUTPUT_PATH")" = "$EXPECTED_MISSING" \
  && uv run python scripts/backfill_outcome_jobs.py \
       --from-gcp "$PROJECT" --verify-manifest \
       --expect-count "$EXPECTED_MISSING" \
       --manifest "$BACKFILL_MANIFEST_PATH" \
       2>&1 | tee "$MANIFEST_VERIFY_PATH" \
  && test "$(jq -er '.verified_untouched' "$MANIFEST_VERIFY_PATH")" = "$EXPECTED_MISSING"; then
  APPLY_STATE=verified
fi
printf 'APPLY_STATE=%s\n' "$APPLY_STATE"
```

If `APPLY_STATE=verified`, skip §5 and continue to §6. If it is
`needs-recovery`, do not run apply again, do not execute the Job, and run §5
now. Preserve `APPLY_OUTPUT_PATH` and any file at `BACKFILL_MANIFEST_PATH`.

## 5. Classify a failed or unverifiable apply

Rollback is not the default. This read-only block classifies the database and,
only for a committed-like state, asks the guarded CLI to prove that the exact
complete manifest rows are still untouched.

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo/api
test "$APPLY_STATE" = needs-recovery
test "$ROLLBACK_FORBIDDEN" = 0
test ! -e "$ROLLBACK_FORBIDDEN_PATH"

FAILED_APPLY_SCHEDULER_PATH="$RECEIPT_DIR/failed-apply-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$FAILED_APPLY_SCHEDULER_PATH"
test "$(jq -er '.state' "$FAILED_APPLY_SCHEDULER_PATH")" = PAUSED
test "$(jq -er '.schedule' "$FAILED_APPLY_SCHEDULER_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$FAILED_APPLY_SCHEDULER_PATH")" = Etc/UTC

FAILED_APPLY_ANALYSIS_PATH="$RECEIPT_DIR/failed-apply-analysis.json"
test ! -e "$FAILED_APPLY_ANALYSIS_PATH"
RECOVERY_STATE=investigate
ANALYSIS_COMMAND_OK=0
if uv run python scripts/backfill_outcome_jobs.py \
    --from-gcp "$PROJECT" --dry-run | tee "$FAILED_APPLY_ANALYSIS_PATH"; then
  ANALYSIS_COMMAND_OK=1
fi

if [ "$ANALYSIS_COMMAND_OK" -eq 1 ] \
  && jq -e '
       (.missing | type) == "number"
       and (.mismatches | type) == "array"
       and (.orphan_60 | type) == "number"
     ' "$FAILED_APPLY_ANALYSIS_PATH" >/dev/null; then
  ANALYSIS_MISSING=$(jq -er '.missing' "$FAILED_APPLY_ANALYSIS_PATH")
  ANALYSIS_MISMATCHES=$(jq -er '.mismatches | length' "$FAILED_APPLY_ANALYSIS_PATH")
  ANALYSIS_ORPHANS=$(jq -er '.orphan_60' "$FAILED_APPLY_ANALYSIS_PATH")

  if [ "$ANALYSIS_MISSING" -eq "$EXPECTED_MISSING" ] \
    && [ "$ANALYSIS_MISMATCHES" -eq 0 ] \
    && [ "$ANALYSIS_ORPHANS" -eq 0 ]; then
    RECOVERY_STATE=no-commit
  elif [ "$ANALYSIS_MISSING" -eq 0 ] \
    && [ "$ANALYSIS_MISMATCHES" -eq 0 ] \
    && [ "$ANALYSIS_ORPHANS" -eq 0 ]; then
    FAILED_APPLY_VERIFY_PATH="$RECEIPT_DIR/failed-apply-manifest-verification.log"
    if uv run python scripts/backfill_outcome_jobs.py \
         --from-gcp "$PROJECT" --verify-manifest \
         --expect-count "$EXPECTED_MISSING" \
         --manifest "$BACKFILL_MANIFEST_PATH" \
         2>&1 | tee "$FAILED_APPLY_VERIFY_PATH" \
      && test "$(jq -er '.verified_untouched' "$FAILED_APPLY_VERIFY_PATH")" = "$EXPECTED_MISSING"; then
      RECOVERY_STATE=committed-untouched
    fi
  fi
fi
printf 'RECOVERY_STATE=%s\n' "$RECOVERY_STATE"
```

The three states are exclusive in this order, including the zero-row case:

- `no-commit`: the original missing count remains and the structural audits
  are clean. Run §5a; rollback is forbidden.
- `committed-untouched`: zero rows are missing and the complete manifest's
  exact rows independently verify untouched. Run §5b.
- `investigate`: a partial count, touched row, missing/unreadable/incomplete
  manifest in committed-like state, or any disagreement. Run §5c and stop.

### 5a. Evidenced no commit: audit, resume, verify, stop

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo/api
test "$RECOVERY_STATE" = no-commit

NO_COMMIT_AUDIT_PATH="$RECEIPT_DIR/no-commit-final-audit.json"
test ! -e "$NO_COMMIT_AUDIT_PATH"
uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp "$PROJECT" --dry-run | tee "$NO_COMMIT_AUDIT_PATH"
test "$(jq -er '.missing' "$NO_COMMIT_AUDIT_PATH")" = "$EXPECTED_MISSING"
test "$(jq -er '.mismatches | length' "$NO_COMMIT_AUDIT_PATH")" = 0
test "$(jq -er '.orphan_60' "$NO_COMMIT_AUDIT_PATH")" = 0

NO_COMMIT_PRE_RESUME_PATH="$RECEIPT_DIR/no-commit-pre-resume-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$NO_COMMIT_PRE_RESUME_PATH"
test "$(jq -er '.state' "$NO_COMMIT_PRE_RESUME_PATH")" = PAUSED
test "$(jq -er '.schedule' "$NO_COMMIT_PRE_RESUME_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$NO_COMMIT_PRE_RESUME_PATH")" = Etc/UTC

gcloud scheduler jobs resume "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION"
NO_COMMIT_SCHEDULER_PATH="$RECEIPT_DIR/no-commit-final-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$NO_COMMIT_SCHEDULER_PATH"
test "$(jq -er '.state' "$NO_COMMIT_SCHEDULER_PATH")" = ENABLED
test "$(jq -er '.schedule' "$NO_COMMIT_SCHEDULER_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$NO_COMMIT_SCHEDULER_PATH")" = Etc/UTC
```

Stop here. Preserve the full receipt directory and start any future attempt
from §1 with a new `RUN_ID`, receipt directory, and manifest path.

### 5b. All rows committed and untouched: guarded rollback, audit, resume, stop

This branch remains before manual Job execution. The rollback command itself
locks and re-verifies every exact manifest row before deleting all or none.

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo/api
test "$RECOVERY_STATE" = committed-untouched
test "$ROLLBACK_FORBIDDEN" = 0
test ! -e "$ROLLBACK_FORBIDDEN_PATH"
test "$(gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" --format='value(state)')" = PAUSED

ROLLBACK_OUTPUT_PATH="$RECEIPT_DIR/rollback.json"
test ! -e "$ROLLBACK_OUTPUT_PATH"
uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp "$PROJECT" --rollback \
  --expect-count "$EXPECTED_MISSING" \
  --manifest "$BACKFILL_MANIFEST_PATH" | tee "$ROLLBACK_OUTPUT_PATH"
test "$(jq -er '.rolled_back' "$ROLLBACK_OUTPUT_PATH")" = "$EXPECTED_MISSING"

POST_ROLLBACK_AUDIT_PATH="$RECEIPT_DIR/post-rollback-audit.json"
test ! -e "$POST_ROLLBACK_AUDIT_PATH"
uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp "$PROJECT" --dry-run | tee "$POST_ROLLBACK_AUDIT_PATH"
test "$(jq -er '.missing' "$POST_ROLLBACK_AUDIT_PATH")" = "$EXPECTED_MISSING"
test "$(jq -er '.mismatches | length' "$POST_ROLLBACK_AUDIT_PATH")" = 0
test "$(jq -er '.orphan_60' "$POST_ROLLBACK_AUDIT_PATH")" = 0

ROLLBACK_PRE_RESUME_PATH="$RECEIPT_DIR/rollback-pre-resume-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$ROLLBACK_PRE_RESUME_PATH"
test "$(jq -er '.state' "$ROLLBACK_PRE_RESUME_PATH")" = PAUSED
test "$(jq -er '.schedule' "$ROLLBACK_PRE_RESUME_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$ROLLBACK_PRE_RESUME_PATH")" = Etc/UTC

gcloud scheduler jobs resume "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION"
ROLLBACK_SCHEDULER_PATH="$RECEIPT_DIR/rollback-final-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$ROLLBACK_SCHEDULER_PATH"
test "$(jq -er '.state' "$ROLLBACK_SCHEDULER_PATH")" = ENABLED
test "$(jq -er '.schedule' "$ROLLBACK_SCHEDULER_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$ROLLBACK_SCHEDULER_PATH")" = Etc/UTC
```

Stop here. Preserve the full receipt directory and start any future attempt
from §1 with a new `RUN_ID`, receipt directory, and manifest path.

### 5c. Investigation state: prove PAUSED and stop

```bash
set -euo pipefail
test "$RECOVERY_STATE" = investigate
INVESTIGATION_SCHEDULER_PATH="$RECEIPT_DIR/investigation-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$INVESTIGATION_SCHEDULER_PATH"
test "$(jq -er '.state' "$INVESTIGATION_SCHEDULER_PATH")" = PAUSED
test "$(jq -er '.schedule' "$INVESTIGATION_SCHEDULER_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$INVESTIGATION_SCHEDULER_PATH")" = Etc/UTC
printf 'STOP: preserve %s; do not apply, roll back, execute, or resume.\n' \
  "$RECEIPT_DIR" >&2
exit 1
```

## Rollback boundary — read before manual execution

**After invoking `gcloud run jobs execute`, rollback is forbidden.** The Job
may have claimed or adjudicated inserted rows even if `gcloud` later exits
nonzero. Any failure from that point keeps the Scheduler paused for
investigation. Resume only after the audited manual-execution path below.

## 6. Create and run the pre-Job SQL audit

This success path is reachable only after the apply and manifest both verify.
The generated SQL file prints every violation row, then raises an error if any
of the four sets is nonempty. `--echo-all` and `tee` spool the exact SQL and
results, while `ON_ERROR_STOP` plus `pipefail` propagate either side's failure.

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo/api
test "$APPLY_STATE" = verified
test "$(gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" --format='value(state)')" = PAUSED

PSQL_DATABASE_URL=$(gcloud secrets versions access latest \
  --secret=doug-database-url --project="$PROJECT" | python3 -c '
import sys
url = sys.stdin.read().strip()
url = url.split("?host=", 1)[0]
url = url.replace("postgresql+psycopg://", "postgresql://")
print(url.replace("@/doug", "@127.0.0.1:5433/doug"))
')
test -n "$PSQL_DATABASE_URL"

test ! -e "$AUDIT_SQL_PATH"
tee "$AUDIT_SQL_PATH" >/dev/null <<'SQL'
-- A registered 14-day job without its 60-day sibling.
SELECT j14.id, j14.installation_id, j14.github_repo_id,
       j14.pr_number, j14.merge_commit_sha
FROM outcome_jobs j14
WHERE j14.window_days = 14
  AND EXISTS (
    SELECT 1 FROM installations i
    WHERE i.installation_id = j14.installation_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM outcome_jobs j60
    WHERE j60.installation_id = j14.installation_id
      AND j60.github_repo_id = j14.github_repo_id
      AND j60.pr_number = j14.pr_number
      AND j60.merge_commit_sha = j14.merge_commit_sha
      AND j60.window_days = 60
  );

-- A registered 60-day job without its 14-day source.
SELECT j60.id, j60.installation_id, j60.github_repo_id,
       j60.pr_number, j60.merge_commit_sha
FROM outcome_jobs j60
WHERE j60.window_days = 60
  AND EXISTS (
    SELECT 1 FROM installations i
    WHERE i.installation_id = j60.installation_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM outcome_jobs j14
    WHERE j14.installation_id = j60.installation_id
      AND j14.github_repo_id = j60.github_repo_id
      AND j14.pr_number = j60.pr_number
      AND j14.merge_commit_sha = j60.merge_commit_sha
      AND j14.window_days = 14
  );

-- A pair whose stored facts or 60-day due date disagree.
SELECT j14.id AS job_14_id, j60.id AS job_60_id,
       j14.merged_at AS merged_at_14, j60.merged_at AS merged_at_60,
       j14.base_ref AS base_ref_14, j60.base_ref AS base_ref_60,
       j60.due_at
FROM outcome_jobs j14
JOIN outcome_jobs j60
  ON j60.installation_id = j14.installation_id
 AND j60.github_repo_id = j14.github_repo_id
 AND j60.pr_number = j14.pr_number
 AND j60.merge_commit_sha = j14.merge_commit_sha
 AND j60.window_days = 60
WHERE j14.window_days = 14
  AND EXISTS (
    SELECT 1 FROM installations i
    WHERE i.installation_id = j14.installation_id
  )
  AND (
    j60.merged_at IS DISTINCT FROM j14.merged_at
    OR j60.base_ref IS DISTINCT FROM j14.base_ref
    OR j60.due_at IS DISTINCT FROM j60.merged_at + INTERVAL '60 days'
  );

-- A done job without exactly one outcome at the full published identity.
SELECT j.id, count(o.id) AS matching_outcomes
FROM outcome_jobs j
LEFT JOIN outcomes o
  ON o.installation_id = j.installation_id
 AND o.github_repo_id = j.github_repo_id
 AND o.pr_number = j.pr_number
 AND o.merge_commit_sha = j.merge_commit_sha
 AND o.window_days = j.window_days
WHERE j.status = 'done'
GROUP BY j.id
HAVING count(o.id) <> 1;

DO $audit$
BEGIN
  IF EXISTS (
    SELECT 1 FROM outcome_jobs j14
    WHERE j14.window_days = 14
      AND EXISTS (
        SELECT 1 FROM installations i
        WHERE i.installation_id = j14.installation_id
      )
      AND NOT EXISTS (
        SELECT 1 FROM outcome_jobs j60
        WHERE j60.installation_id = j14.installation_id
          AND j60.github_repo_id = j14.github_repo_id
          AND j60.pr_number = j14.pr_number
          AND j60.merge_commit_sha = j14.merge_commit_sha
          AND j60.window_days = 60
      )
  ) THEN
    RAISE EXCEPTION 'registered 14-day job is missing its 60-day sibling';
  END IF;

  IF EXISTS (
    SELECT 1 FROM outcome_jobs j60
    WHERE j60.window_days = 60
      AND EXISTS (
        SELECT 1 FROM installations i
        WHERE i.installation_id = j60.installation_id
      )
      AND NOT EXISTS (
        SELECT 1 FROM outcome_jobs j14
        WHERE j14.installation_id = j60.installation_id
          AND j14.github_repo_id = j60.github_repo_id
          AND j14.pr_number = j60.pr_number
          AND j14.merge_commit_sha = j60.merge_commit_sha
          AND j14.window_days = 14
      )
  ) THEN
    RAISE EXCEPTION 'registered 60-day job is missing its 14-day source';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM outcome_jobs j14
    JOIN outcome_jobs j60
      ON j60.installation_id = j14.installation_id
     AND j60.github_repo_id = j14.github_repo_id
     AND j60.pr_number = j14.pr_number
     AND j60.merge_commit_sha = j14.merge_commit_sha
     AND j60.window_days = 60
    WHERE j14.window_days = 14
      AND EXISTS (
        SELECT 1 FROM installations i
        WHERE i.installation_id = j14.installation_id
      )
      AND (
        j60.merged_at IS DISTINCT FROM j14.merged_at
        OR j60.base_ref IS DISTINCT FROM j14.base_ref
        OR j60.due_at IS DISTINCT FROM j60.merged_at + INTERVAL '60 days'
      )
  ) THEN
    RAISE EXCEPTION '14/60 pair facts or due date disagree';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM outcome_jobs j
    LEFT JOIN outcomes o
      ON o.installation_id = j.installation_id
     AND o.github_repo_id = j.github_repo_id
     AND o.pr_number = j.pr_number
     AND o.merge_commit_sha = j.merge_commit_sha
     AND o.window_days = j.window_days
    WHERE j.status = 'done'
    GROUP BY j.id
    HAVING count(o.id) <> 1
  ) THEN
    RAISE EXCEPTION 'done job does not have exactly one full-identity outcome';
  END IF;
END
$audit$;
SQL

test ! -e "$PRE_JOB_SQL_RECEIPT_PATH"
psql "$PSQL_DATABASE_URL" -X --echo-all --set=ON_ERROR_STOP=1 \
  --file="$AUDIT_SQL_PATH" 2>&1 | tee "$PRE_JOB_SQL_RECEIPT_PATH"
PRE_JOB_AUDIT_VERIFIED=1
```

Any SQL row makes the generated `DO` assertion fail and leaves the Scheduler
paused. Do not execute the Job.

## 7. Execute once and capture the execution, logs, and `DrainSummary`

The rollback boundary closes durably immediately before the execute command.
The command waits for completion and preserves stdout and stderr separately.
On success stdout is the returned execution resource. If `--wait` exits
nonzero after creating an execution, the before/after latest-execution receipt
identifies the new name and `executions describe` captures its resource before
the runbook stops. Cloud Logging is queried by the exact execution label and
saves all scoped entries; summary extraction considers only container stdout.
Because log ingestion can lag, each read has a new preserved path. The loop
accepts only one JSON object with exactly the five `DrainSummary` integer
fields.

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo/api
test "$PRE_JOB_AUDIT_VERIFIED" = 1

PRE_EXECUTION_SCHEDULER_PATH="$RECEIPT_DIR/pre-execution-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$PRE_EXECUTION_SCHEDULER_PATH"
test "$(jq -er '.state' "$PRE_EXECUTION_SCHEDULER_PATH")" = PAUSED
test "$(jq -er '.schedule' "$PRE_EXECUTION_SCHEDULER_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$PRE_EXECUTION_SCHEDULER_PATH")" = Etc/UTC

PRE_EXECUTION_LATEST_PATH="$RECEIPT_DIR/pre-execution-latest-name.txt"
PRE_EXECUTION_LATEST_NAME=$(gcloud run jobs describe "$ADJUDICATOR_JOB" \
  --project "$PROJECT" --region "$REGION" \
  --format='value(status.latestCreatedExecution.name)')
printf '%s\n' "$PRE_EXECUTION_LATEST_NAME" > "$PRE_EXECUTION_LATEST_PATH"

test ! -e "$EXECUTION_RESOURCE_PATH"
test ! -e "$EXECUTION_COMMAND_OUTPUT_PATH"
test ! -e "$EXECUTION_COMMAND_ERROR_PATH"
test ! -e "$ROLLBACK_FORBIDDEN_PATH"
printf 'rollback forbidden after execute invocation at %s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$ROLLBACK_FORBIDDEN_PATH"
ROLLBACK_FORBIDDEN=1

EXECUTE_STATUS=0
if gcloud run jobs execute "$ADJUDICATOR_JOB" \
    --project "$PROJECT" --region "$REGION" \
    --wait --format=json \
    > "$EXECUTION_COMMAND_OUTPUT_PATH" \
    2> "$EXECUTION_COMMAND_ERROR_PATH"; then
  EXECUTE_STATUS=0
else
  EXECUTE_STATUS=$?
fi

POST_EXECUTION_LATEST_PATH="$RECEIPT_DIR/post-execution-latest-name.txt"
POST_EXECUTION_LATEST_NAME=$(gcloud run jobs describe "$ADJUDICATOR_JOB" \
  --project "$PROJECT" --region "$REGION" \
  --format='value(status.latestCreatedExecution.name)')
printf '%s\n' "$POST_EXECUTION_LATEST_NAME" > "$POST_EXECUTION_LATEST_PATH"

EXECUTION_NAME=
if jq -e '.metadata.name | type == "string" and length > 0' \
    "$EXECUTION_COMMAND_OUTPUT_PATH" >/dev/null 2>&1; then
  EXECUTION_NAME=$(jq -er '.metadata.name' "$EXECUTION_COMMAND_OUTPUT_PATH")
  cp "$EXECUTION_COMMAND_OUTPUT_PATH" "$EXECUTION_RESOURCE_PATH"
elif [ -n "$POST_EXECUTION_LATEST_NAME" ] \
  && [ "$POST_EXECUTION_LATEST_NAME" != "$PRE_EXECUTION_LATEST_NAME" ]; then
  EXECUTION_NAME="$POST_EXECUTION_LATEST_NAME"
  gcloud run jobs executions describe "$EXECUTION_NAME" \
    --project "$PROJECT" --region "$REGION" \
    --format=json > "$EXECUTION_RESOURCE_PATH"
else
  printf 'STOP: execute exited %s and no new execution identity was recoverable; preserve %s.\n' \
    "$EXECUTE_STATUS" "$RECEIPT_DIR" >&2
  exit 1
fi

test "$(jq -er '.metadata.labels["run.googleapis.com/job"]' \
  "$EXECUTION_RESOURCE_PATH")" = "$ADJUDICATOR_JOB"
printf '%s\n' "$EXECUTION_NAME" | tee "$EXECUTION_NAME_PATH"

EXECUTION_LOG_FILTER="resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$ADJUDICATOR_JOB\" AND resource.labels.location=\"$REGION\" AND labels.\"run.googleapis.com/execution_name\"=\"$EXECUTION_NAME\""
test ! -e "$DRAIN_SUMMARY_PATH"
SUMMARY_CANDIDATE=$(mktemp "$RECEIPT_DIR/.drain-summary.XXXXXX")

for LOG_ATTEMPT in {1..12}; do
  EXECUTION_LOGS_PATH=$(printf '%s/job-execution-logs-%02d.json' \
    "$RECEIPT_DIR" "$LOG_ATTEMPT")
  test ! -e "$EXECUTION_LOGS_PATH"
  gcloud logging read "$EXECUTION_LOG_FILTER" \
    --project "$PROJECT" --freshness=1d \
    --format=json > "$EXECUTION_LOGS_PATH"
  jq -c '
    [
      .[]
      | select(.logName | endswith("/logs/run.googleapis.com%2Fstdout"))
      | .jsonPayload
      | select(type == "object")
      | select((keys | sort) == [
          "done", "failed_repositories", "reclaimed", "repositories", "retried"
        ])
      | select(
          (.repositories | type) == "number"
          and (.done | type) == "number"
          and (.retried | type) == "number"
          and (.failed_repositories | type) == "number"
          and (.reclaimed | type) == "number"
          and .repositories >= 0 and .repositories == (.repositories | floor)
          and .done >= 0 and .done == (.done | floor)
          and .retried >= 0 and .retried == (.retried | floor)
          and .failed_repositories >= 0
          and .failed_repositories == (.failed_repositories | floor)
          and .reclaimed >= 0 and .reclaimed == (.reclaimed | floor)
        )
    ]
    | if length == 1 then .[0] else empty end
  ' "$EXECUTION_LOGS_PATH" > "$SUMMARY_CANDIDATE"
  if [ -s "$SUMMARY_CANDIDATE" ]; then
    mv "$SUMMARY_CANDIDATE" "$DRAIN_SUMMARY_PATH"
    break
  fi
  sleep 10
done

test -s "$DRAIN_SUMMARY_PATH"
jq -e . "$DRAIN_SUMMARY_PATH" >/dev/null
test "$EXECUTE_STATUS" -eq 0
jq -e '.status.completionTime != null' "$EXECUTION_RESOURCE_PATH" >/dev/null
JOB_EXECUTION_VERIFIED=1
```

If execute, log retrieval, or exact-summary extraction fails, keep the
Scheduler paused, preserve every artifact, and investigate. Do not roll back.

## 8. Run the post-Job SQL audit

The same durable SQL file and a new `psql` session prove the same four
invariants after adjudication.

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo/api
test "$JOB_EXECUTION_VERIFIED" = 1
test "$ROLLBACK_FORBIDDEN" = 1
test -s "$ROLLBACK_FORBIDDEN_PATH"
test -s "$DRAIN_SUMMARY_PATH"
test ! -e "$POST_JOB_SQL_RECEIPT_PATH"

psql "$PSQL_DATABASE_URL" -X --echo-all --set=ON_ERROR_STOP=1 \
  --file="$AUDIT_SQL_PATH" 2>&1 | tee "$POST_JOB_SQL_RECEIPT_PATH"
POST_JOB_AUDIT_VERIFIED=1
```

Any returned violation causes the generated assertion to fail. Keep the
Scheduler paused and do not roll back.

## 9. Final CLI audit, resume, and verify Scheduler

This section is only for the successful manual-execution path. All earlier
assertions must have passed in the same primary operator flow.

```bash
set -euo pipefail
cd /Users/andrew/Projects/doughq/repo/api
test "$POST_JOB_AUDIT_VERIFIED" = 1
test ! -e "$FINAL_REPORT_PATH"

uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp "$PROJECT" --dry-run | tee "$FINAL_REPORT_PATH"
test "$(jq -er '.missing' "$FINAL_REPORT_PATH")" = 0
test "$(jq -er '.mismatches | length' "$FINAL_REPORT_PATH")" = 0
test "$(jq -er '.orphan_60' "$FINAL_REPORT_PATH")" = 0

FINAL_PRE_RESUME_PATH="$RECEIPT_DIR/final-pre-resume-scheduler.json"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$FINAL_PRE_RESUME_PATH"
test "$(jq -er '.state' "$FINAL_PRE_RESUME_PATH")" = PAUSED
test "$(jq -er '.schedule' "$FINAL_PRE_RESUME_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$FINAL_PRE_RESUME_PATH")" = Etc/UTC

gcloud scheduler jobs resume "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION"
gcloud scheduler jobs describe "$SCHEDULER_JOB" \
  --project "$PROJECT" --location "$REGION" \
  --format=json > "$FINAL_SCHEDULER_PATH"
test "$(jq -er '.state' "$FINAL_SCHEDULER_PATH")" = ENABLED
test "$(jq -er '.schedule' "$FINAL_SCHEDULER_PATH")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$FINAL_SCHEDULER_PATH")" = Etc/UTC
```

## 10. Preserve the closure-PR receipt

Do not edit or delete the receipt directory. Record these exact paths in the
Task 7 closure work:

- `COMMIT_RECEIPT_PATH`, `DEPLOY_OUTPUT_PATH`, `JOB_CONFIG_PATH`, and
  `DEPLOY_IDENTITY_PATH`;
- `DRY_REPORT_PATH`, `APPLY_OUTPUT_PATH`, `BACKFILL_MANIFEST_PATH`, and
  `MANIFEST_VERIFY_PATH`;
- `PAUSED_SCHEDULER_PATH`, every `quiescence-executions-*.json` receipt,
  `PRE_APPLY_QUIESCENCE_PATH`, and `PRE_APPLY_SCHEDULER_PATH`;
- `AUDIT_SQL_PATH`, `PRE_JOB_SQL_RECEIPT_PATH`, and
  `POST_JOB_SQL_RECEIPT_PATH`;
- `PRE_EXECUTION_LATEST_PATH`, `POST_EXECUTION_LATEST_PATH`,
  `EXECUTION_COMMAND_OUTPUT_PATH`, `EXECUTION_COMMAND_ERROR_PATH`,
  `EXECUTION_RESOURCE_PATH`, `EXECUTION_NAME_PATH`,
  `ROLLBACK_FORBIDDEN_PATH`, the selected `EXECUTION_LOGS_PATH`, and
  `DRAIN_SUMMARY_PATH`; and
- `FINAL_REPORT_PATH`, `FINAL_PRE_RESUME_PATH`, and `FINAL_SCHEDULER_PATH`.

If a recovery branch ran instead, preserve its final audit plus both of that
branch's pre-resume and final Scheduler JSON paths.

Only a complete receipt may change the roadmap and handoff from “built” to
“production catch-up complete.” This runbook does not claim that Task 7 ran or
that the new pre-registration hash is live.
