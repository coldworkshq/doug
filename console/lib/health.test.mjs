import assert from "node:assert/strict";
import test from "node:test";

import {
  ADJUDICATOR_GRACE_HOURS,
  PENDING_THRESHOLD_MINUTES,
  classify,
  overdueReason,
  pendingReason,
} from "./health.ts";

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
        // 16 minutes before AS_OF (PENDING_THRESHOLD_MINUTES + 1), with no
        // trailing "Z" -- exactly what sqlite hands back for this field.
        oldest_pending_at: "2026-08-07T11:44:00",
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
    const zoneless = "2026-08-07T11:40:00"; // 20 minutes before AS_OF
    assert.equal(pendingReason(zoneless, AS_OF), "not drained 20m");
  } finally {
    process.env.TZ = originalTz;
  }
});
