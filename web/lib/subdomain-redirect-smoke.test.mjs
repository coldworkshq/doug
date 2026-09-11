import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";

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

function runSmoke(subdomainUrl) {
  return new Promise((resolve, reject) => {
    const child = spawn("bash", [SCRIPT, subdomainUrl, APEX], { cwd: WEB_DIR });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal, stdout, stderr }));
  });
}

async function withServer(handler, run) {
  const server = createServer(handler);
  server.listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  const address = server.address();
  assert.equal(typeof address, "object");
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}

function answering(status, location) {
  return (request, response) => {
    assert.equal(request.url, PROBE);
    response.writeHead(status, location ? { location } : {});
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
  });
});
