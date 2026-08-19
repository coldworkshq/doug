import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const validConnections = {
  connections: [
    {
      provider: "github",
      installation_id: 101,
      organization_id: "org_acme",
      account_login: "acme",
      account_type: "Organization",
      status: "ready",
      label: null,
      repositories: [
        { id: 11, full_name: "acme/one", needs_you_threshold: null },
        { id: 12, full_name: "acme/two", needs_you_threshold: 0.5 },
      ],
    },
  ],
  default_needs_you_threshold: { reader: 0.3, fallback: 0.62 },
};

test("session fetch is cacheless, bounded, and puts the WorkOS bearer only in a header", async () => {
  const oldFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify(validConnections), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    const { getConnections } = await import("./session-api.ts?request-contract");
    assert.deepEqual(await getConnections("workos-secret"), validConnections);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].options.cache, "no-store");
    assert.equal(calls[0].options.headers.Authorization, "Bearer workos-secret");
    assert.ok(calls[0].options.signal instanceof AbortSignal);
    assert.equal(String(calls[0].url).includes("workos-secret"), false);
    assert.equal(JSON.stringify(calls[0].options).includes("fixture"), false);
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("direct bind posts only the installation id with a bounded WorkOS bearer request", async () => {
  const oldFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(null, { status: 204 });
  };
  try {
    const { bindInstallation } = await import("./session-api.ts?bind-request");
    await bindInstallation("workos-session-secret", 404);
    assert.equal(calls.length, 1);
    assert.equal(String(calls[0].url).endsWith("/v1/installations/bind"), true);
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.cache, "no-store");
    assert.equal(calls[0].options.headers.Authorization, "Bearer workos-session-secret");
    assert.equal(calls[0].options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(calls[0].options.body), { installation_id: 404 });
    assert.ok(calls[0].options.signal instanceof AbortSignal);
    assert.equal(String(calls[0].url).includes("workos-session-secret"), false);
    assert.equal(calls[0].options.body.includes("workos-session-secret"), false);
    assert.equal(calls[0].options.body.includes("organization"), false);
    assert.equal(calls[0].options.body.includes("token"), false);
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("direct bind accepts exactly 204 and keeps upstream and token failures constant", async () => {
  const oldFetch = globalThis.fetch;
  try {
    const { bindInstallation, SessionApiError } = await import(
      "./session-api.ts?bind-failures"
    );
    for (const response of [
      async () => new Response("workos-session-secret leaked upstream", { status: 200 }),
      async () => new Response("provider token leaked upstream", { status: 503 }),
      async () => { throw new Error("network carried workos-session-secret"); },
    ]) {
      globalThis.fetch = response;
      await assert.rejects(
        bindInstallation("workos-session-secret", 404),
        (error) => {
          assert.ok(error instanceof SessionApiError);
          assert.equal(error.message, "Doug could not finish this repository connection.");
          assert.equal(String(error).includes("workos-session-secret"), false);
          assert.equal(String(error).includes("provider token"), false);
          assert.equal(String(error).includes("network carried"), false);
          return true;
        },
      );
    }
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("session responses reject extra or malformed fields instead of rendering invented facts", async () => {
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ ...validConnections, tenant: "all" }), { status: 200 });
  try {
    const { getConnections, SessionApiError } = await import(
      "./session-api.ts?shape-rejection"
    );
    await assert.rejects(getConnections("secret"), SessionApiError);
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("the connections validator accepts the old API body and the reauthorize_required one", async () => {
  // DEPLOY-ORDER SAFETY, and the reason this validator change ships in its own
  // PR ahead of the API's. `.github/workflows/deploy.yml:162` gives the web job
  // `needs: [changes, api]` — the API revision goes live FIRST. If the enum
  // widened on both sides at once, the new API would emit
  // `status: "reauthorize_required"` to a still-running old web build, whose
  // exact-enum check would reject the whole body and turn every dashboard into
  // "Doug could not load your connected spaces." So: web learns to accept it
  // while nothing emits it, and only then does the API emit it.
  const bodies = [
    { label: "old api", status: "ready" },
    { label: "old api", status: "setup_required" },
    { label: "new api", status: "reauthorize_required" },
  ];
  for (const { label, status } of bodies) {
    const oldFetch = globalThis.fetch;
    const body = {
      connections: [{ ...validConnections.connections[0], status }],
      default_needs_you_threshold: validConnections.default_needs_you_threshold,
    };
    globalThis.fetch = async () =>
      new Response(JSON.stringify(body), { status: 200 });
    try {
      const { getConnections } = await import(`./session-api.ts?enum-${status}`);
      assert.deepEqual(
        await getConnections("secret"),
        body,
        `${label} body carrying status=${status} must survive the validator`,
      );
    } finally {
      globalThis.fetch = oldFetch;
    }
  }
});

test("a status outside the known enum is still refused rather than rendered", async () => {
  // Widening the enum is not the same as abandoning it. An unknown status is a
  // fact this build cannot render honestly, so it stays a hard rejection.
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        connections: [{ ...validConnections.connections[0], status: "expired" }],
      }),
      { status: 200 },
    );
  try {
    const { getConnections, SessionApiError } = await import(
      "./session-api.ts?unknown-status"
    );
    await assert.rejects(getConnections("secret"), SessionApiError);
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("session API failures never echo the bearer or upstream response body", async () => {
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response('provider said token "secret-bearing-value" was bad', { status: 401 });
  try {
    const { getConnections } = await import("./session-api.ts?safe-errors");
    await assert.rejects(
      getConnections("secret-bearing-value"),
      (error) => {
        assert.equal(error.message, "Doug could not load your connected spaces.");
        assert.equal(String(error).includes("secret-bearing-value"), false);
        assert.equal(String(error).includes("provider said"), false);
        return true;
      },
    );
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("session data has no fixture or public API fallback", async () => {
  const source = await readFile(new URL("./session-api.ts", import.meta.url), "utf8");
  assert.equal(source.includes('from "./api"'), false);
  assert.equal(source.includes("queue-fixture"), false);
  assert.equal(source.includes("fixture"), false);
  assert.match(source, /cache:\s*["']no-store["']/);
});

test("run list rejects a malformed nested job before the page dereferences it", async () => {
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    items: [{
      verdict_id: 1, repo: "acme/one", installation_id: 101, github_repo_id: 11,
      pr_number: 7, title: "Fix cache", url: null, scored_at: "2026-08-10T10:00:00Z",
      tier: "reader", source: "app", score: 0.2, band: "cleared", threshold: 0.62,
      coverage: null, changed_files: null,
      finding_counts: { total: 0, high: 0, medium: 0, low: 0 },
      job: {
        status: "done", attempts: "one", error: null, enqueued_at: null,
        started_at: null, finished_at: null,
      },
      outcome_14: null,
      outcome_60: null,
    }],
    limit: 100,
    offset: 0,
  }), { status: 200 });
  try {
    const { getSessionRuns, SessionApiError } = await import("./session-api.ts?nested-list");
    await assert.rejects(getSessionRuns("secret"), SessionApiError);
  } finally {
    globalThis.fetch = oldFetch;
  }
});

// Every field of api/doug/models.py's PRMetadata, in that model's order. The
// API always serializes the whole model (api.py's _with_url returns PRMetadata,
// so pydantic fills the defaults), which is what lets the validator be exact.
const validPr = {
  number: 7,
  title: "Fix cache",
  author: "octocat",
  author_type: "human",
  additions: 12,
  deletions: 3,
  files: ["src/cache.ts"],
  approvals: 1,
  approval_latency_s: 3600,
  days_since_last_human_commit: 2,
  files_added: 1,
  files_modified: 0,
  url: "https://github.com/acme/one/pull/7",
  head_sha: "abc123",
  changed_files: 4,
  files_dropped: ["vendor/blob.bin"],
};

function detailBody(pr) {
  return {
    verdict_id: 1, repo: "acme/one", pr_number: 7, installation_id: 101,
    github_repo_id: 11, pr, scored_at: "2026-08-10T10:00:00Z", tier: "reader",
    prompt_hash: null, model: null, source: "app", head_sha: null, risk_score: null,
    rationale: null, score: 0.2, band: "cleared", threshold: 0.62, coverage: null,
    reasons: [], deviations: [], intent_alignment: null, intent_refs: [], job: null,
    outcomes: [], outcome_jobs: [],
  };
}

test("run detail validates PR metadata field-for-field against the API model", async () => {
  const oldFetch = globalThis.fetch;
  try {
    const { getSessionRun, SessionApiError } = await import("./session-api.ts?pr-metadata");

    globalThis.fetch = async () => new Response(JSON.stringify(detailBody(validPr)));
    assert.deepEqual((await getSessionRun("secret", 1)).pr, validPr);

    globalThis.fetch = async () => new Response(JSON.stringify(detailBody(null)));
    assert.equal((await getSessionRun("secret", 1)).pr, null);

    // An unexpected key is the deploy-order signal web must not render past.
    globalThis.fetch = async () =>
      new Response(JSON.stringify(detailBody({ ...validPr, merged_by: "octocat" })));
    await assert.rejects(getSessionRun("secret", 1), SessionApiError);

    for (const missing of ["author", "head_sha", "files_dropped", "changed_files"]) {
      const partial = { ...validPr };
      delete partial[missing];
      globalThis.fetch = async () => new Response(JSON.stringify(detailBody(partial)));
      await assert.rejects(getSessionRun("secret", 1), SessionApiError);
    }
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("getSessionRuns requests an explicit limit and offset", async () => {
  const oldFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return new Response(JSON.stringify({ items: [], limit: 500, offset: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    const { getSessionRuns } = await import("./session-api.ts?run-limit");
    await getSessionRuns("token");
  } finally {
    globalThis.fetch = oldFetch;
  }
  assert.equal(calls.length, 1);
  assert.match(calls[0], /\/v1\/sessions\/runs\?repo=all&limit=500&offset=0$/);
});

test("run detail rejects malformed rendered findings", async () => {
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    verdict_id: 1, repo: "acme/one", pr_number: 7, installation_id: 101,
    github_repo_id: 11, pr: null, scored_at: "2026-08-10T10:00:00Z", tier: "reader",
    prompt_hash: null, model: null, source: "app", head_sha: null, risk_score: null,
    rationale: null, score: 0.2, band: "cleared", threshold: 0.62, coverage: null,
    reasons: [{ rule: "reader:x", weight: 0, severity: "low" }],
    deviations: [], intent_alignment: null, intent_refs: [], job: null,
    outcomes: [], outcome_jobs: [],
  }), { status: 200 });
  try {
    const { getSessionRun, SessionApiError } = await import("./session-api.ts?nested-detail");
    await assert.rejects(getSessionRun("secret", 1), SessionApiError);
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("SessionApiError carries the HTTP status when there was one", async () => {
  const { SessionApiError } = await import("./session-api.ts?error-status-set");
  const err = new SessionApiError("nope", 404);
  assert.equal(err.status, 404);
});

test("SessionApiError status is null when the request never got a response", async () => {
  const { SessionApiError } = await import("./session-api.ts?error-status-null");
  const err = new SessionApiError("nope");
  assert.equal(err.status, null);
});

test("getReceipt rejects a payload that is not a receipt", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ repo: "x" }), { status: 200 });
  try {
    const { getReceipt, SessionApiError } = await import("./session-api.ts?receipt-shape");
    await assert.rejects(() => getReceipt("token", "drewjst/doug", 90), SessionApiError);
  } finally {
    globalThis.fetch = original;
  }
});

test("getReceipt surfaces a 404 as a 404, not as a generic failure", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response("{}", { status: 404 });
  try {
    const { getReceipt } = await import("./session-api.ts?receipt-404");
    await getReceipt("token", "drewjst/doug", 90);
    assert.fail("should have thrown");
  } catch (error) {
    assert.equal(error.status, 404);
  } finally {
    globalThis.fetch = original;
  }
});

test("getReceipt sends repo as a query parameter, encoded", async () => {
  const original = globalThis.fetch;
  let seen = "";
  globalThis.fetch = async (url) => {
    seen = String(url);
    return new Response("{}", { status: 404 });
  };
  try {
    const { getReceipt } = await import("./session-api.ts?receipt-query");
    await getReceipt("token", "drewjst/doug", 90).catch(() => {});
    assert.ok(seen.includes("/v1/prs/90/receipt?repo=drewjst%2Fdoug"));
  } finally {
    globalThis.fetch = original;
  }
});

test("the connections validator now requires the per-repo flag line and the process defaults", async () => {
  // Task 1 made these keys TOLERATED so this build could deploy ahead of the
  // API (deploy.yml gives the web job `needs: [changes, api]`, so the API
  // revision is already live by the time this build runs). Task 7 shipped the
  // API side, so the keys are load-bearing now: a body missing either one is
  // as malformed as a body with an unknown key.
  const { getConnections, SessionApiError } = await import(
    "./session-api.ts?required-flag-fields"
  );
  const oldFetch = globalThis.fetch;
  try {
    // The full, current shape still round-trips.
    globalThis.fetch = async () =>
      new Response(JSON.stringify(validConnections), { status: 200 });
    assert.deepEqual(await getConnections("token"), validConnections);

    // Missing the top-level process defaults: rejected.
    const withoutDefaults = { connections: validConnections.connections };
    globalThis.fetch = async () =>
      new Response(JSON.stringify(withoutDefaults), { status: 200 });
    await assert.rejects(() => getConnections("token"), SessionApiError);

    // A repository missing its own flag line: rejected.
    const missingRepoField = {
      ...validConnections,
      connections: [{
        ...validConnections.connections[0],
        repositories: [{ id: 11, full_name: "acme/one" }],
      }],
    };
    globalThis.fetch = async () =>
      new Response(JSON.stringify(missingRepoField), { status: 200 });
    await assert.rejects(() => getConnections("token"), SessionApiError);

    // Still exact on everything else: an unknown key is still rejected.
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ ...validConnections, surprise: 1 }), { status: 200 });
    await assert.rejects(() => getConnections("token"), SessionApiError);
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("setRepositoryThreshold PATCHes a JSON number or null, never a string, and returns the stored value", async () => {
  const { setRepositoryThreshold } = await import("./session-api.ts");
  const calls = [];
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ needs_you_threshold: 0.62 }), { status: 200 });
  };
  try {
    const stored = await setRepositoryThreshold("token", 11, 0.6249);
    assert.equal(stored, 0.62);
    assert.equal(calls[0].url, `${process.env.DOUG_API_URL ?? "http://localhost:8000"}/v1/sessions/repositories/11`);
    assert.equal(calls[0].options.method, "PATCH");
    assert.deepStrictEqual(JSON.parse(calls[0].options.body), { needs_you_threshold: 0.6249 });
    assert.equal(typeof JSON.parse(calls[0].options.body).needs_you_threshold, "number");
    await setRepositoryThreshold("token", 11, null);
    assert.deepStrictEqual(JSON.parse(calls[1].options.body), { needs_you_threshold: null });
    // Out-of-range never leaves the client.
    await assert.rejects(() => setRepositoryThreshold("token", 11, 1.5));
    await assert.rejects(() => setRepositoryThreshold("token", 11, Number.NaN));
    assert.equal(calls.length, 2);
  } finally {
    globalThis.fetch = oldFetch;
  }
});
