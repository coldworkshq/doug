---
title: The mechanical tier may run a non-Anthropic model, and ADR-0016's scope claim is ratified
status: accepted
date: 2026-08-28
amends: ADR-0016
amended_by: ADR-0029
---

> **Amended by ADR-0029, 2026-08-28: the mechanical tier's TRANSPORT moved to
> Vertex. Its VENDOR boundary and all three conditions below are untouched.**
>
> This record's Consequences describe ADR-0028 as moving "the risk and intent
> reads' transport", and that is no longer the whole picture. ADR-0029 routes
> both client construction sites through Vertex, `_verify_client` included, so
> `verify_finding` and `attribute_findings` now reach the same `claude-sonnet-5`
> weights over a different API surface. Doug raised the gap (`beyond-ticket`)
> and it is marked here rather than only there.
>
> **Nothing about C1, C2 or C3 changes.** A transport is not a vendor. No
> non-Anthropic model serves the mechanical tier, C3 (#263) is still
> undischarged — it closed by accident on a commit-message keyword and has been
> reopened — and the attribution study has not been re-run. This record still
> governs any change of mechanical MODEL; ADR-0029 governs only how the request
> reaches it.
>
> ADR-0029 also did what item 5 forbids without a paired run, and says so in
> its own title. That was Andrew's direction against a funding constraint, not
> a reinterpretation of this record.

> **Two records in one, and only the first is free.**
>
> The first half ratifies the boundary claim ADR-0016 made about itself and
> flagged as self-authorized. It asks for no new evidence, because ADR-0016 is
> right that there is no experiment to run on a question of what an earlier
> record meant.
>
> The second half is not free. It lets the mechanical tier cross a vendor
> boundary that ADR-0016 never considered — every alternative that record
> rejected was an Anthropic model — and it costs a re-run of ADR-0015's
> pre-registered attribution study before anything ships.
>
> `amends`, not `supersedes`: ADR-0016's split of the four paid calls into a
> judgment tier and a mechanical tier is untouched and still binding, as is its
> rejection of moving the settlement passes. Only the tier's vendor boundary
> changes, and only under the conditions below.

## Context

### What ADR-0016 left open, by its own account

ADR-0016 has a section titled "This record is self-authorized, and that is worth
naming." It asserts that ADR-0012's frozen constants govern the risk read's
instrument and that `verify_finding` and `attribute_findings` were never inside
the freeze — they inherited `MODEL` and `EFFORT` from the request dict
`read_diff` was written with first. It then names the problem with asserting
that: the reading is made in the same change that benefits from it, by the party
that benefits. Doug flagged it on `da5b3fb`, and ADR-0016 records the flag as
fair.

It asks for one specific thing: sign-off that ADR-0012's constants describe the
risk read and not every call in `reader.py`. Until that sign-off, it says to
treat its scope claim as proposed rather than settled.

That sign-off has never been given. The claim has been load-bearing for five
days and is about to carry more weight than it was written to carry.

### What ADR-0016 did not consider

Every alternative in its Rejected section is an Anthropic model: `claude-haiku-4-5`
declined on headroom, and changing `MODEL` itself declined on the freeze. The
question of whether the mechanical tier may run a model from a different
provider was never asked, so nothing in that record answers it either way.

`design-lock.md:83` names the gap as open risk #2: a single frozen instrument,
where "model retirement or price change forces a new validation run." A2 in
`docs/design/outcome-loop/addendum-agentic-architecture.md` resolves it with two
bars, and the distinction is the whole reason this record can be short:
**superiority** for a voluntary swap, **non-inferiority** when a price or
retirement event forces a move.

### The safety argument transfers across vendors; the evidence does not

`reader.py`'s comment on the mechanical tier states the property that makes the
substitution safe:

> A weaker model can therefore only cost an abstention, never a wrong row, which
> is the property that makes this substitution safe and does not hold for the
> risk or intent reads.

That property rests on code, not on which weights answered. Verified on this
commit:

- `attribute_findings` rejects the whole response unless every pick is an
  integer within the enumerated hunk range (`reader.py:1669`), and code — not
  the model — converts validated numbers to content hashes.
- `ground_findings` carries an assertion that grounding is additive: every
  finding that goes in comes out. `verify.run_check` either produces a citation
  whose text it has hashed against the file at head, or abstains.
- Both fail soft on spend cap, transport, stop reason, parse, out-of-range pick,
  and index drift.

None of those three sentences mention a vendor. The worst case a foreign model
can buy is an abstention.

**What does not transfer is yield.** ADR-0015 admitted attribution on a
pre-registered study whose bars were frozen before any model call: 126 findings,
double-run, 0 of 84 state flips, 42 of 42 single-hunk controls, 50 of 59 yield on
the abstention class, and 0 of 25 danger-class contradictions against mechanical
ground truth. Those numbers measured `claude-sonnet-5`. The abstention-class
yield is the number that justified the pass existing at all — code validation
bounds the worst case, it does not preserve the yield. A foreign model that
abstains on 40 of 59 is safe and worthless.

### Two mechanical facts a swap runs into

- **`MECHANICAL_EFFORT` does not port.** It ships as a literal `"effort":
  "medium"` field in the request dicts at `reader.py:661` and `reader.py:1640`.
  It is an Anthropic request parameter, not a portable concept.
- **The manifest cannot tell two mechanical models apart.** `WholeInstrumentManifestV0`
  carries one `provider`, one `pinned_model_id`, and one `effort`, all describing
  the risk or intent read. `MECHANICAL_MODEL` appears nowhere in
  `example_pack_capture.py`; it reaches only the request dicts and the
  `_report_cost` line. So two reads that ran different mechanical models hash to
  the same `instrument_id`, while ADR-0015 makes `findings.hunks` — the
  attribution pass's output — part of convergence identity. Verified on this
  commit by grep: the capture path never names either mechanical call.

## Decision

**1. ADR-0016's scope claim is ratified.** ADR-0012's five constants describe the
risk read's instrument. `verify_finding` and `attribute_findings` were never
inside the freeze. ADR-0016's scope claim stops being provisional when this
record's status reaches `accepted`, and not before.

**2. The mechanical tier may run a model from any provider,** subject to three
conditions, all of which bind before production traffic reaches it.

- **C1 — Attribution re-earns ADR-0015's evidence.** No non-Anthropic model
  serves `attribute_findings` in production until the span-verification study is
  re-run against the frozen batches with the candidate and graded against the
  bars ADR-0015 froze. The harness is on main:
  `docs/design/walked-out/span_verification_run.py`,
  `span_verification_grade.py`, and `span-verification/batches.json`. A failure
  leaves the tier where it is. Re-running against frozen bars with a new
  instrument is a replication, not a new pre-registration; the bars are not
  reopened, and a candidate that misses them does not get new ones.
- **C2 — Verify reports its grounding rate, before and after.** `verify_finding`
  has no frozen bar to re-earn, because its output is grounded or discarded. It
  does have a yield, and a swap that halves the grounding rate is a real loss
  that nothing else would surface. The rate on the same corpus is recorded on
  both models and published in the record that names the model. No bar is set
  here; inventing one after the fact would be worth nothing.
- **C3 — The manifest names the mechanical model before it can vary.** The gap
  in Context is a blocker, not a note: while `instrument_id` cannot distinguish
  two mechanical models, a swap silently pools two instruments in a corpus that
  `example_pack_eval.py` partitions by exactly that hash. Fixing it needs code
  and a migration, so it lands before the swap, not after. Filed as **#263**.

  **This condition is enforced, not asserted.**
  `test_the_mechanical_tier_has_not_left_anthropic_while_the_manifest_cannot_say_so`
  fails the suite if `MECHANICAL_MODEL` leaves Anthropic while the manifest
  still cannot record which mechanical model produced a row. Doug flagged the
  unguarded state on the signing PR (`beyond-ticket`) and it was right: a
  condition that binds only in prose does not bind. The test names how to remove
  it — close #263 first, then delete it in the same PR that changes the model —
  so that it cannot be quietly relaxed to keep a swap green.

**3. The request path forks per vendor.** A vendor adapter owns its own parameter
names and its own defaults. `MECHANICAL_EFFORT` is not translated into a foreign
equivalent by guess; whatever is actually sent is recorded the way
`INFERENCE_PARAMETERS` records the risk read's, so provenance names what ran
rather than what the constant is called.

**4. This record names no model and no vendor.** It moves a boundary. The record
that picks a model states which one, reports C1 and C2, and cites this one.

**5. The risk and intent reads are out of scope.** ADR-0012's freeze on `SYSTEM`,
`SCHEMA`, `MODEL`, and `MAX_TOKENS` is untouched. Moving `read_diff` or
`read_with_decisions` to another provider, another transport, or another host —
including running the same `claude-opus-5` weights through a different API — needs
its own record and clears A2's non-inferiority bar with a paired silent run.
Nothing here licenses it.

## Rejected

**Editing ADR-0016 in place.** `docs/decisions/README.md` requires marking both
sides of an amendment, and ADR-0012's own Rejected section gives the reason: an
in-place edit erases the record of what was decided and why. ADR-0016 gets a
banner pointing here; its text stands.

**Ratifying the scope claim without touching the vendor question.** That is the
smaller and more honest record, and it was the first draft. It was rejected
because the sign-off is being requested now for a reason, and a ratification that
does not say what it is about to be used for is the same self-authorization
problem one level up.

**Swapping the tier on the code-validation argument alone.** The argument is
sound and it is not sufficient. It proves a foreign model cannot write a wrong
row. It says nothing about how often it writes a right one, and ADR-0015's 50
of 59 is the number that bought the pass its place in the read path.

**Requiring superiority.** A2 sets non-inferiority as the bar for a transition
forced by a price or retirement event, and superiority for a voluntary swap.
Demanding the higher bar for a forced move is how a forced move ships
unmeasured instead of measured, because the bar it cannot clear is the one
nobody runs.

**Moving the settlement passes.** Unchanged from ADR-0016 and still rejected.
`settle.py` drops findings, a drop is validated by nothing downstream, and the
safety argument above does not transfer to it.

**Pinning a model in this record.** It would make every future tier change an
amendment to a boundary record, which is how a boundary stops being one.

## Consequences

- **This record is inert until signed.** Only `accepted` records reach Doug's
  reader. While it sits at `proposed`, ADR-0016's scope claim stays provisional
  by its own terms and the tier stays inside Anthropic. Signing is flipping
  `status` and rewriting ADR-0016's banner in the same commit, the ADR-0022
  precedent.
- **C3 is #263, and it is code plus a migration.** It is the only condition
  here that cannot be discharged by running something that already exists, and
  it is worth doing whether or not this record is signed: the manifest's job is
  to say what produced a row, and today it under-describes the instrument by two
  paid model calls.
- **C1 costs one span-verification run per candidate model.** The corpus, the
  harness, and the bars exist, so the cost is compute and a grading pass, not
  design.
- **A second vendor in the process means a second SDK in `api/pyproject.toml`**,
  which moves `tool_versions` and therefore `instrument_id` for the risk read
  too, on a change that does not touch the risk read. That partition is a
  bookkeeping artifact, not an instrument change, and the record that adds the
  dependency says so at the time rather than leaving a future reader to work it
  out.
- **The cost figures in ADR-0016's Consequences go stale on the swap.** They are
  Anthropic list prices for a two-model tier. The record that picks a model
  restates them; this one does not, because it names no model.
- **A fourth test pins the mechanical tier, and ADR-0016 does not list it.**
  ADR-0016 names three. `test_effort_diverges_from_the_probe_on_purpose` also
  asserts `reader.MECHANICAL_EFFORT == "medium"` as a literal, with a comment
  saying it exists to catch a blanket "raise effort everywhere" edit sweeping
  the mechanical tier up. A vendor fork of the request path changes what that
  constant means, so the test is updated deliberately with a reason, never
  relaxed to keep a swap green.
- **Companion record: ADR-0028** moves the risk and intent reads' transport to
  Vertex. The two are deliberately separate. This record's tier is validated by
  code on every call; that one's is validated by nothing downstream, which is
  the distinction ADR-0016 drew and neither record blurs.
- **ADR-0016's line citations have already drifted.** It cites
  `reader.py:1607-1610` for the attribution range check, which is now at
  `reader.py:1669`, and `reader.py:695-703` for grounding. This record cites
  functions where it can and one line where it must, which is the same defect
  class as #230 and is not fixed here.
