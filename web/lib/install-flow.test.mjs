import { AsyncLocalStorage } from "node:async_hooks";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { register } from "node:module";
import test from "node:test";

import {
  InstallFlowConfigurationError,
  sealInstallFlow,
  verifyInstallFlow,
} from "./install-flow.ts";
// Imported, not retyped: the 403 arm renders this exact URL, so a rename that
// left the route compiling against a stale constant fails HERE.
import { GITHUB_REPO_URL } from "./links.ts";

globalThis.AsyncLocalStorage ??= AsyncLocalStorage;
register("./node-next-loader.mjs", import.meta.url);

const FIXTURE_SECRET = "install-flow-fixture-secret-32-bytes";
const FIXTURE_NONCE = Uint8Array.from({ length: 32 }, (_, index) => index);
const FIXTURE_TOKEN =
  "eyJ2IjoxLCJub25jZSI6IkFBRUNBd1FGQmdjSUNRb0xEQTBPRHhBUkVoTVVGUllYR0JrYUd4d2RIaDgi" +
  "LCJleHAiOjIwMDAwMDAwMDAsInN1YiI6InVzZXJfMDFBQkMiLCJpbnN0YWxsYXRpb25faWQiOjEwMDEs" +
  "InBrY2VfcmV0cmllZCI6ZmFsc2V9.80d_xUkijhR281JyJ8ATMcYGRgotlbWqw5t23Tiu_-g";

function signed(payload) {
  const segment = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature = createHmac("sha256", FIXTURE_SECRET).update(segment).digest("base64url");
  return `${segment}.${signature}`;
}

function tamperToken(token) {
  const replacement = token.at(-1) === "A" ? "B" : "A";
  const tampered = token.slice(0, -1) + replacement;
  assert.notEqual(tampered, token);
  return tampered;
}

test("tamper helper changes tokens ending in either candidate character", () => {
  assert.equal(tamperToken("tokenA"), "tokenB");
  assert.equal(tamperToken("tokenB"), "tokenA");
});

test("TypeScript and Python share one exact install-flow fixture", () => {
  const token = sealInstallFlow({
    nonce: FIXTURE_NONCE,
    expiresAt: 2_000_000_000,
    subject: "user_01ABC",
    installationId: 1001,
    pkceRetried: false,
    secret: FIXTURE_SECRET,
  });
  assert.equal(token, FIXTURE_TOKEN);

  const flow = verifyInstallFlow(FIXTURE_TOKEN, {
    now: 1_999_999_999,
    expectedSubject: "user_01ABC",
    expectedInstallationId: 1001,
    secret: FIXTURE_SECRET,
  });
  assert.deepEqual(flow.nonce, FIXTURE_NONCE);
  assert.equal(flow.subject, "user_01ABC");
  assert.equal(flow.installationId, 1001);
  assert.equal(flow.expiresAt, 2_000_000_000);
  assert.equal(flow.pkceRetried, false);
});

test("a pre-auth flow may carry null subject until WorkOS binds it", () => {
  const token = sealInstallFlow({
    nonce: FIXTURE_NONCE,
    expiresAt: 2_000_000_000,
    subject: null,
    installationId: 1001,
    pkceRetried: false,
    secret: FIXTURE_SECRET,
  });
  const flow = verifyInstallFlow(token, {
    now: 1_999_999_999,
    secret: FIXTURE_SECRET,
  });
  assert.equal(flow.subject, null);
  assert.throws(
    () =>
      verifyInstallFlow(token, {
        now: 1_999_999_999,
        expectedSubject: "user_01ABC",
        secret: FIXTURE_SECRET,
      }),
    /^Error: invalid install flow$/,
  );
});

test("PKCE retry guard is an exact signed boolean", () => {
  const token = sealInstallFlow({
    nonce: FIXTURE_NONCE,
    expiresAt: 2_000_000_000,
    subject: "user_01ABC",
    installationId: 1001,
    pkceRetried: true,
    secret: FIXTURE_SECRET,
  });
  assert.equal(
    verifyInstallFlow(token, { now: 1_999_999_999, secret: FIXTURE_SECRET }).pkceRetried,
    true,
  );

  const base = {
    v: 1,
    nonce: Buffer.from(FIXTURE_NONCE).toString("base64url"),
    exp: 2_000_000_000,
    sub: "user_01ABC",
    installation_id: 1001,
  };
  for (const payload of [base, { ...base, pkce_retried: 1 }]) {
    assert.throws(
      () => verifyInstallFlow(signed(payload), { now: 1_999_999_999, secret: FIXTURE_SECRET }),
      /^Error: invalid install flow$/,
    );
  }
});

test("verification refuses tamper, expiry, identity swaps, and malformed nonces", () => {
  const cases = [
    [tamperToken(FIXTURE_TOKEN), 1_999_999_999, "user_01ABC", 1001],
    [FIXTURE_TOKEN, 2_000_000_000, "user_01ABC", 1001],
    [FIXTURE_TOKEN, 1_999_999_999, "user_attacker", 1001],
    [FIXTURE_TOKEN, 1_999_999_999, "user_01ABC", 1002],
    [
      signed({
        v: 2,
        nonce: Buffer.from(FIXTURE_NONCE).toString("base64url"),
        exp: 2_000_000_000,
        sub: "user_01ABC",
        installation_id: 1001,
        pkce_retried: false,
      }),
      1_999_999_999,
      "user_01ABC",
      1001,
    ],
    [
      signed({
        v: 1,
        nonce: "dG9vLXNob3J0",
        exp: 2_000_000_000,
        sub: "user_01ABC",
        installation_id: 1001,
        pkce_retried: false,
      }),
      1_999_999_999,
      "user_01ABC",
      1001,
    ],
  ];

  for (const [token, now, expectedSubject, expectedInstallationId] of cases) {
    assert.throws(
      () =>
        verifyInstallFlow(token, {
          now,
          expectedSubject,
          expectedInstallationId,
          secret: FIXTURE_SECRET,
        }),
      /^Error: invalid install flow$/,
    );
  }
});

test("missing or short secrets are named configuration faults without sensitive material", () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  delete process.env.DOUG_INSTALL_FLOW_SECRET;
  const secret = "secret-that-must-not-appear";
  const rawNonce = "raw-nonce-that-must-not-appear";
  const badToken = `${FIXTURE_TOKEN}.${rawNonce}.${secret}`;
  try {
    for (const configuredSecret of [undefined, "short-secret"]) {
      assert.throws(
        () => verifyInstallFlow(badToken, { secret: configuredSecret }),
        (error) => {
          assert.equal(error instanceof InstallFlowConfigurationError, true);
          assert.equal(error.message, "install flow not configured");
          assert.equal(error.message.includes(FIXTURE_TOKEN), false);
          assert.equal(error.message.includes(rawNonce), false);
          assert.equal(error.message.includes(secret), false);
          return true;
        },
      );
    }

    const setupSecret = "a".repeat(64);
    const setupToken = sealInstallFlow({
      nonce: FIXTURE_NONCE,
      expiresAt: 2_000_000_000,
      subject: "user_01ABC",
      installationId: 1001,
      pkceRetried: false,
      secret: setupSecret,
    });
    assert.equal(
      verifyInstallFlow(setupToken, { now: 1_999_999_999, secret: setupSecret }).installationId,
      1001,
    );
  } finally {
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
  }
});

const ROUTE_SECRET = "install-flow-route-test-secret-32-bytes";

function routeToken({
  subject = "user_01ABC",
  installationId = 1001,
  nonce = Uint8Array.from({ length: 32 }, () => 7),
  expiresAt = Math.floor(Date.now() / 1000) + 1800,
  pkceRetried = false,
} = {}) {
  return sealInstallFlow({
    nonce,
    expiresAt,
    subject,
    installationId,
    pkceRetried,
    secret: ROUTE_SECRET,
  });
}

function cookieValue(response) {
  const match = response.headers.get("set-cookie")?.match(/doug_install_flow=([^;]+)/);
  assert.ok(match, "response did not set doug_install_flow");
  return match[1];
}

async function nextRequest(url, token) {
  const { NextRequest } = await import("next/server");
  return new NextRequest(url, token ? { headers: { cookie: `doug_install_flow=${token}` } } : {});
}

test("install start explicitly requires WorkOS and creates the human-TTL HttpOnly flow", async () => {
  const old = {
    secret: process.env.DOUG_INSTALL_FLOW_SECRET,
    slug: process.env.DOUG_GITHUB_APP_SLUG,
    nodeEnv: process.env.NODE_ENV,
  };
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  process.env.DOUG_GITHUB_APP_SLUG = "dougs-review";
  process.env.NODE_ENV = "production";
  globalThis.__workosAuth = { user: { id: "user_01ABC" }, accessToken: "workos-jwt" };
  globalThis.__workosWithAuthOptions = [];
  try {
    const { GET } = await import("../app/install/start/route.ts");
    const response = await GET();

    assert.equal(response.status, 307);
    assert.equal(response.headers.get("location"), "https://github.com/apps/dougs-review/installations/new");
    assert.equal(response.headers.get("location").includes("state="), false);
    assert.deepEqual(globalThis.__workosWithAuthOptions, [{ ensureSignedIn: true }]);
    const setCookie = response.headers.get("set-cookie");
    assert.match(setCookie, /doug_install_flow=/);
    assert.match(setCookie, /HttpOnly/i);
    assert.match(setCookie, /SameSite=lax/i);
    assert.match(setCookie, /Path=\//i);
    assert.doesNotMatch(setCookie, /Path=\/install/i);
    assert.match(setCookie, /Max-Age=1800/i);
    assert.match(setCookie, /Secure/i);
    const flow = verifyInstallFlow(cookieValue(response), { secret: ROUTE_SECRET });
    assert.equal(flow.subject, "user_01ABC");
    assert.equal(flow.installationId, null);
    assert.equal(flow.pkceRetried, false);
  } finally {
    if (old.secret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = old.secret;
    if (old.slug === undefined) delete process.env.DOUG_GITHUB_APP_SLUG;
    else process.env.DOUG_GITHUB_APP_SLUG = old.slug;
    if (old.nodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = old.nodeEnv;
  }
});

test("GitHub-first callback stores installation state, signs in, and resumes without query state", async () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  const oldApiUrl = process.env.DOUG_API_URL;
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  process.env.DOUG_API_URL = "https://api.doug.test";
  globalThis.__workosAuth = { user: null };
  globalThis.__workosSignInCalls = [];
  globalThis.__workosSignInUrl = "https://auth.workos.test/authorize";
  const requests = [];
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    return new Response(null, { status: 204 });
  };
  try {
    const { GET } = await import("../app/install/callback/route.ts");
    const cold = await GET(await nextRequest("https://doug.example/install/callback?installation_id=1001"));
    assert.equal(cold.status, 307);
    assert.equal(cold.headers.get("location"), "https://auth.workos.test/authorize");
    assert.deepEqual(globalThis.__workosSignInCalls, [{ returnTo: "/install/callback" }]);
    const coldCookie = cold.headers.get("set-cookie");
    assert.match(coldCookie, /HttpOnly/i);
    assert.match(coldCookie, /SameSite=lax/i);
    assert.match(coldCookie, /Path=\//i);
    assert.doesNotMatch(coldCookie, /Path=\/install/i);
    assert.match(coldCookie, /Max-Age=1800/i);
    const pendingToken = cookieValue(cold);
    const pending = verifyInstallFlow(pendingToken, { secret: ROUTE_SECRET });
    assert.equal(pending.subject, null);
    assert.equal(pending.installationId, 1001);
    assert.equal(pending.pkceRetried, false);
    assert.deepEqual(requests, []);

    globalThis.__workosAuth = {
      user: { id: "user_01ABC" },
      accessToken: "workos-session-jwt",
    };
    const resumed = await GET(
      await nextRequest("https://doug.example/install/callback", pendingToken),
    );
    assert.equal(resumed.status, 307);
    assert.equal(resumed.headers.get("location"), "https://doug.example/dashboard");
    assert.equal(requests.length, 1);
    const [request] = requests;
    assert.equal(request.url, "https://api.doug.test/v1/installations/bind/complete");
    assert.deepEqual(request.options.headers, {
      Authorization: "Bearer workos-session-jwt",
      "Content-Type": "application/json",
    });
    const body = JSON.parse(request.options.body);
    assert.deepEqual(Object.keys(body).sort(), ["flow_token", "installation_id"]);
    assert.equal(body.installation_id, 1001);
    const completed = verifyInstallFlow(body.flow_token, {
      expectedSubject: "user_01ABC",
      expectedInstallationId: 1001,
      secret: ROUTE_SECRET,
    });
    assert.deepEqual(completed.nonce, pending.nonce);
    assert.equal(request.url.includes(body.flow_token), false);
    assert.equal(resumed.headers.get("location").includes(body.flow_token), false);
    assert.equal((await resumed.text()).includes(body.flow_token), false);
    assert.match(resumed.headers.get("set-cookie"), /doug_install_flow=;/);
  } finally {
    globalThis.fetch = oldFetch;
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
    if (oldApiUrl === undefined) delete process.env.DOUG_API_URL;
    else process.env.DOUG_API_URL = oldApiUrl;
  }
});

test("callback refuses changed subject or installation without contacting the API", async () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  const oldFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (...args) => {
    requests.push(args);
    return new Response(null, { status: 204 });
  };
  try {
    const { GET } = await import("../app/install/callback/route.ts");
    globalThis.__workosAuth = {
      user: { id: "user_attacker" },
      accessToken: "workos-session-jwt",
    };
    const subjectSwap = await GET(
      await nextRequest("https://doug.example/install/callback", routeToken()),
    );
    assert.equal(subjectSwap.status, 400);

    globalThis.__workosAuth = {
      user: { id: "user_01ABC" },
      accessToken: "workos-session-jwt",
    };
    const installationSwap = await GET(
      await nextRequest(
        "https://doug.example/install/callback?installation_id=1002",
        routeToken(),
      ),
    );
    assert.equal(installationSwap.status, 400);
    assert.deepEqual(requests, []);
  } finally {
    globalThis.fetch = oldFetch;
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
  }
});

test("request waits for an admin and update re-consents without ever binding", async () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new Error("setup_action reached bind");
  };
  globalThis.__workosSignInCalls = [];
  globalThis.__workosSignInUrl = "https://auth.workos.test/consent";
  try {
    const { GET } = await import("../app/install/callback/route.ts");
    const request = await GET(
      await nextRequest("https://doug.example/install/callback?setup_action=request"),
    );
    assert.equal(request.status, 200);
    assert.match(await request.text(), /waiting for your organization admin/i);
    assert.match(request.headers.get("set-cookie"), /Max-Age=0/i);

    const update = await GET(
      await nextRequest("https://doug.example/install/callback?setup_action=update"),
    );
    assert.equal(update.status, 307);
    assert.equal(update.headers.get("location"), "https://auth.workos.test/consent");
    assert.deepEqual(globalThis.__workosSignInCalls, [
      { prompt: "consent", returnTo: "/dashboard" },
    ]);
    assert.match(update.headers.get("set-cookie"), /Max-Age=0/i);
  } finally {
    globalThis.fetch = oldFetch;
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
  }
});

test("the refused-authority 403 offers no link that returns to the same 403", async () => {
  // THE REGRESSION THIS EXISTS TO CATCH (#176). This arm shipped with exactly
  // one action — /install/callback?reauth=github — and that action provably
  // changed nothing: WorkOS honours `prompt=consent` itself and never forwards
  // it to GitHub, so the reader came back with the same session, the same
  // GitHub identity, the same 404 from the API, and this same page offering the
  // same link. Measured in production on 2026-08-21 under #167.
  //
  // The old test hid the loop by stubbing the SECOND bind call to 204, which
  // manufactured a success the deployed path could not produce. So this test
  // holds the API at 404 for every call — the only honest fixture, because
  // api._prove_installer's answer does not move when a session is refreshed —
  // and then FOLLOWS the links the page actually offers.
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  const oldFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    return new Response(null, { status: 404 });
  };
  globalThis.__workosAuth = {
    user: { id: "user_01ABC" },
    accessToken: "workos-session-jwt",
  };
  globalThis.__workosSignInCalls = [];
  globalThis.__workosSignInUrl = "https://auth.workos.test/github-consent";
  try {
    const { GET } = await import("../app/install/callback/route.ts");
    const token = routeToken();
    const response = await GET(
      await nextRequest("https://doug.example/install/callback", token),
    );
    assert.equal(response.status, 403);
    const copy = await response.text();

    // The flow cookie SURVIVES, and that is the recovery path: a reader who
    // signs out and signs back in as the installing account still holds the
    // installation id, so the bind can complete without a second GitHub round.
    assert.equal(response.headers.get("set-cookie"), null);

    // The page still says the account is not lost, which is the one thing a 403
    // must not leave a reader guessing about.
    assert.match(copy, /Doug account remains available/i);
    // It names the remedy that can change the answer, and says why signing in
    // again cannot. Without this pin the copy can quietly revert to a reconnect.
    assert.match(copy, /sign out of Doug/i);
    assert.match(copy, /changes nothing/i);
    // THE GOAL PRECEDES THE INSTRUCTION, and the case the instruction cannot
    // help is named by something the reader can check rather than by a claim
    // about who they are. The API returns one 404 for three causes, so an
    // unconditional "you are signed in as the wrong account" is wrong twice.
    const remedy = copy.indexOf("To connect this repository");
    const instruction = copy.indexOf("sign out of Doug");
    assert.ok(remedy >= 0 && remedy < instruction, "the 403 instructs before it states the goal");
    assert.match(copy, /If you do that and this page comes back/i);
    // The operator escape hatch is a real, reachable destination.
    assert.ok(
      copy.includes(`href="${GITHUB_REPO_URL}/issues"`),
      "the 403 lost its operator escape hatch",
    );

    // Every link the page offers, followed. A link this route serves itself
    // must not answer 403, or the reader is back where they started.
    const hrefs = [...copy.matchAll(/href="([^"]+)"/g)].map((match) => match[1]);
    assert.ok(hrefs.length > 0, "the 403 offers the reader no way onward at all");
    let selfLinks = 0;
    for (const href of hrefs) {
      const target = new URL(href, "https://doug.example");
      if (target.origin !== "https://doug.example") continue;
      if (target.pathname !== "/install/callback") continue;
      selfLinks += 1;
      const followed = await GET(await nextRequest(target.toString(), token));
      assert.notEqual(
        followed.status,
        403,
        `the 403 links to ${href}, whose handler returns the same 403`,
      );
    }
    // Belt and braces: this route has no arm that can escape its own 404, so
    // any self-link is a loop whether or not the walk above happens to catch
    // it. The walk stays because it survives a rewrite of the copy.
    assert.equal(selfLinks, 0, "the 403 links back into /install/callback");

    // No WorkOS round trip is started from this page, by the link or otherwise.
    assert.deepEqual(globalThis.__workosSignInCalls, []);
    assert.equal(requests.length, 1, "rendering the 403 called bind more than once");
  } finally {
    globalThis.fetch = oldFetch;
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
  }
});

test("a stale ?reauth=github bookmark retries the bind instead of re-signing in", async () => {
  // The arm that served the dead link is gone, so the parameter is now just an
  // unknown query on the normal path: the flow cookie still carries the
  // installation id, so the request retries the bind and answers with whatever
  // the API says. What it must never do again is spend a WorkOS sign-in to
  // arrive back at the same answer.
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  const oldFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    return new Response(null, { status: 204 });
  };
  globalThis.__workosAuth = {
    user: { id: "user_01ABC" },
    accessToken: "workos-session-jwt",
  };
  globalThis.__workosSignInCalls = [];
  globalThis.__workosSignInUrl = "https://auth.workos.test/github-consent";
  try {
    const { GET } = await import("../app/install/callback/route.ts");
    const response = await GET(
      await nextRequest(
        "https://doug.example/install/callback?reauth=github",
        routeToken(),
      ),
    );
    assert.equal(response.status, 307);
    assert.equal(response.headers.get("location"), "https://doug.example/dashboard");
    assert.deepEqual(globalThis.__workosSignInCalls, []);
    assert.equal(requests.length, 1);
    const sent = verifyInstallFlow(JSON.parse(requests[0].options.body).flow_token, {
      expectedSubject: "user_01ABC",
      expectedInstallationId: 1001,
      secret: ROUTE_SECRET,
    });
    assert.equal(sent.installationId, 1001);
  } finally {
    globalThis.fetch = oldFetch;
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
  }
});

test("temporary API failure preserves the flow for a safe retry", async () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, { status: 503 });
  globalThis.__workosAuth = {
    user: { id: "user_01ABC" },
    accessToken: "workos-session-jwt",
  };
  try {
    const { GET } = await import("../app/install/callback/route.ts");
    const response = await GET(
      await nextRequest("https://doug.example/install/callback", routeToken()),
    );
    assert.equal(response.status, 503);
    assert.match(await response.text(), /temporarily unavailable/i);
    assert.equal(response.headers.get("set-cookie"), null);
  } finally {
    globalThis.fetch = oldFetch;
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
  }
});

test("an expired AuthKit PKCE callback gets one signed retry with only its remaining lifetime", async () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  const realNow = Date.now;
  const now = 1_900_000_000;
  Date.now = () => now * 1000;
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  globalThis.__workosSignInCalls = [];
  globalThis.__workosSignInUrl = "https://auth.workos.test/renewed-pkce";
  const { CallbackError } = await import("@workos-inc/authkit-nextjs");
  globalThis.__workosCallbackError = new CallbackError(
    "marker-that-must-not-escape",
    "missing_pkce_cookie",
  );
  try {
    const { GET } = await import("../app/auth/callback/route.ts?install-flow-pkce-recovery");
    const token = routeToken({ expiresAt: now + 127 });
    const original = verifyInstallFlow(token, { now, secret: ROUTE_SECRET });
    const first = await GET(
      await nextRequest(
        "https://doug.example/auth/callback?code=code-marker&state=state-marker",
        token,
      ),
    );

    assert.equal(first.status, 307);
    assert.equal(first.headers.get("location"), "https://auth.workos.test/renewed-pkce");
    assert.deepEqual(globalThis.__workosSignInCalls, [{ returnTo: "/install/callback" }]);
    assert.equal(first.headers.get("location").includes(token), false);
    assert.equal((await first.text()).includes("marker-that-must-not-escape"), false);
    const retryCookie = first.headers.get("set-cookie");
    assert.match(retryCookie, /doug_install_flow=/i);
    assert.match(retryCookie, /HttpOnly/i);
    assert.match(retryCookie, /SameSite=lax/i);
    assert.match(retryCookie, /Path=\//i);
    assert.match(retryCookie, /Max-Age=127/i);
    const retryToken = cookieValue(first);
    const retried = verifyInstallFlow(retryToken, { now, secret: ROUTE_SECRET });
    assert.equal(retried.pkceRetried, true);
    assert.equal(retried.expiresAt, original.expiresAt);
    assert.equal(retried.subject, original.subject);
    assert.equal(retried.installationId, original.installationId);
    assert.deepEqual(retried.nonce, original.nonce);

    const second = await GET(
      await nextRequest(
        "https://doug.example/auth/callback?code=second-code&state=second-state",
        retryToken,
      ),
    );
    assert.equal(second.status, 400);
    assert.equal(second.headers.get("location"), null);
    assert.equal(await second.text(), "Authentication could not be completed.");
    assert.deepEqual(globalThis.__workosSignInCalls, [{ returnTo: "/install/callback" }]);
    assert.equal(
      second.headers.get("set-cookie")?.includes("doug_install_flow") ?? false,
      false,
    );
  } finally {
    delete globalThis.__workosCallbackError;
    Date.now = realNow;
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
  }
});

test("PKCE recovery refuses stale, malformed, unrelated, and lookalike callback failures", async () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  const { CallbackError } = await import("@workos-inc/authkit-nextjs");
  const { GET } = await import("../app/auth/callback/route.ts?install-flow-pkce-negative");
  const marker = "callback-secret-marker";
  const cases = [
    [new CallbackError(marker, "missing_pkce_cookie"), undefined],
    [new CallbackError(marker, "missing_pkce_cookie"), `${marker}.not-a-flow`],
    [
      new CallbackError(marker, "missing_pkce_cookie"),
      routeToken({ expiresAt: Math.floor(Date.now() / 1000) - 1 }),
    ],
    [new CallbackError(marker, "missing_pkce_cookie"), routeToken({ installationId: null })],
    [new CallbackError(marker, "missing_pkce_cookie"), routeToken({ pkceRetried: true })],
    [new CallbackError(marker, "oauth_state_mismatch"), routeToken()],
    [Object.assign(new Error(marker), { code: "missing_pkce_cookie" }), routeToken()],
  ];
  try {
    for (const [error, token] of cases) {
      globalThis.__workosSignInCalls = [];
      globalThis.__workosCallbackError = error;
      const response = await GET(
        await nextRequest(
          `https://doug.example/auth/callback?code=${marker}&state=${marker}`,
          token,
        ),
      );
      assert.equal(response.status, 400);
      assert.equal(await response.text(), "Authentication could not be completed.");
      assert.deepEqual(globalThis.__workosSignInCalls, []);
      assert.equal(response.headers.get("location"), null);
      assert.equal(
        response.headers.get("set-cookie")?.includes("doug_install_flow") ?? false,
        false,
      );
    }
  } finally {
    delete globalThis.__workosCallbackError;
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
  }
});

test("install routes report a configuration fault without clearing a valid browser flow", async () => {
  const old = {
    secret: process.env.DOUG_INSTALL_FLOW_SECRET,
    slug: process.env.DOUG_GITHUB_APP_SLUG,
  };
  const token = routeToken();
  process.env.DOUG_INSTALL_FLOW_SECRET = "short-secret";
  process.env.DOUG_GITHUB_APP_SLUG = "dougs-review";
  globalThis.__workosAuth = { user: { id: "user_01ABC" }, accessToken: "workos-jwt" };
  globalThis.__workosWithAuthOptions = [];
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new Error("configuration fault reached the API");
  };
  try {
    const start = await import("../app/install/start/route.ts");
    const callback = await import("../app/install/callback/route.ts");
    const responses = [
      await start.GET(),
      await callback.GET(
        await nextRequest("https://doug.example/install/callback", token),
      ),
    ];
    for (const response of responses) {
      assert.equal(response.status, 503);
      assert.equal(
        await response.text(),
        "Repository setup is temporarily unavailable. Please retry.",
      );
      assert.equal(response.headers.get("set-cookie"), null);
    }
    assert.deepEqual(globalThis.__workosWithAuthOptions, []);
  } finally {
    globalThis.fetch = oldFetch;
    if (old.secret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = old.secret;
    if (old.slug === undefined) delete process.env.DOUG_GITHUB_APP_SLUG;
    else process.env.DOUG_GITHUB_APP_SLUG = old.slug;
  }
});

test("PKCE recovery reports configuration unavailability without consuming the browser flow", async () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  const token = routeToken();
  process.env.DOUG_INSTALL_FLOW_SECRET = "short-secret";
  globalThis.__workosSignInCalls = [];
  const { CallbackError } = await import("@workos-inc/authkit-nextjs");
  globalThis.__workosCallbackError = new CallbackError(
    "marker-that-must-not-escape",
    "missing_pkce_cookie",
  );
  try {
    const { GET } = await import("../app/auth/callback/route.ts?install-flow-config-fault");
    const response = await GET(
      await nextRequest("https://doug.example/auth/callback?code=x&state=y", token),
    );
    assert.equal(response.status, 503);
    assert.equal(
      await response.text(),
      "Repository setup is temporarily unavailable. Please retry.",
    );
    assert.deepEqual(globalThis.__workosSignInCalls, []);
    assert.equal(
      response.headers.get("set-cookie")?.includes("doug_install_flow") ?? false,
      false,
    );
  } finally {
    delete globalThis.__workosCallbackError;
    if (oldSecret === undefined) delete process.env.DOUG_INSTALL_FLOW_SECRET;
    else process.env.DOUG_INSTALL_FLOW_SECRET = oldSecret;
  }
});
