#!/usr/bin/env bash
# One-time setup so GitHub Actions can deploy without a long-lived key.
#
# Workload Identity Federation lets a GitHub Actions run exchange its OIDC
# token for short-lived GCP credentials. Nothing secret is stored in the
# repo, which matters here because coldworkshq/doug is public.
#
#   PROJECT=doug-prod0 REPO=coldworkshq/doug bash deploy/setup-cicd.sh
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

# Retry an eventually-consistent IAM call. Creating a principal and using
# it in the same breath loses to propagation often enough that the first
# run of this script failed on it.
retry() {
  local n=0 out
  until out=$("$@" 2>&1); do
    n=$((n + 1))
    if [ "$n" -ge 6 ]; then
      echo "failed after $n attempts:" >&2
      echo "$out" >&2
      return 1
    fi
    echo "  attempt $n failed, retrying in $((n * 5))s..." >&2
    sleep $((n * 5))
  done
  return 0
}

# --- the identity CI acts as -------------------------------------------
# Only "already exists" is swallowed. Hiding all stderr here is what made
# the first failure read as "denied on resource (or it may not exist)"
# with no way to tell which — a silent create is worse than a loud one.
if ! sa_out=$(gcloud iam service-accounts create "$SA_NAME" \
  --project "$PROJECT" --display-name "Doug CI deployer" 2>&1); then
  if echo "$sa_out" | grep -qi "already exists"; then
    echo "service account exists"
  else
    echo "$sa_out" >&2
    exit 1
  fi
fi

# Deploy-time rights only. Secret access belongs to the *runtime* service
# account (granted in gcp.sh setup), not to this one — CI never reads a
# secret, it only points Cloud Run at them.
#
# roles/secretmanager.viewer is metadata, not payloads: it can list secrets
# and describe one, and it cannot access a version. It is here because
# gcp.sh decides whether tracing is on by asking whether the two Langfuse
# secrets exist (ADR-0031), and GCP answers PERMISSION_DENIED rather than
# NOT_FOUND to a principal without project-level get, for secrets that exist
# and for secrets that do not alike. Without this, every CI deploy read the
# pair as absent (2026-09-04); with a per-secret grant instead, deleting the
# pair to turn tracing off would read as "cannot tell" forever, because the
# grant goes with the secret.
for role in \
  roles/run.admin \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/storage.admin \
  roles/iam.serviceAccountUser \
  roles/secretmanager.viewer
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
# here. Pinning assertion.repository is what makes it coldworkshq/doug only,
# and pinning assertion.ref is what makes it main only — without the ref pin,
# any branch of this repo could mint the deployer credential (verified live
# 2026-08-24). The condition evaluates CEL over the RAW assertion, so
# assertion.ref needs no attribute-mapping entry.
#
# Since ADR-0025 retired the reviewer gate, this condition is the ONLY
# boundary between a branch and production — there is no GitHub environment
# on the deploy jobs any more. Weakening either clause here silently reopens
# the path on the next run of this script, because the exists-arm below
# converges the live provider onto whatever CONDITION says.
# test_setup_cicd_pins_both_the_repository_and_the_ref guards the string.
CONDITION="assertion.repository=='$REPO' && assertion.ref=='refs/heads/main'"
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
  --project "$PROJECT" --location=global --workload-identity-pool="$POOL" \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="$CONDITION" 2>/dev/null \
  || {
    # An existing provider keeps whatever condition it was created with — a
    # guarded create is exactly how the repository-only condition outlived
    # the 2026-08-26 tightening until update-oidc was run by hand. Converge
    # it here, loudly: a real failure (permissions, wrong pool) surfaces
    # from the update instead of hiding behind "provider exists".
    echo "provider exists — converging its attribute-condition"
    gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" \
      --project "$PROJECT" --location=global --workload-identity-pool="$POOL" \
      --attribute-condition="$CONDITION"
  }

POOL_ID="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL"

# Only this repository may impersonate the deployer. Retried: the service
# account was created moments ago and the binding races its propagation.
MEMBER="principalSet://iam.googleapis.com/$POOL_ID/attribute.repository/$REPO"
retry gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --project "$PROJECT" \
  --role=roles/iam.workloadIdentityUser \
  --member="$MEMBER"

# Wait until the binding is readable before claiming success. This is what
# we can observe; it is not a guarantee the *token exchange* is live, which
# is a separate propagation path and is what actually failed the first
# deploy. Hence the settle wait below rather than an immediate "Done".
echo "waiting for the binding to become visible..."
for _ in $(seq 1 12); do
  if gcloud iam service-accounts get-iam-policy "$SA" --project "$PROJECT" \
      --format=json 2>/dev/null | grep -qF "$MEMBER"; then
    echo "  binding visible"
    break
  fi
  sleep 5
done

# Token exchange lags the policy write. Deploying inside this window fails
# with 'iam.serviceAccounts.getAccessToken denied', which reads like a
# misconfiguration and is not one.
echo "letting token exchange settle (60s)..."
sleep 60

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

It must print a condition naming $REPO and refs/heads/main. If it is
empty, delete the provider and re-create it — an unconditioned pool is
world-writable. If it prints anything else, re-run this script: the
provider step converges an existing provider's condition in place.

If the first deploy still fails on 'iam.serviceAccounts.getAccessToken
denied', that is propagation, not configuration. Re-run it:

  gh run rerun --repo $REPO --failed <run-id>
EOF
