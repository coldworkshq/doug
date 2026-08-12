import assert from "node:assert/strict";
import test from "node:test";

import {
  adjacentDocsPages,
  DOCS_NAV,
  filterDocsNav,
  flattenDocsNav,
} from "./docs-nav.ts";

test("every doc href is unique — a duplicate would make prev/next and the active-link check ambiguous", () => {
  const hrefs = flattenDocsNav().map((p) => p.href);
  assert.equal(new Set(hrefs).size, hrefs.length);
});

test("the introduction page has no prev — it is the start of reading order, not a mid-list item", () => {
  const { prev, next } = adjacentDocsPages("/docs");
  assert.equal(prev, null);
  assert.equal(next?.href, "/docs/quickstart");
});

test("the last page has no next — prev/next must not wrap around to Introduction", () => {
  const last = flattenDocsNav().at(-1);
  const { next } = adjacentDocsPages(last.href);
  assert.equal(next, null);
});

test("prev/next are the immediate neighbors across a group boundary, not just within one group", () => {
  // "What Doug gets wrong" closes Concepts; "CLI · doug-backtest" opens
  // Reference. Paging must cross that boundary, not stop at the group edge.
  const { next } = adjacentDocsPages("/docs/what-doug-gets-wrong");
  assert.equal(next?.href, "/docs/cli");
});

test("an href with no match returns nulls instead of a false neighbor", () => {
  const { prev, next } = adjacentDocsPages("/docs/nonexistent");
  assert.equal(prev, null);
  assert.equal(next, null);
});

test("an empty query returns every group unfiltered", () => {
  assert.deepEqual(filterDocsNav(""), [...DOCS_NAV]);
});

test("filtering is case-insensitive and matches mid-title, matching the ported site's contract", () => {
  const groups = filterDocsNav("CLEARED");
  const titles = groups.flatMap((g) => g.pages.map((p) => p.title));
  assert.deepEqual(titles, ["The cleared band"]);
});

test("a group with zero surviving matches is dropped, not rendered empty", () => {
  const groups = filterDocsNav("changelog");
  assert.equal(groups.length, 1);
  assert.equal(groups[0].name, "Meta");
});

test("a query matching nothing returns no groups at all", () => {
  assert.deepEqual(filterDocsNav("xyz-does-not-exist"), []);
});

test("every 'available' status page actually exists in Reference or earlier — Coming up is preview/planned only", () => {
  const comingUp = DOCS_NAV.find((g) => g.name === "Coming up");
  for (const page of comingUp.pages) {
    assert.notEqual(
      page.status,
      "available",
      `${page.title} is in "Coming up" but marked available`,
    );
  }
});
