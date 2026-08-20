---
title: Doug's surface is a neutral check run posted by the App
status: accepted
date: 2026-07-31
supersedes: ADR-0003
---

## Context

ADR-0003 chose the job summary because Doug ran inside someone else's CI
job, and that job was the only surface it had. The GitHub App removes the
job. There is no workflow step, no `$GITHUB_STEP_SUMMARY` file, and no
runner — the review happens on Cloud Run in response to a webhook. The
job summary does not become less attractive under the App; it stops
existing.

The surfaces still reachable are the ones ADR-0003 already ranked: fail
the check, post a check run, comment on the PR. ADR-0003 rejected check
runs because they "imply a pass/fail semantic Doug does not have and does
not want". That objection is about the *conclusion* field, not about
check runs, and the conclusion field has a value for exactly this case:
`neutral`.

Nothing about confidence has improved since ADR-0003. Per-pattern
precision on the seed corpus still resolves to almost nothing once
reweighted to real base rates — one pattern clears the population base
rate on sentry, none on grafana — and the 2026-07-31 derangement check on
the deviation instrument returned FAIL, meaning that instrument is not
currently valid.

## Decision

The surface is one check run named `Doug`, posted against the pull
request's head SHA by the installation, and its conclusion is always
`neutral`. No code path may pass any other value, and `check_run.post`
takes no conclusion argument for a caller to get wrong.

The title states the tier honestly. A verdict produced by the
deterministic fallback says so in the title, not in a footnote further
down the summary. `review.score_one` falls back silently when a reader
call fails, and a fallback verdict rendered as though a model had read
the diff is the one misrepresentation this surface could make on its own.

Deviations render in their own section below the risk verdict, carry the
label `unvalidated`, and never touch `verdicts.score`, `band`, or `raw`
(ADR-0007).

A failure to post is swallowed and logged to stderr. The check run is the
output of a review, not a step in one.

## Rejected

**Keeping the job summary by keeping the workflow alongside the App.**
Two ingest paths, two auth models, two places a verdict can come from,
and a shared token in every adopting repo's settings — which is the thing
the App exists to remove.

**A `success` or `failure` conclusion, however generously thresholded.**
This is what ADR-0003 actually rejected and it stays rejected. A red
Doug check becomes a merge gate when an admin requires it, and even when
it is not required it falsely signals failure. Doug's precision does not
support either outcome.

**PR comments.** Unchanged from ADR-0003: a wrong comment notifies every
subscriber and it persists. Amended by ADR-0014: one sticky, App-authored
comment that mirrors this check run, edited in place.

**Holding the surface until a precision number is published**, which is
what ADR-0003's consequences asked for. That condition was written about
surfaces that can block or notify, and it still binds those. A neutral
check run does neither. Applying the condition here would have meant
shipping the App with no surface at all, which is not a more conservative
outcome, only a less useful one.

## Consequences

- ADR-0003 is superseded and stops being fed to the reader. Left
  `accepted`, it would make Doug's own check-run code read as a deviation
  from Doug's own decisions.
- For every check run Doug posts, never-blocks becomes structural rather
  than procedural. It used to rest on `continue-on-error: true` in a YAML
  file the adopting repo owned and could edit; it now rests on a
  conclusion value GitHub accepts as a successful required-check state.
- An admin can still add the `Doug` check to a branch's required checks.
  A correctly sourced `neutral` result on the latest head satisfies it,
  but requiring Doug also makes its presence, freshness, and configured
  App source merge dependencies. A missing result or one from the wrong
  expected App does not satisfy the rule.
- Visibility rises: the check appears in the PR's check list without
  anyone opening a summary. Wrong findings get seen more often too. That
  is the cost of the upgrade, and it is why the tier in the title and the
  `unvalidated` label on deviations are load-bearing rather than
  decoration.
- With Doug left advisory, an outage stays invisible to the repo: no check
  run posted is no signal, not a red one. If an admin makes Doug required,
  the same outage can leave the pull request waiting; that configuration
  turns Doug's availability into a gate despite the advisory conclusion.
