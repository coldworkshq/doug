import type { RunCoverage } from "./runs";

export type Band = "cleared" | "flagged";

export interface RunFindingCounts {
  total: number;
  high: number;
  medium: number;
  low: number;
}

export interface RunJob {
  status: string;
  attempts: number;
  error: string | null;
  enqueued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunSummary {
  verdict_id: number;
  repo: string;
  installation_id: number | null;
  github_repo_id: number | null;
  pr_number: number;
  title: string;
  url: string | null;
  scored_at: string;
  tier: string;
  source: string | null;
  score: number;
  band: Band;
  threshold: number;
  coverage: RunCoverage | null;
  changed_files: number | null;
  finding_counts: RunFindingCounts;
  job: RunJob | null;
  outcome_14: string | null;
}

export const API_URL = process.env.DOUG_API_URL ?? "http://localhost:8000";

/** There is deliberately NO fixture fallback here.
 *
 *  doug-web falls back to a bundled fixture because a marketing page must
 *  survive an API outage. On an operator console that behaviour is strictly
 *  worse than an error: the page exists to answer "what did Doug do", and a
 *  plausible wrong answer defeats the entire purpose. Callers render the
 *  error string. */
async function get<T>(path: string): Promise<T | { error: string }> {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
      headers: { "X-Doug-Token": process.env.DOUG_API_TOKEN ?? "" },
    });
    if (!res.ok) return { error: `${path} → HTTP ${res.status}` };
    return (await res.json()) as T;
  } catch (e) {
    return { error: `${path} → ${e instanceof Error ? e.message : "unreachable"}` };
  }
}

export function isError<T>(v: T | { error: string }): v is { error: string } {
  return typeof v === "object" && v !== null && "error" in v;
}

export async function getRuns(params: {
  repo?: string;
  installationId?: number;
  limit?: number;
}): Promise<{ items: RunSummary[]; limit: number; offset: number } | { error: string }> {
  const q = new URLSearchParams();
  if (params.repo) q.set("repo", params.repo);
  if (params.installationId) q.set("installation_id", String(params.installationId));
  q.set("limit", String(params.limit ?? 100));
  // limit/offset round-trip the request back — the only way a caller can
  // tell "this IS every run" from "this is the first page of more", since
  // the API returns no total count. Dropping them (as the first cut of
  // this type did) throws away the one signal that distinguishes the two.
  return get<{ items: RunSummary[]; limit: number; offset: number }>(`/v1/runs?${q}`);
}
