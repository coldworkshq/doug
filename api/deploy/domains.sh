#!/usr/bin/env bash
# Doug's public address: map doug-web onto doug.coldworks.dev.
#
#   PROJECT=doug-prod0 ./deploy/domains.sh map      # create the mapping, print DNS
#   PROJECT=doug-prod0 ./deploy/domains.sh status   # mapping + certificate state
#   PROJECT=doug-prod0 ./deploy/domains.sh cutover  # move sign-in and receipt links
#
# WHY THIS IS THREE SUBCOMMANDS AND NOT ONE. A Cloud Run domain mapping is
# the small half. Doug's web host is written into two other places that break
# in different directions if they move at the wrong moment:
#
#   1. NEXT_PUBLIC_WORKOS_REDIRECT_URI (secret doug-workos-redirect-uri).
#      AuthKit refuses a redirect_uri that is not on the application's
#      allowlist in the WorkOS dashboard. Flip the secret before the
#      dashboard has the new URI and every sign-in fails at the callback —
#      a signed-out visitor cannot reach the dashboard at all.
#   2. DOUG_WEB_URL on doug-api, which receipt_url() puts into the link in
#      every PR comment Doug writes. Flip it before the certificate is live
#      and Doug publishes links that do not resolve, into other people's
#      repositories, where they persist after the mistake is fixed.
#
# So `map` is safe to run at any time and changes nothing a user can see;
# `cutover` refuses to run until both hazards are checked. Between the two,
# both hostnames serve the site and nothing is broken.
#
# `cutover` is not reversible in the way that matters. The PR comments Doug
# has already written keep whichever host they were written with.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECT=${PROJECT:?set PROJECT}
REGION=${REGION:-us-central1}
WEB_SERVICE=${WEB_SERVICE:-doug-web}
API_SERVICE=${API_SERVICE:-doug-api}
DOMAIN=${DOUG_WEB_DOMAIN:-doug.coldworks.dev}

# Domain mappings are a `beta` surface and are not offered in every Cloud Run
# region. us-central1 offers them; a region that does not fails here with an
# unhelpful message, so name the constraint rather than let it surface as a
# 404 on the mapping resource.
case "$REGION" in
  us-central1|us-east1|us-east4|us-west1|europe-west1|asia-east1|asia-northeast1|asia-southeast1) ;;
  *) echo "domains.sh: $REGION does not offer Cloud Run domain mappings." >&2
     echo "Use a load balancer, or deploy doug-web to a region that does." >&2
     exit 1 ;;
esac

mapping_exists() {
  gcloud beta run domain-mappings describe --domain "$DOMAIN" \
    --project "$PROJECT" --region "$REGION" --format="value(metadata.name)" \
    >/dev/null 2>&1
}

map() {
  if mapping_exists; then
    echo "Mapping for $DOMAIN already exists; leaving it."
  else
    # Cloud Run refuses to map a domain the project has not verified. The
    # verification lives in Search Console against the account running this,
    # is a founder action, and is the single most common reason this command
    # fails on a first run — so say it here rather than in a runbook.
    echo "Creating the mapping. If this fails with a verification error, the"
    echo "domain is not verified for this account: open"
    echo "  https://search.google.com/search-console/welcome"
    echo "verify coldworks.dev, then re-run."
    gcloud beta run domain-mappings create \
      --service "$WEB_SERVICE" --domain "$DOMAIN" \
      --project "$PROJECT" --region "$REGION"
  fi
  echo
  echo "Add these records at the coldworks.dev registrar:"
  gcloud beta run domain-mappings describe --domain "$DOMAIN" \
    --project "$PROJECT" --region "$REGION" \
    --format="table(status.resourceRecords[].name,
                    status.resourceRecords[].type,
                    status.resourceRecords[].rrdata)"
  echo
  echo "Google issues the certificate after the records resolve; that takes"
  echo "up to about 24 hours. Run 'status' until it is READY, then 'cutover'."
}

status() {
  gcloud beta run domain-mappings describe --domain "$DOMAIN" \
    --project "$PROJECT" --region "$REGION" \
    --format="table(metadata.name, status.conditions[].type,
                    status.conditions[].status, status.conditions[].message)"
  echo
  echo -n "https://$DOMAIN/ serves: "
  curl -sS -o /dev/null -w '%{http_code}\n' --max-time 15 "https://$DOMAIN/" \
    || echo "no answer (DNS or certificate not ready)"
}

cutover() {
  local new_redirect="https://$DOMAIN/callback"

  # Hazard 2, checked first because it is checkable without credentials: the
  # site must actually answer over HTTPS on the new name. A 200 here proves
  # DNS resolves, the certificate is issued and valid, and Cloud Run is
  # routing the name to a service that renders — the four things that have to
  # be true before a link to this host may be published into someone's repo.
  echo "Checking $DOMAIN serves over HTTPS..."
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "https://$DOMAIN/") || {
    echo "cutover: https://$DOMAIN/ did not answer. Run 'status'." >&2; exit 1; }
  if [ "$code" != "200" ]; then
    echo "cutover: https://$DOMAIN/ returned $code, not 200. Refusing." >&2
    exit 1
  fi

  # Hazard 1. This is a real check, not a reminder to do one. WorkOS
  # validates redirect_uri against the application allowlist at /authorize
  # and answers 302 to the hosted UI when the URI is allowed, or 400 with
  # invalid_redirect_uri when it is not. Asking WorkOS is the only way to
  # know; asking the operator produces a yes either way.
  echo "Asking WorkOS whether $new_redirect is allowlisted..."
  local client_id authorize_code
  client_id=$(gcloud secrets versions access latest \
    --secret doug-workos-client-id --project "$PROJECT")
  authorize_code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 \
    -G "https://api.workos.com/user_management/authorize" \
    --data-urlencode "client_id=$client_id" \
    --data-urlencode "redirect_uri=$new_redirect" \
    --data-urlencode "response_type=code" \
    --data-urlencode "provider=authkit")
  if [ "$authorize_code" = "400" ]; then
    echo "cutover: WorkOS rejects $new_redirect. Add it under" >&2
    echo "  Redirects in the WorkOS dashboard, KEEPING the existing URI," >&2
    echo "  then re-run. Removing the old one is a separate, later step." >&2
    exit 1
  fi
  echo "WorkOS answered $authorize_code for the new redirect URI."

  echo "Pointing NEXT_PUBLIC_WORKOS_REDIRECT_URI at $new_redirect"
  printf '%s' "$new_redirect" | gcloud secrets versions add doug-workos-redirect-uri \
    --project "$PROJECT" --data-file=-

  # NEXT_PUBLIC_* is inlined into the client bundle at build time, so the
  # secret alone changes nothing until the image is rebuilt. This is the step
  # that is easiest to forget and hardest to see: the secret reads correctly,
  # the service restarts, and the browser keeps sending the old URI.
  echo "Rebuilding doug-web so the new value reaches the client bundle..."
  PROJECT="$PROJECT" REGION="$REGION" ./deploy/gcp.sh web

  # doug-api holds DOUG_WEB_URL for receipt links. gcp.sh's web_url() prefers
  # the mapped domain, so this converges rather than fighting the next deploy.
  echo "Pointing DOUG_WEB_URL at https://$DOMAIN"
  gcloud run services update "$API_SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --update-env-vars "DOUG_WEB_URL=https://$DOMAIN"

  # THE THIRD PLACE THE HOSTNAME LIVES, and the only one that talks to search
  # engines. The gh-pages branch serves a redirect stub at
  # coldworkshq.github.io/doug/ whose <link rel="canonical"> and meta refresh
  # both name the generated host. Left alone after a cutover it does not just
  # send visitors to the old address — it tells crawlers the generated
  # hostname is Doug's canonical one, which is the opposite of what a custom
  # domain is for. It is a branch in git, not a deploy, so this reports it
  # rather than editing it.
  echo
  echo -n "Checking the gh-pages redirect stub... "
  local stub
  stub=$(curl -sS --max-time 20 "https://coldworkshq.github.io/doug/" 2>/dev/null || true)
  if printf '%s' "$stub" | grep -q "$DOMAIN"; then
    echo "already names $DOMAIN."
  else
    echo "STILL NAMES THE OLD HOST."
    echo "  Edit index.html on the gh-pages branch: the canonical link and the"
    echo "  meta refresh both have to become https://$DOMAIN/. Until they do,"
    echo "  the stub declares the generated hostname canonical to crawlers."
    echo "  Consider pointing the repository's homepage URL at https://$DOMAIN"
    echo "  in the same pass; it currently points at the stub."
  fi

  echo
  echo "Done. Both hostnames still serve. Left deliberately undone:"
  echo "  - The old run.app redirect URI is still allowlisted in WorkOS."
  echo "    Remove it only after a real sign-in through $DOMAIN succeeds."
  echo "  - PR comments already published keep the run.app link they were"
  echo "    written with. Nothing rewrites them and nothing should."
}

case "${1:?map|status|cutover}" in
  map) map ;;
  status) status ;;
  cutover) cutover ;;
  *) echo "unknown subcommand: $1" >&2; exit 1 ;;
esac
