---
title: Doug's CI surface is the job summary, never comments or checks
status: superseded
superseded_by: ADR-0010
date: 2026-07-29
---

## Context

Doug runs in other people's CI. The available surfaces are: fail the
job, post a check run, comment on the PR, or write to the job summary.
Each is progressively less intrusive and less visible.

Precision is not yet dogfood-proven. Per-pattern precision on the seed
corpus resolves to almost nothing once reweighted to real base rates —
one pattern clears the population base rate on sentry, none on grafana.

## Decision

Job summary only. Doug never comments on a PR, never posts a check run,
never fails a job. The workflow step carries `continue-on-error: true`,
and a missing credential (fork PRs get no secrets) skips cleanly with a
note rather than failing.

## Rejected

**PR comments.** A wrong comment is a notification to every subscriber
and it persists. At the precision we can currently demonstrate, that is
a tax on the team, not a service.

**Check runs.** They imply a pass/fail semantic Doug does not have and
does not want; "routes, never blocks" is the product.

## Consequences

- Lower visibility, and adoption depends on people opening the summary.
- A Doug outage is invisible to the repo, which is correct: an advisory
  reviewer must never redden someone else's pull request.
- Any future surface upgrade should be earned with a published precision
  number, not assumed.
