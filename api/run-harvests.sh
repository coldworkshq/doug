#!/bin/bash
# Detached harvest queue. Runs grafana replication, then deepens the sentry
# TRAIN side, sequentially so they never contend for the 5000/hr rate limit.
#
# Each job is supervised: harvests span many hours and a single transient DNS
# or connection blip used to kill the whole run (it did, at 2577/12000 on
# 2026-07-28). githubkit's retry chain covers rate limits and 5xx responses,
# not transport errors, and one failed task takes down the whole asyncio
# gather. Every job is checkpointed to a partial JSONL, so a restart resumes
# rather than re-spending quota — which makes "just run it again" the correct
# and cheapest recovery.
# TO STOP THIS: pkill -f run-harvests.sh AND pkill -f doug-backtest.
# Killing the wrapper alone leaves the harvest child running — and a previous
# version of this script used `exec`, which renamed the process so pkill on
# the script name matched nothing at all. The orphan then competed with the
# next job for the same 5000/hr quota and drove both into 403s. Two jobs
# appending to one checkpoint can also interleave mid-line and corrupt it.
cd "$(dirname "$0")"
export GITHUB_TOKEN="$(gh auth token)"

MAX_ATTEMPTS=40

run() {
  local name="$1"; shift
  for attempt in $(seq 1 $MAX_ATTEMPTS); do
    echo "=== $name attempt $attempt/$MAX_ATTEMPTS at $(date) ==="
    if uv run doug-backtest "$@"; then
      echo "=== $name COMPLETE at $(date) ==="
      return 0
    fi
    echo "=== $name failed (exit $?); resuming from checkpoint in 60s ==="
    sleep 60
  done
  echo "=== $name GAVE UP after $MAX_ATTEMPTS attempts ==="
  return 1
}

# Replication repo. Labels are ~7x thinner here than sentry (~2.7 defects/mo),
# hence 12000 PRs to reach n≈30.
run grafana grafana/grafana \
  --limit 12000 --before 2026-06-15 --labels git --backfill-details \
  --output backtest-grafana-grafana-12000.json

# --before 2026-03-20 is load-bearing: the existing 5000 sample starts there,
# so this is strictly OLDER data. It grows the training window and leaves the
# newer-2500 holdout untouched by construction.
run sentry-older getsentry/sentry \
  --limit 10000 --before 2026-03-20 --labels git \
  --output backtest-getsentry-sentry-older10k.json

echo "=== ALL HARVESTS DONE $(date) ==="
