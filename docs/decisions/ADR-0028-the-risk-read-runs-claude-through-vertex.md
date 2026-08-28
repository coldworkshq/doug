---
title: The risk read runs Claude through Vertex, and clears a non-inferiority bar before it does
status: proposed
date: 2026-08-28
---

> **This record is INCOMPLETE ON PURPOSE and cannot be signed as it stands.**
>
> Section **The bar** has four blank numbers. They are founder-only under R11
> and they are a pre-registration: filling them in after a run is worth nothing,
> and filling them in by an agent's guess is worse, because it would look like a
> declared bar while being a fabricated one.
>
> Sign this record by writing those four numbers and flipping `status` in the
> same commit. Merging it at `proposed` is safe — `proposed` records do not
> reach Doug's reader — and changes nothing about what runs.
>
> Companion record: **ADR-0027** moves the *mechanical* tier's vendor boundary.
> This one moves the *risk and intent* reads' transport. They are separate on
> purpose: ADR-0027's tier is validated by code on every call, and this one's is
> not validated by anything downstream, which is the whole distinction ADR-0016
> drew and this record does not blur.

## Context

### What actually changes, and what does not

Claude Opus 5 through Vertex is the same weights reached over a different API
surface. Verified on this commit, in the deployed environment:

| Fact | State |
|---|---|
| `anthropic` version | 0.120.2, already a declared dependency |
| `anthropic.AnthropicVertex` | present in the installed package |
| `google-auth` | 2.56.3, already installed transitively through `google-cloud-storage` |
| Client construction sites | two, `reader._client` and `reader._verify_client` |
| Other client construction anywhere in `reader.py` | none |

So the transport move adds **no new SDK and no new vendor**, and
`tool_versions` — which names `anthropic-sdk`, `pydantic`, and `python` — does
not move. That is the unusual part of this change and the reason it is worth
doing separately from anything else: the diff is two functions and a
dependency extra.

`MODEL` stays `"claude-opus-5"`. ADR-0012's freeze on `SYSTEM`, `SCHEMA`,
`MODEL`, and `MAX_TOKENS` is untouched, and
`test_reader_and_probe_share_the_validated_prompt_bytes` compares those four
constants against `scripts/llm_probe.py` — not clients, not transports — so it
stays green by construction. This record does not amend ADR-0012 and must not
be read as narrowing it.

### The thing that is not free

`WholeInstrumentManifestV0` carries a `provider` field, hardcoded `"anthropic"`
at the risk-read call site. What that field means has never been decided,
because until now there was only one answer.

A2 in `docs/design/outcome-loop/addendum-agentic-architecture.md` states the
governing rule: whole-instrument identity covers the model snapshot and
inference parameters, prompt and output schema, input budget and ordering,
tools, orchestration graph, runtime commit, fallback policy, and publication
policy — and "any change creates a new instrument era and cannot silently
inherit historical evidence."

Two serving stacks for the same weights can differ in defaults, in snapshot
pinning, in retry and error surfaces, and in when a version is retired. None of
those differences is visible in a verdict row. Pooling them is exactly the
silent inheritance A2 forbids.

### The bar this runs against

`design-lock.md:83` names open risk #2: a single frozen instrument, where
"model retirement or price change forces a new validation run." A2 sets two
bars and the distinction decides how expensive this is:

- **Superiority** for a voluntary swap.
- **Non-inferiority** when a price or retirement event forces the move.

This is the forced class. The instrument is not being changed because a better
one was found; it is being moved because the terms of reaching the current one
changed. Demanding superiority here is how a forced move ships unmeasured
instead of measured, because the bar nobody can clear is the bar nobody runs.

## Decision

**1. `provider` names the API surface actually called, not the vendor of the
weights.** Moving the risk and intent reads to Vertex changes that field,
therefore moves `instrument_id`, and therefore partitions the labelled corpus
at the cutover. Reads before and after are not pooled. This is a cost, it is
chosen deliberately, and the alternative is in Rejected.

**2. The move clears A2's non-inferiority bar first,** through a paired silent
run: both transports score the same frozen PR snapshots, PR is the primary
unit, findings are nested evidence within a PR and never counted as independent
samples, and nothing surfaces to a customer or touches a published number until
the bar is met.

**3. The bar is declared before the run and is founder-only.** See below.

**4. `anthropic[vertex]` is declared explicitly in `api/pyproject.toml`.**
`google-auth` arrives transitively through `google-cloud-storage` today. That is
an accident of the dependency graph, and a transport that depends on an
accident is a transport that breaks when an unrelated dependency is dropped.

**5. Credentials follow the existing GCP path.** No new secret class, no new
key material in the service. If that turns out to be false in the build, this
record is wrong and gets amended rather than quietly worked around.

**6. Rollback is a constant, not a redeploy.** The transport is selected by
configuration read at client construction, so reverting is a value change and
not a release. A forced transition whose rollback needs a deploy is a forced
transition with an outage attached.

## The bar

**UNFILLED. Founder-only under R11. Do not run against these.**

| Quantity | Value | Notes |
|---|---|---|
| Corpus and size | ______ | The frozen PR snapshots the paired run scores |
| Non-inferiority margin on PR-level validated yield | ______ | The margin below the current transport that still counts as non-inferior |
| False-positive burden ceiling | ______ | Declared, not measured after |
| Latency and reliability constraints | ______ | The read sits inside a 300s Cloud Run request; `MAX_READ_RETRIES = 1` exists because of that arithmetic |

The margin is the number that matters and the one most likely to be filled in
loosely. A margin wide enough that nothing can fail it converts this record from
a measurement into a formality.

## Rejected

**Keeping `provider = "anthropic"` so the corpus does not partition.** This is
the tempting option and it is the one that destroys the evidence quietly. It
buys corpus continuity by asserting that the serving stack is not part of the
instrument, which is a claim about the world that nobody has tested, made by the
party who benefits from it being true. A2 already ruled the other way.

**Moving the mechanical tier in the same change.** It has its own record,
ADR-0027, its own conditions, and a different safety argument: the mechanical
passes are validated in code on every call and the risk read is validated by
nothing downstream. One PR moving both would make a single review decide two
questions that deserve different evidence.

**Bedrock.** `anthropic.AnthropicBedrock` is equally present in the installed
SDK, so the same two-function change reaches it. Not chosen and not rejected on
merit: the service already runs on Cloud Run with GCP credentials in the image,
so Vertex is the transport that adds no new cloud relationship. If that stops
being true, this record is the wrong one to consult.

**Shipping the move and measuring afterward.** ADR-0004's Rejected section
already refuses this shape: "the bars were frozen before the run, which is the
only reason the result is worth anything." ADR-0018 shipped against that rule
once, by direction, and was candid that the value ships governed by nothing.
Doing it twice would make the exception the practice.

**Running both transports live and splitting traffic.** That is a surfaced-policy
experiment. A2 reserves it for a later opt-in randomized stage, because only a
surfaced review can change the code, the merge decision, or reviewer effort — so
a live split measures something other than the transport.

## Consequences

- **The published series partitions at the cutover.** `example_pack_eval.py`
  partitions by `instrument_id`, so this is mechanical rather than a matter of
  discipline. Every surface that reports a rate names which era it covers, and
  the pre-registered publication series states the partition rather than
  spanning it.
- **The paired run doubles the read bill for its duration** on the line item
  that sets margin. Sampling or a corpus-only run is a decision to make before
  switching it on, not after the invoice.
- **This record is not a licence to move anything else.** It moves a transport
  for two named calls. A new prompt, schema, budget, tool, orchestration graph,
  or fallback policy is a different instrument under A2 and needs its own
  record.
- **`scripts/llm_probe.py` stays on the current transport.** It reports what it
  measured, which is the same reason ADR-0018 left its `EFFORT` alone.
- **If the bar fails, the record stands and the move does not happen.** A failed
  non-inferiority run is a result, not a reason to widen the margin. Widening a
  declared margin after seeing the data is the failure this whole file is
  arranged to prevent.
