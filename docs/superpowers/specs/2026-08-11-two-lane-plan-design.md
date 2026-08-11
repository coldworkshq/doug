# Two-lane plan — Lane 0 strike, dashboard parity, and the agent door

Date: 2026-08-11 · Status: APPROVED by Andrew (shape, Lane-2 order, exec loop)
Baseline: origin/main @ `2b56376` (#88)

Evidence base: three research reports at
`workspace/research/two-lane-2026-08-11/` (outside this repo —
`ui-inventory-report.md`, `landscape-report.md`, `lane2-readiness-report.md`).
Every file:line claim in this spec traces to one of them; consult them before
disputing a claim here. They were compiled against this exact baseline.

Verification pass (2026-08-11, controller, by reproduction against this
checkout): LOCKED v8 header · zero `remediat` hits · §2.1 governing rule ·
§12 cadence-only free list + amendment rule + per-row hash stamping ·
ROADMAP "zero adjudications before 2026-08-16" and unchecked Task 7 ·
MCP-garden min-n gate · derangement gate · dashboard no-limit/default-100/
rows.length bug · coverage-math divergence · settle drop functions ·
insert-only save_review + description-match backfill · receipt() + external
exclusion · window_days==14 join · 4000 cap comment · line-free SCHEMA ·
tenancy MCP comment · patterns refuse-to-grow · rf_kamei persists nothing ·
backtest cache on disk · example-pack-enable + LOCKED preflight + hash
one-liner · adjudicator hash refusal · survival FAIL verdict · runbook
exists · design-lock never-writes-code + score() binding · OPERATIONS
deploy-drops-capture. Two citation drifts found in the readiness report
(migrations uniqueness index is ~:186 not :169-171; example-pack-enable case
arm is gcp.sh:857 not :401); neither propagated into this spec.

## 0. Decisions (locked 2026-08-11, do not re-litigate)

1. **Shape**: a small time-critical **Lane 0 strike** this week, then two
   parallel lanes — **Lane 1** tenant dashboard parity, **Lane 2**
   convergence scoring → verdict MCP v0.
   Rejected: skipping Lane 0 (risks the 2026-08-16 prereg window); making
   Lane 2 the spend-router/arbitration product directly (needs customers
   running multiple reviewers + competitor API dependencies; convergence+MCP
   builds the same muscles on our own ledger first).
2. **Lane 1 scope**: bring `web/`'s signed-in dashboard to console quality —
   console design language, real metrics. Extract shared pieces only where
   free. Rejected: unified design system first; console-first.
3. **Lane 2 order**: convergence lands **before** the MCP serves any agent
   fix-loop. The halt signal plus a per-PR read ceiling gate the spend motor
   (every push = new head SHA = new paid read; the 4,000/month cap was sized
   against accidents, not loops — `reader.py:221-230`). A read-only MCP
   preview may ship earlier but must not be consumed in a loop.
4. **Spend policy**: autonomous sub-sessions may run pre-registered paid
   probes up to ~$25/run without checking in. Larger needs Andrew.
5. **Execution loop**: controller session + per-lane worktrees, TDD
   subagents, cold controller verification, mutation proofs on
   honesty/security tests, report-to-file-before-idle, Doug dogfood review
   on every PR. Rejected: lighter reviews (drop per-task reviewers).
6. **Positioning correction** (from landscape): Doug's differentiation claim
   is **post-merge grounding** (reverts/hotfixes/incidents). Incumbents do
   ground pre-merge (author-response proxies). Never again write "they don't
   ground in outcomes"; retire "we catch more bugs" everywhere; the cost
   wedge now has dollar figures ($15–25/PR incumbent deep review vs
   $1–1.50/PR triage-tier competitors).

## 1. Lane 0 — time-critical strike (this week)

Ordered; items 1–2 ride one lock-and-deploy cycle. Items 2–3 are Andrew's
(prod gcloud). Items 1 and 4 are session work.

### 1.1 Prereg v9 disclosure amendment (`remediated_clears`) — before 2026-08-16

The published cleared band already pools two populations: never-flagged PRs
and flagged-then-repaired ones (governing verdict = greatest
`scored_at <= merged_at`, prereg §2.1; PR #49 flipped bands this way). v8 has
no bucket for it (grep `remediat` across docs/ + api/ = zero hits). §2.4
applies this exact standard to `unverdicted_merges` ("an exclusion nobody can
see is a population that can be quietly resized").

- Amend `docs/design/outcome-loop/publication-preregistration.md`: add a
  `remediated_clears` disclosure bucket (count of cleared-governing PRs whose
  earlier verdict on the same PR was flagged, published beside the cleared
  rate, plus their revert count — mirroring the `unverdicted_merges`
  treatment). New dated version, `LOCKED v9`, new hash. Honest note in §12's
  amendment log: this is a disclosure addition, which §12's letter does not
  list as free; it is permitted under the general amendment rule
  (:904-905) and unbounded because only the shrinking direction is
  restricted (:861-864).
- **Why the clock**: `prereg_hash` is stamped per adjudicated row
  (`outcomes.detail`); zero adjudications exist; first due clock is
  2026-08-16 (ROADMAP.md:296-297). Landed before then, no row is ever
  stamped v8 and no permanent two-hash record exists on the flagship repo.
- Data cost: one query at publication time — prior verdicts carry `band` and
  `scored_at` and are append-only (`store.py:791`). No migration.
- Deploy: hash re-pins via the ordinary deploy path (`gcp.sh:607-610`);
  deploy refuses a non-LOCKED doc (`gcp.sh:596-597`).

### 1.2 M3 Task 7 — production 60-day catch-up (Andrew)

The hard gate before the first 14-day publication (ROADMAP.md:317-320).
Runbook: `docs/design/outcome-loop/60-day-backfill-runbook.md`. Known
arrival condition: the v8→v9 hash will already be pinned by the 1.1 deploy —
re-read the runbook's deploy step with that in mind (it predates the hash
self-pinning observed 2026-08-08). Requires pausing the Scheduler and
proving execution quiescence per the runbook.

### 1.3 Enable Example Pack capture (Andrew, one command)

`gcp.sh example-pack-enable` + `DOUG_EXAMPLE_PACK_CAPTURE=1` + sink
(`example_pack_capture.py:82-92`). An ordinary API deploy drops admission
settings (OPERATIONS.md:70-74) — so re-run after any deploy until that is
automated. This starts the only labelled corpus that can ever support a
reader challenger or eval harness. Zero packs exist today.

### 1.4 Run and record `rf_kamei.py`

The RandomForest-on-Kamei-14 baseline is fully built
(`api/scripts/rf_kamei.py`, three splits, bootstrap CIs) but prints to
stdout and its results are recorded nowhere in the repo. Run it against the
on-disk harvest cache (`api/.backtest-cache`, 2.8 GB, present in the main
checkout; zero model spend) and commit the results as a dated doc under
`docs/design/outcome-loop/` (it is the baseline IDEAS says the LLM reader
must beat; until recorded, the reader's cost has no comparator on file).

## 2. Lane 1 — tenant dashboard parity

One autonomous session, own worktree off origin/main. Zero model spend.
North star: `docs/design/outcome-loop/experience.md`'s five surfaces
(built: check run, queue; unbuilt: receipt screen, scoreboard, meter).

### Phase A — correctness before styling

The dashboard has four honesty bugs, each the exact failure class the
console refuses (report §4.1):

1. Silent truncation: `getSessionRuns` sends no `limit`
   (`web/lib/session-api.ts:319`), API defaults to 100 (`api.py:1121`), page
   prints `rows.length` as the total (`dashboard/page.tsx:393`). Fix: send
   `limit=500`, compute at-cap, port the console's `CountLine` semantics
   ("latest 500", never a fake total).
2. Coverage math divergence: web uses `sent_chars/diff_chars`
   (`dashboard-model.ts:48-50`); console uses `files_sent/changed_files`
   (`console/lib/runs.ts:28-35`) with unknown-denominator and rounding
   guards. Adopt the console's semantics wholesale (one shared module).
3. Outcome tone divergence: web maps `revert|hotfix→flag` else neutral;
   console maps `clean→clear`, everything else→flag. ~~Adopt console's.~~
   **SUPERSEDED 2026-08-11 during execution** — the premise (vocabulary
   agreement) was false: production writes `{revert, clean, censored}`
   (adjudicate.py's OutcomeKind; hotfix deliberately never written, §10),
   and the console's binary rule paints `censored` — an UNOBSERVED
   outcome — in the miss colour with the revert glyph. Ruled mapping,
   both surfaces: `clean→clear`, `censored→neutral`, any other non-null
   →flag, null→neutral. Console correction + stale store.py:124 comment
   are a logged follow-up (task list), outside Lane 1 Phase A.
4. Type `RunDetail.pr` (currently `Record<string, unknown>`,
   `session-api.ts:61`) so `changed_files`/`files_dropped`/`author`/
   `head_sha` become renderable; mirror `console/lib/api.ts:62-79`.

Constraint: `web/lib/dashboard-contract.test.mjs` pins exact markup strings
and will break mechanically — rewriting those tests as behavior tests **is
part of Phase A**, not collateral damage. Keep the repo's no-render-test
discipline: logic goes in `lib/` where `node --test` reaches it.

### Phase B — the design-system port

- Port the console's four utility classes into `web/app/globals.css`:
  `.panel`, `.mono` (tabular-nums mandatory on number columns),
  `.data-flag`/`.data-clear` (never a third data colour; iridescent is
  chrome-only — CVD rule documented at `console/app/globals.css:160-196`),
  `.cov-track`/`.cov-fill`. Delete `dashboard.module.css` (186 lines, its
  own duplicate token set).
- Port as-is (pure, tested, framework-free): `search.ts`, `sorting.ts`,
  `paging.ts`, `facets.ts`, `grouping.ts` + `facet-bar` — giving the
  dashboard search, honest facet counts, paging, and the **per-PR verdict
  history accordion** (data already in `/v1/sessions/runs`).
- Port components: `CoverageRuler` (hatched unseen block, budget-cut marker,
  `files_dropped` list), `BandChip` (colour always accompanied by its word),
  `RunSpine`, section-label-with-hairline.
- Free consolidation only (per locked scope): byte-identical `doug-logo.tsx`,
  `utils.ts`, remove web's five unused shadcn components. Do NOT build a
  shared package this pass; copy with a header comment naming the source.

### Phase C — surface what is already built

Ordered by effort-to-value:
1. `finding_counts` — on every list row already, typed on both clients,
   rendered by neither.
2. `source` + `claim_generation` on the evidence pane (console parity).
3. 60-day outcome in list views — `store.run_history` joins only
   `window_days == 14` (`store.py:2231-2240`); add the 60-day join. No
   migration.
4. Tenant-scoped health strip — `/v1/health` already accepts
   `repo`/`installation_id` (`api.py:1178`); the console's global-by-design
   comment does not bind a tenant view. Note
   `dashboard-contract.test.mjs:19` asserts "health" absent — a deliberate
   test change.
5. **Receipt screen** — `GET /v1/prs/{n}/receipt` (`api.py:898`) is the
   richest document in the system with zero consumers: governing vs latest
   verdict, per-window adjudications with the prereg hash stamped at
   adjudication time, read/budget provenance. This is the trust surface the
   landscape report says sells.
6. **Tenant queue page** — `/v1/queue` is complete and session-capable
   (real titles, authors, rationales); web only calls the showcase variant.
7. Spend meter — needs one new read-only endpoint over `deep_read_counters`
   (`store.py:1193`); `experience.md` surface #5 (`deep reads x/200`).
   Pairs with the M3 check-run footer item.

### Phase D — copy honesty (landing)

Apply §0.6: post-merge grounding phrasing, dollar-figure cost wedge, retire
any catch-more-bugs implication. The evidence panel's hardcoded
`0.69/0.67` + "Published miss rate: —" (`web/app/page.tsx:270-298`) stays
honest as-is until the first publication exists; do not fake it forward.

### Lane 1 exit gate

Dashboard renders console-grammar UI with zero contradictions against the
console on identical data (coverage %, outcome tone, counts); the four
Phase-A bugs have regression tests that were proven to discriminate
(mutation: reintroduce each bug, watch the test fail); `npm test` both
workspaces + lint + build green; screenshots attached to the PR for Andrew.

## 3. Lane 2 — the agent door

One autonomous session, own worktree. Design doc first (this section is the
charter, not the design).

### Phase 1 — convergence / finding-diff scoring

Mechanism (picked 2026-08-08): finding-diff only, **no new read** — a pure
function over verdict rows already in the ledger, answering "is this PR
converging?" beside the risk score's "how hard should we look?".

Invariants (each traces to a standing rule):
- **Never enters `score()`** — that is what exempts it from the 2.34× bar
  and ADR-0012 (`design-lock.md:75`). Write a structural test.
- **No new paid read** — consumes existing verdicts only.
- **Three states**: `resolved` / `persisted` / `unknown`; `unknown` reported
  alongside, never folded into a ratio (REVIEWING.md: a claim about an
  absence cannot be settled by looking at the same place the claim came
  from).
- **Coverage-aware**: a finding whose file was cut/unseen/dropped in the
  newer read is `unknown`, never `resolved` (`reads` carries
  `files_unseen`/`file_cut`/`files_dropped`).
- **settle-aware**: `settle.py` drops disproved findings between read and
  write (`settle.py:151`, `:257`) — a finding Doug disproved must not score
  `resolved`. The design must consult settle's drop record (or re-derive
  droppability) before classifying.

The real design work is **finding identity** — it does not exist in the
schema: no line numbers (frozen SCHEMA, `reader.py:84-100` — adding one is
an ADR-0012 experiment, off the table); `category_slug` free-form with a
10-entry canonicalisation map that deliberately refuses to grow
(`patterns.py:9-13`); `findings.file` backfilled by exact
description-match and silently lossy (`store.py:825-838`). De-facto
precedent: the `(category_slug, file)` pair (`llm_probe.py:401-402`); the
only true stable ID in the codebase is the Example Pack's sha256
`finding_id` (`example_pack.py:204-228`) — study it before inventing one.

Pre-registered bars (declare the identity key first, then evaluate on the
multi-round PRs already in the ledger — #49 and #72 are known cases):
1. `resolved` precision ≥ a floor declared in the Phase-1 design note
   *before* evaluation runs, on a hand-labelled sample of
   consecutive-verdict pairs (declaring the floor is a design-note
   deliverable, not a blank to fill later).
2. **Zero** false-`resolved` on any finding whose file was dropped, cut, or
   unseen in the later read (hard bar — the asymmetric failure: wrong
   toward `resolved` tells an agent it is done when it is not).
3. settle-dropped findings never classify `resolved`.
Record slug drift as a covariate (probe measured 276 distinct slugs over
395 findings). Cost: $0 (ledger-only).

Deliverables: design note (identity key + bars, pre-registered before
evaluation) → pure module + tests → evaluation on ledger pairs → surface in
`run_detail`/receipt (a derived field, no migration) — NOT in `score()`.

### Phase 2 — verdict MCP v0 (Reading A only)

Doug ships an MCP server; the customer's agent consumes the verdict and
writes the fix. Reading B (Doug ships the fixing agent) violates
`design-lock.md:76` ("Doug never writes code, never opens a PR, never
blocks") and stays rejected.

- Payload: `store.receipt()` (`store.py:1722`) — score, band, threshold,
  risk score, rationale, head_sha, model, prompt_hash, reasons, deviations,
  coverage — **plus Phase 1's convergence summary**. The band/receipt/
  convergence fields are the differentiation ("me-too" without them —
  landscape report); `raw` stays excluded (`api.py:800-802`).
- Seams already paid for: `tenancy.py:3-6` is FastAPI-free "because its
  consumers are the API and later MCP"; the `scopes` column exists so an
  MCP-only key does not inherit queue access (`api.py:561`,
  `test_api.py:2286`); `architecture.md:144` specifies doug-mcp as its own
  service on the same image.
- Spend controls BEFORE any loop use: per-PR read ceiling (new), and
  convergence gating whether a re-review is bought. The monthly cap
  (`reader.py:230`) is a backstop, not the mechanism.
- Roadmap correction shipped with this phase: split "MCP garden service"
  (gated on adjudicated ≥ min-n — a historical claim needing history) from
  the verdict MCP (serves rows that exist today, no historical claim).
- Known footguns: receipt's `latest_verdict` excludes `tier='external'`
  deliberately (`store.py:1783-1791`); `prereg_hash` comes from the
  per-window stamp in `detail`, never from env (`api.py:850-857`).
- Goodhart note, recorded not solved: the consulting agent is often the
  author-agent; a prior the author can read is a prior it can optimize
  against. v0's exposure is post-hoc verdicts (not the scoring recipe), and
  the main dodge it invites — smaller PRs — is behavior we want (small PRs
  get complete reads). Revisit before any tenant beyond dogfood.
- First user: Andrew's Claude Code sessions reviewing Doug's own PRs.
- v9 (Lane 0) must be locked before the MCP is used in any fix-loop on the
  published repo — the `remediated_clears` bucket is what keeps the
  publication honest once fixes become cheap.

### Lane 2 exit gate

Convergence: all three pre-registered bars pass on ledger pairs, structural
test proves it is absent from `score()`. MCP v0: a Claude Code session on
this repo retrieves the verdict + convergence for a live PR via MCP with an
MCP-scoped key that cannot read the queue; per-PR ceiling enforced by test;
Doug's dogfood review of the PR itself comes back clean or adjudicated.

## 4. Explicitly deferred (with the gate that holds each)

- **Garden probes #2/#3**: probe #1 FAILED its locked bars
  (`survival-probe-1-results.md:3`); PC2 gated on PC1 transfer, PC1 unrun.
  Entry query when reopened: beats 2.34× where `hotspot_path` doesn't fire.
- **Intent probe v2**: ROADMAP.md:460 — derangement positive control must
  pass first; until then the stream is UNBELIEVED while burning >half of
  input tokens (a keep-or-kill decision, not a build item).
- **Reader prompt v2**: ADR-0012 freeze; needs a pre-registered experiment
  against the 653-PR corpus whose re-run Andrew already declined.
- **Distillation step 4 (outcome join)**: denominator is zero adjudicated
  rows until ≥ 2026-08-16, realistically months.
- **LangGraph / Temporal**: rejected — the Postgres queue is the durable
  layer. Watch item: Claude Agent SDK, if the reader ever becomes
  multi-step adaptive investigation.
- **Spend router / cross-reviewer arbitration as products**: the strategic
  prize (landscape opportunities #1/#3); revisit once convergence + MCP
  exist and a design partner runs ≥2 reviewers.

## 5. Execution loop (approved)

- **Controller session** (this one): plans, dispatches, verifies, keeps
  HANDOFF.md and the SDD ledger current at every decision.
- **Per-lane worktrees** off origin/main; lanes touch disjoint areas
  (Lane 1: web/, console/, small api read paths; Lane 2: api/, docs/).
  The one shared file is `store.py` — changes to it ship as small separate
  PRs, coordinated by the controller.
- **TDD subagents** per task; per-task reviewers retained.
- **Cold verification**: the controller re-runs pytest/ruff/npm
  test/lint/build itself; implementer and reviewer reports are claims, not
  evidence. (History: every substantive defect on the last branch was
  caught by controller mutation testing, not by reviewers.)
- **Mutation proofs**: any test guarding honesty/security behavior is
  proven to discriminate by reintroducing the bug and watching it fail;
  clear `__pycache__` between weaken and restore.
- **Report-to-file-before-idle**: every subagent writes its
  report/ledger to a file before finishing (2026-08-11 measurement: 3 of 3
  research agents went idle without delivering until nudged; one nudge
  recovered each).
- **Review chain per PR**: `/code-review` before push → CI → Doug's own
  review (findings verified by reproduction, adjudicated into
  `docs/findings-log.jsonl` — append-only, compact separators) → Andrew
  merges. `/code-review ultra` remains Andrew's trigger.
- **Spend**: pre-registered probes ≤ ~$25/run autonomous; larger asks
  Andrew. Lane 1 spends $0; Lane 2 Phase 1 spends $0.

## 6. Sequencing

```
Week of 08-11:  Lane 0.1 v9 amendment  ──┐ (must land before 08-16)
                Lane 0.4 RF record        │
                Lane 0.2 Task 7 (Andrew) ─┴─ same lock-and-deploy cycle
                Lane 0.3 capture enable (Andrew)
Then, parallel: Lane 1 Phase A → B → C → D     (session A)
                Lane 2 Phase 1 → Phase 2        (session B)
Controller: dispatch, verify, integrate; store.py changes serialized.
```
