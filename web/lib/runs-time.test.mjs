// Ported from console/lib/runs.test.mjs — the 8 tests covering the time and
// provenance half of console/lib/runs.ts. Names and comments are verbatim, so
// a divergence between the two suites is visible in a diff.
//
// Not ported: the 10 coveragePercent/coverageLabel tests (that half already
// lives in web/lib/coverage.ts) and the 2 parseTenantId tests (web's dashboard
// is scoped by session, not by a ?tenant= param — dashboard-contract.test.mjs
// pins that "tenant all" never appears).
import assert from "node:assert/strict";
import test from "node:test";

import {
  jobDuration,
  relativeAge,
  utcClock,
  utcDate,
  utcShortDate,
  utcTimestamp,
} from "./runs-time.ts";

test("relativeAge renders hours, days and weeks distinctly", () => {
  const now = new Date("2026-08-06T12:00:00Z");
  assert.equal(relativeAge("2026-08-06T10:00:00Z", now), "2h");
  assert.equal(relativeAge("2026-08-04T12:00:00Z", now), "2d");
  assert.equal(relativeAge("2026-07-16T12:00:00Z", now), "3w");
});

test("relativeAge treats a zoneless timestamp as UTC, never as the server's local time", () => {
  // The regression this test pins, for the ledger's age column specifically:
  // run_history's scored_at crosses the wire with no zone suffix on sqlite
  // (same store.py._utc() gap utcClock's zoneless test documents above).
  // `new Date(iso)` on that raw string parses it as LOCAL time — on a
  // UTC-behind server every row's "then" lands AFTER "now", the
  // Math.max(0, ...) clamp swallows the negative, and every row in the
  // table prints "0m" regardless of true age. Forcing a non-UTC TZ is what
  // makes this test catch that: on a UTC-default CI machine the bug would
  // pass by accident.
  const originalTz = process.env.TZ;
  process.env.TZ = "America/Los_Angeles"; // UTC-7 in August (PDT)
  try {
    const now = new Date("2026-08-06T12:00:00Z");
    assert.equal(relativeAge("2026-08-06T10:00:00", now), "2h");
  } finally {
    process.env.TZ = originalTz;
  }
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
