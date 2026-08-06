---
title: Freeze the reader's prompt and schema to the validated probe
status: superseded
date: 2026-07-29
superseded_by: ADR-0012
---

## Context

The LLM diff-reader's standing rests on a pre-registered experiment: AUC
0.687 on sentry and 0.668 on grafana, against best-deterministic
baselines of 0.591 and 0.518, with the ReDef polarity counterfactual
passing on both repos. That evidence attaches to a specific prompt,
schema, model, effort setting and diff budget — not to "the reader" as
an idea.

A prompt is trivially editable and looks like configuration. It is not.

## Decision

`SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT`, `MAX_TOKENS` and `DIFF_BUDGET`
live in `doug/reader.py`, byte-identical to `scripts/llm_probe.py` as of
commit 0064e6b, and are pinned by test. Changing any of them is a new
experiment that needs its own pre-registration and its own run — not a
tweak, and not a refactor.

## Rejected

**Treating the prompt as tunable configuration.** It would let anyone
silently invalidate the only cross-repo evidence the product has, with a
one-line edit that reviews as a copy change.

**Re-validating after the fact.** Post-hoc bar edits are how a failed
experiment becomes a passed one. The v1 intent probe's FAIL is recorded
as a FAIL for this reason, with a v2 replication run separately.

## Consequences

- Prompt improvements are gated behind experiment cost. That is the
  intended friction.
- Anything that adds input to the model — intent documents, for example —
  must occupy a *separate* frozen prompt rather than editing this one.
