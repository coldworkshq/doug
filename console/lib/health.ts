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
  /** Optional because an older API predates the field, never because the
   *  console may ignore it. See `resolveBar` below. */
  liveness_bar_seconds?: number;
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
  /** As above. */
  liveness_bar_seconds?: number;
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

/* THE BARS COME FROM THE API. Both lanes' liveness bars are served on
 * `/v1/health` as `liveness_bar_seconds`, and they are the same numbers
 * `/healthz/queues` collapses to 200/503 for the Cloud Monitoring uptime
 * check that pages a human (doug#121, doug#260).
 *
 * This module used to hold its own opinion instead — 15 minutes for the
 * review lane against the route's 30 — and that is a defect, not a
 * preference. A review job pending 20 minutes read `degraded` here while
 * the pager stayed silent, so the surface an operator reads and the surface
 * that wakes one up disagreed about the same contradiction. An operator who
 * learns the strip cries wolf stops reading it, and a strip nobody reads is
 * the 2026-08-16 outage again.
 *
 * The older comments here argued the bars "cannot come from the API" because
 * they describe drain cadence rather than a stored value. That was true
 * until doug#260: the bars are now enforced in `api/doug/api.py`, beside the
 * route that pages on them, and a second copy over here is exactly what has
 * to stop existing. */

/** Used only when the API did not answer with a bar — an older deployment,
 *  or a payload that carries nonsense. It is a COPY of the API's value and
 *  must equal it; `health.test.mjs` reads `api/doug/api.py` and fails when
 *  the two drift. It is not this module's own threshold. */
export const REVIEW_BAR_FALLBACK_SECONDS = 30 * 60;

/** As above, for the outcome lane: the adjudicator's daily cadence plus
 *  slack. A clock is legitimately overdue until the sweep that should have
 *  claimed it demonstrably did not run. */
export const OUTCOME_BAR_FALLBACK_SECONDS = 26 * 3_600;

/** The lane's bar in seconds: the server's, or the fallback when the server
 *  did not give one.
 *
 *  A non-finite or non-positive value is treated as absent rather than
 *  honoured. A bar of 0 grades every pending row as broken and a negative
 *  one grades nothing as broken — silence, which is the thing #121 exists
 *  to end — so a malformed payload must degrade to the known-good copy, not
 *  to whatever arrived. */
export function resolveBar(
  lane: { liveness_bar_seconds?: number } | null | undefined,
  fallbackSeconds: number,
): number {
  const served = lane?.liveness_bar_seconds;
  return typeof served === "number" && Number.isFinite(served) && served > 0
    ? served
    : fallbackSeconds;
}

/** How long ago `at` was, against the server's `asOf`. Null when either is
 *  missing, or when `at` is in the future — a backward-looking label with a
 *  forward timestamp is nonsense and must produce no duration rather than a
 *  negative one. */
function elapsedMs(at: string | null, asOf: string | null): number | null {
  if (at === null || asOf === null) return null;
  const ms = parseUtc(asOf).getTime() - parseUtc(at).getTime();
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

function ladder(ms: number): string {
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  return hours < 48 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
}

/** How a `/jobs` row explains itself, for the two states where the server's
 *  row membership and the strip's verdict deliberately disagree.
 *
 *  `store.job_rows` applies no threshold and no grace: its unhealthy
 *  predicate returns every pending review job and every past-due outcome
 *  clock. That is deliberate — the bars are alerting thresholds rather than
 *  lane semantics, so they live beside the route that pages on them
 *  (`api/doug/api.py`) and reach this module through the health payload. So
 *  a job enqueued one second ago and a clock the adjudicator simply hasn't
 *  reached today both land in the "unhealthy only" list while the strip
 *  beside them reads clear.
 *
 *  That is not a row-membership bug — those rows genuinely belong on a page
 *  whose question is "what is Doug waiting on". It is a *wording* problem,
 *  and the wording is what these own: the alarming phrasing is reserved for
 *  rows past the same bar the strip grades against AND the same bar
 *  /healthz/queues pages on, so no two of the three can contradict each
 *  other about the same row.
 *
 *  Both degrade to the bare word when there is no clock to check against —
 *  `asOf` rides the health payload, which is fetched independently of the
 *  rows and can fail on its own. Same discipline as the attempts cap:
 *  say less, never invent a duration. */
export function pendingReason(
  enqueuedAt: string | null,
  asOf: string | null,
  /** The review lane's bar, threaded from the same health payload `asOf`
   *  rides. Defaulted rather than required so a caller that has no payload
   *  at all still words the row against the known-good copy — the same
   *  degrade `asOf: null` already gets. */
  barSeconds: number = REVIEW_BAR_FALLBACK_SECONDS,
): string {
  const ms = elapsedMs(enqueuedAt, asOf);
  if (ms === null) return "pending";
  return ms > barSeconds * 1_000 ? `not drained ${ladder(ms)}` : `pending ${ladder(ms)}`;
}

export function overdueReason(
  dueAt: string | null,
  asOf: string | null,
  /** As above, for the outcome lane. */
  barSeconds: number = OUTCOME_BAR_FALLBACK_SECONDS,
): string {
  const ms = elapsedMs(dueAt, asOf);
  if (ms === null) return "overdue";
  return ms > barSeconds * 1_000 ? `clock overdue ${ladder(ms)}` : `overdue ${ladder(ms)}`;
}

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

  // The bars the pager uses, served beside the counts they grade. The
  // strip and /healthz/queues therefore call the same queue state by the
  // same name, which is the whole point of #121.
  const reviewBar = resolveBar(review, REVIEW_BAR_FALLBACK_SECONDS);
  const outcomeBar = resolveBar(outcome, OUTCOME_BAR_FALLBACK_SECONDS);

  const pendingAge = ageMs(review.oldest_pending_at, asOf);
  const pendingStale = pendingAge !== null && pendingAge > reviewBar * 1_000;

  const overdueAge = ageMs(outcome.oldest_overdue_due_at, asOf);
  const overduePastGrace = overdueAge !== null && overdueAge > outcomeBar * 1_000;

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
      // The hours are read off the bar in force, never a literal: when the
      // adjudicator's schedule changes, the API's bar moves and this
      // sentence moves with it. A hardcoded "26h" beside a bar that had
      // become something else is a falsifiable claim rendered false, on the
      // one surface built to be trusted about silence.
      detail: overduePastGrace
        ? `no adjudicator pass in over ${Math.round(outcomeBar / 3_600)}h`
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
