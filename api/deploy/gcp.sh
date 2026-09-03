#!/usr/bin/env bash
# Doug on GCP: Cloud Run (API) + Cloud SQL Postgres (outcome ledger).
#
# One-time-ish and idempotent where possible. Requires: gcloud authed on a
# project with billing. Secrets go to Secret Manager, never into env specs.
#
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh setup   # APIs, SQL, secrets, IAM
#   PROJECT=doug-prod0 REGION=us-central1 DOUG_EXAMPLE_PACK_BUCKET=... ./deploy/gcp.sh example-pack-setup
#   PROJECT=doug-prod0 REGION=us-central1 DOUG_EXAMPLE_PACK_...=... ./deploy/gcp.sh example-pack-enable
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh example-pack-disable
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh adjudicator-setup # M3 IAM only
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh deploy  # build + deploy the API
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh adjudicator # deploy M3 Job
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh schedule # create/update daily trigger
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh reconcile-job # deploy outcome reconciler Job
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh schedule-reconcile # create/update 6h trigger
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh web     # build + deploy the site
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh console # build + deploy the operator console
#
# `deploy` and `web` are what CI runs on every merge to main
# (.github/workflows/deploy.yml), so they are pure deploys — no IAM, no
# resource creation, nothing that needs admin rights. That is what lets the
# CI principal stay narrow. Anything privileged belongs in `setup`.
# `console` is deliberately not wired into CI: it is IAM-gated, so a stray
# grant belongs to a human running `setup`, not to the merge-to-main path.
set -euo pipefail

SCRIPT_SOURCE=${BASH_SOURCE[0]}
while [ -h "$SCRIPT_SOURCE" ]; do
  SCRIPT_DIR=$(cd -P -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)
  SCRIPT_SOURCE=$(readlink "$SCRIPT_SOURCE")
  case "$SCRIPT_SOURCE" in
    /*) ;;
    *) SCRIPT_SOURCE="$SCRIPT_DIR/$SCRIPT_SOURCE" ;;
  esac
done
SCRIPT_DIR=$(cd -P -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)
API_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
REPO_ROOT=$(cd -- "$API_DIR/.." && pwd -P)
cd "$API_DIR"

PROJECT=${PROJECT:?set PROJECT}
REGION=${REGION:-us-central1}
# ADR-0029. The Vertex region the reader calls, and deliberately NOT defaulted
# to $REGION. Claude is not served from every Vertex region and the api
# service's own region is not necessarily one of them. A wrong value does not
# fail loudly: every read fails soft into the deterministic score, which reads
# as "the reader is down" rather than "the region is wrong", so a guessed
# default would degrade the product silently. Checked at `deploy` only — the
# other subcommands do not construct a reader.
VERTEX_REGION=${VERTEX_REGION:-}
# ADR-0029. Which transport THIS deploy pins on the service. Vertex is the
# destination, and it is a variable rather than a literal for one reason: the
# preflight below hard-fails while Vertex quota is zero, which would make an
# unrelated urgent deploy hostage to a founder-level quota grant. R1 says
# production Doug wins every conflict, and a hotfix that cannot ship because a
# transport migration is half-finished is that conflict.
#
# `READER_TRANSPORT=anthropic ./deploy/gcp.sh deploy` ships the current
# transport and skips the Vertex preflight entirely. Doug raised this
# (`reader:deploy-blocking-precondition`) and it was a fair objection to a gate
# that had no way out.
READER_TRANSPORT=${READER_TRANSPORT:-vertex}
# Workload Identity Federation. How the api service proves who it is on the
# FIRST-PARTY transport, replacing the ANTHROPIC_API_KEY mount that used to sit
# in --set-secrets below. None of these four is a secret — they name resources,
# and the credential is a Google-signed token the workload fetches for its own
# service account at call time — so they are plain env vars and belong in this
# file where a diff can review them, not in Secret Manager.
#
# The rule pins BOTH the service account email and its numeric unique ID, so
# only doug-api-sa can mint a token against it, and only from a workload
# Google itself signed for. There is no key to expire, rotate, leak, or paste
# into a shell.
#
# ANTHROPIC_API_KEY OUTRANKS FEDERATION in every SDK's credential precedence.
# That is why the mount is gone rather than kept as a fallback: a leftover key
# does not fail, it silently wins, and the reader would go on billing a
# credential everyone believes is retired. Pinned by
# test_the_api_deploy_mounts_no_anthropic_key.
#
# The rollback is therefore an env change on the running service, exactly like
# ADR-0029's transport rollback and with no deploy:
#   gcloud run services update doug-api --region "$REGION" \
#     --update-secrets ANTHROPIC_API_KEY=doug-anthropic-key:latest
# The secret and its IAM binding are deliberately left in place for that.
FEDERATION_RULE_ID=${FEDERATION_RULE_ID:-fdrl_01C9roE2McZ4TRyAVyrBQ6oP}
FEDERATION_ORG_ID=${FEDERATION_ORG_ID:-2f3e6be2-8390-4f32-a0bc-f2544ac86641}
FEDERATION_SERVICE_ACCOUNT_ID=${FEDERATION_SERVICE_ACCOUNT_ID:-svac_01AsuQr8exnkCC8Tqv9KxQca}
FEDERATION_WORKSPACE_ID=${FEDERATION_WORKSPACE_ID:-wrkspc_01AS2iPQV3Z6Z4ie76pn5YuW}
INSTANCE=doug-ledger
SERVICE=doug-api
WEB_SERVICE=doug-web
CONSOLE_SERVICE=doug-console
ADJUDICATOR_JOB=doug-adjudicator
SCHEDULER_JOB=doug-adjudicator-daily
RECONCILE_JOB=doug-outcome-reconciler
RECONCILE_SCHEDULER_JOB=doug-outcome-reconciler-6h
CONN="$PROJECT:$REGION:$INSTANCE"
# The showcase queue shows one repo's queue; unset would mix the backfilled
# probe corpora into it.
SHOWCASE_REPO=${SHOWCASE_REPO:-coldworkshq/doug}
PREREG_DOC="$REPO_ROOT/docs/design/outcome-loop/publication-preregistration.md"

setup() {
  # compute.googleapis.com is not used directly, but enabling it is what
  # creates the default compute service account the secret bindings below
  # attach to — on a project that never touched Compute, that SA simply
  # does not exist and setup used to silently bind secrets to nobody.
  # aiplatform: ADR-0029 moved the reader's transport to Vertex, so the api
  # service calls it with application default credentials. Without the API
  # enabled the failure arrives at runtime as a soft reader fallback rather
  # than at deploy time, which is the shape this whole script exists to avoid.
  gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    secretmanager.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com compute.googleapis.com \
    aiplatform.googleapis.com \
    cloudscheduler.googleapis.com --project "$PROJECT"

  if ! gcloud sql instances describe "$INSTANCE" --project "$PROJECT" >/dev/null 2>&1; then
    # Smallest sensible tier (~$10/mo). The ledger outlives any one service.
    gcloud sql instances create "$INSTANCE" \
      --database-version=POSTGRES_18 --tier=db-f1-micro --edition=enterprise \
      --region="$REGION" --project "$PROJECT" --async
  fi

  openssl rand -hex 32 | tr -d '\n' \
    | gcloud secrets create doug-api-token --data-file=- --project "$PROJECT" 2>/dev/null \
    || echo "doug-api-token secret exists; leaving it"

  # sys.stdout.write, not print(): the trailing newline is stored as part of
  # the secret, and _pepper's validate=True b64decode refused it — prod
  # 503'd every mint on 2026-08-05. The app now strips whitespace too
  # (belt), but the secret should be clean at the source (braces).
  python3 -c "import base64,secrets,sys;sys.stdout.write(base64.b64encode(secrets.token_bytes(32)).decode())" \
    | gcloud secrets create doug-token-pepper --data-file=- --project "$PROJECT" 2>/dev/null \
    || echo "doug-token-pepper secret exists; leaving it"

  # Purpose-scoped signer shared by doug-web and doug-api for the 30-minute
  # installation flow. It is not the AuthKit cookie key or an operator token.
  openssl rand -hex 32 | tr -d '\n' \
    | gcloud secrets create doug-install-flow-secret --data-file=- --project "$PROJECT" 2>/dev/null \
    || echo "doug-install-flow-secret secret exists; leaving it"

  STATE=$(gcloud sql instances describe "$INSTANCE" --project "$PROJECT" \
    --format='value(state)' 2>/dev/null || echo CREATING)
  if [ "$STATE" != "RUNNABLE" ]; then
    echo "Cloud SQL instance is $STATE (creation ~10 min) — re-run setup when RUNNABLE."
    return
  fi

  gcloud sql databases create doug --instance="$INSTANCE" --project "$PROJECT" 2>/dev/null || true

  DB_PASS=$(openssl rand -hex 24)
  gcloud sql users create doug --instance="$INSTANCE" --password="$DB_PASS" \
    --project "$PROJECT" 2>/dev/null \
    || gcloud sql users set-password doug --instance="$INSTANCE" \
      --password="$DB_PASS" --project "$PROJECT"

  printf 'postgresql+psycopg://doug:%s@/doug?host=/cloudsql/%s' "$DB_PASS" "$CONN" \
    | gcloud secrets create doug-database-url --data-file=- --project "$PROJECT" 2>/dev/null \
    || printf 'postgresql+psycopg://doug:%s@/doug?host=/cloudsql/%s' "$DB_PASS" "$CONN" \
      | gcloud secrets versions add doug-database-url --data-file=- --project "$PROJECT"

  # Secret access for the runtime service account. This lives in setup, not
  # deploy: re-binding IAM on every merge would force the CI principal to
  # carry admin rights it has no other reason to hold.
  #
  # doug-api gets its own identity: the App private key mints installation
  # tokens for every repo Doug is installed on, and a secret bound to the
  # default compute service account is readable by every workload in the
  # project.
  gcloud iam service-accounts create doug-api-sa \
    --display-name "doug-api runtime" --project "$PROJECT" 2>/dev/null \
    || echo "doug-api-sa exists; leaving it"
  # Constructed, never resolved by a display-name filter: the filter this
  # replaced returned empty on projects where the SA didn't exist yet, the
  # empty string flowed into --member, and `|| true` swallowed every failed
  # binding — "setup done" with secrets bound to nobody, surfacing later as
  # an opaque permission crash on the first real request. The describe is
  # the other half of that guard: the create above is `|| echo`'d, so a
  # create that failed for any reason other than "already exists" must not
  # reach the bindings below.
  SA="doug-api-sa@$PROJECT.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1; then
    echo "ERROR: service account $SA is not visible after create." >&2
    echo "Either the create failed (it needs roles/iam.serviceAccountAdmin) or it has" >&2
    echo "not propagated yet — wait a minute and re-run setup." >&2
    exit 1
  fi

  # Not optional: the default compute SA reached Cloud SQL through the
  # roles/editor it carries on this project (verified 2026-08-02), and a
  # freshly created SA carries nothing at all — without this grant every
  # ledger write fails on the
  # first request after the cutover, at runtime, long after the deploy went
  # green. Unsuppressed for the same reason as the secret bindings below.
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA" --role=roles/cloudsql.client >/dev/null

  # ADR-0029: the reader reaches Claude through Vertex on this identity's
  # application default credentials, so the grant is IAM rather than a secret.
  # That is the whole reason the transport move adds no new key material — and
  # it is also why the Anthropic key stays bound below: it is the rollback.
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA" --role=roles/aiplatform.user >/dev/null

  # doug-workos-api-key reads every tenant's identity data and doug-workos-
  # client-id is what session_auth's JWKS URL is built from — without the
  # second, every browser session 503s. Both are created by hand (like the
  # Anthropic key below) so neither sits in shell history; the loop only
  # binds read access and WARNs while they are missing.
  for s in doug-database-url doug-api-token doug-anthropic-key \
           doug-webhook-secret doug-github-app-key doug-token-pepper \
           doug-workos-api-key doug-workos-client-id \
           doug-install-flow-secret; do
    if ! gcloud secrets describe "$s" --project "$PROJECT" >/dev/null 2>&1; then
      echo "WARN: secret $s does not exist yet — create it and re-run setup to bind access." >&2
      continue
    fi
    # No error suppression here: a failed binding must kill setup loudly,
    # not surface later as a permission crash on the first real request.
    gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
      --member="serviceAccount:$SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null
  done

  # doug-web gets its own identity too. It must not share the default
  # compute SA: that principal holds roles/editor on doug-prod0, and a
  # browser-facing service running as editor is the blast radius Task 10
  # held doug-web back from. Same create/describe guard as doug-api-sa
  # above — never a display-name filter.
  gcloud iam service-accounts create doug-web-sa \
    --display-name "doug-web runtime" --project "$PROJECT" 2>/dev/null \
    || echo "doug-web-sa exists; leaving it"
  WEB_SA="doug-web-sa@$PROJECT.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$WEB_SA" --project "$PROJECT" >/dev/null 2>&1; then
    echo "ERROR: service account $WEB_SA is not visible after create." >&2
    echo "Either the create failed (it needs roles/iam.serviceAccountAdmin) or it has" >&2
    echo "not propagated yet — wait a minute and re-run setup." >&2
    exit 1
  fi
  # doug-web remains public, but AuthKit needs exactly these four values to
  # seal a session and complete its callback. They are intentionally bound
  # here rather than sharing doug-api-sa: no API/operator credential belongs
  # in an --allow-unauthenticated service.
  for s in doug-workos-client-id doug-workos-api-key \
           doug-workos-cookie-password doug-workos-redirect-uri \
           doug-install-flow-secret; do
    if ! gcloud secrets describe "$s" --project "$PROJECT" >/dev/null 2>&1; then
      echo "WARN: secret $s does not exist yet — create it and re-run setup to bind access." >&2
      continue
    fi
    gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
      --member="serviceAccount:$WEB_SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null
  done

  # WEB_SA is deliberately NOT bound to doug-api-token: Front Door Phase 0
  # dropped that secret from web(), and the leftover production binding was
  # revoked 2026-08-20 (#152). setup() grants no accessor it cannot point at
  # a --set-secrets flag, which is what let the last one rot unnoticed.
  # Revoking a stale one is an operator action, not a setup step — see
  # docs/OPERATIONS.md, "Audit the default compute SA's secret access".

  # doug-console is the operator surface. It crosses every installation, so
  # it is IAM-gated rather than token-gated, and it gets its own identity
  # for the same reason doug-web did: a service must not inherit the
  # default compute SA's roles/editor.
  gcloud iam service-accounts create doug-console-sa \
    --display-name "doug-console runtime" --project "$PROJECT" 2>/dev/null \
    || echo "doug-console-sa exists; leaving it"
  CONSOLE_SA="doug-console-sa@$PROJECT.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$CONSOLE_SA" --project "$PROJECT" >/dev/null 2>&1; then
    echo "ERROR: service account $CONSOLE_SA is not visible after create." >&2
    exit 1
  fi
  if gcloud secrets describe doug-api-token --project "$PROJECT" >/dev/null 2>&1; then
    gcloud secrets add-iam-policy-binding doug-api-token --project "$PROJECT" \
      --member="serviceAccount:$CONSOLE_SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null
  else
    echo "WARN: secret doug-api-token does not exist yet — create it and re-run setup." >&2
  fi

  # Keep the broad bootstrap a superset, but production follow-ups must call
  # adjudicator-setup directly: setup() rotates the SQL password above.
  adjudicator_setup

  # Node web/console images push to Artifact Registry repo `doug`. Create it
  # here (privileged path), never in web()/console(): CI's deployer only has
  # artifactregistry.writer, which cannot repositories.create — creating in
  # the deploy path would make the first post-merge web deploy fail.
  ensure_node_artifact_repo

  # Grant yourself the ability to invoke the gated console:
  #   gcloud run services add-iam-policy-binding doug-console --project "$PROJECT" \
  #     --region "$REGION" --member="user:YOUR@EMAIL" --role=roles/run.invoker

  # ANTHROPIC key: create manually so it never sits in shell history:
  #   gcloud secrets create doug-anthropic-key --data-file=/path/to/keyfile
  echo "setup done (check SQL instance state before first deploy)"
}

# One-purpose bootstrap for the hosted Example Pack lane. This is deliberately
# separate from setup(): neither CI nor a normal Doug deployment should need
# evidence-bucket administration privileges.
example_pack_setup() {
  local bucket api_sa console_sa lifecycle_file
  bucket=${DOUG_EXAMPLE_PACK_BUCKET:?set DOUG_EXAMPLE_PACK_BUCKET}
  api_sa="doug-api-sa@$PROJECT.iam.gserviceaccount.com"
  console_sa="doug-console-sa@$PROJECT.iam.gserviceaccount.com"

  gcloud services enable storage.googleapis.com secretmanager.googleapis.com \
    --project "$PROJECT"

  if ! gcloud iam service-accounts describe "$api_sa" \
      --project "$PROJECT" >/dev/null 2>&1; then
    echo "ERROR: service account $api_sa does not exist; run setup first." >&2
    return 1
  fi
  if ! gcloud iam service-accounts describe "$console_sa" \
      --project "$PROJECT" >/dev/null 2>&1; then
    echo "ERROR: service account $console_sa does not exist; run setup first." >&2
    return 1
  fi

  openssl rand -hex 32 | tr -d '\n' \
    | gcloud secrets create doug-example-pack-token --data-file=- \
      --project "$PROJECT" 2>/dev/null \
    || echo "doug-example-pack-token secret exists; leaving it"

  if ! gcloud storage buckets create "gs://$bucket" \
      --project "$PROJECT" --location="$REGION" \
      --default-storage-class=STANDARD \
      --uniform-bucket-level-access --public-access-prevention 2>/dev/null; then
    echo "evidence bucket create did not succeed; verifying the existing bucket"
  fi
  if ! gcloud storage buckets describe "gs://$bucket" \
      --project "$PROJECT" --raw --format=json \
      | python3 -c '
import json
import sys

bucket = json.load(sys.stdin)
region = sys.argv[1]
iam = bucket.get("iamConfiguration", {})
uniform = iam.get("uniformBucketLevelAccess", {})
if bucket.get("location", "").lower() != region.lower():
    raise SystemExit("bucket location does not match REGION")
if bucket.get("storageClass") != "STANDARD":
    raise SystemExit("bucket storage class is not STANDARD")
if uniform.get("enabled") is not True:
    raise SystemExit("uniform bucket-level access is not enabled")
if iam.get("publicAccessPrevention") != "enforced":
    raise SystemExit("public access prevention is not enforced")
' "$REGION"; then
    echo "ERROR: evidence bucket is absent or does not satisfy the private-bucket contract." >&2
    return 1
  fi

  lifecycle_file=$(mktemp)
  printf '%s\n' \
    '{"rule":[{"action":{"type":"Delete"},"condition":{"age":90,"matchesPrefix":["cohorts/"]}}]}' \
    > "$lifecycle_file"
  if ! gcloud storage buckets update "gs://$bucket" \
      --project "$PROJECT" --lifecycle-file="$lifecycle_file"; then
    rm -f "$lifecycle_file"
    return 1
  fi
  rm -f "$lifecycle_file"

  # Capture and read both happen in doug-api. The console receives rendered
  # API responses only and therefore gets no bucket capability.
  gcloud storage buckets add-iam-policy-binding "gs://$bucket" \
    --project "$PROJECT" --member="serviceAccount:$api_sa" \
    --role=roles/storage.objectCreator
  gcloud storage buckets add-iam-policy-binding "gs://$bucket" \
    --project "$PROJECT" --member="serviceAccount:$api_sa" \
    --role=roles/storage.objectViewer

  for service_account in "$api_sa" "$console_sa"; do
    gcloud secrets add-iam-policy-binding doug-example-pack-token \
      --project "$PROJECT" --member="serviceAccount:$service_account" \
      --role=roles/secretmanager.secretAccessor
  done
  echo "Example Pack storage and purpose token are ready; capture is still disabled."
}

validate_example_pack_enablement() {
  local source_root actual_revision source_status
  : "${DOUG_EXAMPLE_PACK_BUCKET:?set DOUG_EXAMPLE_PACK_BUCKET}"
  : "${DOUG_EXAMPLE_PACK_COHORT:?set DOUG_EXAMPLE_PACK_COHORT}"
  : "${DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT:?set DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT}"
  : "${DOUG_EXAMPLE_PACK_CAPTURE_UNTIL:?set DOUG_EXAMPLE_PACK_CAPTURE_UNTIL}"
  : "${DOUG_EXAMPLE_PACK_INSTALLATION_IDS:?set DOUG_EXAMPLE_PACK_INSTALLATION_IDS}"
  : "${DOUG_EXAMPLE_PACK_REPOSITORY_IDS:?set DOUG_EXAMPLE_PACK_REPOSITORY_IDS}"
  : "${DOUG_EXAMPLE_PACK_ADJUDICATOR:?set DOUG_EXAMPLE_PACK_ADJUDICATOR}"
  : "${DOUG_APPLICATION_REVISION:?set DOUG_APPLICATION_REVISION}"

  [[ "$DOUG_EXAMPLE_PACK_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] \
    || { echo "ERROR: invalid evidence bucket name." >&2; return 1; }
  [[ "$DOUG_EXAMPLE_PACK_ADJUDICATOR" =~ ^[A-Za-z0-9._-]+$ ]] \
    || { echo "ERROR: invalid adjudicator id." >&2; return 1; }
  [[ "$DOUG_APPLICATION_REVISION" =~ ^[0-9a-f]{40}$ ]] \
    || { echo "ERROR: application revision must be a full lowercase Git SHA." >&2; return 1; }

  python3 - "$DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT" \
    "$DOUG_EXAMPLE_PACK_CAPTURE_UNTIL" \
    "$DOUG_EXAMPLE_PACK_COHORT" \
    "$DOUG_EXAMPLE_PACK_INSTALLATION_IDS" \
    "$DOUG_EXAMPLE_PACK_REPOSITORY_IDS" <<'PY'
from datetime import datetime
import re
import sys

pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
try:
    start, end = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        for value in sys.argv[1:3]
    )
except ValueError as error:
    raise SystemExit(f"ERROR: invalid capture timestamp: {error}") from error
if not all(pattern.fullmatch(value) for value in sys.argv[1:3]):
    raise SystemExit("ERROR: capture timestamps must be second-precision UTC RFC3339 values.")
if end <= start:
    raise SystemExit("ERROR: capture end must be after capture start.")

cohort_pattern = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
if cohort_pattern.fullmatch(sys.argv[3]) is None:
    raise SystemExit("ERROR: invalid cohort id.")

def numeric_ids(raw: str, name: str) -> tuple[int, ...]:
    try:
        values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    except ValueError as error:
        raise SystemExit(f"ERROR: {name} must contain numeric IDs.") from error
    if not values or any(value <= 0 for value in values):
        raise SystemExit(f"ERROR: {name} must contain positive numeric IDs.")
    if len(values) != len(set(values)):
        raise SystemExit(f"ERROR: {name} must contain unique IDs.")
    return tuple(sorted(values))

numeric_ids(sys.argv[4], "installation ids")
numeric_ids(sys.argv[5], "repository ids")
PY

  source_root=${DOUG_EXAMPLE_PACK_SOURCE_ROOT:-$REPO_ROOT}
  actual_revision=$(git -C "$source_root" rev-parse HEAD 2>/dev/null) \
    || { echo "ERROR: Example Pack source root is not a Git checkout." >&2; return 1; }
  source_status=$(git -C "$source_root" status --porcelain)
  if [ -n "$source_status" ]; then
    echo "ERROR: Example Pack source checkout is dirty; refusing capture." >&2
    return 1
  fi
  if [ "$actual_revision" != "$DOUG_APPLICATION_REVISION" ]; then
    echo "ERROR: DOUG_APPLICATION_REVISION does not match the source checkout." >&2
    return 1
  fi
}

# Opt-in is an explicit, reversible service update. Normal deploys preserve
# only the existing read configuration and purpose token. They omit capture
# admission, so CI remains independent of privileged setup and closes writes.
example_pack_enable() {
  validate_example_pack_enablement
  local env_vars
  env_vars="^@^DOUG_EXAMPLE_PACK_CAPTURE=1"
  env_vars+="@DOUG_EXAMPLE_PACK_BUCKET=$DOUG_EXAMPLE_PACK_BUCKET"
  env_vars+="@DOUG_EXAMPLE_PACK_COHORT=$DOUG_EXAMPLE_PACK_COHORT"
  env_vars+="@DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT=$DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT"
  env_vars+="@DOUG_EXAMPLE_PACK_CAPTURE_UNTIL=$DOUG_EXAMPLE_PACK_CAPTURE_UNTIL"
  env_vars+="@DOUG_EXAMPLE_PACK_INSTALLATION_IDS=$DOUG_EXAMPLE_PACK_INSTALLATION_IDS"
  env_vars+="@DOUG_EXAMPLE_PACK_REPOSITORY_IDS=$DOUG_EXAMPLE_PACK_REPOSITORY_IDS"
  env_vars+="@DOUG_EXAMPLE_PACK_ADJUDICATOR=$DOUG_EXAMPLE_PACK_ADJUDICATOR"
  env_vars+="@DOUG_APPLICATION_REVISION=$DOUG_APPLICATION_REVISION"

  gcloud run services update "$SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --update-env-vars "$env_vars" \
    --update-secrets "DOUG_EXAMPLE_PACK_TOKEN=doug-example-pack-token:latest"
  gcloud run services update "$CONSOLE_SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --update-secrets "DOUG_EXAMPLE_PACK_TOKEN=doug-example-pack-token:latest"
  echo "Example Pack capture enabled for cohort $DOUG_EXAMPLE_PACK_COHORT."
}

example_pack_disable() {
  gcloud run services update "$SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --update-env-vars DOUG_EXAMPLE_PACK_CAPTURE=0
  echo "Example Pack capture disabled; stored evidence remains readable."
}

wait_for_service_account() {
  local service_account="$1" attempt=1
  while [ "$attempt" -le 10 ]; do
    if gcloud iam service-accounts describe "$service_account" \
        --project "$PROJECT" >/dev/null 2>&1; then
      return 0
    fi
    if [ "$attempt" -lt 10 ]; then
      sleep 1
    fi
    attempt=$((attempt + 1))
  done
  echo "ERROR: service account $service_account is not visible after create." >&2
  return 1
}

adjudicator_setup() {
  # Narrow M3 bootstrap. Unlike setup(), this function never creates a SQL
  # database/user, changes a password, or publishes a database secret version.
  # It owns only API enablement and the two identities the Job boundary needs.
  gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    secretmanager.googleapis.com iam.googleapis.com \
    cloudscheduler.googleapis.com --project "$PROJECT"

  # The adjudicator runs the same image as doug-api but under a narrower
  # identity: database + GitHub App key, no Anthropic key and no operator
  # token. The scheduler gets a separate identity whose only runtime power is
  # invoking this one Job; schedule() installs that resource-level grant after
  # the Job exists.
  gcloud iam service-accounts create doug-adjudicator-sa \
    --display-name "Doug adjudicator runtime" --project "$PROJECT" 2>/dev/null \
    || echo "doug-adjudicator-sa exists; leaving it"
  ADJUDICATOR_SA="doug-adjudicator-sa@$PROJECT.iam.gserviceaccount.com"
  wait_for_service_account "$ADJUDICATOR_SA"
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$ADJUDICATOR_SA" \
    --role=roles/cloudsql.client >/dev/null
  for s in doug-database-url doug-github-app-key; do
    if ! gcloud secrets describe "$s" --project "$PROJECT" >/dev/null 2>&1; then
      echo "ERROR: required secret $s does not exist." >&2
      return 1
    fi
    gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
      --member="serviceAccount:$ADJUDICATOR_SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null
  done

  gcloud iam service-accounts create doug-scheduler-sa \
    --display-name "Doug adjudicator scheduler" --project "$PROJECT" 2>/dev/null \
    || echo "doug-scheduler-sa exists; leaving it"
  SCHEDULER_SA="doug-scheduler-sa@$PROJECT.iam.gserviceaccount.com"
  wait_for_service_account "$SCHEDULER_SA"
  echo "adjudicator IAM ready (no SQL credentials changed)"
}

# Staged deploys: the new revision starts with a tag and zero traffic, gets
# smoke-tested on its tagged URL, and only then takes 100%. Before this,
# `gcloud run deploy` cut all traffic to the new revision the moment it
# bound the port, and the pipeline's smoke test could only report — loudly,
# after the fact — that prod was already broken, with rollback left to a
# human running update-traffic by hand. A failed candidate now simply never
# serves; the previous revision keeps 100% and the job goes red.

# Whether $1 already exists as a Cloud Run service. A brand-new service
# cannot take --no-traffic (its first revision must serve), so the very
# first deploy of each service goes straight to traffic, smoke-tested
# after the fact — with nothing serving yet, there is nothing to protect.
service_exists() {
  gcloud run services describe "$1" --project "$PROJECT" --region "$REGION" >/dev/null 2>&1
}

# Return only the purpose-scoped binding needed to keep stored cohorts readable
# across an ordinary deployment. Capture admission settings are intentionally
# excluded, so a normal deploy always closes writes while preserving review.
existing_example_pack_binding() { # $1 service, $2 read|token
  gcloud run services describe "$1" \
    --project "$PROJECT" --region "$REGION" --format=json \
    | python3 -c '
import json
import re
import sys

service = json.load(sys.stdin)
mode = sys.argv[1]
containers = service.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
entries = containers[0].get("env", []) if containers else []
plain = {entry.get("name"): entry.get("value") for entry in entries if "value" in entry}
token_entry = next(
    (entry for entry in entries if entry.get("name") == "DOUG_EXAMPLE_PACK_TOKEN"),
    None,
)
required = (
    "DOUG_EXAMPLE_PACK_BUCKET",
    "DOUG_EXAMPLE_PACK_COHORT",
    "DOUG_EXAMPLE_PACK_ADJUDICATOR",
)
if token_entry is None:
    if mode == "token" or not any(plain.get(name) for name in required):
        raise SystemExit(0)
    raise SystemExit("incomplete Example Pack read binding")
secret_ref = (token_entry or {}).get("valueFrom", {}).get("secretKeyRef", {})
secret_name = secret_ref.get("name", "").rsplit("/", 1)[-1]
secret_version = secret_ref.get("key", "")
if secret_name != "doug-example-pack-token" or re.fullmatch(r"(?:latest|[1-9][0-9]*)", secret_version) is None:
    raise SystemExit(1)
token = f"DOUG_EXAMPLE_PACK_TOKEN={secret_name}:{secret_version}"
if mode == "token":
    print(token)
    raise SystemExit(0)
if mode != "read":
    raise SystemExit(2)
if not any(plain.get(name) for name in required):
    raise SystemExit(0)
if any(not plain.get(name) for name in required):
    raise SystemExit("incomplete Example Pack read binding")
if re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", plain[required[0]]) is None:
    raise SystemExit(1)
if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", plain[required[1]]) is None:
    raise SystemExit(1)
if re.fullmatch(r"[A-Za-z0-9._-]+", plain[required[2]]) is None:
    raise SystemExit(1)
print(",".join(f"{name}={plain[name]}" for name in required))
' "$2"
}

candidate_url() {
  gcloud run services describe "$1" --project "$PROJECT" --region "$REGION" --format=json \
    | python3 -c "
import json, sys
t = [x for x in json.load(sys.stdin)['status'].get('traffic', []) if x.get('tag') == 'candidate']
print(t[0]['url'] if t else '')"
}

smoke() { # $1 url — 200 or die
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 "$1" || echo 000)
  echo "smoke: $1 -> $code"
  [ "$code" = "200" ]
}

promote_if_healthy() { # $1 service, $2... one or more smoke paths
  local service="$1" url path
  shift
  url=$(candidate_url "$service")
  if [ -z "$url" ]; then
    echo "ERROR: no candidate-tagged revision found on $service to promote" >&2
    return 1
  fi
  for path in "$@"; do
    if ! smoke "$url$path"; then
      echo "ERROR: candidate revision of $service failed its smoke test." >&2
      echo "Traffic stays on the previous revision. Inspect $url, fix, redeploy." >&2
      return 1
    fi
  done
  gcloud run services update-traffic "$service" --to-latest \
    --project "$PROJECT" --region "$REGION" >/dev/null
  echo "promoted: 100% of $service -> latest revision"
}

preregistration_preflight() {
  if [ ! -f "$PREREG_DOC" ] || [ ! -r "$PREREG_DOC" ]; then
    echo "ERROR: cannot read publication pre-registration: $PREREG_DOC" >&2
    return 1
  fi
  if ! grep -q '^\*\*Status:\*\* LOCKED ' "$PREREG_DOC"; then
    echo "ERROR: publication pre-registration is not LOCKED; refusing adjudicator deploy." >&2
    return 1
  fi
}

# The one place this hash is computed. Both doug-api and the adjudicator Job
# stamp it into their env, and a second copy of this one-liner could drift
# from this one if ever edited independently — silently answering "which
# document is in force" two different ways from the same deploy. Callers run
# preregistration_preflight first; this does not repeat that check.
compute_prereg_hash() {
  python3 -c \
    'import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' \
    "$PREREG_DOC"
}

# ADR-0029 / #274. The region check inside `deploy` proves a string is set. It
# does not prove the model is reachable through it, and both ways that has
# already gone wrong are invisible to a non-empty check:
#
#   1. `claude-opus-5` is served in THREE of thirteen Vertex regions for this
#      project. Ten of them 404. A plausible-looking region is a coin flip.
#   2. Model Garden access and throughput quota are separate grants. With
#      access and no quota every call returns 429, which is indistinguishable
#      from a healthy deploy until someone reads a verdict.
#
# Either one leaves reader.py falling soft into the deterministic score on
# every read. That is the contracted behaviour for a stalled upstream and it
# is exactly wrong here: the check run still renders, the PR still gets a
# verdict, and the deep read is simply gone. Nothing pages, and the regression
# is unattributable days later. So the deploy refuses instead, which is the
# same trade `preregistration_preflight` and the showcase smoke already make.
#
# The probe posts an empty body. That fails request validation before the
# model generates anything, so it costs nothing and cannot be rate-limited by
# its own token count — which is what makes a 429 here mean "the allocation is
# zero" rather than "we are momentarily busy".
#
# WHAT THIS DOES NOT CHECK: it runs as the operator's credentials, not as
# doug-api-sa, so it proves the model is available in the region and says
# nothing about whether the RUNTIME identity may call it. That half is the
# roles/aiplatform.user binding in `setup`, asserted by
# test_setup_enables_vertex_and_grants_the_api_identity_access.
reader_models() {
  python3 -c 'import re,pathlib,sys
source = pathlib.Path("doug/reader.py").read_text()
for name in ("MODEL", "MECHANICAL_MODEL"):
    found = re.search(r"^%s = \"([^\"]+)\"" % name, source, re.M)
    if not found:
        sys.exit("could not read %s from doug/reader.py" % name)
    print(found.group(1))'
}

vertex_preflight() {
  local token model code
  token=$(gcloud auth print-access-token --project "$PROJECT" 2>/dev/null)
  if [ -z "$token" ]; then
    echo "ERROR: no access token; run 'gcloud auth login' before deploying." >&2
    return 1
  fi
  # Both tiers ride this transport under ADR-0029, so both are probed. The
  # mechanical tier hits the same region and quota walls as the risk read and
  # is billed on a separate per-base-model quota.
  for model in $(reader_models); do
    code=$(curl -s -m 20 -o /dev/null -w '%{http_code}' -X POST \
      -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d '{}' \
      "https://${VERTEX_REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${VERTEX_REGION}/publishers/anthropic/models/${model}:rawPredict")
    # An ALLOWLIST, not a denylist. Doug flagged the earlier denylist
    # (`reader:incomplete-error-handling`) and was right: a 5xx, or an empty
    # string from a missing curl or a malformed URL, fell through as success
    # and passed the gate this function exists to provide. Only two answers
    # mean the route resolved — 400, the empty body rejected on validation
    # having generated nothing, and 200 if the API ever accepts it.
    case "$code" in
      200|400) : ;;
      404)
        echo "ERROR: $model is not served in $VERTEX_REGION (404)." >&2
        echo "Pick a region that serves it, or enable it in Vertex Model Garden." >&2
        return 1 ;;
      401|403)
        echo "ERROR: $model in $VERTEX_REGION refused the operator credential ($code)." >&2
        echo "Model Garden access for $PROJECT is missing, or the token cannot reach it." >&2
        return 1 ;;
      429)
        echo "ERROR: $model in $VERTEX_REGION has no throughput quota (429)." >&2
        echo "An empty-body probe consumes no input tokens, so a quota rejection here" >&2
        echo "means the allocation is zero, not that the endpoint is busy. Request" >&2
        echo "online_prediction_input_tokens_per_minute_per_base_model for" >&2
        echo "anthropic-$model in $VERTEX_REGION, then re-run. See #274." >&2
        return 1 ;;
      000|"")
        echo "ERROR: probe for $model in $VERTEX_REGION did not complete (network, timeout, or no curl)." >&2
        return 1 ;;
      *)
        echo "ERROR: probe for $model in $VERTEX_REGION answered $code, which is not a" >&2
        echo "resolved route. Only 200 and 400 mean the model is reachable; anything" >&2
        echo "else is refused rather than assumed benign. See ADR-0029." >&2
        return 1 ;;
    esac
  done
}

deploy() {
  preregistration_preflight
  # ADR-0029. Refuse the deploy rather than ship a guessed Vertex region.
  # DOUG_READER_TRANSPORT is pinned to vertex on the line below, so an empty
  # CLOUD_ML_REGION would deploy a service whose every read raises at client
  # construction and falls back to the deterministic score. That failure is
  # silent by design — the reader contracts for a soft fallback — so it would
  # surface as a quality regression nobody can attribute, days later. The
  # rollback for a region that turns out wrong is DOUG_READER_TRANSPORT=anthropic
  # on the running service, which needs no deploy.
  if [ "$READER_TRANSPORT" = "vertex" ] && [ -z "$VERTEX_REGION" ]; then
    echo "ERROR: set VERTEX_REGION to the Vertex region that serves $(grep -m1 '^MODEL' doug/reader.py | cut -d'"' -f2)." >&2
    echo "It is not defaulted: a wrong region fails every read soft into the" >&2
    echo "deterministic fallback instead of failing the deploy. See ADR-0029." >&2
    exit 1
  fi
  # Only when this deploy actually pins Vertex. See READER_TRANSPORT above.
  if [ "$READER_TRANSPORT" = "vertex" ]; then
    vertex_preflight || exit 1
  fi
  local traffic_flags="" prereg_hash example_pack_env="" example_pack_secret=""
  if service_exists "$SERVICE"; then
    traffic_flags="--no-traffic --tag candidate"
    example_pack_env=$(existing_example_pack_binding "$SERVICE" read)
    if [ -n "$example_pack_env" ]; then
      example_pack_secret=$(existing_example_pack_binding "$SERVICE" token)
    fi
  fi
  prereg_hash=$(compute_prereg_hash)
  # Both tiers are configured here on purpose: --set-env-vars replaces the
  # whole env block. The only out-of-band exception is the validated,
  # read-only Example Pack binding above. An installation opted into intent
  # by hand still does not survive a deploy, so opting one in means editing
  # this line.
  #
  # --no-cpu-throttling: the drain runs *after* the response is written
  # (BackgroundTasks) and again in the startup reconcile thread. Under
  # request-based throttling Cloud Run freezes the instance's CPU the moment
  # the response goes out, so a claimed job would sit half-run, holding its
  # row in 'running', until some unrelated request thawed the instance. The
  # queue would look alive and be stalled.
  #
  # DOUG_GITHUB_APP_ID + GITHUB_APP_PRIVATE_KEY are what app_auth.enabled()
  # reads; both must be present or there is no App path at all.
  #
  # DOUG_INTENT_INSTALLATIONS is an ALLOWLIST, not a switch. It replaced
  # DOUG_INTENT=1, which turned the experimental intent tier on for every
  # installation this service reviews — fine while there is one, wrong the
  # moment there are two, because that tier's findings are still unbelieved
  # (the 2026-07-31 derangement check failed its bar) and its read is the
  # larger of the two paid reads. 153075663 is the dogfood installation on
  # coldworkshq — after the org move (#226) it spans doug AND coldworks, so
  # naming it opts both founder-owned repos in; the retired drewjst
  # installation 150424894 covers no doug repo any more. Adding an id here
  # opts a real tenant into an experiment and charges them for it, so it is
  # a deliberate act, not a default.
  #
  # DOUG_WEB_URL: the base URL of the doug-web service, used by receipt_url()
  # to build links to the PR comment dashboard (/dashboard/pr/{n}?repo=…).
  # Empty or unset → no link, and receipts degrade silently. The web_url()
  # helper prefers doug-web's mapped custom domain and falls back to the
  # generated run.app URL, so on a bootstrap deploy where doug-web does not
  # exist yet, $(web_url) is empty and DOUG_WEB_URL gets set to an empty
  # string — exactly why the code tolerates empty values. The domain itself
  # is mapped and cut over by deploy/domains.sh, not here.
  #
  # There is deliberately NO DOUG_PR_COMMENT_INSTALLATIONS here. The staged
  # rollout it gated (ADR-0014 D3a) ended on 2026-08-20 with issue #144; the
  # per-repository `installation_repos.pr_comment` toggle on the dashboard is
  # now the only thing that decides. Re-adding the variable would silently
  # dark every installation not named in it while their toggles still read
  # "on" — see the guard in api/tests/test_deploy_gcp.py.
  #
  # If comments have to stop in a hurry: turn the repository's toggle off on
  # the dashboard (immediate, no deploy), or shift traffic back to the prior
  # revision, which restores the gate AND its reader together because a
  # revision pins image and environment as one. Re-adding the variable here
  # would not stop anything on its own — nothing reads it any more.
  #
  # DOUG_VERIFY_INSTALLATIONS is an ALLOWLIST, not a switch, and it replaced
  # a process-wide DOUG_VERIFY=1 boolean before that boolean was ever set.
  # Grounding buys up to MAX_VERIFY_READS_PER_REVIEW extra paid calls per
  # review and changes what renders on the check run, so switching it on is a
  # decision about a named tenant. The boolean would have made it a decision
  # about every tenant, including every tenant added later — exactly what
  # DOUG_INTENT=1 did before DOUG_INTENT_INSTALLATIONS replaced it (see
  # docs/design/outcome-loop/design-lock.md:64). Empty or unset → grounding is
  # off everywhere. 153075663 is the same dogfood installation
  # DOUG_INTENT_INSTALLATIONS above names. (It read "the two allowlists
  # above" until #144 removed DOUG_PR_COMMENT_INSTALLATIONS; there is one
  # left.)
  #
  # Known limit at switch-on: VERIFY_SCHEMA's predicate enum holds exactly one
  # check, constant_value_is, so most findings will abstain rather than ground.
  # That is the honest starting state, not a fault — abstention costs a call
  # and stores nothing. Widening the enum is tracked separately.
  #
  # DOUG_PREREG_HASH: same value the adjudicator Job below carries, from the
  # same compute_prereg_hash call site. The receipt endpoint reports this as
  # the methodology document currently in force — never a value it reads
  # from anywhere else.
  #
  # WORKOS_CLIENT_ID and WORKOS_API_KEY reach the api and NOTHING else.
  # Production currently uses WorkOS's hosted issuer. A custom AuthKit domain
  # also changes the access-token `iss`; that rollout must add WORKOS_ISSUER to
  # this service's env at the same time or session verification will fail closed.
  # doug-web is --allow-unauthenticated and holds no credential at all (see
  # setup); the console talks to this service over HTTP. The client id is not
  # secret, but it lives in Secret Manager beside the key so the front door
  # has one place to look, and a missing one 503s /v1/installations/bind with
  # a named detail rather than refusing every session as if it were forged.
  gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --service-account "doug-api-sa@$PROJECT.iam.gserviceaccount.com" \
    --add-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,DOUG_API_TOKEN=doug-api-token:latest,GITHUB_WEBHOOK_SECRET=doug-webhook-secret:latest,GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest,DOUG_TOKEN_PEPPER=doug-token-pepper:latest,WORKOS_API_KEY=doug-workos-api-key:latest,WORKOS_CLIENT_ID=doug-workos-client-id:latest,DOUG_INSTALL_FLOW_SECRET=doug-install-flow-secret:latest${example_pack_secret:+,$example_pack_secret}" \
    --set-env-vars "DOUG_READER=1,DOUG_INTENT_INSTALLATIONS=153075663,DOUG_GITHUB_APP_ID=4450932,DOUG_PREREG_HASH=$prereg_hash,DOUG_SHOWCASE_REPO=$SHOWCASE_REPO,DOUG_WEB_URL=$(web_url),DOUG_VERIFY_INSTALLATIONS=153075663,DOUG_READER_TRANSPORT=$READER_TRANSPORT,CLOUD_ML_REGION=$VERTEX_REGION,ANTHROPIC_FEDERATION_RULE_ID=$FEDERATION_RULE_ID,ANTHROPIC_ORGANIZATION_ID=$FEDERATION_ORG_ID,ANTHROPIC_SERVICE_ACCOUNT_ID=$FEDERATION_SERVICE_ACCOUNT_ID,ANTHROPIC_WORKSPACE_ID=$FEDERATION_WORKSPACE_ID${example_pack_env:+,$example_pack_env}" \
    --no-cpu-throttling \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 300 \
    $traffic_flags
  if [ -n "$traffic_flags" ]; then
    # /healthz is intercepted by the Google frontend; openapi.json is a
    # real route through the app. /v1/showcase/queue is smoked here too:
    # it 404s if DOUG_SHOWCASE_REPO is wrong or unset, but /openapi.json
    # returns 200 either way, so that check alone would happily promote a
    # candidate whose public pages are broken. Gated BEFORE
    # update-traffic — a check that runs after traffic moves protects
    # nothing.
    promote_if_healthy "$SERVICE" /openapi.json /v1/showcase/queue /v1/showcase/scoreboard
  else
    smoke "$(api_url)/openapi.json"
    smoke "$(api_url)/v1/showcase/queue"
    smoke "$(api_url)/v1/showcase/scoreboard"
  fi
  # The Job consumes the promoted service's exact immutable image. Building
  # it separately would let the live review and outcome detector drift even
  # when both source deploys began at the same commit.
  adjudicator
  reconcile_job
  api_url
}

adjudicator() {
  local api_image prereg_hash
  preregistration_preflight
  prereg_hash=$(compute_prereg_hash)
  api_image=$(gcloud run services describe "$SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --format='value(spec.template.spec.containers[0].image)')
  if [ -z "$api_image" ]; then
    echo "ERROR: $SERVICE has no deployed image; deploy the API first." >&2
    return 1
  fi

  gcloud run jobs deploy "$ADJUDICATOR_JOB" \
    --image "$api_image" \
    --project "$PROJECT" --region "$REGION" \
    --command python --args=-m,doug.outcome_worker \
    --service-account "doug-adjudicator-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest" \
    --set-env-vars "DOUG_GITHUB_APP_ID=4450932,DOUG_PREREG_HASH=$prereg_hash" \
    --memory 2Gi --cpu 1 --tasks 1 --max-retries 0 --task-timeout 3600s
  echo "adjudicator deployed from $api_image"
}

schedule() {
  local scheduler_sa uri action
  scheduler_sa="doug-scheduler-sa@$PROJECT.iam.gserviceaccount.com"
  uri="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$ADJUDICATOR_JOB:run"

  gcloud run jobs add-iam-policy-binding "$ADJUDICATOR_JOB" \
    --project "$PROJECT" --region "$REGION" \
    --member="serviceAccount:$scheduler_sa" --role=roles/run.invoker >/dev/null

  if gcloud scheduler jobs describe "$SCHEDULER_JOB" \
      --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    action=update
  else
    action=create
  fi
  gcloud scheduler jobs "$action" http "$SCHEDULER_JOB" \
    --project "$PROJECT" --location "$REGION" \
    --schedule "0 3 * * *" --time-zone "Etc/UTC" \
    --uri "$uri" --http-method POST \
    --oauth-service-account-email "$scheduler_sa" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --max-retry-attempts 0
  echo "scheduled: $SCHEDULER_JOB -> $ADJUDICATOR_JOB daily at 03:00 UTC"
}

reconcile_job() {
  local api_image
  api_image=$(gcloud run services describe "$SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --format='value(spec.template.spec.containers[0].image)')
  if [ -z "$api_image" ]; then
    echo "ERROR: $SERVICE has no deployed image; deploy the API first." >&2
    return 1
  fi

  # No DOUG_PREREG_HASH: reconciliation only enqueues outcome_jobs rows, it
  # never adjudicates or publishes anything, so the hash preflight the
  # adjudicator requires does not apply here.
  #
  # 3600s, the adjudicator's timeout, not the 15 minutes this sweep's per-run
  # work looks like it needs. reconcile_all_outcomes walks installations
  # sequentially and store.active_installations() has no ORDER BY, so a task
  # killed at the timeout has no resume point and no fairness: with
  # --max-retries 0 the next execution starts from the same list head and
  # whichever tenants sort last are never reconciled at all, while the
  # symptom in the console is an ordinary timeout rather than a coverage gap.
  # The headroom is what keeps that failure hypothetical; if a sweep ever
  # approaches an hour, the fix is batching with a durable cursor, not a
  # bigger number here.
  gcloud run jobs deploy "$RECONCILE_JOB" \
    --image "$api_image" \
    --project "$PROJECT" --region "$REGION" \
    --command python --args=-m,doug.reconcile_worker \
    --service-account "doug-adjudicator-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest" \
    --set-env-vars "DOUG_GITHUB_APP_ID=4450932" \
    --memory 512Mi --cpu 1 --tasks 1 --max-retries 0 --task-timeout 3600s
  echo "outcome reconciler deployed from $api_image"
}

schedule_reconcile() {
  local scheduler_sa uri action
  scheduler_sa="doug-scheduler-sa@$PROJECT.iam.gserviceaccount.com"
  uri="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$RECONCILE_JOB:run"

  gcloud run jobs add-iam-policy-binding "$RECONCILE_JOB" \
    --project "$PROJECT" --region "$REGION" \
    --member="serviceAccount:$scheduler_sa" --role=roles/run.invoker >/dev/null

  if gcloud scheduler jobs describe "$RECONCILE_SCHEDULER_JOB" \
      --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    action=update
  else
    action=create
  fi
  # Every 6 hours, not daily: reconciliation is cheap (no cloning, no model
  # reads — pulls.list + pulls.get only), and the whole point is shrinking
  # the window a lost webhook can sit undiscovered. The adjudicator stays
  # daily because adjudication itself is expensive and nothing about that
  # cadence is what this Job is fixing.
  gcloud scheduler jobs "$action" http "$RECONCILE_SCHEDULER_JOB" \
    --project "$PROJECT" --location "$REGION" \
    --schedule "0 */6 * * *" --time-zone "Etc/UTC" \
    --uri "$uri" --http-method POST \
    --oauth-service-account-email "$scheduler_sa" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --max-retry-attempts 0
  echo "scheduled: $RECONCILE_SCHEDULER_JOB -> $RECONCILE_JOB every 6h"
}

# Node apps live in an npm workspaces monorepo. Cloud Run `--source ../web`
# can only see the app directory, so it cannot `npm ci` against the root
# lockfile. Build the image from REPO_ROOT via Cloud Build, then deploy
# that image. The Dockerfile path is relative to the monorepo root.
#
# The Artifact Registry repo `doug` is created in setup() only. CI's
# doug-deployer already has cloudbuild.builds.editor + artifactregistry.writer
# + iam.serviceAccountUser (setup-cicd.sh) — enough to submit and push once
# the repo exists, not enough to create it.
ensure_node_artifact_repo() {
  gcloud artifacts repositories describe doug \
    --location="$REGION" --project="$PROJECT" >/dev/null 2>&1 \
    || gcloud artifacts repositories create doug \
      --repository-format=docker \
      --location="$REGION" \
      --project="$PROJECT" \
      --description="Doug Node service images"
}

require_node_artifact_repo() {
  if gcloud artifacts repositories describe doug \
      --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
    return 0
  fi
  echo "ERROR: Artifact Registry repo 'doug' is missing in $PROJECT/$REGION." >&2
  echo "Run: PROJECT=$PROJECT REGION=$REGION $0 setup" >&2
  echo "(or: gcloud artifacts repositories create doug --repository-format=docker --location=$REGION --project=$PROJECT)" >&2
  return 1
}

build_node_image() {
  # $1 = Dockerfile relative to REPO_ROOT (web/Dockerfile | console/Dockerfile)
  # $2 = image name under the doug Artifact Registry repo (doug-web | doug-console)
  #
  # Callers capture stdout as the image tag (`image=$(build_node_image …)`),
  # so every noisy command here must write to stderr. gcloud builds submit
  # streams build logs to stdout by default; --suppress-logs + >&2 keep the
  # captured value a single clean tag.
  local dockerfile=$1 name=$2 image tag
  require_node_artifact_repo >&2
  tag=$(git -C "$REPO_ROOT" rev-parse --short HEAD)
  image="${REGION}-docker.pkg.dev/${PROJECT}/doug/${name}:${tag}"
  gcloud builds submit "$REPO_ROOT" \
    --project "$PROJECT" \
    --config="$SCRIPT_DIR/cloudbuild-node.yaml" \
    --substitutions="_IMAGE=${image},_DOCKERFILE=${dockerfile}" \
    --timeout=1200s \
    --suppress-logs >&2
  printf '%s\n' "$image"
}

web() {
  local traffic_flags="" image
  service_exists "$WEB_SERVICE" && traffic_flags="--no-traffic --tag candidate"
  # DOUG_API_URL is read at request time by the public pages' server
  # components. AuthKit gets its four secrets plus the purpose-scoped install
  # flow signer (see setup()'s
  # doug-web-sa block); its cookie lifetime matches the eight-hour GitHub
  # user-token lifetime rather than AuthKit's 400-day default.
  # --service-account: deploying without it silently falls back to the
  # default compute SA (roles/editor).
  image=$(build_node_image web/Dockerfile doug-web)
  gcloud run deploy "$WEB_SERVICE" \
    --image "$image" \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --service-account "doug-web-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-env-vars "DOUG_API_URL=$(api_url),WORKOS_COOKIE_MAX_AGE=28800,DOUG_GITHUB_APP_SLUG=dougs-review" \
    --set-secrets "WORKOS_CLIENT_ID=doug-workos-client-id:latest,WORKOS_API_KEY=doug-workos-api-key:latest,WORKOS_COOKIE_PASSWORD=doug-workos-cookie-password:latest,NEXT_PUBLIC_WORKOS_REDIRECT_URI=doug-workos-redirect-uri:latest,DOUG_INSTALL_FLOW_SECRET=doug-install-flow-secret:latest" \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 60 \
    $traffic_flags
  # The web deploy had no verification at all: Cloud Run's readiness probe
  # only proves the Next server binds its port, so a build that 500'd on
  # every real route shipped green. The homepage is the real route here.
  if [ -n "$traffic_flags" ]; then
    promote_if_healthy "$WEB_SERVICE" /
  else
    smoke "$(web_url)/"
  fi
  web_url
}

console() {
  # NO staged-traffic dance and NO smoke test: the service is
  # --no-allow-unauthenticated, so an unauthenticated curl from this script
  # gets 403 no matter how healthy the revision is. A failing console is an
  # operator inconvenience, not an outage — the tradeoff web() cannot make.
  local image example_pack_secret=""
  if service_exists "$CONSOLE_SERVICE"; then
    example_pack_secret=$(existing_example_pack_binding "$CONSOLE_SERVICE" token)
  fi
  image=$(build_node_image console/Dockerfile doug-console)
  gcloud run deploy "$CONSOLE_SERVICE" \
    --image "$image" \
    --project "$PROJECT" --region "$REGION" \
    --no-allow-unauthenticated \
    --service-account "doug-console-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-env-vars "DOUG_API_URL=$(api_url)" \
    --set-secrets "DOUG_API_TOKEN=doug-api-token:latest${example_pack_secret:+,$example_pack_secret}" \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 60
  echo "console deployed. Reach it with:"
  echo "  gcloud run services proxy $CONSOLE_SERVICE --project $PROJECT --region $REGION"
}

web_url() {
  # A CUSTOM DOMAIN DOES NOT CHANGE status.url. A Cloud Run service keeps
  # reporting its generated run.app hostname for the life of the service, so
  # reading status.url here is correct only while doug-web has no mapping.
  #
  # It matters because DOUG_WEB_URL is built from this function on every api
  # deploy and lands in the receipt link of every PR comment Doug writes, in
  # other people's repositories, permanently. Without this branch the failure
  # is silent and delayed: deploy/domains.sh cutover sets DOUG_WEB_URL to the
  # mapped domain, everything looks right, and then the next unrelated api
  # deploy — days later, by someone fixing something else — quietly reverts
  # every newly published link to the generated hostname. Nothing errors and
  # no test covers a value that is read from a live service.
  #
  # So the mapping is the source of truth for what the site is called, and
  # status.url is the fallback for a service that has not been given a name.
  local mapped
  mapped=$(gcloud beta run domain-mappings list \
    --project "$PROJECT" --region "$REGION" \
    --filter="spec.routeName=$WEB_SERVICE" \
    --format="value(metadata.name)" 2>/dev/null | head -n 1)
  if [ -n "$mapped" ]; then
    echo "https://$mapped"
    return
  fi
  gcloud run services describe "$WEB_SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

api_url() {
  gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

case "${1:?setup|example-pack-setup|example-pack-enable|example-pack-disable|adjudicator-setup|deploy|adjudicator|schedule|reconcile-job|schedule-reconcile|web|console}" in
  setup) setup ;;
  example-pack-setup) example_pack_setup ;;
  example-pack-enable) example_pack_enable ;;
  example-pack-disable) example_pack_disable ;;
  adjudicator-setup) adjudicator_setup ;;
  deploy) deploy ;;
  adjudicator) adjudicator ;;
  schedule) schedule ;;
  reconcile-job) reconcile_job ;;
  schedule-reconcile) schedule_reconcile ;;
  web) web ;;
  console) console ;;
  *) echo "usage: $0 setup|example-pack-setup|example-pack-enable|example-pack-disable|adjudicator-setup|deploy|adjudicator|schedule|reconcile-job|schedule-reconcile|web|console" >&2; exit 2 ;;
esac
