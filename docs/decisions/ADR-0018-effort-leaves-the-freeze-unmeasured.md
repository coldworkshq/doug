---
title: Raise EFFORT to high and remove it from the freeze, without the run
status: accepted
date: 2026-08-23
amends: ADR-0012
---

> **This record contradicts two accepted ADRs, on purpose and by direction.**
> ADR-0012 froze `EFFORT`; ADR-0004 rejects "shipping the reader without
> pre-registration" on the grounds that "the bars were frozen before the run,
> which is the only reason the result is worth anything." Both objections are
> correct and neither is answered by anything below. See **What this contradicts**.
>
> `amends`, not `supersedes`: ADR-0012's coverage bar for `DIFF_BUDGET` is
> untouched and still binding. Only its freeze list changes.

## Context

`reader.EFFORT` was `"medium"`. The Claude API's default is `"high"`, so the
shipped reader ran one step **below** the provider default, and had since the
probe chose that value on 2026-07-29. Nothing chose `"medium"` for Doug — the
probe chose it, and `reader.py` inherited it along with the rest of the request
dict.

On `claude-opus-5`, `effort` governs thinking depth. Doug's measured failure mode
is not misreading the diff it was given; it is asserting things about a
repository from a diff without doing the reasoning that would expose the claim as
unresolvable from the evidence in hand. That is the class `effort` is supposed to
move.

ADR-0012 kept `EFFORT` frozen on the grounds that "nothing about the prompt,
schema, model, effort or output cap is measurably wrong." That is still true, in
the narrow sense that nothing has measured it wrong. Nothing has measured it at
all.

### What the freeze was still protecting

Less than it looks. ADR-0012 already recorded, in its own Consequences:

> **"The shipped reader is the one that scored AUC 0.687 sentry / 0.668 grafana"
> is now false.** Those figures describe the 30,000-character configuration in
> its original file order.

The live instrument already diverges from the validated one in input amount and
input order. `EFFORT` was the third of six constants to leave, not the first
crack in an otherwise intact claim.

That cuts both ways, and the second edge is the honest one: because the shipped
configuration is already unvalidated, adding a fourth divergence makes an
unmeasured instrument *less* well characterised, not more. "The AUC claim was
already void" is a reason the freeze protects little. It is not evidence that
raising `EFFORT` helps.

## Decision

`reader.EFFORT = "high"`. `scripts/llm_probe.py` stays at `"medium"`, because it
must go on reporting what it actually measured. The freeze narrows to **four**
constants: `SYSTEM`, `SCHEMA`, `MODEL`, `MAX_TOKENS`.

`test_effort_diverges_from_the_probe_on_purpose` pins both sides against
literals, in the shape `test_diff_budget_diverges_from_the_probe_on_purpose`
established. Literals rather than a cross-module inequality, because
`reader.EFFORT != llm_probe.EFFORT` would stay green if someone raised the probe
too — which is exactly the move that destroys the probe's ability to report what
it measured. Three mutations verified, including that one.

`MECHANICAL_EFFORT` does **not** move. The verify and attribution passes were
never in the probe and never in the freeze (ADR-0016), so they have no divergence
to record — and the same test pins that a blanket "raise effort everywhere" edit
does not sweep them up.

`read_with_decisions` reads the same constant and therefore moves with it. That
is in scope and stated here rather than discovered later; ADR-0007 keeps the
intent tier's output off the risk score, so no band changes because of it.

## What this contradicts

Doug flagged both of these on `b767f2e` at `high` severity, against the
unamended ADR-0012. It was right, and the flags are recorded here rather than
argued away.

**ADR-0012's freeze.** It states that `SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT` and
`MAX_TOKENS` remain frozen byte-identical to the probe, pinned by
`test_reader_and_probe_share_the_validated_prompt_bytes`. This ADR unfreezes
`EFFORT` and removes that assertion. ADR-0012 now carries an amendment banner
pointing here, so the two records no longer disagree in the directory Doug
reads.

**ADR-0012's replacement standard.** It permits a freeze to be replaced by a
governing bar, and is explicit about what made that safe:

> The bar is checked by `api/scripts/read_budget_gate.py`, which costs **zero
> model calls** ... That is the property that makes a coverage bar a safe
> replacement for a freeze.

`EFFORT` has no such bar and this ADR does not invent one. **It ships governed
by nothing.** That is a real weakening of ADR-0012's standard, not a variation
on it.

**ADR-0004's rejected alternative.** "Shipping the reader without
pre-registration. The bars were frozen before the run, which is the only reason
the result is worth anything." ADR-0004 said that about putting the reader in
the scoring path; it applies with the same force to changing the reader's
instrument, and this ADR does the thing that ADR-0004 rejected.

None of the three is answered. They are the price, and the price is recorded so
that a later reader does not have to rediscover it — or worse, cite this ADR as
precedent for the next unmeasured change. **It is not precedent.** The next one
needs its own direction, its own record, and preferably its run.

## This shipped without its pre-registered run, deliberately

`docs/design/reader-effort/preregistration.md` exists, has bars locked, and has
**not been run**. Andrew directed the raise anyway, twice, on 2026-08-23. This
section is the record of what that costs, so nobody later reconstructs it as an
oversight.

**No claim about accuracy attaches to this value.** Not "high is better", not
"medium was hurting us". The only defensible statements today are that `"high"`
is the provider default and that `"medium"` was never chosen for this workload.
Any future document citing an accuracy benefit from this change is citing
something that was not measured.

What the run would settle, and what it costs:

| | |
|---|---|
| Primary arm | AUC replication, sentry + grafana, 520 reads |
| Cost | **~$24 batched** — `llm_probe.py:250` already submits through the Batch API |
| Secondary arm | Findings-log precision, 27 PRs, no extra API spend |
| Real cost | ~1 day of blind dispositioning, which is not delegable to Doug |

The `$24` figure is itself the correction of an earlier error: ADR-0012 declined
this replication as costing "real money", and that decline predated anyone doing
the arithmetic against batch pricing that was already in force.

**Reversal is one line.** If the run is done and fails its bars, set `EFFORT`
back to `"medium"`, delete `test_effort_diverges_from_the_probe_on_purpose`, and
supersede this ADR. No migration, no data change.

### The pre-registration document is not to be edited

`docs/design/reader-effort/preregistration.md` stays byte-identical to the
version whose bars were locked. Bar 1 is `<=19.6%` disproved, bar 2 is `>=68`
real, and the power statement says the corpus can only detect a large effect.

An earlier version of this change added a banner to that file explaining that
the raise had shipped first. Doug flagged it on `b767f2e`: "mutating a
bars-locked pre-registration to accommodate a shipped value is the pattern
ADR-0018 itself names." That is right, and the irony was the tell — the banner's
own text said *do not amend the bars to fit the shipped value*, while amending
the document to fit the shipped value. Editing a locked document to record that
it was bypassed still edits a locked document, and the next editor has one fewer
reason not to.

The banner has been reverted. Everything it said lives here instead, which is
where a record of a decision belongs. **If the run happens and fails, the remedy
is the reversal above, never a bar edit.**

## Rejected

**Running the pre-registration first.** The correct order, and the one this ADR
does not follow. Declined by Andrew on the grounds that the raise is wanted now;
recorded as a decision rather than presented as best practice.

**Governing `EFFORT` by a cheap bar, the way ADR-0012 governs `DIFF_BUDGET`.**
There isn't one. `DIFF_BUDGET`'s coverage bar costs zero model calls because
`reader.coverage` is a pure function over the assembled diff, and ADR-0012 says
plainly that this property "is why a coverage bar is a safe replacement for a
freeze." Nothing about `effort` is checkable without spending money. Inventing a
proxy bar that could be computed for free would be the post-hoc bar edit ADR-0002
names as the way a failed experiment becomes a passed one.

**`xhigh`.** More plausible still for correctness-sensitive review, and one step
further from anything anyone has measured. If a run happens, it should include
`xhigh` as an arm rather than have it arrive by the same route this value did.

## Consequences

- Higher cost per read, unmeasured. `effort` raises thinking tokens, which bill
  as output, and nothing in this repo has measured that multiplier on this
  prompt. The pre-registration's estimate is 3x output, explicitly flagged there
  as assumed. **A 20-PR pilot would settle it for about $1** and should happen
  before anyone quotes a per-read cost.
- Higher latency per read, also unmeasured, against a 120s per-attempt timeout
  and a Cloud Run request budget of 300s (ADR-0017's neighbour, issue #178).
  Watch `reader-unavailable` rates after deploy; a rise there is the first place
  a too-slow read shows up.
- **`instrument_id` moves.** `EFFORT` is in the Example Pack manifest
  (`output_config.effort`), so reads before and after this change are not the
  same instrument and must not be pooled. `PROMPT_HASH` does **not** move — it is
  `sha256(SYSTEM + repr(SCHEMA))` and never took `EFFORT` as an input — so
  verdict comparability on prompt identity survives while instrument
  comparability does not.
- The convergence corpus is partitioned at the cutover for the same reason. Pairs
  spanning it compare two instruments.
- **Two of the probe's six constants have now left the freeze**, and four remain:
  `SYSTEM`, `SCHEMA`, `MODEL`, `MAX_TOKENS`. (An earlier draft of this line said
  "three have left ... the remaining four", which is seven of six. Doug caught
  the arithmetic on `b767f2e`.) If a **third** leaves, the freeze has stopped
  being a freeze and should be retired by name rather than eroded.
