import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { after, before, test } from "node:test";

const WEB_DIR = fileURLToPath(new URL("..", import.meta.url));
const NEXT_BIN = path.resolve(WEB_DIR, "../node_modules/next/dist/bin/next");
const COOKIE_PASSWORD = "local-test-cookie-password-32-chars";

// This test is the only writer of this dist dir. It must never be `.next`:
// `next build` deletes the whole dist dir the moment it takes the dist lock
// (next/dist/build/index.js:623), whereas the `next start` below takes no lock
// and only reads BUILD_ID about 80ms after it prints "Ready"
// (next/dist/server/lib/router-utils/filesystem.js:183). Sharing `.next` with
// `npm run build`, `next dev`, a Docker build, or a second agent therefore let
// those builds delete BUILD_ID inside this server's startup window, killing it
// with "Could not find a production build in the '.next' directory". Read by
// web/next.config.ts.
const DIST_DIR = ".next-auth-entry-test";

// Both the build and every server below must agree on the dist dir, or the
// server reads a directory the build never wrote.
const NEXT_ENV = { ...process.env, DOUG_WEB_DIST_DIR: DIST_DIR };

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
      env: NEXT_ENV,
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
  // Delete the marker first so the assertion below cannot be satisfied by a
  // leftover from an earlier run — a stale dist dir would otherwise let the
  // guard pass while the build actually landed in the shared `.next`.
  const buildIdPath = path.join(WEB_DIR, DIST_DIR, "BUILD_ID");
  rmSync(buildIdPath, { force: true });

  const build = await run(process.execPath, [NEXT_BIN, "build"]);
  assert.equal(build.code, 0, build.stdout + build.stderr);

  // If web/next.config.ts ever stops honouring DOUG_WEB_DIST_DIR — renamed,
  // dropped, or reverted — the build silently lands back in the shared `.next`
  // and the race this isolation exists to prevent returns as an intermittent
  // failure that looks like an infrastructure blip. Fail loudly and by name
  // instead: the build must land where these servers are about to read from.
  assert.ok(
    existsSync(buildIdPath),
    `build did not land in ${DIST_DIR}: web/next.config.ts must set distDir from DOUG_WEB_DIST_DIR`,
  );

  const port = await availablePort();
  origin = `http://127.0.0.1:${port}`;
  callbackOrigin = `https://127.0.0.1:${port}`;
  serverProcess = spawn(
    process.execPath,
    [NEXT_BIN, "start", "-H", "127.0.0.1", "-p", String(port)],
    {
      cwd: WEB_DIR,
      env: {
        ...NEXT_ENV,
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
        ...NEXT_ENV,
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
