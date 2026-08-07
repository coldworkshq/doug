# Production runbook — 60-day outcome-job catch-up

**Status:** Built on `m3-60-day-backfill`; not executed in production. Run only
after this branch is merged to `main`, as the separately authorized Task 7.

This is the one-time repair for historical registered-installation merges that
have a 14-day `outcome_jobs` row but no 60-day sibling. Future merges receive
both rows atomically from merge ingestion. The repair copies the stored merge
facts, sets `window_days = 60`, and derives `due_at` from `merged_at`; it does
not change the publication metric, windows, censoring, cadence, or denominator.

Do not use Cloud SQL Studio temporary tables. Every SQL audit below is
session-independent, so it can be rerun on a fresh connection. Keep the Cloud
SQL proxy running until the final audit and Scheduler check are complete.

Success means all of the following are true:

- the API and Job use the same immutable image and the Job carries the hash of
  the committed `LOCKED` pre-registration;
- the dry-run reports no mismatched pairs and no registered 60-day orphans;
- the Scheduler is paused before the insert-select;
- the manifest names exactly the inserted, untouched rows before adjudication;
- all three pair-violation queries and the complete-identity audit return zero
  rows before and after the manual Job;
- the final CLI audit reports zero missing rows, mismatches, and orphans; and
- the Scheduler is restored to `ENABLED`, `0 3 * * *`, `Etc/UTC`.

## 1. Update and deploy from `main`

Use the normal checkout, not an implementation worktree. `git status --short`
must print nothing. Record the SHA printed by `git rev-parse HEAD` with the
operator receipt.

```bash
cd /Users/andrew/Projects/doughq/repo
git fetch origin main
git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD

cd api
PROJECT=doug-prod0 REGION=us-central1 bash deploy/gcp.sh deploy

API_IMAGE=$(gcloud run services describe doug-api \
  --project doug-prod0 --region us-central1 \
  --format='value(spec.template.spec.containers[0].image)')
JOB_JSON=$(mktemp /tmp/doug-adjudicator-job.XXXXXX)
gcloud run jobs describe doug-adjudicator \
  --project doug-prod0 --region us-central1 --format=json > "$JOB_JSON"
JOB_IMAGE=$(jq -er '.spec.template.spec.template.spec.containers[0].image' "$JOB_JSON")
LOCAL_PREREG_HASH=$(python3 -c \
  "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('../docs/design/outcome-loop/publication-preregistration.md').read_bytes()).hexdigest())")
JOB_PREREG_HASH=$(jq -er \
  '.spec.template.spec.template.spec.containers[0].env[] | select(.name=="DOUG_PREREG_HASH") | .value' \
  "$JOB_JSON")
test "$API_IMAGE" = "$JOB_IMAGE"
test "$LOCAL_PREREG_HASH" = "$JOB_PREREG_HASH"
```

Stop if the checkout is dirty, the deploy fails, or either equality test
fails. Do not continue with a Job that is on a different image or lock hash.

## 2. Start the Cloud SQL proxy in a second terminal

```bash
cloud-sql-proxy doug-prod0:us-central1:doug-ledger --port 5433
```

Leave that process running. Run the remaining shell commands from the first
terminal.

## 3. Dry-run, pause, apply, and verify the manifest

The manifest path is intentionally new and absolute. `test ! -e` prevents a
prior receipt from being overwritten. The captured `EXPECTED_MISSING` is the
write guard; do not edit it after the dry-run.

```bash
cd /Users/andrew/Projects/doughq/repo/api
DRY_REPORT_PATH=/tmp/doug-60-day-backfill-dry-run.json
APPLY_REPORT_PATH=/tmp/doug-60-day-backfill-apply.json
BACKFILL_MANIFEST_PATH="/tmp/doug-60-day-backfill-$(date -u +%Y%m%dT%H%M%SZ).json"
test ! -e "$BACKFILL_MANIFEST_PATH"

uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --dry-run | tee "$DRY_REPORT_PATH"
EXPECTED_MISSING=$(jq -er '.missing' "$DRY_REPORT_PATH")
test "$(jq -er '.mismatches | length' "$DRY_REPORT_PATH")" = 0
test "$(jq -er '.orphan_60' "$DRY_REPORT_PATH")" = 0

test "$(gcloud scheduler jobs describe doug-adjudicator-daily \
  --project doug-prod0 --location us-central1 --format='value(state)')" = ENABLED
gcloud scheduler jobs pause doug-adjudicator-daily \
  --project doug-prod0 --location us-central1
test "$(gcloud scheduler jobs describe doug-adjudicator-daily \
  --project doug-prod0 --location us-central1 --format='value(state)')" = PAUSED

uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --apply \
  --expect-missing "$EXPECTED_MISSING" \
  --manifest "$BACKFILL_MANIFEST_PATH" | tee "$APPLY_REPORT_PATH"
test "$(jq -er '.inserted' "$APPLY_REPORT_PATH")" = "$EXPECTED_MISSING"

uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --verify-manifest \
  --expect-count "$EXPECTED_MISSING" \
  --manifest "$BACKFILL_MANIFEST_PATH"
```

## Rollback boundary — read before manual execution

If the apply or any pre-Job audit is wrong, keep the Scheduler paused and run:

```bash
uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --rollback \
  --expect-count "$EXPECTED_MISSING" \
  --manifest "$BACKFILL_MANIFEST_PATH"
```

Verify that the command reports `rolled_back` equal to `EXPECTED_MISSING`.
After that verified rollback, resume and verify the Scheduler directly:

```bash
gcloud scheduler jobs resume doug-adjudicator-daily \
  --project doug-prod0 --location us-central1
ROLLBACK_SCHEDULER_JSON=$(mktemp /tmp/doug-adjudicator-rollback-scheduler.XXXXXX)
gcloud scheduler jobs describe doug-adjudicator-daily \
  --project doug-prod0 --location us-central1 --format=json > "$ROLLBACK_SCHEDULER_JSON"
test "$(jq -er '.state' "$ROLLBACK_SCHEDULER_JSON")" = ENABLED
test "$(jq -er '.schedule' "$ROLLBACK_SCHEDULER_JSON")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$ROLLBACK_SCHEDULER_JSON")" = Etc/UTC
```

Stop here after the Scheduler checks pass. The rollback path is complete; do
not continue into the pre-Job audit or manual-execution path.

**After `gcloud run jobs execute`, rollback is forbidden.** The Job may have
claimed or adjudicated inserted rows, so deleting them would erase clocks whose
outcome work has begun. Resume the Scheduler only after either a verified
rollback or the audited manual execution below.

## 4. Audit the pairs before adjudication

Create a proxy-backed `psql` URL and open a session:

```bash
PSQL_DATABASE_URL=$(gcloud secrets versions access latest \
  --secret=doug-database-url --project=doug-prod0 | python3 -c '
import sys
url = sys.stdin.read().strip()
url = url.split("?host=", 1)[0]
url = url.replace("postgresql+psycopg://", "postgresql://")
print(url.replace("@/doug", "@127.0.0.1:5433/doug"))
')
psql "$PSQL_DATABASE_URL" -v ON_ERROR_STOP=1
```

Run all three queries. Each must return zero rows. These predicates use
membership in `installations`, not a numeric sentinel, so research/CLI rows are
outside the prospective publication population.

```sql
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
```

Exit with `\q`. Any returned row is a stop: do not execute the Job. Use the
rollback path above while the manifest still verifies as untouched.

## 5. Execute the Job once

```bash
gcloud run jobs execute doug-adjudicator \
  --project doug-prod0 --region us-central1 --wait
```

The rollback boundary is now closed even if this command or a later audit
fails. Keep the Scheduler paused while investigating any failure.

## 6. Repeat the SQL audits after adjudication

Open a fresh session; no temporary pre-state is required:

```bash
psql "$PSQL_DATABASE_URL" -v ON_ERROR_STOP=1
```

Rerun all three queries from §4. Each must still return zero rows. Then run the
complete-identity audit from `HANDOFF.md`; it too must return zero rows:

```sql
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
```

Exit with `\q`. If any audit returns rows, keep the Scheduler paused and retain
the dry-run report, apply report, manifest, Job execution name, and SQL output.
Do not roll back.

## 7. Manual-execution final CLI audit and Scheduler resume

This section is only for the manual-execution path. Continue only after the
post-Job SQL audits all returned zero rows.

```bash
uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --dry-run | tee /tmp/doug-60-day-backfill-after.json
test "$(jq -er '.missing' /tmp/doug-60-day-backfill-after.json)" = 0
test "$(jq -er '.mismatches | length' /tmp/doug-60-day-backfill-after.json)" = 0
test "$(jq -er '.orphan_60' /tmp/doug-60-day-backfill-after.json)" = 0

gcloud scheduler jobs resume doug-adjudicator-daily \
  --project doug-prod0 --location us-central1
SCHEDULER_JSON=$(mktemp /tmp/doug-adjudicator-scheduler.XXXXXX)
gcloud scheduler jobs describe doug-adjudicator-daily \
  --project doug-prod0 --location us-central1 --format=json > "$SCHEDULER_JSON"
test "$(jq -er '.state' "$SCHEDULER_JSON")" = ENABLED
test "$(jq -er '.schedule' "$SCHEDULER_JSON")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$SCHEDULER_JSON")" = Etc/UTC
```

Retain the commit SHA, both JSON reports, manifest, Job execution name, the
pre-Job three-query receipt, the post-Job four-query receipt, final CLI audit,
and Scheduler JSON as the Task 7 production receipt. Only that receipt may
change the roadmap and handoff from “built” to “production catch-up complete.”
