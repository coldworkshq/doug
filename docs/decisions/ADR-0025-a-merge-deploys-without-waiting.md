---
title: A merge deploys without waiting for approval
status: accepted
date: 2026-08-28
amends: ADR-0021
---

## Context

ADR-0021 put both deploy jobs in a `production` GitHub environment whose one
protection rule is a required reviewer. It was live from 2026-08-26 21:46 UTC
to 2026-08-28. Six deploy runs entered the gate in that window, and the
measured result was worse than the hole it closed:

| run | commit | outcome |
|---|---|---|
| 33019286537 | the approval commit itself | cancelled, 1h07m in |
| 33037516367 | docs-only | 11s — both deploy jobs filtered out, never gated |
| 33038580214 | org move | approved after **17h00m** |
| 33042841775 | #229 | **cancelled, 13h29m in, never deployed** |
| 33106436217 | #233 | approved after **8h56m** |
| 33139859993 | #242 | approved after 12m, in the same sweep |

Two failures, not one:

1. **Waiting deploys are silently cancelled.** Run 33042841775 was cancelled
   at 19:01:53, one second after the next merge's run was created at 19:01:52.
   `concurrency.cancel-in-progress: false` protects a run that is already
   running; a run sitting in `waiting` for approval holds the group's *pending*
   slot instead, and GitHub evicts a pending run when a newer one arrives. So
   #229's deploy was destroyed by the next merge, and its changes reached
   production only 8h later, carried by someone else's approved run. Nothing
   went red. The cancellation looks identical to a deliberate one.

2. **The drift the gate creates is the drift ADR-0009 exists to prevent.**
   ADR-0009 was written after production was deployed from an unmerged branch,
   so `main` and the running revision disagreed about which features existed.
   Under the gate, `main` and the running revision disagreed for most of two
   consecutive days — by hours at a time, across three merges, with no signal
   anywhere that they had.

The gate's premise was that a human between the merge and the rollout is worth
that cost. In a solo repository the human between them is the same person who
wrote the change and merged the pull request, approving their own run minutes
or hours later with no new information. The review already happened at the PR.

## Decision

Neither deploy job names a GitHub environment, and the `production` environment
is deleted rather than stripped of its rule. A merge to main deploys, as
ADR-0009 says it does.

ADR-0021's other half stands unchanged: the federation provider's attribute
condition still pins both the repository and `refs/heads/main`, so only a run
on main can exchange its token for the deployer credential. That pin is now the
only boundary between a branch and production, and `api/deploy/setup-cicd.sh`
is untouched by this record.

## Rejected

**Keeping the environment and deleting only the reviewer rule.** Same running
behaviour, and `deploy.yml` would still say `environment: production` — a
one-click settings change could re-gate the pipeline with no diff for anyone to
review, which is how the gate's cost stayed invisible for two days in the first
place. Deleting the environment means re-gating requires editing the workflow.

**Keeping the gate and fixing the eviction** (a per-SHA concurrency group, so a
waiting run is not displaced). Closes the silent cancellation and nothing else:
the hours of main-versus-production drift are the gate working as designed, not
a bug in it. It also turns a backlog of merges into a backlog of approvals.

**A wait timer, or auto-approval after N minutes.** ADR-0021 already rejected
this and was right — a delay is not a review. It is rejected again from the
other side: it is also not automation, just a slower version of the same drift.

**Reverting the ref pin along with the reviewer gate.** The pin costs nothing
per deploy and closes a real path: without it, a workflow added on any branch
mints the deployer credential without review. Unrelated to deploy latency.

**A staging environment to promote through.** Rejected by ADR-0009 and again by
ADR-0021, unchanged: nothing to promote through with one developer.

## Consequences

- ADR-0009's contract is restored as written: merging deploys, and a bad merge
  reaches production in a couple of minutes. Rollback stays a `workflow_dispatch`
  on main or a Cloud Run traffic split — and the dispatch no longer costs an
  approval, though ADR-0021's ref pin still refuses a dispatch on a tag or any
  non-main branch.
- A direct push to main ships with no human having reviewed anything. This was
  the acknowledged gap in ADR-0009's posture, it is re-accepted here, and the
  deploy workflow's re-run of the full test suite remains the only thing
  standing in front of it. That re-run is therefore load-bearing, not redundant.
- The staged-rollout gate in `gcp.sh` is now the whole safety story for a bad
  build: a candidate revision takes no traffic until its tagged URL returns 200,
  and the previous revision keeps serving if it does not.
- Deleting the environment changes the OIDC token's `sub` claim back to its
  ref form. Nothing conditions on `sub` — verified live against the deployer
  service account's bindings while settling #223 — so the token exchange is
  unaffected.
- ADR-0021 keeps `status: accepted`: its ref pin is in force and the reader
  must still see it. Its reviewer-gate half is marked amended in place.
- The trigger to revisit is ADR-0009's, unchanged: a second developer, or the
  first deploy-caused incident that breaks someone else's day.
