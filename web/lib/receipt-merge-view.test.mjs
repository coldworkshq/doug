import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

// receipt-merge-view.ts delegates its tone rule to dashboard-model.ts rather
// than keeping a third copy of it, and dashboard-model imports "./coverage"
// extensionless the way Next resolves it. Same registration dashboard-model's
// own tests use.
register("./node-next-loader.mjs", import.meta.url);

const {
  governingLine,
  mergeCaption,
  mergedHeadLine,
  windowOutcome,
  windowPreregLine,
} = await import("./receipt-merge-view.ts");

/** The API's own words, copied verbatim from `api/doug/api.py:748-753`.
 *
 *  This is a FIXTURE OF THE REAL INPUT, not a convenience string. The
 *  `publication_note` field is never empty on the wire — api.py picks one of
 *  two non-empty constants by `publication_governing` alone — so a test that
 *  fed `""` proved only that an unreachable branch existed. It passed against
 *  the implementation that shipped the defect. */
const NOT_PUBLICATION_GOVERNING_NOTE =
  "This merge did not govern publication. The pull request merged again " +
  "later, and the published quarterly statistic uses the verdict standing " +
  "at that later merge. The verdict shown here is historical context — what " +
  "was standing when THIS commit merged — and is not the published number.";

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

test("a merge with no governing verdict says so, even though the API always sends a note", () => {
  // THE REAL PAYLOAD. `governing_verdict: null` arrives alongside a full,
  // non-empty `publication_note` — that combination is what
  // test_merged_pr_without_a_reader_verdict_reports_null_governing produces —
  // and the note must NOT win. `merge.publication_note || <sentence>` passes
  // the old empty-string test and fails this one: it returns the note, whose
  // words are "The verdict shown here is historical context — what was
  // standing when THIS commit merged", printed under the label `governing`
  // beside no verdict at all. The store says no verdict was standing
  // (store.py:1795-1797, prereg §2.4's excluded bucket), so that is the page
  // asserting the opposite of the truth about the most sensitive thing on it.
  const line = governingLine({
    governing_verdict: null,
    publication_note: NOT_PUBLICATION_GOVERNING_NOTE,
  });
  assert.equal(line, "no governing verdict at this merge");
  assert.equal(
    line.includes("what was standing when THIS commit merged"),
    false,
    "the note claims a verdict was standing at a merge where none was",
  );
});

test("a null governing verdict beats the GOVERNING note too, not just the non-governing one", () => {
  // The other constant (api.py:744-747) on the same null verdict. It is a
  // stranger payload — the governing merge with nothing to govern with — but
  // it is the same field and the same rule, and pinning only the non-governing
  // constant would leave `publication_governing && note` as a live fallback.
  const line = governingLine({
    governing_verdict: null,
    publication_note:
      "This is the merge whose governing verdict the published quarterly " +
      "statistic uses for this pull request.",
  });
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
  assert.equal(caption, "not the governing merge");
  // The regression this exact equality exists to prevent: the caption used to
  // append `publication_note`, which `governingLine` ALSO returns, so a page
  // rendering both — the receipt screen renders both, by design — printed the
  // same sentence twice for every merge. A `.includes()` check here would pass
  // on the appending version.
  assert.equal(
    caption.includes("superseded by a later merge"),
    false,
    "the caption echoes the note governingLine already renders",
  );
});

test("the governing merge is named as governing", () => {
  const caption = mergeCaption(
    { publication_governing: true, publication_note: "governing merge" },
    2,
  );
  assert.equal(caption, "governs the published record");
});

test("a single merge needs no governing qualifier", () => {
  const caption = mergeCaption({ publication_governing: true, publication_note: "" }, 1);
  assert.equal(caption, "");
});
