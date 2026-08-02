# Addendum: Selective-Agent Architecture

**Date:** 2026-07-31 · **Status:** rulings on post-lock founder input · **Extends** `design-lock.md`; nothing here reopens a locked decision.

Context: after the lock, the founder brought a proposal for agentic orchestration around the loop — a live specialist review team, an offline "evidence refinery," a retrieval-first garden elaboration, and champion–challenger model management. The proposal's governing principle is adopted verbatim as design law:

> **Agents make hypotheses. Evidence decides what becomes product behavior.**

The deterministic spine (score → clock → adjudicate → publish) is unchanged. Agents attach around it. Rulings:

## Adopted

**A1 — The evidence refinery (offline learning council). Phase 3+, once adjudicated data exists.**
Pattern miners propose lessons from verdict→outcome joins → a prosecutor hunts counterexamples and confounders → replication agents test across time splits, repos, and model versions → deterministic statistics compute lift, uncertainty, and sample sufficiency → a policy compiler emits *candidate* rules or garden guidance → **a deterministic gate — never an LLM — promotes, rejects, or holds as experimental** → a monitor re-tests promoted lessons continuously and demotes on lift decay.
This is the standing-machinery form of disciplines the corpus already enforces: only outcome-predictive findings become behavior (IDEAS.md distillation constraint), every promotion clears a portability gate (the `hotspot_path` 0-of-12,000 lesson), and anything entering review-time routing additionally clears the 2.34× disjoint-population bar. Nothing the refinery produces enters `score()` unless `backtest/replay.py` can replay it — the lock's rule, unchanged.

*Shape notes (2026-08-01, capture-only; mirrored under `workspace/research/`):*
[`distillation-shape.md`](distillation-shape.md) · [`health-connectors.md`](health-connectors.md).

**A2 — Champion–challenger model management.** Resolves design-lock open risk #2 (single-model dependency) with the ADR-0002-compliant path: a new model is a *new instrument*, and shadow mode is its validation run. Challengers score the same PRs in shadow (never surfacing to customers, never touching the ledger's published numbers); promotion requires a versioned evaluation on the matured outcome set showing improvement on capture, calibration, cost, and latency. Vertex Model Garden / evaluation are optional tooling; the deterministic comparison on Doug's own outcome set is the essence.

*Operationally (2026-08-01):* a beta path running beside live, released only when it measurably beats live. `verdicts.source` is the quarantine (shipped, migration 002 — the same mechanism already carrying `replay` and `research`) and `prompt_hash` segments rates by instrument version, so two eras are never silently averaged. Because adjudicated evidence lags 14–60 days, promotion runs in two stages: replay the challenger against the 653-PR corpus whose labels already exist — immediate, and it decides whether shadowing is even warranted — then shadow live traffic for the outcome evidence that actually promotes it; stage 1 alone is the backtest-overfitting trap, stage 2 alone is too slow to iterate against. Shadow doubles the deep-read bill on the line item that sets margin, so sample or corpus-only is a decision to make before switching it on. Two bars, not one: *superiority* for a voluntary swap, *non-inferiority* when the move is forced — this track's own trigger is a model price or retirement event, and a superiority-only rule leaves no legal move when the champion is retired out from under us. Prompt revisions ride the identical path: ADR-0002 freezes the bytes so rates stay comparable, which makes a revised prompt a new instrument on the same terms. The bar is declared before the run, or a challenger that wins on one of four metrics gets promoted on that one.

**A3 — Retrieval-first garden elaboration (v1.5 detail).** Deterministic retrieval of outcome-backed, compatibility-filtered evidence is the default and the fast path; the compatibility check, skeptic pass, and composer are bounded refinements on top. The composer may explain evidence; it cannot invent or promote a pattern. The refusal behavior (weak or incompatible evidence → decline, with the reason) is unchanged from the lock. Bound: a writing agent is blocked waiting on this call — agent passes must fit a latency budget or be skipped.

**A4 — Replay as the onboarding win.** The under-weighted sleeper. On install, Doug replays the repo's recent history (target: last 90 days): scores the historical PRs, adjudicates them against the reverts that *already happened* using the same `git_labels` detector, and shows a filled **retrospective** scoreboard on day 1. Discipline: replay rows carry `source='replay'` and are structurally excluded from the prospective counters and every published rate — retrospective and prospective are different instruments and each receipt names which it is. The prospective clock still starts at zero and says so. COGS: one deep read per replayed PR (~$0.15; ~$45 one-time at 300 PRs — sample if larger). Product effect: the empty-scoreboard journey keeps its honesty and loses its emptiness.

## Gated (admitted as a pre-registered experiment, not a v1 commitment)

**G1 — The live specialist panel** (security / migration / concurrency / architecture / test-evidence agents + adversarial reviewer + synthesizer, invoked on the flagged minority). Three bounds, from the debate's own findings:
- *Economics:* under ADR-0004 the deep read IS the ranking, so the panel is a second, costlier tier — ~6 opus-class calls on ~25% of PRs ≈ $70–90/mo COGS on a 300-PR repo against a $99 card. It runs on cheaper models, on a tighter budget, or as a separately priced tier; it never silently eats the margin.
- *Validation:* the panel is a new, unvalidated instrument. Its findings ship as labeled advisory receipt content (the deviations pattern: separate stream, never touching score or band) until a pre-registered bar clears: **panel-on-flagged-band beats single-read-on-flagged-band on outcome capture, measured by the loop itself.** The refinery (A1) is the natural harness for that experiment.
- *Identity:* the altitude finding stands — everything that makes Doug a competing reviewer erodes the moat. The panel's product meaning is *deeper receipts on the risky few*, never "Doug reviews harder than Bugbot."

## Rejected

- **Agents on every PR** (proposal's option 2): cost and noise scale with exactly what agents are inflating; reproduces the competitor shape; unfalsifiable spend. Killed.
- **Offline-agents-only as the identity** (option 3): the spine *is* deterministic, but the live experience differentiates on receipts + adjudication, not on being a classifier; no change needed to get option 3's auditability.
- **Agent Engine for the live pipeline:** the live verdict path is a fixed, auditable workflow and stays on Cloud Run (lock, unchanged). Agent Engine remains a *later, optional* host for the offline council only, if session/trace management earns its bill.

## Consequences for other documents

- `product-spec.md`: install journey and v1 cut gain the 90-day replay (labeled retrospective).
- `experience.md`: scoreboard surface gains the day-1 replay panel, visually distinct from prospective counters.
- `build-plan.md` unchanged: replay reuses the backtest machinery (`harvest`/`replay`/`git_labels`) already in the repo; the refinery and panel are post-Phase-3 work with their own gates.
