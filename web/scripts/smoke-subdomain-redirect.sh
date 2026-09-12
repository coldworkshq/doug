#!/usr/bin/env bash
# The subdomain redirects to the apex, path-preserving (ADR-0034 decision 1;
# `redirects()` in web/next.config.ts). That rule is keyed on the Host header
# the container receives, so this is the live assertion that the front of the
# service hands it the mapped domain: one public path with a query on the
# subdomain must answer 308 to the same path and query on the apex. Anything
# else, a 200 (the redirect never fired), a 307 (the proxy's canonicalization
# answered instead), or a Location on another host, fails.
set -euo pipefail

if (( $# != 2 )); then
  echo "usage: smoke-subdomain-redirect.sh SUBDOMAIN_URL APEX_URL" >&2
  exit 64
fi

subdomain="${1%/}"
apex="${2%/}"
probe="/scoreboard?smoke=subdomain"

result=$(curl --silent --show-error --output /dev/null \
  --write-out $'%{http_code}\n%{redirect_url}' --max-time 30 "$subdomain$probe")
code="${result%%$'\n'*}"
location="${result#*$'\n'}"

echo "$subdomain$probe -> $code"
if [[ "$code" != "308" ]]; then
  echo "expected 308 from the subdomain; the redirect in web/next.config.ts did not answer" >&2
  exit 1
fi
if [[ "$location" != "$apex$probe" ]]; then
  echo "expected the same path and query on $apex; the redirect went elsewhere" >&2
  exit 1
fi
echo "  -> 308 -> $apex$probe"
