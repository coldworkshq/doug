# Review Quality Contract Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile Doug's selective-agent and outcome-loop documents with the verified instrument-identity, experimental-unit, causal-evaluation, and statistical-decidability contracts.

**Architecture:** This is a documentation-only correction. The selective-agent addendum will define the complete reviewer as a whole instrument, split silent paired review-quality evaluation from later surfaced causal evaluation, and make PR the primary unit. Existing product and roadmap copy will defer outcome-rate legibility to the locked two-sided Wilson rule in `publication-preregistration.md` instead of the withdrawn `N >= 30` heuristic, while the Sentry-specific `2.34x` result remains evidence rather than a universal gate.

**Tech Stack:** Markdown, Git, ripgrep, existing Python/Node test suites.

## Global Constraints

- Do not change runtime code, schemas, APIs, or production behavior.
- Preserve `publication-preregistration.md` section 8 as the authoritative locked outcome-rate decidability contract.
- Preserve `N >= 30` in the preregistration's historical explanation of the withdrawn v1 rule.
- Preserve the Sentry `2.34x` observation as historical evidence; remove only its use as a universal promotion gate.
- Keep silent paired review-quality evidence distinct from a later opt-in randomized surfaced-policy experiment.
- Treat PR as the primary evaluation unit; findings remain nested evidence within a PR.
- Treat `prompt_hash` as a component receipt, never the whole-instrument identity.

---

### Task 1: Correct the selective-agent experiment contract

**Files:**
- Modify: `docs/design/outcome-loop/addendum-agentic-architecture.md:13-33`

**Interfaces:**
- Consumes: the current `prompt_hash`, shadow-challenger, evidence-refinery, and specialist-panel rulings.
- Produces: the normative definitions of `instrument_id`, silent paired evaluation, surfaced causal evaluation, PR-level analysis, and panel promotion evidence.

- [x] **Step 1: Replace the universal `2.34x` gate with a repository-specific evidence rule**

  Keep the `hotspot_path` result as a warning about portability. State that new candidates require preregistered practical margins, uncertainty, and temporal/repository holdouts appropriate to the named claim; no historical multiplier automatically promotes a different instrument.

- [x] **Step 2: Define whole-instrument identity**

  Replace the claim that `prompt_hash` segments instrument eras with this contract:

  ```text
  prompt_hash is one component receipt. A whole instrument includes the model snapshot and inference parameters; prompt and output schema; input budget and ordering; Context Pack schema, retriever, and selection policy; tools; orchestration graph and roles; runtime commit; fallback policy; and publication policy. Any change creates a new instrument era and cannot silently inherit historical evidence.
  ```

- [x] **Step 3: Split silent quality evaluation from surfaced causal evaluation**

  State that silent challengers run on the same frozen PR snapshot and can establish blinded review quality, calibration, cost, latency, and reliability. State that they cannot establish the causal effect of surfacing because only the surfaced review can change the code, merge decision, or reviewer effort. Reserve causal outcome claims for a later opt-in randomized experiment that surfaces exactly one assigned instrument per PR and analyzes intention-to-treat.

- [x] **Step 4: Make PR the primary unit and correct the specialist-panel gate**

  Replace the current `panel-on-flagged-band ... outcome capture` bar with a first-stage paired shadow bar: the panel must beat a compute-matched grounded single reader on a preregistered PR-level validated-yield endpoint, without violating false-positive, cost, latency, or reliability constraints. Findings are nested within PRs and never count as independent sample units. A later surfaced randomized canary is required before claiming the panel changes downstream outcomes.

- [x] **Step 5: Review the addendum diff**

  Run:

  ```bash
  git diff --check
  git diff -- docs/design/outcome-loop/addendum-agentic-architecture.md
  ```

  Expected: no whitespace errors; the addendum contains the four corrected contracts and no longer says `prompt_hash` segments whole instruments, shadow outcomes promote a silent challenger causally, or `2.34x` is a universal gate.

### Task 2: Reconcile locked product copy with the current statistical contract

**Files:**
- Modify: `docs/design/outcome-loop/design-lock.md:40-85`
- Modify: `docs/design/outcome-loop/product-spec.md:17-23`
- Modify: `docs/design/outcome-loop/experience.md:17-17,76-80`
- Modify: `docs/design/outcome-loop/ROADMAP.md:329-335,448-456`
- Reference only: `docs/design/outcome-loop/publication-preregistration.md:622-664`

**Interfaces:**
- Consumes: the locked rule that publishes on schedule at any N and labels a repo/window rate decidable only when its two-sided Wilson 95% interval excludes that repo/window's historical base rate.
- Produces: consistent install projection, scoreboard copy, open-risk wording, roadmap trigger, and specialist-panel trigger.

- [x] **Step 1: Replace `N >= 30` customer projections**

  Across the design lock, product spec, experience brief, and roadmap, use the following meaning:

  ```text
  first adjudication lands on a projected date; outcome rates publish on schedule at any N; a rate becomes decidable only when the preregistered two-sided interval excludes the repo/window base rate, and the projection may remain undecidable for months.
  ```

  Replace `below our floor — this is a rumor` with the locked phrase `not yet decidable — a count, not a rate`.

- [x] **Step 2: Correct the locked design's historical gate language**

  Change the garden rule so the Sentry `2.34x` result is a repository-specific comparator, not a universal promotion threshold. Require new temporal and repository holdouts, a named practical margin, and uncertainty for the candidate instrument.

- [x] **Step 3: Correct the roadmap's specialist-panel trigger**

  Change the M6 trigger from `beats single-read on flagged-band outcome capture` to a preregistered paired PR-level review-quality gate against a compute-matched grounded reader, followed by a separate surfaced canary before downstream causal claims.

- [x] **Step 4: Preserve withdrawn-rule history**

  Confirm that `publication-preregistration.md:626` still records `v1 proposed N >= 30` as withdrawn history. Do not remove or rewrite that evidence.

- [x] **Step 5: Review the cross-document diff**

  Run:

  ```bash
  git diff --check
  git diff -- docs/design/outcome-loop/design-lock.md docs/design/outcome-loop/product-spec.md docs/design/outcome-loop/experience.md docs/design/outcome-loop/ROADMAP.md
  ```

  Expected: all live customer and roadmap copy defers to the preregistered decidability rule; the only remaining `N >= 30` occurrence is the preregistration's withdrawn-history paragraph.

### Task 3: Prove the correction is complete and regression-safe

**Files:**
- Verify: `docs/design/outcome-loop/*.md`
- Verify: repository test suites

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: a contradiction scan, Markdown integrity evidence, and unchanged runtime-test evidence.

- [x] **Step 1: Run the stale-claim scan**

  Run:

  ```bash
  rg -n 'N[[:space:]]*(≥|>=)[[:space:]]*30|2\.34(x|×) disjoint-population bar|prompt_hash segments rates by instrument version|panel-on-flagged-band beats single-read-on-flagged-band on outcome capture|below our (pre-registered )?floor|this is a rumor|rate worth reading|publish(es)? (at every N|after every)' docs/design/outcome-loop
  ```

  Expected: no live-contract matches. The historical withdrawn-rule wording in `publication-preregistration.md` may match only if the Unicode spelling is broadened deliberately; it must remain.

- [x] **Step 2: Run the required-contract scan**

  Run:

  ```bash
  rg -n 'whole instrument|component receipt|primary.*PR|paired|intention-to-treat|not yet decidable|two-sided|compute-matched|repository holdout|temporal holdout' docs/design/outcome-loop
  ```

  Expected: the new addendum and corrected product documents make every approved contract discoverable.

- [x] **Step 3: Run repository verification**

  Run:

  ```bash
  make test
  git diff --check
  git status --short
  ```

  Expected: 934 API tests, 93 console tests, and 4 web tests pass; no whitespace errors; only the plan and approved outcome-loop documents are changed.

- [x] **Step 4: Address independent review findings**

  Name the historical 30,000-character original-order configuration anywhere the AUC 0.687/0.668 result appears, explicitly distinguish the unmeasured shipped reader, remove the last dated "rate worth reading" promise, use "on schedule at any N," and broaden the stale-claim scan to cover Unicode and semantic variants.

- [x] **Step 5: Commit the PR-sized change**

  ```bash
  git add docs/superpowers/plans/2026-08-09-review-quality-contract-corrections.md docs/design/outcome-loop/addendum-agentic-architecture.md docs/design/outcome-loop/design-lock.md docs/design/outcome-loop/product-spec.md docs/design/outcome-loop/experience.md docs/design/outcome-loop/ROADMAP.md
  git commit -m "docs: correct review quality experiment contracts"
  ```

  Expected: one documentation-only commit whose message names the contract correction rather than implying a production behavior change.
