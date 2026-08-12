// Ported from console/lib/search.ts — keep the two in lockstep.
// ENFORCED: lib/console-lockstep.test.mjs imports both copies and feeds them identical
// inputs, so it fails whichever side moves. The two dropped job exports are
// listed there as a ruled divergence, so dropping a THIRD would fail.
//
// Run-search half only. console's jobMatchesQuery/filterJobsByQuery are NOT
// ported: they take console's JobItem (its /jobs page type), and web has no
// jobs surface to type them against. Inventing the type to carry dead code
// would be a worse port than dropping it (plan D6).
import type { RunSummary } from "./session-api";

/** Trim + lowercase. Empty / whitespace-only becomes "" (no constraint). */
export function normalizeQuery(raw: string | null | undefined): string {
  return (raw ?? "").trim().toLowerCase();
}

function haystack(...parts: Array<string | number | null | undefined>): string {
  return parts
    .filter((p) => p !== null && p !== undefined && p !== "")
    .map(String)
    .join(" ")
    .toLowerCase();
}

/** True when every whitespace-separated token in `q` appears somewhere in
 *  the run's identity fields. An empty query matches everything. */
export function runMatchesQuery(run: RunSummary, q: string): boolean {
  const query = normalizeQuery(q);
  if (!query) return true;
  const text = haystack(
    run.repo,
    `#${run.pr_number}`,
    run.pr_number,
    run.title,
    run.band,
    run.tier,
    run.outcome_14,
  );
  return query.split(/\s+/).every((token) => text.includes(token));
}

export function filterRunsByQuery(runs: RunSummary[], q: string): RunSummary[] {
  const query = normalizeQuery(q);
  if (!query) return runs;
  return runs.filter((run) => runMatchesQuery(run, query));
}
