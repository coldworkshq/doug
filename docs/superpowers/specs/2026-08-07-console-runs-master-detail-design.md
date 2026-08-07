# Console Runs master-detail (forensics under the table)

**Status:** design approved (Andrew, 2026-08-07) · **Milestone:** console UX
**Amends:** `docs/superpowers/specs/2026-08-06-doug-console-design.md` Decision 2
(Phase 1 shipped forensics as `/runs/[verdict_id]`; this moves the primary
interaction to an under-table panel on `/`)
**Branch:** `doug-console-next` (from `origin/main` @ `#67`)

The mockup stacked Runs + forensics on one page. The live console navigates
away to `/runs/[id]` on title click, so the table consumes the whole viewport
and operators lose list context. Bring the live console closer to that
interaction: select a row → forensics appears below; the table scrolls in a
capped region.

---

## Decisions (locked)

| Topic | Choice |
|---|---|
| Selection URL | `/?run=<verdict_id>` alongside existing tenant/repo/facets/sort |
| Deep link | `/runs/[id]` redirects to `/?run=<id>` |
| Table height | Capped (~`max-h-[40vh]` / ~12–16 rows), independent scroll; flexible, not a rigid split-pane |
| Mobile | Same vertical order: filters → capped table → forensics; stack spine above evidence (existing breakpoint) |
| Visual scope | Interaction + selected-row / panel chrome (crumb, highlight, section rhythm). No cream/dot-grid theme rewrite |
| Data path | Server-driven: `app/page.tsx` fetches detail when `run` is present |

---

## IA, URL, selection

- Primary surface stays `/`. Setting `run` selects; clearing `run` deselects.
- Full-row click (or the primary PR-title control) selects. It does **not**
  navigate to `/runs/[id]`.
- Preserve today’s non-selection links: repo → scope filter, PR number →
  GitHub, history chevron → expand/collapse only.
- Selected row gets a clear highlight.
- `/runs/[verdictId]` is a deep-link shim only: redirect to `/?run=<verdictId>`.
- Unavailable API or unknown id: honest empty/error in the panel (existing
  `getRunDetail` / `isError` rules — no fabricated numbers). Table stays usable.

---

## Layout

- Sticky shell header + tabs unchanged.
- Facet bar stays **above** the table scroll region.
- Table region: `overflow-y: auto`, sticky thead inside the scroll box, height
  capped (~40vh). Without a selection the same cap still applies when the list
  is long so the page does not become an endless table.
- Forensics renders **below** the table in document flow. Long forensics may
  scroll the page; the table keeps its own scroll position across selection
  changes.
- Empty selection: no forensics body (optional one-line “select a run”).
- Mobile: same order; touch-friendly full-row select; do not steal chevron taps.

**Chrome polish (in scope):** selected-row background/border; forensics crumb
aligned with the mockup (`← clear selection · repo · #n · source`); keep
existing `Block` / `RunSpine` / `CoverageRuler` / `BandChip` visual language.

---

## Components and data flow

1. Extract forensics body from `console/app/runs/[verdictId]/page.tsx` into
   `console/components/run-forensics.tsx` (server component).
2. `console/app/page.tsx`: `getRuns()` as today; if `searchParams.run` parses to
   a positive integer, also `getRunDetail(id)` and render `RunForensics` under
   the table.
3. `console/components/runs-table.tsx`: accept `selectedId`; row select updates
   the `run` query param using the same URL-as-state approach as facets/sort
   (avoid blowing the 500-run list cache on every click when possible).
4. `console/app/runs/[verdictId]/page.tsx`: redirect to `/?run=<id>`.

Selecting an id not present in the current filtered list still loads detail by
id when the API has it.

---

## Testing

- URL helper: set/clear `run` without dropping facets/sort/scope.
- Selected row + panel render when `run` is set.
- `/runs/[id]` redirects to `/?run=<id>`.
- Honesty: unreachable API / unknown id show the existing empty/error copy in
  the panel with zero fabricated metrics.

---

## Non-goals

- Console Phase 2 (`/repos`), Phase 3 (Evidence), Phase 4 (showcase / token).
- Full mockup theme pass (cream background, dot-grid, type system rewrite).
- Changes to `/v1/runs` or `/v1/runs/{id}` wire contracts.
- Rigid desktop split-pane with independently fixed forensics viewport.

---

## Relationship to prior design

`2026-08-06-doug-console-design.md` Decision 2 named `/runs/[verdict_id]` as
the forensic route. That remains a valid deep link; the **primary** operator
path becomes under-table forensics on `/` driven by `?run=`. Phase numbering
is unchanged — this is a UX amendment to Phase 1’s Runs surface.
