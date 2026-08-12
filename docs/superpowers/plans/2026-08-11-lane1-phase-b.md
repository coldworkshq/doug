# Lane 1 Phase B — design-system port (EXPANSION to execution standard)

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.
> Steps use checkbox (`- [ ]`) syntax. This file expands **Phase B** of
> `docs/superpowers/plans/2026-08-11-lane1-dashboard-parity.md` (branch
> `docs/two-lane-plan-2026-08-11`, worktree `repo/.worktrees/research-main`) per that
> plan's **Expansion protocol**. Phase A is merged as #90. Spec §2 is
> `docs/superpowers/specs/2026-08-11-two-lane-plan-design.md:156-174`.

**Baseline:** origin/main @ `ffc0d27`. Worktree `.worktrees/lane1-phaseb`, branch
`lane1-phase-b`. `npm ci` already run at the REPO ROOT (npm workspaces — `web/` has no
lockfile of its own).

**Goal:** the signed-in dashboard renders in the console's design grammar, with the
console's pure logic modules underneath it, and contradicts the console nowhere.

---

## Grounding pass — what changed since the parent plan was written

Every claim below was re-verified against live code at `ffc0d27` before this expansion was
written. **Four of the parent plan's Phase-B requirements are wrong or incomplete as
stated.** They are corrected here, not silently adapted.

### D1. `.panel` already exists in `web/app/globals.css` — the port is a reconcile, not an add

`web/app/globals.css:226-229` already defines `.panel` with declarations byte-identical to
`console/app/globals.css:162` (`background: var(--card); border: 1px solid var(--border)`).
Its comment (`:221-225`) additionally documents that `/queue` and the loading skeleton use
`.glass` because they are forced dark. So requirement 1's list of six utilities is really
**five to add** (`.mono`, `.data-flag`, `.data-clear`, `.cov-track`, `.cov-fill`) plus one
to leave alone and cross-reference.

### D2. The dashboard is a deliberate **light-paper island**; web has a live dark toggle

`web/app/dashboard/dashboard.module.css:1-17` opens `.console { --paper: #fcfcfa; … }` —
its own private token set, deliberately NOT web's. `web/lib/dashboard-contract.test.mjs:50`
pins `css.includes(":global(.dark)") === false` under the test name *"the signed-in console
stays on the reference light paper surface"*. Meanwhile web ships a real theme toggle
(`web/components/theme-toggle.tsx`, `theme-provider.tsx`, `@custom-variant dark
(&:is(.dark *))` at `globals.css:5`) and a full `.dark` palette at `globals.css:108-164`.
Console's own `.dark` block is inert by design (`console/app/globals.css:89-93`: *"Nothing
in the console adds a 'dark' class to `<html>`"*).

**Therefore:** deleting `dashboard.module.css` and rebuilding on globals utilities makes the
dashboard follow web's dark toggle for the first time. That is a behavior change the parent
plan never names, and it collides with a pinned intent. It needs a ruling before any commit
— see **RULING 1**. Two of the ported utilities make this concrete: `.cov-track`/`.cov-fill`
are hardcoded light hex (`#eceae3` / `#3d403c`, `console/app/globals.css:177-178`) and
`RunSpine` hardcodes `#3d403c` / `#c9c6bd` (`console/components/run-spine.tsx:18-20`).

### D3. The pure modules pull **more of `console/lib/runs.ts` than Phase A ported**

Phase A copied only the coverage half of `console/lib/runs.ts` into `web/lib/coverage.ts`.
But `console/lib/sorting.ts:3` imports `{ coveragePercent, parseUtc }` from `./runs.ts`,
`console/lib/grouping.ts:7` imports `{ parseUtc }`, and `console/components/run-spine.tsx:2`
imports `{ jobDuration, utcClock, utcShortDate }`. `parseUtc` carries a load-bearing
docstring: run_history timestamps cross the wire **with no zone designator**, so
`new Date(iso)` reads them as server-local and on a UTC-behind server every row's "then"
lands after "now". Porting the modules without it silently mis-sorts and mis-ages every row.
This is its own task (**B2**), not a footnote of the module port.

### D4. Console's facet bar is **client state**; web's dashboard is **server + URL state**

`console/components/facet-bar.tsx:1` and `console/components/runs-table.tsx:1` are
`"use client"`. `web/app/dashboard/page.tsx` has no `"use client"` — it is a server
component reading `searchParams`, and it advertises the property in its own count line:
*"filters live in the URL"* (`page.tsx:393`, shipped in #90). Copying the facet bar verbatim
would move filter state into client memory and silently retire a shareable-URL property the
page currently claims in prose. Needs **RULING 2**.

### D5. Name collision: two different `filterRuns`

`web/lib/dashboard-model.ts` exports `filterRuns` (repo/band/low-coverage, URL-driven) and
`console/lib/facets.ts:123` exports a *different* `filterRuns` (facet selection). Porting
verbatim into `web/lib/facets.ts` and importing both into `page.tsx` is a compile error at
best and a silent wrong-function-called at worst. The port renames the incoming one
`filterRunsByFacets` and records why in a header comment.

### D6. Smaller corrections
- `console/lib/search.ts:1` also imports `JobItem` (the console's jobs page type). Web has
  no jobs surface; the port drops the job-search export rather than inventing the type.
- `web/lib/session-api.ts`'s `RunSummary` is **already field-for-field identical** to
  `console/lib/api.ts:36-55`'s (Phase A did this). The modules therefore port with no shape
  work — this is the one parent-plan assumption that held.
- `web/components/ui/` holds **six** shadcn files (badge, button, card, chart, slider,
  table), not five; `chart.tsx` is reachable from `score-strip.tsx` (landing). The "five
  unused" claim is restated as: delete exactly those proven unreferenced by grep, and say in
  the report which and why — never a fixed count.

---

## RULINGS — SIGNED OFF BY ANDREW 2026-08-11. Do not re-litigate.

- **RULING 1 — dashboard theme: STAYS PINNED LIGHT-PAPER.** The signed-in dashboard does
  NOT follow web's toggle. The port scopes the dashboard subtree to the console's light
  tokens in `globals.css` (~15 lines replacing the module's 185). The `:48` pin's intent
  ("the signed-in console stays on the reference light paper surface") is **preserved**, and
  B5 additionally pins that the subtree does not inherit `.dark`. Rejected: theme-aware —
  it would require inventing dark values for the coverage ramp (`#eceae3`/`#3d403c`) and
  RunSpine's nodes, which is a new design decision rather than a port, and it reopens CVD
  separation on a surface where it was never measured.
- **RULING 2 — filter state: URL / SERVER.** The facet bar is adapted, not copied: a server
  component emitting `<Link>`s via the page's existing `href(params, changes)` helper, with
  selection parsed from `searchParams` by a pure, tested function in `lib/`. The page keeps
  its "filters live in the URL" property and gains no client island. Rejected: copying
  console's client components verbatim — filter state would leave the URL and the page's own
  shipped prose would become false.
- **RULING 3 — TWO PRs.**
  - **PR 1 — foundations (invisible):** B1 utilities · B2 runs-time · B3 pure modules ·
    B4 components · B7 consolidations. Additive, fully unit-tested, no visual change.
  - **PR 2 — the rebuild (visible):** B5 chrome rebuild + pin rewrites · B6 wiring ·
    B8 exit-gate evidence. Opened after PR 1 merges; rebase first.

---

## Global constraints (inherited; violations are defects)

- Tests live in `web/lib/*.test.mjs`, run by `npm test --workspace=web`. Logic goes in
  `lib/` where tests reach it. **NO component render tests** (house rule).
- `web/lib/dashboard-contract.test.mjs` pins source strings. A task that breaks a pin
  **rewrites it in the same commit**, with the new pin asserting the new behavior and
  preserving the old pin's INTENT. Never delete a pin without replacing it.
- Every behavior a test guards gets a **mutation proof**: reintroduce the defect, watch the
  named test fail, restore, watch it pass. Record the failing assertion's line.
- Ported files carry a header comment naming the source path. **No shared package this
  pass** (locked decision).
- Web is a NEW Next.js — read `node_modules/next/dist/docs/` before using any API learned
  elsewhere (`web/AGENTS.md`).
- Do NOT change any `/v1/sessions/*` response shape in this phase. Phase B needs none.
- Report to file before idle: `.worktrees/lane1-phaseb/PHASEB-REPORT.md`.
- Controller re-runs cold after each task: `npm test --workspace=web && npm test
  --workspace=console && npm run lint --workspace=web && npm run build --workspace=web`.
- Known pre-existing flake: the full-glob web run intermittently fails
  `lib/auth-entry.integration.test.mjs` (task #8, separate branch). If it appears, say so
  and re-run scoped; never "fix" it here.

---

### Task B1: Port the console's utilities into `web/app/globals.css`

**Files:** Modify `web/app/globals.css`. Test: `web/lib/design-system.test.mjs` (new).

**Interfaces:** adds `.mono`, `.data-flag`, `.data-clear`, `.cov-track`, `.cov-fill` (and
`.evidence-seam`/`.evidence-step` only if B6 needs them — do not port unused CSS).

- [ ] **Step 1: Re-read the source and the receiver.** `sed -n '160,196p'
  console/app/globals.css` and `sed -n '194,236p' web/app/globals.css`. Confirm D1 (`.panel`
  already present, identical declarations) still holds; record the live line numbers in
  PHASEB-REPORT.md. If `.panel`'s declarations have diverged, STOP — that is a
  console/web contradiction to surface, not to overwrite.

- [ ] **Step 2: Write the failing contract test** (`web/lib/design-system.test.mjs`), reading
  `../app/globals.css` with `readFile` (same style as `dashboard-contract.test.mjs`).
  Assert, each with the intent in a comment:
  - `.mono` declares `font-variant-numeric: tabular-nums` — *number columns must align at
    34px rows*;
  - `.data-flag` uses `var(--flag)` and `.data-clear` uses `var(--clear)`, and **no third**
    `.data-*` class exists (regex-count the `.data-` selectors — the never-a-third-colour
    rule made mechanical);
  - `.cov-fill` / `.cov-track` reference **neither** `var(--flag)` nor `var(--clear)` —
    *coverage is a magnitude, not a judgement*;
  - `--iridescent` appears in no `.data-*` rule — *chrome never becomes a data verdict*
    (the CVD rule at ΔE 6.1);
  - the CVD comment text itself survives the port (match a distinctive substring).

- [ ] **Step 3: Run — expect FAIL** (`npm test --workspace=web -- lib/design-system.test.mjs`
  style scoping; the classes do not exist yet). Paste the RED output into the report.

- [ ] **Step 4: Implement.** Append the five utilities to web's existing `@layer utilities`
  block **with their comments copied verbatim** (they are the spec, not decoration), plus a
  one-line header naming `console/app/globals.css` as the source. Leave `.panel` untouched;
  add one line to its comment noting the console's copy is the twin.

- [ ] **Step 5: Run — expect PASS.** Then **mutation proof**: change `.cov-fill` to
  `background: var(--flag)`, re-run, confirm the coverage-is-not-a-judgement assertion is the
  one that fails; restore. Paste both. Repeat for the third-data-colour count (add a
  throwaway `.data-warn`) — that assertion must be the one that fails.

- [ ] **Step 6: Verify + commit.** Full verify command above.
  `style(web): port the console's data utilities into globals, comments and all`

---

### Task B2: Port the time/provenance half of `console/lib/runs.ts`

**Files:** Create `web/lib/runs-time.ts`; test `web/lib/runs-time.test.mjs`. (Do NOT widen
`web/lib/coverage.ts` — its header pins it as a verbatim mirror of the coverage half.)

**Interfaces:** `parseUtc`, `relativeAge`, `utcDate`, `utcShortDate`, `utcClock`,
`utcTimestamp`, `jobDuration` — signatures identical to `console/lib/runs.ts`. Port only
what B3/B5 actually consume; list what you skipped and why.

- [ ] **Step 1:** `grep -n "export function" console/lib/runs.ts` and record each symbol's
  live line range. Then `grep -rn "from \"@/lib/runs\"\|from \"./runs" console/` to see which
  callers need which — that set is your port list.
- [ ] **Step 2:** Copy the corresponding tests out of `console/lib/runs.test.mjs` FIRST into
  `web/lib/runs-time.test.mjs` (imports repointed to `./runs-time.ts`). Run → FAIL (module
  missing). Paste RED.
- [ ] **Step 3:** Copy the implementations **with their docstrings verbatim** (`parseUtc`'s
  zoneless-timestamp docstring is the whole reason this task exists) under a header comment:
  `// Ported verbatim from console/lib/runs.ts — keep the two in lockstep.` Run → PASS.
- [ ] **Step 4: Mutation proof.** Replace `parseUtc(iso)` with `new Date(iso)` inside
  `relativeAge`. The zoneless test MUST fail. Restore. Paste the failing assertion. If no
  ported test discriminates that, the port is untested — **write the test that does before
  moving on**.
- [ ] **Step 5:** Verify + commit. `feat(web): port the console's UTC parsing and age
  formatting, docstrings intact`

---

### Task B3: Port the pure modules

**Files:** Create `web/lib/search.ts`, `sorting.ts`, `paging.ts`, `facets.ts`, `grouping.ts`
+ the five matching `*.test.mjs`. Modify nothing else.

**Interfaces:** exports identical to console's, **except** `facets.filterRuns` →
`filterRunsByFacets` (D5). Types come from `web/lib/session-api.ts` (`RunSummary` is already
identical — D6), NOT from a copied `api.ts`.

- [ ] **Step 1: Prove the type identity before porting, don't assume it.** Diff
  `console/lib/api.ts:36-55` against `web/lib/session-api.ts`'s `RunSummary` field by field
  and paste the result. Any field console's modules read that web's rows lack is a **STOP** —
  it would need the two-step web-first validator protocol and an api PR, which is out of
  Phase B's scope.
- [ ] **Step 2:** Port test files first, one module at a time, in dependency order:
  `paging` → `search` → `facets` → `grouping` → `sorting` (sorting depends on grouping and
  runs-time). Repoint imports; keep every test name and comment. Run → FAIL. Paste RED counts
  per module.
- [ ] **Step 3:** Port each implementation with a source-path header comment, keeping all
  docstrings. Run → PASS with the SAME test count as console's file (state both numbers; a
  lower count means you dropped a test).
- [ ] **Step 4:** Rename `filterRuns` → `filterRunsByFacets` in the ported `facets.ts` + its
  tests, with a header comment naming the collision with `dashboard-model.ts`'s `filterRuns`.
- [ ] **Step 5: Mutation proof, one per module**, targeting each module's honesty property —
  at minimum: facets' cleared/clean distinction comment (`facets.ts:51`) and grouping's
  at-cap handling (`groupRunsByPr(runs, atCap)` — a group assembled from a capped page must
  not claim completeness). Reintroduce each defect, name the failing test, restore.
- [ ] **Step 6:** Verify + commit (one commit per module is fine and preferred for review).
  `feat(web): port the console's search/sorting/paging/facets/grouping modules with tests`

---

### Task B4: Port the components

**Files:** Create `web/components/coverage-ruler.tsx`, `band-chip.tsx`, `run-spine.tsx`.

- [ ] **Step 1:** Read all three console sources in full plus every Tailwind token they use.
  Record which read fields web's rows lack (expect none after B3 Step 1) and which hardcode
  light-only hex — those are RULING 1's dependents; do not invent dark values without it.
- [ ] **Step 2:** Copy with source-path header comments, repointing type imports to
  `@/lib/session-api` and helpers to `@/lib/runs-time`. Keep BandChip's docstring verbatim —
  *"the colour is ALWAYS accompanied by its word"* is the CVD secondary encoding.
- [ ] **Step 3:** No render tests (house rule). Instead extend `web/lib/design-system.test.mjs`
  with source pins that encode the two rules a future edit would break: BandChip renders the
  word in both branches (never a bare dot/swatch), and CoverageRuler's cut marker does not use
  `var(--flag)` (the same intent `dashboard-contract.test.mjs:60-61` pins today for the CSS
  module). Run RED → implement → GREEN → mutation-proof each by deleting the word / swapping
  the marker colour.
- [ ] **Step 4:** Verify + commit. `feat(web): port CoverageRuler, BandChip and RunSpine`

---

### Task B5: Rebuild the dashboard chrome; delete `dashboard.module.css`

**Blocked on RULING 1.** This is the visible task and the one that breaks pins.

**Files:** Modify `web/app/dashboard/page.tsx`, `web/app/globals.css` (surface scope, if
RULING 1 = pinned-light); Delete `web/app/dashboard/dashboard.module.css`; Modify
`web/lib/dashboard-contract.test.mjs`.

- [ ] **Step 1: Inventory before editing.** `grep -o "styles\.[a-zA-Z]*"
  web/app/dashboard/page.tsx | sort | uniq -c` and list every class with its region. Confirm
  every class in the module is either used by page.tsx or dead; list the dead ones separately
  (they are deleted, not translated).
- [ ] **Step 2: Rewrite the four affected pins FIRST**, in this commit, before the markup
  changes — so the suite is RED for the right reason and you can watch it go green:
  - `:12` — `assert.match(page, /coverageRuler/)` becomes an assertion that the ruler
    component is rendered (intent: *the reader's coverage is on screen*); `page.includes
    ("health") === false` and the `"tenant all"` / `"illustrative"` pins stay as they are.
  - `:48` — *"stays on the reference light paper surface"*: rewrite against the new surface
    per RULING 1. If pinned-light, pin the scope block (`--paper: #fcfcfa` and the 1440px
    canvas) in `globals.css` and additionally pin that the dashboard subtree does not inherit
    `.dark`. If theme-aware, this pin's intent CHANGES and the new pin must say so out loud
    in a comment — that is a deliberate, ruled change, not a silent deletion.
  - `:55` — the cut-marker-is-not-flag, `.outcomeClear/.outcomeFlag/.outcomeNeutral` token
    pins, and the `:focus-within` ring: re-pin each against the new classes. The
    three-outcome-tone classes must survive in some form — they encode the ruled three-way
    tone rule (`clean`/`censored`/other) from #90.
  - `:69` — the `connectRepositories` markup string: re-pin the *reachability* intent (connect
    action appears before the state branches, in every state), not the literal class name.
- [ ] **Step 3:** Run → RED, with failures ONLY in the rewritten pins. Paste.
- [ ] **Step 4:** Rebuild region by region (bar → filters → table → evidence pane), Tailwind +
  the B1 utilities, committing per region if it helps review. Delete the module file in the
  same commit as the last region. **Behavior must not change**: same server component, same
  `searchParams` reads, same server actions, same links (`prefetch={false}` on both
  `/install/start` links — `:83` pins it).
- [ ] **Step 5:** Run → GREEN. Then mutation-proof the two honesty pins that matter most:
  make the cut marker `var(--flag)`, watch the named test fail; restore. Remove the neutral
  outcome class, watch the tone pin fail; restore.
- [ ] **Step 6:** `npm run build --workspace=web` and confirm the dashboard route still
  builds as a server route (no accidental client boundary). Commit.
  `refactor(web): rebuild the dashboard on the console's design grammar`

---

### Task B6: Wire facets, search, paging, and the per-PR accordion

**Blocked on RULING 2.**

- [ ] **Step 1:** Decide nothing here — implement the ruled model. If URL-state: the facet
  bar is a server component emitting `<Link>`s built by the existing `href(params, changes)`
  helper (`page.tsx:35`), and selection is parsed from `searchParams` by a pure function in
  `lib/` that gets its own tests. If client-state: one client island, and the count line's
  *"filters live in the URL"* prose must change in the same commit — it would otherwise
  become false.
- [ ] **Step 2:** Tests first, in `lib/` (parse selection from params → `FacetSelection`;
  round-trip a selection back to a query string; grouping at-cap behavior through the page's
  own call site). RED → implement → GREEN.
- [ ] **Step 3:** Mutation proof: drop a facet key from the parser, watch the round-trip test
  fail. Restore.
- [ ] **Step 4:** Verify + commit. `feat(web): dashboard gains the console's facets, search
  and per-PR history`

---

### Task B7: Free consolidations only

- [ ] **Step 1:** `diff web/components/doug-logo.tsx console/components/doug-logo.tsx` and
  the same for `utils.ts`; paste both. Byte-identical → unify per the parent plan (web's path
  wins; **console's import stays untouched — console keeps its own copy this pass**).
  Not identical → do NOT unify; record the diff and move on.
- [ ] **Step 2:** For each file in `web/components/ui/`, `grep -rn "components/ui/<name>"
  web/ --include=*.tsx --include=*.ts` and delete only those with zero references. Paste the
  grep evidence per file. Do not assume the count is five (D6).
- [ ] **Step 3:** `npm run build --workspace=web` must still pass. Commit.
  `chore(web): remove unreferenced shadcn components and duplicate helpers`

---

### Task B8: Exit-gate evidence

- [ ] Screenshots of all four dashboard states (no-connection, choose, ready-with-runs,
  evidence pane open) via the `run` skill, attached to the PR.
- [ ] A side-by-side contradiction check on identical data: coverage %, outcome tone, and
  run counts must read the same on console and dashboard. Any disagreement is a Phase-B
  failure, not a follow-up.
- [ ] `npm test` both workspaces + lint + build, run cold by the controller.
- [ ] `/code-review` before push; findings adjudicated into `docs/findings-log.jsonl`.
- [ ] **Multi-agent review + adversarial pass (Andrew, 2026-08-11):** once the design lane
  is done, run a fan-out review over the whole lane — independent finders per dimension,
  then an adversarial verification round that tries to REFUTE each finding before it counts.
  Applies to the lane as a whole, not per-PR; the per-PR `/code-review` above still happens.
  (`/code-review ultra` remains Andrew's own trigger and is not a substitute.)
