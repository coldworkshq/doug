import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { after, before, test } from "node:test";

const WEB_DIR = fileURLToPath(new URL("..", import.meta.url));
const NEXT_BIN = path.resolve(WEB_DIR, "../node_modules/next/dist/bin/next");
const COOKIE_PASSWORD = "local-test-cookie-password-32-chars";

let origin;
let callbackOrigin;
let serverProcess;
let serverOutput = "";

async function availablePort() {
  const reservation = createServer();
  reservation.listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const address = reservation.address();
  assert.equal(typeof address, "object");
  const port = address.port;
  await new Promise((resolve, reject) => reservation.close((error) => error ? reject(error) : resolve()));
  return port;
}

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: WEB_DIR,
      env: process.env,
      ...options,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal, stdout, stderr }));
  });
}

async function waitForServer(url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (serverProcess.exitCode !== null) {
      throw new Error(`Next server exited before readiness (${serverProcess.exitCode})\n${serverOutput}`);
    }
    try {
      const response = await fetch(url, { redirect: "manual" });
      if (response.status === 200) return;
    } catch {
      // Startup races are expected until Next binds the port.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Next server did not become ready\n${serverOutput}`);
}

before(async () => {
  const build = await run(process.execPath, [NEXT_BIN, "build"]);
  assert.equal(build.code, 0, build.stdout + build.stderr);

  const port = await availablePort();
  origin = `http://127.0.0.1:${port}`;
  callbackOrigin = `https://127.0.0.1:${port}`;
  serverProcess = spawn(
    process.execPath,
    [NEXT_BIN, "start", "-H", "127.0.0.1", "-p", String(port)],
    {
      cwd: WEB_DIR,
      env: {
        ...process.env,
        NODE_ENV: "production",
        WORKOS_CLIENT_ID: "local-test-client",
        WORKOS_API_KEY: "local-test-api-key",
        WORKOS_COOKIE_PASSWORD: COOKIE_PASSWORD,
        NEXT_PUBLIC_WORKOS_REDIRECT_URI: `${callbackOrigin}/auth/callback`,
        DOUG_API_URL: "http://127.0.0.1:9",
        DOUG_INSTALL_FLOW_SECRET: "local-test-install-flow-secret-32ch",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  serverProcess.stdout.on("data", (chunk) => { serverOutput += chunk; });
  serverProcess.stderr.on("data", (chunk) => { serverOutput += chunk; });
  await waitForServer(`${origin}/`);
}, { timeout: 60_000 });

after(async () => {
  if (!serverProcess || serverProcess.exitCode !== null) return;
  serverProcess.kill("SIGTERM");
  await once(serverProcess, "exit");
});

test("the public landing page exposes provider-neutral account entry", async () => {
  const response = await fetch(`${origin}/`);
  const html = await response.text();

  assert.equal(response.status, 200);
  assert.match(html, /href="\/sign-in"[^>]*>Sign in</);
  assert.match(html, /class="[^"]*whitespace-nowrap[^"]*" href="\/sign-in">Sign in</);
  assert.match(html, /href="\/sign-in"[^>]*>Get started</);
  assert.match(html, /href="\/queue"/);
});

test("an unauthenticated dashboard crosses TLS termination before rendering", async () => {
  const response = await fetch(`${origin}/dashboard`, {
    redirect: "manual",
    headers: { accept: "text/html" },
  });
  const authorizationUrl = new URL(response.headers.get("location") ?? origin);

  assert.equal(response.status, 307);
  assert.equal(authorizationUrl.origin, "https://api.workos.com");
  assert.equal(authorizationUrl.pathname, "/user_management/authorize");
  assert.equal(authorizationUrl.searchParams.get("redirect_uri"), `${callbackOrigin}/auth/callback`);
  assert.match(response.headers.get("set-cookie") ?? "", /wos-auth-verifier(?:-[^=;]+)?=[^;]+;[^\r\n]*\bSecure\b/);
});

test("the canonical sign-in route mints PKCE in a Route Handler", async () => {
  const response = await fetch(`${origin}/sign-in`, { redirect: "manual" });
  const authorizationUrl = new URL(response.headers.get("location") ?? origin);

  assert.equal(response.status, 307);
  assert.equal(authorizationUrl.origin, "https://api.workos.com");
  assert.equal(authorizationUrl.pathname, "/user_management/authorize");
  assert.equal(authorizationUrl.searchParams.get("redirect_uri"), `${callbackOrigin}/auth/callback`);
  assert.match(response.headers.get("set-cookie") ?? "", /wos-auth-verifier(?:-[^=;]+)?=[^;]+;[^\r\n]*\bSecure\b/);
});

test("an alternate Cloud Run host canonicalizes before PKCE is minted", async () => {
  const response = await fetch(`${origin}/sign-in`, {
    redirect: "manual",
    headers: {
      accept: "text/html",
      "x-forwarded-host": "alternate.run.app",
    },
  });

  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), `${callbackOrigin}/sign-in`);
  assert.doesNotMatch(response.headers.get("set-cookie") ?? "", /wos-auth-verifier(?:-[^=;]+)?=/);
});

test("an invalid callback configuration fails closed before WorkOS", async () => {
  const port = await availablePort();
  const invalidOrigin = `http://127.0.0.1:${port}`;
  let invalidOutput = "";
  const invalidProcess = spawn(
    process.execPath,
    [NEXT_BIN, "start", "-H", "127.0.0.1", "-p", String(port)],
    {
      cwd: WEB_DIR,
      env: {
        ...process.env,
        NODE_ENV: "production",
        WORKOS_CLIENT_ID: "local-test-client",
        WORKOS_API_KEY: "local-test-api-key",
        WORKOS_COOKIE_PASSWORD: COOKIE_PASSWORD,
        NEXT_PUBLIC_WORKOS_REDIRECT_URI: "not-an-absolute-url",
        DOUG_API_URL: "http://127.0.0.1:9",
        DOUG_INSTALL_FLOW_SECRET: "local-test-install-flow-secret-32ch",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  invalidProcess.stdout.on("data", (chunk) => { invalidOutput += chunk; });
  invalidProcess.stderr.on("data", (chunk) => { invalidOutput += chunk; });
  try {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (invalidProcess.exitCode !== null) {
        throw new Error(`Invalid-config server exited before readiness\n${invalidOutput}`);
      }
      try {
        const root = await fetch(`${invalidOrigin}/`);
        if (root.status === 200) break;
      } catch {
        // Startup races are expected until Next binds the port.
      }
      if (attempt === 119) throw new Error(`Invalid-config server did not become ready\n${invalidOutput}`);
      await new Promise((resolve) => setTimeout(resolve, 100));
    }

    const response = await fetch(`${invalidOrigin}/sign-in`, { redirect: "manual" });
    assert.equal(response.status, 503);
    assert.equal(await response.text(), "Sign-in is temporarily unavailable.");
    assert.equal(response.headers.get("location"), null);
  } finally {
    if (invalidProcess.exitCode === null) {
      invalidProcess.kill("SIGTERM");
      await once(invalidProcess, "exit");
    }
  }
});
