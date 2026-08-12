// The dashboard's view controls, as query-string rewrites.
//
// RULING 2: the facet bar is ADAPTED from console's, not copied. Console's is a
// client component that writes the URL with `window.history.pushState` and
// re-derives its state from `useSearchParams`; web's dashboard is a server
// component that reads `searchParams` and advertises "filters live in the URL"
// in its own count line. Copying console's would move filter state into client
// memory and make that shipped prose false.
//
// So every control on web's side is a <Link> or a GET <form>, and the work each
// one does is "given the params I am looking at, what changes?" — a pure
// function, tested by lib/dashboard-view.test.mjs without a DOM. The page's own
// `href(params, changes)` helper applies the result.
import { FACET_KEYS, type FacetKey, type FacetSelection, serializeFacets } from "./facets";
import { DEFAULT_SORT, type SortState, serializeSort } from "./sorting";

type SearchValues = Record<string, string | string[] | undefined>;

/** Every query param the dashboard page reads for something OTHER than a
 *  facet: `repo` and `run` decide what the server fetches and which run it
 *  opens, and the rest are the page's own view state.
 *
 *  This is web's version of the collision guard console keeps in
 *  facets.test.mjs against `repo`/`tenant`. A facet named `repo` would rewrite
 *  the fetch while claiming to narrow the result; one named `run` would open an
 *  evidence pane. Adding a param here and a facet key of the same name in
 *  facets.ts trips the test. */
export const DASHBOARD_OWN_PARAMS = ["repo", "run", "coverage", "error", "q", "sort", "page"] as const;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** Write the WHOLE facet selection, not just the key that changed.
 *
 *  Every facet key appears in the returned changes — set to its comma-joined
 *  values, or null to be deleted. Writing only the touched key leaves a
 *  previous facet stranded in the URL: the bar renders it unselected (because
 *  the selection it was handed says so) while the query string still carries
 *  it, and the two disagree until the next full page load. */
function facetChanges(selection: FacetSelection): Record<string, string | null> {
  const serialized = serializeFacets(selection);
  const changes: Record<string, string | null> = {};
  for (const key of FACET_KEYS) changes[key] = serialized[key] ?? null;
  // Page 4 of the unfiltered list is not page 4 of the filtered one. Every
  // control that changes WHICH rows there are returns to the first page.
  changes.page = null;
  return changes;
}

/** Add or remove one value on one facet. OR within a facet, so a second click
 *  on a different value of the same facet widens the selection rather than
 *  replacing it — the semantic `matchesFacets` implements. */
export function facetToggleChanges(
  selection: FacetSelection,
  key: FacetKey,
  value: string,
): Record<string, string | null> {
  const current = selection[key] ?? [];
  const next = current.includes(value)
    ? current.filter((item) => item !== value)
    : [...current, value];
  return facetChanges({ ...selection, [key]: next });
}

/** Clear every facet — and only the facets. Scope (`repo`), the open run and
 *  the page's own predicates survive: a "clear filters" that silently refetched
 *  a different repo would change what the table is a view OF. */
export function facetClearChanges(): Record<string, string | null> {
  return facetChanges({});
}

/** The dashboard's own two predicates (`?coverage=low`, `?error=yes`). Not
 *  facets: neither is a value a run carries on some dimension, so neither has
 *  a partition to count pills over. They still change WHICH rows there are, so
 *  they return to the first page exactly as a facet does. */
export function predicateChanges(
  key: "coverage" | "error",
  next: string | null,
): Record<string, string | null> {
  return { [key]: next, page: null };
}

/** The default sort writes no param at all. A param that is always present
 *  carries no information and makes two identical views look like different
 *  ones when shared. */
export function sortChanges(sort: SortState): Record<string, string | null> {
  return { sort: serializeSort(sort), page: null };
}

export { DEFAULT_SORT };

/** The params a GET <form> must re-submit as hidden inputs.
 *
 *  A GET form submits ONLY its own controls, so without these the search box
 *  would silently clear every pill the operator had set. Keys the form owns are
 *  excluded — sending them twice lets the stale hidden copy win — and so is
 *  `run`: searching can exclude the very run whose evidence pane is pinned
 *  open, and a pane beside a table that no longer lists its row claims the row
 *  is there.
 *
 *  Absent keys are omitted rather than written blank, the same empty-vs-absent
 *  rule `parseFacetSelection` documents. */
export function carriedParams(values: SearchValues, own: string[]): Array<[string, string]> {
  const skip = new Set([...own, "run"]);
  const carried: Array<[string, string]> = [];
  for (const key of [...DASHBOARD_OWN_PARAMS, ...FACET_KEYS]) {
    if (skip.has(key)) continue;
    const value = one(values[key]);
    if (value) carried.push([key, value]);
  }
  return carried;
}
