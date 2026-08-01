---
title: Deviation findings never move the risk score
status: accepted
date: 2026-07-30
---

## Context

Given a PR's diff and the recorded decisions bearing on it, the reader
can report deviations — things the record asks for that the change does
not do, changes the record does not sanction, and places where the
change contradicts it. Experiment B v2 validated the capability on
tickets: HIGH-severity deviations fired on 4% of matched PRs against
100% of mismatched ones, with intent-alignment 80 versus 2.

The tempting next step is to let a deviation raise the risk score.

## Decision

Deviation findings and `intent_alignment` are written to their own
`deviations` table and never contribute to `risk_score` or `band`. They
render as a separate advisory section of the check run (ADR-0010), each
line carrying the decision reference so the claim can be checked against
the record.

The feature ships on from the first merge. There is no staged rollout,
because Doug never blocks and every verdict it emits is already
advisory — a deviation on a neutral check run cannot hurt anyone.

## Rejected

**Letting deviation raise the score.** Deviation has no outcome-precision
evaluation. Folding it in would silently change what every score in the
ledger means and would invalidate the AUC evidence the reader is trusted
on — the two numbers would no longer measure the same thing across time.

**Gating the feature behind the integrity experiment.** The experiment
decides whether to *believe* deviations, not whether to show them. If
the arms come out identical the feature is theater, and that is worth
knowing whether or not it is live.

## Consequences

- Two streams to reason about, and a reader of the check run has to
  understand that one of them does not affect routing.
- Whether deviation ever earns its way into routing is a later decision
  needing outcome-joined evidence that does not exist yet.
- A failed intent read must be recorded distinctly from "no deviations
  found", or the eventual precision numbers will be wrong.
