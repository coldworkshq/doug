// The lens is a VIEW, not a setting. The needs-you line is a server-side env
// var (api/doug/scoring.py:21, DOUG_THRESHOLD, default 0.62) stamped onto each
// verdict row at scoring time (api/doug/store.py:74). Nothing here changes what
// Doug did; it re-derives a band from a score Doug already recorded, against a
// line the reader chose.
//
// Tested as pure functions rather than by rendering, for the reason
// dashboard-view.test.mjs gives about the rest of the dashboard's controls.
import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);
const { applyLens, parseThresholdLens, rebandedCount, serializeThresholdLens } =
  await import("./threshold-lens.ts");

function run(overrides) {
  return {
    verdict_id: 1,
    repo: "drewjst/doug",
    installation_id: 150424894,
    github_repo_id: 1,
    pr_number: 56,
    title: "route read budget by file tier",
    url: null,
    scored_at: "2026-08-05T10:00:00",
    tier: "code",
    source: "app",
    score: 0.38,
    band: "flagged",
    threshold: 0.3,
    coverage: null,
    changed_files: null,
    finding_counts: { total: 0, high: 0, medium: 0, low: 0 },
    job: null,
    outcome_14: null,
    ...overrides,
  };
}

test("a missing or blank lens is no lens, not a lens of zero", () => {
  // A lens of 0 flags EVERY run (score >= 0 always). Defaulting a missing
  // param to 0 would turn a bare /dashboard into a ledger where everything
  // needs you — the loudest possible way to be wrong.
  assert.equal(parseThresholdLens(undefined), null);
  assert.equal(parseThresholdLens(""), null);
  assert.equal(parseThresholdLens("   "), null);
});

test("a lens that is not a number in range is no lens, never an error page", () => {
  // Same rule parseFacetSelection documents: unreadable input is absent input.
  // A stale or hand-edited link must render the ledger, not a stack trace.
  for (const raw of ["abc", "0.5.1", "NaN", "Infinity", "-0.1", "1.1", "62", "1e3"]) {
    assert.equal(parseThresholdLens(raw), null, `${raw} was accepted as a lens`);
  }
});

test("the lens range is the score range, endpoints included", () => {
  // Scores are 0..1 (api/doug/scoring.py caps total at 0.99; reader.py divides
  // risk_score by 100). Both endpoints are legitimate lenses: 0 means "flag
  // everything", 1 means "flag nothing this ledger can reach".
  assert.equal(parseThresholdLens("0"), 0);
  assert.equal(parseThresholdLens("1"), 1);
  assert.equal(parseThresholdLens("0.3"), 0.3);
  assert.equal(parseThresholdLens("0.62"), 0.62);
});

test("no lens is the identity, and returns the same array", () => {
  // The default render must be bit-for-bit what it was before this module
  // existed. Returning the input array (not a copy) makes that structural, not
  // a claim: nothing downstream can observe a difference that does not exist.
  const rows = [run({}), run({ verdict_id: 2, score: 0.1, band: "cleared" })];
  assert.equal(applyLens(rows, null), rows);
});

test("the lens re-bands from the recorded score, and flags a run sitting exactly on the line", () => {
  // >= , matching api/doug/scoring.py:146 and api/doug/reader.py:957 rather
  // than inventing a second convention for the same comparison.
  const rows = [
    run({ verdict_id: 1, score: 0.4, band: "cleared" }),
    run({ verdict_id: 2, score: 0.3, band: "cleared" }),
    run({ verdict_id: 3, score: 0.29, band: "flagged" }),
  ];
  const lensed = applyLens(rows, 0.3);
  assert.deepEqual(lensed.map((r) => r.band), ["flagged", "flagged", "cleared"]);
  // ...and the score itself is never touched. The lens changes the verdict the
  // VIEW draws, never the measurement it draws it from.
  assert.deepEqual(lensed.map((r) => r.score), [0.4, 0.3, 0.29]);
});

test("applyLens does not mutate its input, so the evidence pane can still be fed the truth", () => {
  // This is the property that keeps the run detail honest. page.tsx resolves
  // the selected summary from the UNLENSED array; that only stays possible
  // while the lens copies rather than writes through.
  const rows = [run({ score: 0.4, band: "cleared" })];
  applyLens(rows, 0.3);
  assert.equal(rows[0].band, "cleared");
});

test("rebandedCount counts only the rows the lens actually moved", () => {
  // The banner prints this number. Counting rows the lens AGREED with would
  // overstate the lens's effect and make an honest banner into a scary one.
  const before = [
    run({ verdict_id: 1, score: 0.4, band: "cleared" }),
    run({ verdict_id: 2, score: 0.4, band: "flagged" }),
    run({ verdict_id: 3, score: 0.1, band: "cleared" }),
  ];
  const after = applyLens(before, 0.3);
  assert.equal(rebandedCount(before, after), 1);
  // NOT `rebandedCount(before, before)` — comparing an array to itself makes
  // `before[i].band !== before[i].band` false for every i under ANY
  // implementation, even one that (wrongly) compares object identity instead
  // of `.band`, so it cannot fail no matter what the function does. A
  // hand-built copy — new objects, identical bands — actually exercises the
  // "nothing moved" path: it would also catch an implementation that compared
  // `before[i] !== after[i]` instead of their `.band` fields.
  const unmoved = before.map((row) => ({ ...row }));
  assert.equal(rebandedCount(before, unmoved), 0);
});

test("the default-shaped lens still round-trips through the URL", () => {
  // Unlike sort, there is no "default" threshold to omit: the server's line is
  // per-verdict and this page never knows a single one, so ANY lens is a
  // deliberate choice and every one of them is written.
  assert.equal(serializeThresholdLens(null), null);
  assert.equal(serializeThresholdLens(0.3), "0.3");
  assert.equal(serializeThresholdLens(0), "0");
  assert.equal(parseThresholdLens(serializeThresholdLens(0.62)), 0.62);
});
