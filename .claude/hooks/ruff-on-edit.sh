#!/usr/bin/env bash
# PostToolUse on Write|Edit|MultiEdit. Formats the touched Python file under
# api/, applies safe fixes, and hands what remains back to the agent (exit 2).
# Three fixes stay manual. F401 and F841: an import added one edit before its
# first use would be deleted in between. RUF100: a noqa can read as unused only
# because the debt table covers the same rule, and deleting it loses the reason.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:?}"
path=$(jq -r '.tool_input.file_path // empty')
case "$path" in "$root"/api/*.py) ;; *) exit 0 ;; esac
[ -f "$path" ] || exit 0

ruff="$root/api/.venv/bin/ruff"
if [ ! -x "$ruff" ]; then
  echo '{"systemMessage": "ruff hook skipped: no api/.venv (run uv sync in api/)"}'
  exit 0
fi

cd "$root/api"
"$ruff" format --force-exclude --quiet "$path"
out=$("$ruff" check --force-exclude --fix --unfixable F401,F841,RUF100 \
  --output-format concise --quiet "$path" 2>&1)
[ -z "$out" ] && exit 0
{
  echo "ruff, ${path#"$root"/}:"
  head -n 20 <<<"$out"
} >&2
exit 2
