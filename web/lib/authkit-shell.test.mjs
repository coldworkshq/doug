import { AsyncLocalStorage } from "node:async_hooks";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { register } from "node:module";
import test from "node:test";

globalThis.AsyncLocalStorage ??= AsyncLocalStorage;
register("./node-next-loader.mjs", import.meta.url);

async function withEntitlementServer(run) {
  const requests = [];
  const server = createServer(async (request, response) => {
    let body = "";
    for await (const chunk of request) body += chunk;
    requests.push({
      method: request.method,
      url: request.url,
      headers: request.headers,
      body,
    });
    response.writeHead(204);
    response.end();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  const oldApiUrl = process.env.DOUG_API_URL;
  process.env.DOUG_API_URL = `http://127.0.0.1:${port}`;
  try {
    await run(requests);
  } finally {
    if (oldApiUrl === undefined) delete process.env.DOUG_API_URL;
    else process.env.DOUG_API_URL = oldApiUrl;
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}

test("AuthKit proxy leaves the public homepage and showcase queue outside session handling", async () => {
  const { config } = await import("../proxy.ts");
  const { unstable_doesMiddlewareMatch } = await import("next/experimental/testing/server.js");
  const matches = (url) => unstable_doesMiddlewareMatch({ config, nextConfig: {}, url });

  assert.equal(matches("/"), false);
  assert.equal(matches("/queue"), false);
  assert.equal(matches("/dashboard"), true);
});

test("a successful callback without an upstream provider token leaves the API untouched", async () => {
  const { recordProviderEntitlements } = await import("./entitlements.ts");
  await withEntitlementServer(async (requests) => {
    await recordProviderEntitlements({
      accessToken: "workos-session-token",
      authenticationMethod: "Password",
      oauthTokens: undefined,
    });
    assert.deepEqual(requests, []);
  });
});

test("the callback gives AuthKit Doug's public origin and an entitlement onSuccess hook", async () => {
  const oldRedirectUri = process.env.NEXT_PUBLIC_WORKOS_REDIRECT_URI;
  process.env.NEXT_PUBLIC_WORKOS_REDIRECT_URI = "https://doug.example/auth/callback";
  globalThis.__workosHandleAuthOptions = undefined;
  try {
    await import("../app/auth/callback/route.ts?callback-options-test");
    assert.equal(globalThis.__workosHandleAuthOptions.baseURL, "https://doug.example");
    assert.equal(typeof globalThis.__workosHandleAuthOptions.onSuccess, "function");
  } finally {
    if (oldRedirectUri === undefined) delete process.env.NEXT_PUBLIC_WORKOS_REDIRECT_URI;
    else process.env.NEXT_PUBLIC_WORKOS_REDIRECT_URI = oldRedirectUri;
  }
});

test("callback entitlement derivation sends the provider token only in the server-side JSON body", async () => {
  const { recordProviderEntitlements } = await import("./entitlements.ts");
  await withEntitlementServer(async (requests) => {
    const providerToken = "ghu_provider-token-only-in-request-body";
    await recordProviderEntitlements({
      accessToken: "workos-session-token",
      authenticationMethod: "GitHubOAuth",
      oauthTokens: {
        accessToken: providerToken,
        refreshToken: "unused-refresh-token",
        expiresAt: 0,
        scopes: [],
      },
    });

    assert.equal(requests.length, 1);
    const [request] = requests;
    assert.equal(request.method, "POST");
    assert.equal(request.url, "/v1/sessions/entitlements");
    assert.equal(request.headers.authorization, "Bearer workos-session-token");
    assert.equal(request.headers["content-type"], "application/json");
    assert.equal(request.headers.cookie, undefined);
    assert.equal(request.url.includes(providerToken), false);
    assert.equal(request.headers.authorization.includes(providerToken), false);
    assert.deepEqual(JSON.parse(request.body), {
      provider: "GitHubOAuth",
      token: providerToken,
    });
  });
});

test("sign-out delegates to AuthKit from a server action instead of a browser GET", async () => {
  globalThis.__workosSignOutCalls = 0;
  const { signOutAction } = await import("../app/auth/actions.ts");
  await signOutAction();
  assert.equal(globalThis.__workosSignOutCalls, 1);
});
