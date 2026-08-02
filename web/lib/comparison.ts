export interface ComparisonCoverage {
  diff_chars: number;
  sent_chars: number;
  files_sent: number;
  files_unseen: string[];
  file_cut: string | null;
}

export interface ComparisonRun {
  id: number;
  repo: string;
  pr_number: number;
  title: string;
  url: string;
  head_sha: string | null;
  path: "app" | "ci";
  scored_at: string;
  score: number;
  band: "cleared" | "flagged";
  threshold: number;
  tier: string;
  coverage: ComparisonCoverage | null;
}

export interface ComparisonResponse {
  runs: ComparisonRun[];
}

export type ComparisonPresence = "paired" | "app-only" | "ci-only" | "head-unknown";

export interface ComparisonGroup {
  key: string;
  repo: string;
  pr_number: number;
  title: string;
  url: string;
  head_sha: string | null;
  app: ComparisonRun[];
  ci: ComparisonRun[];
  presence: ComparisonPresence;
  duplicate: boolean;
  delta: number | null;
  newest_scored_at: string;
}

export interface ComparisonSummary {
  exactPairs: number;
  missingApp: number;
  missingCi: number;
  duplicateGroups: number;
  meanSignedGap: number | null;
  meanAbsoluteGap: number | null;
  maxAbsoluteGap: number | null;
}

export interface ComparisonView {
  groups: ComparisonGroup[];
  summary: ComparisonSummary;
}

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

function isCoverage(value: unknown): value is ComparisonCoverage {
  if (typeof value !== "object" || value === null) return false;
  const coverage = value as Record<string, unknown>;
  return (
    isFiniteNumber(coverage.diff_chars) &&
    isFiniteNumber(coverage.sent_chars) &&
    isFiniteNumber(coverage.files_sent) &&
    Array.isArray(coverage.files_unseen) &&
    coverage.files_unseen.every((file) => typeof file === "string") &&
    (typeof coverage.file_cut === "string" || coverage.file_cut === null)
  );
}

function isComparisonRun(value: unknown): value is ComparisonRun {
  if (typeof value !== "object" || value === null) return false;
  const run = value as Record<string, unknown>;
  return (
    isFiniteNumber(run.id) &&
    typeof run.repo === "string" &&
    isFiniteNumber(run.pr_number) &&
    typeof run.title === "string" &&
    typeof run.url === "string" &&
    (typeof run.head_sha === "string" || run.head_sha === null) &&
    (run.path === "app" || run.path === "ci") &&
    typeof run.scored_at === "string" && Number.isFinite(Date.parse(run.scored_at)) &&
    isFiniteNumber(run.score) &&
    (run.band === "cleared" || run.band === "flagged") &&
    isFiniteNumber(run.threshold) &&
    typeof run.tier === "string" &&
    (run.coverage === null || isCoverage(run.coverage))
  );
}

export function isComparisonResponse(data: unknown): data is ComparisonResponse {
  if (typeof data !== "object" || data === null) return false;
  const response = data as Record<string, unknown>;
  return Array.isArray(response.runs) && response.runs.every(isComparisonRun);
}

const keyFor = (run: ComparisonRun) =>
  run.head_sha
    ? `${run.repo}:${run.pr_number}:${run.head_sha}`
    : `${run.repo}:${run.pr_number}:unknown:${run.id}`;

export function summarizeComparisons(runs: ComparisonRun[]): ComparisonView {
  const groups = new Map<string, ComparisonGroup>();

  for (const run of runs) {
    const key = keyFor(run);
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        repo: run.repo,
        pr_number: run.pr_number,
        title: run.title,
        url: run.url,
        head_sha: run.head_sha,
        app: [],
        ci: [],
        presence: run.head_sha === null ? "head-unknown" : "app-only",
        duplicate: false,
        delta: null,
        newest_scored_at: run.scored_at,
      };
      groups.set(key, group);
    }
    group[run.path].push(run);
    if (Date.parse(run.scored_at) > Date.parse(group.newest_scored_at)) {
      group.newest_scored_at = run.scored_at;
    }
  }

  const orderedGroups = [...groups.values()]
    .map((group) => {
      const hasApp = group.app.length > 0;
      const hasCi = group.ci.length > 0;
      group.presence = group.head_sha === null
        ? "head-unknown"
        : hasApp && hasCi
          ? "paired"
          : hasApp
            ? "app-only"
            : "ci-only";
      group.duplicate = group.app.length > 1 || group.ci.length > 1;
      group.delta = !group.duplicate && group.presence === "paired"
        ? group.app[0].score - group.ci[0].score
        : null;
      return group;
    })
    .sort((left, right) => Date.parse(right.newest_scored_at) - Date.parse(left.newest_scored_at));

  const deltas = orderedGroups.flatMap((group) => group.delta === null ? [] : [group.delta]);
  const exactPairs = deltas.length;
  const totalSignedGap = deltas.reduce((total, delta) => total + delta, 0);
  const absoluteGaps = deltas.map(Math.abs);

  return {
    groups: orderedGroups,
    summary: {
      exactPairs,
      missingApp: orderedGroups.filter((group) => group.presence === "ci-only").length,
      missingCi: orderedGroups.filter((group) => group.presence === "app-only").length,
      duplicateGroups: orderedGroups.filter((group) => group.duplicate).length,
      meanSignedGap: exactPairs ? totalSignedGap / exactPairs : null,
      meanAbsoluteGap: exactPairs
        ? absoluteGaps.reduce((total, gap) => total + gap, 0) / exactPairs
        : null,
      maxAbsoluteGap: exactPairs ? Math.max(...absoluteGaps) : null,
    },
  };
}
