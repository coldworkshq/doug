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

const SERVER_ENV = {
  NODE_ENV: "production",
  WORKOS_CLIENT_ID: "local-test-client",
  WORKOS_API_KEY: "local-test-api-key",
  WORKOS_COOKIE_PASSWORD: COOKIE_PASSWORD,
  DOUG_API_URL: "http://127.0.0.1:9",
  DOUG_INSTALL_FLOW_SECRET: "local-test-install-flow-secret-32ch",
};

// ADR-0034 decision 1: the apex, and the subdomain that redirects to it.
const APEX = "coldworks.dev";
const SUBDOMAIN = "doug.coldworks.dev";
// The alias, redirecting the same way (doug#333).
const WWW = "www.coldworks.dev";
const RUN_APP_HOST = "doug-web-candidate-uc.a.run.app";

// The main server, with the redirect URI on its own loopback origin, and the
// apex server, with the redirect URI on the apex. Both start in the top-level
// `before` so their readiness waits overlap, and both are stoppable from
// `after` from the moment they are spawned, not only once they are ready.
let main;
let apex;
let origin;
let callbackOrigin;

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

// A child killed by a signal has `exitCode === null` and `signalCode` set;
// testing only `exitCode` would wait for an exit that already happened.
function exited(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

async function waitForServer(url, child, output) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (exited(child)) {
      throw new Error(`Next server exited before readiness (${child.exitCode ?? child.signalCode})\n${output()}`);
    }
    try {
      // One attempt never blocks the loop: a server that binds and then
      // hangs is a failed readiness, not a hung test file.
      const response = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(1_000) });
      if (response.status === 200) return;
    } catch {
      // Startup races are expected until Next binds the port.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Next server did not become ready\n${output()}`);
}

// A `next start` over the build the top-level `before` made. `env` is an
// object, or a function of the server's port for values that name its own
// origin. `ready` resolves on the first 200 from `/` and rejects with the
// server's output otherwise; `stop` is safe to call at any time after spawn,
// including when `ready` rejected or never settled, and it escalates to
// SIGKILL if Next ignores SIGTERM.
async function spawnServer(env) {
  const port = await availablePort();
  const origin = `http://127.0.0.1:${port}`;
  const extra = typeof env === "function" ? env(port) : env;
  let output = "";
  const child = spawn(
    process.execPath,
    [NEXT_BIN, "start", "-H", "127.0.0.1", "-p", String(port)],
    {
      cwd: WEB_DIR,
      env: { ...NEXT_ENV, ...SERVER_ENV, ...extra },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  child.stdout.on("data", (chunk) => { output += chunk; });
  child.stderr.on("data", (chunk) => { output += chunk; });
  const stop = async () => {
    if (exited(child)) return;
    const gone = once(child, "exit");
    child.kill("SIGTERM");
    const escalate = setTimeout(() => child.kill("SIGKILL"), 5_000);
    await gone;
    clearTimeout(escalate);
  };
  const ready = waitForServer(`${origin}/`, child, () => output);
  return { origin, port, ready, stop };
}

// A GET that arrives as if for `host`. Node's fetch drops a caller-supplied
// Host header, and `has: host` in next.config.ts reads exactly that header,
// so these requests go through node:http, which sends it as given. Redirects
// are never followed; `set-cookie` comes back as node:http's array.
function requestAs(host, origin, pathname) {
  const url = new URL(pathname, origin);
  return new Promise((resolve, reject) => {
    const req = httpRequest(
      {
        host: url.hostname,
        port: url.port,
        method: "GET",
        path: `${url.pathname}${url.search}`,
        headers: { accept: "text/html", host },
      },
      (res) => {
        res.once("error", reject);
        res.resume();
        res.once("end", () => resolve({ status: res.statusCode, headers: res.headers }));
      },
    );
    req.setTimeout(10_000, () => req.destroy(new Error(`no response within 10s for ${host} ${pathname}`)));
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

  main = await spawnServer((port) => ({
    NEXT_PUBLIC_WORKOS_REDIRECT_URI: `https://127.0.0.1:${port}/auth/callback`,
  }));
  origin = main.origin;
  callbackOrigin = `https://127.0.0.1:${main.port}`;
  apex = await spawnServer({ NEXT_PUBLIC_WORKOS_REDIRECT_URI: `https://${APEX}/auth/callback` });
  await Promise.all([main.ready, apex.ready]);
}, { timeout: 60_000 });

after(async () => {
  await Promise.all([main?.stop(), apex?.stop()]);
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
  const invalid = await spawnServer({ NEXT_PUBLIC_WORKOS_REDIRECT_URI: "not-an-absolute-url" });
  try {
    await invalid.ready;
    const response = await fetch(`${invalid.origin}/sign-in`, { redirect: "manual" });
    assert.equal(response.status, 503);
    assert.equal(await response.text(), "Sign-in is temporarily unavailable.");
    assert.equal(response.headers.get("location"), null);
  } finally {
    await invalid.stop();
  }
});

for (const retiredHost of [SUBDOMAIN, WWW]) {
  test(`a redirect URI on the retired host ${retiredHost} fails closed instead of looping`, async () => {
    // `next.config.ts` answers every path on this host with a 308 to the apex,
    // so a redirect URI here would make that 308 and the proxy's 307 chase
    // each other. `auth-origin.ts` refuses the URI: /sign-in answers 503 on
    // every host, which the deploy's candidate check turns into a refused
    // promotion (api/deploy/gcp.sh), never a live loop.
    const retired = await spawnServer({ NEXT_PUBLIC_WORKOS_REDIRECT_URI: `https://${retiredHost}/auth/callback` });
    try {
      await retired.ready;
      const onApex = await requestAs(APEX, retired.origin, "/sign-in");
      assert.equal(onApex.status, 503);
      assert.equal(onApex.headers.location, undefined);
      assert.equal(onApex.headers["set-cookie"], undefined);

      const onRetired = await requestAs(retiredHost, retired.origin, "/sign-in");
      assert.equal(onRetired.status, 308);
      assert.equal(onRetired.headers.location, `https://${APEX}/sign-in`);
    } finally {
      await retired.stop();
    }
  });
}

// ADR-0034 decision 1, the single host. With the redirect URI on the apex:
// sign-in mints PKCE on the apex and nowhere else; `doug.coldworks.dev`
// answers every path with a permanent, path-preserving redirect there, so a
// receipt link already written into a pull request lands on the same receipt;
// and the run.app host keeps serving 200, which is what the deploy's smoke
// test reads before it promotes a revision. Why the rule is keyed on Host and
// on exactly that host: the comment on `redirects()` in web/next.config.ts.
describe("single host: the subdomain redirects to the apex", () => {
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
    assert.equal(door.headers.location, `https://${APEX}`);

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

  test("a host that differs from the subdomain only where its dots are is not redirected", async () => {
    // `has[].value` is a regex to Next; an unescaped dot would match this.
    const response = await requestAs("dougXcoldworksXdev", apex.origin, "/");
    assert.equal(response.status, 200);
    const alias = await requestAs("wwwXcoldworksXdev", apex.origin, "/");
    assert.equal(alias.status, 200);
  });

  test("the www alias redirects to the apex, and its legacy docs URLs land on the audit docs", async () => {
    // doug#333. The alias answers like the subdomain: 308, path and query
    // preserved, sign-in redirected before any PKCE is minted.
    const page = await requestAs(WWW, apex.origin, "/scoreboard?from=pr");
    assert.equal(page.status, 308);
    assert.equal(page.headers.location, `https://${APEX}/scoreboard?from=pr`);

    const signIn = await requestAs(WWW, apex.origin, "/sign-in");
    assert.equal(signIn.status, 308);
    assert.equal(signIn.headers.location, `https://${APEX}/sign-in`);
    assert.equal(signIn.headers["set-cookie"], undefined);

    // The alias served the registry's landing and the audit CLI's docs, so
    // each of those URLs means an audit docs page, not Doug's own /docs. A
    // path-preserving rule would strand /docs/cli.html on a 404. The www hop
    // is permanent, so it lands on a stable apex URL: an audit page's route,
    // or the audit's home at /docs/audit, which forwards temporarily to its
    // half of the overview (the audit docs joined the one docs site on
    // 2026-09-15). Every chain is followed to its end on the apex: a forward
    // to a missing page is a 404 with extra hops, and a chain that ends
    // anywhere but the replacement lands the reader on the wrong page. The old
    // stylesheet is not in the table: no page links it.
    //
    // The apex's own old audit URLs forward, temporarily and in one hop, to
    // what replaced them.
    for (const [from, to] of [
      ["/docs/audit/index", "/docs#the-audit"],
      ["/docs/audit/index.html", "/docs#the-audit"],
      ["/docs/audit/connect.html", "/docs/audit/connect"],
    ]) {
      const forward = await requestAs(APEX, apex.origin, from);
      assert.equal(forward.status, 307, `${APEX}${from}`);
      const target = new URL(forward.headers.location, `https://${APEX}`);
      assert.equal(`${target.pathname}${target.hash}`, to, `${APEX}${from}`);
    }
    const legacy = [
      ["/", "", "/"],
      ["/landing.html", "/", "/"],
      ["/docs", "/docs/audit", "/docs#the-audit"],
      ["/docs/index", "/docs/audit", "/docs#the-audit"],
      ["/docs/index.html", "/docs/audit", "/docs#the-audit"],
      ["/docs/cli", "/docs/audit/cli", "/docs/audit/cli"],
      ["/docs/cli.html", "/docs/audit/cli", "/docs/audit/cli"],
      ["/docs/quickstart.html", "/docs/audit/quickstart", "/docs/audit/quickstart"],
      ["/docs/connect", "/docs/audit/connect", "/docs/audit/connect"],
      // Only the audit's own legacy names mean the audit. Every other docs
      // path keeps its path: Doug's pages, and the audit's routes themselves,
      // which a rule on every /docs path sent to /docs/audit/audit/cli.
      ["/docs/report", "/docs/report", "/docs/report"],
      ["/docs/audit/cli", "/docs/audit/cli", "/docs/audit/cli"],
    ];
    for (const [from, to, final] of legacy) {
      const response = await requestAs(WWW, apex.origin, from);
      assert.equal(response.status, 308, `${WWW}${from}`);
      assert.equal(response.headers.location, `https://${APEX}${to}`, `${WWW}${from}`);
      let at = new URL(to || "/", `https://${APEX}`);
      for (let hops = 0; ; hops++) {
        const landed = await requestAs(APEX, apex.origin, `${at.pathname}${at.search}`);
        if (landed.status === 200) break;
        assert.equal(landed.status, 307, `${APEX}${at.pathname} must serve, or forward temporarily, for ${WWW}${from}`);
        assert.ok(hops < 2, `${WWW}${from} is still forwarding after three hops`);
        at = new URL(landed.headers.location, at);
      }
      assert.equal(`${at.pathname}${at.hash}`, final, `${WWW}${from} ends on the wrong page`);
    }
  });

  test("the audit's old overview URL lands on a heading the served overview renders", async () => {
    // /docs/audit forwards to /docs#the-audit. A fragment with no element
    // behind it is not an error anywhere: the reader lands at the top of the
    // overview, on Doug's half, and nothing reports it. So this reads the
    // served HTML; lib/docs-nav.test.mjs reads only the page's source.
    const forward = await requestAs(APEX, apex.origin, "/docs/audit");
    assert.equal(forward.status, 307);
    const target = new URL(forward.headers.location, `https://${APEX}`);
    assert.equal(`${target.pathname}${target.hash}`, "/docs#the-audit");
    const html = await (await fetch(new URL(target.pathname, apex.origin))).text();
    assert.match(
      html,
      new RegExp(`<h2[^>]*\\bid="${target.hash.slice(1)}"`),
      "the served overview has no heading for the fragment the redirect names",
    );
  });
});
