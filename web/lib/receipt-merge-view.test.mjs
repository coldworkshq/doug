import assert from "node:assert/strict";
import test from "node:test";

import {
  governingLine,
  mergeCaption,
  mergedHeadLine,
  windowOutcome,
  windowPreregLine,
} from "./receipt-merge-view.ts";

function win(overrides = {}) {
  return {
    window_days: 14,
    status: "pending",
    due_at: "2026-08-24T00:00:00Z",
    kind: null,
    observed_at: null,
    source: null,
    detail: null,
    prereg_hash: null,
    ...overrides,
  };
}

test("an open window reports the JOB status, never an adjudication word", () => {
  const out = windowOutcome(win({ status: "pending", kind: null }));
  assert.equal(out.text, "pending");
  assert.equal(out.tone, "neutral");
  assert.ok(!/clean|revert|censored/i.test(out.text));
});

test("a failed job is not a clean result", () => {
  const out = windowOutcome(win({ status: "failed", kind: null }));
  assert.equal(out.text, "failed");
  assert.equal(out.tone, "neutral");
});

test("clean adjudicates to clear", () => {
  const out = windowOutcome(win({ status: "done", kind: "clean" }));
  assert.deepEqual(out, { text: "clean", tone: "clear" });
});

test("revert adjudicates to flag", () => {
  const out = windowOutcome(win({ status: "done", kind: "revert" }));
  assert.deepEqual(out, { text: "revert", tone: "flag" });
});

test("censored is a NON-OBSERVATION, never painted as a miss", () => {
  const out = windowOutcome(win({ status: "done", kind: "censored" }));
  assert.equal(out.text, "censored");
  assert.equal(out.tone, "neutral", "censored in the miss colour is the #93 defect");
});

test("a pending window points at what WILL govern it, labelled as such", () => {
  const line = windowPreregLine(win({ prereg_hash: null }), { hash: "c8e30da3", in_force: true });
  assert.ok(line.includes("c8e30da3"));
  assert.ok(/will govern/i.test(line), "must not claim this document governed it");
});

test("an adjudicated window quotes ITS OWN stamp, not the one in force", () => {
  const line = windowPreregLine(win({ prereg_hash: "v8old" }), { hash: "c8e30da3", in_force: true });
  assert.ok(line.includes("v8old"));
  assert.ok(!line.includes("c8e30da3"), "reprinting today's hash manufactures a claim");
});

test("no pre-registration in force renders as absence, never a fabricated hash", () => {
  const line = windowPreregLine(win({ prereg_hash: null }), { hash: null, in_force: false });
  assert.equal(line, "no pre-registration in force");
});

test("a merge with no governing verdict falls back to its own words, not the latest verdict", () => {
  // publication_note is deliberately EMPTY here. A fixture whose note already
  // reads "no governing verdict" would pass whether or not the null-branch
  // exists — the note would simply pass through — so it proves nothing about
  // the branch it is named for.
  const line = governingLine({ governing_verdict: null, publication_note: "" });
  assert.equal(line, "no governing verdict at this merge");
});

test("a merge WITH a governing verdict renders its note verbatim", () => {
  const line = governingLine({
    governing_verdict: { verdict_id: 1044 },
    publication_note: "governing merge",
  });
  assert.equal(line, "governing merge");
});

test("an unrecorded merged head sha renders as not recorded", () => {
  assert.equal(mergedHeadLine({ merged_head_sha: null }), "not recorded");
});

test("a recorded merged head sha renders it", () => {
  assert.equal(mergedHeadLine({ merged_head_sha: "fe307ab6" }), "fe307ab6");
});

test("a non-governing merge names which merge governs instead of vanishing", () => {
  const caption = mergeCaption(
    { publication_governing: false, publication_note: "superseded by a later merge" },
    2,
  );
  assert.ok(caption.includes("superseded by a later merge"), "the note renders verbatim");
  assert.ok(/not.*governing/i.test(caption));
});

test("the governing merge is named as governing", () => {
  const caption = mergeCaption(
    { publication_governing: true, publication_note: "governing merge" },
    2,
  );
  assert.ok(/governs/i.test(caption));
});

test("a single merge needs no governing qualifier", () => {
  const caption = mergeCaption({ publication_governing: true, publication_note: "" }, 1);
  assert.equal(caption, "");
});
