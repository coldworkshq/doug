# Console Runs Master-Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the doug console Runs page, selecting a row opens forensics under a capped scrollable table via `/?run=<verdict_id>`, without navigating away to a separate forensics page.

**Architecture:** Server-driven selection. `app/page.tsx` reads `searchParams.run`, fetches `getRunDetail` when set, and renders a shared `RunForensics` server component below the table. `RunsTable` updates `run` with `router.replace` (so the RSC re-renders with detail) while facets/sort keep `history.pushState` (no list refetch on every pill). `/runs/[id]` redirects to `/?run=<id>`.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4, Node built-in test runner (`console` `npm test`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-07-console-runs-master-detail-design.md`
- Work in `/Users/andrew/Projects/doughq/repo/.worktrees/doug-console` on `doug-console-next`
- Do not change `/v1/runs` API contracts, worker, or doug-web
- No Phase 2/3/4 scope; no cream/dot-grid theme rewrite
- Facet/sort URL writers must preserve an existing `run` param; `run` must not collide with facet keys (`band`/`tier`/`read`/`outcome`) or scope (`repo`/`tenant`)
- Honesty rules unchanged: unreachable API / unknown id → error panel with zero fabricated metrics
- Run `npm test` and `npm run lint` in `console/` before each commit; `npm run build` before the final task
- Do not deploy or open a PR unless asked

---

## File map

| Action | Path | Responsibility |
|---|---|---|
| Create | `console/lib/selection.ts` | Parse/serialize `run` query param |
| Create | `console/lib/selection.test.mjs` | Unit tests for selection helpers |
| Create | `console/components/run-forensics.tsx` | Shared forensics UI (server) |
| Modify | `console/app/page.tsx` | Fetch detail; compose table + panel |
| Modify | `console/components/runs-table.tsx` | Select row, scroll region, highlight |
| Modify | `console/app/runs/[verdictId]/page.tsx` | Redirect deep links |
| Keep | design + this plan under `docs/superpowers/` | Commit with final docs task if untracked |

---

### Task 1: `run` query helpers (TDD)

**Files:**
- Create: `console/lib/selection.ts`
- Create: `console/lib/selection.test.mjs`
- Test: `console/lib/selection.test.mjs`

**Interfaces:**
- Produces:
  - `parseRunId(raw: string | null | undefined): number | null` — positive integer only; blank/`0`/non-numeric → `null`
  - `applyRunParam(params: URLSearchParams, id: number | null): void` — set or delete `run`
  - `RUN_PARAM = "run"` constant

- [ ] **Step 1: Write failing tests**

Create `console/lib/selection.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";

import { RUN_PARAM, applyRunParam, parseRunId } from "./selection.ts";

test("parseRunId accepts positive integers only", () => {
  assert.equal(parseRunId("1071"), 1071);
  assert.equal(parseRunId("1"), 1);
  assert.equal(parseRunId(undefined), null);
  assert.equal(parseRunId(null), null);
  assert.equal(parseRunId(""), null);
  assert.equal(parseRunId("0"), null);
  assert.equal(parseRunId("-3"), null);
  assert.equal(parseRunId("1.5"), null);
  assert.equal(parseRunId("abc"), null);
  assert.equal(parseRunId("1071 "), 1071);
});

test("applyRunParam sets and clears without touching other keys", () => {
  const params = new URLSearchParams("tenant=1&band=flagged&run=9");
  applyRunParam(params, 1071);
  assert.equal(params.get(RUN_PARAM), "1071");
  assert.equal(params.get("tenant"), "1");
  assert.equal(params.get("band"), "flagged");
  applyRunParam(params, null);
  assert.equal(params.get(RUN_PARAM), null);
  assert.equal(params.get("tenant"), "1");
});

test("run param name does not collide with facet or scope keys", () => {
  assert.equal(RUN_PARAM, "run");
  for (const key of ["band", "tier", "read", "outcome", "repo", "tenant", "sort"]) {
    assert.notEqual(RUN_PARAM, key);
  }
});
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console/console
npm test -- --test-name-pattern='parseRunId|applyRunParam|run param'
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `console/lib/selection.ts`**

```typescript
export const RUN_PARAM = "run";

/** Positive integer verdict ids only. Blank, zero, negative, and non-integers
 *  are "no selection" — never coerce them into a fetch. */
export function parseRunId(raw: string | null | undefined): number | null {
  if (raw == null) return null;
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  if (!/^\d+$/.test(trimmed)) return null;
  const id = Number(trimmed);
  if (!Number.isInteger(id) || id < 1) return null;
  return id;
}

export function applyRunParam(params: URLSearchParams, id: number | null): void {
  if (id === null) params.delete(RUN_PARAM);
  else params.set(RUN_PARAM, String(id));
}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console/console
npm test -- --test-name-pattern='parseRunId|applyRunParam|run param'
```

- [ ] **Step 5: Commit**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console
git add console/lib/selection.ts console/lib/selection.test.mjs
git commit -m "$(cat <<'EOF'
feat(console): parse and write the run selection query param

Selection lives in ?run= beside facets and scope.
EOF
)"
```

---

### Task 2: Extract `RunForensics` server component

**Files:**
- Create: `console/components/run-forensics.tsx`
- Modify: `console/app/runs/[verdictId]/page.tsx` — thin wrapper that still works until Task 4 redirects
- Test: `cd console && npm run lint` (extraction must typecheck)

**Interfaces:**
- Consumes: `RunDetail` and error shape from `@/lib/api` (`isError`)
- Produces: `RunForensics({ run }: { run: RunDetail })` and `RunForensicsUnavailable({ error: string })` — no `Shell` inside

- [ ] **Step 1: Move the success + error forensics UI into `run-forensics.tsx`**

Cut from `app/runs/[verdictId]/page.tsx`:
- `Block` helper
- Success body (header through outcome grid) — **without** the outer `<Shell>`
- Error panel body — **without** `<Shell>`

Export:

```typescript
export function RunForensicsUnavailable({ error }: { error: string }): React.ReactNode
export function RunForensics({ run }: { run: RunDetail }): React.ReactNode
```

Crumb in the success header: replace `← runs` `Link href="/"` with a clear-selection control that goes to the current path without `run` when used from `/`. For this task, keep a prop:

```typescript
clearHref: string  // e.g. "/" or "/?tenant=…" without run
```

Pass `clearHref="/"` from the detail page for now. Label: `← runs` (Task 3 will pass a href that preserves facets).

- [ ] **Step 2: Make the detail page a thin Shell wrapper**

```tsx
// app/runs/[verdictId]/page.tsx — still navigable until Task 4
const run = await getRunDetail(id);
if (isError(run)) {
  return (
    <Shell scope={{ tenant: null, repo: null }} active="runs">
      <RunForensicsUnavailable error={run.error} />
    </Shell>
  );
}
return (
  <Shell scope={{ tenant: null, repo: null }} active="runs">
    <RunForensics run={run} clearHref="/" />
  </Shell>
);
```

- [ ] **Step 3: Lint**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console/console
npm run lint
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console
git add console/components/run-forensics.tsx console/app/runs/\[verdictId\]/page.tsx
git commit -m "$(cat <<'EOF'
refactor(console): extract RunForensics for reuse on the Runs page

Same forensic blocks, no Shell — ready to embed under the table.
EOF
)"
```

---

### Task 3: Wire master-detail on `/`

**Files:**
- Modify: `console/app/page.tsx`
- Modify: `console/components/runs-table.tsx`
- Test: `npm test`, `npm run lint`

**Interfaces:**
- Consumes: `parseRunId`, `applyRunParam`, `RunForensics`, `RunForensicsUnavailable`, `getRunDetail`
- Produces: `/` shows capped table + optional panel; `selectedId` drives highlight

- [ ] **Step 1: Extend `app/page.tsx` searchParams and fetch**

```tsx
searchParams: Promise<{ repo?: string; tenant?: string; run?: string }>;
// ...
const selectedId = parseRunId(params.run);
const detail =
  selectedId === null || isError(result)
    ? null
    : await getRunDetail(selectedId);
```

Build `clearHref` from current scope/facets is hard on the server without all facet keys — pass scope-only clear for the crumb, or rebuild from `params`: keep `tenant`/`repo` on clear, drop `run`. Facets are client-only for filtering the already-fetched list; clearing selection from the crumb should use a client-aware href. Simplest honest approach:

- Pass `selectedId` into `RunsTable`
- Render panel **sibling below** `RunsTable` inside the success branch:

```tsx
<Suspense fallback={null}>
  <RunsTable
    runs={result.items}
    atCap={atCap}
    limit={result.limit}
    tenant={scope.tenant}
    scopeLabel={scopeLabel}
    selectedId={selectedId}
  />
</Suspense>
{selectedId !== null && detail !== null && (
  isError(detail) ? (
    <div className="mt-6">
      <RunForensicsUnavailable error={detail.error} />
    </div>
  ) : (
    <div className="mt-6 border-t border-border">
      <RunForensics
        run={detail}
        clearHref={/* pathname + params without run: build from tenant/repo only for SSR */}
      />
    </div>
  )
)}
```

For `clearHref` on the server page, build from `tenant`/`repo` only (omit facets — acceptable; Task 3b below has the table’s select writer preserve facets). Example:

```typescript
function clearRunHref(tenant: string | null, repo: string | null): string {
  const p = new URLSearchParams();
  if (tenant) p.set("tenant", tenant);
  if (repo) p.set("repo", repo);
  const q = p.toString();
  return q ? `/?${q}` : "/";
}
```

- [ ] **Step 2: Update `RunsTable` — selection, scroll, highlight**

1. Add prop `selectedId: number | null`.
2. Import `useRouter` from `next/navigation` and `applyRunParam` from `@/lib/selection`.
3. Extend `writeView` so it **never deletes** an existing `run` unless selection changes through the new helper. Today it copies `searchParams`, so `run` already survives facet/sort writes — add a comment asserting that.
4. Add:

```typescript
function selectRun(id: number | null) {
  const params = new URLSearchParams(searchParams);
  applyRunParam(params, id);
  const query = params.toString();
  // replace (not pushState): server must re-render to fetch getRunDetail.
  // Facets keep pushState so pill clicks do not refetch the 500-run list.
  router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
}
```

5. Wrap the table (not the FacetBar) in:

```tsx
<div className="max-h-[40vh] overflow-y-auto rounded-[6px] border border-border">
  <table className="...">
    <thead className="sticky top-0 z-10 bg-background">...</thead>
    ...
  </table>
</div>
```

6. Row interaction: on the main run row `<tr>`, add `onClick` that calls `selectRun(run.verdict_id)` when the click target is not an interactive child (`a`, `button`). Add `aria-selected={selectedId === run.verdict_id}` and selected styles, e.g. `bg-[color-mix(in_srgb,var(--iridescent)_8%,transparent)]` or `bg-muted`.
7. Replace `href={/runs/${id}}` Links on title/timestamp with `button` or `<span role="link">` that calls `selectRun(id)` — or leave the title as a button. Do **not** navigate to `/runs/[id]`.
8. Stop propagation on chevron, repo `Link`, and GitHub `<a>`.

- [ ] **Step 3: Verify**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console/console
npm test
npm run lint
```

Expected: all existing tests pass; lint clean.

Manual smoke (if console + API available): open `/`, click a row → URL gains `run=`, panel appears below, table scrolls inside ~40vh.

- [ ] **Step 4: Commit**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console
git add console/app/page.tsx console/components/runs-table.tsx
git commit -m "$(cat <<'EOF'
feat(console): open run forensics under a scrollable Runs table

Selection uses ?run=; facets still update without refetching the list.
EOF
)"
```

---

### Task 4: Deep-link redirect from `/runs/[id]`

**Files:**
- Modify: `console/app/runs/[verdictId]/page.tsx` — replace body with redirect
- Test: lint/build

**Interfaces:**
- Produces: `redirect(\`/?run=${id}\`)` for valid ids; `notFound()` for invalid

- [ ] **Step 1: Replace page with redirect**

```tsx
import { notFound, redirect } from "next/navigation";
import { parseRunId } from "@/lib/selection";

export const dynamic = "force-dynamic";

export default async function RunDetailRedirect({
  params,
}: {
  params: Promise<{ verdictId: string }>;
}) {
  const { verdictId } = await params;
  const id = parseRunId(verdictId);
  if (id === null) notFound();
  redirect(`/?run=${id}`);
}
```

- [ ] **Step 2: Lint + build**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console/console
npm run lint
npm run build
```

Expected: success; route table still lists `/runs/[verdictId]` (redirect). Confirm `/` is the primary UI.

- [ ] **Step 3: Commit**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console
git add console/app/runs/\[verdictId\]/page.tsx
git commit -m "$(cat <<'EOF'
feat(console): redirect /runs/[id] deep links to /?run=

Forensics now lives under the Runs table.
EOF
)"
```

---

### Task 5: Docs commit + final verification

**Files:**
- Add if untracked: `docs/superpowers/specs/2026-08-07-console-runs-master-detail-design.md`
- Add if untracked: `docs/superpowers/plans/2026-08-07-console-runs-master-detail.md`

- [ ] **Step 1: Commit design + plan if still untracked**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console
git add docs/superpowers/specs/2026-08-07-console-runs-master-detail-design.md \
        docs/superpowers/plans/2026-08-07-console-runs-master-detail.md
git status
# commit only if staged
git commit -m "$(cat <<'EOF'
docs: console Runs master-detail design and plan

EOF
)" || true
```

- [ ] **Step 2: Full console verify**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console/console
npm test && npm run lint && npm run build
```

Expected: all green.

- [ ] **Step 3: Grep orphans**

```bash
cd /Users/andrew/Projects/doughq/repo/.worktrees/doug-console/console
rg -n 'href=\{`/runs/|/runs/\$\{' components/ app/ || echo 'no stale forensics links in app/components'
```

Expected: no stale in-app navigations to `/runs/${id}` from the table (redirect page may still mention the path).

- [ ] **Step 4: Stop** — do not open a PR unless asked.

---

## Spec coverage self-review

| Spec requirement | Task |
|---|---|
| `/?run=` selection | 1, 3 |
| Deep-link redirect | 4 |
| Capped scrollable table ~40vh | 3 |
| Forensics below table | 2, 3 |
| Mobile same order / stack | 3 (layout) |
| Selected-row + crumb chrome | 2, 3 |
| Server-driven detail fetch | 3 |
| Preserve facets on select; pushState facets keep list | 3 |
| Honesty empty/error in panel | 2, 3 |
| No API / Phase 2–4 / theme rewrite | Global constraints |
| Tests for URL helper + verify suite | 1, 3, 5 |
