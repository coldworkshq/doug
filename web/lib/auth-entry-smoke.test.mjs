import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";

const WEB_DIR = fileURLToPath(new URL("..", import.meta.url));
const SCRIPT = path.join(WEB_DIR, "scripts/smoke-auth-entry.sh");

function runSmoke(baseUrl) {
  return new Promise((resolve, reject) => {
    const child = spawn("bash", [SCRIPT, baseUrl], { cwd: WEB_DIR });
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

test("the deploy smoke proves root, dashboard protection, and WorkOS entry without printing PKCE state", async () => {
  await withServer((request, response) => {
    const callback = encodeURIComponent(`http://${request.headers.host}/auth/callback`);
    if (request.url === "/") {
      response.writeHead(200);
    } else if (request.url === "/dashboard") {
      response.writeHead(307, {
        location: `https://api.workos.com/user_management/authorize?redirect_uri=${callback}&state=dashboard-must-not-be-logged`,
      });
    } else if (request.url === "/sign-in") {
      response.writeHead(307, {
        location: `https://api.workos.com/user_management/authorize?redirect_uri=${callback}&state=sign-in-must-not-be-logged`,
      });
    } else {
      response.writeHead(404);
    }
    response.end();
  }, async (baseUrl) => {
    const result = await runSmoke(baseUrl);
    assert.equal(result.code, 0, result.stdout + result.stderr);
    assert.doesNotMatch(result.stdout + result.stderr, /must-not-be-logged|state=/);
  });
});

test("the deploy smoke follows one same-app canonicalization hop", async () => {
  await withServer((request, response) => {
    const port = request.headers.host.split(":").at(-1);
    const canonicalBase = `http://localhost:${port}`;
    const onCanonicalHost = request.headers.host.startsWith("localhost:");
    const callback = encodeURIComponent(`${canonicalBase}/auth/callback`);

    if (request.url === "/") {
      response.writeHead(200);
    } else if (!onCanonicalHost && (request.url === "/dashboard" || request.url === "/sign-in")) {
      response.writeHead(307, { location: `${canonicalBase}${request.url}` });
    } else if (onCanonicalHost && (request.url === "/dashboard" || request.url === "/sign-in")) {
      response.writeHead(307, {
        location: `https://api.workos.com/user_management/authorize?redirect_uri=${callback}&state=canonical-state-must-not-be-logged`,
      });
    } else {
      response.writeHead(404);
    }
    response.end();
  }, async (baseUrl) => {
    const result = await runSmoke(baseUrl);
    assert.equal(result.code, 0, result.stdout + result.stderr);
    assert.doesNotMatch(result.stdout + result.stderr, /canonical-state-must-not-be-logged|state=/);
  });
});

test("a WorkOS redirect with the wrong callback cannot pass the deploy smoke", async () => {
  await withServer((request, response) => {
    if (request.url === "/") {
      response.writeHead(200);
    } else if (request.url === "/dashboard" || request.url === "/sign-in") {
      response.writeHead(307, {
        location: "https://api.workos.com/user_management/authorize?redirect_uri=https%3A%2F%2Fwrong.example%2Fauth%2Fcallback&state=must-not-be-logged",
      });
    } else {
      response.writeHead(404);
    }
    response.end();
  }, async (baseUrl) => {
    const result = await runSmoke(baseUrl);
    assert.notEqual(result.code, 0, result.stdout + result.stderr);
    assert.doesNotMatch(result.stdout + result.stderr, /must-not-be-logged|state=|wrong\.example/);
  });
});

test("a root-only 200 cannot pass the auth-entry deployment smoke", async () => {
  await withServer((_request, response) => {
    response.writeHead(200);
    response.end();
  }, async (baseUrl) => {
    const result = await runSmoke(baseUrl);
    assert.notEqual(result.code, 0, result.stdout + result.stderr);
  });
});
