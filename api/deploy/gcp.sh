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
  gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    secretmanager.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com --project "$PROJECT"

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
  SA=$(gcloud iam service-accounts list --project "$PROJECT" \
    --filter="displayName:'Default compute service account'" --format="value(email)")
  # NOTE for the GitHub App work: this binds secrets to the *default*
  # compute service account, so every workload in the project can read
  # them. Tolerable for these four; not tolerable for an App private key,
  # which needs a dedicated service account.
  for s in doug-database-url doug-api-token doug-anthropic-key doug-webhook-secret; do
    gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
      --member="serviceAccount:$SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null 2>&1 || true
  done

  # ANTHROPIC key: create manually so it never sits in shell history:
  #   gcloud secrets create doug-anthropic-key --data-file=/path/to/keyfile
  echo "setup done (check SQL instance state before first deploy)"
}

deploy() {
  # Both tiers are set here on purpose: --set-env-vars replaces the whole
  # env block, so anything set out-of-band is wiped by the next deploy.
  gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --add-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,DOUG_API_TOKEN=doug-api-token:latest,ANTHROPIC_API_KEY=doug-anthropic-key:latest,GITHUB_WEBHOOK_SECRET=doug-webhook-secret:latest" \
    --set-env-vars "DOUG_READER=1,DOUG_INTENT=1" \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 300
  gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

web() {
  # Built from ../web, so this runs from api/ like every other command here.
  # DOUG_API_URL is read at request time by the dashboard's server component.
  gcloud run deploy "$WEB_SERVICE" \
    --source ../web \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "DOUG_API_URL=$(api_url),DOUG_QUEUE_REPO=$QUEUE_REPO" \
    --set-secrets "DOUG_API_TOKEN=doug-api-token:latest" \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 60
  gcloud run services describe "$WEB_SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

api_url() {
  gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

"${1:?setup|deploy|web}"
