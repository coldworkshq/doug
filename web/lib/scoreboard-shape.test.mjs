import assert from "node:assert/strict";
import test from "node:test";

import { isScoreboardResponse } from "./scoreboard-shape.ts";

function body(overrides = {}) {
  return {
    repo: "drewjst/doug",
    adjudicated: 0,
    pending: 12,
    as_of: "2026-08-13T12:00:00Z",
    first_due: "2026-08-16T00:00:00Z",
    deep_reads: 0,
    deep_read_cap: 200,
    miss_rate: null,
    decidable: false,
    label: "not yet decidable — a count, not a rate",
    ...overrides,
  };
}

test("accepts a body carrying every field the scoreboard page dereferences", () => {
  assert.equal(isScoreboardResponse(body()), true);
});

test("rejects a body that invented a miss rate", () => {
  assert.equal(isScoreboardResponse(body({ miss_rate: 0.12 })), false);
});

test("rejects a body that claims decidable", () => {
  assert.equal(isScoreboardResponse(body({ decidable: true })), false);
});

test("rejects a body missing the honesty label", () => {
  const b = body();
  delete b.label;
  assert.equal(isScoreboardResponse(b), false);
});

test("accepts a null first_due on an empty ledger", () => {
  assert.equal(isScoreboardResponse(body({ first_due: null })), true);
});

test("rejects null, which JSON.parse produces for a bare null body", () => {
  assert.equal(isScoreboardResponse(null), false);
});

test("the public header links to /scoreboard, distinct from /queue", async () => {
  const { readFile } = await import("node:fs/promises");
  const header = await readFile(new URL("../components/site-header.tsx", import.meta.url), "utf8");
  assert.match(header, /href: "\/scoreboard"/);
  assert.match(header, /href: "\/queue"/);
});
