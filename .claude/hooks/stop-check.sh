#!/usr/bin/env bash
# Stop. While api/ Python, its config, its lock or its type baseline differs
# from HEAD, the agent does not finish on a red `make check`. It blocks once: a
# stop that already follows a block (stop_hook_active) passes, so a red tree
# the agent cannot fix gets reported instead of looped on.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:?}"
[ "$(jq -r '.stop_hook_active // false')" = "true" ] && exit 0

cd "$root"
git status --porcelain --untracked-files=all -- \
  'api/*.py' api/pyproject.toml api/uv.lock api/.basedpyright/baseline.json | grep -q . || exit 0

out=$(make -s check 2>&1) && exit 0
jq -n --arg tail "$(tail -n 30 <<<"$out")" \
  '{decision: "block", reason: ("make check is red. Fix it, or say why it stays red:\n" + $tail)}'
