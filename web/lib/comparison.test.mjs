import assert from "node:assert/strict";
import test from "node:test";

import { isComparisonResponse, summarizeComparisons } from "./comparison.ts";

const coverage = {
  diff_chars: 100,
  sent_chars: 80,
  files_sent: 2,
  files_unseen: ["late.ts"],
  file_cut: "late.ts",
};

function run(overrides = {}) {
  return {
    id: 1,
    repo: "drewjst/doug",
    pr_number: 7,
    title: "Keep both runs",
    url: "https://github.com/drewjst/doug/pull/7",
    head_sha: "a".repeat(40),
    path: "app",
    scored_at: "2026-08-02T05:12:00Z",
    score: 0.4,
    band: "flagged",
    threshold: 0.3,
    tier: "reader",
    coverage,
    ...overrides,
  };
}

test("summarizeComparisons pairs only singleton App and CI runs for the exact same SHA", () => {
  const runs = [
    run({ id: 1, head_sha: "a".repeat(40), path: "app", score: 0.4, scored_at: "2026-08-02T05:12:00Z" }),
    run({ id: 2, head_sha: "a".repeat(40), path: "ci", score: 0.2, scored_at: "2026-08-02T05:11:00Z" }),
    run({ id: 3, head_sha: "b".repeat(40), path: "app", score: 0.2, scored_at: "2026-08-03T05:12:00Z" }),
    run({ id: 4, head_sha: "b".repeat(40), path: "ci", score: 0.4, scored_at: "2026-08-03T05:11:00Z" }),
    run({ id: 5, head_sha: "c".repeat(40), path: "app", scored_at: "2026-08-04T05:12:00Z" }),
    run({ id: 6, head_sha: "d".repeat(40), path: "ci", scored_at: "2026-08-05T05:12:00Z" }),
    run({ id: 7, head_sha: "e".repeat(40), path: "app", scored_at: "2026-08-06T05:12:00Z" }),
    run({ id: 8, head_sha: "e".repeat(40), path: "app", scored_at: "2026-08-06T05:11:00Z" }),
    run({ id: 9, head_sha: "e".repeat(40), path: "ci", scored_at: "2026-08-06T05:10:00Z" }),
    run({ id: 10, head_sha: null, path: "app", scored_at: "2026-08-07T05:12:00Z" }),
    run({ id: 11, head_sha: null, path: "ci", scored_at: "2026-08-08T05:12:00Z" }),
  ];

  const view = summarizeComparisons(runs);
  const duplicate = view.groups.find((group) => group.head_sha === "e".repeat(40));
  const unknownGroups = view.groups.filter((group) => group.head_sha === null);

  assert.equal(view.summary.exactPairs, 2);
  assert.equal(view.summary.missingApp, 1);
  assert.equal(view.summary.missingCi, 1);
  assert.equal(view.summary.duplicateGroups, 1);
  assert.ok(Math.abs(view.summary.meanSignedGap - 0) < 1e-9);
  assert.ok(Math.abs(view.summary.meanAbsoluteGap - 0.2) < 1e-9);
  assert.ok(Math.abs(view.summary.maxAbsoluteGap - 0.2) < 1e-9);
  assert.deepEqual(view.groups.slice(0, 2).map((group) => group.head_sha), [null, null]);
  assert.equal(duplicate.duplicate, true);
  assert.equal(duplicate.delta, null);
  assert.equal(duplicate.app.length, 2);
  assert.equal(duplicate.ci.length, 1);
  assert.notEqual(unknownGroups[0].key, unknownGroups[1].key);
});

test("isComparisonResponse accepts complete renderable data and rejects malformed runs", () => {
  assert.equal(isComparisonResponse({ runs: [] }), true);
  assert.equal(isComparisonResponse({ runs: [run({ path: "queue" })] }), false);
  assert.equal(isComparisonResponse({ runs: [run({ coverage: { ...coverage, files_unseen: [42] } })] }), false);
  assert.equal(isComparisonResponse({ runs: [run({ scored_at: "not-a-timestamp" })] }), false);
  assert.equal(isComparisonResponse({ runs: [run({ title: undefined })] }), false);
  assert.equal(isComparisonResponse({ runs: [run({ score: Number.NaN })] }), false);
});
