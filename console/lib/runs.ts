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

export function relativeAge(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h`;
  if (seconds < 604_800) return `${Math.round(seconds / 86_400)}d`;
  return `${Math.round(seconds / 604_800)}w`;
}
