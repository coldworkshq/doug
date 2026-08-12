# Lane 1: Tenant Dashboard Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `web/`'s signed-in dashboard to console quality — fix its four honesty bugs, port the console's design grammar, surface built-but-invisible metrics.

**Architecture:** Phase A (Tasks 1–4, stepped below) fixes correctness with zero visual redesign. Phases B–D are SPECIFIED, NOT STEPPED — expand each to Phase A's standard one at a time, just before executing it (this repo's plan-defect history is why; see "Expansion protocol").

**Tech Stack:** Next.js 16 (web/), TypeScript, `node --test --experimental-strip-types` for `web/lib/*.test.mjs`, Tailwind v4 (Phase B+).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-two-lane-plan-design.md` §2. Baseline origin/main @ `2b56376`.
- Worktree: `git -C /Users/andrew/Projects/doughq/repo worktree add .worktrees/lane1 -b lane1-dashboard-parity origin/main`, then `npm ci` at the REPO ROOT (npm workspaces — web/ has no lockfile of its own).
- Tests live in `web/lib/*.test.mjs` and run via `npm test --workspace=web`. Logic goes in `lib/` where tests reach it; NO component render tests (house rule).
- `web/lib/dashboard-contract.test.mjs` pins source strings. A task that breaks a pin updates that pin IN THE SAME COMMIT, with the new pin asserting the new behavior — never delete a pin without replacing it.
- Every regression test added for a Phase-A bug gets a MUTATION PROOF step: reintroduce the bug, watch the test fail, restore, watch it pass.
- Web is a NEW Next.js — read `node_modules/next/dist/docs/` before using any API you learned elsewhere (web/AGENTS.md rule).
- Report-to-file before idle: `.worktrees/lane1/LANE1-REPORT.md`.
- Verification the controller re-runs cold after each task: `npm test --workspace=web && npm run lint --workspace=web && npm run build --workspace=web`.
- Do NOT change any `/v1/sessions/*` response shape in this lane without the two-step validator protocol (Phase C notes) — web's exact-key validators treat any drift as an outage.

---

### Task 1: Honest run-ledger cap (bug A1)

**Files:**
- Modify: `web/lib/session-api.ts:313-325` (`getSessionRuns`)
- Modify: `web/lib/dashboard-model.ts` (add `capSuffix`)
- Modify: `web/app/dashboard/page.tsx:336` and `:393`
- Test: `web/lib/session-api.test.mjs`, `web/lib/dashboard-model.test.mjs`

**Interfaces:**
- Produces: `getSessionRuns(accessToken, repo = "all")` now requests `limit=500&offset=0`; `capSuffix(fetched: number, limit: number): string` returns `" · latest ${limit}"` when `fetched >= limit`, else `""`.

- [ ] **Step 1: Check the API's clamp before pinning 500**

Run: `sed -n '1118,1135p' api/doug/api.py` and look for a max/clamp on `limit`. If the session route clamps below 500, use the clamped value as the constant. Record what you found in LANE1-REPORT.md.

- [ ] **Step 2: Write the failing URL test**

Append to `web/lib/session-api.test.mjs` (match its import style):

```js
test("getSessionRuns requests an explicit limit and offset", async () => {
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return new Response(JSON.stringify({ items: [], limit: 500, offset: 0 }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  };
  try {
    await getSessionRuns("token");
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.equal(calls.length, 1);
  assert.match(calls[0], /\/v1\/sessions\/runs\?repo=all&limit=500&offset=0$/);
});
```

- [ ] **Step 3: Run it — expect FAIL** (`npm test --workspace=web`; the URL today ends at `repo=all`). If Step 1 found a clamp below 500, substitute that value for 500 in this test, in `SESSION_RUNS_LIMIT`, and in Step 5's `capSuffix` expectations — one constant everywhere.

- [ ] **Step 4: Implement**

In `session-api.ts`, add `const SESSION_RUNS_LIMIT = 500;` above `getSessionRuns` and change the fetch path to:

```ts
`/v1/sessions/runs?repo=${encodeURIComponent(repo)}&limit=${SESSION_RUNS_LIMIT}&offset=0`
```

- [ ] **Step 5: Write the failing `capSuffix` test**

In `web/lib/dashboard-model.test.mjs`:

```js
test("capSuffix marks a full page as a cap, never as a total", () => {
  assert.equal(capSuffix(500, 500), " · latest 500");
  assert.equal(capSuffix(501, 500), " · latest 500");
  assert.equal(capSuffix(499, 500), "");
  assert.equal(capSuffix(0, 500), "");
});
```

- [ ] **Step 6: Run (FAIL), implement in `dashboard-model.ts`, run (PASS)**

```ts
/** Suffix for the run-count line: at the fetch cap, say so — a capped page
 *  presented as a total is the lie the console's CountLine exists to refuse. */
export function capSuffix(fetched: number, limit: number): string {
  return fetched >= limit ? ` · latest ${limit}` : "";
}
```

- [ ] **Step 7: Wire the page**

In `page.tsx`, inside the `if (current)` block keep `const response = ...`; hoist what the count line needs: `capNote = capSuffix(response.items.length, response.limit);` (declare `let capNote = "";` beside `let rows`). Change line 393's span to:

```tsx
<span className={styles.count}><b>{rows.length}</b> runs{capNote} · filters live in the URL</span>
```

- [ ] **Step 8: Mutation proof**

Revert Step 4's URL change only (`git stash push web/lib/session-api.ts` … or edit back), run tests → the Step-2 test MUST fail. Restore, run → pass. Record in LANE1-REPORT.md.

- [ ] **Step 9: Full verify + commit**

`npm test --workspace=web && npm run lint --workspace=web && npm run build --workspace=web`

```bash
git add web/lib/session-api.ts web/lib/dashboard-model.ts web/app/dashboard/page.tsx web/lib/session-api.test.mjs web/lib/dashboard-model.test.mjs
git commit -m "fix(web): dashboard requests an explicit run limit and labels the cap honestly"
```

---

### Task 2: One coverage semantics for both surfaces (bug A2)

**Files:**
- Create: `web/lib/coverage.ts` (copy of the console's semantics; header comment: `// Ported verbatim from console/lib/runs.ts — keep the two in lockstep.`)
- Modify: `web/lib/dashboard-model.ts` (`coverageView`, `filterRuns`)
- Modify: `web/app/dashboard/page.tsx` (render sites that used `percent`)
- Test: `web/lib/coverage.test.mjs`, `web/lib/dashboard-model.test.mjs`

**Interfaces:**
- Produces: `coveragePercent(coverage: RunCoverage | null, changedFiles: number | null): CoverageResult`, `coverageLabel(result: CoverageResult): string`, `LOW_COVERAGE = 0.5` — signatures identical to `console/lib/runs.ts:26-60`.
- `coverageView(run)` keeps its return keys but `percent` is now derived from `coveragePercent` (files-based), plus new keys `kind` and `label`.

- [ ] **Step 1: Copy `RunCoverage`, `LOW_COVERAGE`, `CoverageResult`, `coveragePercent`, `coverageLabel` from `console/lib/runs.ts:1-60` into `web/lib/coverage.ts`** — verbatim, including docstrings (the docstrings ARE the spec: files-based denominator, unknown-never-100%, `<1%`/`<100%` guards).

- [ ] **Step 2: Write the failing tests** (`web/lib/coverage.test.mjs`)

```js
test("coverage uses GitHub's changed_files as denominator, never the fetched list", () => {
  const cov = { diff_chars: 100, sent_chars: 100, files_sent: 3, files_unseen: [], file_cut: null };
  assert.deepEqual(coveragePercent(cov, 6), { kind: "known", pct: 50, low: false });
  assert.deepEqual(coveragePercent(cov, null), { kind: "unknown-denominator" });
  assert.deepEqual(coveragePercent(null, 6), { kind: "no-read" });
});
test("coverageLabel refuses the false 100% and the false 0%", () => {
  assert.equal(coverageLabel({ kind: "known", pct: 99.6, low: false }), "<100%");
  assert.equal(coverageLabel({ kind: "known", pct: 0.3, low: false }), "<1%");
  assert.equal(coverageLabel({ kind: "unknown-denominator" }), "—");
});
```

- [ ] **Step 3: Run (FAIL — module missing), confirm module makes them PASS**

- [ ] **Step 4: Repoint `coverageView` and `filterRuns`**

`coverageView` computes `const result = coveragePercent(read, run.changed_files)`; `percent` becomes `result.kind === "known" ? result.pct : null`; add `kind: result.kind` and `label: coverageLabel(result)`. `filterRuns`'s `lowCoverage` branch becomes: keep the row only when `result.kind === "known" && result.low`.

- [ ] **Step 5: Update render sites**

In `page.tsx`, wherever coverage renders a percent, use `label` (which carries the guards); the mini ruler keeps using `percent` for bar width. `grep -n "coverageView\|percent" web/app/dashboard/page.tsx` to find every site — list them in LANE1-REPORT.md before editing.

- [ ] **Step 6: Mutation proof** — change `coveragePercent`'s ratio back to `sent_chars / diff_chars`; Step-2 test 1 MUST fail. Restore.

- [ ] **Step 7: Full verify + commit** (`fix(web): dashboard coverage adopts the console's files-based semantics`)

---

### Task 3: One outcome-tone vocabulary (bug A3)

**Files:**
- Modify: `web/lib/dashboard-model.ts` (`outcomeTone`)
- Test: `web/lib/dashboard-model.test.mjs`

- [ ] **Step 1: Pin the real outcome vocabulary before writing the mapping**

Run: `grep -rn "kind" api/doug/outcome_worker.py | grep -i "clean\|revert\|hotfix\|=" | head -20` and `sed -n '220,235p' "console/app/runs/[verdictId]/page.tsx"`.
Record in LANE1-REPORT.md: the exact set of `outcomes.kind` values production writes, and the console's exact mapping expression. If the console's mapping would mislabel a real vocabulary value (e.g. a `"clear"` kind exists and console flags it), STOP and surface to the controller — the spec locked "adopt console's" on the belief the vocabularies agree.

- [ ] **Step 2: Failing test** — assert the unified rule (console's): `null → "neutral"`, `"clean" → "clear"`, every other string → `"flag"`. Include one asserting `outcomeTone("hotfix") === "flag"` and one for an unknown kind `outcomeTone("graded-miss") === "flag"` (the current web code returns `"neutral"` here — that's the bug).

- [ ] **Step 3: Implement, PASS, mutation-proof** (restore the old `revert|hotfix` allowlist → unknown-kind test fails), **commit** (`fix(web): outcome tone matches the console — non-clean is flagged, not neutral`).

---

### Task 4: Type the PR metadata (bug A4)

**Files:**
- Modify: `web/lib/session-api.ts` (`RunDetail.pr`, new `PRMetadata` type + validator)
- Test: `web/lib/session-api.test.mjs`

**Interfaces:**
- Produces: `export type PRMetadata` mirroring `api/doug/models.py`'s `PRMetadata` field-for-field; `RunDetail.pr: PRMetadata | null`.

- [ ] **Step 1: Read the authoritative field list**

Run: `grep -n "class PRMetadata" -A 30 api/doug/models.py`. Copy the fields from the MODEL, not from console's mirror. Then diff against `console/lib/api.ts`'s `PRMetadata` — if they disagree, the model wins; note the discrepancy in LANE1-REPORT.md.

- [ ] **Step 2: Failing tests** — a fully-populated valid `pr` object passes `isRunDetail`; an extra key on `pr` fails; a missing key fails; `pr: null` still passes. Build the valid fixture from the model's fields exactly.

- [ ] **Step 3: Implement** — `prMetadata(value)` validator in session-api.ts using the existing `record`/`exact`/`nullableString`/`nullableNumber` helpers; swap `(value.pr === null || record(value.pr))` for `(value.pr === null || prMetadata(value.pr))` in `isRunDetail`; replace `pr: Record<string, unknown> | null` with `pr: PRMetadata | null`.

- [ ] **Step 4: PASS, mutation-proof** (loosen validator back to bare `record(value.pr)` → extra-key test fails), **commit** (`fix(web): type and validate PR metadata on the run detail`).

Rendering `author` / `head_sha` / `files_dropped` on the evidence pane is Phase C item 2's work, not this task's.

---

## Phase B — design-system port (SPECIFIED, NOT STEPPED)

Requirements (expand to Phase-A standard just before execution — see Expansion protocol):

1. Port `.panel` / `.mono` / `.data-flag` / `.data-clear` / `.cov-track` / `.cov-fill` from `console/app/globals.css:160-196` into `web/app/globals.css`, WITH their comments (the CVD rule and never-a-third-data-colour rule are load-bearing).
2. Rebuild the dashboard's chrome on those utilities + Tailwind; DELETE `web/app/dashboard/dashboard.module.css`. This breaks `dashboard-contract.test.mjs`'s CSS pins (`--paper`, `max-width: 1440px`, `.outcomeClear` etc.) — rewrite each pin against the new classes in the same commit, preserving each pin's INTENT (light-paper surface, 1440px canvas, honest tone classes).
3. Port pure modules with their tests: `console/lib/search.ts`, `sorting.ts`, `paging.ts`, `facets.ts`, `grouping.ts`; wire the facet bar and per-PR grouping accordion into the dashboard run table (data already in `/v1/sessions/runs`).
4. Port components `CoverageRuler`, `BandChip`, `RunSpine` (copy with source-path header comments; NO shared package this pass — locked decision).
5. Consolidations that are free: delete web's five unused shadcn components; unify `doug-logo.tsx` and `utils.ts` copies (pick web's path, make console import stay untouched — console keeps its own copy this pass).

## Phase C — surface what's built (SPECIFIED, NOT STEPPED)

Order: finding_counts column → source/claim_generation/author/head_sha/files_dropped on evidence pane → 60-day outcome in lists → tenant-scoped health strip → receipt screen → tenant queue → spend meter.

**The deploy-order trap, named:** adding ANY key to a `/v1/sessions/*` response breaks web's exact-key validators, and deploys run api-before-web — the old web would reject the new body and the dashboard reads as an outage. Protocol for every shape change: **PR 1 (web): validator accepts the new key as OPTIONAL, deploy; PR 2 (api): add the key.** Never one PR. `finding_counts` needs no shape change (already in the response). The 60-day item changes `store.run_history` (join `window_days == 60` alongside 14 — read the comment at `store.py:2226-2240` first; it explains why a naive second join fans rows out). Health strip: `/v1/health` already accepts `repo`/`installation_id` (`api.py:1178`) but the SESSION surface must scope it server-side from session claims, never trust query params; `dashboard-contract.test.mjs:19`'s `page.includes("health") === false` pin is a deliberate test change. Receipt screen and tenant queue need session-scoped API routes (new endpoints reusing `store.receipt()` / the `/v1/queue` machinery under `live_scope`) — coordinate with Lane 2's receipt extension (§3 T4) through the controller; `store.py` changes ship as their own small PRs (spec §5).

## Phase D — copy honesty (SPECIFIED, NOT STEPPED)

`web/app/page.tsx`: replace any incumbents-don't-ground-in-outcomes implication with post-merge grounding language; add dollar figures to the cost wedge ($15–25/PR deep review vs $1–1.50 triage — cite the landscape report's sources in the PR body, not the page); keep the miss-rate "—" honest until the first publication. Also fix the stale gh-pages cost-wedge copy if that repo surface is touched this pass (memory: it predates the LLM-reader-in-scoring decision).

## Expansion protocol (for B, C, D)

One phase at a time, just before executing it: re-read the spec section + this plan's requirements; grep every file:line you will touch (they WILL have drifted); write the phase out to full Phase-A standard (failing test → run → implement → run → mutation proof where a bug is guarded → commit); get controller sign-off on the expansion before the first commit. This repo's history: four plan defects were caught in Phase-1a only because expansion happened late, against live code.

## Lane exit gate (controller verifies cold)

Spec §2's gate: no coverage/tone/count contradiction between console and dashboard on identical data; every Phase-A regression test mutation-proven; `npm test` both workspaces + lint + build green; screenshots of each dashboard state attached to the PR (use the `run` skill; states: no-connection, choose, ready-with-runs, evidence pane open).
