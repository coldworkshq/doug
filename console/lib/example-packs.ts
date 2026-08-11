export type CohortAvailabilityStatus =
  | "complete"
  | "incomplete"
  | "empty"
  | "invalid"
  | "too_large";
export type CaptureStatus = "captured" | "partial" | "failed";
export type Disposition =
  | "disproved"
  | "verified_actionable"
  | "verified_accepted_nonactionable"
  | "unknown";

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface CohortManifest {
  schema_version: "example-pack-cohort-v0";
  cohort_id: string;
  capture_started_at: string;
  capture_until: string;
  installation_ids: number[];
  github_repository_ids: number[];
  attempt_kinds: ["risk"];
  finding_cap: 3;
  raw_retention_days: 90;
  application_revision: string;
}

export interface CohortAvailability {
  status: CohortAvailabilityStatus;
  reason: string | null;
}

export interface CompletedJobIdentity {
  installation_id: number;
  github_repository_id: number;
  repository_full_name: string;
  pull_number: number;
  admitted_base_sha: string;
  admitted_head_sha: string;
}

export interface CaptureCompleteness {
  completed_jobs: number;
  members: number;
  missing: CompletedJobIdentity[];
  extra: CompletedJobIdentity[];
  boundary: "terminal-start-or-membership-linked-v0";
}

export interface AttemptSummary {
  pack_hash: string;
  run_id: string;
  member: boolean;
  review_job_id: number | null;
  instrument_id: string;
  repository_full_name: string;
  pull_number: number;
  admitted_base_sha: string;
  admitted_head_sha: string;
  captured_at: string;
  capture_status: CaptureStatus;
  findings: number;
}

export interface NameVersion {
  name: string;
  version: string;
}

export interface WholeInstrumentManifest {
  schema_version: "whole-instrument-v0";
  provider: string;
  pinned_model_id: string;
  max_output_tokens: number;
  effort: string;
  inference_parameters: NameVersion[];
  system_prompt_sha256: string;
  output_schema_sha256: string;
  diff_budget: number;
  read_order: string;
  input_policy_version: string;
  coverage_policy_version: string;
  verifier_versions: NameVersion[];
  tool_versions: NameVersion[];
  failure_policy_version: string;
  publication_policy_version: string;
  application_revision: string | null;
  runtime_revision: string | null;
  attempt_kind: "risk" | "intent";
}

export interface Scorecard {
  schema_version: "example-pack-scorecard-v0";
  eligible_prs: number;
  yield_denominator: number;
  burden_denominator: number;
  validated_actionable: number;
  verified_accepted_nonactionable: number;
  unsupported: number;
}

export interface InstrumentResult {
  instrument_id: string;
  manifest: WholeInstrumentManifest;
  scorecard: Scorecard;
  null_control: Scorecard;
  spam_control: Scorecard;
}

export interface CohortSummary {
  cohort_id: string;
  manifest: CohortManifest | null;
  availability: CohortAvailability;
  completeness: CaptureCompleteness | null;
}

export interface CohortDetail {
  manifest: CohortManifest;
  availability: CohortAvailability;
  completeness: CaptureCompleteness;
  adjudicated_findings: number;
  total_findings: number;
  members: AttemptSummary[];
  non_member_attempts: AttemptSummary[];
  instruments: InstrumentResult[];
}

export interface CohortResults {
  manifest: CohortManifest;
  availability: CohortAvailability;
  completeness: CaptureCompleteness;
  instruments: InstrumentResult[];
  members: AttemptSummary[];
}

export interface ContentRef {
  sha256: string;
  size: number;
  media_type: string;
}

export interface PackScope {
  installation_id: number;
  github_repository_id: number;
  repository_full_name: string;
  pull_number: number;
  admitted_base_sha: string;
  admitted_head_sha: string;
}

export interface PackCoverage {
  diff_chars: number;
  sent_chars: number;
  files_sent: number;
  files_unseen: string[];
  file_cut: string | null;
  changed_files: number | null;
  files_dropped: string[];
}

export interface PackFailure {
  phase: "preflight" | "transport" | "stop_reason" | "parse";
  error_type: string;
  detail: string;
}

export interface CapturedFinding {
  finding_id: string;
  ordinal: number;
  finding: { [key: string]: JsonValue };
}

export interface ExamplePack {
  schema_version: "example-pack-v0";
  pack_hash: string;
  run_id: string;
  attempt_kind: "risk" | "intent";
  captured_at: string;
  scope: PackScope;
  request: ContentRef | null;
  evidence: ContentRef;
  model_call_made: boolean;
  raw_output: ContentRef | null;
  parsed_output: { [key: string]: JsonValue } | null;
  coverage: PackCoverage;
  usage: { input_tokens: number | null; output_tokens: number | null };
  latency_ms: number;
  capture_status: CaptureStatus;
  failure: PackFailure | null;
  fallback_state: "none" | "spend_capped" | "deterministic_expected" | "intent_unavailable";
  instrument_manifest: WholeInstrumentManifest;
  instrument_id: string;
  findings: CapturedFinding[];
}

export interface EvidenceReceipt {
  kind: string;
  locator: string;
  sha256: string | null;
  detail: string;
}

export interface VerifierReceipt {
  name: string;
  version: string;
  result: string;
  detail: string;
}

export interface ExampleAdjudication {
  schema_version: "example-adjudication-v0";
  adjudication_id: string;
  pack_hash: string;
  run_id: string;
  finding_id: string;
  disposition: Disposition;
  evidence: EvidenceReceipt[];
  verifier_receipts: VerifierReceipt[];
  adjudicator: string;
  adjudicated_at: string;
  supersedes: string | null;
}

export interface PackDetail {
  pack: ExamplePack;
  request: { [key: string]: JsonValue } | null;
  evidence_text: string;
  raw_output_text: string | null;
  effective_adjudications: ExampleAdjudication[];
}

export interface AdjudicationInput {
  disposition: Disposition;
  evidence: EvidenceReceipt[];
  verifier_receipts: VerifierReceipt[];
  expected_current_adjudication_id: string | null;
}

type UnknownRecord = Record<string, unknown>;

function fail(path: string, message: string): never {
  throw new TypeError(`${path}: ${message}`);
}

function record(value: unknown, path: string, fields: readonly string[]): UnknownRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(path, "expected object");
  }
  const actual = Object.keys(value);
  for (const field of fields) {
    if (!Object.hasOwn(value, field)) fail(`${path}.${field}`, "missing field");
  }
  for (const field of actual) {
    if (!fields.includes(field)) fail(path, `unexpected field ${field}`);
  }
  return value as UnknownRecord;
}

function text(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) fail(path, "expected non-empty string");
  return value;
}

function nullableText(value: unknown, path: string): string | null {
  return value === null ? null : text(value, path);
}

function integer(value: unknown, path: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) {
    fail(path, `expected integer >= ${minimum}`);
  }
  return value;
}

function nullableInteger(value: unknown, path: string, minimum = 0): number | null {
  return value === null ? null : integer(value, path, minimum);
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") fail(path, "expected boolean");
  return value;
}

function literal<T extends string | number>(
  value: unknown,
  path: string,
  allowed: readonly T[],
): T {
  if (!allowed.some((item) => value === item)) {
    fail(path, `expected one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function array<T>(value: unknown, path: string, parse: (item: unknown, path: string) => T): T[] {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value.map((item, index) => parse(item, `${path}[${index}]`));
}

function sha256(value: unknown, path: string): string {
  const result = text(value, path);
  if (!/^[0-9a-f]{64}$/.test(result)) fail(path, "expected lowercase SHA-256");
  return result;
}

function gitSha(value: unknown, path: string): string {
  const result = text(value, path);
  if (!/^[0-9a-f]{40}$/.test(result)) fail(path, "expected full lowercase Git SHA");
  return result;
}

function timestamp(value: unknown, path: string): string {
  const result = text(value, path);
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(result) || Number.isNaN(Date.parse(result))) {
    fail(path, "expected timezone-qualified timestamp");
  }
  return result;
}

function json(value: unknown, path: string): JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.map((item, index) => json(item, `${path}[${index}]`));
  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, json(item, `${path}.${key}`)]),
    );
  }
  fail(path, "expected JSON value");
}

function jsonObject(value: unknown, path: string): { [key: string]: JsonValue } {
  const parsed = json(value, path);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    fail(path, "expected JSON object");
  }
  return parsed;
}

function parseManifest(value: unknown, path: string): CohortManifest {
  const item = record(value, path, [
    "schema_version", "cohort_id", "capture_started_at", "capture_until", "installation_ids",
    "github_repository_ids", "attempt_kinds", "finding_cap", "raw_retention_days",
    "application_revision",
  ]);
  const attemptKinds = array(item.attempt_kinds, `${path}.attempt_kinds`, (entry, entryPath) =>
    literal(entry, entryPath, ["risk"] as const),
  );
  if (attemptKinds.length !== 1) fail(`${path}.attempt_kinds`, "expected exactly risk");
  return {
    schema_version: literal(item.schema_version, `${path}.schema_version`, ["example-pack-cohort-v0"] as const),
    cohort_id: text(item.cohort_id, `${path}.cohort_id`),
    capture_started_at: timestamp(item.capture_started_at, `${path}.capture_started_at`),
    capture_until: timestamp(item.capture_until, `${path}.capture_until`),
    installation_ids: array(item.installation_ids, `${path}.installation_ids`, (entry, entryPath) => integer(entry, entryPath, 1)),
    github_repository_ids: array(item.github_repository_ids, `${path}.github_repository_ids`, (entry, entryPath) => integer(entry, entryPath, 1)),
    attempt_kinds: ["risk"],
    finding_cap: literal(item.finding_cap, `${path}.finding_cap`, [3] as const),
    raw_retention_days: literal(item.raw_retention_days, `${path}.raw_retention_days`, [90] as const),
    application_revision: gitSha(item.application_revision, `${path}.application_revision`),
  };
}

function parseAvailability(value: unknown, path: string): CohortAvailability {
  const item = record(value, path, ["status", "reason"]);
  return {
    status: literal(item.status, `${path}.status`, ["complete", "incomplete", "empty", "invalid", "too_large"] as const),
    reason: nullableText(item.reason, `${path}.reason`),
  };
}

function parseCompletedIdentity(value: unknown, path: string): CompletedJobIdentity {
  const item = record(value, path, ["installation_id", "github_repository_id", "repository_full_name", "pull_number", "admitted_base_sha", "admitted_head_sha"]);
  return {
    installation_id: integer(item.installation_id, `${path}.installation_id`, 1),
    github_repository_id: integer(item.github_repository_id, `${path}.github_repository_id`, 1),
    repository_full_name: text(item.repository_full_name, `${path}.repository_full_name`),
    pull_number: integer(item.pull_number, `${path}.pull_number`, 1),
    admitted_base_sha: text(item.admitted_base_sha, `${path}.admitted_base_sha`),
    admitted_head_sha: text(item.admitted_head_sha, `${path}.admitted_head_sha`),
  };
}

function parseCompleteness(value: unknown, path: string): CaptureCompleteness {
  const item = record(value, path, ["completed_jobs", "members", "missing", "extra", "boundary"]);
  return {
    completed_jobs: integer(item.completed_jobs, `${path}.completed_jobs`),
    members: integer(item.members, `${path}.members`),
    missing: array(item.missing, `${path}.missing`, parseCompletedIdentity),
    extra: array(item.extra, `${path}.extra`, parseCompletedIdentity),
    boundary: literal(item.boundary, `${path}.boundary`, ["terminal-start-or-membership-linked-v0"] as const),
  };
}

function parseAttempt(value: unknown, path: string): AttemptSummary {
  const item = record(value, path, ["pack_hash", "run_id", "member", "review_job_id", "instrument_id", "repository_full_name", "pull_number", "admitted_base_sha", "admitted_head_sha", "captured_at", "capture_status", "findings"]);
  const member = booleanValue(item.member, `${path}.member`);
  const job = nullableInteger(item.review_job_id, `${path}.review_job_id`, 1);
  if (member && job === null) fail(`${path}.review_job_id`, "member requires review job id");
  if (!member && job !== null) fail(`${path}.review_job_id`, "non-member cannot claim review job id");
  return {
    pack_hash: sha256(item.pack_hash, `${path}.pack_hash`),
    run_id: text(item.run_id, `${path}.run_id`),
    member,
    review_job_id: job,
    instrument_id: sha256(item.instrument_id, `${path}.instrument_id`),
    repository_full_name: text(item.repository_full_name, `${path}.repository_full_name`),
    pull_number: integer(item.pull_number, `${path}.pull_number`, 1),
    admitted_base_sha: text(item.admitted_base_sha, `${path}.admitted_base_sha`),
    admitted_head_sha: text(item.admitted_head_sha, `${path}.admitted_head_sha`),
    captured_at: timestamp(item.captured_at, `${path}.captured_at`),
    capture_status: literal(item.capture_status, `${path}.capture_status`, ["captured", "partial", "failed"] as const),
    findings: integer(item.findings, `${path}.findings`),
  };
}

function parseNameVersion(value: unknown, path: string): NameVersion {
  const item = record(value, path, ["name", "version"]);
  return { name: text(item.name, `${path}.name`), version: text(item.version, `${path}.version`) };
}

function parseInstrumentManifest(value: unknown, path: string): WholeInstrumentManifest {
  const item = record(value, path, ["schema_version", "provider", "pinned_model_id", "max_output_tokens", "effort", "inference_parameters", "system_prompt_sha256", "output_schema_sha256", "diff_budget", "read_order", "input_policy_version", "coverage_policy_version", "verifier_versions", "tool_versions", "failure_policy_version", "publication_policy_version", "application_revision", "runtime_revision", "attempt_kind"]);
  return {
    schema_version: literal(item.schema_version, `${path}.schema_version`, ["whole-instrument-v0"] as const),
    provider: text(item.provider, `${path}.provider`),
    pinned_model_id: text(item.pinned_model_id, `${path}.pinned_model_id`),
    max_output_tokens: integer(item.max_output_tokens, `${path}.max_output_tokens`, 1),
    effort: text(item.effort, `${path}.effort`),
    inference_parameters: array(item.inference_parameters, `${path}.inference_parameters`, parseNameVersion),
    system_prompt_sha256: sha256(item.system_prompt_sha256, `${path}.system_prompt_sha256`),
    output_schema_sha256: sha256(item.output_schema_sha256, `${path}.output_schema_sha256`),
    diff_budget: integer(item.diff_budget, `${path}.diff_budget`, 1),
    read_order: text(item.read_order, `${path}.read_order`),
    input_policy_version: text(item.input_policy_version, `${path}.input_policy_version`),
    coverage_policy_version: text(item.coverage_policy_version, `${path}.coverage_policy_version`),
    verifier_versions: array(item.verifier_versions, `${path}.verifier_versions`, parseNameVersion),
    tool_versions: array(item.tool_versions, `${path}.tool_versions`, parseNameVersion),
    failure_policy_version: text(item.failure_policy_version, `${path}.failure_policy_version`),
    publication_policy_version: text(item.publication_policy_version, `${path}.publication_policy_version`),
    application_revision: nullableText(item.application_revision, `${path}.application_revision`),
    runtime_revision: nullableText(item.runtime_revision, `${path}.runtime_revision`),
    attempt_kind: literal(item.attempt_kind, `${path}.attempt_kind`, ["risk", "intent"] as const),
  };
}

function parseScorecard(value: unknown, path: string): Scorecard {
  const item = record(value, path, ["schema_version", "eligible_prs", "yield_denominator", "burden_denominator", "validated_actionable", "verified_accepted_nonactionable", "unsupported"]);
  return {
    schema_version: literal(item.schema_version, `${path}.schema_version`, ["example-pack-scorecard-v0"] as const),
    eligible_prs: integer(item.eligible_prs, `${path}.eligible_prs`),
    yield_denominator: integer(item.yield_denominator, `${path}.yield_denominator`),
    burden_denominator: integer(item.burden_denominator, `${path}.burden_denominator`),
    validated_actionable: integer(item.validated_actionable, `${path}.validated_actionable`),
    verified_accepted_nonactionable: integer(item.verified_accepted_nonactionable, `${path}.verified_accepted_nonactionable`),
    unsupported: integer(item.unsupported, `${path}.unsupported`),
  };
}

function parseInstrument(value: unknown, path: string): InstrumentResult {
  const item = record(value, path, ["instrument_id", "manifest", "scorecard", "null_control", "spam_control"]);
  return {
    instrument_id: sha256(item.instrument_id, `${path}.instrument_id`),
    manifest: parseInstrumentManifest(item.manifest, `${path}.manifest`),
    scorecard: parseScorecard(item.scorecard, `${path}.scorecard`),
    null_control: parseScorecard(item.null_control, `${path}.null_control`),
    spam_control: parseScorecard(item.spam_control, `${path}.spam_control`),
  };
}

export function parseExamplePackCohorts(value: unknown): CohortSummary[] {
  return array(value, "$", (entry, path) => {
    const item = record(entry, path, ["cohort_id", "manifest", "availability", "completeness"]);
    return {
      cohort_id: text(item.cohort_id, `${path}.cohort_id`),
      manifest: item.manifest === null ? null : parseManifest(item.manifest, `${path}.manifest`),
      availability: parseAvailability(item.availability, `${path}.availability`),
      completeness: item.completeness === null ? null : parseCompleteness(item.completeness, `${path}.completeness`),
    };
  });
}

export function parseExamplePackCohort(value: unknown): CohortDetail {
  const item = record(value, "$", ["manifest", "availability", "completeness", "adjudicated_findings", "total_findings", "members", "non_member_attempts", "instruments"]);
  return {
    manifest: parseManifest(item.manifest, "$.manifest"),
    availability: parseAvailability(item.availability, "$.availability"),
    completeness: parseCompleteness(item.completeness, "$.completeness"),
    adjudicated_findings: integer(item.adjudicated_findings, "$.adjudicated_findings"),
    total_findings: integer(item.total_findings, "$.total_findings"),
    members: array(item.members, "$.members", parseAttempt),
    non_member_attempts: array(item.non_member_attempts, "$.non_member_attempts", parseAttempt),
    instruments: array(item.instruments, "$.instruments", parseInstrument),
  };
}

export function parseExamplePackResults(value: unknown): CohortResults {
  const item = record(value, "$", ["manifest", "availability", "completeness", "instruments", "members"]);
  return {
    manifest: parseManifest(item.manifest, "$.manifest"),
    availability: parseAvailability(item.availability, "$.availability"),
    completeness: parseCompleteness(item.completeness, "$.completeness"),
    instruments: array(item.instruments, "$.instruments", parseInstrument),
    members: array(item.members, "$.members", parseAttempt),
  };
}

function parseContentRef(value: unknown, path: string): ContentRef {
  const item = record(value, path, ["sha256", "size", "media_type"]);
  return {
    sha256: sha256(item.sha256, `${path}.sha256`),
    size: integer(item.size, `${path}.size`),
    media_type: text(item.media_type, `${path}.media_type`),
  };
}

function parsePackScope(value: unknown, path: string): PackScope {
  const item = record(value, path, ["installation_id", "github_repository_id", "repository_full_name", "pull_number", "admitted_base_sha", "admitted_head_sha"]);
  return {
    installation_id: integer(item.installation_id, `${path}.installation_id`, 1),
    github_repository_id: integer(item.github_repository_id, `${path}.github_repository_id`, 1),
    repository_full_name: text(item.repository_full_name, `${path}.repository_full_name`),
    pull_number: integer(item.pull_number, `${path}.pull_number`, 1),
    admitted_base_sha: text(item.admitted_base_sha, `${path}.admitted_base_sha`),
    admitted_head_sha: text(item.admitted_head_sha, `${path}.admitted_head_sha`),
  };
}

function parseCoverage(value: unknown, path: string): PackCoverage {
  const item = record(value, path, ["diff_chars", "sent_chars", "files_sent", "files_unseen", "file_cut", "changed_files", "files_dropped"]);
  return {
    diff_chars: integer(item.diff_chars, `${path}.diff_chars`),
    sent_chars: integer(item.sent_chars, `${path}.sent_chars`),
    files_sent: integer(item.files_sent, `${path}.files_sent`),
    files_unseen: array(item.files_unseen, `${path}.files_unseen`, text),
    file_cut: nullableText(item.file_cut, `${path}.file_cut`),
    changed_files: nullableInteger(item.changed_files, `${path}.changed_files`),
    files_dropped: array(item.files_dropped, `${path}.files_dropped`, text),
  };
}

function parseFailure(value: unknown, path: string): PackFailure {
  const item = record(value, path, ["phase", "error_type", "detail"]);
  return {
    phase: literal(item.phase, `${path}.phase`, ["preflight", "transport", "stop_reason", "parse"] as const),
    error_type: text(item.error_type, `${path}.error_type`),
    detail: text(item.detail, `${path}.detail`),
  };
}

function parseFinding(value: unknown, path: string): CapturedFinding {
  const item = record(value, path, ["finding_id", "ordinal", "finding"]);
  return {
    finding_id: sha256(item.finding_id, `${path}.finding_id`),
    ordinal: integer(item.ordinal, `${path}.ordinal`),
    finding: jsonObject(item.finding, `${path}.finding`),
  };
}

function parsePack(value: unknown, path: string): ExamplePack {
  const item = record(value, path, ["schema_version", "pack_hash", "run_id", "attempt_kind", "captured_at", "scope", "request", "evidence", "model_call_made", "raw_output", "parsed_output", "coverage", "usage", "latency_ms", "capture_status", "failure", "fallback_state", "instrument_manifest", "instrument_id", "findings"]);
  const usage = record(item.usage, `${path}.usage`, ["input_tokens", "output_tokens"]);
  return {
    schema_version: literal(item.schema_version, `${path}.schema_version`, ["example-pack-v0"] as const),
    pack_hash: sha256(item.pack_hash, `${path}.pack_hash`),
    run_id: text(item.run_id, `${path}.run_id`),
    attempt_kind: literal(item.attempt_kind, `${path}.attempt_kind`, ["risk", "intent"] as const),
    captured_at: timestamp(item.captured_at, `${path}.captured_at`),
    scope: parsePackScope(item.scope, `${path}.scope`),
    request: item.request === null ? null : parseContentRef(item.request, `${path}.request`),
    evidence: parseContentRef(item.evidence, `${path}.evidence`),
    model_call_made: booleanValue(item.model_call_made, `${path}.model_call_made`),
    raw_output: item.raw_output === null ? null : parseContentRef(item.raw_output, `${path}.raw_output`),
    parsed_output: item.parsed_output === null ? null : jsonObject(item.parsed_output, `${path}.parsed_output`),
    coverage: parseCoverage(item.coverage, `${path}.coverage`),
    usage: {
      input_tokens: nullableInteger(usage.input_tokens, `${path}.usage.input_tokens`),
      output_tokens: nullableInteger(usage.output_tokens, `${path}.usage.output_tokens`),
    },
    latency_ms: integer(item.latency_ms, `${path}.latency_ms`),
    capture_status: literal(item.capture_status, `${path}.capture_status`, ["captured", "partial", "failed"] as const),
    failure: item.failure === null ? null : parseFailure(item.failure, `${path}.failure`),
    fallback_state: literal(item.fallback_state, `${path}.fallback_state`, ["none", "spend_capped", "deterministic_expected", "intent_unavailable"] as const),
    instrument_manifest: parseInstrumentManifest(item.instrument_manifest, `${path}.instrument_manifest`),
    instrument_id: sha256(item.instrument_id, `${path}.instrument_id`),
    findings: array(item.findings, `${path}.findings`, parseFinding),
  };
}

function parseEvidenceReceipt(value: unknown, path: string): EvidenceReceipt {
  const item = record(value, path, ["kind", "locator", "sha256", "detail"]);
  return {
    kind: text(item.kind, `${path}.kind`),
    locator: text(item.locator, `${path}.locator`),
    sha256: item.sha256 === null ? null : sha256(item.sha256, `${path}.sha256`),
    detail: text(item.detail, `${path}.detail`),
  };
}

function parseVerifierReceipt(value: unknown, path: string): VerifierReceipt {
  const item = record(value, path, ["name", "version", "result", "detail"]);
  return {
    name: text(item.name, `${path}.name`),
    version: text(item.version, `${path}.version`),
    result: text(item.result, `${path}.result`),
    detail: text(item.detail, `${path}.detail`),
  };
}

function parseDisposition(value: unknown, path: string): Disposition {
  return literal(value, path, ["disproved", "verified_actionable", "verified_accepted_nonactionable", "unknown"] as const);
}

export function parseExampleAdjudication(value: unknown, path = "$"
): ExampleAdjudication {
  const item = record(value, path, ["schema_version", "adjudication_id", "pack_hash", "run_id", "finding_id", "disposition", "evidence", "verifier_receipts", "adjudicator", "adjudicated_at", "supersedes"]);
  return {
    schema_version: literal(item.schema_version, `${path}.schema_version`, ["example-adjudication-v0"] as const),
    adjudication_id: sha256(item.adjudication_id, `${path}.adjudication_id`),
    pack_hash: sha256(item.pack_hash, `${path}.pack_hash`),
    run_id: text(item.run_id, `${path}.run_id`),
    finding_id: sha256(item.finding_id, `${path}.finding_id`),
    disposition: parseDisposition(item.disposition, `${path}.disposition`),
    evidence: array(item.evidence, `${path}.evidence`, parseEvidenceReceipt),
    verifier_receipts: array(item.verifier_receipts, `${path}.verifier_receipts`, parseVerifierReceipt),
    adjudicator: text(item.adjudicator, `${path}.adjudicator`),
    adjudicated_at: timestamp(item.adjudicated_at, `${path}.adjudicated_at`),
    supersedes: item.supersedes === null ? null : sha256(item.supersedes, `${path}.supersedes`),
  };
}

export function parseExamplePackDetail(value: unknown): PackDetail {
  const item = record(value, "$", ["pack", "request", "evidence_text", "raw_output_text", "effective_adjudications"]);
  return {
    pack: parsePack(item.pack, "$.pack"),
    request: item.request === null ? null : jsonObject(item.request, "$.request"),
    evidence_text: typeof item.evidence_text === "string" ? item.evidence_text : fail("$.evidence_text", "expected string"),
    raw_output_text: item.raw_output_text === null ? null : typeof item.raw_output_text === "string" ? item.raw_output_text : fail("$.raw_output_text", "expected string or null"),
    effective_adjudications: array(item.effective_adjudications, "$.effective_adjudications", parseExampleAdjudication),
  };
}

export function parseAdjudicationInput(value: unknown): AdjudicationInput {
  const item = record(value, "$", ["disposition", "evidence", "verifier_receipts", "expected_current_adjudication_id"]);
  return {
    disposition: parseDisposition(item.disposition, "$.disposition"),
    evidence: array(item.evidence, "$.evidence", parseEvidenceReceipt),
    verifier_receipts: array(item.verifier_receipts, "$.verifier_receipts", parseVerifierReceipt),
    expected_current_adjudication_id: item.expected_current_adjudication_id === null
      ? null
      : sha256(item.expected_current_adjudication_id, "$.expected_current_adjudication_id"),
  };
}

export function formatExamplePackRate(numerator: number, denominator: number): string | null {
  if (!Number.isSafeInteger(numerator) || numerator < 0) throw new TypeError("invalid numerator");
  if (!Number.isSafeInteger(denominator) || denominator < 0) throw new TypeError("invalid denominator");
  if (denominator === 0) return null;
  return `${((numerator / denominator) * 100).toFixed(1)}% · N=${denominator}`;
}

export type CohortMetric =
  | { kind: "rate"; label: string }
  | { kind: "blocked"; label: "blocked — cohort incomplete" }
  | { kind: "empty"; label: "no eligible PRs" }
  | { kind: "unavailable"; label: "unavailable" };

export function cohortMetric(
  availability: CohortAvailabilityStatus,
  numerator: number,
  denominator: number,
): CohortMetric {
  if (availability === "incomplete") {
    return { kind: "blocked", label: "blocked — cohort incomplete" };
  }
  if (availability !== "complete" && availability !== "empty") {
    return { kind: "unavailable", label: "unavailable" };
  }
  const rate = formatExamplePackRate(numerator, denominator);
  return rate === null
    ? { kind: "empty", label: "no eligible PRs" }
    : { kind: "rate", label: rate };
}

export function memberAttemptLabel(attempt: AttemptSummary): string {
  return attempt.member
    ? `member · job ${attempt.review_job_id}`
    : "non-member attempt";
}

export function completedIdentityLabel(identity: CompletedJobIdentity): string {
  return `${identity.repository_full_name} #${identity.pull_number} · installation ${identity.installation_id} · repo ${identity.github_repository_id} · ${identity.admitted_base_sha.slice(0, 12)} → ${identity.admitted_head_sha.slice(0, 12)}`;
}

/** React receives captured material only as children. Keeping this identity
 * function at the rendering seam makes any future escaping/transformation a
 * tested contract change; callers must never route the value through HTML. */
export function plainCapturedText(value: string): string {
  return value;
}

export function adjudicationActionMessage(error: string): string {
  return /→ HTTP 409$/.test(error)
    ? "Evidence changed since this page loaded. Reload before correcting this finding."
    : `Adjudication was not recorded. ${error}`;
}
