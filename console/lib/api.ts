import type { HealthPayload } from "./health";
import type { RunCoverage } from "./runs";
import {
  parseAdjudicationInput,
  parseExampleAdjudication,
  parseExamplePackCohort,
  parseExamplePackCohorts,
  parseExamplePackDetail,
  parseExamplePackResults,
  type AdjudicationInput,
  type CohortDetail,
  type CohortResults,
  type CohortSummary,
  type ExampleAdjudication,
  type PackDetail,
} from "./example-packs.ts";

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
  outcome_60: string | null;
}

/** Mirrors api/doug/models.py's PRMetadata field-by-field. Deliberately
 *  restricted to what GitHub hands out for free — see that model's own
 *  docstring. `author` has no default there, which is exactly why
 *  RunDetailResponse.pr as a whole is nullable rather than ever
 *  synthesizing this shape: a row with no pr_meta has no author to guess. */
export interface PRMetadata {
  number: number;
  title: string;
  author: string;
  author_type: "human" | "agent";
  additions: number;
  deletions: number;
  files: string[];
  approvals: number;
  approval_latency_s: number | null;
  days_since_last_human_commit: number | null;
  files_added: number | null;
  files_modified: number | null;
  url: string | null;
  head_sha: string | null;
  changed_files: number | null;
  files_dropped: string[];
}

/** Mirrors RunDetailResponse in api/doug/models.py field-by-field.
 *
 *  `pr` is `PRMetadata | null`, NOT the non-null object earlier drafts of
 *  this type assumed. A verdict row can carry pr_meta=NULL — every
 *  worker-path row before pr_meta capture, and every /v1/score caller —
 *  and api.py's run_detail nulls `pr` rather than synthesizing it
 *  (PRMetadata.author has no default to fill). `repo` and `pr_number`
 *  still travel at the top level in that case, so identity is never lost;
 *  what's lost is the coverage denominator, since changed_files lives on
 *  `pr` and nowhere else on this response. */
export interface RunDetail {
  verdict_id: number;
  repo: string;
  pr_number: number;
  installation_id: number | null;
  github_repo_id: number | null;
  pr: PRMetadata | null;
  scored_at: string;
  tier: string;
  prompt_hash: string | null;
  model: string | null;
  source: string | null;
  head_sha: string | null;
  risk_score: number | null;
  rationale: string | null;
  score: number;
  band: Band;
  threshold: number;
  coverage: RunCoverage | null;
  reasons: { rule: string; label: string; weight: number; severity: string | null }[];
  deviations: { type: string; description: string; severity: string }[];
  intent_alignment: number | null;
  intent_refs: string[];
  job: {
    status: string;
    attempts: number;
    claim_generation: number;
    error: string | null;
    enqueued_at: string | null;
    started_at: string | null;
    finished_at: string | null;
  } | null;
  outcomes: {
    kind: string;
    window_days: number | null;
    observed_at: string;
    source: string;
    detail: string | null;
  }[];
  outcome_jobs: { window_days: number; status: string; due_at: string; merged_at: string }[];
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
  // Explicit presence, not truthiness: installationId 0 is falsy but is a
  // value the caller passed, not an absent one. `if (params.installationId)`
  // silently dropped it — the same trap that let a malformed ?tenant= reach
  // this function as a "valid" id of 0 and query every installation.
  if (params.installationId !== undefined) q.set("installation_id", String(params.installationId));
  q.set("limit", String(params.limit ?? 100));
  // limit/offset round-trip the request back — the only way a caller can
  // tell "this IS every run" from "this is the first page of more", since
  // the API returns no total count. Dropping them (as the first cut of
  // this type did) throws away the one signal that distinguishes the two.
  return get<{ items: RunSummary[]; limit: number; offset: number }>(`/v1/runs?${q}`);
}

export async function getRunDetail(id: number): Promise<RunDetail | { error: string }> {
  return get<RunDetail>(`/v1/runs/${id}`);
}

/** Global, never scoped. "Is Doug failing on anything" is a global question,
 *  and a scope filter that can hide a fire in another tenant is an
 *  anti-feature on this surface specifically — so this deliberately takes no
 *  repo or installation argument even though /v1/health accepts them. */
export async function getHealth(): Promise<HealthPayload | { error: string }> {
  return get<HealthPayload>("/v1/health");
}

/** Mirrors JobItem in api/doug/models.py field-by-field.
 *
 *  `repo` is nullable because outcome_jobs carries only github_repo_id and
 *  installation_repos can be stale or absent entirely — the page renders the
 *  bare id in that case rather than guessing a name.
 *
 *  `stalled`, `retrying` and `overdue` are computed by the API against each
 *  lane's own lease and travel on the row, so this client never re-derives
 *  them against a constant it holds locally. */
export interface JobItem {
  id: number;
  lane: string;
  repo: string | null;
  github_repo_id: number;
  installation_id: number;
  pr_number: number;
  status: string;
  attempts: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  stalled: boolean;
  head_sha: string | null;
  enqueued_at: string | null;
  verdict_id: number | null;
  retrying: boolean;
  merge_commit_sha: string | null;
  window_days: number | null;
  due_at: string | null;
  merged_at: string | null;
  overdue: boolean;
}

export async function getJobs(params: {
  lane: "review" | "outcome";
  view: "unhealthy" | "all";
  repo?: string;
  installationId?: number;
  limit?: number;
}): Promise<{ items: JobItem[]; limit: number; offset: number } | { error: string }> {
  const q = new URLSearchParams();
  q.set("lane", params.lane);
  q.set("view", params.view);
  if (params.repo) q.set("repo", params.repo);
  // Explicit presence, not truthiness: installation id 0 is falsy but is a
  // value the caller passed, not an absent one — the same trap parseTenantId
  // exists to close on the Runs page.
  if (params.installationId !== undefined) {
    q.set("installation_id", String(params.installationId));
  }
  q.set("limit", String(params.limit ?? 100));
  return get<{ items: JobItem[]; limit: number; offset: number }>(`/v1/jobs?${q}`);
}

type ApiError = { error: string };

async function examplePackRequest<T>(
  path: string,
  parse: (value: unknown) => T,
  body?: AdjudicationInput,
): Promise<T | ApiError> {
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method: body === undefined ? "GET" : "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
      headers: {
        "X-Doug-Example-Pack-Token": process.env.DOUG_EXAMPLE_PACK_TOKEN ?? "",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) return { error: `${path} → HTTP ${response.status}` };
    return parse(await response.json());
  } catch {
    // Never include a thrown transport message here: request libraries may
    // interpolate headers, and this purpose credential must not reach UI text.
    return { error: `${path} → invalid or unavailable Example Pack response` };
  }
}

function segment(value: string): string {
  return encodeURIComponent(value);
}

export function getExamplePackCohorts(): Promise<CohortSummary[] | ApiError> {
  return examplePackRequest("/v1/example-pack-cohorts", parseExamplePackCohorts);
}

export function getExamplePackCohort(cohortId: string): Promise<CohortDetail | ApiError> {
  return examplePackRequest(
    `/v1/example-pack-cohorts/${segment(cohortId)}`,
    parseExamplePackCohort,
  );
}

export function getExamplePackDetail(
  cohortId: string,
  packHash: string,
): Promise<PackDetail | ApiError> {
  return examplePackRequest(
    `/v1/example-pack-cohorts/${segment(cohortId)}/packs/${segment(packHash)}`,
    parseExamplePackDetail,
  );
}

export function getExamplePackResults(cohortId: string): Promise<CohortResults | ApiError> {
  return examplePackRequest(
    `/v1/example-pack-cohorts/${segment(cohortId)}/results`,
    parseExamplePackResults,
  );
}

export function postExamplePackAdjudication(
  cohortId: string,
  packHash: string,
  findingId: string,
  input: unknown,
): Promise<ExampleAdjudication | ApiError> {
  const path = `/v1/example-pack-cohorts/${segment(cohortId)}/packs/${segment(packHash)}/findings/${segment(findingId)}/adjudications`;
  let checked: AdjudicationInput;
  try {
    checked = parseAdjudicationInput(input);
  } catch {
    return Promise.resolve({ error: `${path} → invalid adjudication input` });
  }
  return examplePackRequest(path, parseExampleAdjudication, checked);
}
