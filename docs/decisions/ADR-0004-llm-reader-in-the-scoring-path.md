---
title: Put the LLM diff-reader in the scoring path
status: accepted
date: 2026-07-29
supersedes: thesis-v2 point 2 ("no model invocation in scoring")
---

## Context

Thesis v2 (2026-07-28) committed to deterministic scoring with no model
in the hot path, on an explicit cost-wedge argument: competitors' COGS
scale with PR volume because they run a model on every diff, so Doug's
differentiation was routing at fractions of a cent.

Phase 0 and the RandomForest baseline then proved that bet was
protecting a method that does not work. Three method families — shape
rules, rolling hotspots, and RF on Kamei's 14 metadata features — all
land at the same ~0.54-0.61 AUC ceiling on sentry, and on grafana every
one of them sits at or below random. Nothing transfers across repos.
Diff *content* was the last untested information source.

The Phase-1 entry probe was pre-registered with frozen bars before any
model call: AUC **0.687 sentry / 0.668 grafana** against best
deterministic 0.591 / 0.518, bootstrap 100% / 96%. It is the first
method to beat the size sort, and the first to survive a second repo at
all. The ReDef polarity counterfactual passed on both repos, so the
reader is responding to semantics rather than surface.

## Decision

The LLM diff-reader is the scoring path when enabled. Deterministic
scoring becomes the fallback tier, used when the reader is off or a read
fails, and the fallback says so in the verdict's reasons — a silent
downgrade would corrupt any calibration built on the output.

## Rejected

**Holding the cost wedge.** It was a bet on a method with a proven
ceiling and no cross-repo transfer. Cheap routing that does not rank is
not a wedge, it is a cheaper way to be wrong.

**Shipping the reader without pre-registration.** The bars were frozen
before the run, which is the only reason the result is worth anything.

## Consequences

- COGS now scale with PR volume. The economics claim on the public site
  ("no model in the hot path, ~$0.001/PR") is false and must be rewritten.
- The reader's prompt is load-bearing evidence — see ADR-0002.
- Deterministic scoring is not deleted; it is the degraded mode, and it
  keeps the open-source and no-credential paths alive.
