// Ported verbatim from console/lib/runs.ts — keep the two in lockstep.

export interface RunCoverage {
  diff_chars: number;
  sent_chars: number;
  files_sent: number;
  files_unseen: string[];
  file_cut: string | null;
}

/** Below this, the run is marked. Not a hue — the ruler's emptiness is the
 *  alarm, and hue stays reserved for Doug's routing decision. */
export const LOW_COVERAGE = 0.5;

export type CoverageResult =
  | { kind: "known"; pct: number; low: boolean }
  | { kind: "no-read" }
  | { kind: "unknown-denominator" };

/** Read coverage as a percentage of the PR's true file count.
 *
 *  `changedFiles` is GitHub's own count, carried on pr_meta. It is the only
 *  correct denominator: `files` is the paginated list actually fetched and
 *  can be short of the true count, so deriving the denominator from it
 *  inflates coverage on exactly the large PRs where coverage matters most.
 *  When it is absent the honest answer is "unknown", never 100%.
 */
export function coveragePercent(
  coverage: RunCoverage | null,
  changedFiles: number | null,
): CoverageResult {
  if (coverage === null) return { kind: "no-read" };
  if (changedFiles === null || changedFiles <= 0) {
    return { kind: "unknown-denominator" };
  }
  const ratio = Math.min(1, coverage.files_sent / changedFiles);
  return { kind: "known", pct: ratio * 100, low: ratio < LOW_COVERAGE };
}

/** The rounded percentage label for a `CoverageResult`, carrying both
 *  guards a plain `Math.round` drops — shared so the Runs table and the
 *  forensics ruler can never again disagree on the same run's number:
 *
 *  - At or above 99.5% but below 100.0 exactly, "<100%" rather than a
 *    false "100%" — the same complete-read claim `coveragePercent` itself
 *    already refuses to invent when the true ratio isn't exactly 100.
 *  - Above 0% but below 0.5%, "<1%" rather than a false "0%" — the same
 *    nothing-was-read claim `{ kind: "no-read" }` exists to distinguish
 *    itself from.
 *
 *  Non-"known" results render "—": both callers show their own richer,
 *  differently-worded text for "no read" / "denominator unknown" next to
 *  this, so this only needs a safe placeholder for whichever caller
 *  doesn't. */
export function coverageLabel(result: CoverageResult): string {
  if (result.kind !== "known") return "—";
  if (result.pct >= 100) return "100%";
  if (result.pct > 0 && result.pct < 0.5) return "<1%";
  const rounded = Math.round(result.pct);
  return rounded >= 100 ? "<100%" : `${rounded}%`;
}
