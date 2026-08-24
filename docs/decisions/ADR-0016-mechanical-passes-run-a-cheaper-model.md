---
title: The verify and attribution passes run their own model, not the frozen one
status: accepted
date: 2026-08-23
---

## Context

Four paid model calls exist in `api/doug/reader.py`. Until now all four sent
`MODEL = "claude-opus-5"` at `EFFORT = "medium"`, because `read_diff` was the
first one written and the other three copied its request dict.

Two of the four are not judgments. They are lookups with validated answers:

- **`attribute_findings`** enumerates a file's hunks, numbers them, and asks
  which numbers a finding rests on. The response is a list of integers.
  `attribute_findings` then range-checks every integer against the stored hunk
  index and discards the whole row if any is out of bounds
  (`reader.py:1607-1610`). The model cannot name a hunk that does not exist,
  cannot name a file, and cannot write a value into a row directly.
- **`verify_finding`** returns a place to look. `verify.run_check` grounds that
  location against the file at head and either produces a `Citation` whose text
  it has hashed, or abstains (`ground_findings`, `reader.py:695-703`). A
  location that does not check out yields nothing.

Both fail soft on every path, and `ground_findings` carries an assertion that
grounding is additive: a finding that goes in comes out.

The other two calls are judgments. `read_diff` produces the risk score and the
findings; `read_with_decisions` produces the alignment read. Nothing downstream
validates either — `verdict_from_reader` maps findings to reasons 1:1 and stores
them.

ADR-0012 freezes `SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT` and `MAX_TOKENS`
byte-identical to `scripts/llm_probe.py`, and that freeze is about the risk
read's instrument. Neither mechanical pass was in the probe. Neither has ever
been covered by the freeze; both were merely sharing its constants by
inheritance.

## Decision

`MECHANICAL_MODEL = "claude-sonnet-5"` and `MECHANICAL_EFFORT = "medium"`
(`reader.py:64-65`). `verify_finding` and `attribute_findings` send them.
`read_diff` and `read_with_decisions` continue to send `MODEL` and `EFFORT`,
unchanged and still frozen.

`_report_cost` takes the model as a parameter instead of interpolating the
module constant. Its own docstring already named this failure — "the moment
anyone splits it per read, a line that silently changed meaning is this repo's
recurring defect" — and the split has now happened.

Three tests pin it, each mutation-verified:

| Test | Catches |
|---|---|
| `test_the_mechanical_passes_run_their_own_model_and_say_so` | either pass drifting back to `MODEL`, and the cost line naming a model that did not run |
| `test_the_two_paid_reads_did_not_follow_the_mechanical_tier_down` | the "tidy-up" that unifies the two constants and silently re-anchors the risk read |
| `test_every_read_line_names_the_model_that_produced_it` | `_report_cost` reverting to the constant |

The second and third assert against the literal `"claude-opus-5"` rather than
`reader.MODEL`, so that setting `MODEL = MECHANICAL_MODEL` cannot make them
tautologically true.

## This record is self-authorized, and that is worth naming

ADR-0012 froze five constants. This ADR asserts that the freeze governs the risk
read's instrument and that `verify_finding` / `attribute_findings` were never
inside it — they were sharing `MODEL` and `EFFORT` by inheritance from the
request dict `read_diff` was written with first, not by a decision.

That reading is almost certainly right, and it follows ADR-0012's own precedent
of narrowing scope through a new record rather than an in-place edit. It is also
an interpretation of a freeze's boundary, made in the same change that benefits
from it, by the party that benefits. Doug flagged exactly this on `da5b3fb`
("the scope-narrowing is self-authorized here"), and the flag is fair.

What would ratify it: Andrew's sign-off on the boundary claim specifically —
that ADR-0012's five constants describe the risk read and not every call in
`reader.py`. Nothing here depends on new measurement, so there is no experiment
to run; the question is whether the reading of ADR-0012 is the intended one.
Until that sign-off, treat this ADR's scope claim as proposed rather than
settled, even though its status line says accepted for the change it makes.

## Rejected

**Changing `MODEL` itself.** Breaks
`test_reader_and_probe_share_the_validated_prompt_bytes` and, worse, would move
the risk read onto an unvalidated instrument while every stored verdict kept
claiming the frozen one. The `model` column on `verdicts` records the risk
read's model; it is not a per-call field.

**`claude-haiku-4-5`.** Cheaper again ($1/$5 per MTok against Sonnet 5's $3/$15
and Opus 5's $5/$25). Declined by Andrew, 2026-08-23. Sonnet 5 keeps more
headroom on the attribution task, which is the one whose input can run to
several thousand tokens of hunk text, and the saving from Opus is already the
large step.

**Moving the settlement passes too.** `settle.py` and any future generalized
settlement **drop** findings. A drop is not validated by anything downstream —
that is the whole point of it — so the safety argument above does not transfer,
and a weaker model there would buy cost by losing real findings.

## Consequences

- Per review with both flags on, at list prices: **$0.072 → $0.043**, a 40%
  reduction on the mechanical tier. The risk read's ~$0.074 is untouched.
- **Half that saving is realised on merge; half is not.** An earlier draft of
  this section claimed both passes were dark and the saving was $0.00. That was
  true when it was written and false by the time the PR was opened, because the
  same PR turns grounding on (ADR-0017). Doug caught it on its own review of
  `da5b3fb` as `reader:doc-code-inconsistency`, and it is corrected here rather
  than in place-with-no-trace, because `docs/decisions/README.md` records that
  these files are an input to Doug's own reader: a stale record "does not just
  mislead a human, it produces a confident false finding."
  - `verify_finding` is **live** for the installation `DOUG_VERIFY_INSTALLATIONS`
    names, so its share of the saving starts on deploy.
  - `attribute_findings` stays dark; `DOUG_ATTRIBUTION` is unset. Its share is
    prospective.
- Sonnet 5 carries introductory pricing ($2/$10) through 2026-08-31. The figures
  above use list price deliberately, so that nothing here silently gets more
  expensive on 2026-09-01.
- The spend cap is unaffected in shape. `_charge(scope)` counts reads, not
  tokens, and both passes already charge their own scope prefixes to stay off
  the customer's published `deep reads N/200` meter.
- `PROMPT_HASH` and `ATTRIBUTION_PROMPT_HASH` are unmoved: neither takes a model
  as input. Verdicts stay comparable on prompt identity across this change.
- A future third model tier gets harder to add carelessly, because
  `_report_cost` now demands the caller name which model it bought.
