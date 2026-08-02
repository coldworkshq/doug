#!/usr/bin/env bash
# Doug on GCP: Cloud Run (API) + Cloud SQL Postgres (outcome ledger).
#
# One-time-ish and idempotent where possible. Requires: gcloud authed on a
# project with billing. Secrets go to Secret Manager, never into env specs.
#
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh setup   # APIs, SQL, secrets, IAM
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh deploy  # build + deploy the API
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh web     # build + deploy the site
#
# `deploy` and `web` are what CI runs on every merge to main
# (.github/workflows/deploy.yml), so they are pure deploys — no IAM, no
# resource creation, nothing that needs admin rights. That is what lets the
# CI principal stay narrow. Anything privileged belongs in `setup`.
set -euo pipefail

PROJECT=${PROJECT:?set PROJECT}
REGION=${REGION:-us-central1}
INSTANCE=doug-ledger
SERVICE=doug-api
WEB_SERVICE=doug-web
CONN="$PROJECT:$REGION:$INSTANCE"
# The dashboard shows one repo's queue; unset would mix the backfilled
# probe corpora into it.
QUEUE_REPO=${QUEUE_REPO:-drewjst/doug}

setup() {
  # compute.googleapis.com is not used directly, but enabling it is what
  # creates the default compute service account the secret bindings below
  # attach to — on a project that never touched Compute, that SA simply
  # does not exist and setup used to silently bind secrets to nobody.
  gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    secretmanager.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com compute.googleapis.com --project "$PROJECT"

  if ! gcloud sql instances describe "$INSTANCE" --project "$PROJECT" >/dev/null 2>&1; then
    # Smallest sensible tier (~$10/mo). The ledger outlives any one service.
    gcloud sql instances create "$INSTANCE" \
      --database-version=POSTGRES_18 --tier=db-f1-micro --edition=enterprise \
      --region="$REGION" --project "$PROJECT" --async
  fi

  openssl rand -hex 32 | tr -d '\n' \
    | gcloud secrets create doug-api-token --data-file=- --project "$PROJECT" 2>/dev/null \
    || echo "doug-api-token secret exists; leaving it"

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
           doug-webhook-secret doug-github-app-key; do
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

  # The default compute SA keeps every binding it already holds — nothing
  # here revokes one. doug-web has no --service-account of its own yet (see
  # web()), so it runs as that SA and reads doug-api-token as that identity;
  # that single binding is asserted below rather than dropped when doug-api
  # moved off the shared identity. Do not "tidy" either the binding or this
  # block away: losing it breaks the dashboard on the next web deploy, not
  # on this command, which is the worst possible moment to find out. Both go
  # when doug-web gets its own SA.
  #
  # Resolved from the project number for the same reason $SA is constructed
  # rather than filtered: a display-name filter returns empty on a project
  # where the SA does not exist yet, and the empty string flows into
  # --member.
  PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
  WEB_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$WEB_SA" --project "$PROJECT" >/dev/null 2>&1; then
    echo "ERROR: default compute service account $WEB_SA does not exist yet." >&2
    echo "Enabling compute.googleapis.com (done above) creates it, but not instantly —" >&2
    echo "wait a minute and re-run setup." >&2
    exit 1
  fi
  gcloud secrets add-iam-policy-binding doug-api-token --project "$PROJECT" \
    --member="serviceAccount:$WEB_SA" \
    --role=roles/secretmanager.secretAccessor >/dev/null

  # ANTHROPIC key: create manually so it never sits in shell history:
  #   gcloud secrets create doug-anthropic-key --data-file=/path/to/keyfile
  echo "setup done (check SQL instance state before first deploy)"
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

promote_if_healthy() { # $1 service, $2 smoke path
  local url
  url=$(candidate_url "$1")
  if [ -z "$url" ]; then
    echo "ERROR: no candidate-tagged revision found on $1 to promote" >&2
    return 1
  fi
  if ! smoke "$url$2"; then
    echo "ERROR: candidate revision of $1 failed its smoke test." >&2
    echo "Traffic stays on the previous revision. Inspect $url, fix, redeploy." >&2
    return 1
  fi
  gcloud run services update-traffic "$1" --to-latest \
    --project "$PROJECT" --region "$REGION" >/dev/null
  echo "promoted: 100% of $1 -> latest revision"
}

deploy() {
  local traffic_flags=""
  service_exists "$SERVICE" && traffic_flags="--no-traffic --tag candidate"
  # Both tiers are set here on purpose: --set-env-vars replaces the whole
  # env block, so anything set out-of-band is wiped by the next deploy.
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
  gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --service-account "doug-api-sa@$PROJECT.iam.gserviceaccount.com" \
    --add-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,DOUG_API_TOKEN=doug-api-token:latest,ANTHROPIC_API_KEY=doug-anthropic-key:latest,GITHUB_WEBHOOK_SECRET=doug-webhook-secret:latest,GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest" \
    --set-env-vars "DOUG_READER=1,DOUG_INTENT=1,DOUG_GITHUB_APP_ID=4450932" \
    --no-cpu-throttling \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 300 \
    $traffic_flags
  if [ -n "$traffic_flags" ]; then
    # /healthz is intercepted by the Google frontend; openapi.json is a
    # real route through the app.
    promote_if_healthy "$SERVICE" /openapi.json
  else
    smoke "$(api_url)/openapi.json"
  fi
  api_url
}

web() {
  local traffic_flags=""
  service_exists "$WEB_SERVICE" && traffic_flags="--no-traffic --tag candidate"
  # Built from ../web, so this runs from api/ like every other command here.
  # DOUG_API_URL is read at request time by the dashboard's server component.
  gcloud run deploy "$WEB_SERVICE" \
    --source ../web \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "DOUG_API_URL=$(api_url),DOUG_QUEUE_REPO=$QUEUE_REPO" \
    --set-secrets "DOUG_API_TOKEN=doug-api-token:latest" \
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

web_url() {
  gcloud run services describe "$WEB_SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

api_url() {
  gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

"${1:?setup|deploy|web}"
