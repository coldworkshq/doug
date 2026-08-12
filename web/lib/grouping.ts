// Ported verbatim from console/lib/grouping.ts — keep the two in lockstep.
// ENFORCED: lib/console-lockstep.test.mjs imports both copies and feeds them identical
// inputs, so it fails whichever side moves. This comment is not on trust.
// The only adaptation is the import preamble, explained below.
import type { RunSummary } from "./session-api";
// Extensionless, unlike console's copy: web's tsconfig does NOT set
// allowImportingTsExtensions, so a "./runs-time.ts" specifier would fail
// `next build`'s typecheck here even though it is correct over in console.
// Web's own convention is extensionless lib-to-lib imports (lib/api.ts does
// it too), resolved by Next's bundler at build and by lib/node-next-loader.mjs
// under `node --test` — which is why grouping.test.mjs registers that loader
// and imports this module dynamically.
import { parseUtc } from "./runs-time";

/** One pull request's runs, collapsed for the accordion.
 *
 *  `latest` is the newest run and is what the collapsed row renders;
 *  `children` is everything older, newest first, and is EMPTY for a PR with
 *  a single run — the table keys "render a disclosure control" off that,
 *  because a chevron that expands to nothing claims there is more to see.
 */
export interface PrGroup {
  key: string;
  repo: string;
  prNumber: number;
  latest: RunSummary;
  children: RunSummary[];
  runCount: number;
  /** True when the fetched page hit its limit, so `runCount` counts only
   *  the runs that fit on it. See `groupRunsByPr`. */
  countIsLowerBound: boolean;
}

/** Group runs by pull request, newest group first.
 *
 *  Keyed on `repo` AND `pr_number`, never `pr_number` alone: this console
 *  spans every installation by design, so two unrelated repositories each
 *  having a #12 is the normal case, not an edge one.
 *
 *  `atCap` is the caller's `items.length >= limit`. A capped page is
 *  truncated at its oldest end, and any PR may have older runs past that
 *  boundary — including a PR whose visible runs are all recent. Nothing in
 *  the response distinguishes a complete group from a truncated one, so
 *  when the page is capped EVERY count degrades to a lower bound and the
 *  table renders "8+" rather than "8". Same rule as the page header
 *  refusing to print `items.length` as a total: a count that might be
 *  wrong is not rendered as one that is right.
 */
export function groupRunsByPr(runs: RunSummary[], atCap: boolean): PrGroup[] {
  const buckets = new Map<string, RunSummary[]>();

  for (const run of runs) {
    const key = `${run.repo}#${run.pr_number}`;
    const bucket = buckets.get(key);
    if (bucket) bucket.push(run);
    else buckets.set(key, [run]);
  }

  const groups: PrGroup[] = [];
  for (const [key, bucket] of buckets) {
    // Ordering is derived here rather than inherited from the response.
    // run_history returns newest-first today, which makes arrival order
    // and newest-first agree — so trusting arrival order would look
    // correct right up until the query's ORDER BY changes.
    const sorted = [...bucket].sort(byScoredAtDesc);
    const [latest, ...children] = sorted;
    groups.push({
      key,
      repo: latest.repo,
      prNumber: latest.pr_number,
      latest,
      children,
      runCount: sorted.length,
      countIsLowerBound: atCap,
    });
  }

  return groups.sort((a, b) => byScoredAtDesc(a.latest, b.latest));
}

/** The collapsed row's count badge, and the sentence that explains it.
 *
 *  Two separate things can make a bare number false, and they compose:
 *
 *  - the page cap (`countIsLowerBound`) — older runs may exist past the
 *    truncation boundary, so the number becomes "8+";
 *  - an active facet filter — the group holds only the runs that matched,
 *    so "3" is a count of matches, not of the PR's runs.
 *
 *  The badge stays a number either way; the `title` is where the number
 *  says what it is counting. A count rendered with no way to learn its
 *  denominator is the defect this console was built around.
 */
export function runCountLabel(
  group: PrGroup,
  filtered: boolean,
): { text: string; title: string } {
  const text = group.countIsLowerBound ? `${group.runCount}+` : `${group.runCount}`;
  const noun = group.runCount === 1 ? "run" : "runs";

  if (group.countIsLowerBound && filtered) {
    return { text, title: `at least ${group.runCount} matching ${noun} — more may exist past the page limit` };
  }
  if (group.countIsLowerBound) {
    return { text, title: `at least ${group.runCount} ${noun} — more may exist past the page limit` };
  }
  if (filtered) {
    return { text, title: `${group.runCount} ${noun} matching the current filter` };
  }
  return { text, title: `${group.runCount} ${noun}` };
}

/** Newest first, parsed through the same `parseUtc` the age column uses —
 *  see its docstring for why a second parser makes the table disagree with
 *  itself. */
function byScoredAtDesc(a: RunSummary, b: RunSummary): number {
  return parseUtc(b.scored_at).getTime() - parseUtc(a.scored_at).getTime();
}
