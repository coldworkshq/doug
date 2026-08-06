import assert from "node:assert/strict";
import test from "node:test";

import { coveragePercent, jobDuration, relativeAge } from "./runs.ts";

const coverage = {
  diff_chars: 108200,
  sent_chars: 18400,
  files_sent: 4,
  files_unseen: ["api/doug/tenancy.py"],
  file_cut: "api/doug/api.py",
};

test("coveragePercent divides files_sent by changed_files, not by the fetched file list", () => {
  // The live defect this page exists to make visible: 4 of 23 files.
  // files_unseen holds 1 entry, so a naive files_sent/(sent+unseen) would
  // report 80% on a run that read 17% — and would be MOST wrong on the
  // large PRs where coverage matters most, because `files` is paginated
  // and can be short of the true count.
  const result = coveragePercent(coverage, 23);
  assert.equal(result.kind, "known");
  assert.equal(Math.round(result.pct), 17);
});

test("coveragePercent reports no-read rather than zero when there was no read", () => {
  // A deterministic run never opened the diff. Zero would claim Doug read
  // none of it, which is a different and false statement.
  assert.deepEqual(coveragePercent(null, 23), { kind: "no-read" });
});

test("coveragePercent refuses to invent a denominator", () => {
  // changed_files is null on rows predating its capture. 100% would be a
  // fabricated claim about how much Doug saw.
  assert.deepEqual(coveragePercent(coverage, null), { kind: "unknown-denominator" });
});

test("coveragePercent treats a zero or negative changed_files as unknown, not as a divide-by-zero", () => {
  // changed_files should never be 0 or negative in practice, but the type
  // only promises `number | null`. A bad value must render as "unknown",
  // never as Infinity% or a negative percentage.
  assert.deepEqual(coveragePercent(coverage, 0), { kind: "unknown-denominator" });
  assert.deepEqual(coveragePercent(coverage, -1), { kind: "unknown-denominator" });
});

test("coveragePercent flags a run below the low-coverage line", () => {
  assert.equal(coveragePercent(coverage, 23).low, true);
  assert.equal(coveragePercent({ ...coverage, files_sent: 20 }, 23).low, false);
});

test("coveragePercent never exceeds 100 even if files_sent overruns", () => {
  const result = coveragePercent({ ...coverage, files_sent: 30 }, 23);
  assert.equal(result.kind, "known");
  assert.equal(result.pct, 100);
});

test("relativeAge renders hours, days and weeks distinctly", () => {
  const now = new Date("2026-08-06T12:00:00Z");
  assert.equal(relativeAge("2026-08-06T10:00:00Z", now), "2h");
  assert.equal(relativeAge("2026-08-04T12:00:00Z", now), "2d");
  assert.equal(relativeAge("2026-07-16T12:00:00Z", now), "3w");
});

test("jobDuration renders seconds and minutes the way the mockup does", () => {
  assert.equal(jobDuration("2026-08-06T12:00:00Z", "2026-08-06T12:00:41Z"), "41s");
  assert.equal(jobDuration("2026-08-06T12:00:00Z", "2026-08-06T12:01:12Z"), "1m12s");
});

test("jobDuration refuses to guess when either timestamp is missing", () => {
  // A running or superseded-before-finish job has no finished_at yet — null
  // means "not measurable", never a fabricated 0s.
  assert.equal(jobDuration(null, "2026-08-06T12:00:41Z"), null);
  assert.equal(jobDuration("2026-08-06T12:00:00Z", null), null);
  assert.equal(jobDuration(null, null), null);
});
