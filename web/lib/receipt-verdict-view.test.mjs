import assert from "node:assert/strict";
import test from "node:test";

import {
  latestVerdictCaption,
  promptHashLine,
  readLine,
  verdictGap,
} from "./receipt-verdict-view.ts";

test("an unrecorded read renders as not recorded, never as a number", () => {
  const line = readLine({ diff_budget: null, read_order: null, recorded: false });
  assert.equal(line, "not recorded");
});

test("a half-stamped read is still not recorded — a budget with no ordering is not an instrument", () => {
  const line = readLine({ diff_budget: 100000, read_order: null, recorded: false });
  assert.equal(line, "not recorded");
  assert.ok(!line.includes("100000"), "must not quote a budget nothing was read under");
});

test("a recorded read quotes both halves", () => {
  const line = readLine({ diff_budget: 100000, read_order: "tier", recorded: true });
  assert.equal(line, "100000 chars · tier order");
});

test("an unstamped prompt hash never reads as a match against the frozen prompt", () => {
  const line = promptHashLine({ prompt_hash: null });
  assert.equal(line, "not stamped");
  assert.ok(!/match|frozen|verified/i.test(line));
});

test("a stamped prompt hash renders the hash", () => {
  assert.equal(promptHashLine({ prompt_hash: "abc123" }), "abc123");
});

test("the latest-verdict caption states the external EXCLUSION, not merely the topic", () => {
  const caption = latestVerdictCaption();
  // Exact equality, deliberately. A /external/i check would pass on
  // "…including external reviews" — the precise inversion this caption
  // exists to prevent — so it cannot discriminate the thing that matters.
  assert.equal(
    caption,
    "Doug's most recent score. Excludes external reviews, which carry no read.",
  );
});

test("a gap between latest and governing is reported with both ids", () => {
  const gap = verdictGap({
    latest_verdict: { verdict_id: 1076 },
    merges: [
      { merge_commit_sha: "70fe216", publication_governing: true, governing_verdict: { verdict_id: 1044 } },
    ],
  });
  assert.deepEqual(gap, { latestId: 1076, governingId: 1044, mergeSha: "70fe216" });
});

test("no gap is reported when latest IS the governing verdict", () => {
  const gap = verdictGap({
    latest_verdict: { verdict_id: 1044 },
    merges: [
      { merge_commit_sha: "70fe216", publication_governing: true, governing_verdict: { verdict_id: 1044 } },
    ],
  });
  assert.equal(gap, null);
});

test("no gap is reported when the governing merge has no governing verdict", () => {
  const gap = verdictGap({
    latest_verdict: { verdict_id: 1044 },
    merges: [
      { merge_commit_sha: "70fe216", publication_governing: true, governing_verdict: null },
    ],
  });
  assert.equal(gap, null);
});

test("the gap reads the publication-governing merge, not merely the first", () => {
  const gap = verdictGap({
    latest_verdict: { verdict_id: 1076 },
    merges: [
      { merge_commit_sha: "aaa", publication_governing: false, governing_verdict: { verdict_id: 900 } },
      { merge_commit_sha: "bbb", publication_governing: true, governing_verdict: { verdict_id: 1044 } },
    ],
  });
  assert.equal(gap.governingId, 1044);
  assert.equal(gap.mergeSha, "bbb");
});
