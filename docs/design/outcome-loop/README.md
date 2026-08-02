# The Outcome Loop — design pass, 2026-07-31

Product-architecture design for Doug's primitive: the verdict→outcome join. Produced by an
adversarial design debate (5 grounding agents → 3 independent positions → cross-examination →
Chief Architect rulings, converged round 1 → 3-skeptic red-team → lock).

Reading order:

1. **[design-lock.md](design-lock.md)** — the converged design: every ruled tension with the
   alternative it killed, supersessions, red-team mitigations applied, non-goals, open risks.
   The do-not-reopen record.
2. **[product-spec.md](product-spec.md)** — what it changes for the user, the journeys
   (install / empty scoreboard / loop closes / publication / garden), v1 vs vNext with
   promotion triggers, pricing, the honesty contract, cited sources.
3. **[architecture.md](architecture.md)** — the system diagram (ASCII), the loop's lifecycle,
   and where to split services / repos / GCP projects, each with its trigger.
4. **[experience.md](experience.md)** — the differentiated UX ("calibration, not confidence"),
   the five surfaces, copy rules, and a self-contained design brief for Claude design.
5. **[build-plan.md](build-plan.md)** — the seams with file:line anchors, Phase 0 dogfood
   gate, phases, test-for-intent strategy, and the concrete first moves.
6. **[addendum-agentic-architecture.md](addendum-agentic-architecture.md)** — post-lock
   rulings on the selective-agent proposal: evidence refinery, champion–challenger models,
   retrieval-first garden, 90-day replay onboarding (adopted); live specialist panel (gated
   behind a pre-registered experiment); agents-on-every-PR (rejected).
7. **[distillation-shape.md](distillation-shape.md)** — check-time deterministic MATCH;
   offline distillation as margin engine. Mirror: `workspace/research/distillation-shape.md`.
8. **[health-connectors.md](health-connectors.md)** — repo health narrative + inbound
   Datadog/Grafana/Sentry connector contract (not an observability product). Mirror:
   `workspace/research/health-connectors.md`.
9. **[survival-probe-1-preregistration.md](survival-probe-1-preregistration.md)** / **[survival-probe-1-results.md](survival-probe-1-results.md)** — garden survival pulse #1 on sentry (FAIL on locked bars; does not unlock PC2).
10. **[ROADMAP.md](ROADMAP.md)** — the tracking document: milestones M0–M6 with checkboxes,
   exit gates, and triggers. Progress is checked off in the PRs that earn it.

Ground rules this design inherits (brand-level, closed): route never block · never write
code, never open a PR · publish the miss rate.
