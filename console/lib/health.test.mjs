import assert from "node:assert/strict";
import test from "node:test";

import {
  ADJUDICATOR_GRACE_HOURS,
  PENDING_THRESHOLD_MINUTES,
  classify,
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
