#!/usr/bin/env bash
# Doug on GCP: Cloud Run (API) + Cloud SQL Postgres (outcome ledger).
#
# One-time-ish and idempotent where possible. Requires: gcloud authed on a
# project with billing. Secrets go to Secret Manager, never into env specs.
#
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh setup   # APIs, SQL, secrets, IAM
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh adjudicator-setup # M3 IAM only
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh deploy  # build + deploy the API
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh adjudicator # deploy M3 Job
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh schedule # create/update daily trigger
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
INSTANCE=doug-ledger
SERVICE=doug-api
WEB_SERVICE=doug-web
CONSOLE_SERVICE=doug-console
ADJUDICATOR_JOB=doug-adjudicator
SCHEDULER_JOB=doug-adjudicator-daily
CONN="$PROJECT:$REGION:$INSTANCE"
# The showcase queue shows one repo's queue; unset would mix the backfilled
# probe corpora into it.
SHOWCASE_REPO=${SHOWCASE_REPO:-drewjst/doug}
PREREG_DOC="$REPO_ROOT/docs/design/outcome-loop/publication-preregistration.md"

setup() {
  # compute.googleapis.com is not used directly, but enabling it is what
  # creates the default compute service account the secret bindings below
  # attach to — on a project that never touched Compute, that SA simply
  # does not exist and setup used to silently bind secrets to nobody.
  gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    secretmanager.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com compute.googleapis.com \
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

  for s in doug-database-url doug-api-token doug-anthropic-key \
           doug-webhook-secret doug-github-app-key doug-token-pepper; do
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
  # doug-web binds NO secret. It serves only /v1/showcase/queue, which is
  # unauthenticated and pinned by the API's own DOUG_SHOWCASE_REPO. A
  # --allow-unauthenticated service holding an operator credential was the
  # hole this closed; test_deploy_gcp.py pins it shut.

  # The default compute SA may still hold a leftover secretAccessor on
  # doug-api-token from before doug-web had its own identity. That is a
  # one-off operator action, not a setup step — see docs/OPERATIONS.md,
  # "Revoke the default compute SA's access to doug-api-token".

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

  # Grant yourself the ability to invoke the gated console:
  #   gcloud run services add-iam-policy-binding doug-console --project "$PROJECT" \
  #     --region "$REGION" --member="user:YOUR@EMAIL" --role=roles/run.invoker

  # ANTHROPIC key: create manually so it never sits in shell history:
  #   gcloud secrets create doug-anthropic-key --data-file=/path/to/keyfile
  echo "setup done (check SQL instance state before first deploy)"
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

deploy() {
  preregistration_preflight
  local traffic_flags="" prereg_hash
  service_exists "$SERVICE" && traffic_flags="--no-traffic --tag candidate"
  prereg_hash=$(compute_prereg_hash)
  # Both tiers are configured here on purpose: --set-env-vars replaces the
  # whole env block, so anything set out-of-band is wiped by the next deploy.
  # That cuts both ways for the intent allowlist below — an installation
  # opted in by hand on the console does not survive a deploy, so opting one
  # in means editing this line.
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
  # larger of the two paid reads. 150424894 is the dogfood installation on
  # drewjst. Adding an id here opts a real tenant into an experiment and
  # charges them for it, so it is a deliberate act, not a default.
  #
  # DOUG_PREREG_HASH: same value the adjudicator Job below carries, from the
  # same compute_prereg_hash call site. The receipt endpoint reports this as
  # the methodology document currently in force — never a value it reads
  # from anywhere else.
  gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --service-account "doug-api-sa@$PROJECT.iam.gserviceaccount.com" \
    --add-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,DOUG_API_TOKEN=doug-api-token:latest,ANTHROPIC_API_KEY=doug-anthropic-key:latest,GITHUB_WEBHOOK_SECRET=doug-webhook-secret:latest,GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest,DOUG_TOKEN_PEPPER=doug-token-pepper:latest" \
    --set-env-vars "DOUG_READER=1,DOUG_INTENT_INSTALLATIONS=150424894,DOUG_GITHUB_APP_ID=4450932,DOUG_PREREG_HASH=$prereg_hash,DOUG_SHOWCASE_REPO=$SHOWCASE_REPO" \
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
    promote_if_healthy "$SERVICE" /openapi.json /v1/showcase/queue
  else
    smoke "$(api_url)/openapi.json"
    smoke "$(api_url)/v1/showcase/queue"
  fi
  # The Job consumes the promoted service's exact immutable image. Building
  # it separately would let the live review and outcome detector drift even
  # when both source deploys began at the same commit.
  adjudicator
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

web() {
  local traffic_flags=""
  service_exists "$WEB_SERVICE" && traffic_flags="--no-traffic --tag candidate"
  # Built from ../web, so this runs from api/ like every other command here.
  # DOUG_API_URL is read at request time by the public pages' server
  # components. No secrets: see setup()'s doug-web-sa block.
  # --service-account: deploying without it silently falls back to the
  # default compute SA (roles/editor).
  gcloud run deploy "$WEB_SERVICE" \
    --source ../web \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --service-account "doug-web-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-env-vars "DOUG_API_URL=$(api_url)" \
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
  gcloud run deploy "$CONSOLE_SERVICE" \
    --source ../console \
    --project "$PROJECT" --region "$REGION" \
    --no-allow-unauthenticated \
    --service-account "doug-console-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-env-vars "DOUG_API_URL=$(api_url)" \
    --set-secrets "DOUG_API_TOKEN=doug-api-token:latest" \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 60
  echo "console deployed. Reach it with:"
  echo "  gcloud run services proxy $CONSOLE_SERVICE --project $PROJECT --region $REGION"
}

web_url() {
  gcloud run services describe "$WEB_SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

api_url() {
  gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

case "${1:?setup|adjudicator-setup|deploy|adjudicator|schedule|web|console}" in
  setup) setup ;;
  adjudicator-setup) adjudicator_setup ;;
  deploy) deploy ;;
  adjudicator) adjudicator ;;
  schedule) schedule ;;
  web) web ;;
  console) console ;;
  *) echo "usage: $0 setup|adjudicator-setup|deploy|adjudicator|schedule|web|console" >&2; exit 2 ;;
esac
