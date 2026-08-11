#!/usr/bin/env bash
set -euo pipefail

if (( $# != 1 )); then
  echo "usage: smoke-auth-entry.sh BASE_URL" >&2
  exit 64
fi

base_url="${1%/}"

encode_callback() {
  node -e 'process.stdout.write(encodeURIComponent(process.argv[1]))' \
    "$1/auth/callback"
}

is_expected_workos_redirect() {
  local location="$1"
  local expected_callback="$2"
  [[ "$location" == https://api.workos.com/user_management/authorize\?* ]] \
    && [[ "$location" == *"?redirect_uri=$expected_callback"* \
      || "$location" == *"&redirect_uri=$expected_callback"* ]]
}

safe_canonical_origin() {
  local location="$1"
  local expected_path="$2"
  printf '%s' "$location" | node -e '
    const fs = require("node:fs");
    const expectedPath = process.argv[1];
    try {
      const target = new URL(fs.readFileSync(0, "utf8"));
      const loopback = target.hostname === "localhost"
        || target.hostname === "127.0.0.1"
        || target.hostname === "[::1]";
      const allowedProtocol = target.protocol === "https:"
        || (target.protocol === "http:" && loopback);
      if (!allowedProtocol
          || target.username
          || target.password
          || target.pathname !== expectedPath
          || target.search
          || target.hash) process.exit(1);
      process.stdout.write(target.origin);
    } catch {
      process.exit(1);
    }
  ' "$expected_path"
}

request_redirect() {
  curl --silent --show-error --output /dev/null \
    --header 'Accept: text/html' \
    --write-out $'%{http_code}\n%{redirect_url}' --max-time 30 "$1"
}

root_code=$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --max-time 30 "$base_url/")
echo "$base_url/ -> $root_code"
[[ "$root_code" == "200" ]]

canonical_base="$base_url"
expected_callback=$(encode_callback "$canonical_base")
sign_in_result=$(request_redirect "$base_url/sign-in")
sign_in_code="${sign_in_result%%$'\n'*}"
sign_in_location="${sign_in_result#*$'\n'}"
canonical_hop=0

if ! is_expected_workos_redirect "$sign_in_location" "$expected_callback"; then
  [[ "$sign_in_code" == "307" ]]
  canonical_base=$(safe_canonical_origin "$sign_in_location" "/sign-in")
  [[ "$canonical_base" != "$base_url" ]]
  expected_callback=$(encode_callback "$canonical_base")
  sign_in_result=$(request_redirect "$canonical_base/sign-in")
  sign_in_code="${sign_in_result%%$'\n'*}"
  sign_in_location="${sign_in_result#*$'\n'}"
  canonical_hop=1
fi

[[ "$sign_in_code" == "307" ]]
is_expected_workos_redirect "$sign_in_location" "$expected_callback"
if (( canonical_hop == 1 )); then
  echo "$base_url/sign-in -> 307 canonical -> 307 -> WorkOS AuthKit"
else
  echo "$base_url/sign-in -> 307 -> WorkOS AuthKit"
fi

dashboard_result=$(request_redirect "$base_url/dashboard")
dashboard_code="${dashboard_result%%$'\n'*}"
dashboard_location="${dashboard_result#*$'\n'}"
if (( canonical_hop == 1 )); then
  [[ "$dashboard_code" == "307" ]]
  [[ "$dashboard_location" == "$canonical_base/dashboard" ]]
  dashboard_result=$(request_redirect "$canonical_base/dashboard")
  dashboard_code="${dashboard_result%%$'\n'*}"
  dashboard_location="${dashboard_result#*$'\n'}"
fi

[[ "$dashboard_code" == "307" ]]
is_expected_workos_redirect "$dashboard_location" "$expected_callback"
if (( canonical_hop == 1 )); then
  echo "$base_url/dashboard -> 307 canonical -> 307 -> WorkOS AuthKit"
else
  echo "$base_url/dashboard -> 307 -> WorkOS AuthKit"
fi
