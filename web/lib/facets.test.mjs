// Ported verbatim from console/lib/facets.test.mjs — keep the two in lockstep.
// ENFORCED (count only): lib/console-lockstep.test.mjs fails if console's copy
// gains a test this one does not. The bodies are not text-compared.
// Every test name and comment is the console's. The ONE rename: console's
// filterRuns is filterRunsByFacets here, because web/lib/dashboard-model.ts
// already exports a different filterRuns (plan D5).
import assert from "node:assert/strict";
import test from "node:test";

import { FACET_KEYS, buildFacets, filterRunsByFacets, parseFacetSelection, serializeFacets } from "./facets.ts";

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
    outcome_60: null,
    ...overrides,
  };
}

const read = { diff_chars: 1000, sent_chars: 500, files_sent: 4, files_unseen: [], file_cut: null };

test("a pill's count is the exact number of runs it matches", () => {
  // The count is a claim, and it is exact over whatever array it is given.
  // Callers pass the full fetched set — the same set the header counts —
  // and say what that set represents: FacetBar's title reads "in scope"
  // below the page limit and "the newest N fetched" at it.
  const facets = buildFacets([
    run({ verdict_id: 1, band: "flagged" }),
    run({ verdict_id: 2, band: "flagged" }),
    run({ verdict_id: 3, band: "cleared" }),
  ]);

  const band = facets.find((f) => f.key === "band");
  assert.deepEqual(band.options, [
    { value: "cleared", label: "cleared", count: 1 },
    // Label copies BandChip's word; the value stays the wire value, which
    // is what the URL carries and what runs are matched against.
    { value: "flagged", label: "needs you", count: 2 },
  ]);
});

test("a facet with only one value is dropped — it filters nothing", () => {
  // Every run in a single-repo scope is tier "code"; a lone "code" pill
  // is a control that cannot change the result. Rendering it teaches the
  // operator that the pills do nothing.
  const facets = buildFacets([run({ verdict_id: 1, tier: "code" }), run({ verdict_id: 2, tier: "code" })]);

  assert.equal(facets.find((f) => f.key === "tier"), undefined);
});

test("a missing outcome is 'pending', which is a different fact from 'clean'", () => {
  // outcome_14 null means the 14-day window has not closed yet. Folding it
  // into "clean" would claim Doug's verdict was borne out when nothing has
  // been observed at all.
  const facets = buildFacets([
    run({ verdict_id: 1, outcome_14: null }),
    run({ verdict_id: 2, outcome_14: "clean" }),
    run({ verdict_id: 3, outcome_14: "reverted" }),
  ]);

  const outcome = facets.find((f) => f.key === "outcome");
  assert.deepEqual(outcome.options.map((o) => o.value), ["clean", "pending", "reverted"]);
});

test("a missing 60-day outcome is 'pending', which is a different fact from 'clean'", () => {
  // outcome_60 null means the 60-day window has not closed yet — the same
  // fact outcome_14 null states about its own window, and independent of
  // it: a run can be "clean" at 14 days and still "pending" at 60. Folding
  // either into "clean" would claim an observation that has not happened.
  const facets = buildFacets([
    run({ verdict_id: 1, outcome_60: null }),
    run({ verdict_id: 2, outcome_60: "clean" }),
    run({ verdict_id: 3, outcome_60: "reverted" }),
  ]);

  const outcome60 = facets.find((f) => f.key === "outcome_60");
  assert.deepEqual(outcome60.options.map((o) => o.value), ["clean", "pending", "reverted"]);
});

test("'no read' is keyed off a missing coverage row, not off a zero rate", () => {
  // A run with coverage but no denominator was still READ — it just has no
  // rate to show. Grouping it under "no read" would claim Doug never
  // looked at the diff.
  const facets = buildFacets([
    run({ verdict_id: 1, coverage: null, changed_files: null }),
    run({ verdict_id: 2, coverage: read, changed_files: null }),
  ]);

  const readFacet = facets.find((f) => f.key === "read");
  assert.deepEqual(readFacet.options, [
    { value: "no-read", label: "no read", count: 1 },
    { value: "read", label: "read", count: 1 },
  ]);
});

test("values within one facet are OR'd, values across facets are AND'd", () => {
  // The standard faceted-search semantic, and the only one that reads
  // correctly: "flagged OR cleared" narrows nothing, "flagged AND pending"
  // narrows twice.
  const runs = [
    run({ verdict_id: 1, band: "flagged", outcome_14: null }),
    run({ verdict_id: 2, band: "flagged", outcome_14: "clean" }),
    run({ verdict_id: 3, band: "cleared", outcome_14: null }),
  ];

  assert.deepEqual(
    filterRunsByFacets(runs, { band: ["flagged", "cleared"] }).map((r) => r.verdict_id),
    [1, 2, 3],
  );
  assert.deepEqual(
    filterRunsByFacets(runs, { band: ["flagged"], outcome: ["pending"] }).map((r) => r.verdict_id),
    [1],
  );
});

test("an empty selection matches everything rather than nothing", () => {
  // The unfiltered table is the default view. A selection with an empty
  // array for a key is the same fact as that key being absent — both mean
  // "no constraint" — and treating [] as "match none" would blank the
  // table when the last pill in a facet is deselected.
  const runs = [run({ verdict_id: 1 }), run({ verdict_id: 2 })];

  assert.equal(filterRunsByFacets(runs, {}).length, 2);
  assert.equal(filterRunsByFacets(runs, { band: [] }).length, 2);
});

test("an unknown value in the URL matches nothing and does not crash", () => {
  // ?band=purple is reachable by hand-editing or a stale bookmark. The
  // honest result is an empty table under a filter that says "purple" —
  // never a silent fallback to unfiltered, which would show every run
  // while the pill bar claims a filter is on.
  const runs = [run({ verdict_id: 1, band: "flagged" })];

  assert.deepEqual(filterRunsByFacets(runs, { band: ["purple"] }), []);
});

test("selection round-trips through the URL", () => {
  // Operators share console links. A filtered view that does not survive
  // a copied URL is a view they cannot hand to anyone.
  const selection = { band: ["flagged"], outcome: ["pending", "reverted"] };
  const serialized = serializeFacets(selection);

  assert.deepEqual(serialized, { band: "flagged", outcome: "pending,reverted" });
  assert.deepEqual(parseFacetSelection((key) => serialized[key] ?? null), selection);
});

test("blank and whitespace URL values parse to no constraint, not to a phantom value", () => {
  // `?band=` is present-but-empty — the same empty-vs-absent trap
  // ScopeSwitch documents. A [""] selection would match no run at all and
  // blank the table.
  assert.deepEqual(parseFacetSelection(() => ""), {});
  assert.deepEqual(parseFacetSelection((key) => (key === "band" ? " , " : null)), {});
  assert.deepEqual(parseFacetSelection((key) => (key === "band" ? "flagged, " : null)), {
    band: ["flagged"],
  });
});

test("facet keys never collide with the scope params the page reads", () => {
  // The pill bar writes into the same query string the page reads its scope
  // from. A facet named "repo" would silently rewrite the server-side scope
  // filter and refetch a different set than the pills claim to narrow.
  //
  // RE-PINNED for web (RULING 4). Console's copy of this test guards `repo`
  // and `tenant`, which are ITS scope params; web's dashboard is scoped by
  // session and pins that "tenant all" never appears, while it reads `run` to
  // decide which evidence pane to open. Left as console's literals this test
  // would have guarded a param web does not have and missed one it does.
  //
  // The full list lives in lib/dashboard-view.ts, next to the code that writes
  // these keys, and lib/dashboard-view.test.mjs asserts the same separation
  // from that side — so adding a key to either side trips a test.
  for (const key of FACET_KEYS) {
    assert.ok(key !== "repo", `facet key ${key} collides with the server-side fetch scope`);
    assert.ok(key !== "run", `facet key ${key} collides with the open-run selection`);
  }
});

test("every outcome facet names its window, so no pill group says bare \"outcome\"", () => {
  // The KEY is a contract and the LABEL is not. `outcome` stays the key so
  // links already in circulation round-trip; what the pill bar RENDERS is
  // `facet.label`, and both tables now read "14d outcome" / "60d outcome".
  // A group labelled bare "outcome" beside them leaves the reader to guess
  // which window the filter narrows — a bare header is exactly what the
  // two-column ruling refused, and the filter above the columns is not
  // exempt from it.
  const facets = buildFacets([
    run({ verdict_id: 1, outcome_14: "clean", outcome_60: "clean" }),
    run({ verdict_id: 2, outcome_14: null, outcome_60: null }),
  ]);

  const fourteen = facets.find((f) => f.key === "outcome");
  const sixty = facets.find((f) => f.key === "outcome_60");
  assert.ok(fourteen && sixty, "both outcome facets must be built when both vary");
  assert.equal(fourteen.label, "14d outcome");
  assert.equal(sixty.label, "60d outcome");
  // The keys are untouched — a "fix" that renamed the key to match the label
  // would break every shared URL carrying ?outcome=.
  assert.ok(FACET_KEYS.includes("outcome"));
  assert.ok(FACET_KEYS.includes("outcome_60"));
});
