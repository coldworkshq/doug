import assert from "node:assert/strict";
import test from "node:test";

import { isQueueResponse } from "./queue-shape.ts";

function body(overrides = {}) {
  return {
    summary: { open: 1, flagged: 1, cleared: 0, threshold: 0.3 },
    items: [
      {
        pr: { number: 7, files: ["a.py"] },
        verdict: { score: 0.9, reasons: [] },
      },
    ],
    ...overrides,
  };
}

test("accepts a body carrying every field the pages dereference", () => {
  assert.equal(isQueueResponse(body()), true);
});

test("rejects a summary missing a counter", () => {
  assert.equal(
    isQueueResponse(body({ summary: { open: 1, flagged: 1, cleared: 0 } })),
    false,
  );
});

test("rejects an item whose verdict lost its reasons array", () => {
  assert.equal(
    isQueueResponse(
      body({ items: [{ pr: { number: 7, files: [] }, verdict: { score: 0.1 } }] }),
    ),
    false,
  );
});

test("rejects null, which JSON.parse produces for a bare null body", () => {
  assert.equal(isQueueResponse(null), false);
});
