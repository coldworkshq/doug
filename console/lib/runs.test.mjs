import assert from "node:assert/strict";
import test from "node:test";

import {
  coverageLabel,
  coveragePercent,
  jobDuration,
  outcomeLabel,
  outcomeTone,
  outcomeToneClass,
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

test("coverageLabel prints '<100%' rather than a false '100%' for a near-complete read", () => {
  // 199 of 200 files: true ratio 99.5%. Math.round alone prints "100%",
  // the same complete-read claim coveragePercent itself already refuses to
  // invent when the ratio isn't 100.0 exactly — the defect the Runs table
  // had and the forensics ruler didn't.
  const result = coveragePercent({ ...coverage, files_sent: 199 }, 200);
  assert.equal(result.kind, "known");
  assert.equal(coverageLabel(result), "<100%");
});

test("coverageLabel prints '<1%' rather than a false '0%' for a real but tiny read", () => {
  // 1 of 300 files: true ratio 0.33%. Math.round alone prints "0%", the
  // same nothing-was-read claim "no read" exists to distinguish itself
  // from — the defect the forensics ruler had and the Runs table didn't.
  const result = coveragePercent({ ...coverage, files_sent: 1 }, 300);
  assert.equal(result.kind, "known");
  assert.equal(coverageLabel(result), "<1%");
});

test("coverageLabel prints exactly '100%' and '0%' at the true boundaries", () => {
  assert.equal(coverageLabel(coveragePercent({ ...coverage, files_sent: 23 }, 23)), "100%");
  assert.equal(coverageLabel(coveragePercent({ ...coverage, files_sent: 0 }, 23)), "0%");
});

test("coverageLabel renders a dash for the non-known results", () => {
  assert.equal(coverageLabel({ kind: "no-read" }), "—");
  assert.equal(coverageLabel({ kind: "unknown-denominator" }), "—");
});

test("relativeAge renders minutes for durations under 1 hour", () => {
  const now = new Date("2026-08-06T12:00:00Z");
  assert.equal(relativeAge("2026-08-06T12:00:00Z", now), "0m");
  assert.equal(relativeAge("2026-08-06T11:55:00Z", now), "5m");
  assert.equal(relativeAge("2026-08-06T11:01:00Z", now), "59m");
});

test("relativeAge renders hours, days and weeks distinctly", () => {
  const now = new Date("2026-08-06T12:00:00Z");
  assert.equal(relativeAge("2026-08-06T10:00:00Z", now), "2h");
  assert.equal(relativeAge("2026-08-04T12:00:00Z", now), "2d");
  assert.equal(relativeAge("2026-07-16T12:00:00Z", now), "3w");
});

test("relativeAge clamps future timestamps to 0m", () => {
  const now = new Date("2026-08-06T12:00:00Z");
  assert.equal(relativeAge("2026-08-06T13:00:00Z", now), "0m");
  assert.equal(relativeAge("2026-08-10T12:00:00Z", now), "0m");
});

test("relativeAge boundary thresholds transition correctly across time units", () => {
  const now = new Date("2026-08-06T12:00:00Z");
  // 3599 seconds ago: < 3600 seconds, so rendered in minutes (Math.round(3599/60) = 60m)
  assert.equal(relativeAge("2026-08-06T11:00:01Z", now), "60m");
  // Exactly 3600 seconds (1 hour): >= 3600 seconds, rendered in hours
  assert.equal(relativeAge("2026-08-06T11:00:00Z", now), "1h");
  // 86399 seconds ago: < 86400 seconds, so rendered in hours (Math.round(86399/3600) = 24h)
  assert.equal(relativeAge("2026-08-05T12:00:01Z", now), "24h");
  // Exactly 86400 seconds (1 day): >= 86400 seconds, rendered in days
  assert.equal(relativeAge("2026-08-05T12:00:00Z", now), "1d");
  // 604799 seconds ago: < 604800 seconds, rendered in days (Math.round(604799/86400) = 7d)
  assert.equal(relativeAge("2026-07-30T12:00:01Z", now), "7d");
  // Exactly 604800 seconds (1 week): >= 604800 seconds, rendered in weeks
  assert.equal(relativeAge("2026-07-30T12:00:00Z", now), "1w");
});

test("relativeAge handles ISO strings with explicit time zone offsets", () => {
  const now = new Date("2026-08-06T12:00:00Z");
  // 2026-08-06T14:00:00+02:00 is 2026-08-06T12:00:00Z (0m difference)
  assert.equal(relativeAge("2026-08-06T14:00:00+02:00", now), "0m");
  // 2026-08-06T05:00:00-05:00 is 2026-08-06T10:00:00Z (2h ago)
  assert.equal(relativeAge("2026-08-06T05:00:00-05:00", now), "2h");
});

test("relativeAge defaults to current time when now parameter is omitted", () => {
  const fiveMinsAgoIso = new Date(Date.now() - 5 * 60 * 1000).toISOString();
  assert.equal(relativeAge(fiveMinsAgoIso), "5m");
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

test("outcomeTone treats an unobserved outcome as neutral, not as a miss", () => {
  // The production vocabulary is exactly revert | clean | censored
  // (api/doug/adjudicate.py's OutcomeKind). The column also permits hotfix,
  // which the adjudicator deliberately never writes — §10 rules a hotfix is
  // not a miss and that no detector here can tell one repairing this PR
  // apart from one merely following it — so a row carrying it is unexplained
  // and flags.
  assert.equal(outcomeTone("clean"), "clear");
  assert.equal(outcomeTone("revert"), "flag");
  assert.equal(outcomeTone("hotfix"), "flag");
  // The assertion this whole rule exists for. `censored` records that the PR
  // left the risk set UNOBSERVED — merged off the branch the treeless
  // single-branch clone can see, or no clone reachable at all
  // (adjudicate.py's CensorReason). The console painted it in the flag
  // colour, which asserts a bad outcome the ledger does not record.
  assert.equal(outcomeTone("censored"), "neutral");
  // An unrecognised kind flags. An allowlist here — anything-but-revert
  // reads as fine — is what would let a genuinely bad new outcome arrive
  // looking like nothing.
  assert.equal(outcomeTone("graded-miss"), "flag");
  assert.equal(outcomeTone("unknown-future-kind"), "flag");
  // No outcome row at all: the window has not closed. The one honest neutral
  // the console already got right.
  assert.equal(outcomeTone(null), "neutral");
});

test("outcomeToneClass keeps neutral out of the two data colours", () => {
  // globals.css: "The two data colours. NEVER add a third" — the CVD rule.
  // Neutral is the absence of a data colour, not a new one, so it takes the
  // same muted foreground the pending tile already uses.
  assert.equal(outcomeToneClass("clear"), "data-clear");
  assert.equal(outcomeToneClass("flag"), "data-flag");
  assert.equal(outcomeToneClass("neutral"), "text-muted-foreground");
  // Pinned as a set, not just per-case: a third data-* colour must not be
  // reachable from any tone this module can return.
  const emitted = ["clear", "flag", "neutral"].map(outcomeToneClass);
  assert.deepEqual(
    emitted.filter((className) => className.startsWith("data-")).sort(),
    ["data-clear", "data-flag"],
  );
});

test("outcomeLabel withholds the revert glyph from every kind that is not a revert", () => {
  // ↩ is the revert glyph and it carries a claim. Wearing it is a statement
  // that this PR was reverted, so only a `revert` row may.
  assert.equal(outcomeLabel("revert"), "↩ revert");
  assert.equal(outcomeLabel("clean"), "✓ clean");
  // Censored is a non-observation, so it takes a muted marker from the same
  // hollow-circle family as `◷ pending` — the console's existing precedent
  // for "the ledger is not claiming anything here". It is NOT `◷`: that
  // would say the window is still running, and this one has closed.
  assert.equal(outcomeLabel("censored"), "○ censored");
  // Flagged but not a revert: the colour carries "bad outcome", the word
  // carries which kind, and no glyph invents a revert that was never
  // recorded. hotfix is the permitted-but-never-written case; the last two
  // are kinds this build has never heard of.
  assert.equal(outcomeLabel("hotfix"), "hotfix");
  assert.equal(outcomeLabel("graded-miss"), "graded-miss");
  assert.equal(outcomeLabel("unknown-future-kind"), "unknown-future-kind");
  // No row yet — the table's existing pending label, unchanged.
  assert.equal(outcomeLabel(null), "◷ pending");
});
