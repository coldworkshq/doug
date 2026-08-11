const SESSION_API_URL = process.env.DOUG_API_URL ?? "http://localhost:8000";
const SESSION_FETCH_TIMEOUT_MS = 5_000;

export type RepositoryConnection = {
  provider: "github";
  installation_id: number;
  organization_id: string | null;
  account_login: string;
  account_type: "User" | "Organization";
  status: "ready" | "setup_required";
  label: string | null;
  repositories: Array<{ id: number; full_name: string }>;
};

export type ConnectionsResponse = { connections: RepositoryConnection[] };

export type RunCoverage = {
  diff_chars: number;
  sent_chars: number;
  files_sent: number;
  files_unseen: string[];
  file_cut: string | null;
};

export type RunSummary = {
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
  band: "cleared" | "flagged";
  threshold: number;
  coverage: RunCoverage | null;
  changed_files: number | null;
  finding_counts: { total: number; high: number; medium: number; low: number };
  job: {
    status: string;
    attempts: number;
    error: string | null;
    enqueued_at: string | null;
    started_at: string | null;
    finished_at: string | null;
  } | null;
  outcome_14: string | null;
};

export type RunListResponse = { items: RunSummary[]; limit: number; offset: number };

/** Mirrors api/doug/models.py's PRMetadata field-for-field. The API always
 *  sends the whole model (api.py's `_with_url` returns a PRMetadata, so
 *  pydantic fills every default), which is what lets `prMetadata` below
 *  demand an exact key set. `author` has no default there, which is why `pr`
 *  is nullable rather than ever synthesized: a row with no pr_meta has no
 *  author to guess. */
export type PRMetadata = {
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
};

export type RunDetail = Record<string, unknown> & {
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
  band: "cleared" | "flagged";
  threshold: number;
  coverage: RunCoverage | null;
  reasons: Array<{ rule: string; label: string; weight: number; severity: string | null }>;
  deviations: Array<{ type: string; description: string; severity: string }>;
  intent_alignment: number | null;
  intent_refs: string[];
  job: {
    status: string; attempts: number; claim_generation: number; error: string | null;
    enqueued_at: string | null; started_at: string | null; finished_at: string | null;
  } | null;
  outcomes: Array<{
    kind: string; window_days: number | null; observed_at: string;
    source: string; detail: string | null;
  }>;
  outcome_jobs: Array<{
    window_days: number; status: string; due_at: string; merged_at: string;
  }>;
};

export class SessionApiError extends Error {}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && actual.every((key, index) => key === [...keys].sort()[index]);
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function nullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function stringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

const PR_METADATA_KEYS = [
  "number", "title", "author", "author_type", "additions", "deletions", "files",
  "approvals", "approval_latency_s", "days_since_last_human_commit", "files_added",
  "files_modified", "url", "head_sha", "changed_files", "files_dropped",
] as const;

function prMetadata(value: unknown): value is PRMetadata {
  return (
    record(value) && exact(value, PR_METADATA_KEYS) &&
    Number.isInteger(value.number) && typeof value.title === "string" &&
    typeof value.author === "string" &&
    (value.author_type === "human" || value.author_type === "agent") &&
    Number.isInteger(value.additions) && Number.isInteger(value.deletions) &&
    stringList(value.files) && Number.isInteger(value.approvals) &&
    nullableNumber(value.approval_latency_s) &&
    nullableNumber(value.days_since_last_human_commit) &&
    nullableNumber(value.files_added) && nullableNumber(value.files_modified) &&
    nullableString(value.url) && nullableString(value.head_sha) &&
    nullableNumber(value.changed_files) && stringList(value.files_dropped)
  );
}

function repository(value: unknown): value is { id: number; full_name: string } {
  return (
    record(value) &&
    exact(value, ["id", "full_name"]) &&
    Number.isInteger(value.id) &&
    typeof value.full_name === "string"
  );
}

function connection(value: unknown): value is RepositoryConnection {
  if (!record(value) || !exact(value, [
    "provider", "installation_id", "organization_id", "account_login",
    "account_type", "status", "label", "repositories",
  ])) return false;
  return (
    value.provider === "github" &&
    Number.isInteger(value.installation_id) &&
    nullableString(value.organization_id) &&
    typeof value.account_login === "string" &&
    (value.account_type === "User" || value.account_type === "Organization") &&
    (value.status === "ready" || value.status === "setup_required") &&
    nullableString(value.label) &&
    Array.isArray(value.repositories) &&
    value.repositories.every(repository)
  );
}

function isConnectionsResponse(value: unknown): value is ConnectionsResponse {
  return (
    record(value) &&
    exact(value, ["connections"]) &&
    Array.isArray(value.connections) &&
    value.connections.every(connection)
  );
}

function coverage(value: unknown): value is RunCoverage | null {
  if (value === null) return true;
  return (
    record(value) &&
    exact(value, ["diff_chars", "sent_chars", "files_sent", "files_unseen", "file_cut"]) &&
    typeof value.diff_chars === "number" &&
    typeof value.sent_chars === "number" &&
    typeof value.files_sent === "number" &&
    Array.isArray(value.files_unseen) &&
    value.files_unseen.every((item) => typeof item === "string") &&
    nullableString(value.file_cut)
  );
}

const RUN_SUMMARY_KEYS = [
  "verdict_id", "repo", "installation_id", "github_repo_id", "pr_number", "title", "url",
  "scored_at", "tier", "source", "score", "band", "threshold", "coverage", "changed_files",
  "finding_counts", "job", "outcome_14",
] as const;

function runSummary(value: unknown): value is RunSummary {
  if (!record(value) || !exact(value, RUN_SUMMARY_KEYS)) return false;
  const counts = value.finding_counts;
  const job = value.job;
  return (
    Number.isInteger(value.verdict_id) && typeof value.repo === "string" &&
    nullableNumber(value.installation_id) && nullableNumber(value.github_repo_id) &&
    Number.isInteger(value.pr_number) && typeof value.title === "string" &&
    nullableString(value.url) && typeof value.scored_at === "string" &&
    typeof value.tier === "string" && nullableString(value.source) &&
    typeof value.score === "number" && (value.band === "cleared" || value.band === "flagged") &&
    typeof value.threshold === "number" && coverage(value.coverage) &&
    nullableNumber(value.changed_files) && record(counts) &&
    exact(counts, ["total", "high", "medium", "low"]) &&
    Object.values(counts).every(Number.isInteger) &&
    (job === null || (record(job) && exact(job, [
      "status", "attempts", "error", "enqueued_at", "started_at", "finished_at",
    ]) && typeof job.status === "string" && Number.isInteger(job.attempts) &&
      nullableString(job.error) && nullableString(job.enqueued_at) &&
      nullableString(job.started_at) && nullableString(job.finished_at))) &&
    nullableString(value.outcome_14)
  );
}

function isRunListResponse(value: unknown): value is RunListResponse {
  return (
    record(value) && exact(value, ["items", "limit", "offset"]) &&
    Array.isArray(value.items) && value.items.every(runSummary) &&
    Number.isInteger(value.limit) && Number.isInteger(value.offset)
  );
}

const RUN_DETAIL_KEYS = [
  "verdict_id", "repo", "pr_number", "installation_id", "github_repo_id", "pr", "scored_at",
  "tier", "prompt_hash", "model", "source", "head_sha", "risk_score", "rationale", "score",
  "band", "threshold", "coverage", "reasons", "deviations", "intent_alignment", "intent_refs",
  "job", "outcomes", "outcome_jobs",
] as const;

function reason(value: unknown): boolean {
  return record(value) && exact(value, ["rule", "label", "weight", "severity"]) &&
    typeof value.rule === "string" && typeof value.label === "string" &&
    typeof value.weight === "number" && nullableString(value.severity);
}

function deviation(value: unknown): boolean {
  return record(value) && exact(value, ["type", "description", "severity"]) &&
    typeof value.type === "string" && typeof value.description === "string" &&
    typeof value.severity === "string";
}

function detailJob(value: unknown): boolean {
  return record(value) && exact(value, [
    "status", "attempts", "claim_generation", "error", "enqueued_at", "started_at",
    "finished_at",
  ]) && typeof value.status === "string" && Number.isInteger(value.attempts) &&
    Number.isInteger(value.claim_generation) && nullableString(value.error) &&
    nullableString(value.enqueued_at) && nullableString(value.started_at) &&
    nullableString(value.finished_at);
}

function outcome(value: unknown): boolean {
  return record(value) && exact(value, [
    "kind", "window_days", "observed_at", "source", "detail",
  ]) && typeof value.kind === "string" && nullableNumber(value.window_days) &&
    typeof value.observed_at === "string" && typeof value.source === "string" &&
    nullableString(value.detail);
}

function outcomeJob(value: unknown): boolean {
  return record(value) && exact(value, ["window_days", "status", "due_at", "merged_at"]) &&
    Number.isInteger(value.window_days) && typeof value.status === "string" &&
    typeof value.due_at === "string" && typeof value.merged_at === "string";
}

function isRunDetail(value: unknown): value is RunDetail {
  return (
    record(value) && exact(value, RUN_DETAIL_KEYS) && Number.isInteger(value.verdict_id) &&
    typeof value.repo === "string" && Number.isInteger(value.pr_number) &&
    nullableNumber(value.installation_id) && nullableNumber(value.github_repo_id) &&
    (value.pr === null || prMetadata(value.pr)) && typeof value.scored_at === "string" &&
    typeof value.tier === "string" && nullableString(value.prompt_hash) &&
    nullableString(value.model) && nullableString(value.source) && nullableString(value.head_sha) &&
    nullableNumber(value.risk_score) && nullableString(value.rationale) &&
    typeof value.score === "number" && (value.band === "cleared" || value.band === "flagged") &&
    typeof value.threshold === "number" && coverage(value.coverage) && Array.isArray(value.reasons) &&
    value.reasons.every(reason) && Array.isArray(value.deviations) &&
    value.deviations.every(deviation) && nullableNumber(value.intent_alignment) &&
    Array.isArray(value.intent_refs) && value.intent_refs.every((item) => typeof item === "string") &&
    (value.job === null || detailJob(value.job)) && Array.isArray(value.outcomes) &&
    value.outcomes.every(outcome) && Array.isArray(value.outcome_jobs) &&
    value.outcome_jobs.every(outcomeJob)
  );
}

async function sessionJson(
  path: string,
  accessToken: string,
  message: string,
): Promise<unknown> {
  try {
    const response = await fetch(`${SESSION_API_URL}${path}`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${accessToken}` },
      signal: AbortSignal.timeout(SESSION_FETCH_TIMEOUT_MS),
    });
    if (!response.ok) throw new SessionApiError(message);
    return await response.json();
  } catch (error) {
    if (error instanceof SessionApiError) throw error;
    throw new SessionApiError(message);
  }
}

export async function getConnections(accessToken: string): Promise<ConnectionsResponse> {
  const message = "Doug could not load your connected spaces.";
  const body = await sessionJson("/v1/sessions/connections", accessToken, message);
  if (!isConnectionsResponse(body)) throw new SessionApiError(message);
  return body;
}

export async function bindInstallation(
  accessToken: string,
  installationId: number,
): Promise<void> {
  const message = "Doug could not finish this repository connection.";
  try {
    if (!Number.isSafeInteger(installationId) || installationId <= 0) {
      throw new SessionApiError(message);
    }
    const response = await fetch(`${SESSION_API_URL}/v1/installations/bind`, {
      method: "POST",
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ installation_id: installationId }),
      signal: AbortSignal.timeout(SESSION_FETCH_TIMEOUT_MS),
    });
    if (response.status !== 204) throw new SessionApiError(message);
  } catch (error) {
    if (error instanceof SessionApiError) throw error;
    throw new SessionApiError(message);
  }
}

/** The API's accepted maximum: `/v1/sessions/runs` rejects anything outside
 *  1..500 with a 422 (api.py). Sending no limit at all takes the route's
 *  default of 100, which the page then printed as if it were the total. */
const SESSION_RUNS_LIMIT = 500;

export async function getSessionRuns(
  accessToken: string,
  repo = "all",
): Promise<RunListResponse> {
  const message = "Doug could not load the run ledger.";
  const body = await sessionJson(
    `/v1/sessions/runs?repo=${encodeURIComponent(repo)}&limit=${SESSION_RUNS_LIMIT}&offset=0`,
    accessToken,
    message,
  );
  if (!isRunListResponse(body)) throw new SessionApiError(message);
  return body;
}

export async function getSessionRun(
  accessToken: string,
  verdictId: number,
): Promise<RunDetail> {
  const message = "Doug could not load this run.";
  const body = await sessionJson(`/v1/sessions/runs/${verdictId}`, accessToken, message);
  if (!isRunDetail(body)) throw new SessionApiError(message);
  return body;
}
