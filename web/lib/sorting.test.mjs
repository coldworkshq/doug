// Ported verbatim from console/lib/sorting.test.mjs — keep the two in
// lockstep. Every test name and comment is the console's.
import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

// register + dynamic import for the reason grouping.test.mjs gives: these
// modules import their siblings extensionless (web convention), and a static
// import would be resolved at link time, before register() ever runs.
register("./node-next-loader.mjs", import.meta.url);
const { groupRunsByPr } = await import("./grouping.ts");
const { DEFAULT_SORT, SORTABLE, nextSort, parseSort, serializeSort, sortGroups } =
  await import("./sorting.ts");

function run(overrides) {
  return {
    verdict_id: 1,
    repo: "drewjst/doug",
    installation_id: 150424894,
    github_repo_id: 1,
    pr_number: 56,
    title: "route read budget by file tier",
    url: null,
    scored_at: "2026-08-05T10:00:00",
    tier: "code",
    source: "app",
    score: 0.38,
    band: "flagged",
    threshold: 0.3,
    coverage: null,
    changed_files: null,
    finding_counts: { total: 0, high: 0, medium: 0, low: 0 },
    job: null,
    outcome_14: null,
    ...overrides,
  };
}

const read = (filesSent) => ({
  diff_chars: 1000,
  sent_chars: 500,
  files_sent: filesSent,
  files_unseen: [],
  file_cut: null,
});

function groups(runs) {
  return groupRunsByPr(runs, false);
}

test("the default sort is newest first, which is what run_history already returns", () => {
  assert.deepEqual(DEFAULT_SORT, { key: "age", dir: "desc" });
});

test("sorting orders groups by the latest run and leaves children chronological", () => {
  // Sorting a nested table can only mean one thing: order the groups by
  // the row the operator can actually see. Reordering children by score
  // would destroy the history the accordion exists to show — the whole
  // point of expanding #56 is watching coverage climb push by push.
  const sorted = sortGroups(
    groups([
      run({ verdict_id: 1, pr_number: 10, score: 0.1, scored_at: "2026-08-05T12:00:00" }),
      run({ verdict_id: 2, pr_number: 10, score: 0.9, scored_at: "2026-08-05T11:00:00" }),
      run({ verdict_id: 3, pr_number: 20, score: 0.5, scored_at: "2026-08-05T13:00:00" }),
    ]),
    { key: "score", dir: "desc" },
  );

  // #20's latest scores 0.5, #10's latest scores 0.1 — even though #10
  // contains the highest-scoring run in the table.
  assert.deepEqual(sorted.map((g) => g.prNumber), [20, 10]);
  assert.deepEqual(sorted[1].children.map((r) => r.verdict_id), [2]);
});

test("score sorts both directions", () => {
  const rows = groups([
    run({ verdict_id: 1, pr_number: 10, score: 0.1 }),
    run({ verdict_id: 2, pr_number: 20, score: 0.9 }),
  ]);

  assert.deepEqual(sortGroups(rows, { key: "score", dir: "desc" }).map((g) => g.prNumber), [20, 10]);
  assert.deepEqual(sortGroups(rows, { key: "score", dir: "asc" }).map((g) => g.prNumber), [10, 20]);
});

test("a run with no read sorts last by coverage in BOTH directions", () => {
  // "No read" is not zero coverage — it is an absent measurement, and the
  // console draws that distinction everywhere else (coveragePercent returns
  // {kind:"no-read"} rather than 0). Treating it as 0 would put unread runs
  // at the top of an ascending sort as if Doug had read them and found
  // nothing, which is the exact fabrication the CoverageBar refuses to make.
  const rows = groups([
    run({ verdict_id: 1, pr_number: 10, coverage: read(1), changed_files: 10 }),
    run({ verdict_id: 2, pr_number: 20, coverage: null, changed_files: null }),
    run({ verdict_id: 3, pr_number: 30, coverage: read(9), changed_files: 10 }),
  ]);

  assert.deepEqual(
    sortGroups(rows, { key: "coverage", dir: "desc" }).map((g) => g.prNumber),
    [30, 10, 20],
  );
  assert.deepEqual(
    sortGroups(rows, { key: "coverage", dir: "asc" }).map((g) => g.prNumber),
    [10, 30, 20],
  );
});

test("a read with no denominator also sorts last — an unknown rate is not a low one", () => {
  // changed_files is the only correct denominator; without it the rate is
  // unknown, not small. Ranking it as 0% would order a fully-read PR below
  // a barely-read one purely because GitHub's file count was missing.
  const rows = groups([
    run({ verdict_id: 1, pr_number: 10, coverage: read(1), changed_files: 10 }),
    run({ verdict_id: 2, pr_number: 20, coverage: read(4), changed_files: null }),
  ]);

  assert.deepEqual(
    sortGroups(rows, { key: "coverage", dir: "asc" }).map((g) => g.prNumber),
    [10, 20],
  );
});

test("ties keep their incoming order, so a re-sort never shuffles equal rows", () => {
  const rows = groups([
    run({ verdict_id: 1, pr_number: 10, score: 0.5, scored_at: "2026-08-05T12:00:00" }),
    run({ verdict_id: 2, pr_number: 20, score: 0.5, scored_at: "2026-08-05T11:00:00" }),
    run({ verdict_id: 3, pr_number: 30, score: 0.5, scored_at: "2026-08-05T10:00:00" }),
  ]);

  assert.deepEqual(sortGroups(rows, { key: "score", dir: "desc" }).map((g) => g.prNumber), [10, 20, 30]);
  assert.deepEqual(sortGroups(rows, { key: "score", dir: "asc" }).map((g) => g.prNumber), [10, 20, 30]);
});

test("sortGroups does not mutate its input", () => {
  // The page renders from the grouped array on every sort change; an
  // in-place sort would make the previous order unrecoverable and turn
  // tie-stability above into a lie after the first click.
  const rows = groups([
    run({ verdict_id: 1, pr_number: 10, score: 0.1 }),
    run({ verdict_id: 2, pr_number: 20, score: 0.9 }),
  ]);
  const before = rows.map((g) => g.prNumber);

  sortGroups(rows, { key: "score", dir: "desc" });

  assert.deepEqual(rows.map((g) => g.prNumber), before);
});

test("clicking a new column starts descending; clicking the active one flips", () => {
  // Descending-first is right for all three: the operator opening a
  // console wants the riskiest score, the newest run, and — because
  // unknowns sink either way — the best-read PR.
  assert.deepEqual(nextSort({ key: "age", dir: "desc" }, "score"), { key: "score", dir: "desc" });
  assert.deepEqual(nextSort({ key: "score", dir: "desc" }, "score"), { key: "score", dir: "asc" });
  assert.deepEqual(nextSort({ key: "score", dir: "asc" }, "score"), { key: "score", dir: "desc" });
});

test("sort round-trips through the URL, so a shared link restores the order it was shared in", () => {
  // Facet selection already lives in the URL. Leaving sort in local state
  // meant a copied link restored the filters but not the ordering, so the
  // recipient saw a different table than the sender was looking at.
  const sort = { key: "coverage", dir: "asc" };
  assert.equal(serializeSort(sort), "coverage:asc");
  assert.deepEqual(parseSort("coverage:asc"), sort);
});

test("the default sort writes no param at all", () => {
  // A param that is always present carries no information, and it makes two
  // identical views look like different ones when shared.
  assert.equal(serializeSort(DEFAULT_SORT), null);
  assert.deepEqual(parseSort(null), DEFAULT_SORT);
});

test("an unhonourable sort param falls back to the default", () => {
  // Unlike ?band=purple — which honestly renders an empty table under a
  // filter that says "purple" — there is no truthful way to render a table
  // ordered by a column that does not exist.
  assert.deepEqual(parseSort("title:desc"), DEFAULT_SORT);
  assert.deepEqual(parseSort("score:sideways"), DEFAULT_SORT);
  assert.deepEqual(parseSort("score"), DEFAULT_SORT);
  assert.deepEqual(parseSort(""), DEFAULT_SORT);
});

test("only columns with a real ordering are sortable", () => {
  // band, tier and outcome are categories, not magnitudes — sorting them
  // alphabetically implies a ranking that does not exist. The facet pills
  // are how those get narrowed.
  assert.deepEqual(SORTABLE, ["score", "coverage", "age"]);
});
