import assert from "node:assert/strict";
import test from "node:test";

import {
  getExamplePackCohorts,
  getJobs,
  getRuns,
  isError,
  postExamplePackAdjudication,
} from "./api.ts";

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

const HASH = "a".repeat(64);

function examplePackSummary() {
  return {
    cohort_id: "dogfood-2026-08",
    manifest: {
      schema_version: "example-pack-cohort-v0",
      cohort_id: "dogfood-2026-08",
      capture_started_at: "2026-08-10T18:00:00Z",
      capture_until: "2026-08-17T18:00:00Z",
      installation_ids: [11],
      github_repository_ids: [22],
      attempt_kinds: ["risk"],
      finding_cap: 3,
      raw_retention_days: 90,
      application_revision: "c".repeat(40),
    },
    availability: { status: "empty", reason: "no attempts" },
    completeness: {
      completed_jobs: 0,
      members: 0,
      missing: [],
      extra: [],
      boundary: "terminal-start-or-membership-linked-v0",
    },
  };
}

function exampleAdjudication() {
  return {
    schema_version: "example-adjudication-v0",
    adjudication_id: HASH,
    pack_hash: HASH,
    run_id: "review-job:9:claim:1:risk",
    finding_id: HASH,
    disposition: "unknown",
    evidence: [],
    verifier_receipts: [],
    adjudicator: "andrew",
    adjudicated_at: "2026-08-10T20:00:00Z",
    supersedes: null,
  };
}

test("Example Pack GET uses only the purpose token and no-store", () => {
  const priorPurpose = process.env.DOUG_EXAMPLE_PACK_TOKEN;
  const priorOperator = process.env.DOUG_API_TOKEN;
  process.env.DOUG_EXAMPLE_PACK_TOKEN = "purpose-only-secret";
  process.env.DOUG_API_TOKEN = "operator-secret";
  let request;
  return withFetch(
    async (url, init) => {
      request = { url: String(url), init };
      return Response.json([examplePackSummary()]);
    },
    async () => {
      try {
        const result = await getExamplePackCohorts();
        assert.equal(isError(result), false);
        assert.equal(request.init.cache, "no-store");
        assert.equal(request.init.headers["X-Doug-Example-Pack-Token"], "purpose-only-secret");
        assert.equal(request.init.headers["X-Doug-Token"], undefined);
        assert.equal(JSON.stringify(request).includes("operator-secret"), false);
      } finally {
        process.env.DOUG_EXAMPLE_PACK_TOKEN = priorPurpose;
        process.env.DOUG_API_TOKEN = priorOperator;
      }
    },
  );
});

test("Example Pack POST sends only validated adjudication fields", () => {
  const priorPurpose = process.env.DOUG_EXAMPLE_PACK_TOKEN;
  process.env.DOUG_EXAMPLE_PACK_TOKEN = "purpose-only-secret";
  let sentBody;
  return withFetch(
    async (_url, init) => {
      sentBody = JSON.parse(init.body);
      return Response.json(exampleAdjudication());
    },
    async () => {
      try {
        const result = await postExamplePackAdjudication("cohort/id", HASH, HASH, {
          disposition: "unknown",
          evidence: [],
          verifier_receipts: [],
          expected_current_adjudication_id: null,
        });
        assert.equal(isError(result), false);
        assert.deepEqual(Object.keys(sentBody).sort(), [
          "disposition",
          "evidence",
          "expected_current_adjudication_id",
          "verifier_receipts",
        ]);
      } finally {
        process.env.DOUG_EXAMPLE_PACK_TOKEN = priorPurpose;
      }
    },
  );
});

test("Example Pack failures never echo the purpose credential", () => {
  const priorPurpose = process.env.DOUG_EXAMPLE_PACK_TOKEN;
  process.env.DOUG_EXAMPLE_PACK_TOKEN = "must-not-leak";
  return withFetch(
    async () => {
      throw new Error("transport carried must-not-leak");
    },
    async () => {
      try {
        const result = await getExamplePackCohorts();
        assert.equal(isError(result), true);
        assert.equal(result.error.includes("must-not-leak"), false);
      } finally {
        process.env.DOUG_EXAMPLE_PACK_TOKEN = priorPurpose;
      }
    },
  );
});
