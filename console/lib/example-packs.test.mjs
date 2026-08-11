import assert from "node:assert/strict";
import test from "node:test";

import {
  formatExamplePackRate,
  parseAdjudicationInput,
  parseExampleAdjudication,
  parseExamplePackCohort,
  parseExamplePackCohorts,
  parseExamplePackDetail,
  parseExamplePackResults,
} from "./example-packs.ts";

const HASH = "a".repeat(64);
const OTHER_HASH = "b".repeat(64);

function manifest() {
  return {
    schema_version: "example-pack-cohort-v0",
    cohort_id: "dogfood-2026-08",
    capture_started_at: "2026-08-10T18:00:00Z",
    capture_until: "2026-08-17T18:00:00Z",
    installation_ids: [11],
    github_repository_ids: [22],
    attempt_kinds: ["risk"],
    finding_cap: 3,
    raw_retention_days: 90,
    application_revision: "c".repeat(40),
  };
}

function completeness() {
  return {
    completed_jobs: 1,
    members: 1,
    missing: [],
    extra: [],
    boundary: "terminal-start-or-membership-linked-v0",
  };
}

function attempt() {
  return {
    pack_hash: HASH,
    run_id: "review-job:9:claim:1:risk",
    member: true,
    review_job_id: 9,
    instrument_id: OTHER_HASH,
    repository_full_name: "drewjst/doug",
    pull_number: 80,
    admitted_base_sha: "base",
    admitted_head_sha: "head",
    captured_at: "2026-08-10T19:00:00Z",
    capture_status: "captured",
    findings: 1,
  };
}

function scorecard() {
  return {
    schema_version: "example-pack-scorecard-v0",
    eligible_prs: 1,
    yield_denominator: 1,
    burden_denominator: 1,
    validated_actionable: 1,
    verified_accepted_nonactionable: 0,
    unsupported: 0,
  };
}

function instrument() {
  return {
    instrument_id: OTHER_HASH,
    manifest: {
      schema_version: "whole-instrument-v0",
      provider: "anthropic",
      pinned_model_id: "claude-test",
      max_output_tokens: 1200,
      effort: "high",
      inference_parameters: [{ name: "temperature", version: "0" }],
      system_prompt_sha256: HASH,
      output_schema_sha256: OTHER_HASH,
      diff_budget: 30000,
      read_order: "risk-v0",
      input_policy_version: "input-v0",
      coverage_policy_version: "coverage-v0",
      verifier_versions: [{ name: "ast", version: "1" }],
      tool_versions: [{ name: "doug", version: "1" }],
      failure_policy_version: "reader-fallback-v0",
      publication_policy_version: "neutral-check-v0",
      application_revision: "c".repeat(40),
      runtime_revision: "doug-api-00001",
      attempt_kind: "risk",
    },
    scorecard: scorecard(),
    null_control: { ...scorecard(), validated_actionable: 0 },
    spam_control: { ...scorecard(), validated_actionable: 0, unsupported: 1 },
  };
}

function cohortDetail() {
  return {
    manifest: manifest(),
    availability: { status: "complete", reason: null },
    completeness: completeness(),
    adjudicated_findings: 1,
    total_findings: 1,
    members: [attempt()],
    non_member_attempts: [{ ...attempt(), member: false, review_job_id: null }],
    instruments: [instrument()],
  };
}

function adjudication() {
  return {
    schema_version: "example-adjudication-v0",
    adjudication_id: OTHER_HASH,
    pack_hash: HASH,
    run_id: "review-job:9:claim:1:risk",
    finding_id: HASH,
    disposition: "verified_actionable",
    evidence: [{ kind: "source", locator: "api/doug/api.py:376", sha256: null, detail: "Exact route" }],
    verifier_receipts: [{ name: "pytest", version: "8", result: "pass", detail: "focused test" }],
    adjudicator: "andrew",
    adjudicated_at: "2026-08-10T20:00:00Z",
    supersedes: null,
  };
}

function packDetail() {
  return {
    pack: {
      schema_version: "example-pack-v0",
      pack_hash: HASH,
      run_id: "review-job:9:claim:1:risk",
      attempt_kind: "risk",
      captured_at: "2026-08-10T19:00:00Z",
      scope: {
        installation_id: 11,
        github_repository_id: 22,
        repository_full_name: "drewjst/doug",
        pull_number: 80,
        admitted_base_sha: "base",
        admitted_head_sha: "head",
      },
      request: { sha256: HASH, size: 12, media_type: "application/json" },
      evidence: { sha256: OTHER_HASH, size: 18, media_type: "text/plain" },
      model_call_made: true,
      raw_output: { sha256: HASH, size: 10, media_type: "text/plain" },
      parsed_output: { findings: [{ title: "Unsafe <script>" }] },
      coverage: {
        diff_chars: 18,
        sent_chars: 18,
        files_sent: 1,
        files_unseen: [],
        file_cut: null,
        changed_files: 1,
        files_dropped: [],
      },
      usage: { input_tokens: 10, output_tokens: 5 },
      latency_ms: 100,
      capture_status: "captured",
      failure: null,
      fallback_state: "none",
      instrument_manifest: instrument().manifest,
      instrument_id: OTHER_HASH,
      findings: [{ finding_id: HASH, ordinal: 0, finding: { title: "Unsafe <script>" } }],
    },
    request: { model: "claude-test", messages: [{ role: "user", content: "review" }] },
    evidence_text: "diff --git a/x b/x\n+<script>alert(1)</script>",
    raw_output_text: '{"findings":[]}',
    effective_adjudications: [adjudication()],
  };
}

test("Example Pack cohort contracts preserve complete, empty, and unavailable as distinct states", () => {
  const summaries = parseExamplePackCohorts([
    {
      cohort_id: "dogfood-2026-08",
      manifest: manifest(),
      availability: { status: "complete", reason: null },
      completeness: completeness(),
    },
    {
      cohort_id: "broken-cohort",
      manifest: null,
      availability: { status: "invalid", reason: "cohort evidence is invalid or unavailable" },
      completeness: null,
    },
  ]);
  assert.equal(summaries[0].availability.status, "complete");
  assert.equal(summaries[1].availability.status, "invalid");
  assert.equal(summaries[1].manifest, null);

  const detail = parseExamplePackCohort(cohortDetail());
  const results = parseExamplePackResults({
    manifest: detail.manifest,
    availability: detail.availability,
    completeness: detail.completeness,
    instruments: detail.instruments,
    members: detail.members,
  });
  assert.equal(results.instruments[0].scorecard.validated_actionable, 1);
  assert.equal(detail.members[0].member, true);
  assert.equal(detail.non_member_attempts[0].member, false);
});

test("Example Pack validators reject a malformed nested scorecard instead of partially casting it", () => {
  const payload = cohortDetail();
  payload.instruments[0].scorecard.unsupported = "0";
  assert.throws(() => parseExamplePackCohort(payload), /unsupported/);
});

test("Example Pack validators reject a malformed member job identity", () => {
  const payload = cohortDetail();
  payload.members[0].review_job_id = 0;
  assert.throws(() => parseExamplePackCohort(payload), /review_job_id/);
});

test("pack detail validates exact evidence and append-only adjudication receipts", () => {
  const parsed = parseExamplePackDetail(packDetail());
  assert.match(parsed.evidence_text, /<script>/);
  assert.equal(parsed.effective_adjudications[0].evidence[0].kind, "source");

  const malformed = packDetail();
  malformed.effective_adjudications[0].evidence[0].sha256 = "not-a-hash";
  assert.throws(() => parseExamplePackDetail(malformed), /sha256/);
});

test("adjudication input accepts only disposition, receipts, and the observed head", () => {
  const input = parseAdjudicationInput({
    disposition: "unknown",
    evidence: [],
    verifier_receipts: [],
    expected_current_adjudication_id: null,
  });
  assert.deepEqual(Object.keys(input).sort(), [
    "disposition",
    "evidence",
    "expected_current_adjudication_id",
    "verifier_receipts",
  ]);
  assert.throws(
    () => parseAdjudicationInput({ ...input, adjudicator: "browser-controlled" }),
    /unexpected field adjudicator/,
  );
  assert.equal(parseExampleAdjudication(adjudication()).adjudicator, "andrew");
});

test("every rendered rate includes its denominator and zero denominators stay empty", () => {
  assert.equal(formatExamplePackRate(1, 2), "50.0% · N=2");
  assert.equal(formatExamplePackRate(0, 3), "0.0% · N=3");
  assert.equal(formatExamplePackRate(0, 0), null);
});
