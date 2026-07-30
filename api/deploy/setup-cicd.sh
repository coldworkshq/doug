#!/usr/bin/env bash
# One-time setup so GitHub Actions can deploy without a long-lived key.
#
# Workload Identity Federation lets a GitHub Actions run exchange its OIDC
# token for short-lived GCP credentials. Nothing secret is stored in the
# repo, which matters here because drewjst/doug is public.
#
#   PROJECT=doug-prod0 REPO=drewjst/doug bash deploy/setup-cicd.sh
#
# Idempotent: every create is guarded, so re-running is safe.
set -euo pipefail

PROJECT=${PROJECT:?set PROJECT}
REPO=${REPO:?set REPO as owner/name}
POOL=github
PROVIDER=github-oidc
SA_NAME=doug-deployer

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA="$SA_NAME@$PROJECT.iam.gserviceaccount.com"

gcloud services enable iamcredentials.googleapis.com sts.googleapis.com \
  --project "$PROJECT"

# --- the identity CI acts as -------------------------------------------
gcloud iam service-accounts create "$SA_NAME" \
  --project "$PROJECT" --display-name "Doug CI deployer" 2>/dev/null \
  || echo "service account exists"

# Deploy-time rights only. Secret access belongs to the *runtime* service
# account (granted in gcp.sh setup), not to this one — CI never reads a
# secret, it only points Cloud Run at them.
for role in \
  roles/run.admin \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/storage.admin \
  roles/iam.serviceAccountUser
do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA" --role="$role" \
    --condition=None >/dev/null
  echo "granted $role"
done

# --- the federation ----------------------------------------------------
gcloud iam workload-identity-pools create "$POOL" \
  --project "$PROJECT" --location=global --display-name="GitHub" 2>/dev/null \
  || echo "pool exists"

# The attribute-condition is the security boundary. Without it, ANY GitHub
# repository on the internet could mint tokens for this pool and deploy
# here. Pinning assertion.repository is what makes it drewjst/doug only.
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
  --project "$PROJECT" --location=global --workload-identity-pool="$POOL" \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='$REPO'" 2>/dev/null \
  || echo "provider exists (verify its attribute-condition pins $REPO)"

POOL_ID="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL"

# Only this repository may impersonate the deployer.
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --project "$PROJECT" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/$POOL_ID/attribute.repository/$REPO" \
  >/dev/null

PROVIDER_PATH="$POOL_ID/providers/$PROVIDER"

cat <<EOF

Done. Point the workflow at it:

  gh variable set GCP_WIF_PROVIDER --repo $REPO \\
    --body "$PROVIDER_PATH"
  gh variable set GCP_DEPLOY_SA --repo $REPO \\
    --body "$SA"

These are repo *variables*, not secrets — neither value is sensitive, and
access is controlled by the attribute-condition above, not by hiding them.

Verify the boundary held:

  gcloud iam workload-identity-pools providers describe $PROVIDER \\
    --project $PROJECT --location=global --workload-identity-pool=$POOL \\
    --format='value(attributeCondition)'

It must print a condition naming $REPO. If it is empty, delete the
provider and re-create it — an unconditioned pool is world-writable.
EOF
