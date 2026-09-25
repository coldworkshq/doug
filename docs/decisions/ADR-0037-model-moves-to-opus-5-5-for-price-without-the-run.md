---
title: MODEL moves to claude-opus-5-5 and leaves the freeze, for price, without a run
status: accepted
date: 2026-09-25
amends: ADR-0012, ADR-0016
---

> **This record contradicts ADR-0012's freeze and ADR-0018's warning, on
> purpose and by direction.** ADR-0012 freezes `MODEL` byte-identical to the
> probe. ADR-0018 says of its own unmeasured change that "it is not
> precedent" and that "the next one needs its own direction, its own record,
> and preferably its run." This change has the direction and this record. It
> does not have the run.
>
> `amends`, not `supersedes`: ADR-0012's coverage bar for `DIFF_BUDGET` is
> untouched, and `SYSTEM`, `SCHEMA` and `MAX_TOKENS` stay frozen.

## Context

The risk read and the intent read both send `reader.MODEL`, which was
`claude-opus-5`, the model the Phase-1 probe measured. Claude Opus 5.5 is the
next model in the same line. It costs $4 per million input tokens and $20
per million output tokens, against $5 and $25 for Opus 5, and it uses the
same tokenizer, so the same diff costs 20% less per token.

Andrew directed the switch on 2026-09-25, for price. The context was the
cost of review on the coldworks repository, where Doug read coldworks#105
five times (coldworks#109 moves that repository to one read per PR).

### What the request needed

Nothing but the model string. Opus 5.5 changes four things for code written
against Opus 5, and the reader uses none of them:

| Opus 5.5 change | The reader today |
|---|---|
| Thinking cannot be disabled | Sends no `thinking` parameter; runs adaptive on both models |
| The default effort is `medium`, not `high` | Sends `effort` explicitly (`EFFORT = "high"`, `MECHANICAL_EFFORT` is unaffected) |
| Forced `tool_choice` returns `400` | Sends no `tool_choice`; structured output goes through `output_config.format` |
| Thinking blocks bind to the model | Every read is one turn; nothing is replayed |

## Decision

`reader.MODEL = "claude-opus-5-5"`. `scripts/llm_probe.py` stays on
`claude-opus-5`, because it must go on reporting what it measured, and
`scripts/intent_probe.py` imports the probe's `MODEL`, so it stays too. The
freeze narrows to **three** constants: `SYSTEM`, `SCHEMA` and `MAX_TOKENS`.

`test_model_diverges_from_the_probe_on_purpose` pins both sides against
literals, in the shape `test_effort_diverges_from_the_probe_on_purpose`
established, and `test_reader_and_probe_share_the_validated_prompt_bytes`
drops its `MODEL` assertion for that one. The two ADR-0016 tests that assert
the literal the paid reads send now assert `claude-opus-5-5`.

`MECHANICAL_MODEL` does **not** move. It is `claude-sonnet-5` at $2 and $10,
which already costs less than Opus 5.5, and ADR-0016 governs it.

## What this contradicts

**ADR-0012's freeze.** It keeps `MODEL` byte-identical to the probe, pinned by
`test_reader_and_probe_share_the_validated_prompt_bytes`. This record removes
`MODEL` from that test and from the freeze. ADR-0012 carries an amendment
banner that points here, so the two records don't disagree in the directory
Doug reads.

**ADR-0018's warning.** It asks the next unmeasured change for its own
direction, its own record, and preferably its run. The run is the part
missing. `MODEL` ships governed by nothing, as `EFFORT` did.

**ADR-0004's rejected alternative**, which ADR-0018 already quotes: changing
the instrument without pre-registration. It applies here with the same force,
and nothing here answers it.

## Rejected

**Measure first.** Run `docs/design/reader-effort/preregistration.md`'s
design, or a new one, with both models on the same PRs before switching. It
is the right way to change an instrument, and ADR-0018 costs its AUC arm at
about $24 batched, but the real cost there is about one day of blind
dispositioning that only Andrew can do. Declined by direction: the saving
starts on the first read, and the reversal is one line.

**Stay on `claude-opus-5`.** It keeps the freeze and pays 25% more per token
for a model whose advantage on this prompt is unmeasured too. Nothing has
compared the two.

**Move the probe with the reader.** Syncing `llm_probe.MODEL` would keep the
freeze test green, and it is the one change this record forbids: the probe
would then claim to report a model it never measured.

**Move the mechanical tier to Opus 5.5.** It would raise that tier's cost,
which is the opposite of the reason for this change.

## Consequences

- **No claim about accuracy attaches to this value.** Not "Opus 5.5 reads
  better" and not "no worse." The AUC figures were already void for the live
  read (ADR-0012, ADR-0018), and this record adds a fourth divergence.
- **The saving is per token, not per read.** Input and output prices fall 20%.
  Output includes thinking, and adaptive thinking on a different model can
  spend a different number of tokens on the same diff. The `doug: read` cost
  lines on stderr are the measurement; nothing has read them yet.
- **The instrument era changes where the data records it.** Each verdict row
  stores the model that produced it, and the Example Pack manifest's
  `pinned_model_id` comes from the same constant, so reads before and after
  this change land in different `instrument_id` partitions and are never
  pooled.
- **A refusal falls back loudly.** Opus 5.5 runs broader safety classifiers
  (`bio` and `reasoning_extraction` join `cyber`). A refused read stops with
  `stop_reason: "refusal"`, which the reader already treats like every stop
  other than `end_turn`: a `ReaderError`, and the deterministic fallback that
  says so in its reasons. No server-side fallback to another model is added,
  because a silent rescue on a different model would record one model and
  score with another.
- **Availability gates the merge.** A merge to `main` deploys. If the Models
  API does not serve `claude-opus-5-5` to Doug's organization, every read
  falls back, and each fallback looks like a model outage rather than a bad
  deploy. Before the merge, confirm that
  `GET /v1/models/claude-opus-5-5` returns `200` with the organization's
  credential.
- **Reversal is one line.** Set `MODEL` back to `"claude-opus-5"`, restore the
  `MODEL` assertion in the freeze test, delete
  `test_model_diverges_from_the_probe_on_purpose`, and supersede this record.
  No migration and no data change.
