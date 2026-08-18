import { coveragePercent } from "./coverage";
import { outcomeTone } from "./dashboard-model";
import { parseUtc } from "./runs-time";
import type { RunSummary } from "./session-api";

/** Aggregates over the runs a dashboard is ALREADY holding.
 *
 *  Every function here is a count of a list the page has fetched — never an
 *  estimate, never a projection, and never a second request. That is the whole
 *  design constraint: the API returns `finding_counts`, three job timestamps
 *  and two outcome kinds on every row of `/v1/sessions/runs`, and until now the
 *  dashboard rendered none of them. This module reads what is already on the
 *  wire; it does not widen the contract.
 *
 *  THE DENOMINATOR IS PART OF THE ANSWER. Nothing here returns a rate. Every
 *  shape carries the count it was measured over beside the measurement, so a
 *  caller cannot render "62%" without also being able to say "of what" — the
 *  same rule `isAtCap` and `runCountLabel` already enforce for the ledger's own
 *  totals. A fetched page is a window, not a population, and a percentage
 *  rendered without its window is the failure this whole surface refuses.
 *
 *  ABSENT IS NOT ZERO, everywhere. A run with no coverage record is counted as
 *  a run with no coverage record — not as a run that read nothing. A job with
 *  no `finished_at` contributes no duration rather than a zero one. Each shape
 *  below keeps its own "measured" count for exactly this reason. */

/** How close a run has to sit to its OWN recorded threshold to count as near
 *  the line. 0.05 is one histogram bucket (see `SCORE_BUCKET`), which is what
 *  makes the two readouts describe the same picture: a bar straddling the
 *  threshold marker and a run counted here are the same run.
 *
 *  Measured against `run.threshold`, never against a page-wide constant. The
 *  ledger spans installations and tiers, and thresholds genuinely differ row to
 *  row; a single hardcoded line would count runs as near-misses against a
 *  number no verdict on the page was scored with. */
export const NEAR_LINE = 0.05;

export const SCORE_BUCKET = 0.05;

export type Severity = { total: number; high: number; medium: number; low: number };

/** One bucket of the score histogram, split by the band each run actually
 *  carries — NOT by comparing the bucket's own range to a threshold. Rows in
 *  one bucket can hold different thresholds, and with the lens active a row's
 *  band is the lens's verdict rather than the recorded one. Reading `run.band`
 *  keeps the bars agreeing with the chips in the table beside them, in both
 *  cases, because it is the same field. */
export type ScoreBucket = { from: number; to: number; cleared: number; flagged: number };

export type BandCensus = {
  runs: number;
  cleared: number;
  flagged: number;
  /** Runs within ±NEAR_LINE of their own threshold, in either direction. A
   *  cleared run at 0.28 against a 0.30 line and a flagged one at 0.32 are the
   *  same fact — a verdict a small scoring change would flip — and splitting
   *  them into "near-clear" and "near-flag" would invite reading one as safer. */
  nearLine: number;
  /** True when the fetched rows do not all share one threshold, which is what
   *  makes a single drawn line a lie. The caller renders the marker only when
   *  this is false, and names the spread when it is true. */
  thresholdVaries: boolean;
  /** The one threshold every row shares, or null when they do not share one. */
  threshold: number | null;
  buckets: ScoreBucket[];
};

export type ReadCensus = {
  /** Runs carrying a coverage record at all. */
  measured: number;
  /** Runs with `coverage === null` — Doug scored these from metadata and read
   *  no diff. Not a coverage of 0%: a deterministic run is not a failed read. */
  noRead: number;
  /** Read but with no trustworthy denominator (`changed_files` absent), so the
   *  percentage is genuinely unknown. Counted apart from `measured`'s ratio so
   *  the aggregate below is never inflated by rows it could not measure. */
  unknownDenominator: number;
  /** Runs whose known coverage is below `LOW_COVERAGE`. */
  low: number;
  /** Chars, summed only over runs with a coverage record. */
  sentChars: number;
  diffChars: number;
  /** Runs that left at least one changed file unseen, and runs whose read was
   *  cut mid-file. Two different holes in the evidence and two counts: a cut
   *  says the budget ran out inside a file the reader had started. */
  unseenRuns: number;
  cutRuns: number;
};

export type OutcomeCensus = {
  window: 14 | 60;
  /** Rows the window has GRADED. `pending` is deliberately outside it: a clock
   *  still running is not an observation, and folding it in would let a mostly
   *  un-elapsed ledger report a flattering clean rate. */
  graded: number;
  pending: number;
  clean: number;
  /** Every graded kind whose tone is `flag` — revert today, plus any kind this
   *  build has never heard of. Same allowlist-refusing rule as `outcomeTone`:
   *  an unknown outcome is counted as bad, never quietly as neutral. */
  flagged: number;
  /** The merge left the risk set UNOBSERVED. Reported on its own line because
   *  §3 of the publication pre-registration requires the censoring rate to be
   *  published beside every outcome claim, and because a censored window is
   *  the one result that is neither good news nor bad news. */
  censored: number;
};

export type DeliveryCensus = {
  jobs: number;
  done: number;
  errored: number;
  /** Jobs that took more than one attempt, whether or not they ended in error.
   *  A job that succeeded on attempt three still cost two failures. */
  retried: number;
  /** Jobs whose status is neither done nor error — still queued, claimed, or a
   *  status this build does not know. Kept as a residual so the three counts
   *  above can never be read as a partition they are not. */
  other: number;
  /** Reads with BOTH `started_at` and `finished_at`. The durations below are
   *  over this count and no other. */
  readMeasured: number;
  medianReadSeconds: number | null;
  slowestReadSeconds: number | null;
  /** Jobs with both `enqueued_at` and `started_at` — how long Doug sat in the
   *  queue before anything looked at the PR. */
  waitMeasured: number;
  medianWaitSeconds: number | null;
  slowestWaitSeconds: number | null;
};

export type RepoRow = {
  repo: string;
  runs: number;
  prs: number;
  flagged: number;
  findings: number;
  errored: number;
  /** Aggregate read coverage as a percentage, or null when no run in this repo
   *  had both a read and a usable denominator. Null renders as "—"; it must
   *  never render as 0%. */
  coveragePct: number | null;
};

function bucketIndex(score: number): number {
  const last = Math.round(1 / SCORE_BUCKET) - 1;
  if (!Number.isFinite(score)) return 0;
  return Math.min(last, Math.max(0, Math.floor(score / SCORE_BUCKET)));
}

export function bandCensus(runs: RunSummary[]): BandCensus {
  const count = Math.round(1 / SCORE_BUCKET);
  const buckets: ScoreBucket[] = Array.from({ length: count }, (_, index) => ({
    from: index * SCORE_BUCKET,
    to: (index + 1) * SCORE_BUCKET,
    cleared: 0,
    flagged: 0,
  }));

  let cleared = 0;
  let flagged = 0;
  let nearLine = 0;
  const thresholds = new Set<number>();

  for (const run of runs) {
    const bucket = buckets[bucketIndex(run.score)];
    if (run.band === "flagged") {
      flagged += 1;
      bucket.flagged += 1;
    } else {
      cleared += 1;
      bucket.cleared += 1;
    }
    thresholds.add(run.threshold);
    if (Math.abs(run.score - run.threshold) <= NEAR_LINE) nearLine += 1;
  }

  return {
    runs: runs.length,
    cleared,
    flagged,
    nearLine,
    thresholdVaries: thresholds.size > 1,
    threshold: thresholds.size === 1 ? [...thresholds][0] : null,
    buckets,
  };
}

export function severityCensus(runs: RunSummary[]): Severity & { runsWithFindings: number } {
  let total = 0;
  let high = 0;
  let medium = 0;
  let low = 0;
  let runsWithFindings = 0;
  for (const run of runs) {
    const counts = run.finding_counts;
    total += counts.total;
    high += counts.high;
    medium += counts.medium;
    low += counts.low;
    if (counts.total > 0) runsWithFindings += 1;
  }
  return { total, high, medium, low, runsWithFindings };
}

export function readCensus(runs: RunSummary[]): ReadCensus {
  const census: ReadCensus = {
    measured: 0,
    noRead: 0,
    unknownDenominator: 0,
    low: 0,
    sentChars: 0,
    diffChars: 0,
    unseenRuns: 0,
    cutRuns: 0,
  };
  for (const run of runs) {
    const read = run.coverage;
    if (read === null) {
      census.noRead += 1;
      continue;
    }
    census.measured += 1;
    census.sentChars += read.sent_chars;
    census.diffChars += read.diff_chars;
    if (read.files_unseen.length > 0) census.unseenRuns += 1;
    if (read.file_cut !== null) census.cutRuns += 1;
    const result = coveragePercent(read, run.changed_files);
    if (result.kind === "unknown-denominator") census.unknownDenominator += 1;
    else if (result.kind === "known" && result.low) census.low += 1;
  }
  return census;
}

/** One window's census, over the field that window's own column reads.
 *
 *  `window` is passed rather than derived so the two calls are two visibly
 *  separate statements at the call site, matching the ruling that 14d and 60d
 *  are different observations and never one resolving to the other. Feeding
 *  this `run.outcome_60 ?? run.outcome_14` would produce a census of a value
 *  no column renders. */
export function outcomeCensus(runs: RunSummary[], window: 14 | 60): OutcomeCensus {
  const census: OutcomeCensus = {
    window,
    graded: 0,
    pending: 0,
    clean: 0,
    flagged: 0,
    censored: 0,
  };
  for (const run of runs) {
    const kind = window === 14 ? run.outcome_14 : run.outcome_60;
    if (kind === null) {
      census.pending += 1;
      continue;
    }
    census.graded += 1;
    // Routed through the SAME rule the columns and the detail tile use, so a
    // row painted red in the table can never be counted as neutral here.
    // `censored` is the one kind whose neutral tone it shares with nothing
    // else, which is what lets it be told apart without a second vocabulary.
    if (kind === "censored") census.censored += 1;
    else if (outcomeTone(kind) === "clear") census.clean += 1;
    else census.flagged += 1;
  }
  return census;
}

/** Seconds between two ISO-ish stamps, or null when either is missing or the
 *  pair is nonsense (finish before start).
 *
 *  Both sides go through `parseUtc`, the same parser the age column and the
 *  sort comparator use. `jobDuration` in runs-time.ts uses a bare `new Date()`
 *  and is right anyway — a zoneless pair shifts identically and the difference
 *  survives — but that only holds while BOTH stamps are zoneless. A job
 *  enqueued under one serialization and finished under another would shift one
 *  side and not the other, and the duration would be off by the server's whole
 *  UTC offset with nothing to show for it. */
function seconds(from: string | null, to: string | null): number | null {
  if (from === null || to === null) return null;
  const ms = parseUtc(to).getTime() - parseUtc(from).getTime();
  return Number.isFinite(ms) && ms >= 0 ? ms / 1000 : null;
}

/** The median of a non-empty list, or null for an empty one. Median, not mean:
 *  one 40-minute read on a 900-file PR should not be able to describe every
 *  other run on the page. The slowest is reported separately, as itself. */
function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

export function deliveryCensus(runs: RunSummary[]): DeliveryCensus {
  let jobs = 0;
  let done = 0;
  let errored = 0;
  let retried = 0;
  let other = 0;
  const reads: number[] = [];
  const waits: number[] = [];

  for (const run of runs) {
    const job = run.job;
    if (job === null) continue;
    jobs += 1;
    // `error` first: a job can carry a terminal error and a status this build
    // does not recognise, and an errored job counted as "other" is an error
    // that vanishes from the readout.
    if (job.error !== null) errored += 1;
    else if (job.status === "done") done += 1;
    else other += 1;
    if (job.attempts > 1) retried += 1;
    const read = seconds(job.started_at, job.finished_at);
    if (read !== null) reads.push(read);
    const wait = seconds(job.enqueued_at, job.started_at);
    if (wait !== null) waits.push(wait);
  }

  return {
    jobs,
    done,
    errored,
    retried,
    other,
    readMeasured: reads.length,
    medianReadSeconds: median(reads),
    slowestReadSeconds: reads.length === 0 ? null : Math.max(...reads),
    waitMeasured: waits.length,
    medianWaitSeconds: median(waits),
    slowestWaitSeconds: waits.length === 0 ? null : Math.max(...waits),
  };
}

/** Per-repository rollup, busiest first.
 *
 *  `coveragePct` is a chars ratio rather than the mean of each run's file
 *  percentage: averaging percentages weights a one-file PR the same as a
 *  two-hundred-file one, and the question this row answers is "how much of
 *  what changed in this repo did Doug actually see". Null when the repo has no
 *  read at all — an unmeasured repo and a repo Doug read nothing in are
 *  different facts. */
type RepoTally = {
  runs: number;
  prs: Set<number>;
  flagged: number;
  findings: number;
  errored: number;
  sent: number;
  diff: number;
};

export function repoRollup(runs: RunSummary[]): RepoRow[] {
  const tallies = new Map<string, RepoTally>();
  for (const run of runs) {
    let tally = tallies.get(run.repo);
    if (!tally) {
      tally = { runs: 0, prs: new Set(), flagged: 0, findings: 0, errored: 0, sent: 0, diff: 0 };
      tallies.set(run.repo, tally);
    }
    tally.runs += 1;
    tally.prs.add(run.pr_number);
    if (run.band === "flagged") tally.flagged += 1;
    tally.findings += run.finding_counts.total;
    if (run.job?.error) tally.errored += 1;
    if (run.coverage) {
      tally.sent += run.coverage.sent_chars;
      tally.diff += run.coverage.diff_chars;
    }
  }

  return [...tallies.entries()]
    .map(([repo, tally]) => ({
      repo,
      runs: tally.runs,
      prs: tally.prs.size,
      flagged: tally.flagged,
      findings: tally.findings,
      errored: tally.errored,
      coveragePct: tally.diff > 0 ? Math.min(100, (tally.sent / tally.diff) * 100) : null,
    }))
    .sort((a, b) => b.runs - a.runs || a.repo.localeCompare(b.repo));
}

/** "41s" / "6m12s" / "1h04m" from a duration in seconds, or "—" for null.
 *
 *  Never rounds a real duration down to "0s": anything under a second reads
 *  "<1s", the same refusal `coverageLabel` makes at the other end of its
 *  range. A read that happened is not a read that took no time. */
export function durationLabel(value: number | null): string {
  if (value === null) return "—";
  if (value < 1) return "<1s";
  const total = Math.round(value);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m${String(total % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}m`;
}

/** The sentence naming the set every census number was counted over.
 *
 *  Same four facts CountLine renders and the same rule: at the page cap the
 *  fetched set is only the newest `limit` runs, so a bare total there would
 *  report a fraction of the scope as the whole of it. "fetched" rather than "in
 *  this space" throughout — the census can only see what came back.
 *
 *  A sentence rather than a tooltip because the panel states many numbers and
 *  they all share one denominator. Repeating it per readout would be noise;
 *  omitting it would leave six unqualified counts on a surface whose entire
 *  claim is that it does not make unqualified counts. */
export function censusScope(input: {
  shown: number;
  fetched: number;
  limit: number;
  atCap: boolean;
  filtering: boolean;
}): string {
  const fetched = input.atCap ? `the latest ${input.limit} fetched` : `${input.fetched} fetched`;
  if (input.filtering) return `Over the ${input.shown} runs in view, of ${fetched}`;
  return input.atCap
    ? `Over the latest ${input.limit} runs fetched — the scope may hold more`
    : `Over all ${input.fetched} runs fetched`;
}

/** "1.2M" / "834k" / "512" — chars, at a glance. Below 1000 the exact number
 *  is shorter than any abbreviation of it, so it stays exact. */
export function charsLabel(value: number): string {
  if (value < 1_000) return String(value);
  if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(1)}M`;
}
