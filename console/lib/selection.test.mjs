import assert from "node:assert/strict";
import { test } from "node:test";

import { RUN_PARAM, applyRunParam, parseRunId, runHref } from "./selection.ts";

test("parseRunId accepts positive integers only", () => {
  assert.equal(parseRunId("1071"), 1071);
  assert.equal(parseRunId("1"), 1);
  assert.equal(parseRunId(undefined), null);
  assert.equal(parseRunId(null), null);
  assert.equal(parseRunId(""), null);
  assert.equal(parseRunId("0"), null);
  assert.equal(parseRunId("-3"), null);
  assert.equal(parseRunId("1.5"), null);
  assert.equal(parseRunId("abc"), null);
  assert.equal(parseRunId("1071 "), 1071);
});

test("applyRunParam sets and clears without touching other keys", () => {
  const params = new URLSearchParams("tenant=1&band=flagged&run=9");
  applyRunParam(params, 1071);
  assert.equal(params.get(RUN_PARAM), "1071");
  assert.equal(params.get("tenant"), "1");
  assert.equal(params.get("band"), "flagged");
  applyRunParam(params, null);
  assert.equal(params.get(RUN_PARAM), null);
  assert.equal(params.get("tenant"), "1");
});

test("run param name does not collide with facet or scope keys", () => {
  assert.equal(RUN_PARAM, "run");
  for (const key of ["band", "tier", "read", "outcome", "repo", "tenant", "sort"]) {
    assert.notEqual(RUN_PARAM, key);
  }
});

test("runHref sets run while preserving other params", () => {
  const base = new URLSearchParams("tenant=1&band=flagged&sort=-score");
  assert.equal(
    runHref(1071, base),
    "/?tenant=1&band=flagged&sort=-score&run=1071",
  );
  assert.equal(runHref(null, new URLSearchParams("run=9&tenant=1")), "/?tenant=1");
  assert.equal(runHref(null, new URLSearchParams("run=9")), "/");
});
