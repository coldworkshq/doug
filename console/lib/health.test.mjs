import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  OUTCOME_BAR_FALLBACK_SECONDS,
  REVIEW_BAR_FALLBACK_SECONDS,
  resolveBar,
  classify,
  overdueReason,
  pendingReason,
} from "./health.ts";

// The fallbacks, in the units the assertions below think in. `payload()`
// deliberately omits `liveness_bar_seconds`, so every test that does not set
// one exercises the fallback path and these two are the bars in force.
const PENDING_THRESHOLD_MINUTES = REVIEW_BAR_FALLBACK_SECONDS / 60;
const ADJUDICATOR_GRACE_HOURS = OUTCOME_BAR_FALLBACK_SECONDS / 3_600;

const AS_OF = "2026-08-07T12:00:00Z";

function payload(overrides = {}) {
  return {
    review: {
      pending: 0,
      oldest_pending_at: null,
      retrying: 0,
      oldest_retry_at: null,
      running: 0,
      stalled: 0,
      failed: 0,
      failed_24h: 0,
      stall_lease_seconds: 900,
      max_attempts: 3,
      ...(overrides.review ?? {}),
    },
    outcome: {
      pending: 0,
      overdue: 0,
      next_due_at: null,
      oldest_overdue_due_at: null,
      running: 0,
      stalled: 0,
      failed: 0,
      stall_lease_seconds: 7200,
      max_attempts: 10,
      ...(overrides.outcome ?? {}),
    },
    as_of: overrides.as_of ?? AS_OF,
  };
}

/** Minutes before as_of, as an ISO string. */
function ago(minutes) {
  return new Date(Date.parse(AS_OF) - minutes * 60_000).toISOString();
}

test("an unreachable API is unknown, never clear", () => {
  // The worst possible outcome for this surface: converting "I do not know"
  // into "everything is fine" on the one page built to prevent exactly that.
  const verdict = classify({ error: "/v1/health → HTTP 503" });
  assert.equal(verdict.level, "unknown");
  assert.notEqual(verdict.level, "clear");
  // No cell may claim a count it does not have.
  assert.ok(verdict.cells.every((c) => c.count === null));
});

test("a quiet ledger is clear, and clear is not unknown", () => {
  const verdict = classify(payload());
  assert.equal(verdict.level, "clear");
  // Zero is a real measurement and renders as one.
  assert.equal(verdict.cells.find((c) => c.key === "failed").count, 0);
});

test("a terminal failure is failing, not degraded", () => {
  // attempts >= max: Doug gave up, and nothing in the system retries it.
  assert.equal(classify(payload({ review: { failed: 2 } })).level, "failing");
});

test("a stalled claim is degraded, because reclaim_stalled heals it", () => {
  // worker.drain calls ingest.reclaim_stalled() before its first claim, so
  // the next webhook or cold start re-pends this row without spending an
  // attempt. Real, but not the same alarm as a terminal failure.
  assert.equal(classify(payload({ review: { running: 1, stalled: 1 } })).level, "degraded");
});

test("a job pending past the threshold is degraded; one under it is clear", () => {
  // The threshold has to bite in BOTH directions or it is decoration.
  const over = payload({
    review: { pending: 1, oldest_pending_at: ago(PENDING_THRESHOLD_MINUTES + 1) },
  });
  const under = payload({
    review: { pending: 1, oldest_pending_at: ago(PENDING_THRESHOLD_MINUTES - 1) },
  });
  assert.equal(classify(over).level, "degraded");
  assert.equal(classify(under).level, "clear");
});

test("ages are measured against as_of, never the client clock", () => {
  // A skewed browser must not invent or suppress an alarm. Same payload,
  // same relative age, as_of moved a year forward: the verdict cannot move.
  const shifted = payload({
    as_of: "2027-08-07T12:00:00Z",
    review: {
      pending: 1,
      oldest_pending_at: new Date(
        Date.parse("2027-08-07T12:00:00Z") - (PENDING_THRESHOLD_MINUTES + 1) * 60_000,
      ).toISOString(),
    },
  });
  assert.equal(classify(shifted).level, "degraded");
});

test("an outcome clock overdue inside the grace is not an alarm", () => {
  // The adjudicator fires daily, so any clock can be legitimately overdue
  // for most of a day. Without grace this is red every single day and is
  // ignored inside a week.
  const inside = payload({
    outcome: {
      pending: 1,
      overdue: 1,
      oldest_overdue_due_at: new Date(
        Date.parse(AS_OF) - (ADJUDICATOR_GRACE_HOURS - 1) * 3_600_000,
      ).toISOString(),
    },
  });
  assert.equal(classify(inside).level, "clear");
});

test("an outcome clock overdue past the grace is failing", () => {
  // Past this, a scheduled fire was genuinely missed.
  const outside = payload({
    outcome: {
      pending: 1,
      overdue: 1,
      oldest_overdue_due_at: new Date(
        Date.parse(AS_OF) - (ADJUDICATOR_GRACE_HOURS + 1) * 3_600_000,
      ).toISOString(),
    },
  });
  assert.equal(classify(outside).level, "failing");
});

test("each lane's stall is measured against its own lease", () => {
  // ingest is 900s, outcome_queue is 7200s. The server already applied both
  // when it set the stalled counts; classify must not re-derive them against
  // one shared number.
  const verdict = classify(
    payload({ outcome: { running: 1, stalled: 0 }, review: { running: 1, stalled: 1 } }),
  );
  assert.equal(verdict.level, "degraded");
  assert.equal(verdict.cells.find((c) => c.key === "stalled").count, 1);
});

test("every cell carries a word, so colour is never the only carrier", () => {
  // Red already means "this PR needs a human" in the band column. A
  // greyscale or colour-blind read of this strip must lose nothing.
  for (const cell of classify(payload()).cells) {
    assert.ok(cell.word.length > 0, `cell ${cell.key} has no word`);
  }
});

test("a zoneless lane timestamp is treated as UTC, matching parseUtc's convention elsewhere", () => {
  // job_health's lane timestamps (oldest_pending_at, oldest_retry_at,
  // oldest_overdue_due_at, next_due_at) come from raw MIN() queries in
  // store.py that skip _as_utc, so on sqlite they cross the wire with no
  // zone suffix at all -- the same gap runs.ts's parseUtc exists to close
  // (see its own docstring's repro: `TZ=America/Los_Angeles node -e
  // 'new Date("2026-08-06T14:22:48").toISOString()'` -> a 7-hour shift).
  //
  // as_of itself is always server-tz-aware (store._db_now()), so the
  // realistic mismatch this pins is a ZONELESS `at` measured against a
  // Z-suffixed `as_of` -- pairing two zoneless values together would let
  // the same local-offset shift cancel out of the subtraction and pass
  // even under the bug (verified: raw Date.parse on two zoneless
  // timestamps 16 minutes apart still reports a 16-minute gap under
  // TZ=America/Los_Angeles). Forcing a non-UTC TZ here, on the mismatched
  // pair, is what makes this test actually catch it: on a UTC-default CI
  // machine, or on a matched-zoneless pair, the bug would pass by accident.
  const originalTz = process.env.TZ;
  process.env.TZ = "America/Los_Angeles"; // UTC-7 in August (PDT)
  try {
    const zoneless = payload({
      review: {
        pending: 1,
        // One minute past the bar in force, with no trailing "Z" -- exactly
        // what sqlite hands back for this field. Derived from the bar rather
        // than written out, so moving the bar cannot leave this test
        // asserting a shift it no longer produces.
        oldest_pending_at: ago(PENDING_THRESHOLD_MINUTES + 1).replace("Z", ""),
      },
    });
    assert.equal(classify(zoneless).level, "degraded");
  } finally {
    process.env.TZ = originalTz;
  }
});

// Row labels. These live here, beside the two thresholds they compare
// against, rather than in jobs-table.tsx — that component has no test
// infrastructure, and the defect they close is precisely the /jobs table and
// the health strip disagreeing about the same row. Co-locating each labeller
// with its threshold is what stops the two drifting apart again.

test("a freshly enqueued job is not labelled as undrained", () => {
  // store.job_rows' unhealthy predicate has no threshold — it returns every
  // pending row, including one enqueued a second ago. The strip waits
  // PENDING_THRESHOLD_MINUTES before calling that degraded. Without this
  // split the table shouts about a job the strip calls clear.
  const at = new Date(Date.parse(AS_OF) - (PENDING_THRESHOLD_MINUTES - 1) * 60_000).toISOString();
  assert.equal(pendingReason(at, AS_OF), `pending ${PENDING_THRESHOLD_MINUTES - 1}m`);
});

test("a job pending past the threshold says the drain did not take it", () => {
  const at = new Date(Date.parse(AS_OF) - (PENDING_THRESHOLD_MINUTES + 1) * 60_000).toISOString();
  assert.equal(pendingReason(at, AS_OF), `not drained ${PENDING_THRESHOLD_MINUTES + 1}m`);
});

test("the pending threshold bites in both directions", () => {
  // A label whose wording never changes is decoration. Same row, two clocks.
  const at = new Date(Date.parse(AS_OF) - (PENDING_THRESHOLD_MINUTES - 1) * 60_000).toISOString();
  const later = new Date(Date.parse(AS_OF) + 2 * 60_000).toISOString();
  assert.ok(pendingReason(at, AS_OF).startsWith("pending"));
  assert.ok(pendingReason(at, later).startsWith("not drained"));
});

test("an overdue clock inside the grace reads neutral, past it reads alarming", () => {
  // The same boundary the strip applies, so the two cannot disagree.
  const inside = new Date(
    Date.parse(AS_OF) - (ADJUDICATOR_GRACE_HOURS - 1) * 3_600_000,
  ).toISOString();
  const outside = new Date(
    Date.parse(AS_OF) - (ADJUDICATOR_GRACE_HOURS + 1) * 3_600_000,
  ).toISOString();
  assert.ok(overdueReason(inside, AS_OF).startsWith("overdue"));
  assert.ok(overdueReason(outside, AS_OF).startsWith("clock overdue"));
});

test("no clock means no age and no verdict, never a fabricated one", () => {
  // asOf comes from the health payload, fetched independently of the rows,
  // so it can be absent while the rows load fine. Same discipline as the
  // attempts cap: degrade to the bare word rather than invent a duration.
  assert.equal(pendingReason("2026-08-07T11:00:00Z", null), "pending");
  assert.equal(overdueReason("2026-08-07T11:00:00Z", null), "overdue");
  assert.equal(pendingReason(null, AS_OF), "pending");
  assert.equal(overdueReason(null, AS_OF), "overdue");
});

test("row labels parse zoneless timestamps as UTC, like everything else here", () => {
  // job_rows' enqueued_at and due_at reach the client the same way the
  // health payload's lane timestamps do. A second parser here would let a
  // row's label disagree with the strip's verdict about the same instant.
  const originalTz = process.env.TZ;
  process.env.TZ = "America/Los_Angeles"; // UTC-7 in August (PDT)
  try {
    // Comfortably past the bar in force, and derived from it for the same
    // reason as the strip test above.
    const minutes = PENDING_THRESHOLD_MINUTES + 10;
    const zoneless = ago(minutes).replace("Z", "");
    assert.equal(pendingReason(zoneless, AS_OF), `not drained ${minutes}m`);
  } finally {
    process.env.TZ = originalTz;
  }
});


// --- The bars come from the API (doug#121) -----------------------------
//
// Before this, the strip held its own bar: 15 minutes against the route's
// 30. A review job pending 20 minutes read `degraded` here while
// /healthz/queues answered 200 and the pager stayed silent. Two surfaces
// disagreeing about one contradiction is the defect #121 exists to close —
// an operator who learns the strip cries wolf stops reading it, and a strip
// nobody reads is the 2026-08-16 outage again.

test("the fallback bars are the API's bars, to the second", async () => {
  // A SOURCE-TEXT PIN, and the only mechanism that can hold two languages
  // to one number. `api/doug/api.py` owns the bars — /healthz/queues serves
  // them and the Cloud Monitoring uptime check pages on them — and these
  // constants are a copy used only when the API did not answer with one. A
  // copy nothing checks is how the 15-vs-30 split happened in the first
  // place.
  //
  // Mutation proof: change either constant in lib/health.ts without
  // changing api.py (or the reverse) and this fails naming both values.
  const api = await readFile(new URL("../../api/doug/api.py", import.meta.url), "utf8");
  const read = (name) => {
    const match = api.match(new RegExp(`^${name} = ([^#\n]+)`, "m"));
    assert.ok(match, `${name} is gone from api/doug/api.py — the bar moved or was renamed`);
    // The API writes these as arithmetic ("30 * 60", "26 * 3600") because
    // the units are the point. Evaluate the product rather than pinning the
    // spelling, so a rewrite as "1800" is not a false failure.
    //
    // Any number of factors, and Python's underscore separators stripped:
    // this module writes `26 * 3_600` itself, and `Number("3_600")` is NaN.
    // A parser that quietly dropped a factor would fail while the two values
    // AGREED — a false alarm on the test whose whole job is telling drift
    // from agreement.
    const factors = match[1].trim().split("*").map((part) => Number(part.trim().replace(/_/g, "")));
    assert.ok(
      factors.length > 0 && factors.every(Number.isFinite),
      `cannot read ${name} from "${match[1].trim()}" — this parser handles a product of integer literals`,
    );
    return factors.reduce((a, b) => a * b, 1);
  };
  assert.equal(
    REVIEW_BAR_FALLBACK_SECONDS,
    read("REVIEW_PENDING_LIVENESS_SECONDS"),
    "the console's review-lane fallback has drifted from the bar the pager uses",
  );
  assert.equal(
    OUTCOME_BAR_FALLBACK_SECONDS,
    read("OUTCOME_OVERDUE_LIVENESS_SECONDS"),
    "the console's outcome-lane fallback has drifted from the bar the pager uses",
  );
});

test("a served bar governs, so the strip grades what the pager grades", () => {
  // The bar the API sends wins over the copy. Proven with a bar the copy
  // could never produce: at 60 minutes a 45-minute-old pending row is
  // clear, where the 30-minute fallback would call it degraded. If the
  // served value were ignored, this reads "degraded" and fails.
  const served = classify(
    payload({ review: { pending: 1, oldest_pending_at: ago(45), liveness_bar_seconds: 3_600 } }),
  );
  assert.equal(served.level, "clear");

  // And the other direction: a tighter served bar makes a row degraded that
  // the fallback would wave through.
  const tight = classify(
    payload({ review: { pending: 1, oldest_pending_at: ago(10), liveness_bar_seconds: 300 } }),
  );
  assert.equal(tight.level, "degraded");
});

test("a nonsense bar degrades to the copy, never to itself", () => {
  // 0 grades every pending row as broken; a negative grades nothing as
  // broken — which is SILENCE, the exact thing this surface exists to end.
  // A malformed payload must land on the known-good copy in both
  // directions, not on whatever arrived.
  for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY, "1800", null, undefined]) {
    assert.equal(
      resolveBar({ liveness_bar_seconds: bad }, REVIEW_BAR_FALLBACK_SECONDS),
      REVIEW_BAR_FALLBACK_SECONDS,
      `a served bar of ${String(bad)} must not be honoured`,
    );
  }
  assert.equal(resolveBar(undefined, REVIEW_BAR_FALLBACK_SECONDS), REVIEW_BAR_FALLBACK_SECONDS);
  assert.equal(resolveBar({ liveness_bar_seconds: 42 }, REVIEW_BAR_FALLBACK_SECONDS), 42);
});

test("the clocks sentence names the bar in force, not a literal", () => {
  // "no adjudicator pass in over 26h" is a falsifiable claim. When the
  // adjudicator's schedule changes the API's bar moves, and a hardcoded 26
  // would render that claim false on the one surface built to be trusted
  // about silence.
  const verdict = classify(
    payload({
      outcome: {
        pending: 1,
        overdue: 1,
        oldest_overdue_due_at: new Date(Date.parse(AS_OF) - 20 * 3_600_000).toISOString(),
        liveness_bar_seconds: 12 * 3_600,
      },
    }),
  );
  const clocks = verdict.cells.find((c) => c.key === "clocks");
  assert.equal(verdict.level, "failing");
  assert.equal(clocks.detail, "no adjudicator pass in over 12h");
});

test("the clocks sentence understates a fractional bar rather than overstating it", () => {
  // "in over Nh" is a claim, so N must never exceed the bar. Rounding made
  // a 90-minute bar say "over 2h" — false — and anything under half an hour
  // say "over 0h", which is not a claim at all. Both are the falsifiable-
  // but-false sentence the code comment above warns against.
  const at = (secondsAgo) =>
    new Date(Date.parse(AS_OF) - secondsAgo * 1_000).toISOString();
  const detail = (barSeconds, ageSeconds) =>
    classify(
      payload({
        outcome: {
          pending: 1,
          overdue: 1,
          oldest_overdue_due_at: at(ageSeconds),
          liveness_bar_seconds: barSeconds,
        },
      }),
    ).cells.find((c) => c.key === "clocks").detail;

  assert.equal(detail(90 * 60, 3 * 3_600), "no adjudicator pass in over 1h");
  assert.equal(detail(20 * 60, 3 * 3_600), "no adjudicator pass in over 20m");
  assert.equal(detail(26 * 3_600, 40 * 3_600), "no adjudicator pass in over 26h");
});

test("the labellers word a row against the bar they are handed", () => {
  // /jobs threads the same served bar into these, so a row the table calls
  // "not drained" is a row the pager would fire on. Same 45-minutes-at-a-
  // 60-minute-bar case as the strip test above, on the other surface.
  const at = new Date(Date.parse(AS_OF) - 45 * 60_000).toISOString();
  assert.ok(pendingReason(at, AS_OF, 3_600).startsWith("pending"));
  assert.ok(pendingReason(at, AS_OF, 600).startsWith("not drained"));

  const due = new Date(Date.parse(AS_OF) - 20 * 3_600_000).toISOString();
  assert.ok(overdueReason(due, AS_OF, 26 * 3_600).startsWith("overdue"));
  assert.ok(overdueReason(due, AS_OF, 12 * 3_600).startsWith("clock overdue"));
});
