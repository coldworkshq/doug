#!/usr/bin/env bash
# Production-executable proof for the WorkOS session front door.
#
# This script is read-only. It accepts short-lived WorkOS access tokens,
# sends them only as Authorization bearer values, and never prints response
# bodies. The operator performs the one suspension/restore mutation by hand
# and confirms each webhook delivery before the script makes the next read.

set -u
set -o pipefail

PASS=0
FAIL=0
code=""

preflight_fail() {
  printf 'preflight failed: %s\n' "$1" >&2
  exit 2
}

require_value() {
  local name=$1
  [ -n "${!name-}" ] || preflight_fail "$name is required"
}

for command_name in curl jq mktemp; do
  command -v "$command_name" >/dev/null 2>&1 \
    || preflight_fail "$command_name is required"
done

for required_name in \
  DOUG_URL \
  A_SESSION_JWT A_INSTALLATION_ID \
  B_SESSION_JWT B_INSTALLATION_ID \
  ONE_REPO_SESSION_JWT ONE_REPO_ALLOWED ONE_REPO_FORBIDDEN \
  ORGLESS_SESSION_JWT EXPIRED_SESSION_JWT UNMAPPED_ORG_SESSION_JWT \
  READ_ONLY_SESSION_JWT READ_ONLY_INSTALLATION_ID
do
  require_value "$required_name"
done

[[ "$DOUG_URL" =~ ^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[1-9][0-9]{0,4})?$ ]] \
  || preflight_fail "DOUG_URL must be an HTTPS origin without a trailing slash"

for id_name in A_INSTALLATION_ID B_INSTALLATION_ID READ_ONLY_INSTALLATION_ID; do
  id_value=${!id_name}
  [[ "$id_value" =~ ^[1-9][0-9]*$ ]] \
    || preflight_fail "$id_name must be a positive integer"
done
[ "$A_INSTALLATION_ID" != "$B_INSTALLATION_ID" ] \
  || preflight_fail "A and B installation ids must differ"

for jwt_name in \
  A_SESSION_JWT B_SESSION_JWT ONE_REPO_SESSION_JWT ORGLESS_SESSION_JWT \
  EXPIRED_SESSION_JWT UNMAPPED_ORG_SESSION_JWT READ_ONLY_SESSION_JWT
do
  jwt_value=${!jwt_name}
  [[ "$jwt_value" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]] \
    || preflight_fail "$jwt_name must have three JWT segments"
done

for repo_name in ONE_REPO_ALLOWED ONE_REPO_FORBIDDEN; do
  repo_value=${!repo_name}
  [[ "$repo_value" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] \
    || preflight_fail "$repo_name must be a full repository name"
done
[ "$ONE_REPO_ALLOWED" != "$ONE_REPO_FORBIDDEN" ] \
  || preflight_fail "allowed and forbidden repositories must differ"

jwt_claim() {
  local jwt=$1 claim=$2 payload normalized remainder
  payload=${jwt#*.}
  payload=${payload%%.*}
  normalized=${payload//-/+}
  normalized=${normalized//_/\/}
  remainder=$(( ${#normalized} % 4 ))
  if [ "$remainder" -eq 2 ]; then
    normalized="${normalized}=="
  elif [ "$remainder" -eq 3 ]; then
    normalized="${normalized}="
  elif [ "$remainder" -eq 1 ]; then
    return 1
  fi
  jq -Rer --arg claim "$claim" \
    '@base64d | fromjson | .[$claim] | strings | select(length > 0)' \
    <<<"$normalized" 2>/dev/null
}

A_SUB=$(jwt_claim "$A_SESSION_JWT" sub) \
  || preflight_fail "A session must carry a non-empty sub claim"
A_ORG=$(jwt_claim "$A_SESSION_JWT" org_id) \
  || preflight_fail "A session must carry a non-empty org_id claim"
B_SUB=$(jwt_claim "$B_SESSION_JWT" sub) \
  || preflight_fail "B session must carry a non-empty sub claim"
B_ORG=$(jwt_claim "$B_SESSION_JWT" org_id) \
  || preflight_fail "B session must carry a non-empty org_id claim"
ONE_SUB=$(jwt_claim "$ONE_REPO_SESSION_JWT" sub) \
  || preflight_fail "one-repo session must carry a non-empty sub claim"
ONE_ORG=$(jwt_claim "$ONE_REPO_SESSION_JWT" org_id) \
  || preflight_fail "one-repo session must carry a non-empty org_id claim"

[ "$A_SUB" = "$B_SUB" ] \
  || preflight_fail "A and B sessions must carry the same sub claim"
[ "$A_ORG" != "$B_ORG" ] \
  || preflight_fail "A and B sessions must carry different org_id claims"
[ "$ONE_ORG" = "$A_ORG" ] \
  || preflight_fail "one-repo session must carry A's org_id claim"
[ "$ONE_SUB" != "$A_SUB" ] \
  || preflight_fail "one-repo session must carry a different sub claim"

unset A_SUB A_ORG B_SUB B_ORG ONE_SUB ONE_ORG jwt_value id_value repo_value

RESPONSE_FILE=$(mktemp "${TMPDIR:-/tmp}/doug-session-proof.XXXXXX") \
  || preflight_fail "could not create response file"
trap 'rm -f -- "$RESPONSE_FILE"' EXIT

req() { # req <method> <path> <access-token> [json-body]
  local method=$1 path=$2 token=$3 data=${4-} result
  local curl_args=(
    -sS -o "$RESPONSE_FILE" -w '%{http_code}' -X "$method"
    "$DOUG_URL$path" -H "Authorization: Bearer $token"
  )
  if [ -n "$data" ]; then
    curl_args+=(-H 'content-type: application/json' -d "$data")
  fi
  : >"$RESPONSE_FILE"
  code=$(curl "${curl_args[@]}" 2>/dev/null)
  result=$?
  if [ "$result" -ne 0 ] || ! [[ "$code" =~ ^[0-9][0-9][0-9]$ ]]; then
    code=000
  fi
}

gate() { # gate <number> <safe-label> <true|false> <status-summary>
  local number=$1 label=$2 ok=$3 status=$4
  if [ "$ok" = true ]; then
    PASS=$((PASS + 1))
    printf 'PASS  gate %s - %s\n' "$number" "$label"
  else
    FAIL=$((FAIL + 1))
    printf 'FAIL  gate %s - %s status=%s reason=contract-refused\n' \
      "$number" "$label" "$status"
  fi
}

runs_are_scoped() { # runs_are_scoped <installation-id>
  local installation_id=$1
  jq -e --argjson installation_id "$installation_id" '
    (.items | type == "array")
    and (.items | length > 0)
    and all(.items[]; .installation_id == $installation_id)
  ' "$RESPONSE_FILE" >/dev/null 2>&1
}

runs_are_one_repo() { # runs_are_one_repo <installation-id> <full-name>
  local installation_id=$1 full_name=$2
  jq -e --argjson installation_id "$installation_id" --arg full_name "$full_name" '
    (.items | type == "array")
    and (.items | length > 0)
    and all(.items[];
      .installation_id == $installation_id and .repo == $full_name
    )
  ' "$RESPONSE_FILE" >/dev/null 2>&1
}

connection_is_setup_required() { # connection_is_setup_required <installation-id>
  local installation_id=$1
  jq -e --argjson installation_id "$installation_id" '
    (.connections | type == "array")
    and ([.connections[] | select(
      .installation_id == $installation_id
      and .status == "setup_required"
      and (.repositories | type == "array")
      and (.repositories | length > 0)
    )] | length == 1)
  ' "$RESPONSE_FILE" >/dev/null 2>&1
}

# Gate 1: A's selected organization is non-vacuous, multi-repo, and exclusive.
req GET '/v1/sessions/runs?repo=all' "$A_SESSION_JWT"
g1_code=$code
g1_ok=false
if [ "$code" = 200 ] && runs_are_scoped "$A_INSTALLATION_ID" \
  && jq -e --arg allowed "$ONE_REPO_ALLOWED" --arg forbidden "$ONE_REPO_FORBIDDEN" '
    any(.items[]; .repo == $allowed) and any(.items[]; .repo == $forbidden)
  ' "$RESPONSE_FILE" >/dev/null 2>&1
then
  g1_ok=true
fi
gate 1 'A session is confined to its multi-repo installation' "$g1_ok" "$g1_code"

# Gate 2: the same user's other selected organization cannot borrow A's rows.
req GET '/v1/sessions/runs?repo=all' "$B_SESSION_JWT"
g2_code=$code
g2_ok=false
if [ "$code" = 200 ] && runs_are_scoped "$B_INSTALLATION_ID"; then
  g2_ok=true
fi
gate 2 'B session is confined to its distinct installation' "$g2_ok" "$g2_code"

# Gate 3: a user-level one-repo entitlement remains narrower than its org.
g3_ok=true
g3_status=""
req GET "/v1/sessions/runs?repo=$ONE_REPO_FORBIDDEN" "$A_SESSION_JWT"
g3_status="a-forbidden:$code"
[ "$code" = 200 ] && runs_are_one_repo "$A_INSTALLATION_ID" "$ONE_REPO_FORBIDDEN" \
  || g3_ok=false
req GET '/v1/sessions/runs?repo=all' "$ONE_REPO_SESSION_JWT"
g3_status="$g3_status,one-all:$code"
[ "$code" = 200 ] && runs_are_one_repo "$A_INSTALLATION_ID" "$ONE_REPO_ALLOWED" \
  || g3_ok=false
req GET "/v1/sessions/runs?repo=$ONE_REPO_ALLOWED" "$ONE_REPO_SESSION_JWT"
g3_status="$g3_status,one-allowed:$code"
[ "$code" = 200 ] && runs_are_one_repo "$A_INSTALLATION_ID" "$ONE_REPO_ALLOWED" \
  || g3_ok=false
req GET "/v1/sessions/runs?repo=$ONE_REPO_FORBIDDEN" "$ONE_REPO_SESSION_JWT"
forbidden_code=$code
req GET '/v1/sessions/runs?repo=__doug_isolation_proof__/absent' "$ONE_REPO_SESSION_JWT"
absent_code=$code
g3_status="$g3_status,forbidden:$forbidden_code,absent:$absent_code"
[ "$forbidden_code" = 404 ] && [ "$absent_code" = 404 ] \
  || g3_ok=false
gate 3 'one-repo member cannot widen its explicit scope' "$g3_ok" "$g3_status"

# Gate 4: orgless is a valid claims-only state, never run-data authority.
req GET '/v1/sessions/connections' "$ORGLESS_SESSION_JWT"
orgless_connections_code=$code
req GET '/v1/sessions/runs?repo=all' "$ORGLESS_SESSION_JWT"
orgless_runs_code=$code
g4_ok=false
if [ "$orgless_connections_code" = 200 ] && [ "$orgless_runs_code" = 401 ]; then
  g4_ok=true
fi
gate 4 'orgless discovery is valid but run data is refused' "$g4_ok" \
  "connections:$orgless_connections_code,runs:$orgless_runs_code"

# Gate 5: the operator owns the mutation; the script proves the next reads.
req GET '/v1/sessions/runs?repo=all' "$A_SESSION_JWT"
suspend_before_code=$code
suspend_before_ok=false
if [ "$code" = 200 ] && runs_are_scoped "$A_INSTALLATION_ID"; then
  suspend_before_ok=true
fi
printf 'Wait for installation.suspend delivery 202, then type exactly: SUSPENDED %s\n' \
  "$A_INSTALLATION_ID" >&2
suspend_confirmation=""
read -r suspend_confirmation || true
suspend_confirm_ok=false
[ "$suspend_confirmation" = "SUSPENDED $A_INSTALLATION_ID" ] \
  && suspend_confirm_ok=true

# This is deliberately the very next API request after the confirmation.
req GET '/v1/sessions/runs?repo=all' "$A_SESSION_JWT"
suspended_code=$code

printf 'Wait for installation.unsuspend delivery 202, then type exactly: RESTORED %s\n' \
  "$A_INSTALLATION_ID" >&2
restore_confirmation=""
read -r restore_confirmation || true
restore_confirm_ok=false
[ "$restore_confirmation" = "RESTORED $A_INSTALLATION_ID" ] \
  && restore_confirm_ok=true

# This is deliberately the very next API request after the confirmation and
# is cleanup evidence even when an earlier subcheck failed.
req GET '/v1/sessions/runs?repo=all' "$A_SESSION_JWT"
restored_code=$code
restored_ok=false
if [ "$code" = 200 ] && runs_are_scoped "$A_INSTALLATION_ID"; then
  restored_ok=true
fi
g5_ok=false
if [ "$suspend_before_ok" = true ] \
  && [ "$suspend_confirm_ok" = true ] \
  && [ "$suspended_code" = 401 ] \
  && [ "$restore_confirm_ok" = true ] \
  && [ "$restored_ok" = true ]
then
  g5_ok=true
fi
gate 5 'suspension refuses the next read and restoration recovers' "$g5_ok" \
  "before:$suspend_before_code,suspended:$suspended_code,restored:$restored_code"

# Gate 6: change the first significant signature character, never padding.
signature=${A_SESSION_JWT##*.}
signature_first=${signature:0:1}
if [ "$signature_first" = A ]; then
  replacement=B
else
  replacement=A
fi
tampered_session="${A_SESSION_JWT%.*}.${replacement}${signature:1}"
req GET '/v1/sessions/runs?repo=all' "$tampered_session"
tampered_code=$code
req GET '/v1/sessions/runs?repo=all' "$EXPIRED_SESSION_JWT"
expired_code=$code
g6_ok=false
if [ "$tampered_code" = 401 ] && [ "$expired_code" = 401 ]; then
  g6_ok=true
fi
gate 6 'tampered and expired access tokens are refused' "$g6_ok" \
  "tampered:$tampered_code,expired:$expired_code"
unset tampered_session signature signature_first replacement

# Gate 7: a verified but unmapped org is distinct from an invalid session.
req GET '/v1/sessions/connections' "$UNMAPPED_ORG_SESSION_JWT"
unmapped_connections_code=$code
req GET '/v1/sessions/runs?repo=all' "$UNMAPPED_ORG_SESSION_JWT"
unmapped_runs_code=$code
g7_ok=false
if [ "$unmapped_connections_code" = 200 ] && [ "$unmapped_runs_code" = 401 ]; then
  g7_ok=true
fi
gate 7 'unmapped org can discover claims but cannot read runs' "$g7_ok" \
  "connections:$unmapped_connections_code,runs:$unmapped_runs_code"

# Gate 8: this executable inventory is paired with the AST inventory test.
OPERATOR_ROUTES=(
  'POST|/v1/score/read|{"pr":{"number":1,"title":"session-isolation-proof","author":"proof"},"diff":""}'
  'GET|/v1/runs|'
  'GET|/v1/runs/1|'
  'GET|/v1/health|'
  'GET|/v1/jobs|'
  'GET|/v1/patterns|'
)
g8_ok=true
g8_status=""
for operator_route in "${OPERATOR_ROUTES[@]}"; do
  IFS='|' read -r operator_method operator_path operator_body <<<"$operator_route"
  req "$operator_method" "$operator_path" "$A_SESSION_JWT" "$operator_body"
  g8_status="${g8_status:+$g8_status,}${operator_method}:${operator_path}:$code"
  if [ "$code" != 401 ] && [ "$code" != 404 ]; then
    g8_ok=false
  fi
done
gate 8 'session bearer is refused by every operator-only route' "$g8_ok" "$g8_status"

# Gate 9: visibility is not installer authority and a refusal changes nothing.
req GET '/v1/sessions/connections' "$READ_ONLY_SESSION_JWT"
readonly_before_code=$code
readonly_before_ok=false
if [ "$code" = 200 ] && connection_is_setup_required "$READ_ONLY_INSTALLATION_ID"; then
  readonly_before_ok=true
fi
req POST '/v1/installations/bind' "$READ_ONLY_SESSION_JWT" \
  "{\"installation_id\":$READ_ONLY_INSTALLATION_ID}"
readonly_bind_code=$code
req GET '/v1/sessions/connections' "$READ_ONLY_SESSION_JWT"
readonly_after_code=$code
readonly_after_ok=false
if [ "$code" = 200 ] && connection_is_setup_required "$READ_ONLY_INSTALLATION_ID"; then
  readonly_after_ok=true
fi
g9_ok=false
if [ "$readonly_before_ok" = true ] \
  && [ "$readonly_bind_code" = 404 ] \
  && [ "$readonly_after_ok" = true ]
then
  g9_ok=true
fi
gate 9 'read-only discovery cannot bind or mutate installation state' "$g9_ok" \
  "before:$readonly_before_code,bind:$readonly_bind_code,after:$readonly_after_code"

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
if [ "$FAIL" -eq 0 ]; then
  printf 'EXIT GATE: PROVEN\n'
  exit 0
fi
printf 'EXIT GATE: NOT PROVEN\n'
exit 1
