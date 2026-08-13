// Ported verbatim from console/lib/facets.ts — keep the two in lockstep.
// ENFORCED: lib/console-lockstep.test.mjs imports both copies and feeds them identical
// inputs, so it fails whichever side moves. This comment is not on trust.
//
// ONE rename, deliberate: console's `filterRuns` is `filterRunsByFacets`
// here. web/lib/dashboard-model.ts already exports a DIFFERENT `filterRuns`
// (the URL-driven repo/band/low-coverage filter the dashboard page calls).
// Importing both under one name into page.tsx is a compile error at best
// and a silently wrong function call at worst (plan D5).
//
// Types come from ./session-api, whose RunSummary is field-for-field
// identical to console/lib/api.ts's — verified before this port, not
// assumed.
import type { RunSummary } from "./session-api";

/** The five dimensions the pill bar narrows on.
 *
 *  None of these may ever collide with `repo` or `tenant`: those are scope
 *  params the SERVER reads to decide what to fetch, and the pill bar writes
 *  into the same query string. A facet named "repo" would rewrite the fetch
 *  while claiming to filter the result. A test asserts the separation.
 *
 *  `outcome` and `outcome_60` are deliberately two separate keys, not one
 *  keyed by window: they are different observations of different windows
 *  (14 and 60 days), and folding them into one facet would let a single
 *  "clean" pill silently mean either. Same ruling that governs the two
 *  table columns they filter. */
export const FACET_KEYS = ["band", "tier", "read", "outcome", "outcome_60"] as const;

export type FacetKey = (typeof FACET_KEYS)[number];

export interface FacetOption {
  value: string;
  label: string;
  count: number;
}

export interface Facet {
  key: FacetKey;
  label: string;
  options: FacetOption[];
}

/** Absent key and empty array both mean "no constraint on this facet". */
export type FacetSelection = Partial<Record<FacetKey, string[]>>;

/** KEY and LABEL are separate things, and only one of them is a contract.
 *
 *  `outcome` stays the key so links already in circulation still round-trip;
 *  the label names its window because the pill bar renders `facet.label`, and
 *  a group labelled bare "outcome" beside a table column reading "14d outcome"
 *  leaves the reader to guess which window the filter narrows — the same
 *  unnamed-window defect the two-column ruling exists to refuse. */
const FACET_LABELS: Record<FacetKey, string> = {
  band: "band",
  tier: "tier",
  read: "read",
  outcome: "14d outcome",
  outcome_60: "60d outcome",
};

/** The facet value a run carries on one dimension. Total by construction —
 *  every run has an answer for every facet, because "absent" is itself a
 *  value here ("pending", "no read") rather than a hole. */
function facetValue(run: RunSummary, key: FacetKey): string {
  switch (key) {
    case "band":
      return run.band;
    case "tier":
      return run.tier;
    // Keyed on the coverage row existing, NOT on the rate being computable.
    // A run with coverage but no changed_files denominator was still read —
    // it just has no percentage to show — and filing it under "no read"
    // would claim Doug never looked at the diff.
    case "read":
      return run.coverage === null ? "no-read" : "read";
    // outcome_14 null is "the 14-day window has not closed", which is a
    // different fact from "clean". Folding them together would claim a
    // verdict was borne out when nothing has been observed.
    case "outcome":
      return run.outcome_14 ?? "pending";
    // Same treatment, same reason, for the 60-day window — a distinct
    // observation of a distinct window, not a fallback for the 14-day one.
    case "outcome_60":
      return run.outcome_60 ?? "pending";
  }
}

/** Display text for a pill. The VALUE stays the wire value (it is what
 *  travels in the URL and what a run is compared against); only the label
 *  changes. Band labels copy BandChip's own words so the filter and the
 *  column it filters speak the same language — an operator who sees
 *  "needs you" in the table should not have to guess that the pill saying
 *  "flagged" is the same thing. */
function optionLabel(key: FacetKey, value: string): string {
  if (key === "read" && value === "no-read") return "no read";
  if (key === "band") return value === "flagged" ? "needs you" : value;
  return value;
}

/** Build the pill bar from the runs themselves — never from a hardcoded
 *  list of bands or tiers, which would render pills for values that do not
 *  occur and counts of zero for facts nobody asserted.
 *
 *  Counts are exact over the array passed in, which is the full fetched set
 *  — never the filtered one, or pressing a pill would zero out every option
 *  it excluded. What that set REPRESENTS is the caller's to state: below the
 *  page limit it is the whole scope, at the limit it is only the newest N,
 *  and FacetBar words its title from `atCap` accordingly. A count computed
 *  over a page and rendered as a count over the scope is the same defect as
 *  a rate without its denominator.
 *
 *  A facet with fewer than two distinct values is dropped: a lone pill
 *  cannot change the result, and rendering one teaches the operator that
 *  the controls do nothing.
 */
export function buildFacets(runs: RunSummary[]): Facet[] {
  const facets: Facet[] = [];

  for (const key of FACET_KEYS) {
    const counts = new Map<string, number>();
    for (const run of runs) {
      const value = facetValue(run, key);
      counts.set(value, (counts.get(value) ?? 0) + 1);
    }

    if (counts.size < 2) continue;

    // Alphabetical, not by count: a control bar whose pills reorder
    // themselves as new runs land is a control bar you cannot build muscle
    // memory for.
    const options = [...counts.entries()]
      .sort((a, b) => (a[0] < b[0] ? -1 : 1))
      .map(([value, count]) => ({ value, label: optionLabel(key, value), count }));

    facets.push({ key, label: FACET_LABELS[key], options });
  }

  return facets;
}

/** OR within a facet, AND across facets — the standard faceted-search
 *  semantic and the only one that reads correctly ("flagged OR cleared"
 *  narrows nothing; "flagged AND pending" narrows twice). */
export function matchesFacets(run: RunSummary, selection: FacetSelection): boolean {
  for (const key of FACET_KEYS) {
    const chosen = selection[key];
    if (chosen === undefined || chosen.length === 0) continue;
    if (!chosen.includes(facetValue(run, key))) return false;
  }
  return true;
}

export function filterRunsByFacets(runs: RunSummary[], selection: FacetSelection): RunSummary[] {
  return runs.filter((run) => matchesFacets(run, selection));
}

/** Selection → query-string values, so a filtered view survives being
 *  copied and pasted. Facets with nothing selected are omitted rather than
 *  written blank — `?band=` present-but-empty is the same empty-vs-absent
 *  confusion ScopeSwitch documents. */
export function serializeFacets(selection: FacetSelection): Partial<Record<FacetKey, string>> {
  const out: Partial<Record<FacetKey, string>> = {};
  for (const key of FACET_KEYS) {
    const chosen = selection[key];
    if (chosen && chosen.length > 0) out[key] = chosen.join(",");
  }
  return out;
}

/** Query string → selection. `read` takes a getter rather than
 *  URLSearchParams so this stays a pure function testable without a DOM.
 *
 *  Blank and whitespace-only values collapse to "no constraint". A [""]
 *  selection would match no run at all and blank the table on a bare
 *  `?band=`. Unrecognised values are preserved deliberately: `?band=purple`
 *  should render an empty table under a filter that says "purple", never a
 *  silent fallback to unfiltered while the pill bar claims a filter is on.
 */
export function parseFacetSelection(read: (key: FacetKey) => string | null): FacetSelection {
  const selection: FacetSelection = {};
  for (const key of FACET_KEYS) {
    const raw = read(key);
    if (raw === null) continue;
    const values = raw
      .split(",")
      .map((v) => v.trim())
      .filter((v) => v !== "");
    if (values.length > 0) selection[key] = values;
  }
  return selection;
}
