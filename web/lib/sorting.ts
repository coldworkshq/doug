// Ported verbatim from console/lib/sorting.ts — keep the two in lockstep.
// The only adaptation is the import preamble, explained below.
import type { RunSummary } from "./session-api";
import type { PrGroup } from "./grouping";
// console imports both of these from one module (its lib/runs.ts). Web split
// that module in two when Phase A ported the coverage half, so coveragePercent
// comes from ./coverage and parseUtc from ./runs-time — the same two functions,
// same signatures. Extensionless for the reason grouping.ts's header gives.
import { coveragePercent } from "./coverage";
import { parseUtc } from "./runs-time";

/** The only three columns with a real ordering.
 *
 *  band, tier and outcome are deliberately absent: they are categories, and
 *  sorting a category alphabetically implies a ranking that does not exist
 *  ("cleared" before "flagged" is not a fact about risk). Narrowing those
 *  is what the facet pills do. */
export const SORTABLE = ["score", "coverage", "age"] as const;

export type SortKey = (typeof SORTABLE)[number];
export type SortDir = "asc" | "desc";
export interface SortState {
  key: SortKey;
  dir: SortDir;
}

/** Newest first — the order run_history already returns, so the table's
 *  initial render matches the response and no sort is implied by default. */
export const DEFAULT_SORT: SortState = { key: "age", dir: "desc" };

/** Header-click transition: a new column starts descending, the active one
 *  flips. Descending-first suits all three — the riskiest score, the newest
 *  run, the best-read PR are each what an operator opens the console for. */
export function nextSort(current: SortState, key: SortKey): SortState {
  if (current.key !== key) return { key, dir: "desc" };
  return { key, dir: current.dir === "desc" ? "asc" : "desc" };
}

/** Sort → query-string value, or null when it is the default.
 *
 *  Returning null for the default keeps `?sort=age:desc` out of every URL:
 *  a param that is always present carries no information and makes two
 *  identical views look like different ones when shared. */
export function serializeSort(sort: SortState): string | null {
  if (sort.key === DEFAULT_SORT.key && sort.dir === DEFAULT_SORT.dir) return null;
  return `${sort.key}:${sort.dir}`;
}

/** Query-string value → sort, falling back to the default on anything this
 *  module cannot honour.
 *
 *  Unlike a facet value, an unrecognised sort key has no honest rendering:
 *  `?band=purple` can show an empty table under a filter that says
 *  "purple", but there is no such thing as a table ordered by a column that
 *  does not exist. The default is the truthful answer, and it is what the
 *  header's caret will then show. */
export function parseSort(raw: string | null): SortState {
  if (raw === null) return DEFAULT_SORT;
  const [key, dir] = raw.split(":");
  if (!SORTABLE.includes(key as SortKey)) return DEFAULT_SORT;
  if (dir !== "asc" && dir !== "desc") return DEFAULT_SORT;
  return { key: key as SortKey, dir };
}

/** Sort GROUPS by their latest run. Children are never reordered.
 *
 *  Ordering children by anything but time would destroy the one thing the
 *  accordion exists to show: a PR's runs in the sequence they happened,
 *  with coverage climbing push by push.
 *
 *  Returns a new array — the page re-sorts from the same grouped list on
 *  every header click, and an in-place sort would make the previous order
 *  unrecoverable.
 */
export function sortGroups(groups: PrGroup[], sort: SortState): PrGroup[] {
  const direction = sort.dir === "desc" ? -1 : 1;

  return [...groups]
    .map((group, index) => ({ group, index }))
    .sort((a, b) => {
      const av = sortValue(a.group.latest, sort.key);
      const bv = sortValue(b.group.latest, sort.key);

      // Absent values sink in BOTH directions. A run Doug never read has
      // no coverage — not zero coverage — and ranking it as 0% would put
      // unread PRs at the top of an ascending sort as though they had been
      // read and found empty. Same rule the CoverageBar renders by: a
      // missing measurement is stated, never substituted.
      if (av === null && bv === null) return a.index - b.index;
      if (av === null) return 1;
      if (bv === null) return -1;

      // Stable on ties, so re-sorting an equal-valued column never
      // shuffles rows that have no reason to move.
      return av === bv ? a.index - b.index : (av < bv ? -1 : 1) * direction;
    })
    .map((entry) => entry.group);
}

/** The comparable magnitude for a column, or null when the run has none. */
function sortValue(run: RunSummary, key: SortKey): number | null {
  if (key === "score") return run.score;
  if (key === "age") return parseUtc(run.scored_at).getTime();

  // Only a "known" result carries a rate. "no-read" (Doug read nothing)
  // and "unknown-denominator" (read, but GitHub's changed_files is
  // missing) are both absent measurements — an unknown rate is not a low
  // one, and treating it as 0 would rank a fully-read PR below a barely
  // read one purely because a denominator went missing.
  const coverage = coveragePercent(run.coverage, run.changed_files);
  return coverage.kind === "known" ? coverage.pct : null;
}
