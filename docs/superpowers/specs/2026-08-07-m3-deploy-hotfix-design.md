# M3 deploy hotfix design

## Problem

PR #64 promoted `doug-api` successfully, then failed before creating
`doug-adjudicator`. `gcloud run jobs deploy` parsed the separately quoted
`--args "-m,doug.outcome_worker"` value as another option because it begins
with `-`; the supported unambiguous form is
`--args=-m,doug.outcome_worker`.

The first production `adjudicator-setup` run exposed a second rollout defect:
service-account creation succeeded, but the immediately following `describe`
briefly returned not found. The account became visible seconds later. A single
visibility check turns normal IAM propagation into a false setup failure.

## Decision

Ship one narrow hotfix PR from the merged `main` branch.

1. Pass the Job entrypoint arguments with the equals-sign form so a leading
   hyphen remains the value of `--args`.
2. Add a bounded service-account visibility helper and use it for the two M3
   identities. Retry read-only `describe` calls only; never retry account
   creation or IAM mutations.
3. Strengthen the executable fake-`gcloud` tests so they reject the exact
   separated leading-hyphen argument that production rejected and simulate a
   newly created Scheduler identity becoming visible after one failed read.

The helper will make ten visibility checks with a one-second interval. A
permanently missing account still fails loudly after the bounded window.

## Rollout and success criteria

Merging the hotfix reruns the API deployment. The already-live API may receive
an equivalent new revision; after promotion, the workflow must create
`doug-adjudicator` from that exact immutable image and finish green.

Only after the Job exists and its image matches the serving API image may the
operator run `gcp.sh schedule`. The first manual execution and the two SQL
audits in `HANDOFF.md` remain required before marking the roadmap item live.

Success is:

- the deployment regression tests fail on merged #64 and pass with the fix;
- the focused and full API test suites pass;
- the hotfix PR CI passes;
- the post-merge deploy is green and the Job exists with the intended runtime
  account, image, limits, command, and arguments;
- no Scheduler mutation occurs before that verification.

## Non-goals

- No change to adjudication, queue, retry, or outcome semantics.
- No manual one-off Job deployment that would drift from repository state.
- No production schedule or manual execution as part of the code hotfix.
