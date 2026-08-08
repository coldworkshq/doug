# Design: The Session Lane and the Derived Decision Record

**Status:** design-stage, dogfood-first. Not on the M3 path; builds nothing until M3 closes.
**Companion to:** `../outcome-loop/product-spec.md` (the ledger this extends), `../outcome-loop/design-lock.md`, `docs/decisions/ADR-0006` (unchanged by this design — see §9).
**Parent thinking:** `lemahq/lema/docs/session-state-brainstorm-2026-08-06.md` — the session-state design this doc rehomes into Doug, minus its judgment queue.
**Origin:** 2026-08-07 cross-portfolio synthesis (Doug × lema × coldworks). Andrew's rulings that shaped it: Doug is the front door; no human judgment queue anywhere; commitment is the decision; the record informs, never blocks.

---

## 1. Thesis

Doug already grades the *outcome* of work — verdicts, clocks, adjudications. This design gives Doug the *process* that produced the work: agent sessions arrive as a second ingest lane beside the GitHub App, and a decision record is **derived** from what teams already commit — never entered, never approved, never queued. The marriage of the two is the product: Doug becomes the only reviewer that has seen the work in flight, the diff at review, and the outcome after merge, and can say — without blocking anything — *"this was decided here, on this date, for this reason, and here is how it has held up since."*

Every AI reviewer on the market reads the same diff. None of them can read the work that produced the diff, because none of them has session records joined to outcomes. This lane is that join.

## 2. The four laws (and the meta-law)

The judgment queue died in lema for the correct reason: its only user clicked through it without reading. The lesson generalizes:

> **Judgment is observed, never solicited.** Harvest it from actions people already take; never create an action whose only purpose is judging.

Everything else follows as four mechanical laws:

1. **Commitment creates.** Merged code, a committed architecture doc, a resolved review thread — that is what a decision *is*. The artifact is the approval. Decisions have no draft state a human must clear.
2. **Outcomes grade.** The verdict clock, hotfix chains, and fingerprint drift do the quality control. A committed-but-wrong decision is demoted by its own record, not by a ruling.
3. **Recency supersedes.** When a newer commitment contradicts an older one, the newer wins. Supersession is derived, never declared. Conflicts are resolved by the next commit, not by an adjudicator.
4. **Surfacing informs.** The record is raised to agents and humans at the moment it is relevant — boot, edit, review — with date, reason, origin links, and track record. It gates nothing.

## 3. The system, tied together

```
                      THE LOOP
   commitment creates → outcomes grade → recency supersedes → surfacing informs
        ▲                                                            │
        └──────────────── shapes the next commitment ◀───────────────┘

 SOURCES — observed seams; nothing is entered by hand
 ════════════════════════════════════════════════════════════════════════════════════
  [A] GitHub App lane (LIVE)      [B] Session lane (NEW)            [C] Artifact lane (NEW)
  ───────────────────────────     ───────────────────────────       ─────────────────────────
  PR opened / merged              harness hooks (Claude Code        committed code
  pull_request_review             first, dogfood):                  architecture docs and
  revert / hotfix detection         boot {anchors, lineage}         ADR markdown in the repo
        │                           footprint {entity, role}  obs.  (ADR-0006's decision
        │                           rationale_trace {claim,   asrt. provider, now feeding
        │                             why, evidence}                the ledger)
        │                           checkpoint {next, open}           │
        ▼                                   ▼                         ▼
 ┌───────────────────────────────────────────────────────────────────────────────────┐
 │                     APPEND-ONLY LEDGER (Postgres — exists today)                  │
 │   verdicts · outcomes · outcome_jobs · findings      + session_events             │
 │   receipts                                           + session_cards              │
 │                                                      + rationale_traces           │
 │                                                      + derived_decisions          │
 │   shared grammar (the ex-lema IR):                                                │
 │   { subject, evidence, authority, outcome, effective_at } · append-only ·         │
 │   supersede-only · observed/asserted registers never blended                      │
 └───────┬──────────────────┬──────────────────┬─────────────────────┬───────────────┘
         │                  │                  │                     │
         ▼                  ▼                  ▼ S1                  ▼ S2
   VERDICT CLOCK       CARD DERIVER       CORRELATOR           DECISION DERIVER
   (exists)            (new, async)       (new)                (new)
   14 / 60 day:        session_events     session ↔ PR join:   committed artifact
   revert | hotfix     → SessionCard      branch name,         + linked rationale
   | clean             intent · foot-     pushed SHAs,         traces = a derived
         │             print · dead       head_ref. Deter-     decision. Recency
         │             ends · lineage     ministic only;       supersedes.  S3
         │                  │             silent on            Fingerprints mark
         │                  │             ambiguity.           drift.       S6
         │                  │                  │                     │
         └────────┬─────────┴────────┬─────────┴─────────┬───────────┘
                  ▼                  ▼                    ▼
 SURFACES — inform, never block
 ════════════════════════════════════════════════════════════════════════════════════
   boot brief (v1)            check run section (v1)         console (vNext)
   at session start:          on the existing neutral        session timelines,
   settled-near-your-scope    check run (ADR-0010):          collisions, drift
   with date · reason ·       "reverses derived_decision     dashboards
   origin links · record      d_x (settled DATE because
   since ("held 90d clean"    REASON — source: doc/PR/
   vs "hotfixed twice")       session) — if intentional,
         │                    supersede it"
         │                          │
         ▼                          ▼
 EXPORTS — what the corpus feeds (all vNext, all gated)
 ════════════════════════════════════════════════════════════════════════════════════
   S4  process features → scorer routing     S5  graded session traces → coldworks
       (was the session briefed? did it          (the profiler: recurring subgraphs
       re-walk a recorded dead end? does         across session lineage = hot paths
       its footprint overlap recently            = compilation candidates)
       reverted territory?)
   garden MCP (outcome-loop v1.5): writing agents ask before generating —
   "was this decided? what happened last time?"
```

**The seams, named** — each is a marriage between two things that already exist:

| Seam | Marries | Why it matters |
|------|---------|----------------|
| S1 correlator | session ↔ PR (branch, pushed SHAs, head_ref) | The join nobody else has: process to outcome. Everything downstream rides it. Deterministic only; omits on ambiguous multi-match. |
| S2 decision deriver | rationale traces ↔ committed artifacts | lema's mid-flow capture, kept — but a trace is provenance waiting to attach to a commit, not a draft waiting for approval. |
| S3 outcome annotation | derived decisions ↔ verdict clock | The re-litigation scheduler: "settled, held clean 90d" stays quiet and authoritative; "settled, hotfixed twice since" surfaces itself for reopening, evidence attached. |
| S4 process features | session cards ↔ scorer routing | A feature class competitors structurally cannot copy. Feeds routing, not the frozen reader prompt (ADR-0002). |
| S5 trace export | graded session graphs ↔ coldworks engine | Coldworks' JIT needs execution traces to find hot paths beyond single guards. The session corpus is the tracer. |
| S6 drift | fingerprints ↔ current world | A doc citing code that changed is a mechanically detectable decaying decision. Stale-docs review becomes a Doug finding. |

## 4. The session lane (source B)

**Adapter.** Per-harness, thin, deterministic, no model. Claude Code first — the hook set (SessionStart, PostToolUse, Stop) already exists in lema's repo and lifts over. It emits typed `session_events`:

- `boot { repo, branch, issue_ref?, resumed_from? }` — anchors and lineage. Observed.
- `footprint { entity, role: read|modified|created, at }` — from tool calls. Observed.
- `rationale_trace { kind: choice|dead_end, claim, why, evidence_ref?, at }` — from the agent's own account of a choice or a failed path mid-flow. **Asserted**, and marked so at the wire; `kind` is set by the emitting hook, so the deriver never classifies.
- `checkpoint { next_action?, open_questions?, at }` — on stop. Asserted.

**Typed events, not transcripts.** The adapter never ships session text wholesale. Sessions are full of secrets and half-formed thoughts; footprints and structured moments are cheap, scrubbed, and carry their register in the schema. Doug never has to ask "can I trust this row" — the column answers.

**Ingest.** `POST /sessions/events`, append-only, HMAC'd, same discipline as the webhook path. Idempotent by `(session_id, seq)`.

**Card deriver.** Async, embarrassingly simple in v1: fold events into one `SessionCard` per session — intent (from boot anchors), footprint (top-K by weight), dead ends (`kind: dead_end` traces), loose ends (last checkpoint), lineage (`resumed_from`). No LLM in the derivation path. The card exists to serve S1 and the boot brief, not to be a general API.

**Correlator (S1).** Deterministic joins only: branch name match, pushed commit SHAs, PR `head_ref`. On ambiguous multi-match, no join — silence over speculation (the rule field-tested in lema as d_38f201). A joined pair gives the PR its authoring session(s) and gives the session its outcome.

## 5. The derived decision record

There is no decision entry form, no draft queue, no ruling verbs, no approval state. The record is a **projection over commitments**, enriched with linked exhaust:

- **A derived decision exists when an artifact commits** — a merged PR, a committed architecture doc or ADR file (lane C), a resolved review thread with a stated rationale. Its `authority` is the commitment class (merged code > committed doc > resolved thread), all observed-register.
- **Rationale traces attach as the why.** A session said "going with server-side keys — the in-memory cache resets on deploy"; three days later a PR touching `auth/` merges; the correlator attaches the trace. The reasoning was typed anyway; nobody entered anything. PR bodies and review threads attach the same way (deterministic refs only).
- **Recency supersedes.** A newer commitment touching the same subject supersedes the older derived decision. Both survive in the ledger; the projection points at the winner and keeps the chain walkable.
- **Outcomes annotate (S3).** Every derived decision carries its record since: PRs touching its blast radius, hotfixes, reverts, drift of the code it cites (S6). This is what upgrades "don't re-litigate" from a fence to a scheduler — decisions that are holding stay quiet; decisions that are bleeding surface themselves, evidence attached.
- **Rejections that never commit** ("we ruled out CRDTs") exist only as cited exhaust — advisory standing, honestly labeled: "sessions S3 and PR #123's thread ruled this out because Y; nothing was committed." In an informs-never-blocks system that is the correct epistemic weight for a decision nobody acted on.
- **One human verb survives: in-context dismissal.** Dismissing a wrongly surfaced item where it appears (like dismissing a Doug finding) is an action in the flow of work and the only correction signal the projection needs. The moment dismissals grow a tab in the console, the judgment queue has been rebuilt — that is the line this design exists to hold.

## 6. Surfaces (v1 — two, both informational)

1. **Boot brief.** At session start the adapter injects "settled near your scope": derived decisions whose subjects overlap the session's anchors, each with date, reason, origin links, supersession status, and record-since. Plus honest silence: "nothing recorded near `routes/middleware.ts`." Budget-capped, deterministic ranking (footprint overlap as the candidate gate, then a weighted sum of recency and commitment class — the parent doc's §11.5 formula shape), every line cited.
2. **Check run section.** On the existing neutral check run (ADR-0010 — no new surface): when a diff contradicts a live derived decision, one section: *"reverses d_x — settled 2026-05-02 because Y (source: `docs/arch/webhooks.md`, session S12, PR #88) · held clean 60d. If intentional, this PR supersedes it."* Never a status change, never a block.

**Deferred, with triggers:** `lookup/expand` as agent-facing MCP verbs (folds into the outcome-loop garden when it opens); collision warnings ("session B is modifying your footprint right now" — interval intersection, cheap once cards exist); dead-end re-walk warnings; concept-tier tags for cross-repo problem-shape matching; S4 scorer features (trigger: correlated corpus ≥ a pre-registered N); S5 coldworks export (trigger: coldworks M4 + a graded-trace corpus worth mining).

## 7. Dogfood plan

Own fleet only: doughq, lemahq, coldworks repos, Claude Code adapter, no public-shaped adapter interface until the loop proves itself on us. This fleet is the right test bed — three active repos, heavy agent traffic, and an operator who will notice when the boot brief is wrong.

**Draft success bars — to be locked in a pre-registration before the first event ships (numbers below are proposals, not commitments):**

- **Re-proposal rate.** lema's own record established a 58.3% re-propose baseline (agents re-proposing already-settled directions). Bar: the boot brief cuts it by half on ≥30 sessions, measured by the same predicate.
- **Surfaced-item use.** ≥40% of boot-brief items show downstream evidence of use (footprint touches the cited subject, or the check-run section is never contradicted-then-superseded within the session's PR). Below the floor after 50 sessions → the brief is theater; rework or kill.
- **The token bar.** Brief must beat a token-matched "stuff recent context" baseline on steps-to-first-correct-action (the 2026 budget-controlled finding: charged for their tokens, several memory systems lose to context stuffing).
- **Capture cost: zero.** Count of new human actions this system requires per decision recorded: exactly 0. Any design change that makes it 1 is a regression against the meta-law.

## 8. Honesty contract

- **"Commitment = decision" is a modeling choice, not a truth claim.** Committed code can be wrong; committed docs go stale. The design's answer is grading and drift, not human review — and until the S3/S6 machinery exists, derived decisions are surfaced with dates and origins only, no implied endorsement.
- **Merge-fate is a start, not the verdict.** Revert/hotfix labels are noisy (release mechanics, flags, dep conflicts — see the outcome-loop honesty contract). Richer rungs (deploy health, incident links) join the ladder when observable; nothing in this design pretends otherwise.
- **Asserted material can confabulate.** Rationale traces are the agent's own account. They ride the asserted register, decay unless corroborated by observed commitment, and are never promoted into a derived decision without an artifact to attach to.
- **The brief is a correlation channel.** Agents briefed with the same derived decision are not independent confirmations of it. Any convergence measure must discount brief-derived assertions, or the loop launders its own output into confidence (the mem0 failure mode, systematized).
- **We refuse to claim** "learns from your sessions" until the dogfood bars are met and published; any capture-rate percentage; and any suggestion that surfaced context was *followed* (we can observe use, not obedience).

## 9. Relationship to existing decisions

- **ADR-0006 (Doug does not depend on lema): intact.** Nothing here calls lema. The ledger grammar is adopted as internal schema; lane C is ADR-0006's own decision-provider interface, now also feeding the ledger. If lema-the-product retires, this design is where its load-bearing organs live on: mid-flow capture (as rationale traces), never-re-litigate surfacing (as the boot brief and check-run section), settlement semantics (as the four laws). The judgment queue (lema F17) is deliberately not ported — it is this design's named anti-pattern.
- **ADR-0002 (reader prompt frozen): untouched.** S4 process features feed routing, not the reader prompt.
- **ADR-0010 (surface is a neutral check run): obeyed.** The v1 PR surface is a section on the existing check run.
- **ADR-0007 (deviation is a separate stream): the pattern to follow** when session-derived signals eventually inform verdicts — session context never silently changes a verdict.

**Open questions for the build spec:** retention policy for `session_events` vs. the evidence pinned by derived decisions (lema §5.5's ladder is the starting point); scrubbing rules at the adapter (what patterns never leave the machine); whether `rationale_trace` capture piggybacks lema's existing Stop-hook producer or a new PostToolUse predicate; multi-tenant visibility scopes for session rows (dogfood defers this, tenants cannot); and the S1 correlator's behavior on force-pushes and rebases.
