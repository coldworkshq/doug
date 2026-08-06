---
title: Keep the reader prompt and schema frozen; govern DIFF_BUDGET by a coverage bar
status: accepted
date: 2026-08-06
supersedes: ADR-0002
---

## Context

ADR-0002 froze six constants byte-identical to `scripts/llm_probe.py` at
commit `0064e6b`: `SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT`, `MAX_TOKENS` and
`DIFF_BUDGET`. The reasoning holds for five of them. It does not hold for
`DIFF_BUDGET`, and keeping it frozen has a measured cost.

`DIFF_BUDGET` is 30,000 characters — roughly 7,500 tokens, on a model with
a 1M-token context window. Measured over the last 30 first-parent commits:

| | share |
|---|---|
| Diff exceeds the budget | 37% |
| **Code alone** exceeds the budget | 20% |

Three consecutive reviews of the tenancy work never read `tenancy.py`. On
PR #50 (`41182c1`), `api.py` consumed 18,606 chars — 62% of the whole
budget — because `a` sorts before `t`, and the 13,014-char `tenancy.py`
was never sent. Ordering the diff (`review.read_order`) fixes the 17-point
gap where prose and tests crowd out code. It cannot fix the 20% where code
alone exceeds the budget: at 30,000 characters you are choosing which half
of PR #50's 57,441 chars of code to miss, not whether to miss it.

The five other constants have no equivalent problem. Nothing about the
prompt, schema, model, effort or output cap is measurably wrong.

## Decision

`SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT` and `MAX_TOKENS` remain frozen
byte-identical to `scripts/llm_probe.py`, pinned by
`test_reader_and_probe_share_the_validated_prompt_bytes`. ADR-0002's rule
survives for them intact.

`DIFF_BUDGET` is removed from the freeze and governed instead by a
pre-registered coverage bar:

> **100% of code-tier characters sent on ≥95% of PRs**, over the 30
> first-parent commits ending at `135c8e5`.

It is set to **100,000 characters**. The bar is checked by
`api/scripts/read_budget_gate.py`, which costs **zero model calls** —
`reader.coverage` is a pure function over the assembled diff, so the
governing metric is verifiable by anyone at any time without spending a
cent. That is the property that makes a coverage bar a safe replacement
for a freeze.

The probe's own `DIFF_BUDGET` stays at 30,000. It is the frozen
instrument and must keep reporting what it actually measured.

## Rejected

**Leave `DIFF_BUDGET` frozen and ship ordering alone.** Leaves 20% of PRs
with code the reader structurally cannot see. Ordering would improve which
half is missed while the miss itself stayed guaranteed.

**Edit ADR-0002 in place.** Would erase the record of what was frozen and
why. Worse here than in an ordinary codebase: `docs/decisions/README.md`
records that these files are an input to Doug's own reader, so a stale
record does not merely mislead a human, it produces a confident false
finding. A record still claiming `DIFF_BUDGET` was frozen at 30,000 would
have generated exactly that on the PR that changed it.

**60,000.** Covers 100% of code in the sample but only 83% of code+tests.
Tests are load-bearing for this reader: `reader.py`'s coverage comment
records lema#643, where the mutation-verified test file that would have
deduped two findings was never sent.

**200,000.** +$0.007 per read over 100,000 for three points of docs
coverage, on files ranked last precisely because they cannot hold the
defect class the reader is asked for.

**Re-run the probe at 100,000 to keep the AUC claim attached to what
ships.** Costs real money on the 653-PR corpus. Declined (Andrew,
2026-08-06) in favour of recording the limit honestly — see Consequences.

## Consequences

- Coverage at 100,000, with tiering, over the pinned range: **100% of code
  sent, 97% of code+tests**, at **+$0.019 mean per read** ($0.056 →
  $0.074). The budget is a ceiling, not a spend: median diff is 21,785
  chars, so 63% of PRs already fit under 30,000 and cost nothing more. A
  PR that saturates 100,000 costs about +$0.09.
- **"The shipped reader is the one that scored AUC 0.687 sentry / 0.668
  grafana" is now false.** Those figures describe the 30,000-character
  configuration. The prompt, schema, model and effort are unchanged, so
  the instrument is the same in every respect except how much diff it
  sees — but that is not nothing, and it is not measured. Any future
  citation of those numbers must name the configuration that produced
  them. This is the price of the decision, paid openly rather than
  hidden.
- Spend caps are unaffected in shape. `_charge(scope)` still runs before
  the client is constructed and still counts reads, not tokens. The
  4,000 reads/installation/month ceiling now admits a more expensive
  read, which is deliberate.
- `PROMPT_HASH` is unmoved: it is `sha256(SYSTEM + repr(SCHEMA))` and
  `DIFF_BUDGET` was never an input. Verdicts written before and after this
  change stay comparable on prompt identity, and the M3 receipt that
  carries the hash does not silently re-anchor.
- Raising the budget again is not free: it needs a new pre-registered bar
  and a new record. The friction ADR-0002 created is retained, moved from
  "never change this" to "change it against a stated, checkable bar".
