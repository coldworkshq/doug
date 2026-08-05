#!/usr/bin/env bash
# The ROADMAP § MT exit gate, executable: "a second installation on a
# different account reads only its own rows — proven against the real
# ledger, not fixtures."
#
# Run it against prod after: PR #50 deployed, pepper provisioned, MT0
# webhooks redelivered (cold start prints zero "doug: DRIFT" lines), Doug
# installed on the second account, and at least one PR on the second
# account reviewed (the proof refuses to pass vacuously on an empty queue).
#
# Usage:
#   DOUG_URL=https://... GITHUB_PAT=ghp_... \
#   A_OWNER=drewjst A_REPO=drewjst/doug \
#   B_OWNER=<second account> B_REPO=<second-account>/<repo> \
#   [DOUG_API_TOKEN=...] api/deploy/prove-isolation.sh
#
# The PAT must administer both accounts (mint proof is org-admin / account
# owner). Keys minted here are labeled "isolation-proof" and revoked by the
# script's own final steps — revocation IS one of the assertions.

set -u

: "${DOUG_URL:?set DOUG_URL to the api base, no trailing slash}"
: "${GITHUB_PAT:?set GITHUB_PAT (admin on both accounts)}"
: "${A_OWNER:?set A_OWNER (first installed account, e.g. drewjst)}"
: "${A_REPO:?set A_REPO (full name under A, e.g. drewjst/doug)}"
: "${B_OWNER:?set B_OWNER (second installed account)}"
: "${B_REPO:?set B_REPO (full name under B)}"

command -v jq >/dev/null || { echo "jq is required" >&2; exit 2; }

PASS=0; FAIL=0
body=""; code=""

check() { # check <label> <ok-boolean>
  if [ "$2" = "true" ]; then
    PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"
  else
    FAIL=$((FAIL + 1)); printf 'FAIL  %s\n      body: %.300s\n' "$1" "$body"
  fi
}

req() { # req <method> <path> <token-header-value> [json-body]; sets code/body
  local method=$1 path=$2 token=$3 data=${4:-}
  local args=(-s -o /tmp/doug-proof-body -w '%{http_code}' -X "$method" "$DOUG_URL$path")
  [ -n "$token" ] && args+=(-H "x-doug-token: $token")
  [ -n "$data" ] && args+=(-H 'content-type: application/json' -d "$data")
  code=$(curl "${args[@]}")
  body=$(cat /tmp/doug-proof-body)
}

mint() { # mint <owner> -> token \t token_id  (empty on failure)
  local owner=$1
  code=$(curl -s -o /tmp/doug-proof-body -w '%{http_code}' \
    -X POST "$DOUG_URL/v1/installations/token" \
    -H "X-GitHub-Token: $GITHUB_PAT" -H 'content-type: application/json' \
    -d "{\"selection\": \"all\", \"owner\": \"$owner\", \"label\": \"isolation-proof\"}")
  body=$(cat /tmp/doug-proof-body)
  [ "$code" = "200" ] && jq -r '[.token, (.token_id | tostring)] | join("\t")' /tmp/doug-proof-body
}

echo "== mint one 'all' key per account (proof: account owner / org admin) =="
A_MINT=$(mint "$A_OWNER"); check "mint for $A_OWNER returns a key" "$([ -n "$A_MINT" ] && echo true || echo false)"
B_MINT=$(mint "$B_OWNER"); check "mint for $B_OWNER returns a key" "$([ -n "$B_MINT" ] && echo true || echo false)"
[ -z "$A_MINT" ] || [ -z "$B_MINT" ] && { echo "cannot continue without both keys"; exit 1; }
A_KEY=${A_MINT%%$'\t'*}; A_ID=${A_MINT##*$'\t'}
B_KEY=${B_MINT%%$'\t'*}; B_ID=${B_MINT##*$'\t'}

echo "== each key sees only its own account's rows =="
req GET /v1/queue "$B_KEY"
check "B's queue answers 200" "$([ "$code" = 200 ] && echo true || echo false)"
b_total=$(jq '.items | length' /tmp/doug-proof-body)
b_foreign=$(jq --arg o "$A_OWNER" \
  '[.items[].pr.repo | ascii_downcase | select(startswith(($o | ascii_downcase) + "/"))] | length' \
  /tmp/doug-proof-body)
check "B's queue is non-empty (a vacuous pass proves nothing — review a PR on $B_REPO first)" \
  "$([ "$b_total" -gt 0 ] && echo true || echo false)"
check "B's queue carries zero rows from $A_OWNER/*" "$([ "$b_foreign" = 0 ] && echo true || echo false)"

req GET /v1/queue "$A_KEY"
a_foreign=$(jq --arg o "$B_OWNER" \
  '[.items[].pr.repo | ascii_downcase | select(startswith(($o | ascii_downcase) + "/"))] | length' \
  /tmp/doug-proof-body)
check "A's queue carries zero rows from $B_OWNER/*" "$([ "$a_foreign" = 0 ] && echo true || echo false)"

echo "== ?repo= is a filter within scope, never a selector across it =="
req GET "/v1/queue?repo=$A_REPO" "$B_KEY"
check "B's key asking for A's repo gets 404, not an empty 200" "$([ "$code" = 404 ] && echo true || echo false)"
req GET "/v1/queue?repo=$B_REPO" "$A_KEY"
check "A's key asking for B's repo gets 404" "$([ "$code" = 404 ] && echo true || echo false)"
req GET "/v1/queue?repo=$B_REPO" "$B_KEY"
check "B's key asking for B's own repo gets 200" "$([ "$code" = 200 ] && echo true || echo false)"

echo "== management surfaces are tenant-scoped too =="
code=$(curl -s -o /tmp/doug-proof-body -w '%{http_code}' \
  "$DOUG_URL/v1/installations/tokens?owner=$B_OWNER" -H "X-GitHub-Token: $GITHUB_PAT")
body=$(cat /tmp/doug-proof-body)
b_inst=$(jq --argjson id "$B_ID" '[.tokens[] | select(.id == $id)] | first | .installation_id' /tmp/doug-proof-body)
list_cross=$(jq --argjson inst "${b_inst:-0}" '[.tokens[] | select(.installation_id != $inst)] | length' /tmp/doug-proof-body)
check "B's key list contains only B's installation" "$([ "$list_cross" = 0 ] && echo true || echo false)"

code=$(curl -s -o /tmp/doug-proof-body -w '%{http_code}' -X DELETE \
  "$DOUG_URL/v1/installations/token/$B_ID?owner=$A_OWNER" -H "X-GitHub-Token: $GITHUB_PAT")
body=$(cat /tmp/doug-proof-body)
check "A-owner proof cannot revoke B's key (404)" "$([ "$code" = 404 ] && echo true || echo false)"
req GET /v1/queue "$B_KEY"
check "B's key still works after the cross-tenant revoke attempt" "$([ "$code" = 200 ] && echo true || echo false)"

echo "== revocation works, next request, for the right owner =="
code=$(curl -s -o /tmp/doug-proof-body -w '%{http_code}' -X DELETE \
  "$DOUG_URL/v1/installations/token/$B_ID?owner=$B_OWNER" -H "X-GitHub-Token: $GITHUB_PAT")
check "B-owner proof revokes B's key" "$([ "$code" = 200 ] && echo true || echo false)"
req GET /v1/queue "$B_KEY"
check "B's revoked key is dead on the very next request" "$([ "$code" = 401 ] && echo true || echo false)"
code=$(curl -s -o /tmp/doug-proof-body -w '%{http_code}' -X DELETE \
  "$DOUG_URL/v1/installations/token/$A_ID?owner=$A_OWNER" -H "X-GitHub-Token: $GITHUB_PAT")
check "cleanup: A's proof key revoked too" "$([ "$code" = 200 ] && echo true || echo false)"

if [ -n "${DOUG_API_TOKEN:-}" ]; then
  echo "== operator sanity: the unscoped view still sees both =="
  req GET /v1/queue "$DOUG_API_TOKEN"
  op_sees_both=$(jq --arg a "$A_OWNER" --arg b "$B_OWNER" \
    '[.items[].pr.repo | ascii_downcase] as $r
     | (($r | map(select(startswith(($a | ascii_downcase) + "/"))) | length) > 0)
       and (($r | map(select(startswith(($b | ascii_downcase) + "/"))) | length) > 0)' \
    /tmp/doug-proof-body)
  check "operator queue sees rows from both accounts" "$op_sees_both"
fi

echo
echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" = 0 ] && echo "EXIT GATE: PROVEN — a second installation reads only its own rows." \
                || echo "EXIT GATE: NOT PROVEN — do not open App visibility."
rm -f /tmp/doug-proof-body
exit "$([ "$FAIL" = 0 ] && echo 0 || echo 1)"
