#!/usr/bin/env bash
# The alerting doug-prod0 must hold, as something a machine can check.
#
# WHY THIS FILE EXISTS (doug#121). From 2026-08-16 to 2026-08-18 the
# adjudicator was dead and every surface reported `adjudicated 0` — the
# designed honest empty state, pixel-for-pixel identical to the broken one.
# `doug-prod0` held zero alert policies and zero notification channels, and
# the outage was found by reading Cloud Run execution status by hand, three
# days late. Nothing in this repository said the project should hold any
# alerting at all, so nothing could notice that it did not.
#
# The policies were created by hand afterwards. Clicks are not a record: a
# rebuilt project, a deleted channel, or a policy quietly disabled puts the
# instrument straight back into silence, with no diff for anyone to review.
# This script is the record, and `verify` is the half that matters — it is
# the check that would have caught 2026-08-16 on day one.
#
#   PROJECT=doug-prod0 api/deploy/monitoring.sh verify   # read-only, the default
#   PROJECT=doug-prod0 api/deploy/monitoring.sh apply    # create what is MISSING
#
# `verify` mutates nothing and exits non-zero when any requirement is unmet,
# so it is safe for CI, for an agent, and for a curious afternoon.
#
# `apply` creates only what does not exist. It never modifies and never
# deletes: a policy someone deliberately retuned has to survive it, and a
# script that can silently overwrite a live alert is a worse hazard than the
# gap it closes. It also refuses to create the NOTIFICATION CHANNEL — an
# email channel needs a human to confirm the address, which is founder-only
# under R11 and cannot be automated honestly. docs/OPERATIONS.md carries
# that one command.
#
# Because it is create-only, a run that dies partway leaves the project
# closer to correct than it found it and RE-RUNNING IS THE RECOVERY — the
# second pass sees what the first created and asks only for the rest. That
# is also why the uptime-check branch below stops deliberately: the policy
# that follows has to name an id the check did not have a moment ago.
# `verify` after any `apply` is what says whether it finished.
#
# Requires python3, and gcloud authed with monitoring.viewer for `verify` or
# monitoring.editor for `apply`.
set -uo pipefail

PROJECT=${PROJECT:-doug-prod0}
REGION=${REGION:-us-central1}
ACTION=${1:-verify}

case "$ACTION" in
  verify|apply) ;;
  *) echo "usage: PROJECT=<id> $0 [verify|apply]" >&2; exit 2 ;;
esac

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 2; }
TOKEN=$(gcloud auth print-access-token 2>/dev/null) || {
  echo "gcloud auth print-access-token failed — run 'gcloud auth login'" >&2; exit 2; }

API="https://monitoring.googleapis.com/v3/projects/$PROJECT"

# `set -e` is deliberately absent — the audit's non-zero exit is the whole
# point, and -e would abort the script before anything could act on it. So
# each read is checked here instead. A refused or malformed API response must
# NOT fall through to a parser that sees no policies and reports them all
# missing: that is a wrong answer wearing the right answer's clothes, which
# is the failure mode this entire file exists to prevent.
fetch() {
  local body
  body=$(curl -sS -H "Authorization: Bearer $TOKEN" "$API/$1") || {
    echo "ERROR: could not reach $API/$1" >&2; return 3; }
  printf '%s' "$body" | python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    body = json.loads(raw)
except ValueError:
    print("ERROR: " + sys.argv[1] + " did not answer JSON: " + raw[:200], file=sys.stderr)
    sys.exit(3)
if isinstance(body, dict) and "error" in body:
    err = body["error"]
    print("ERROR: " + sys.argv[1] + " -> " + str(err.get("status", "")) + " "
          + err.get("message", "unknown"), file=sys.stderr)
    sys.exit(3)
print(raw)
' "$1"
}
post() {  # post <collection> <json>; prints the created resource name
  curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "$2" "$API/$1" | python3 -c '
import json, sys
body = json.load(sys.stdin)
if "error" in body:
    print("  FAILED: " + body["error"].get("message", "unknown"), file=sys.stderr)
    sys.exit(1)
print("  created " + body["name"])
'
}

MISSING_FILE=$(mktemp); trap 'rm -f "$MISSING_FILE"' EXIT

audit() {  # prints the human report; writes one missing key per line to $MISSING_FILE
  local policies channels uptimes
  # Each read on its own line, and each exit status checked: a `$(fetch ...)`
  # written inline below would have its failure swallowed by the surrounding
  # command's own status.
  policies=$(fetch alertPolicies) || return 3
  channels=$(fetch notificationChannels) || return 3
  uptimes=$(fetch uptimeCheckConfigs) || return 3
  MISSING_FILE="$MISSING_FILE" python3 - "$policies" "$channels" "$uptimes" <<'PY'
import json, os, sys

policies = json.loads(sys.argv[1]).get("alertPolicies", [])
channels = json.loads(sys.argv[2]).get("notificationChannels", [])
uptimes = json.loads(sys.argv[3]).get("uptimeCheckConfigs", [])

LIVENESS_PATH = "/healthz/queues"

# WHAT MUST EXIST. Each policy is identified by what it WATCHES, never by
# its display name: a renamed policy still pages, and a policy renamed to
# look right while watching nothing is the exact failure this file is about.
# Every string in `needs` must appear in some one condition's filter.
REQUIRED = [
    ("job-failed",
     "doug#121's own words: alert on doug-adjudicator failedCount >= 1. No "
     "service_name filter, deliberately — that is what also covers "
     "doug-outcome-reconciler, which is #121's third checkbox.",
     ['resource.type = "cloud_run_job"',
      "run.googleapis.com/job/completed_execution_count",
      'metric.labels.result = "failed"']),
    ("api-5xx",
     "doug-api is the single write path for the outcome ledger; a 5xx burst "
     "is a tenant-visible incident, and one of those pauses every lane on "
     "every track under R1.",
     ['resource.labels.service_name = "doug-api"',
      "run.googleapis.com/request_count",
      'metric.labels.response_code_class = "5xx"']),
    ("queue-liveness",
     "The contradiction itself, watched from OUTSIDE the process. A failed "
     "execution is not the only way to be dead: a Job that never STARTS "
     "emits no failure metric at all, so job-failed cannot see it. "
     "/healthz/queues can — it answers 503 on work sitting past the point "
     "where its drain provably did not run.",
     ["monitoring.googleapis.com/uptime_check/check_passed"]),
]

report, missing = [], []
def record(ok, key, label, detail):
    report.append(("PASS" if ok else "FAIL", label, detail))
    if not ok:
        missing.append(key)

# 1. A channel that reaches a human. Policies wired to nothing are the
#    2026-08-16 state with extra steps.
live = {c["name"]: c for c in channels if c.get("enabled", True)}
record(bool(live), "channel", "a notification channel reaches a human",
       ", ".join(f"{c.get('type')}:{c.get('displayName')}" for c in live.values())
       or "NONE — every policy below would fire into nothing")

# 2. The uptime check, resolved before the policy that has to name it.
check = next((u for u in uptimes
              if (u.get("httpCheck") or {}).get("path") == LIVENESS_PATH), None)
if check is None:
    record(False, "uptime-check", f"an uptime check polls {LIVENESS_PATH}",
           "without it the queue-liveness policy has nothing to watch")
    # And the policy CANNOT be satisfied either, so it is failed here rather
    # than matched on. Without this the remaining requirement is the bare
    # `uptime_check/check_passed` metric, which ANY uptime policy in the
    # project satisfies — caught 2026-08-29 running this against lema-prod0,
    # where "lema-web landing DOWN" reported the queue liveness alert as
    # present. A verifier that greens on the wrong alarm is the defect it
    # was written to catch, one level up.
    record(False, "queue-liveness", "policy queue-liveness",
           "no check on " + LIVENESS_PATH + " exists for a policy to watch")
else:
    check_id = check["name"].rsplit("/", 1)[-1]
    REQUIRED[2][2].append(f'metric.labels.check_id = "{check_id}"')
    host = (check.get("monitoredResource") or {}).get("labels", {}).get("host")
    record(True, "uptime-check", f"an uptime check polls {LIVENESS_PATH}",
           f"{check_id} -> {host}")

# 3. Each policy: present, enabled, and wired to a live channel. All three
#    are load-bearing — "exists" is the weakest of them and the easiest to
#    mistake for the whole answer.
for key, why, needs in REQUIRED:
    label = f"policy {key}"
    if key in missing:
        continue  # already failed above, and for a reason no filter can undo
    match = next((p for p in policies
                  if any(all(n in (c.get("conditionThreshold") or {}).get("filter", "")
                             for n in needs)
                         for c in p.get("conditions", []))), None)
    if match is None:
        record(False, key, label, why)
    elif not match.get("enabled", False):
        record(False, key, label,
               f"'{match['displayName']}' EXISTS BUT IS DISABLED — a muted alert is not an alert")
    elif not [c for c in match.get("notificationChannels", []) if c in live]:
        record(False, key, label,
               f"'{match['displayName']}' is enabled but reaches no live channel")
    else:
        record(True, key, label, match["displayName"])

width = max(len(label) for _, label, _ in report)
for status, label, detail in report:
    print(f"{status}  {label.ljust(width)}  {detail}")
print()

with open(os.environ["MISSING_FILE"], "w") as fh:
    fh.write("\n".join(missing))

if missing:
    print(f"{len(missing)} requirement(s) unmet in {os.environ.get('PROJECT', '?')}.")
    sys.exit(1)
print("Every required alert exists, is enabled, and reaches a human.")
PY
}

PROJECT="$PROJECT" audit
STATUS=$?
# 3 is "could not ask", which is neither pass nor fail and must never be
# mistaken for either. It stops here rather than reaching `apply`, which
# would otherwise create duplicates of policies it merely could not see.
[ $STATUS -eq 3 ] && { echo "could not audit $PROJECT — nothing was checked" >&2; exit 3; }
missing() { grep -qx "$1" "$MISSING_FILE"; }

if [ "$ACTION" = verify ] || [ $STATUS -eq 0 ]; then
  exit $STATUS
fi

# --- apply -------------------------------------------------------------------
# Reached only when the audit above found something absent. Each creator
# posts the shape production already runs, so what this writes and what
# doug-prod0 holds cannot drift apart unnoticed.

if missing channel; then
  echo "REFUSING: no notification channel exists." >&2
  echo "An email channel needs a human to confirm the address — founder-only under" >&2
  echo "R11, and docs/OPERATIONS.md has the one command. Creating policies first" >&2
  echo "would wire every alert to nothing, which is the outage with extra steps." >&2
  exit 1
fi
CHANNEL=$(fetch notificationChannels | python3 -c '
import json, sys
live = [c["name"] for c in json.load(sys.stdin).get("notificationChannels", [])
        if c.get("enabled", True)]
if not live:
    print("no enabled notification channel", file=sys.stderr); sys.exit(1)
print(live[0])') || exit 1

if missing uptime-check; then
  # The STABLE service URL, never a revision URL: a check pinned to a
  # revision stays green while the revision it names serves nobody.
  HOST=$(gcloud run services describe doug-api --project="$PROJECT" --region="$REGION" \
           --format='value(status.url)' 2>/dev/null | sed 's#^https://##')
  [ -n "$HOST" ] || { echo "cannot resolve the doug-api host — is it deployed?" >&2; exit 1; }
  echo "creating uptime check on https://$HOST/healthz/queues"
  post uptimeCheckConfigs "$(python3 -c '
import json, sys
print(json.dumps({
    "displayName": "doug-queue-liveness",
    "monitoredResource": {"type": "uptime_url",
                          "labels": {"project_id": sys.argv[1], "host": sys.argv[2]}},
    "httpCheck": {"useSsl": True, "path": "/healthz/queues", "port": 443,
                  "requestMethod": "GET"},
    "period": "300s", "timeout": "10s",
}))' "$PROJECT" "$HOST")" || exit 1
  echo
  echo "Re-run apply: the queue-liveness policy must name the id this check was"
  echo "just assigned, and that id did not exist a moment ago."
  exit 1
fi

policy() {  # policy <displayName> <conditionName> <conditionJSON> <documentation>
  post alertPolicies "$(python3 -c '
import json, sys
name, cond_name, cond, doc, channel = sys.argv[1:6]
print(json.dumps({
    "displayName": name, "combiner": "OR", "enabled": True,
    "conditions": [{"displayName": cond_name, "conditionThreshold": json.loads(cond)}],
    "documentation": {"content": doc, "mimeType": "text/markdown"},
    "notificationChannels": [channel],
}))' "$1" "$2" "$3" "$4" "$CHANNEL")"
}

if missing job-failed; then
  echo "creating policy: Cloud Run job failed execution"
  policy "Cloud Run job failed execution (adjudicator / outcome-reconciler)" \
    "job completed_execution_count result=failed >= 1" \
    '{"filter":"resource.type = \"cloud_run_job\" AND metric.type = \"run.googleapis.com/job/completed_execution_count\" AND metric.labels.result = \"failed\"","comparison":"COMPARISON_GT","thresholdValue":0,"duration":"0s","trigger":{"count":1},"aggregations":[{"alignmentPeriod":"300s","perSeriesAligner":"ALIGN_SUM","crossSeriesReducer":"REDUCE_SUM","groupByFields":["resource.labels.job_name"]}]}' \
    'doug#121: a Cloud Run job execution completed with result=failed. Covers doug-adjudicator and doug-outcome-reconciler, and any future Job in the project — the absent service_name filter is the point. The adjudicator was dead 2026-08-16 to 2026-08-18 with no signal at all; this is the failedCount>=1 alert that outage was missing.' || exit 1
fi

if missing api-5xx; then
  echo "creating policy: doug-api 5xx responses"
  policy "doug-api 5xx responses" \
    "doug-api request_count response_code_class=5xx > 0" \
    '{"filter":"resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"doug-api\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\"","comparison":"COMPARISON_GT","thresholdValue":0,"duration":"0s","trigger":{"count":1},"aggregations":[{"alignmentPeriod":"300s","perSeriesAligner":"ALIGN_SUM","crossSeriesReducer":"REDUCE_SUM"}]}' \
    'doug#121: doug-api served at least one 5xx in a 5-minute window. The service is the single write path for the outcome ledger, so a 5xx burst is a tenant-visible incident — which pauses every lane on every track under R1.' || exit 1
fi

if missing queue-liveness; then
  CHECK_ID=$(fetch uptimeCheckConfigs | python3 -c '
import json, sys
found = [u["name"].rsplit("/", 1)[-1]
         for u in json.load(sys.stdin).get("uptimeCheckConfigs", [])
         if (u.get("httpCheck") or {}).get("path") == "/healthz/queues"]
if not found:
    print("no uptime check on /healthz/queues to watch", file=sys.stderr); sys.exit(1)
print(found[0])') || exit 1
  echo "creating policy: queue liveness, watching $CHECK_ID"
  # COMPARISON_GT against thresholdValue 1 over REDUCE_COUNT_FALSE is GCP's
  # canonical uptime shape — "more than one checker reports failure" — and
  # NOT the nonsense it reads as out of context, given check_passed is a
  # boolean. Anyone "fixing" it to COMPARISON_LT silences the alert.
  policy "Queue liveness: per-lane oldest-pending-age contradiction (/healthz/queues)" \
    "uptime check on /healthz/queues failing" \
    "$(python3 -c '
import json, sys
print(json.dumps({
    "filter": ("metric.type = \"monitoring.googleapis.com/uptime_check/check_passed\" AND "
               "metric.labels.check_id = \"%s\" AND resource.type = \"uptime_url\"" % sys.argv[1]),
    "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "600s",
    "trigger": {"count": 1},
    "aggregations": [{"alignmentPeriod": "1200s", "perSeriesAligner": "ALIGN_NEXT_OLDER",
                      "crossSeriesReducer": "REDUCE_COUNT_FALSE",
                      "groupByFields": ["resource.label.project_id", "resource.label.host"]}],
}))' "$CHECK_ID")" \
    'doug#121, doug#260. The uptime check polls /healthz/queues, which answers 503 when either lane holds work past the point where its drain provably did not run (review: fresh-pending past the bar; outcome: overdue past the daily cadence plus slack), and when the ledger cannot answer at all. A failing check is therefore the queue contradiction OR total API death — the same alarm on purpose. The bars are served by the route itself, so they are never duplicated here.' || exit 1
fi

echo
echo "Re-run verify to confirm."
