import assert from "node:assert/strict";
import test from "node:test";

import { isReceiptResponse } from "./receipt-shape.ts";

function verdict(overrides = {}) {
  return {
    verdict_id: 1044,
    scored_at: "2026-08-10T12:00:00Z",
    tier: "reader",
    source: "webhook",
    head_sha: "fe307ab6",
    model: "claude-opus-5",
    prompt_hash: "abc123",
    read: { diff_budget: 100000, read_order: "tier", recorded: true },
    score: 0.42,
    band: "cleared",
    threshold: 0.6,
    risk_score: 12,
    rationale: "no boundary crossing",
    reasons: [],
    deviations: [],
    intent_alignment: null,
    intent_refs: [],
    coverage: null,
    ...overrides,
  };
}

function body(overrides = {}) {
  return {
    repo: "drewjst/doug",
    pr_number: 90,
    preregistration: { hash: "c8e30da3", in_force: true },
    latest_verdict: verdict(),
    merges: [
      {
        merge_commit_sha: "70fe216",
        merged_at: "2026-08-10T13:00:00Z",
        base_ref: "main",
        merged_head_sha: "fe307ab6",
        governing_verdict: verdict(),
        publication_governing: true,
        publication_note: "governing merge",
        adjudication: [
          {
            window_days: 14,
            status: "pending",
            due_at: "2026-08-24T13:00:00Z",
            kind: null,
            observed_at: null,
            source: null,
            detail: null,
            prereg_hash: null,
          },
        ],
      },
    ],
    ...overrides,
  };
}

test("accepts a full receipt", () => {
  assert.equal(isReceiptResponse(body()), true);
});

test("accepts a PR with no verdict and no merges", () => {
  assert.equal(isReceiptResponse(body({ latest_verdict: null, merges: [] })), true);
});

test("accepts a merge whose governing verdict is absent", () => {
  const merges = body().merges.map((m) => ({ ...m, governing_verdict: null }));
  assert.equal(isReceiptResponse(body({ merges })), true);
});

test("rejects a missing preregistration block", () => {
  const withoutPrereg = body();
  delete withoutPrereg.preregistration;
  assert.equal(isReceiptResponse(withoutPrereg), false);
});

test("rejects a window whose kind is not a string or null", () => {
  const merges = body().merges.map((m) => ({
    ...m,
    adjudication: m.adjudication.map((w) => ({ ...w, kind: 7 })),
  }));
  assert.equal(isReceiptResponse(body({ merges })), false);
});

test("rejects merges that is not an array", () => {
  assert.equal(isReceiptResponse(body({ merges: null })), false);
});
