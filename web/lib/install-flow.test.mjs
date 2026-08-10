import { AsyncLocalStorage } from "node:async_hooks";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { register } from "node:module";
import test from "node:test";

import { sealInstallFlow, verifyInstallFlow } from "./install-flow.ts";

globalThis.AsyncLocalStorage ??= AsyncLocalStorage;
register("./node-next-loader.mjs", import.meta.url);

const FIXTURE_SECRET = "install-flow-fixture-secret-32-bytes";
const FIXTURE_NONCE = Uint8Array.from({ length: 32 }, (_, index) => index);
const FIXTURE_TOKEN =
  "eyJ2IjoxLCJub25jZSI6IkFBRUNBd1FGQmdjSUNRb0xEQTBPRHhBUkVoTVVGUllYR0JrYUd4d2RIaDgi" +
  "LCJleHAiOjIwMDAwMDAwMDAsInN1YiI6InVzZXJfMDFBQkMiLCJpbnN0YWxsYXRpb25faWQiOjEwMDF9" +
  ".uvB2k7PQLLXOjVmscQyZ4PJo20ay1VsmfR9LZ_p34Sg";

function signed(payload) {
  const segment = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature = createHmac("sha256", FIXTURE_SECRET).update(segment).digest("base64url");
  return `${segment}.${signature}`;
}

test("TypeScript and Python share one exact install-flow fixture", () => {
  const token = sealInstallFlow({
    nonce: FIXTURE_NONCE,
    expiresAt: 2_000_000_000,
    subject: "user_01ABC",
    installationId: 1001,
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
});

test("a pre-auth flow may carry null subject until WorkOS binds it", () => {
  const token = sealInstallFlow({
    nonce: FIXTURE_NONCE,
    expiresAt: 2_000_000_000,
    subject: null,
    installationId: 1001,
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

test("verification refuses tamper, expiry, identity swaps, and malformed nonces", () => {
  const cases = [
    [FIXTURE_TOKEN.slice(0, -1) + "A", 1_999_999_999, "user_01ABC", 1001],
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

test("missing-secret errors never echo token, nonce, or secret material", () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  delete process.env.DOUG_INSTALL_FLOW_SECRET;
  const secret = "secret-that-must-not-appear";
  const rawNonce = "raw-nonce-that-must-not-appear";
  const badToken = `${FIXTURE_TOKEN}.${rawNonce}.${secret}`;
  try {
    assert.throws(
      () => verifyInstallFlow(badToken),
      (error) => {
        assert.equal(error.message, "invalid install flow");
        assert.equal(error.message.includes(FIXTURE_TOKEN), false);
        assert.equal(error.message.includes(rawNonce), false);
        assert.equal(error.message.includes(secret), false);
        return true;
      },
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
} = {}) {
  return sealInstallFlow({
    nonce,
    expiresAt: Math.floor(Date.now() / 1000) + 1800,
    subject,
    installationId,
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
    assert.match(setCookie, /Path=\/install/i);
    assert.match(setCookie, /Max-Age=1800/i);
    assert.match(setCookie, /Secure/i);
    const flow = verifyInstallFlow(cookieValue(response), { secret: ROUTE_SECRET });
    assert.equal(flow.subject, "user_01ABC");
    assert.equal(flow.installationId, null);
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
    assert.match(coldCookie, /Path=\/install/i);
    assert.match(coldCookie, /Max-Age=1800/i);
    const pendingToken = cookieValue(cold);
    const pending = verifyInstallFlow(pendingToken, { secret: ROUTE_SECRET });
    assert.equal(pending.subject, null);
    assert.equal(pending.installationId, 1001);
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
  }
});

test("missing GitHub identity preserves the flow for one explicit consent retry", async () => {
  const oldSecret = process.env.DOUG_INSTALL_FLOW_SECRET;
  process.env.DOUG_INSTALL_FLOW_SECRET = ROUTE_SECRET;
  const oldFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    return new Response(null, { status: requests.length === 1 ? 404 : 204 });
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
    assert.match(copy, /GitHub connection is required only to connect repositories/i);
    assert.match(copy, /Doug account remains available/i);
    assert.match(copy, /href="\/install\/callback\?reauth=github"/i);
    assert.equal(response.headers.get("set-cookie"), null);

    const reauth = await GET(
      await nextRequest(
        "https://doug.example/install/callback?reauth=github",
        token,
      ),
    );
    assert.equal(reauth.status, 307);
    assert.equal(reauth.headers.get("location"), "https://auth.workos.test/github-consent");
    assert.deepEqual(globalThis.__workosSignInCalls, [
      { prompt: "consent", returnTo: "/install/callback" },
    ]);
    assert.equal(requests.length, 1, "explicit reauth must not call bind");

    const resumed = await GET(
      await nextRequest("https://doug.example/install/callback", token),
    );
    assert.equal(resumed.status, 307);
    assert.equal(resumed.headers.get("location"), "https://doug.example/dashboard");
    assert.equal(requests.length, 2);
    const retried = verifyInstallFlow(JSON.parse(requests[1].options.body).flow_token, {
      expectedSubject: "user_01ABC",
      expectedInstallationId: 1001,
      secret: ROUTE_SECRET,
    });
    assert.deepEqual(retried.nonce, verifyInstallFlow(token, { secret: ROUTE_SECRET }).nonce);
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
