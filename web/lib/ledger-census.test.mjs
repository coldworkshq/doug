import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

/** A run with every field the census reads, so each test can override only the
 *  one it is about. Fields the census does not read are omitted deliberately —
 *  a fixture that carries them invites a test to assert on data the module
 *  never looks at. */
function run(overrides = {}) {
  return {
    verdict_id: 1,
    repo: "acme/one",
    pr_number: 12,
    score: 0.22,
    band: "cleared",
    threshold: 0.3,
    coverage: { diff_chars: 1000, sent_chars: 500, files_sent: 2, files_unseen: [], file_cut: null },
    changed_files: 4,
    finding_counts: { total: 0, high: 0, medium: 0, low: 0 },
    job: {
      status: "done",
      attempts: 1,
      error: null,
      enqueued_at: "2026-08-06T10:00:00",
      started_at: "2026-08-06T10:00:10",
      finished_at: "2026-08-06T10:00:40",
    },
    outcome_14: null,
    outcome_60: null,
    ...overrides,
  };
}

test("a run is banded by the band it carries, never by comparing its score to a line", async () => {
  // The histogram bars sit directly beside the table's own BandChips, and with
  // the threshold lens active a row's band is the LENS's verdict rather than
  // the recorded one. Bucketing by `score >= threshold` would recompute a
  // verdict the page has already decided, and the bars would disagree with the
  // chips on exactly the rows the lens moved — the one state the lens banner
  // exists to make legible.
  //
  // This fixture is the proof: a run scored 0.90 but banded `cleared`, which is
  // what a lens raised to 0.95 produces. Any implementation that re-derives the
  // band from score-vs-threshold counts it as flagged and fails here.
  const { bandCensus } = await import("./ledger-census.ts?band");
  const census = bandCensus([run({ score: 0.9, band: "cleared", threshold: 0.3 })]);
  assert.equal(census.cleared, 1);
  assert.equal(census.flagged, 0);
  const bucket = census.buckets.find((b) => b.cleared + b.flagged > 0);
  assert.deepEqual([bucket.from.toFixed(2), bucket.cleared, bucket.flagged], ["0.90", 1, 0]);
});

test("near-the-line is measured against each run's OWN threshold", async () => {
  // The ledger spans installations and tiers and thresholds genuinely differ
  // row to row. A page-wide constant would count runs as near-misses against a
  // number no verdict on the page was scored with.
  //
  // Both fixtures sit 0.01 from their own line and must both count; the second
  // is nowhere near the first's threshold, which is what fails any
  // implementation that picked one line for the page.
  const { bandCensus, NEAR_LINE } = await import("./ledger-census.ts?near");
  const census = bandCensus([
    run({ score: 0.29, threshold: 0.3, band: "cleared" }),
    run({ score: 0.71, threshold: 0.7, band: "flagged" }),
    run({ score: 0.1, threshold: 0.3, band: "cleared" }),
  ]);
  assert.equal(census.nearLine, 2);
  assert.equal(NEAR_LINE, 0.05);
  // Both directions count as one fact. A cleared run just under its line and a
  // flagged one just over it are equally close to flipping, and splitting them
  // would invite reading the cleared side as the safer one.
  assert.equal(census.cleared, 2);
  assert.equal(census.flagged, 1);
});

test("a threshold marker is only offered when every fetched row shares one line", async () => {
  // Drawing one marker over rows scored against different lines is a claim the
  // ledger does not support. The caller renders the marker off `threshold`, so
  // null is what withdraws it.
  const { bandCensus } = await import("./ledger-census.ts?threshold");
  const same = bandCensus([run({ threshold: 0.3 }), run({ threshold: 0.3 })]);
  assert.equal(same.thresholdVaries, false);
  assert.equal(same.threshold, 0.3);
  const mixed = bandCensus([run({ threshold: 0.3 }), run({ threshold: 0.45 })]);
  assert.equal(mixed.thresholdVaries, true);
  assert.equal(mixed.threshold, null);
});

test("a run that read nothing is counted as unread, never as 0% coverage", async () => {
  // A deterministic run has no diff to read and is not a failed read. Folding
  // `coverage === null` into the ratio would drag the aggregate down with rows
  // that were never supposed to contribute to it, and would report Doug as
  // having missed evidence it was never given.
  const { readCensus } = await import("./ledger-census.ts?read");
  const census = readCensus([
    run({ coverage: null }),
    run({ coverage: { diff_chars: 100, sent_chars: 100, files_sent: 4, files_unseen: [], file_cut: null } }),
  ]);
  assert.equal(census.noRead, 1);
  assert.equal(census.measured, 1);
  // The one measured run read everything, and the aggregate says so — it is not
  // halved by the run that had nothing to read.
  assert.equal(census.sentChars, 100);
  assert.equal(census.diffChars, 100);
});

test("an unusable denominator is its own count, and never a low-coverage alarm", async () => {
  // `changed_files === null` means the true file count is unknown, so the
  // percentage is unknown — not low. Counting it as low would alarm on rows
  // whose coverage nobody can compute, which is the exact substitution
  // `coveragePercent` refuses by returning a third kind.
  const { readCensus } = await import("./ledger-census.ts?denominator");
  const census = readCensus([
    run({ changed_files: null }),
    run({ changed_files: 10, coverage: { diff_chars: 100, sent_chars: 10, files_sent: 1, files_unseen: ["a"], file_cut: "a" } }),
  ]);
  assert.equal(census.unknownDenominator, 1);
  assert.equal(census.low, 1);
  assert.equal(census.unseenRuns, 1);
  assert.equal(census.cutRuns, 1);
});

test("a pending clock is not a graded outcome, and censoring is counted apart from both", async () => {
  // Folding pending into the denominator would let a ledger whose clocks have
  // barely started report a flattering clean rate. And a censored window —
  // the merge left the risk set unobserved — is neither good news nor bad
  // news; §3 of the publication pre-registration requires it beside every
  // outcome claim rather than inside one.
  const { outcomeCensus } = await import("./ledger-census.ts?outcome");
  const census = outcomeCensus(
    [
      run({ outcome_14: null }),
      run({ outcome_14: "clean" }),
      run({ outcome_14: "censored" }),
      run({ outcome_14: "revert" }),
    ],
    14,
  );
  assert.deepEqual(
    { graded: census.graded, pending: census.pending, clean: census.clean, censored: census.censored, flagged: census.flagged },
    { graded: 3, pending: 1, clean: 1, censored: 1, flagged: 1 },
  );
});

test("an outcome kind this build has never heard of counts as bad, not as neutral", async () => {
  // Same allowlist-refusing rule as `outcomeTone`, and the reason it exists: an
  // unknown kind arriving as neutral is how a genuinely bad outcome shows up
  // looking fine. Routed through that shared rule rather than re-listed here,
  // so widening the vocabulary can only move both together.
  const { outcomeCensus } = await import("./ledger-census.ts?unknown-kind");
  const census = outcomeCensus([run({ outcome_60: "exploded" })], 60);
  assert.equal(census.flagged, 1);
  assert.equal(census.clean, 0);
  assert.equal(census.censored, 0);
});

test("each window is censused over its own field, so 14d can never stand in for 60d", async () => {
  // The ruling that governs the two table columns governs the two readouts
  // beside them. A census fed `outcome_60 ?? outcome_14` would report a value
  // no column on the page renders.
  const { outcomeCensus } = await import("./ledger-census.ts?windows");
  const rows = [run({ outcome_14: "clean", outcome_60: null })];
  assert.equal(outcomeCensus(rows, 14).clean, 1);
  assert.equal(outcomeCensus(rows, 60).clean, 0);
  assert.equal(outcomeCensus(rows, 60).pending, 1);
});

test("an errored job is counted as errored whatever status word it carries", async () => {
  // A job can hold a terminal error and a status this build does not
  // recognise. Branching on status first drops that job into the residual
  // bucket, and an error that vanishes from the readout is the failure this
  // panel exists to prevent.
  const { deliveryCensus } = await import("./ledger-census.ts?errored");
  const census = deliveryCensus([
    run({ job: { status: "wedged", attempts: 3, error: "timed out", enqueued_at: null, started_at: null, finished_at: null } }),
    run({ job: { status: "done", attempts: 1, error: null, enqueued_at: null, started_at: null, finished_at: null } }),
    run({ job: { status: "claimed", attempts: 1, error: null, enqueued_at: null, started_at: null, finished_at: null } }),
  ]);
  assert.deepEqual(
    { jobs: census.jobs, done: census.done, errored: census.errored, other: census.other, retried: census.retried },
    { jobs: 3, done: 1, errored: 1, other: 1, retried: 1 },
  );
});

test("a duration is measured only where both stamps exist, and the count says how many", async () => {
  // Absent is not zero. A job with no `finished_at` contributes no duration —
  // treating a missing stamp as the epoch, or as `now`, invents a measurement.
  // `readMeasured` is what lets the panel print "median over 2 reads" instead
  // of implying it measured all four.
  const { deliveryCensus, durationLabel } = await import("./ledger-census.ts?durations");
  const census = deliveryCensus([
    run({ job: { status: "done", attempts: 1, error: null, enqueued_at: "2026-08-06T10:00:00", started_at: "2026-08-06T10:00:05", finished_at: "2026-08-06T10:00:15" } }),
    run({ job: { status: "done", attempts: 1, error: null, enqueued_at: "2026-08-06T10:00:00", started_at: "2026-08-06T10:00:05", finished_at: "2026-08-06T10:01:35" } }),
    run({ job: { status: "running", attempts: 1, error: null, enqueued_at: "2026-08-06T10:00:00", started_at: "2026-08-06T10:00:05", finished_at: null } }),
    run({ job: null }),
  ]);
  assert.equal(census.jobs, 3);
  assert.equal(census.readMeasured, 2);
  assert.equal(census.medianReadSeconds, 50);
  assert.equal(census.slowestReadSeconds, 90);
  // The queue wait is a separate measurement with its own count: all three
  // jobs started, so all three waits are real even though only two reads are.
  assert.equal(census.waitMeasured, 3);
  assert.equal(census.medianWaitSeconds, 5);
  assert.equal(durationLabel(census.medianReadSeconds), "50s");
  assert.equal(durationLabel(census.slowestReadSeconds), "1m30s");
  assert.equal(durationLabel(null), "—");
});

test("a duration that happened never renders as no time at all", async () => {
  // The same refusal `coverageLabel` makes at the other end of its range: a
  // read that took 300ms is a read that happened, and "0s" says it did not.
  const { durationLabel } = await import("./ledger-census.ts?sub-second");
  assert.equal(durationLabel(0.3), "<1s");
  assert.equal(durationLabel(0), "<1s");
});

test("a repo with no read reports unknown coverage, never 0%", async () => {
  // An unmeasured repo and a repo Doug read nothing in are different facts, and
  // 0% asserts the second. The rollup is a chars ratio rather than a mean of
  // per-run percentages, so a one-file PR cannot outvote a two-hundred-file one
  // on the question "how much of what changed here did Doug see".
  const { repoRollup } = await import("./ledger-census.ts?repos");
  const rows = repoRollup([
    run({ repo: "acme/one", pr_number: 1, coverage: null, band: "flagged", finding_counts: { total: 3, high: 1, medium: 1, low: 1 } }),
    run({ repo: "acme/two", pr_number: 2, coverage: { diff_chars: 1000, sent_chars: 250, files_sent: 1, files_unseen: [], file_cut: null } }),
    run({ repo: "acme/two", pr_number: 2, coverage: { diff_chars: 1000, sent_chars: 750, files_sent: 1, files_unseen: [], file_cut: null } }),
  ]);
  // Busiest first.
  assert.deepEqual(rows.map((row) => row.repo), ["acme/two", "acme/one"]);
  assert.equal(rows[0].runs, 2);
  // Two runs, one PR — the rollup counts pull requests, not rows.
  assert.equal(rows[0].prs, 1);
  assert.equal(rows[0].coveragePct, 50);
  assert.equal(rows[1].coveragePct, null);
  assert.equal(rows[1].flagged, 1);
  assert.equal(rows[1].findings, 3);
});

test("severity counts survive as three separate numbers plus their own total", async () => {
  // `finding_counts` is on every row of the runs response and nothing rendered
  // it before this module. The three severities are kept apart because the
  // panel ranks by them: eleven low findings and one high are not the same
  // ledger, and a single total says they are.
  const { severityCensus } = await import("./ledger-census.ts?severity");
  const census = severityCensus([
    run({ finding_counts: { total: 3, high: 1, medium: 1, low: 1 } }),
    run({ finding_counts: { total: 0, high: 0, medium: 0, low: 0 } }),
    run({ finding_counts: { total: 2, high: 0, medium: 0, low: 2 } }),
  ]);
  // deepEqual, not a field-by-field check: the shape is the contract, and a new
  // bucket appearing without this test moving is how the panel ends up drawing
  // against a total it no longer accounts for. `unclassified: 0` here is the
  // normal case — every finding in this fixture carries one of the three.
  assert.deepEqual(census, {
    total: 5, high: 1, medium: 1, low: 3, unclassified: 0, runsWithFindings: 2,
  });
});

test("at the page cap the census names the window, never a total it cannot see", async () => {
  // The same substitution CountLine refuses. At the cap the response holds only
  // the newest `limit` runs, so "over all 500 runs" would report a fraction of
  // the scope as the whole of it — and this panel prints six counts under that
  // one sentence, so the error would propagate to all of them at once.
  const { censusScope } = await import("./ledger-census.ts?scope");
  assert.equal(
    censusScope({ shown: 500, fetched: 500, limit: 500, atCap: true, filtering: false }),
    "Over the latest 500 runs fetched — the scope may hold more",
  );
  assert.equal(
    censusScope({ shown: 155, fetched: 155, limit: 500, atCap: false, filtering: false }),
    "Over all 155 runs fetched",
  );
  // Filtering makes the numerator and the denominator two different sets, and
  // both have to be on screen: "91 runs" alone cannot be checked against
  // anything.
  assert.equal(
    censusScope({ shown: 91, fetched: 155, limit: 500, atCap: false, filtering: true }),
    "Over the 91 runs in view, of 155 fetched",
  );
  assert.equal(
    censusScope({ shown: 91, fetched: 500, limit: 500, atCap: true, filtering: true }),
    "Over the 91 runs in view, of the latest 500 fetched",
  );
});

test("a connected repository with no runs in view is a row, not an omission", async () => {
  // The most useful row on the repositories screen. Listing only repos that
  // appear in the ledger would silently drop it, and "Doug has reviewed nothing
  // here" is precisely what an operator opens this screen to find — a repo that
  // is connected but never reviewed is a coverage hole, and an absent row reads
  // as no hole at all.
  const { repositoryTable, repoRollup } = await import("./ledger-census.ts?repo-table");
  const rows = repositoryTable(
    ["acme/busy", "acme/silent"],
    repoRollup([run({ repo: "acme/busy" })]),
  );
  assert.deepEqual(rows.map((r) => r.repo), ["acme/busy", "acme/silent"]);
  const silent = rows[1];
  assert.equal(silent.runs, 0);
  assert.equal(silent.connected, true);
  // Null, not 0. Doug has not read this repo; it has not read 0% of it.
  assert.equal(silent.coveragePct, null);
});

test("a repository with runs but no connection entry is kept and marked, never dropped", async () => {
  // The mirror failure. A repo removed from the installation, renamed, or with
  // access revoked leaves its verdicts in the ledger — they are real runs and
  // real findings. Joining only from the connection side would hide them, and
  // the run table beside this screen would still be showing them, so the two
  // surfaces would disagree about the same ledger.
  const { repositoryTable, repoRollup } = await import("./ledger-census.ts?orphan");
  const rows = repositoryTable(
    ["acme/current"],
    repoRollup([
      run({ repo: "acme/current", pr_number: 1 }),
      run({ repo: "acme/removed", pr_number: 2, band: "flagged" }),
      run({ repo: "acme/removed", pr_number: 3 }),
    ]),
  );
  const removed = rows.find((r) => r.repo === "acme/removed");
  assert.ok(removed, "a repo with runs was dropped because the connection no longer lists it");
  assert.equal(removed.connected, false);
  assert.equal(removed.runs, 2);
  assert.equal(removed.flagged, 1);
  assert.equal(rows.find((r) => r.repo === "acme/current").connected, true);
});

test("every repository appears exactly once, whichever side it came from", async () => {
  // A repo present in BOTH sources is the normal case, and the join must not
  // emit it twice — a duplicated row would double-count in any total taken over
  // this table.
  const { repositoryTable, repoRollup } = await import("./ledger-census.ts?once");
  const rows = repositoryTable(
    ["acme/one", "acme/two"],
    repoRollup([run({ repo: "acme/one" }), run({ repo: "acme/two", pr_number: 9 })]),
  );
  assert.equal(rows.length, 2);
  assert.deepEqual([...new Set(rows.map((r) => r.repo))].length, 2);
});

test("repositories sort busiest first, so silent ones land in one block at the end", async () => {
  // Scattering zero-run repos alphabetically through the list is what makes a
  // coverage hole hard to see. Ties break by name so the order is stable.
  const { repositoryTable, repoRollup } = await import("./ledger-census.ts?repo-sort");
  const rows = repositoryTable(
    ["z/quiet", "a/quiet", "m/busy"],
    repoRollup([run({ repo: "m/busy" }), run({ repo: "m/busy", pr_number: 2 })]),
  );
  assert.deepEqual(rows.map((r) => r.repo), ["m/busy", "a/quiet", "z/quiet"]);
});

test("a finding whose severity was never recorded is counted, not dropped", async () => {
  // REVIEW FINDING (Doug, reader:aggregate-mismatch — its one true finding).
  // `findings.severity` is `Column("severity", String(10))` in store.py — nullable —
  // and store.py:852 writes it straight off the Reason, whose severity is
  // `str | None`. The aggregation makes total = COUNT(*) while high/medium/low are
  // SUM(CASE WHEN severity = 'x' THEN 1 ELSE 0 END) with else_=0, so a null-severity
  // finding lands in `total` and in none of the three buckets.
  //
  // The census must surface that gap as its own number. Leaving the caller to
  // subtract is what produced the bug: the panel drew three segments over `total`
  // and the shortfall rendered as empty track, which Bar's own docstring defines as
  // "a quantity that has not happened yet" — a finding that DID happen, drawn as one
  // that did not.
  const { severityCensus } = await import("./ledger-census.ts?unclassified");
  const census = severityCensus([
    run({ finding_counts: { total: 3, high: 1, medium: 0, low: 0 } }),
    run({ finding_counts: { total: 1, high: 0, medium: 0, low: 1 } }),
  ]);
  assert.equal(census.total, 4);
  assert.equal(census.unclassified, 2);
  // The three named buckets plus the unnamed remainder ALWAYS reconstruct the
  // total. This is the invariant the bar draws against.
  assert.equal(census.high + census.medium + census.low + census.unclassified, census.total);
});

test("unclassified is never negative, even if the API's own counts disagree", async () => {
  // total < high+medium+low should not happen, but a negative remainder would render
  // as a negative-width bar segment and a nonsense caption. Clamped at zero: the
  // panel's job is to not lie, and inventing a negative quantity is a different lie
  // from the one this fixes.
  const { severityCensus } = await import("./ledger-census.ts?unclassified-clamp");
  const census = severityCensus([run({ finding_counts: { total: 1, high: 2, medium: 0, low: 0 } })]);
  assert.equal(census.unclassified, 0);
});

test("the counted-over phrase names the filtered set FIRST, cap or no cap", async () => {
  // REVIEW FINDING (mine; Doug missed it). RepoCountLine branched on `atCap` before
  // consulting `filtering`, so at the cap it claimed counts were over all 500 fetched
  // runs while they were over the filtered subset — and `censusScope`, which branches
  // the other way round, printed a different denominator for the same numbers on the
  // same screen.
  //
  // Both now go through one branch order. The `filtering` case must name `shown`
  // whatever `atCap` says; the cap only ever qualifies the SECOND number.
  const { countedOver } = await import("./ledger-census.ts?counted-over");
  assert.equal(
    countedOver({ shown: 90, fetched: 500, limit: 500, atCap: true, filtering: true }),
    "the 90 runs in view, of the latest 500 fetched",
  );
  assert.equal(
    countedOver({ shown: 90, fetched: 155, limit: 500, atCap: false, filtering: true }),
    "the 90 runs in view, of 155 fetched",
  );
  assert.equal(
    countedOver({ shown: 500, fetched: 500, limit: 500, atCap: true, filtering: false }),
    "the latest 500 runs fetched",
  );
  assert.equal(
    countedOver({ shown: 155, fetched: 155, limit: 500, atCap: false, filtering: false }),
    "all 155 runs fetched",
  );
});

test("the two denominator sentences can never name different sets", async () => {
  // The parity guard, in the spirit of outcome-tone-parity.test.mjs. The ledger
  // header and the dock's census sit on one screen describing one set of rows; the
  // failure this pins is not a wrong string but two surfaces disagreeing about what
  // was counted. Whenever a filter is on, BOTH must name the filtered count and
  // NEITHER may present the fetched total as the denominator.
  const { countedOver, censusScope } = await import("./ledger-census.ts?parity");
  for (const atCap of [true, false]) {
    const input = { shown: 90, fetched: 500, limit: 500, atCap, filtering: true };
    const phrase = countedOver(input);
    const sentence = censusScope(input);
    assert.ok(phrase.includes("90"), `countedOver dropped the filtered count: ${phrase}`);
    assert.ok(sentence.includes("90"), `censusScope dropped the filtered count: ${sentence}`);
    // "the latest 500 fetched" is allowed as the SECOND clause; what is banned is
    // either sentence opening on the unfiltered total as though it were the set.
    assert.equal(phrase.startsWith("the latest"), false, `countedOver leads with the cap: ${phrase}`);
    assert.equal(sentence.startsWith("Over the latest"), false, `censusScope leads with the cap: ${sentence}`);
  }
});

test("a char count just under a million rolls into M rather than printing 1000k", async () => {
  // REVIEW FINDING (mine). The kilo branch covers everything below 1,000,000 and
  // rounds to zero decimals above 10,000, so 999,999 renders "1000k" — a label
  // implying the next unit was never reached when rounding has already crossed it.
  const { charsLabel } = await import("./ledger-census.ts?chars-rollover");
  assert.equal(charsLabel(999_999), "1.0M");
  assert.equal(charsLabel(999_500), "1.0M");
  // The boundaries either side still behave.
  assert.equal(charsLabel(999_400), "999k");
  assert.equal(charsLabel(1_000_000), "1.0M");
  assert.equal(charsLabel(9_999), "10.0k");
  assert.equal(charsLabel(999), "999");
});

test("an empty ledger censuses to zeros and nulls, never to a divide-by-zero", async () => {
  // The empty state is a real state: a freshly connected space has no runs, and
  // every panel on this surface renders against it before it renders against
  // anything else.
  const census = await import("./ledger-census.ts?empty");
  assert.equal(census.bandCensus([]).runs, 0);
  assert.equal(census.bandCensus([]).threshold, null);
  assert.equal(census.readCensus([]).measured, 0);
  assert.equal(census.outcomeCensus([], 14).graded, 0);
  assert.equal(census.deliveryCensus([]).medianReadSeconds, null);
  assert.deepEqual(census.repoRollup([]), []);
  assert.equal(census.charsLabel(0), "0");
});
