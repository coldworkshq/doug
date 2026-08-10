# Addendum: Selective-Agent Architecture

**Date:** 2026-07-31 · **Status:** rulings on post-lock founder input · **Extends** `design-lock.md`; nothing here reopens a locked decision.

**Corrected 2026-08-09:** the identity and evaluation language below now follows the shipped reader contract and the locked publication preregistration. This is a correction of how the experiment is identified and what its evidence may claim, not approval to build or surface the panel.

Context: after the lock, the founder brought a proposal for agentic orchestration around the loop — a live specialist review team, an offline "evidence refinery," a retrieval-first garden elaboration, and champion–challenger model management. The proposal's governing principle is adopted verbatim as design law:

> **Agents make hypotheses. Evidence decides what becomes product behavior.**

The deterministic spine (score → clock → adjudicate → publish) is unchanged. Agents attach around it. Rulings:

## Adopted

**A1 — The evidence refinery (offline learning council). Phase 3+, once adjudicated data exists.**
Pattern miners propose lessons from verdict→outcome joins → a prosecutor hunts counterexamples and confounders → replication agents test across time splits, repos, and model versions → deterministic statistics compute lift, uncertainty, and sample sufficiency → a policy compiler emits *candidate* rules or garden guidance → **a deterministic gate — never an LLM — promotes, rejects, or holds as experimental** → a monitor re-tests promoted lessons continuously and demotes on lift decay.
This is the standing-machinery form of disciplines the corpus already enforces: only outcome-predictive findings become behavior (IDEAS.md distillation constraint), and every promotion clears a portability gate (the `hotspot_path` 0-of-12,000 lesson). The historical 2.34× disjoint-population result is a Sentry-specific comparator, not a universal promotion threshold: a new candidate needs a pre-registered practical margin, uncertainty, and temporal and repository holdouts appropriate to its named claim. Nothing the refinery produces enters `score()` unless `backtest/replay.py` can replay it — the lock's rule, unchanged.

*Shape notes (2026-08-01, capture-only; mirrored under `workspace/research/`):*
[`distillation-shape.md`](distillation-shape.md) · [`health-connectors.md`](health-connectors.md).

**A2 — Champion–challenger instrument management.** Resolves design-lock open risk #2 (single-model dependency) with the ADR-0012-compliant path: a new model, prompt, input policy, context policy, toolset, orchestration graph, runtime, fallback, or publication policy creates a *new instrument*. Silent challengers score the same frozen PR snapshots without surfacing to customers or touching the ledger's published numbers. That paired shadow run can establish review quality, calibration, cost, latency, and reliability; it cannot establish the causal effect of surfacing because only the surfaced review can change the code, merge decision, or reviewer effort. Vertex Model Garden / evaluation are optional tooling; Doug's versioned experiment contract and deterministic promotion gates are the essence.

*Operationally (corrected 2026-08-09):* a beta path runs beside live and is released only after the evidence required for its named claim clears a declared bar. `verdicts.source` remains a quarantine label for replay and research rows; `prompt_hash` is one component receipt, not the instrument identity. The whole-instrument identity covers the model snapshot and inference parameters; prompt and output schema; input budget and ordering; Context Pack schema, retriever, and selection policy; tools; orchestration graph and roles; runtime commit; fallback policy; and publication policy. Any change creates a new instrument era and cannot silently inherit historical evidence.

Evaluation has separate stages. Replay against the frozen 653-PR corpus decides whether a challenger deserves prospective spend; it cannot promote by itself because it is vulnerable to backtest overfitting. A paired silent study then runs eligible instruments on the same frozen PR snapshots, with PR as the primary unit and findings nested within PRs rather than counted as independent samples. It measures blinded validated yield and false-positive burden under declared cost, latency, and reliability constraints. A later opt-in randomized surfaced-policy experiment assigns exactly one instrument per PR and analyzes intention-to-treat; that is the stage required before claiming that surfacing the challenger changes developer behavior or downstream outcomes. Shadow doubles the deep-read bill on the line item that sets margin, so sample or corpus-only is a decision to make before switching it on. Two bars remain for forced model transitions: *superiority* for a voluntary swap and *non-inferiority* when a model price or retirement event forces a move. Every bar is declared before its run.

**A3 — Retrieval-first garden elaboration (v1.5 detail).** Deterministic retrieval of outcome-backed, compatibility-filtered evidence is the default and the fast path; the compatibility check, skeptic pass, and composer are bounded refinements on top. The composer may explain evidence; it cannot invent or promote a pattern. The refusal behavior (weak or incompatible evidence → decline, with the reason) is unchanged from the lock. Bound: a writing agent is blocked waiting on this call — agent passes must fit a latency budget or be skipped.

**A4 — Replay as the onboarding win.** The under-weighted sleeper. On install, Doug replays the repo's recent history (target: last 90 days): scores the historical PRs, adjudicates them against the reverts that *already happened* using the same `git_labels` detector, and shows a filled **retrospective** scoreboard on day 1. Discipline: replay rows carry `source='replay'` and are structurally excluded from the prospective counters and every published rate — retrospective and prospective are different instruments and each receipt names which it is. The prospective clock still starts at zero and says so. COGS: one deep read per replayed PR (~$0.15; ~$45 one-time at 300 PRs — sample if larger). Product effect: the empty-scoreboard journey keeps its honesty and loses its emptiness.

## Gated (admitted as a pre-registered experiment, not a v1 commitment)

**G1 — The live specialist panel** (security / migration / concurrency / architecture / test-evidence agents + adversarial reviewer + synthesizer, invoked on the flagged minority). Three bounds, from the debate's own findings:
- *Economics:* under ADR-0004 the deep read IS the ranking, so the panel is a second, costlier tier — ~6 opus-class calls on ~25% of PRs ≈ $70–90/mo COGS on a 300-PR repo against a $99 card. It runs on cheaper models, on a tighter budget, or as a separately priced tier; it never silently eats the margin.
- *Validation:* the panel is a new, unvalidated instrument. Its first gate is a pre-registered paired shadow study: on the same eligible frozen PRs, it must beat a compute-matched grounded single reader on a PR-level validated-yield endpoint without violating the declared false-positive, cost, latency, or reliability constraints. Findings are nested evidence within a PR, never independent sample units. Passing that gate may qualify the panel for labeled advisory receipt content; it does not establish that surfacing the panel changes downstream outcomes. That causal claim requires the later opt-in randomized surfaced-policy canary defined in A2. The refinery (A1) is the natural harness for both stages.
- *Identity:* the altitude finding stands — everything that makes Doug a competing reviewer erodes the moat. The panel's product meaning is *deeper receipts on the risky few*, never "Doug reviews harder than Bugbot."

## Rejected

- **Agents on every PR** (proposal's option 2): cost and noise scale with exactly what agents are inflating; reproduces the competitor shape; unfalsifiable spend. Killed.
- **Offline-agents-only as the identity** (option 3): the spine *is* deterministic, but the live experience differentiates on receipts + adjudication, not on being a classifier; no change needed to get option 3's auditability.
- **Agent Engine for the live pipeline:** the live verdict path is a fixed, auditable workflow and stays on Cloud Run (lock, unchanged). Agent Engine remains a *later, optional* host for the offline council only, if session/trace management earns its bill.

## Consequences for other documents

- `product-spec.md`: install journey and v1 cut gain the 90-day replay (labeled retrospective).
- `experience.md`: scoreboard surface gains the day-1 replay panel, visually distinct from prospective counters.
- `build-plan.md` unchanged: replay reuses the backtest machinery (`harvest`/`replay`/`git_labels`) already in the repo; the refinery and panel are post-Phase-3 work with their own gates.
