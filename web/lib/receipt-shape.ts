/** Wire types for `GET /v1/prs/{n}/receipt`, mirroring the Pydantic models in
 *  `api/doug/api.py:704-830`. Kept structurally identical on purpose: this is
 *  the one document whose fields all carry honesty meaning, and a silent
 *  rename here would let the page render a state the API did not send. */

export interface ReceiptRead {
  diff_budget: number | null;
  read_order: string | null;
  /** False whenever EITHER column is null. Half a pair describes no
   *  instrument, so absence can never be read as a value. */
  recorded: boolean;
}

export interface ReceiptVerdict {
  verdict_id: number;
  scored_at: string;
  tier: string;
  source: string | null;
  head_sha: string | null;
  model: string | null;
  /** Null means the row predates prompt-hash stamping. NOT a match against
   *  the frozen prompt, and must never render as one. */
  prompt_hash: string | null;
  read: ReceiptRead;
  score: number;
  band: string;
  threshold: number;
  risk_score: number | null;
  rationale: string | null;
  reasons: unknown[];
  deviations: unknown[];
  intent_alignment: number | null;
  intent_refs: string[];
  coverage: Record<string, unknown> | null;
}

export interface ReceiptWindow {
  window_days: number;
  /** The JOB's state: pending | running | done | failed. */
  status: string;
  due_at: string;
  /** The ADJUDICATION's: revert | clean | censored. Null while the window is
   *  open or the job never completed — never substituted with `clean`. */
  kind: string | null;
  observed_at: string | null;
  source: string | null;
  detail: Record<string, unknown> | null;
  /** Stamped at adjudication time. Null on a pending window. */
  prereg_hash: string | null;
}

export interface ReceiptMerge {
  merge_commit_sha: string;
  merged_at: string;
  base_ref: string;
  merged_head_sha: string | null;
  governing_verdict: ReceiptVerdict | null;
  publication_governing: boolean;
  publication_note: string;
  adjudication: ReceiptWindow[];
}

export interface ReceiptPreregistration {
  hash: string | null;
  in_force: boolean;
}

export interface ReceiptResponse {
  repo: string;
  pr_number: number;
  preregistration: ReceiptPreregistration;
  latest_verdict: ReceiptVerdict | null;
  merges: ReceiptMerge[];
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nullableString(value: unknown): boolean {
  return value === null || typeof value === "string";
}

function nullableNumber(value: unknown): boolean {
  return value === null || typeof value === "number";
}

function isRead(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    nullableNumber(value.diff_budget) &&
    nullableString(value.read_order) &&
    typeof value.recorded === "boolean"
  );
}

function isVerdict(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    typeof value.verdict_id === "number" &&
    typeof value.scored_at === "string" &&
    typeof value.tier === "string" &&
    nullableString(value.source) &&
    nullableString(value.head_sha) &&
    nullableString(value.model) &&
    nullableString(value.prompt_hash) &&
    isRead(value.read) &&
    typeof value.score === "number" &&
    typeof value.band === "string" &&
    typeof value.threshold === "number" &&
    nullableNumber(value.risk_score) &&
    nullableString(value.rationale) &&
    Array.isArray(value.reasons) &&
    Array.isArray(value.deviations) &&
    nullableNumber(value.intent_alignment) &&
    Array.isArray(value.intent_refs) &&
    (value.coverage === null || record(value.coverage))
  );
}

function isWindow(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    typeof value.window_days === "number" &&
    typeof value.status === "string" &&
    typeof value.due_at === "string" &&
    nullableString(value.kind) &&
    nullableString(value.observed_at) &&
    nullableString(value.source) &&
    (value.detail === null || record(value.detail)) &&
    nullableString(value.prereg_hash)
  );
}

function isMerge(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    typeof value.merge_commit_sha === "string" &&
    typeof value.merged_at === "string" &&
    typeof value.base_ref === "string" &&
    nullableString(value.merged_head_sha) &&
    (value.governing_verdict === null || isVerdict(value.governing_verdict)) &&
    typeof value.publication_governing === "boolean" &&
    typeof value.publication_note === "string" &&
    Array.isArray(value.adjudication) &&
    value.adjudication.every(isWindow)
  );
}

export function isReceiptResponse(value: unknown): value is ReceiptResponse {
  if (!record(value)) return false;
  const prereg = value.preregistration;
  return (
    typeof value.repo === "string" &&
    typeof value.pr_number === "number" &&
    record(prereg) &&
    nullableString(prereg.hash) &&
    typeof prereg.in_force === "boolean" &&
    (value.latest_verdict === null || isVerdict(value.latest_verdict)) &&
    Array.isArray(value.merges) &&
    value.merges.every(isMerge)
  );
}
