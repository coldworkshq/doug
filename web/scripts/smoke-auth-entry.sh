#!/usr/bin/env bash
set -euo pipefail

if (( $# != 1 )); then
  echo "usage: smoke-auth-entry.sh BASE_URL" >&2
  exit 64
fi

base_url="${1%/}"
expected_callback=$(node -e \
  'process.stdout.write(encodeURIComponent(process.argv[1]))' \
  "$base_url/auth/callback")

is_expected_workos_redirect() {
  local location="$1"
  [[ "$location" == https://api.workos.com/user_management/authorize\?* ]] \
    && [[ "$location" == *"?redirect_uri=$expected_callback"* \
      || "$location" == *"&redirect_uri=$expected_callback"* ]]
}

root_code=$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --max-time 30 "$base_url/")
echo "$base_url/ -> $root_code"
[[ "$root_code" == "200" ]]

dashboard_result=$(curl --silent --show-error --output /dev/null \
  --header 'Accept: text/html' \
  --write-out $'%{http_code}\n%{redirect_url}' --max-time 30 \
  "$base_url/dashboard")
dashboard_code="${dashboard_result%%$'\n'*}"
dashboard_location="${dashboard_result#*$'\n'}"
echo "$base_url/dashboard -> $dashboard_code -> WorkOS AuthKit"
[[ "$dashboard_code" == "307" ]]
is_expected_workos_redirect "$dashboard_location"

sign_in_result=$(curl --silent --show-error --output /dev/null \
  --header 'Accept: text/html' \
  --write-out $'%{http_code}\n%{redirect_url}' --max-time 30 \
  "$base_url/sign-in")
sign_in_code="${sign_in_result%%$'\n'*}"
sign_in_location="${sign_in_result#*$'\n'}"
echo "$base_url/sign-in -> $sign_in_code -> WorkOS AuthKit"
[[ "$sign_in_code" == "307" ]]
is_expected_workos_redirect "$sign_in_location"
