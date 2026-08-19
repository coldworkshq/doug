# Idea: the plan lane — a build plan as a tracked, vertical job graph

**Date:** 2026-08-18 · **Status:** capture-only — not designed, not evaluated, no ship date · **Origin:** Andrew, from a GitHub Actions run graph (`changes → api → web`), rendered vertical

Captured under the `distillation-shape.md` precedent: shape notes, not a decision.

---

## The idea

Render a build plan the way a CI run renders a job graph — vertical, one node per task, each node carrying its state — and drive it **from git** rather than from a checkbox someone remembered to tick. Commit, and the lane moves. Alongside it: flag design drift and stale docs.

## Why it has roots here, not just appeal

1. **Plans are already machine-readable.** `docs/superpowers/plans/*.md` use `- [ ]` per step, and every task declares `**Files:**`. That is a *declared intent* per task, in-tree, across ~40 files. Nobody has ever joined it to anything.
2. **Declared-vs-actual is Doug's existing instrument, aimed at a different unit.** `intent.py`, `intent_providers.py`, the `deviations` table and ADR-0007 already do declared-vs-actual at the **PR** level. The plan lane is the same instrument aimed at the **task**.
3. **Stale docs are the repo's stated #1 recurring defect.** `REVIEWING.md`: *"The recurring defect class here is a comment that outlives its truth."* And ADR-0012 rejected editing ADR-0002 in place precisely because *"a stale record does not merely mislead a human, it produces a confident false finding"* — decision records are an input to Doug's own reader, so staleness is not cosmetic here, it is a correctness bug in the instrument.

## The split that matters (and the part worth doing first)

**The cheap, deterministic half.** Parse a plan's checkboxes and each task's declared `**Files:**`; join to the commits on the branch. A task whose files have been touched and whose box is unticked, or vice versa, is a **fact about git**, not a judgement. Zero model calls, replayable, and it either renders honestly or it doesn't. This is the half that could ship.

**The expensive, unvalidated half.** "This ADR no longer describes the code" is a claim about intent. It rides the deviation instrument — which is currently labelled `unvalidated` after the 2026-07-31 derangement-check FAIL — and ADR-0007's precedent binds it: a new unvalidated signal gets its own stream and never moves the score. Bolting it to the visualization would ship a confident surface on an instrument that has not passed its own bar.

Do not let the second half ride in on the first half's cost.

## Open questions for whoever picks this up

- Is the unit the *plan* or the *branch*? Plans outlive branches; branches outlive plans.
- What does a node's state actually mean — box ticked, files touched, tests green, or merged? Each is a different claim and only some are checkable from git alone.
- Does this surface to customers, or is it internal tooling? If customer-facing it inherits the whole honesty contract; if internal it inherits none of it and can ship in a day.
- `docs/design/session-lane/` already exists and is design-stage. Overlap needs checking before anything is built.
- Nothing here may reopen: route-never-block, never-write-code/never-open-a-PR, ADR-0007 (deviations never touch score or band), ADR-0010 (the surface is an always-`neutral` check run).
