import { parseUtc } from "./runs.ts";

export type HealthLevel = "failing" | "degraded" | "clear" | "unknown";

export interface ReviewLaneHealth {
  pending: number;
  oldest_pending_at: string | null;
  retrying: number;
  oldest_retry_at: string | null;
  running: number;
  stalled: number;
  failed: number;
  failed_24h: number;
  stall_lease_seconds: number;
  max_attempts: number;
}

export interface OutcomeLaneHealth {
  pending: number;
  overdue: number;
  next_due_at: string | null;
  oldest_overdue_due_at: string | null;
  running: number;
  stalled: number;
  failed: number;
  stall_lease_seconds: number;
  max_attempts: number;
}

export interface HealthPayload {
  review: ReviewLaneHealth;
  outcome: OutcomeLaneHealth;
  as_of: string;
}

export interface HealthCell {
  key: string;
  word: string;
  count: number | null;
  detail: string | null;
  level: HealthLevel;
}

export interface HealthVerdict {
  level: HealthLevel;
  cells: HealthCell[];
}

/** A fresh-pending job older than this means the drain that should have
 *  claimed it did not. The drain is kicked by every webhook delivery and
 *  every container start, and a job's own delivery kicks one in the same
 *  request — so several opportunities have passed by this point.
 *
 *  This number cannot come from the API: it is a statement about how often
 *  drains are kicked, not about any stored value. The strip states the
 *  quantity in words so the reader sees the age, not only the verdict. */
export const PENDING_THRESHOLD_MINUTES = 15;

/** The adjudicator Cloud Run Job fires daily at 03:00 UTC, so a clock due at
 *  00:00 is legitimately overdue for three hours and any clock can be
 *  legitimately overdue for most of a day. 24-hour cycle plus two hours of
 *  slack. Without this the alarm is red every single day and is ignored
 *  inside a week.
 *
 *  Like the threshold above, this cannot come from the ledger honestly — the
 *  schedule lives in Cloud Scheduler, not in Python. The strip names the
 *  assumption ("no adjudicator pass in over 26h") so that when the schedule
 *  changes the console says something falsifiable rather than something
 *  quietly wrong. */
export const ADJUDICATOR_GRACE_HOURS = 26;

function isError(v: unknown): v is { error: string } {
  return typeof v === "object" && v !== null && "error" in v;
}

/** Age in milliseconds against the SERVER's clock, never the browser's.
 *  Returns null when there is no timestamp — absent is not zero.
 *
 *  Both sides go through `parseUtc`, not raw `Date.parse`: job_health's lane
 *  timestamps (oldest_pending_at, oldest_retry_at, oldest_overdue_due_at,
 *  next_due_at) come from raw MIN() queries in store.py that skip
 *  `_as_utc`, so on sqlite they cross the wire with no zone suffix at all —
 *  the same gap `parseUtc` exists to close for every other timestamp this
 *  console renders. `as_of` itself is always server-tz-aware and so always
 *  carries an explicit offset, but parsing it through the same function
 *  keeps this module honouring one UTC convention rather than two parsers
 *  that could disagree with no error anywhere. */
function ageMs(at: string | null, asOf: string): number | null {
  if (at === null) return null;
  return parseUtc(asOf).getTime() - parseUtc(at).getTime();
}

const UNKNOWN_CELLS = ["verdict", "failed", "stalled", "waiting", "retrying", "clocks"];

function worst(levels: HealthLevel[]): HealthLevel {
  if (levels.includes("failing")) return "failing";
  if (levels.includes("degraded")) return "degraded";
  return "clear";
}

export function classify(input: HealthPayload | { error: string }): HealthVerdict {
  // An unreachable API is UNKNOWN, and unknown renders no counts at all.
  // Rendering "clear" here would convert "I do not know" into "everything is
  // fine" on the one surface built to prevent exactly that.
  if (isError(input)) {
    return {
      level: "unknown",
      cells: UNKNOWN_CELLS.map((key) => ({
        key,
        word: key === "verdict" ? "unknown" : key,
        count: null,
        detail: "the API did not answer",
        level: "unknown" as HealthLevel,
      })),
    };
  }

  const { review, outcome, as_of: asOf } = input;

  const failed = review.failed + outcome.failed;
  const stalled = review.stalled + outcome.stalled;

  const pendingAge = ageMs(review.oldest_pending_at, asOf);
  const pendingStale =
    pendingAge !== null && pendingAge > PENDING_THRESHOLD_MINUTES * 60_000;

  const overdueAge = ageMs(outcome.oldest_overdue_due_at, asOf);
  const overduePastGrace =
    overdueAge !== null && overdueAge > ADJUDICATOR_GRACE_HOURS * 3_600_000;

  const cells: HealthCell[] = [
    {
      key: "failed",
      word: "failed",
      count: failed,
      detail: review.failed_24h > 0 ? `${review.failed_24h} in 24h` : null,
      level: failed > 0 ? "failing" : "clear",
    },
    {
      key: "stalled",
      word: "stalled",
      count: stalled,
      detail: null,
      level: stalled > 0 ? "degraded" : "clear",
    },
    {
      key: "waiting",
      word: "waiting",
      count: review.pending - review.retrying,
      detail: review.oldest_pending_at,
      level: pendingStale ? "degraded" : "clear",
    },
    {
      key: "retrying",
      word: "retrying",
      count: review.retrying,
      detail: review.oldest_retry_at,
      level: review.retrying > 0 ? "degraded" : "clear",
    },
    {
      key: "clocks",
      word: "clocks",
      count: outcome.pending,
      detail: overduePastGrace
        ? `no adjudicator pass in over ${ADJUDICATOR_GRACE_HOURS}h`
        : outcome.next_due_at,
      level: overduePastGrace ? "failing" : "clear",
    },
  ];

  const level = worst(cells.map((c) => c.level));
  return {
    level,
    cells: [
      { key: "verdict", word: level, count: null, detail: null, level },
      ...cells,
    ],
  };
}
