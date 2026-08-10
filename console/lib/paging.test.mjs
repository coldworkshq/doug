import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DEFAULT_PAGE_SIZE,
  pageRangeLabel,
  pageSlice,
  parsePage,
} from "./paging.ts";

describe("parsePage", () => {
  it("defaults missing and blank to 1", () => {
    assert.equal(parsePage(null), 1);
    assert.equal(parsePage(""), 1);
    assert.equal(parsePage("  "), 1);
  });
  it("rejects non-integers and non-positive values", () => {
    assert.equal(parsePage("0"), 1);
    assert.equal(parsePage("-3"), 1);
    assert.equal(parsePage("1.5"), 1);
    assert.equal(parsePage("nope"), 1);
  });
  it("accepts a real page number", () => {
    assert.equal(parsePage("3"), 3);
  });
});

describe("pageSlice", () => {
  const items = Array.from({ length: 120 }, (_, i) => i + 1);

  it("defaults to page size 50", () => {
    assert.equal(DEFAULT_PAGE_SIZE, 50);
    const first = pageSlice(items, 1);
    assert.equal(first.items.length, 50);
    assert.equal(first.items[0], 1);
    assert.equal(first.items[49], 50);
    assert.equal(first.from, 1);
    assert.equal(first.to, 50);
    assert.equal(first.pageCount, 3);
  });

  it("clamps a page past the end down to the last page", () => {
    const last = pageSlice(items, 99);
    assert.equal(last.page, 3);
    assert.deepEqual(last.items, [101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120]);
    assert.equal(last.from, 101);
    assert.equal(last.to, 120);
  });

  it("returns an empty window for an empty list", () => {
    const empty = pageSlice([], 4);
    assert.deepEqual(empty.items, []);
    assert.equal(empty.page, 1);
    assert.equal(empty.from, 0);
    assert.equal(empty.to, 0);
    assert.equal(empty.pageCount, 1);
  });
});

describe("pageRangeLabel", () => {
  it("renders the inclusive range", () => {
    assert.equal(
      pageRangeLabel(pageSlice([1, 2, 3, 4, 5], 1, 2)),
      "1–2 of 5",
    );
  });
  it("renders zero of zero when empty", () => {
    assert.equal(pageRangeLabel(pageSlice([], 1)), "0 of 0");
  });
});
