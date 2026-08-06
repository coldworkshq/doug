import assert from "node:assert/strict";
import test from "node:test";

import {
  coveragePercent,
  jobDuration,
  parseTenantId,
  relativeAge,
  utcClock,
  utcDate,
  utcShortDate,
  utcTimestamp,
} from "./runs.ts";

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

test("parseTenantId accepts a real installation id and is absent when there's no tenant param", () => {
  assert.deepEqual(parseTenantId(undefined), { kind: "absent" });
  assert.deepEqual(parseTenantId("150424894"), { kind: "present", id: 150424894 });
});

test("utcClock parses and normalizes to UTC rather than slicing the source string", () => {
  // A non-UTC offset must be converted, not read positionally: slicing
  // characters 11-19 out of "...T09:00:00+05:00" would print the source
  // timezone's clock digits and label them UTC, which is wrong by the
  // offset. Parsing first and re-serializing through toISOString() is what
  // makes this actually a UTC value rather than a lucky string position.
  assert.equal(utcClock("2026-08-06T09:00:00+05:00"), "04:00:00 UTC");
  assert.equal(utcClock("2026-08-06T14:22:07Z"), "14:22:07 UTC");
  assert.equal(utcClock(null), "—");
  assert.equal(utcClock("not a date"), "—");
});

test("utcClock treats a zoneless string as UTC, never as the server's local time", () => {
  // The regression this test exists to pin: run_detail's timestamps carry
  // NO zone suffix on sqlite (store.py's own _utc() docstring — "naive
  // means UTC, badly labelled" — is applied only to token rows, never
  // here), so `new Date(iso)` on the raw string parses it as LOCAL time
  // per ECMA-262 and would relabel that shifted value "UTC". Forcing a
  // non-UTC TZ here is what makes this test actually catch that: on a
  // UTC-default CI machine the bug would pass by accident.
  const originalTz = process.env.TZ;
  process.env.TZ = "America/Los_Angeles"; // UTC-7 in August (PDT)
  try {
    assert.equal(utcClock("2026-08-06T14:22:48"), "14:22:48 UTC");
    assert.equal(utcTimestamp("2026-08-06T14:22:48"), "2026-08-06 14:22:48 UTC");
  } finally {
    process.env.TZ = originalTz;
  }
});

test("utcTimestamp renders the full date and time, UTC-normalized", () => {
  assert.equal(utcTimestamp("2026-08-03T14:22:48Z"), "2026-08-03 14:22:48 UTC");
  assert.equal(utcTimestamp("2026-08-03T09:22:48-05:00"), "2026-08-03 14:22:48 UTC");
  // Falls back to the raw string rather than hiding a malformed value
  // behind a dash — this is the one place a caller has no null case to
  // fall through to (scored_at is a required field on RunDetail).
  assert.equal(utcTimestamp("not a date"), "not a date");
});

test("utcDate and utcShortDate convert to UTC before slicing, so a day boundary can't be read off the source's own digits", () => {
  // 2026-08-07T02:00:00+05:00 is 2026-08-06T21:00:00Z — a different
  // calendar date once actually converted. Slicing characters straight out
  // of the source string would print "2026-08-07" / "08-07", a day early.
  assert.equal(utcDate("2026-08-07T02:00:00+05:00"), "2026-08-06");
  assert.equal(utcShortDate("2026-08-07T02:00:00+05:00"), "08-06");
  assert.equal(utcDate("2026-08-17T09:00:00Z"), "2026-08-17");
  assert.equal(utcShortDate("2026-08-17T09:00:00Z"), "08-17");
  // Zoneless input is UTC, same regression utcClock pins above.
  assert.equal(utcDate("2026-08-06T00:30:00"), "2026-08-06");
});

test("parseTenantId rejects everything Number() would silently coerce to 0 or NaN", () => {
  // The coercion boundary that let a fabricated scope claim through:
  // Number("") and Number(" ") are both 0, which passes
  // Number.isInteger — and 0 is itself not a real installation id (never
  // negative, never zero, never fractional, never non-numeric).
  assert.deepEqual(parseTenantId(""), { kind: "invalid" });
  assert.deepEqual(parseTenantId(" "), { kind: "invalid" });
  assert.deepEqual(parseTenantId("0"), { kind: "invalid" });
  assert.deepEqual(parseTenantId("abc"), { kind: "invalid" });
  assert.deepEqual(parseTenantId("12.5"), { kind: "invalid" });
});
