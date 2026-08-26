// The lockstep guard.
//
// Seven files in web/lib/ carry a header saying "keep the two in lockstep"
// with console/lib/. Until this file existed, NOTHING enforced that: someone
// could edit console's copy (or web's), run both suites, get green on both,
// and ship two surfaces that disagree about the same run. That is precisely
// the contradiction Lane 1's exit gate forbids, and it would reach production
// with no test anywhere going red.
//
// This test imports BOTH copies and feeds them identical inputs, so it fails
// whichever side moved. It is deliberately not a source-text diff: the ports
// have ruled, documented differences (renames, split modules, dropped
// exports), and a text diff would either fail on those forever or be loosened
// until it caught nothing.
//
// Direction matters: only web can import console. Web's tests register
// node-next-loader.mjs and console's do not, and console's modules import
// their siblings with an explicit ".ts" that plain Node resolves. So the guard
// lives here, in web/lib/, and console's suite stays untouched.
//
// EVERY divergence between the two sides is listed in RULED_DIVERGENCES below.
// A difference that is not on that list fails this test. Adding to the list is
// how you record a new deliberate divergence — never how you silence a real one.
import assert from "node:assert/strict";
import { register } from "node:module";
import { readFile } from "node:fs/promises";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const web = {
  coverage: await import("./coverage.ts"),
  runsTime: await import("./runs-time.ts"),
  paging: await import("./paging.ts"),
  search: await import("./search.ts"),
  facets: await import("./facets.ts"),
  grouping: await import("./grouping.ts"),
  sorting: await import("./sorting.ts"),
};

const con = {
  runs: await import("../../console/lib/runs.ts"),
  paging: await import("../../console/lib/paging.ts"),
  search: await import("../../console/lib/search.ts"),
  facets: await import("../../console/lib/facets.ts"),
  grouping: await import("../../console/lib/grouping.ts"),
  sorting: await import("../../console/lib/sorting.ts"),
};

/** Every deliberate difference between console's exports and web's, with the
 *  reason. Anything else is a drift bug. */
const RULED_DIVERGENCES = {
  // console/lib/runs.ts is ONE module; web split it in two when Phase A ported
  // the coverage half, so the comparison is against the union of both.
  runs: {
    consoleOnly: [
      // Parses console's ?tenant= scope param. Web's dashboard is scoped by
      // session and pins that "tenant all" never appears.
      "parseTenantId",
      // The outcome-tone rule (#93). It lives in web/lib/dashboard-model.ts,
      // not in the runs-time half, because web's dashboard imports it from
      // there — so it is a divergence of LOCATION, not of behaviour, and
      // this test's export comparison cannot see across that move.
      //
      // It is not unguarded: web/lib/outcome-tone-parity.test.mjs imports
      // BOTH copies of `outcomeTone` and asserts they agree over the whole
      // vocabulary plus kinds neither build knows. That is the same
      // executable-equivalence check this file applies to the ported
      // modules, pointed at the one rule that did not move as a module.
      //
      // `outcomeToneClass` and `outcomeLabel` USED to be listed here too, as
      // console-only in substance: they emit console's Tailwind class names
      // and its glyph vocabulary (`✓ clean`, `○ censored`, `↩ revert`), and
      // web's dashboard painted tone through CSS-module classes instead.
      // Phase B PR 2 rebuilt those render sites on the console's grammar, so
      // both are now ported into web/lib/runs-time.ts and the allowance is
      // GONE rather than left stale — the export comparison below sees them
      // on both sides again, and the test after next pins that they agree.
      // (The `OutcomeTone` type is not listed: types erase under
      // --experimental-strip-types, so they never reach this comparison.)
      "outcomeTone",
    ],
    webOnly: [],
  },
  paging: { consoleOnly: [], webOnly: [] },
  search: {
    consoleOnly: [
      // Take console's JobItem (its /jobs page type). Web has no jobs surface
      // and no such type — plan D6.
      "jobMatchesQuery",
      "filterJobsByQuery",
    ],
    webOnly: [],
  },
  facets: {
    // The D5 rename: web/lib/dashboard-model.ts already exports a DIFFERENT
    // filterRuns, so the facet one is filterRunsByFacets here.
    consoleOnly: ["filterRuns"],
    webOnly: ["filterRunsByFacets"],
  },
  grouping: { consoleOnly: [], webOnly: [] },
  sorting: { consoleOnly: [], webOnly: [] },
};

const names = (mod) => Object.keys(mod).sort();
const missing = (from, present) => from.filter((k) => !present.includes(k));

/** deepStrictEqual compares Dates by `getTime() === getTime()`, and an
 *  unparseable stamp gives NaN on both sides — so two identical Invalid Dates
 *  would report as a divergence. parseUtc returning Invalid Date for garbage
 *  is behaviour the two copies genuinely share, so it is compared by value. */
function comparable(value) {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? "Invalid Date" : value.toISOString();
  }
  return value;
}

/** Assert both copies return deep-equal results for every case. */
function agree(label, webFn, conFn, cases) {
  for (const args of cases) {
    const w = comparable(webFn(...args));
    const c = comparable(conFn(...args));
    assert.deepEqual(
      w,
      c,
      `${label}(${JSON.stringify(args)}) diverged — web and console no longer agree`,
    );
  }
}

// ---------------------------------------------------------------------------
// Fixtures. One run shape, varied across every branch the modules read.
// ---------------------------------------------------------------------------

const READ = { diff_chars: 1000, sent_chars: 500, files_sent: 4, files_unseen: ["a.py"], file_cut: "b.py" };
const TINY = { diff_chars: 100000, sent_chars: 3, files_sent: 1, files_unseen: ["x.py", "y.py"], file_cut: "x.py" };

function run(overrides = {}) {
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
    outcome_60: null,
    ...overrides,
  };
}

// outcome_60 is varied independently of outcome_14 across these rows — a run
// can read "clean" at 14 days and still be pending at 60 (verdict_id 1), or
// pending at 14 and closed by 60 (verdict_id 4) — so the fixture actually
// exercises the two windows as separate observations, not as one value
// mirrored onto two fields.
const RUNS = [
  run({ verdict_id: 1, band: "flagged", outcome_14: null, outcome_60: null, coverage: READ, changed_files: 8, scored_at: "2026-08-05T10:00:00" }),
  run({ verdict_id: 2, band: "cleared", outcome_14: "clean", outcome_60: "clean", coverage: null, changed_files: 8, scored_at: "2026-08-06T11:00:00Z" }),
  run({ verdict_id: 3, band: "flagged", outcome_14: "reverted", outcome_60: "reverted", coverage: TINY, changed_files: null, scored_at: "2026-08-04T09:30:00", pr_number: 57 }),
  run({ verdict_id: 4, band: "cleared", outcome_14: null, outcome_60: "clean", coverage: READ, changed_files: 4, tier: "deep", repo: "acme/other", pr_number: 56 }),
  run({ verdict_id: 5, band: "flagged", outcome_14: "hotfix", outcome_60: null, coverage: READ, changed_files: 100, tier: "deep", scored_at: "2026-08-07T23:59:59+05:00" }),
];

const STAMPS = [
  "2026-08-06T14:22:48",
  "2026-08-06T14:22:07Z",
  "2026-08-06T09:00:00+05:00",
  "2026-08-07T02:00:00+05:00",
  "2026-08-06T00:30:00",
  "not a date",
];

// ---------------------------------------------------------------------------

test("no ported module has gained or lost an export on one side only", () => {
  // The cheapest drift to catch: console grows a function, web's copy silently
  // falls behind, and every existing test still passes because it only ever
  // exercised the functions that already existed.
  const pairs = [
    // console/lib/runs.ts vs the union of BOTH files web split it into.
    ["runs", names(con.runs), [...names(web.coverage), ...names(web.runsTime)].sort()],
    ["paging", names(con.paging), names(web.paging)],
    ["search", names(con.search), names(web.search)],
    ["facets", names(con.facets), names(web.facets)],
    ["grouping", names(con.grouping), names(web.grouping)],
    ["sorting", names(con.sorting), names(web.sorting)],
  ];

  for (const [module, consoleNames, webNames] of pairs) {
    const ruled = RULED_DIVERGENCES[module];
    assert.deepEqual(
      missing(consoleNames, webNames),
      [...ruled.consoleOnly].sort(),
      `${module}: console exports something web's copy does not, and it is not a ruled divergence`,
    );
    assert.deepEqual(
      missing(webNames, consoleNames),
      [...ruled.webOnly].sort(),
      `${module}: web exports something console does not, and it is not a ruled divergence`,
    );
  }
});

test("the UTC and coverage helpers agree with console's originals", () => {
  const now = new Date("2026-08-08T12:00:00Z");
  agree("parseUtc", web.runsTime.parseUtc, con.runs.parseUtc, STAMPS.map((s) => [s]));
  agree("relativeAge", web.runsTime.relativeAge, con.runs.relativeAge, STAMPS.slice(0, 5).map((s) => [s, now]));
  agree("utcClock", web.runsTime.utcClock, con.runs.utcClock, [...STAMPS.map((s) => [s]), [null]]);
  agree("utcTimestamp", web.runsTime.utcTimestamp, con.runs.utcTimestamp, STAMPS.map((s) => [s]));
  agree("utcDate", web.runsTime.utcDate, con.runs.utcDate, STAMPS.map((s) => [s]));
  agree("utcShortDate", web.runsTime.utcShortDate, con.runs.utcShortDate, STAMPS.map((s) => [s]));
  agree("jobDuration", web.runsTime.jobDuration, con.runs.jobDuration, [
    ["2026-08-06T12:00:00Z", "2026-08-06T12:00:41Z"],
    ["2026-08-06T12:00:00Z", "2026-08-06T12:01:12Z"],
    [null, "2026-08-06T12:00:41Z"],
    ["2026-08-06T12:00:00Z", null],
    [null, null],
  ]);

  const covCases = [
    [READ, 8], [READ, null], [READ, 0], [READ, -3], [TINY, 100000], [null, 8], [READ, 1],
  ];
  agree("coveragePercent", web.coverage.coveragePercent, con.runs.coveragePercent, covCases);
  assert.equal(web.coverage.LOW_COVERAGE, con.runs.LOW_COVERAGE);
  agree(
    "coverageLabel",
    web.coverage.coverageLabel,
    con.runs.coverageLabel,
    covCases.map(([c, d]) => [con.runs.coveragePercent(c, d)]),
  );
});

test("the outcome label and tone-class helpers agree with console's originals", () => {
  // These two decide what an outcome row SAYS and what colour it says it in,
  // on both surfaces. A drift here is invisible to either workspace's own
  // suite and shows up as the console and the dashboard describing the same
  // `outcomes.kind` row differently — the exact defect #93 fixed for
  // `outcomeTone`, which is guarded by lib/outcome-tone-parity.test.mjs.
  const KINDS = [null, "clean", "censored", "revert", "hotfix", "graded-miss", "", "CLEAN"];
  agree("outcomeLabel", web.runsTime.outcomeLabel, con.runs.outcomeLabel, KINDS.map((k) => [k]));
  agree("outcomeToneClass", web.runsTime.outcomeToneClass, con.runs.outcomeToneClass,
    ["clear", "flag", "neutral"].map((t) => [t]));

  // And what the two surfaces SAY those words mean. The ⓘ over each outcome
  // column reads from these, so a drift here is the same defect one layer out:
  // the dashboard and the console defining `clean` differently for the same
  // `outcomes.kind` row, with nothing in either workspace's own suite able to
  // see it. `null` for the window is included — RunDetail carries a nullable
  // `window_days`, and the two copies have to agree on that branch too.
  const WINDOWS = [14, 60, null];
  agree("outcomeMeaning", web.runsTime.outcomeMeaning, con.runs.outcomeMeaning,
    KINDS.flatMap((k) => WINDOWS.map((w) => [k, w])));
  agree("outcomeWindowHint", web.runsTime.outcomeWindowHint, con.runs.outcomeWindowHint,
    [[14], [60]]);
});

test("paging agrees with console's original", () => {
  const items = Array.from({ length: 120 }, (_, i) => i + 1);
  agree("parsePage", web.paging.parsePage, con.paging.parsePage,
    [["0"], ["-3"], ["1.5"], ["nope"], ["3"], [""], ["  "], [null], [undefined]].map((a) => a));
  agree("pageSlice", web.paging.pageSlice, con.paging.pageSlice, [
    [items, 1], [items, 3], [items, 99], [items, 1, 2], [[], 4], [items, 2, 0],
  ]);
  agree("pageRangeLabel", web.paging.pageRangeLabel, con.paging.pageRangeLabel, [
    [con.paging.pageSlice(items, 1)], [con.paging.pageSlice([], 1)], [con.paging.pageSlice([1, 2, 3, 4, 5], 1, 2)],
  ]);
  assert.equal(web.paging.DEFAULT_PAGE_SIZE, con.paging.DEFAULT_PAGE_SIZE);
});

test("run search agrees with console's original", () => {
  const queries = ["", "  ", "doug", "74", "56", "flagged", "deep", "doug 56", "doug absent", "CLEAN", "missing-token"];
  agree("normalizeQuery", web.search.normalizeQuery, con.search.normalizeQuery,
    [...queries.map((q) => [q]), [null], [undefined]]);
  agree("runMatchesQuery", web.search.runMatchesQuery, con.search.runMatchesQuery,
    RUNS.flatMap((r) => queries.map((q) => [r, q])));
  agree("filterRunsByQuery", web.search.filterRunsByQuery, con.search.filterRunsByQuery,
    queries.map((q) => [RUNS, q]));
});

test("facets agree with console's original, across the rename", () => {
  const selections = [
    {}, { band: [] }, { band: ["flagged"] }, { band: ["flagged", "cleared"] },
    { band: ["purple"] }, { outcome: ["pending"] }, { band: ["flagged"], outcome: ["pending"] },
    { read: ["no-read"] }, { read: ["read"] }, { tier: ["deep"] },
    { outcome_60: ["pending"] }, { outcome_60: ["clean"] },
    { outcome: ["pending"], outcome_60: ["clean"] },
  ];
  agree("buildFacets", web.facets.buildFacets, con.facets.buildFacets,
    [[RUNS], [[]], [[RUNS[0]]], [RUNS.slice(0, 2)]]);
  agree("matchesFacets", web.facets.matchesFacets, con.facets.matchesFacets,
    RUNS.flatMap((r) => selections.map((s) => [r, s])));
  // The rename is the ONLY difference; the behaviour must be identical.
  agree("filterRunsByFacets/filterRuns", web.facets.filterRunsByFacets, con.facets.filterRuns,
    selections.map((s) => [RUNS, s]));
  agree("serializeFacets", web.facets.serializeFacets, con.facets.serializeFacets, selections.map((s) => [s]));
  agree("parseFacetSelection", web.facets.parseFacetSelection, con.facets.parseFacetSelection, [
    [() => null], [() => ""], [(k) => (k === "band" ? " , " : null)],
    [(k) => (k === "band" ? "flagged, " : null)], [(k) => (k === "outcome" ? "pending,reverted" : null)],
  ]);
  assert.deepEqual([...web.facets.FACET_KEYS], [...con.facets.FACET_KEYS]);
});

test("PR grouping agrees with console's original", () => {
  agree("groupRunsByPr", web.grouping.groupRunsByPr, con.grouping.groupRunsByPr, [
    [RUNS, false], [RUNS, true], [[], false], [[], true], [[RUNS[0]], true],
  ]);
  for (const atCap of [false, true]) {
    const webGroups = web.grouping.groupRunsByPr(RUNS, atCap);
    const conGroups = con.grouping.groupRunsByPr(RUNS, atCap);
    for (const filtered of [false, true]) {
      for (let i = 0; i < conGroups.length; i += 1) {
        assert.deepEqual(
          web.grouping.runCountLabel(webGroups[i], filtered),
          con.grouping.runCountLabel(conGroups[i], filtered),
          `runCountLabel diverged (atCap=${atCap}, filtered=${filtered}, group ${i})`,
        );
      }
    }
  }
});

test("sorting agrees with console's original", () => {
  const sorts = [
    { key: "age", dir: "desc" }, { key: "age", dir: "asc" },
    { key: "score", dir: "desc" }, { key: "score", dir: "asc" },
    { key: "coverage", dir: "desc" }, { key: "coverage", dir: "asc" },
  ];
  for (const atCap of [false, true]) {
    const webGroups = web.grouping.groupRunsByPr(RUNS, atCap);
    const conGroups = con.grouping.groupRunsByPr(RUNS, atCap);
    for (const sort of sorts) {
      assert.deepEqual(
        web.sorting.sortGroups(webGroups, sort),
        con.sorting.sortGroups(conGroups, sort),
        `sortGroups diverged (atCap=${atCap}, ${sort.key}:${sort.dir})`,
      );
    }
  }
  agree("nextSort", web.sorting.nextSort, con.sorting.nextSort,
    sorts.flatMap((s) => ["score", "coverage", "age"].map((k) => [s, k])));
  agree("serializeSort", web.sorting.serializeSort, con.sorting.serializeSort, sorts.map((s) => [s]));
  agree("parseSort", web.sorting.parseSort, con.sorting.parseSort,
    [["age:desc"], ["score:asc"], ["coverage:desc"], ["band:asc"], ["score:sideways"], ["nonsense"], [null]].map((a) => a));
  assert.deepEqual([...web.sorting.SORTABLE], [...con.sorting.SORTABLE]);
  assert.deepEqual(web.sorting.DEFAULT_SORT, con.sorting.DEFAULT_SORT);
});

test("the ported CSS utilities stay character-identical to console's", async () => {
  // web/app/globals.css also claims lockstep with console's. The comments in
  // that block are the spec (never a third data colour; --iridescent fails CVD
  // separation at ΔE 6.1; coverage is a magnitude), so a silent edit to either
  // stylesheet is the same class of defect as a silent edit to a module.
  const [webCss, conCss] = await Promise.all([
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../../console/app/globals.css", import.meta.url), "utf8"),
  ]);
  const first = "  /* Tabular numerals are mandatory";
  const start = conCss.indexOf(first);
  assert.ok(start >= 0, "console's globals.css lost the ported utilities block");
  const block = conCss.slice(start, conCss.indexOf("\n", conCss.indexOf(".cov-fill")));
  assert.ok(block.includes(".cov-track") && block.includes(".data-flag"), "block extraction is wrong");
  assert.ok(
    webCss.includes(block),
    "web/app/globals.css no longer contains console's utilities block verbatim",
  );
});

test("no ported test file has gained a test on console's side only", async () => {
  // Behaviour drift is caught above. This catches the other direction: console
  // grows a test for a new honesty property and web's copy silently does not,
  // so web stops proving something console proves.
  //
  // console/lib/runs.test.mjs is deliberately absent: web splits it across
  // runs-time.test.mjs (8, a true copy of the time half) and coverage.test.mjs
  // (Phase A's, which carries 2 against console's 10 — a real pre-existing gap,
  // reported, and not this guard's to assert away).
  const counts = { paging: 0, search: -2, facets: 0, grouping: 0, sorting: 0 };
  const declarations = (src) => (src.match(/^\s*(?:test|it)\(/gm) ?? []).length;

  for (const [module, delta] of Object.entries(counts)) {
    const [webSrc, conSrc] = await Promise.all([
      readFile(new URL(`./${module}.test.mjs`, import.meta.url), "utf8"),
      readFile(new URL(`../../console/lib/${module}.test.mjs`, import.meta.url), "utf8"),
    ]);
    assert.equal(
      declarations(webSrc),
      declarations(conSrc) + delta,
      `${module}.test.mjs: web has ${declarations(webSrc)} tests, console has ${declarations(conSrc)}` +
        (delta ? ` (${delta} ruled: the job-search tests web does not port)` : ""),
    );
  }
});

test("the ported components stay textually identical to console's below their imports", async () => {
  // The three components have no executable surface without rendering them,
  // and render tests are against the house rule. So this pins the one thing
  // that matters: everything below the import block is console's, character
  // for character. The markers are the first line after the imports on both
  // sides — the import blocks themselves legitimately differ, and each file's
  // header comment says how.
  const components = [
    ["band-chip.tsx", "/** The colour is ALWAYS accompanied by its word."],
    ["coverage-ruler.tsx", "/** The console's signature element:"],
    ["run-spine.tsx", "function Event({"],
  ];

  for (const [file, marker] of components) {
    const [webSrc, conSrc] = await Promise.all([
      readFile(new URL(`../components/${file}`, import.meta.url), "utf8"),
      readFile(new URL(`../../console/components/${file}`, import.meta.url), "utf8"),
    ]);
    const wi = webSrc.indexOf(marker);
    const ci = conSrc.indexOf(marker);
    assert.ok(wi >= 0, `${file}: web copy lost its body marker ${JSON.stringify(marker)}`);
    assert.ok(ci >= 0, `${file}: console copy lost its body marker ${JSON.stringify(marker)}`);
    assert.equal(
      webSrc.slice(wi),
      conSrc.slice(ci),
      `${file} diverged from console's copy below the imports`,
    );
  }
});
