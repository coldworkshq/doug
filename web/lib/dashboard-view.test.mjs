// The dashboard's facet bar, search box and pager are SERVER-rendered: they
// emit <Link>s and a GET <form> rather than mutating client state (RULING 2).
// That makes every one of them a query-string rewrite, and a query-string
// rewrite is a pure function — so it is tested here rather than by rendering.
import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const view = await import("./dashboard-view.ts");
const { FACET_KEYS } = await import("./facets.ts");

/** What the page's own `href(params, changes)` helper does with a changes
 *  object, reduced to the part these functions are responsible for: a null
 *  deletes the key, a string sets it. Re-implemented here on URLSearchParams
 *  so the assertions read as the URL a user would actually land on. */
function apply(params, changes) {
  const next = new URLSearchParams(params);
  for (const [key, item] of Object.entries(changes)) {
    if (item === null) next.delete(key);
    else next.set(key, item);
  }
  return next.toString();
}

test("toggling a pill on and then off returns the exact URL you started from", () => {
  // The round trip is the property. A toggle that adds `band=flagged` but
  // leaves `band=` behind on the way out, or that quietly drops `repo`, gives
  // an operator a URL they cannot get back from by clicking the same pill.
  const start = "repo=acme%2Fone&run=91";
  const on = apply(start, view.facetToggleChanges({}, "band", "flagged"));
  assert.equal(on, "repo=acme%2Fone&run=91&band=flagged");

  const off = apply(on, view.facetToggleChanges({ band: ["flagged"] }, "band", "flagged"));
  assert.equal(off, start);
});

test("a second value on the same facet widens the selection instead of replacing it", () => {
  // OR within a facet: this is the case the band/tier collision blocked. The
  // value written is comma-joined, which is what `parseFacetSelection` reads.
  const changes = view.facetToggleChanges({ band: ["flagged"] }, "band", "cleared");
  assert.equal(changes.band, "flagged,cleared");
  assert.equal(apply("", changes), "band=flagged%2Ccleared");
});

test("every facet key is written on every toggle, so a deselected facet is deleted not left stale", () => {
  // The failure this refuses: toggling the last value off a facet writes only
  // the facet you touched, and the URL keeps `outcome=pending` from a previous
  // click while the bar renders it unselected.
  const changes = view.facetToggleChanges({ outcome: ["pending"] }, "outcome", "pending");
  for (const key of FACET_KEYS) {
    assert.ok(key in changes, `toggle did not write the ${key} facet`);
  }
  assert.equal(changes.outcome, null);
  assert.equal(apply("outcome=pending&repo=acme%2Fone", changes), "repo=acme%2Fone");
});

test("changing the filter returns to the first page", () => {
  // Page 4 of the unfiltered list is not page 4 of the filtered one. Keeping
  // the page number across a filter change lands the operator on an empty
  // page and reads as "no runs match" rather than "you are past the end".
  assert.equal(view.facetToggleChanges({}, "band", "flagged").page, null);
  assert.equal(view.facetClearChanges().page, null);
  assert.equal(view.sortChanges({ key: "score", dir: "desc" }).page, null);
  // The page's own two predicates change which rows there are just as a facet
  // does, so they follow the same rule rather than a second one.
  assert.equal(view.predicateChanges("coverage", "low").page, null);
  assert.deepEqual(view.predicateChanges("error", null), { error: null, page: null });
});

test("clearing removes every facet and nothing else", () => {
  const changes = view.facetClearChanges();
  for (const key of FACET_KEYS) assert.equal(changes[key], null);
  // Scope and the page's own predicates are NOT facets and must survive —
  // "clear filters" that silently refetched a different repo would change what
  // the table is a view OF, not just which of its rows show.
  assert.equal(
    apply("repo=acme%2Fone&band=flagged&coverage=low&error=yes&run=91", changes),
    "repo=acme%2Fone&coverage=low&error=yes&run=91",
  );
});

test("the default sort writes no param, so two identical views share one URL", () => {
  assert.equal(view.sortChanges({ key: "age", dir: "desc" }).sort, null);
  assert.equal(view.sortChanges({ key: "score", dir: "asc" }).sort, "score:asc");
});

test("a GET form re-submits the view it does not own, and invents nothing", () => {
  // A GET <form> submits ONLY its own controls, so the search box would
  // silently clear every pill the operator had set. These hidden inputs are
  // what stop that — and they carry only keys that are actually present, never
  // a blank `band=` that `parseFacetSelection` documents as the empty-vs-absent
  // trap.
  const carried = view.carriedParams(
    { repo: "acme/one", band: "flagged,cleared", outcome: undefined, coverage: "low", q: "old", page: "3" },
    ["q", "page"],
  );
  // WHICH keys travel is the property; the order hidden inputs appear in is
  // not, so this compares as a map rather than pinning an arbitrary sequence.
  assert.deepEqual(Object.fromEntries(carried), {
    repo: "acme/one",
    band: "flagged,cleared",
    coverage: "low",
  });
  // `q` and `page` are the form's own controls, so re-submitting them as
  // hidden inputs too would send the key twice and let the stale copy win.
  assert.equal(carried.some(([key]) => key === "q" || key === "page"), false);
});

test("the search form drops the run selection, because the open run may not survive the search", () => {
  // `?run=` opens the evidence pane for one verdict. Searching can exclude
  // that very run, and a pane pinned open beside a table that no longer lists
  // its row claims the row is there.
  const carried = view.carriedParams({ repo: "acme/one", run: "91" }, ["q", "page"]);
  assert.equal(carried.some(([key]) => key === "run"), false);
});

test("no facet key may collide with a param the dashboard page reads for itself", () => {
  // Web's version of console's own collision guard. The pill bar writes into
  // the same query string the page reads its scope and its predicates from: a
  // facet named `repo` would rewrite what the SERVER fetches while claiming to
  // narrow the result, and one named `run` would open an evidence pane.
  for (const key of FACET_KEYS) {
    assert.equal(
      view.DASHBOARD_OWN_PARAMS.includes(key),
      false,
      `facet key ${key} collides with a param the page reads itself`,
    );
  }
  // Non-vacuity: the guard is worthless if the list it checks against is empty
  // or has quietly lost the scope param it exists for.
  assert.ok(view.DASHBOARD_OWN_PARAMS.includes("repo"));
  assert.ok(view.DASHBOARD_OWN_PARAMS.includes("run"));
});

test("a selection nothing matches is still shown, and still clearable", async () => {
  // Doug, PR 102, reader:query-param-contract-change. A stale or mistyped link
  // (?band=foo) is a real constraint — the table is correctly empty — but
  // buildFacets derives pills from the fetched runs, so nothing rendered the
  // filter that was doing the excluding. The page said "the filter excludes
  // them" and offered no filter to see or clear.
  const { withSelectedOptions } = await import("./dashboard-view.ts?ghost");

  const facets = [
    { key: "band", label: "band", options: [{ value: "flagged", label: "needs you", count: 2 }] },
  ];

  const merged = withSelectedOptions(facets, { band: ["flagged", "foo"] });
  assert.equal(merged.length, 1);
  // Appended, not interleaved: it is not part of the population the real
  // counts partition, and sorting it in would imply it is.
  assert.deepEqual(merged[0].options.map((option) => option.value), ["flagged", "foo"]);
  // Count 0 is the honest number — no run carries it — and it is what makes
  // the pill legible as "this is why the table is empty".
  assert.equal(merged[0].options[1].count, 0);

  // A selected key with NO facet at all still gets its group; otherwise the
  // only evidence of the constraint is the address bar.
  const orphan = withSelectedOptions([], { outcome: ["revert"] });
  assert.equal(orphan.length, 1);
  assert.equal(orphan[0].key, "outcome");
  assert.deepEqual(orphan[0].options, [{ value: "revert", label: "revert", count: 0 }]);

  // And a selection the data DOES cover is left exactly as it was — no
  // duplicate pill, no reordering.
  assert.deepEqual(withSelectedOptions(facets, { band: ["flagged"] }), facets);
  assert.deepEqual(withSelectedOptions(facets, {}), facets);
});
