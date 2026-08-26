// Ported from console/lib/runs.test.mjs — the 8 tests covering the time and
// provenance half of console/lib/runs.ts. Names and comments are verbatim, so
// a divergence between the two suites is visible in a diff.
//
// Not ported: the 10 coveragePercent/coverageLabel tests (that half already
// lives in web/lib/coverage.ts) and the 2 parseTenantId tests (web's dashboard
// is scoped by session, not by a ?tenant= param — dashboard-contract.test.mjs
// pins that "tenant all" never appears).
//
// NOT count-enforced, unlike the other ported test files: lib/console-lockstep.test.mjs
// skips console/lib/runs.test.mjs because web splits it across this file and
// coverage.test.mjs, and that second file is Phase A's (2 tests against
// console's 10 — a real gap, reported, not something to assert away). The
// BEHAVIOUR of both modules is enforced there; only the test count is not.
import assert from "node:assert/strict";
import test from "node:test";

import {
  jobDuration,
  outcomeLabel,
  outcomeMeaning,
  outcomeToneClass,
  outcomeWindowHint,
  relativeAge,
  utcClock,
  utcDate,
  utcShortDate,
  utcTimestamp,
} from "./runs-time.ts";

test("the neutral tone is the ABSENCE of a data colour, never a third one", () => {
  // This is the assertion dashboard-contract.test.mjs:62-64 used to make
  // against the deleted CSS module's .outcomeClear/.outcomeFlag/.outcomeNeutral
  // rules. Same three-way rule, same intent, now on the function that decides
  // it: `censored` and "no outcome yet" record that nothing was OBSERVED, and
  // painting a non-observation in the miss colour is the honesty failure the
  // tone rule exists to refuse.
  assert.equal(outcomeToneClass("clear"), "data-clear");
  assert.equal(outcomeToneClass("flag"), "data-flag");
  assert.equal(outcomeToneClass("neutral"), "text-muted-foreground");
  // Stated as its own assertion because the equality above could be satisfied
  // by any string: neutral must never reach for either data colour.
  assert.equal(outcomeToneClass("neutral").includes("data-flag"), false);
  assert.equal(outcomeToneClass("neutral").includes("data-clear"), false);
});

test("the revert glyph is rationed to a recorded revert", () => {
  // The glyph carries a claim. `↩` says "this PR was reverted" and belongs to
  // `revert` alone — a flagged kind that is not a revert takes the flag colour
  // and its own word, with no marker asserting a revert the ledger never
  // recorded. `◷ pending` (no row yet) and `○ censored` (window closed with
  // nothing observable) are different facts and read differently.
  assert.equal(outcomeLabel(null), "◷ pending");
  assert.equal(outcomeLabel("clean"), "✓ clean");
  assert.equal(outcomeLabel("censored"), "○ censored");
  assert.equal(outcomeLabel("revert"), "↩ revert");
  // An unknown kind is rendered as itself — never given a glyph that would
  // assert a revert, and never swallowed by a fallback that hides it.
  assert.equal(outcomeLabel("hotfix"), "hotfix");
  assert.equal(outcomeLabel("unknown-future-kind"), "unknown-future-kind");
  assert.equal(outcomeLabel("hotfix").includes("↩"), false);
});

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

// ---------------------------------------------------------------------------
// outcomeMeaning / outcomeWindowHint — the ⓘ's text. NOT ported from console;
// added with the affordance and then ported the other way, into
// console/lib/runs.ts. console-lockstep.test.mjs runs both copies over the
// same vocabulary, so the two ledgers cannot explain the same word differently.
// ---------------------------------------------------------------------------

test("every outcome sentence names the window it is talking about", () => {
  // The whole reason 14d and 60d are two columns is that the same word means a
  // different thing in each. A definition that did not say which window it was
  // defining would hand that ambiguity straight back — one tooltip, two
  // columns, no way to tell which one it just described.
  for (const kind of [null, "clean", "revert", "censored", "hotfix"]) {
    assert.match(outcomeMeaning(kind, 14), /\b14 days\b/, `14-day sentence for ${kind}`);
    assert.match(outcomeMeaning(kind, 60), /\b60 days\b/, `60-day sentence for ${kind}`);
    // …and it must not print the OTHER window's number, which is what a
    // hardcoded sentence would do the moment one call site passed the wrong one.
    assert.equal(/\b60 days\b/.test(outcomeMeaning(kind, 14)), false);
  }
});

test("a window the row never recorded is described as one, not printed as null", () => {
  // RunDetail.outcomes[].window_days is nullable — rows written before the
  // outcome-loop identity migration carry NULL, and the detail tile already
  // renders those as "window not recorded". The sentence beside it must not
  // read "the null days after this pull request merged".
  const sentence = outcomeMeaning("clean", null);
  assert.equal(sentence.includes("null"), false);
  assert.match(sentence, /outcome window after this pull request merged/);
});

test("clean is stated as the absence of a revert, never as the absence of defects", () => {
  // THE MISREADING THIS AFFORDANCE EXISTS TO FIX, and the one that costs
  // trust: "clean" is a fact about what did not happen on one branch inside
  // one window, and a reader who takes it as "no bugs" over-trusts the whole
  // ledger. The sentence has to refuse that reading out loud, not merely
  // avoid asserting it.
  const sentence = outcomeMeaning("clean", 14);
  assert.match(sentence, /no revert/i);
  assert.match(sentence, /not that the code was free of defects/i);
});

test("pending says the clock is unfinished, not the review", () => {
  // The other half of the same defect, in the other direction: an operator who
  // reads "pending" as "Doug has not looked at this yet" goes hunting for
  // review work that is already done and scored. Every row in the ledger HAS a
  // verdict — that is what puts it in the ledger.
  const sentence = outcomeMeaning(null, 60);
  assert.match(sentence, /review is already done/i);
});

test("censored is neither a pass nor a miss, and says so", () => {
  // Same rule outcomeTone follows by giving it the NEUTRAL tone (#93): the
  // window closed with nothing observable in it. A definition that let it read
  // as either side would undo in prose what the colour rule protects.
  const sentence = outcomeMeaning("censored", 14);
  assert.match(sentence, /not a pass and not a miss/i);
});

test("an unknown kind is reported as unexplained, never given an invented meaning", () => {
  // outcomeTone FLAGS a kind this build has never heard of rather than
  // allowlisting the three it knows, because an allowlist is how a genuinely
  // bad outcome arrives looking neutral. Explaining one would be the same
  // defect in prose — a confident sentence about a word nobody defined.
  const sentence = outcomeMeaning("graded-miss", 14);
  assert.match(sentence, /graded-miss/);
  assert.match(sentence, /no explanation for that word/i);
});

test("the column hint carries the whole vocabulary, not just the word under the cursor", () => {
  // The ⓘ sits on the HEADER, where no single row's value is in play. It is
  // read by someone who has not hovered a cell yet, so it has to define every
  // word the column can show — including the two that are rare enough that a
  // reader will meet them for the first time as a surprise.
  const hint = outcomeWindowHint(14);
  for (const word of ["Clean:", "Revert:", "Censored:", "Pending:"]) {
    assert.match(hint, new RegExp(word), `the 14d hint never defines ${word}`);
  }
  // It must also say what the column IS before defining what it can say, and
  // that the number is not an input to the score — the outcome is observed
  // after the fact by a different loop entirely.
  assert.match(hint, /not an input to the score/i);
  assert.equal(/\b60 days\b/.test(hint), false, "the 14d hint quotes the 60-day window");
});
