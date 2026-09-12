import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";

import { runScript, withServer } from "./smoke-harness.mjs";

// The deploy-time probe for ADR-0034 decision 1: after every web promotion,
// one public path on the subdomain must answer 308 to the same path and
// query on the apex. These cases are what the probe has to tell apart: the
// redirect that fired correctly, the redirect that never fired (a 200, which
// is what the subdomain answers before the rule deploys), the proxy's 307
// answering in its place, and a 308 that lands on another host or drops the
// query.

const WEB_DIR = fileURLToPath(new URL("..", import.meta.url));
const SCRIPT = path.join(WEB_DIR, "scripts/smoke-subdomain-redirect.sh");
const APEX = "https://apex.example";
const PROBE = "/scoreboard?smoke=subdomain";

const runSmoke = (subdomainUrl) => runScript(SCRIPT, [subdomainUrl, APEX], WEB_DIR);

// Any path other than the probe answers 404, so a renamed probe fails the
// script at once with its own message instead of stalling curl.
function answering(status, location) {
  return (request, response) => {
    if (request.url !== PROBE) {
      response.writeHead(404);
    } else {
      response.writeHead(status, location ? { location } : {});
    }
    response.end();
  };
}

test("a path-preserving 308 to the apex passes the subdomain smoke", async () => {
  await withServer(answering(308, `${APEX}${PROBE}`), async (subdomain) => {
    const result = await runSmoke(subdomain);
    assert.equal(result.code, 0, result.stdout + result.stderr);
    assert.match(result.stdout, /308/);
  });
});

test("a 200 from the subdomain cannot pass: the redirect never fired", async () => {
  await withServer(answering(200), async (subdomain) => {
    const result = await runSmoke(subdomain);
    assert.notEqual(result.code, 0, result.stdout + result.stderr);
    assert.match(result.stderr, /did not answer/);
  });
});

test("the proxy's 307 in place of the config 308 cannot pass", async () => {
  await withServer(answering(307, `${APEX}${PROBE}`), async (subdomain) => {
    const result = await runSmoke(subdomain);
    assert.notEqual(result.code, 0, result.stdout + result.stderr);
    assert.match(result.stderr, /did not answer/);
  });
});

test("a 308 to another host cannot pass", async () => {
  await withServer(answering(308, `https://wrong.example${PROBE}`), async (subdomain) => {
    const result = await runSmoke(subdomain);
    assert.notEqual(result.code, 0, result.stdout + result.stderr);
    assert.match(result.stderr, /went elsewhere/);
  });
});

test("a 308 that drops the query cannot pass", async () => {
  await withServer(answering(308, `${APEX}/scoreboard`), async (subdomain) => {
    const result = await runSmoke(subdomain);
    assert.notEqual(result.code, 0, result.stdout + result.stderr);
    assert.match(result.stderr, /went elsewhere/);
  });
});
