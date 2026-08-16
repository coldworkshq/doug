import type { JobItem, RunSummary } from "./api";

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
    run.outcome_60,
  );
  return query.split(/\s+/).every((token) => text.includes(token));
}

export function filterRunsByQuery(runs: RunSummary[], q: string): RunSummary[] {
  const query = normalizeQuery(q);
  if (!query) return runs;
  return runs.filter((run) => runMatchesQuery(run, query));
}

/** Jobs search includes the operator-facing reason string the table shows,
 *  not just raw status — "lease expired" should match a stalled row. */
export function jobMatchesQuery(
  job: JobItem,
  q: string,
  reasonText: string,
): boolean {
  const query = normalizeQuery(q);
  if (!query) return true;
  const text = haystack(
    job.id,
    job.repo,
    job.github_repo_id,
    `#${job.pr_number}`,
    job.pr_number,
    job.status,
    job.error,
    reasonText,
  );
  return query.split(/\s+/).every((token) => text.includes(token));
}

export function filterJobsByQuery(
  jobs: JobItem[],
  q: string,
  reasonFor: (job: JobItem) => string,
): JobItem[] {
  const query = normalizeQuery(q);
  if (!query) return jobs;
  return jobs.filter((job) => jobMatchesQuery(job, query, reasonFor(job)));
}
