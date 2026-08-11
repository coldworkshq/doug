import { createHash } from "node:crypto";
import { createServer } from "node:http";

const TOKEN = process.env.DOUG_EXAMPLE_PACK_TOKEN ?? "fixture-purpose-token";
const PORT = Number(process.env.PORT ?? 0);
const PACK_HASH = "a".repeat(64);
const FINDING_ID = "b".repeat(64);
const INSTRUMENT_A = "c".repeat(64);
const INSTRUMENT_B = "d".repeat(64);
const APP_REVISION = "e".repeat(40);
const adjudications = [];

function manifest(cohortId, day) {
  return {
    schema_version: "example-pack-cohort-v0",
    cohort_id: cohortId,
    capture_started_at: `2026-08-${day}T18:00:00Z`,
    capture_until: `2026-08-${String(Number(day) + 1).padStart(2, "0")}T18:00:00Z`,
    installation_ids: [11],
    github_repository_ids: [22],
    attempt_kinds: ["risk"],
    finding_cap: 3,
    raw_retention_days: 90,
    application_revision: APP_REVISION,
  };
}

function completeness(completedJobs, members, missing = [], extra = []) {
  return {
    completed_jobs: completedJobs,
    members,
    missing,
    extra,
    boundary: "terminal-start-or-membership-linked-v0",
  };
}

function identity(pullNumber) {
  return {
    installation_id: 11,
    github_repository_id: 22,
    repository_full_name: "drewjst/doug",
    pull_number: pullNumber,
    admitted_base_sha: "1".repeat(40),
    admitted_head_sha: "2".repeat(40),
  };
}

function attempt({
  hash = PACK_HASH,
  instrumentId = INSTRUMENT_A,
  pullNumber = 80,
  member = true,
  reviewJobId = 9,
  captureStatus = "captured",
  findings = 1,
} = {}) {
  return {
    pack_hash: hash,
    run_id: `review-job:${reviewJobId ?? 90}:claim:1:risk`,
    member,
    review_job_id: member ? reviewJobId : null,
    instrument_id: instrumentId,
    repository_full_name: "drewjst/doug",
    pull_number: pullNumber,
    admitted_base_sha: "1".repeat(40),
    admitted_head_sha: "2".repeat(40),
    captured_at: "2026-08-15T19:00:00Z",
    capture_status: captureStatus,
    findings,
  };
}

function instrumentManifest(instrumentId) {
  return {
    schema_version: "whole-instrument-v0",
    provider: "anthropic",
    pinned_model_id: instrumentId === INSTRUMENT_A ? "claude-control" : "claude-candidate",
    max_output_tokens: 1200,
    effort: "high",
    inference_parameters: [{ name: "temperature", version: "0" }],
    system_prompt_sha256: "3".repeat(64),
    output_schema_sha256: "4".repeat(64),
    diff_budget: 30000,
    read_order: "risk-v0",
    input_policy_version: "input-v0",
    coverage_policy_version: "coverage-v0",
    verifier_versions: [{ name: "ast", version: "1" }],
    tool_versions: [{ name: "doug", version: "1" }],
    failure_policy_version: "reader-fallback-v0",
    publication_policy_version: "neutral-check-v0",
    application_revision: APP_REVISION,
    runtime_revision: "doug-api-fixture",
    attempt_kind: "risk",
  };
}

function scorecard(eligible = 1, actionable = 1, unsupported = 0) {
  return {
    schema_version: "example-pack-scorecard-v0",
    eligible_prs: eligible,
    yield_denominator: eligible,
    burden_denominator: eligible,
    validated_actionable: actionable,
    verified_accepted_nonactionable: 0,
    unsupported,
  };
}

function instrument(instrumentId, eligible = 1) {
  return {
    instrument_id: instrumentId,
    manifest: instrumentManifest(instrumentId),
    scorecard: scorecard(eligible, 1, 0),
    null_control: scorecard(eligible, 0, 0),
    spam_control: scorecard(eligible, 0, eligible),
  };
}

function detail(cohortId, values) {
  return {
    manifest: manifest(cohortId, values.day),
    availability: values.availability,
    completeness: values.completeness,
    adjudicated_findings: 0,
    total_findings: values.members.reduce((count, item) => count + item.findings, 0),
    members: values.members,
    non_member_attempts: values.nonMembers ?? [],
    instruments: values.instruments,
  };
}

const cohorts = new Map([
  [
    "complete-docket",
    detail("complete-docket", {
      day: "15",
      availability: { status: "complete", reason: null },
      completeness: completeness(1, 1),
      members: [attempt()],
      instruments: [instrument(INSTRUMENT_A)],
    }),
  ],
  [
    "blocked-missing",
    detail("blocked-missing", {
      day: "14",
      availability: { status: "incomplete", reason: "completed jobs are missing member packs" },
      completeness: completeness(1, 0, [identity(81)]),
      members: [],
      instruments: [],
    }),
  ],
  [
    "mixed-attempts",
    detail("mixed-attempts", {
      day: "13",
      availability: { status: "complete", reason: null },
      completeness: completeness(3, 3),
      members: [
        attempt({ hash: "5".repeat(64), pullNumber: 82, reviewJobId: 10, captureStatus: "partial", findings: 1 }),
        attempt({ hash: "6".repeat(64), pullNumber: 83, reviewJobId: 11, captureStatus: "failed", findings: 0 }),
        attempt({ hash: "7".repeat(64), pullNumber: 84, reviewJobId: 12, findings: 0 }),
      ],
      instruments: [instrument(INSTRUMENT_A, 3)],
    }),
  ],
  [
    "retry-docket",
    detail("retry-docket", {
      day: "12",
      availability: { status: "complete", reason: null },
      completeness: completeness(1, 1),
      members: [attempt({ hash: "8".repeat(64), pullNumber: 85, reviewJobId: 13 })],
      nonMembers: [attempt({ hash: "9".repeat(64), pullNumber: 85, member: false, reviewJobId: null, captureStatus: "failed" })],
      instruments: [instrument(INSTRUMENT_A)],
    }),
  ],
  [
    "two-instruments",
    detail("two-instruments", {
      day: "11",
      availability: { status: "complete", reason: null },
      completeness: completeness(2, 2),
      members: [
        attempt({ hash: "0".repeat(64), pullNumber: 86, reviewJobId: 14, instrumentId: INSTRUMENT_A }),
        attempt({ hash: "f".repeat(64), pullNumber: 87, reviewJobId: 15, instrumentId: INSTRUMENT_B }),
      ],
      instruments: [instrument(INSTRUMENT_A), instrument(INSTRUMENT_B)],
    }),
  ],
]);

const pack = {
  schema_version: "example-pack-v0",
  pack_hash: PACK_HASH,
  run_id: "review-job:9:claim:1:risk",
  attempt_kind: "risk",
  captured_at: "2026-08-15T19:00:00Z",
  scope: identity(80),
  request: { sha256: "3".repeat(64), size: 112, media_type: "application/json" },
  evidence: { sha256: "4".repeat(64), size: 91, media_type: "text/plain" },
  model_call_made: true,
  raw_output: { sha256: "5".repeat(64), size: 72, media_type: "text/plain" },
  parsed_output: { findings: [{ title: "Rendered evidence could execute", severity: "high" }] },
  coverage: { diff_chars: 91, sent_chars: 91, files_sent: 1, files_unseen: [], file_cut: null, changed_files: 1, files_dropped: [] },
  usage: { input_tokens: 120, output_tokens: 40 },
  latency_ms: 850,
  capture_status: "captured",
  failure: null,
  fallback_state: "none",
  instrument_manifest: instrumentManifest(INSTRUMENT_A),
  instrument_id: INSTRUMENT_A,
  findings: [{ finding_id: FINDING_ID, ordinal: 0, finding: { title: "Rendered evidence could execute", severity: "high" } }],
};

function packDetail() {
  return {
    pack,
    request: { model: "claude-control", messages: [{ role: "user", content: "Review exact diff" }] },
    evidence_text: "diff --git a/page.tsx b/page.tsx\n+const payload = \"<script>alert('fixture')</script>\";",
    raw_output_text: JSON.stringify({ findings: pack.findings.map((item) => item.finding) }),
    effective_adjudications: adjudications.slice(-1),
  };
}

function send(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  response.end(body);
}

async function body(request) {
  const parts = [];
  for await (const part of request) parts.push(part);
  return JSON.parse(Buffer.concat(parts).toString("utf8"));
}

const server = createServer(async (request, response) => {
  if (request.headers["x-doug-example-pack-token"] !== TOKEN) {
    send(response, 403, { detail: "forbidden" });
    return;
  }
  const url = new URL(request.url, "http://fixture.invalid");
  if (request.method === "GET" && url.pathname === "/v1/example-pack-cohorts") {
    send(response, 200, [...cohorts.entries()].map(([cohortId, value]) => ({
      cohort_id: cohortId,
      manifest: value.manifest,
      availability: value.availability,
      completeness: value.completeness,
    })));
    return;
  }
  const resultMatch = url.pathname.match(/^\/v1\/example-pack-cohorts\/([^/]+)\/results$/);
  if (request.method === "GET" && resultMatch) {
    const value = cohorts.get(decodeURIComponent(resultMatch[1]));
    if (!value) return send(response, 404, { detail: "not found" });
    send(response, 200, {
      manifest: value.manifest,
      availability: value.availability,
      completeness: value.completeness,
      instruments: value.instruments,
      members: value.members,
    });
    return;
  }
  const packMatch = url.pathname.match(/^\/v1\/example-pack-cohorts\/([^/]+)\/packs\/([0-9a-f]{64})$/);
  if (request.method === "GET" && packMatch) {
    if (decodeURIComponent(packMatch[1]) !== "complete-docket" || packMatch[2] !== PACK_HASH) {
      return send(response, 404, { detail: "not found" });
    }
    send(response, 200, packDetail());
    return;
  }
  const adjudicationMatch = url.pathname.match(/^\/v1\/example-pack-cohorts\/([^/]+)\/packs\/([0-9a-f]{64})\/findings\/([0-9a-f]{64})\/adjudications$/);
  if (request.method === "POST" && adjudicationMatch) {
    if (decodeURIComponent(adjudicationMatch[1]) !== "complete-docket" || adjudicationMatch[2] !== PACK_HASH || adjudicationMatch[3] !== FINDING_ID) {
      return send(response, 404, { detail: "not found" });
    }
    const value = await body(request);
    const current = adjudications.at(-1) ?? null;
    const currentId = current?.adjudication_id ?? null;
    if (value.expected_current_adjudication_id !== currentId) {
      return send(response, 409, { detail: "stale adjudication" });
    }
    if (value.disposition !== "unknown" && value.evidence.length + value.verifier_receipts.length === 0) {
      return send(response, 422, { detail: "adjudication requires receipt" });
    }
    const adjudicationId = createHash("sha256").update(JSON.stringify(value) + adjudications.length).digest("hex");
    const created = {
      schema_version: "example-adjudication-v0",
      adjudication_id: adjudicationId,
      pack_hash: PACK_HASH,
      run_id: pack.run_id,
      finding_id: FINDING_ID,
      disposition: value.disposition,
      evidence: value.evidence,
      verifier_receipts: value.verifier_receipts,
      adjudicator: "andrew-fixture",
      adjudicated_at: "2026-08-15T20:00:00Z",
      supersedes: current?.adjudication_id ?? null,
    };
    adjudications.push(created);
    send(response, 200, created);
    return;
  }
  const cohortMatch = url.pathname.match(/^\/v1\/example-pack-cohorts\/([^/]+)$/);
  if (request.method === "GET" && cohortMatch) {
    const value = cohorts.get(decodeURIComponent(cohortMatch[1]));
    return value ? send(response, 200, value) : send(response, 404, { detail: "not found" });
  }
  send(response, 404, { detail: "not found" });
});

server.listen(PORT, "127.0.0.1", () => {
  const address = server.address();
  process.stdout.write(`fixture listening ${address.port}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
