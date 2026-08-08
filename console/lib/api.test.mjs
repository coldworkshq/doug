import assert from "node:assert/strict";
import test from "node:test";

import { getJobs, getRuns, isError } from "./api.ts";

test("isError treats an API failure as an error, never as empty data", () => {
  // The console must never render a number when the API is unreachable.
  // An empty items array and a failed fetch are different facts and the
  // page states them differently.
  assert.equal(isError({ error: "/v1/runs → HTTP 503" }), true);
  assert.equal(isError({ items: [] }), false);
});

// The three failure modes get<T> actually distinguishes, exercised through
// getRuns with fetch stubbed. This is the behaviour Phase 1's exit criterion
// depends on: stopping doug-api must render the explicit failure panel and
// no numbers — never a plausible-looking empty run list, which is exactly
// what these tests would fail to catch if get<T> silently returned {items: []}.

function withFetch(fn, run) {
  const original = globalThis.fetch;
  globalThis.fetch = fn;
  return run().finally(() => {
    globalThis.fetch = original;
  });
}

test("getRuns reports a non-2xx response as an error, never as an empty run list", () =>
  withFetch(
    // The realistic case: doug-api answers 503 when the ledger is
    // unconfigured (api/doug/api.py's `store.enabled()` guard).
    async () => new Response(null, { status: 503 }),
    async () => {
      const result = await getRuns({});
      assert.equal(isError(result), true);
      assert.match(result.error, /503/);
      assert.notDeepEqual(result, { items: [] });
    },
  ));

test("getRuns reports fetch itself throwing (network unreachable) as an error", () =>
  withFetch(
    async () => {
      throw new TypeError("fetch failed");
    },
    async () => {
      const result = await getRuns({});
      assert.equal(isError(result), true);
      assert.match(result.error, /fetch failed/);
    },
  ));

test("getRuns reports a 200 with an unparseable body as an error, not a crash", () =>
  withFetch(
    // A 200 whose body isn't valid JSON must not throw past getRuns, and
    // must not be swallowed into a false-empty result — res.json() rejects
    // and lands in the same catch that handles a network throw.
    async () => new Response("not json", { status: 200 }),
    async () => {
      const result = await getRuns({});
      assert.equal(isError(result), true);
      assert.notDeepEqual(result, { items: [] });
    },
  ));

test("getJobs sends installationId 0 as a real filter, never drops it as falsy", () => {
  // installation id 0 is falsy but is a value the caller passed, not an
  // absent one — the same trap `parseTenantId` exists to close on the Runs
  // page (lib/runs.ts). getJobs reproduces getRuns's `installationId !==
  // undefined` guard verbatim; a naive `if (params.installationId)` would
  // silently drop 0 and query every installation while the caller still
  // believes it asked for one.
  let requestedUrl;
  return withFetch(
    async (url) => {
      requestedUrl = String(url);
      return new Response(JSON.stringify({ items: [], limit: 100, offset: 0 }), { status: 200 });
    },
    async () => {
      const result = await getJobs({ lane: "review", view: "unhealthy", installationId: 0 });
      assert.equal(isError(result), false);
      assert.match(requestedUrl, /(?:\?|&)installation_id=0(?:&|$)/);
    },
  );
});
