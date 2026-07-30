#!/usr/bin/env bash
# Doug on GCP: Cloud Run (API) + Cloud SQL Postgres (outcome ledger).
#
# One-time-ish and idempotent where possible. Requires: gcloud authed on a
# project with billing. Secrets go to Secret Manager, never into env specs.
#
#   PROJECT=vestige-00 REGION=us-central1 ./deploy/gcp.sh setup   # APIs, SQL, secrets
#   PROJECT=vestige-00 REGION=us-central1 ./deploy/gcp.sh deploy  # build + deploy
set -euo pipefail

PROJECT=${PROJECT:?set PROJECT}
REGION=${REGION:-us-central1}
INSTANCE=doug-ledger
SERVICE=doug-api
CONN="$PROJECT:$REGION:$INSTANCE"

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

  # ANTHROPIC key: create manually so it never sits in shell history:
  #   gcloud secrets create doug-anthropic-key --data-file=/path/to/keyfile
  echo "setup done (check SQL instance state before first deploy)"
}

deploy() {
  SA=$(gcloud iam service-accounts list --project "$PROJECT" \
    --filter="displayName:'Default compute service account'" --format="value(email)")
  for s in doug-database-url doug-api-token doug-anthropic-key; do
    gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
      --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor >/dev/null
  done

  gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --add-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,DOUG_API_TOKEN=doug-api-token:latest,ANTHROPIC_API_KEY=doug-anthropic-key:latest" \
    --set-env-vars "DOUG_READER=1" \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 300
  gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url)"
}

"${1:?setup|deploy}"
