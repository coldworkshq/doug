// The reader's intent: a figure reaches a page only with its sentence, and
// every other outcome is `unknown` with the reason a person can read. A
// stale document never becomes a quotable number, whether it says so itself
// or has simply aged on the way here.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { register } from "node:module";
import test from "node:test";

// registry-api.ts imports its sibling the way Next resolves it; Node needs
// the loader that appends .ts (see node-next-loader.mjs).
register("./node-next-loader.mjs", import.meta.url);

const { readRegistrySnapshot } = await import("./registry-api.ts");

const fixtureText = await readFile(
  new URL("./registry-contract/registry-snapshot.v1.fixture.json", import.meta.url),
  "utf8",
);
const fixture = () => JSON.parse(fixtureText);
const GENERATED_AT = Date.parse(JSON.parse(fixtureText).generated_at);

function fakeFetch(status, body, { json = true } = {}) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => {
        if (!json) throw new SyntaxError("not json");
        return body;
      },
    };
  };
  return { impl, calls };
}

const fresh = () => GENERATED_AT + 60_000;

test("a fresh document is a snapshot, read from the contract path with no credential", async () => {
  const { impl, calls } = fakeFetch(200, fixture());
  const result = await readRegistrySnapshot({ baseUrl: "https://registry.example/", fetchImpl: impl, now: fresh });
  assert.equal(result.kind, "snapshot");
  assert.equal(calls[0].url, "https://registry.example/api/registry/v1/snapshot");
  assert.equal("authorization" in calls[0].init.headers, false);
  assert.equal(calls[0].init.cache, "no-store");
});

test("the bearer slot is sent only when set", async () => {
  const { impl, calls } = fakeFetch(200, fixture());
  await readRegistrySnapshot({ baseUrl: "https://registry.example", bearer: "t", fetchImpl: impl, now: fresh });
  assert.equal(calls[0].init.headers.authorization, "Bearer t");
});

test("no base URL is unknown with the reason, and nothing is fetched", async () => {
  const { impl, calls } = fakeFetch(200, fixture());
  const result = await readRegistrySnapshot({ baseUrl: undefined, fetchImpl: impl, now: fresh });
  assert.equal(result.kind, "unknown");
  assert.match(result.reason, /COLDWORKS_REGISTRY_URL/);
  assert.equal(calls.length, 0);
});

test("a document that says it is stale is unknown with the registry's own reason", async () => {
  const doc = fixture();
  doc.stale = true;
  doc.reason = "stale mirror: the snapshot is 4000s old and the window is 900s";
  const { impl } = fakeFetch(200, doc);
  const result = await readRegistrySnapshot({ baseUrl: "https://r", fetchImpl: impl, now: fresh });
  assert.equal(result.kind, "unknown");
  assert.match(result.reason, /stale mirror/);
});

test("mutation: a document that aged past its own window on the way here is unknown even though it says stale: false", async () => {
  const doc = fixture();
  assert.equal(doc.stale, false);
  const { impl } = fakeFetch(200, doc);
  const later = () => GENERATED_AT + (doc.stale_after_seconds + 1) * 1000;
  const result = await readRegistrySnapshot({ baseUrl: "https://r", fetchImpl: impl, now: later });
  assert.equal(result.kind, "unknown");
  assert.match(result.reason, /old when read/);
});

test("a 503 refusal carries the registry's reason, not a bare status", async () => {
  const doc = fixture();
  doc.snapshot = null;
  doc.generated_at = null;
  doc.reason = "REGISTRY_DATA_PROVENANCE is not set.";
  const { impl } = fakeFetch(503, doc);
  const result = await readRegistrySnapshot({ baseUrl: "https://r", fetchImpl: impl, now: fresh });
  assert.equal(result.kind, "unknown");
  assert.match(result.reason, /PROVENANCE/);
});

test("a non-200 with no document is unknown with the status", async () => {
  const { impl } = fakeFetch(502, { error: "bad gateway" });
  const result = await readRegistrySnapshot({ baseUrl: "https://r", fetchImpl: impl, now: fresh });
  assert.equal(result.kind, "unknown");
  assert.match(result.reason, /502/);
});

test("a body that is not JSON is unknown, not a crash", async () => {
  const { impl } = fakeFetch(200, null, { json: false });
  const result = await readRegistrySnapshot({ baseUrl: "https://r", fetchImpl: impl, now: fresh });
  assert.equal(result.kind, "unknown");
  assert.match(result.reason, /not JSON/);
});

test("a schema version this build does not know is refused by name", async () => {
  const doc = fixture();
  doc.schema_version = 2;
  const { impl } = fakeFetch(200, doc);
  const result = await readRegistrySnapshot({ baseUrl: "https://r", fetchImpl: impl, now: fresh });
  assert.equal(result.kind, "unknown");
  assert.match(result.reason, /schema_version 2/);
});

test("a document the guard rejects is unknown, and no figure leaks through", async () => {
  const doc = fixture();
  delete doc.provenance;
  const { impl } = fakeFetch(200, doc);
  const result = await readRegistrySnapshot({ baseUrl: "https://r", fetchImpl: impl, now: fresh });
  assert.equal(result.kind, "unknown");
  assert.match(result.reason, /did not match/);
});

test("a fetch that throws is unknown with the error's name", async () => {
  const impl = async () => {
    throw new DOMException("aborted", "TimeoutError");
  };
  const result = await readRegistrySnapshot({ baseUrl: "https://r", fetchImpl: impl, now: fresh });
  assert.equal(result.kind, "unknown");
  assert.match(result.reason, /TimeoutError/);
});
