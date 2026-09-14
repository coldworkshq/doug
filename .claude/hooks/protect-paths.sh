#!/usr/bin/env bash
# PreToolUse on Write|Edit|MultiEdit|NotebookEdit. Refuses hand edits to files
# a command writes, and names the command. This stops the edit tools only; a
# shell redirect is caught later by CI (`uv sync --locked`, `npm ci`, and
# .github/scripts/check_ratchets.py).
set -euo pipefail

root="${CLAUDE_PROJECT_DIR:?}"
path=$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
[ -n "$path" ] || exit 0
case "$path" in /*) ;; *) path="$root/$path" ;; esac
case "$path" in "$root"/*) rel="${path#"$root"/}" ;; *) exit 0 ;; esac

decide() {
  jq -n --arg decision "$1" --arg reason "$2" '{hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: $decision,
    permissionDecisionReason: $reason}}'
  exit 0
}

case "$rel" in
  api/uv.lock)
    decide deny "api/uv.lock is resolved, not written: edit api/pyproject.toml, then run uv lock (or uv add) in api/." ;;
  package-lock.json)
    decide deny "package-lock.json is resolved, not written: run npm install at the repository root." ;;
  api/.basedpyright/baseline.json)
    decide deny "The type-error baseline is written by basedpyright, and it only shrinks: fix the error instead, then run make typecheck-baseline." ;;
esac
exit 0
