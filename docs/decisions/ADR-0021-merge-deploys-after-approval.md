---
title: A merge deploys only after Andrew approves the run
status: accepted
date: 2026-08-26
amends: ADR-0009
---

## Context

Two production holes, both verified live on 2026-08-24 and both approved for
closure on 2026-08-25:

1. The deploy workflow declared no environment, so any merge to main deployed
   both Cloud Run services to production with nobody between the merge and the
   rollout. ADR-0009 priced that as "a bad merge reaches production in a couple
   of minutes" back when every merge was a human's own reviewed pull request; a
   direct push to main was already the acknowledged gap in that posture.
2. The Workload Identity Federation provider's attribute condition pinned only
   the repository, not the ref. Any branch of this repository — not only main —
   could exchange its runner token for the deployer credential. The deploy
   workflow on main was therefore not the only path to production: a workflow
   added on any branch could mint the same credential without ever entering
   review.

## Decision

Both deploy jobs run in a GitHub environment named `production` whose one
protection rule is a required reviewer: Andrew. A merge to main still triggers
the workflow and still re-runs the tests, but each deploy job holds until
Andrew approves the run. The manual-dispatch rollback path goes through the
same approval. Self-review is deliberately allowed — the gate exists to put a
human between a merge and production, not to require a second human this solo
repository does not have.

The federation provider's attribute condition now also pins the ref: only a
run on main can exchange its token for the deployer credential. The condition
evaluates CEL over the raw assertion, so no attribute-mapping change was
needed, and the environment's change to the token's subject claim is inert
because nothing conditions on the subject.

## Rejected

**Pinning the ref without the reviewer gate.** Closes the stolen-credential
path but keeps every merge deploying unreviewed at the instant it lands, and a
direct push to main would still ship with no human having seen anything.

**The reviewer gate without the ref pin.** The approval lives in GitHub's
workflow layer; the credential is minted by GCP from the raw token. A workflow
on any branch that never names the environment would still get the deployer
credential. The boundary has to hold at the token exchange, not only in the
workflow that is supposed to use it.

**A deployment branch policy on the environment instead of the ref pin.** That
restricts which branches may reference the environment, which again governs
only workflows that ask for it. Same failure as above: GCP, not GitHub, has to
refuse the exchange.

**A wait timer instead of a reviewer.** A delay is not a review; it turns "a
bad merge reaches production in minutes" into "in more minutes".

**A staging environment.** Rejected by ADR-0009 and unchanged: nothing to
promote through with one developer.

## Consequences

- ADR-0009's "merging deploys" contract becomes "merging deploys after Andrew
  approves the run". An unapproved run waits; GitHub fails it after 30 days,
  and re-running it re-requests approval.
- One approval releases every job of that run which names the environment, so
  a both-services deploy is one click, not two.
- Rollback by manual dispatch now also costs one approval. Accepted: the
  person dispatching a rollback is the approver.
- The filter job stays outside the environment on purpose. It only computes
  which services changed, holds no credential, and gating it would make every
  run — including ones that deploy nothing — demand an approval.
- The setup script's condition, its printed verify command, and the applied
  provider must keep saying the same thing: repository and ref, both pinned.
