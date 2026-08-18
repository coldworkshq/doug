import {
  bandCensus,
  charsLabel,
  deliveryCensus,
  durationLabel,
  outcomeCensus,
  readCensus,
  repoRollup,
  severityCensus,
  NEAR_LINE,
  type OutcomeCensus,
} from "@/lib/ledger-census";
import type { RunSummary } from "@/lib/session-api";

/** The dock's default occupant: what the rows currently in view add up to.
 *
 *  Six readouts over data the runs response has always carried and the ledger
 *  has never shown — finding severities, job timings, and the censoring rate
 *  the outcome columns can only report one row at a time. No second fetch, no
 *  new endpoint: every number here is a count of the array the table beside it
 *  is rendering, which is also why it can never disagree with that table.
 *
 *  DENOMINATORS ARE RENDERED, not implied. `scope` is a sentence naming the set
 *  every number below was counted over, and it sits above all of them rather
 *  than beside one — the same discipline CountLine follows for the ledger's own
 *  total, for the same reason: a fetched page is a window, not a population.
 *
 *  COLOUR DISCIPLINE, unchanged from the table. --flag and --clear appear only
 *  where a verdict does: band counts, the score histogram's two stacks, and an
 *  outcome's graded kinds. Severity, coverage and job timing are magnitudes and
 *  render on the neutral ramp — a high-severity finding is not a verdict about
 *  a pull request, and painting it in the miss colour would assert one. Nothing
 *  here is encoded by colour alone; every band carries its word and its count.
 *
 *  Surface-scoped tokens (--rule-soft, --dim, --row-hover) are deliberately
 *  absent: this file renders inside .dashboard-surface today, but it is a
 *  component and nothing stops it being mounted elsewhere, so it stays on the
 *  palette every surface declares. */

const BLOCK = "border-b border-border px-5 py-[18px]";

const HEADING =
  "mono mb-3 flex items-baseline gap-2 text-[10px] font-medium uppercase tracking-[.17em] " +
  "text-muted-foreground [&_span]:ml-auto [&_span]:text-[9.5px] [&_span]:tracking-[.04em] [&_span]:normal-case";

const FIGURE = "mono text-[21px] font-medium leading-none tabular-nums";

const CAPTION = "mono mt-1.5 text-[10.5px] leading-[1.45] text-muted-foreground";

/** The neutral sequential ramp, as three steps of one ink.
 *
 *  Mixed from --foreground rather than hardcoded, so the ramp follows the
 *  surface it is mounted on instead of pinning a paper-only hex the way the
 *  spine's nodes had to. Same family as globals' .cov-fill and the same rule:
 *  a magnitude is encoded by weight, never by hue. */
const RAMP = ["88%", "52%", "24%"];

function ink(step: number): string {
  return `color-mix(in srgb, var(--foreground) ${RAMP[step]}, transparent)`;
}

/** A labelled count, in a row of them. The word is not decoration — it is the
 *  secondary encoding every coloured band on this panel is required to carry. */
function Tally({
  value,
  word,
  tone,
  title,
}: {
  value: number | string;
  word: string;
  tone?: "flag" | "clear";
  title?: string;
}) {
  const colour = tone === "flag" ? "data-flag" : tone === "clear" ? "data-clear" : "text-foreground";
  return (
    <div className="flex min-w-0 flex-col gap-1" title={title}>
      <span className={`${FIGURE} ${colour}`}>{value}</span>
      <span className="mono truncate text-[9.5px] uppercase tracking-[.12em] text-muted-foreground">{word}</span>
    </div>
  );
}

/** One stacked hairline bar. Segments are given as [width%, background, label]
 *  and any remainder is left as visible empty track — an unfilled bar is a
 *  quantity that has not happened yet, and filling it with a "rest" colour
 *  would turn "not yet observed" into an observation. */
function Bar({ segments, label }: { segments: Array<{ pct: number; fill: string; word: string }>; label: string }) {
  return (
    <div
      className="flex h-2 w-full overflow-hidden rounded-[2px] bg-[color-mix(in_srgb,var(--foreground)_8%,transparent)]"
      role="img"
      aria-label={label}
    >
      {segments.map((segment) =>
        segment.pct <= 0 ? null : (
          <span
            key={segment.word}
            style={{ width: `${segment.pct}%`, background: segment.fill }}
            className="block h-full"
          />
        ),
      )}
    </div>
  );
}

/** The score histogram, and the one line the whole ledger turns on.
 *
 *  Each column is a 0.05 bucket, stacked cleared-under-flagged, scaled against
 *  the busiest bucket. A bucket holding runs gets at least one pixel of bar:
 *  scaled honestly, a bucket of 1 against a bucket of 60 rounds to nothing, and
 *  a run that exists rendering as blank space is the one distortion this chart
 *  must not produce.
 *
 *  The threshold marker is drawn ONLY when every row in view shares a
 *  threshold. Rows scored against different lines have no single line to draw,
 *  and a marker placed at one of them would invite reading every bar against a
 *  number most of them were never measured with. */
function Histogram({ census }: { census: ReturnType<typeof bandCensus> }) {
  const peak = Math.max(1, ...census.buckets.map((bucket) => bucket.cleared + bucket.flagged));
  return (
    <div>
      <div className="relative flex h-[74px] items-end gap-px">
        {census.buckets.map((bucket) => {
          const total = bucket.cleared + bucket.flagged;
          return (
            <div
              key={bucket.from}
              className="flex h-full flex-1 flex-col justify-end"
              title={`${bucket.from.toFixed(2)}–${bucket.to.toFixed(2)} · ${total} ${total === 1 ? "run" : "runs"}`}
            >
              {total > 0 && (
                <div style={{ height: `${Math.max(3, (total / peak) * 100)}%` }} className="flex flex-col justify-end">
                  {bucket.flagged > 0 && (
                    <span
                      className="block w-full bg-[var(--flag)]"
                      style={{ flex: `${bucket.flagged} 1 0`, minHeight: "2px" }}
                    />
                  )}
                  {bucket.cleared > 0 && (
                    <span
                      className="block w-full bg-[var(--clear)]"
                      style={{ flex: `${bucket.cleared} 1 0`, minHeight: "2px" }}
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
        {census.threshold !== null && (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-y-0 w-px bg-[var(--iridescent)]"
            style={{ left: `${Math.min(100, Math.max(0, census.threshold * 100))}%` }}
          />
        )}
      </div>
      <div className="mono mt-1.5 flex items-baseline justify-between border-t border-border pt-1.5 text-[9.5px] text-muted-foreground">
        <span>0.00</span>
        {census.threshold !== null ? (
          <span className="text-[var(--iridescent)]">line {census.threshold.toFixed(2)}</span>
        ) : (
          <span>thresholds differ — no single line to draw</span>
        )}
        <span>1.00</span>
      </div>
    </div>
  );
}

/** One outcome window, censused. Rendered twice, from two separate calls on
 *  two separate fields — never once with a fallback between them. The ruling
 *  that keeps 14d and 60d as two table columns keeps them as two readouts:
 *  they are different observations of different windows, and one standing in
 *  for the other would let a single "clean" silently mean either. */
function Window({ census }: { census: OutcomeCensus }) {
  const total = Math.max(1, census.graded + census.pending);
  return (
    <div className="mb-3.5 last:mb-0">
      <div className="mono mb-1.5 flex items-baseline gap-2 text-[11px]">
        <b className="font-medium">{census.window} day</b>
        <span className="text-[10px] text-muted-foreground">
          {census.graded} graded · {census.pending} still running
        </span>
      </div>
      <Bar
        label={`${census.window}-day outcomes: ${census.clean} clean, ${census.flagged} flagged, ${census.censored} censored, ${census.pending} pending`}
        segments={[
          { pct: (census.clean / total) * 100, fill: "var(--clear)", word: "clean" },
          { pct: (census.flagged / total) * 100, fill: "var(--flag)", word: "flagged" },
          {
            pct: (census.censored / total) * 100,
            // Censored is NOT a verdict — it records that the window closed
            // with the risk set unobserved. Hatched neutral, so it reads as
            // "nothing was seen here" rather than as good or bad news.
            fill: `repeating-linear-gradient(135deg, ${ink(1)} 0 2px, transparent 2px 4px)`,
            word: "censored",
          },
        ]}
      />
      <p className={CAPTION}>
        <b className="data-clear font-medium">{census.clean} clean</b> ·{" "}
        <b className="data-flag font-medium">{census.flagged} flagged</b> ·{" "}
        <b className="font-medium text-foreground">{census.censored} censored</b>
        {census.censored > 0 && (
          <> — {census.censored} of {census.graded} graded windows observed nothing at all.</>
        )}
      </p>
    </div>
  );
}

export function CensusPanel({ runs, scope }: { runs: RunSummary[]; scope: string }) {
  const band = bandCensus(runs);
  const severity = severityCensus(runs);
  const read = readCensus(runs);
  const delivery = deliveryCensus(runs);
  const repos = repoRollup(runs);
  const findingsTotal = Math.max(1, severity.total);
  // Chars, not files. The table's read column is a FILE ratio
  // (files_sent / changed_files) and this is a character ratio over the same
  // rows — two different measurements of the same read, and labelling either
  // one "coverage" without saying which is how they get confused for each
  // other. Every label on this block says "chars".
  const charsPct = read.diffChars > 0 ? Math.min(100, (read.sentChars / read.diffChars) * 100) : null;

  return (
    <section aria-labelledby="census-title" className="pb-16">
      <header className="border-b border-border px-5 pt-5 pb-4">
        <h2 id="census-title" className="mono text-[10px] font-medium uppercase tracking-[.17em] text-[var(--iridescent)]">
          Ledger census
        </h2>
        <p className="mono mt-1.5 text-[10.5px] leading-[1.45] text-muted-foreground">
          {scope}. Open a run to replace this with its evidence.
        </p>
      </header>

      <div className={BLOCK}>
        <h3 className={HEADING}>Verdict spread<span>{band.runs} runs</span></h3>
        <div className="mb-4 grid grid-cols-3 gap-3">
          <Tally value={band.flagged} word="needs you" tone="flag" />
          <Tally value={band.cleared} word="cleared" tone="clear" />
          <Tally
            value={band.nearLine}
            word="near the line"
            title={`within ±${NEAR_LINE.toFixed(2)} of their own recorded threshold`}
          />
        </div>
        <Histogram census={band} />
        <p className={CAPTION}>
          {band.nearLine === 0
            ? `No run sits within ±${NEAR_LINE.toFixed(2)} of its own line.`
            : `${band.nearLine} of ${band.runs} sit within ±${NEAR_LINE.toFixed(2)} of their own line — a small scoring change flips them.`}
        </p>
      </div>

      <div className={BLOCK}>
        <h3 className={HEADING}>Findings<span>{severity.runsWithFindings} of {band.runs} runs</span></h3>
        <div className="mb-3.5 grid grid-cols-4 gap-3">
          <Tally value={severity.total} word="total" />
          <Tally value={severity.high} word="high" />
          <Tally value={severity.medium} word="medium" />
          <Tally value={severity.low} word="low" />
        </div>
        <Bar
          label={`${severity.high} high, ${severity.medium} medium, ${severity.low} low${
            severity.unclassified > 0 ? `, ${severity.unclassified} with no recorded severity` : ""
          }`}
          segments={[
            { pct: (severity.high / findingsTotal) * 100, fill: ink(0), word: "high" },
            { pct: (severity.medium / findingsTotal) * 100, fill: ink(1), word: "medium" },
            { pct: (severity.low / findingsTotal) * 100, fill: ink(2), word: "low" },
            {
              // The fourth segment exists because the first three do NOT have to
              // sum to `total`: `findings.severity` is nullable, and store.py
              // counts total as COUNT(*) against three conditional SUMs. Without
              // it the shortfall rendered as empty track — which this component
              // documents as "a quantity that has not happened yet", i.e. a
              // finding that happened drawn as one that did not.
              //
              // Hatched, borrowing the censored outcome's treatment below for the
              // same reason: this is not a fourth severity, it is the absence of
              // a recorded one, and giving it a solid step of the ramp would rank
              // it against the three that are real.
              pct: (severity.unclassified / findingsTotal) * 100,
              fill: `repeating-linear-gradient(135deg, ${ink(2)} 0 2px, transparent 2px 4px)`,
              word: "unclassified",
            },
          ]}
        />
        <p className={CAPTION}>
          Severity is a magnitude, not a verdict — it renders on the neutral ramp, darkest first.
          {severity.unclassified > 0 && (
            <>
              {" "}
              <b className="font-medium text-foreground">{severity.unclassified}</b>
              {severity.unclassified === 1 ? " finding carries" : " findings carry"} no recorded
              severity and {severity.unclassified === 1 ? "is" : "are"} hatched above — counted,
              not classified.
            </>
          )}
        </p>
      </div>

      <div className={BLOCK}>
        <h3 className={HEADING}>The read<span>chars, not files</span></h3>
        {charsPct === null ? (
          <p className={CAPTION}>No run in view recorded a read, so there is no diff to measure against.</p>
        ) : (
          <>
            <div className="mono mb-2 flex items-baseline gap-2">
              <span className={FIGURE}>{Math.round(charsPct)}%</span>
              <span className="text-[10.5px] text-muted-foreground">
                {charsLabel(read.sentChars)} of {charsLabel(read.diffChars)} chars
              </span>
            </div>
            <span className="cov-track block h-2 w-full overflow-hidden rounded-[2px]">
              <span className="cov-fill block h-full" style={{ width: `${charsPct}%` }} />
            </span>
          </>
        )}
        <dl className="mono m-0 mt-3 flex flex-col text-[10.5px]">
          {[
            ["runs that read a diff", read.measured],
            ["scored from metadata, no read", read.noRead],
            ["left changed files unseen", read.unseenRuns],
            ["cut mid-file by the budget", read.cutRuns],
            ["below 50% of their files", read.low],
            ["file count unknown, so unmeasurable", read.unknownDenominator],
          ].map(([word, count]) => (
            <div key={String(word)} className="flex items-baseline justify-between gap-3 border-t border-border py-[5px] first:border-t-0 first:pt-0">
              <dt className="min-w-0 text-muted-foreground">{word}</dt>
              <dd className="m-0 flex-none tabular-nums text-foreground">{count}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className={BLOCK}>
        <h3 className={HEADING}>Outcome windows<span>{band.runs} runs</span></h3>
        {/* Two calls, two fields, two readouts. Never one with a fallback. */}
        <Window census={outcomeCensus(runs, 14)} />
        <Window census={outcomeCensus(runs, 60)} />
      </div>

      <div className={BLOCK}>
        <h3 className={HEADING}>Delivery<span>{delivery.jobs} jobs</span></h3>
        <div className="mb-3.5 grid grid-cols-4 gap-3">
          <Tally value={delivery.done} word="done" />
          <Tally value={delivery.errored} word="errored" tone={delivery.errored > 0 ? "flag" : undefined} />
          <Tally value={delivery.retried} word="retried" />
          <Tally value={delivery.other} word="in flight" />
        </div>
        <dl className="mono m-0 flex flex-col text-[10.5px]">
          {[
            ["median read", durationLabel(delivery.medianReadSeconds), delivery.readMeasured],
            ["slowest read", durationLabel(delivery.slowestReadSeconds), delivery.readMeasured],
            ["median queue wait", durationLabel(delivery.medianWaitSeconds), delivery.waitMeasured],
          ].map(([word, value, measured]) => (
            <div key={String(word)} className="flex items-baseline justify-between gap-3 border-t border-border py-[5px] first:border-t-0 first:pt-0">
              {/* The count of measurable jobs rides every duration. A median
                  over 2 of 40 jobs and a median over all 40 are different
                  claims, and the number is how a reader tells them apart. */}
              <dt className="min-w-0 text-muted-foreground">
                {word} <span className="text-[9.5px]">over {String(measured)}</span>
              </dt>
              <dd className="m-0 flex-none tabular-nums text-foreground">{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      {repos.length > 0 && (
        <div className={BLOCK}>
          <h3 className={HEADING}>By repository<span>{repos.length} in view</span></h3>
          <div className="mono flex flex-col text-[10.5px]">
            <div className="flex items-baseline gap-2.5 text-[9px] uppercase tracking-[.1em] text-muted-foreground">
              <span className="min-w-0 flex-1">repo</span>
              <span className="w-[30px] flex-none text-right">run</span>
              <span className="w-[30px] flex-none text-right">flag</span>
              <span className="w-[38px] flex-none text-right">read</span>
            </div>
            {repos.map((row) => (
              <div key={row.repo} className="flex items-baseline gap-2.5 border-t border-border py-[5px]">
                <span className="min-w-0 flex-1 truncate text-foreground" title={`${row.repo} · ${row.prs} prs · ${row.findings} findings`}>
                  {row.repo}
                </span>
                <span className="w-[30px] flex-none text-right tabular-nums text-muted-foreground">{row.runs}</span>
                <span className={`w-[30px] flex-none text-right tabular-nums ${row.flagged > 0 ? "data-flag" : "text-muted-foreground"}`}>
                  {row.flagged}
                </span>
                {/* Chars again, and null stays "—". A repo Doug never read and
                    a repo Doug read nothing in are different facts, and 0%
                    asserts the second one. */}
                <span className="w-[38px] flex-none text-right tabular-nums text-muted-foreground">
                  {row.coveragePct === null ? "—" : `${Math.round(row.coveragePct)}%`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
