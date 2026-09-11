import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { after, before, describe, test } from "node:test";

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

async function waitForServer(url, child, output) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (child.exitCode !== null) {
      throw new Error(`Next server exited before readiness (${child.exitCode})\n${output()}`);
    }
    try {
      const response = await fetch(url, { redirect: "manual" });
      if (response.status === 200) return;
    } catch {
      // Startup races are expected until Next binds the port.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Next server did not become ready\n${output()}`);
}

const SERVER_ENV = {
  NODE_ENV: "production",
  WORKOS_CLIENT_ID: "local-test-client",
  WORKOS_API_KEY: "local-test-api-key",
  WORKOS_COOKIE_PASSWORD: COOKIE_PASSWORD,
  DOUG_API_URL: "http://127.0.0.1:9",
  DOUG_INSTALL_FLOW_SECRET: "local-test-install-flow-secret-32ch",
};

// A further `next start` over the build the top-level `before` made, with its
// own environment on top of SERVER_ENV. The caller stops it. A server that
// exits before readiness is stopped here and surfaces its own output.
async function startServer(env) {
  const port = await availablePort();
  const origin = `http://127.0.0.1:${port}`;
  let output = "";
  const child = spawn(
    process.execPath,
    [NEXT_BIN, "start", "-H", "127.0.0.1", "-p", String(port)],
    {
      cwd: WEB_DIR,
      env: { ...NEXT_ENV, ...SERVER_ENV, ...env },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  child.stdout.on("data", (chunk) => { output += chunk; });
  child.stderr.on("data", (chunk) => { output += chunk; });
  const stop = async () => {
    if (child.exitCode !== null) return;
    child.kill("SIGTERM");
    await once(child, "exit");
  };
  try {
    await waitForServer(`${origin}/`, child, () => output);
  } catch (error) {
    await stop();
    throw error;
  }
  return { origin, stop };
}

// A GET that arrives as if for `host`. Node's fetch drops a caller-supplied
// Host header, and `has: host` in next.config.ts reads exactly that header,
// so these requests go through node:http, which sends it as given. Redirects
// are never followed; `set-cookie` comes back as node:http's array.
function requestAs(host, origin, pathname, headers = {}) {
  const url = new URL(pathname, origin);
  return new Promise((resolve, reject) => {
    const req = httpRequest(
      {
        host: url.hostname,
        port: url.port,
        method: "GET",
        path: `${url.pathname}${url.search}`,
        headers: { accept: "text/html", ...headers, host },
      },
      (res) => {
        res.resume();
        res.once("end", () => resolve({ status: res.statusCode, headers: res.headers }));
      },
    );
    req.once("error", reject);
    req.end();
  });
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
        ...SERVER_ENV,
        NEXT_PUBLIC_WORKOS_REDIRECT_URI: `${callbackOrigin}/auth/callback`,
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  serverProcess.stdout.on("data", (chunk) => { serverOutput += chunk; });
  serverProcess.stderr.on("data", (chunk) => { serverOutput += chunk; });
  await waitForServer(`${origin}/`, serverProcess, () => serverOutput);
}, { timeout: 60_000 });

after(async () => {
  if (!serverProcess || serverProcess.exitCode !== null) return;
  serverProcess.kill("SIGTERM");
  await once(serverProcess, "exit");
});

test("the door is the Coldworks landing, and its Log in is provider-neutral account entry", async () => {
  // ADR-0034: / is public/landing.html through a rewrite; Doug's page is /doug.
  const response = await fetch(`${origin}/`);
  const html = await response.text();

  assert.equal(response.status, 200);
  assert.match(html, /Use AI to/);
  assert.match(html, /href="\/sign-in">Log in</);
  assert.match(html, /href="\/dashboard\/overview"/);
});

test("Doug's own page keeps its account entry, one link in", async () => {
  const response = await fetch(`${origin}/doug`);
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
  const invalid = await startServer({ NEXT_PUBLIC_WORKOS_REDIRECT_URI: "not-an-absolute-url" });
  try {
    const response = await fetch(`${invalid.origin}/sign-in`, { redirect: "manual" });
    assert.equal(response.status, 503);
    assert.equal(await response.text(), "Sign-in is temporarily unavailable.");
    assert.equal(response.headers.get("location"), null);
  } finally {
    await invalid.stop();
  }
});

// ADR-0034 decision 1, the single host. With the redirect URI on the apex:
// sign-in mints PKCE on the apex and nowhere else; `doug.coldworks.dev`
// answers every path with a permanent, path-preserving redirect there, so a
// receipt link already written into a pull request lands on the same receipt;
// and the run.app host keeps serving 200, which is what the deploy's smoke
// test reads before it promotes a revision (`api/deploy/gcp.sh`
// promote_if_healthy, `web/scripts/smoke-auth-entry.sh`). The redirect is
// `redirects()` in next.config.ts keyed on the Host header, the header Cloud
// Run hands the container for a mapped domain; the run.app cases are the
// control that keeps it keyed on that one host and never a catch-all.
describe("single host: the subdomain redirects to the apex", () => {
  const APEX = "coldworks.dev";
  const SUBDOMAIN = "doug.coldworks.dev";
  const RUN_APP_HOST = "doug-web-candidate-uc.a.run.app";
  let apex;

  before(async () => {
    apex = await startServer({ NEXT_PUBLIC_WORKOS_REDIRECT_URI: `https://${APEX}/auth/callback` });
  }, { timeout: 60_000 });

  after(async () => {
    await apex?.stop();
  });

  test("a public page on the subdomain answers 308 to the same path and query on the apex", async () => {
    const response = await requestAs(SUBDOMAIN, apex.origin, "/scoreboard?from=pr");

    assert.equal(response.status, 308);
    assert.equal(response.headers.location, `https://${APEX}/scoreboard?from=pr`);
  });

  test("a receipt link on the subdomain lands on the same receipt on the apex", async () => {
    const response = await requestAs(SUBDOMAIN, apex.origin, "/dashboard/pr/42");

    assert.equal(response.status, 308);
    assert.equal(response.headers.location, `https://${APEX}/dashboard/pr/42`);
  });

  test("the door and sign-in on the subdomain redirect before any PKCE is minted", async () => {
    const door = await requestAs(SUBDOMAIN, apex.origin, "/");
    assert.equal(door.status, 308);
    // Next writes the bare origin for the empty path; it is the same URL.
    assert.equal(new URL(door.headers.location).href, `https://${APEX}/`);

    const signIn = await requestAs(SUBDOMAIN, apex.origin, "/sign-in");
    assert.equal(signIn.status, 308);
    assert.equal(signIn.headers.location, `https://${APEX}/sign-in`);
    assert.equal(signIn.headers["set-cookie"], undefined);
  });

  test("sign-in on the apex mints PKCE with the redirect URI on the apex", async () => {
    const response = await requestAs(APEX, apex.origin, "/sign-in");
    const authorizationUrl = new URL(response.headers.location ?? apex.origin);

    assert.equal(response.status, 307);
    assert.equal(authorizationUrl.origin, "https://api.workos.com");
    assert.equal(authorizationUrl.pathname, "/user_management/authorize");
    assert.equal(authorizationUrl.searchParams.get("redirect_uri"), `https://${APEX}/auth/callback`);
    assert.match((response.headers["set-cookie"] ?? []).join("\n"), /wos-auth-verifier(?:-[^=;]+)?=[^;]+;[^\r\n]*\bSecure\b/);
  });

  test("the run.app host still serves the door, and canonicalizes sign-in with a 307, not the 308", async () => {
    const door = await requestAs(RUN_APP_HOST, apex.origin, "/");
    assert.equal(door.status, 200);

    const signIn = await requestAs(RUN_APP_HOST, apex.origin, "/sign-in");
    assert.equal(signIn.status, 307);
    assert.equal(signIn.headers.location, `https://${APEX}/sign-in`);
    assert.equal(signIn.headers["set-cookie"], undefined);
  });
});
