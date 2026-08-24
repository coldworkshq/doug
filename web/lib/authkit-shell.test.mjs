import { AsyncLocalStorage } from "node:async_hooks";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { register } from "node:module";
import test from "node:test";

globalThis.AsyncLocalStorage ??= AsyncLocalStorage;
register("./node-next-loader.mjs", import.meta.url);

/** `status` may be a single code or one code PER ATTEMPT — the retry added in
 *  `recordProviderEntitlements` is only worth having if a first answer and a
 *  second can differ, which is exactly the cold-start case it exists for. */
async function withEntitlementServer(run, { status = 204, delayMs = 0 } = {}) {
  const requests = [];
  const codes = Array.isArray(status) ? [...status] : null;
  const server = createServer(async (request, response) => {
    let body = "";
    for await (const chunk of request) body += chunk;
    requests.push({
      method: request.method,
      url: request.url,
      headers: request.headers,
      body,
    });
    const code = codes ? (codes.shift() ?? 500) : status;
    const finish = () => {
      response.writeHead(code);
      response.end();
    };
    if (delayMs > 0) {
      const timer = setTimeout(finish, delayMs);
      response.once("close", () => clearTimeout(timer));
    } else {
      finish();
    }
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

test("AuthKit proxy injects optional callback session state without gating public pages", async () => {
  const { config } = await import("../proxy.ts");
  const { unstable_doesMiddlewareMatch } = await import("next/experimental/testing/server.js");
  const matches = (url) => unstable_doesMiddlewareMatch({ config, nextConfig: {}, url });

  assert.equal(matches("/"), false);
  assert.equal(matches("/queue"), false);
  assert.equal(matches("/scoreboard"), false);
  assert.equal(matches("/dashboard"), true);
  // The settings route too, and not merely because `/dashboard/:path*` happens
  // to cover it. A matcher narrowed to the literal "/dashboard" would leave
  // /dashboard/settings unguarded — an unauthenticated request reaching a page
  // that calls `withAuth`, on the surface that holds the controls. It is also
  // what makes the marketing header's plain "Dashboard" link safe: signed out,
  // the proxy is what hands the request to AuthKit rather than the link being
  // a dead end.
  assert.equal(matches("/dashboard/settings"), true);
  assert.equal(matches("/install/start"), true);
  assert.equal(matches("/install/callback"), true);
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

/** Collect console.warn while `run` executes, and always put it back. */
async function withCapturedWarnings(run) {
  const warnings = [];
  const oldConsoleWarn = console.warn;
  console.warn = (...args) => warnings.push(args.join(" "));
  try {
    await run(warnings);
  } finally {
    console.warn = oldConsoleWarn;
  }
  return warnings;
}

/** Collect console.error while `run` executes, and always put it back. */
async function withCapturedErrors(run) {
  const errors = [];
  const oldConsoleError = console.error;
  console.error = (...args) => errors.push(args.join(" "));
  try {
    await run(errors);
  } finally {
    console.error = oldConsoleError;
  }
  return errors;
}

const CANARY = {
  accessToken: "workos-session-token-canary",
  authenticationMethod: "GitHubOAuth",
  oauthTokens: { accessToken: "provider-token-canary" },
  user: { id: "user_01CANARY" },
};

// Fast limits for the tests that are about SHAPE — how many attempts, what is
// logged, what is bounded. The production defaults are pinned separately, by
// the cold-start test below, which pays real time on purpose.
const QUICK = { budgetMs: 400, backoffMs: 10 };

test("a transient entitlement API failure does not turn a valid sign-in into a callback failure", async () => {
  const { recordProviderEntitlements } = await import("./entitlements.ts");
  await withEntitlementServer(async (requests) => {
    const errors = await withCapturedErrors(async () => {
      // Resolves. It must never reject: `handleAuth` runs onSuccess inside its
      // own try/catch, so a throw here would take a VALID sign-in down with it.
      await recordProviderEntitlements(CANARY, QUICK);
    });
    assert.equal(requests.length, 2, "a failed derivation is retried exactly once");
    assert.equal(errors.length, 1, "the retry is not narrated twice; only the outcome is logged");
    assert.equal(errors[0].includes("workos-session-token-canary"), false);
    assert.equal(errors[0].includes("provider-token-canary"), false);
  }, { status: 503 });
});

test("a cold-started API gets a second chance, and one success is enough", async () => {
  const { recordProviderEntitlements } = await import("./entitlements.ts");
  await withEntitlementServer(async (requests) => {
    const errors = await withCapturedErrors(async () => {
      await recordProviderEntitlements(CANARY, QUICK);
    });
    assert.equal(requests.length, 2);
    // The retry is a real derivation, not a ping: same bearer, same body.
    assert.deepEqual(JSON.parse(requests[1].body), {
      provider: "GitHubOAuth",
      token: "provider-token-canary",
    });
    assert.equal(requests[1].headers.authorization, "Bearer workos-session-token-canary");
    assert.deepEqual(errors, [], "a derivation that succeeded on retry is not an error");
  }, { status: [503, 204] });
});

test("the derivation deadline outlives a scale-to-zero cold start", async () => {
  // THE BUG, in one number. The old budget was 2s. api/deploy/gcp.sh deploys
  // the API with no --min-instances, so it scales to zero and the first request
  // after an idle period waits for a container boot and a Cloud SQL connection.
  // A 2.5s answer is a cold start answering — not a failure — and abandoning it
  // left the user with no derived scope and no way to tell.
  //
  // Deliberately runs against the PRODUCTION defaults (no limits argument), and
  // pays 2.5s of real time to do it: this is the one claim that a fast test
  // with injected limits could not make.
  const { recordProviderEntitlements } = await import("./entitlements.ts");
  await withEntitlementServer(async (requests) => {
    const errors = await withCapturedErrors(async () => {
      await recordProviderEntitlements(CANARY);
    });
    assert.equal(requests.length, 1, "a slow-but-alive API is waited for, not retried past");
    assert.deepEqual(errors, [], "a cold start is not an error");
  }, { delayMs: 2_500 });
});

test("a hung entitlement API cannot hold the sign-in callback until the platform timeout", async () => {
  const { recordProviderEntitlements } = await import("./entitlements.ts");
  await withEntitlementServer(async (requests) => {
    const started = Date.now();
    let settled = false;
    const errors = await withCapturedErrors(async () => {
      await recordProviderEntitlements(CANARY, QUICK);
      settled = true;
    });
    const elapsed = Date.now() - started;
    assert.equal(settled, true, "the callback is released rather than held open");
    // The budget is a TOTAL, not per attempt: a hung API must not be able to
    // charge the person signing in twice for the same silence.
    assert.ok(
      elapsed < QUICK.budgetMs * 2,
      `derivation took ${elapsed}ms, which is not bounded by a ${QUICK.budgetMs}ms budget`,
    );
    assert.ok(requests.length >= 1 && requests.length <= 2);
    assert.equal(errors.length, 1);
  }, { delayMs: 30_000 });
});

test("a derivation Doug gave up on is one structured line naming the user and no token", async () => {
  // Cloud Run parses a single-line JSON object on stderr into a structured
  // entry, so this is what makes a swallowed failure findable in the logs at
  // all — the previous message named neither the user nor the event, which is
  // why this bug was reported from the dashboard rather than seen in logging.
  const { recordProviderEntitlements } = await import("./entitlements.ts");
  await withEntitlementServer(async () => {
    const errors = await withCapturedErrors(async () => {
      await recordProviderEntitlements(CANARY, QUICK);
    });
    assert.equal(errors.length, 1);
    const entry = JSON.parse(errors[0]);
    assert.equal(entry.severity, "ERROR");
    assert.equal(entry.event, "entitlement_derivation_failed");
    assert.equal(entry.workos_user_id, "user_01CANARY");
    assert.equal(entry.attempts, 2);
    assert.equal(typeof entry.message, "string");
    // Property 2 of api/doug/entitlements.py, held on this side of the wire:
    // the credential appears in the request body and nowhere else, least of all
    // in a log line that outlives the request.
    assert.equal(errors[0].includes("provider-token-canary"), false);
    assert.equal(errors[0].includes("workos-session-token-canary"), false);
  }, { status: 503 });
});

test("a failed derivation leaves a short-lived signal the dashboard can render", async () => {
  const { recordProviderEntitlements, SCOPE_UNCONFIRMED_COOKIE } = await import(
    "./entitlements.ts"
  );
  const writes = [];
  await withEntitlementServer(async () => {
    await withCapturedErrors(async () => {
      await recordProviderEntitlements(CANARY, {
        ...QUICK,
        cookieStore: async () => ({ set: (...args) => writes.push(args) }),
      });
    });
  }, { status: 503 });

  assert.equal(writes.length, 1);
  const [name, value, options] = writes[0];
  assert.equal(name, SCOPE_UNCONFIRMED_COOKIE);
  assert.equal(value, "1");
  assert.equal(options.httpOnly, true, "only the server reads this; it is not for scripts");
  assert.equal(options.path, "/");
  assert.equal(options.sameSite, "lax");
  // Short-lived on purpose: a Server Component cannot delete a cookie, so this
  // has to expire on its own rather than outlive the moment it describes.
  assert.ok(options.maxAge > 0 && options.maxAge <= 300);
});

test("a successful derivation leaves no failure signal behind", async () => {
  const { recordProviderEntitlements } = await import("./entitlements.ts");
  const writes = [];
  await withEntitlementServer(async (requests) => {
    await recordProviderEntitlements(CANARY, {
      ...QUICK,
      cookieStore: async () => ({
        set: (...args) => writes.push(args),
        delete: () => {},
      }),
    });
    assert.equal(requests.length, 1);
  });
  assert.deepEqual(writes, [], "nothing failed, so the dashboard is told nothing");
});

test("a success withdraws a stale failure signal instead of letting it expire", async () => {
  // Doug's PR 99 review, reader:stale-state-signal (real): the cookie was set
  // on failure and only ever aged out (120s), so a fail-then-succeed sign-in
  // kept telling the person their repositories could not be confirmed AFTER a
  // derivation had just confirmed them. The callback is a Route Handler — the
  // one place that CAN delete it — so success must withdraw it affirmatively.
  const { recordProviderEntitlements, SCOPE_UNCONFIRMED_COOKIE } = await import(
    "./entitlements.ts"
  );
  const writes = [];
  const deletes = [];
  await withEntitlementServer(async () => {
    await recordProviderEntitlements(CANARY, {
      ...QUICK,
      cookieStore: async () => ({
        set: (...args) => writes.push(args),
        delete: (name) => deletes.push(name),
      }),
    });
  });
  assert.deepEqual(writes, [], "success writes no failure note");
  assert.deepEqual(deletes, [SCOPE_UNCONFIRMED_COOKIE], "success withdraws any stale one");
});

test("neither a hostile cookie store nor a dead API can fail the sign-in", async () => {
  // The design lock: derivation is best-effort and authentication is not.
  const { recordProviderEntitlements } = await import("./entitlements.ts");
  await withEntitlementServer(async () => {
    await withCapturedErrors(async () => {
      await recordProviderEntitlements(CANARY, {
        ...QUICK,
        cookieStore: async () => {
          throw new Error("cookies() was called outside a request scope");
        },
      });
    });
  }, { status: 503 });

  // No server at all: DNS/connection failure on both attempts.
  const oldApiUrl = process.env.DOUG_API_URL;
  process.env.DOUG_API_URL = "http://127.0.0.1:1";
  try {
    await withCapturedErrors(async () => {
      await recordProviderEntitlements(CANARY, QUICK);
    });
  } finally {
    if (oldApiUrl === undefined) delete process.env.DOUG_API_URL;
    else process.env.DOUG_API_URL = oldApiUrl;
  }
});

test("sign-out delegates to AuthKit from a server action instead of a browser GET", async () => {
  globalThis.__workosSignOutCalls = 0;
  const { signOutAction } = await import("../app/auth/actions.ts");
  await signOutAction();
  assert.equal(globalThis.__workosSignOutCalls, 1);
});

test("a sign-in that carried no provider token says so instead of returning in silence", async () => {
  // THE FAILURE THIS MAKES FINDABLE. `derived_at` never moves, the sign-in
  // succeeds, and the person meets the expired-scope screen on every visit —
  // with nothing in the logs, because this was the one return in the file that
  // wrote neither a line nor a cookie. Two causes reach it and no file in this
  // repo can tell them apart: WorkOS not round-tripping the provider, and the
  // WorkOS connection's "Return GitHub OAuth tokens" option being off.
  const { recordProviderEntitlements } = await import("./entitlements.ts?skip-is-audible");
  await withEntitlementServer(async (requests) => {
    const warnings = await withCapturedWarnings(async () => {
      await recordProviderEntitlements({
        accessToken: "workos-session-token-canary",
        authenticationMethod: "GitHubOAuth",
        oauthTokens: undefined,
        user: { id: "user_01CANARY" },
      });
    });

    // Still no derivation attempt — the line is the whole change, and turning
    // a skipped sign-in into an API call would be a different bug.
    assert.deepEqual(requests, []);

    assert.equal(warnings.length, 1);
    const entry = JSON.parse(warnings[0]);
    assert.equal(entry.event, "entitlement_derivation_skipped");
    assert.equal(entry.workos_user_id, "user_01CANARY");
    assert.equal(entry.provider, "GitHubOAuth");

    // WARNING, not ERROR. On a Password sign-in this path is correct and
    // expected; paging on it would train the reader to mute the event that
    // matters. It must also stay distinguishable from the derivation that RAN
    // and failed — that one is ERROR, and #167's retest reads the difference.
    assert.equal(entry.severity, "WARNING");
    assert.notEqual(entry.event, "entitlement_derivation_failed");

    // Property 2 of api/doug/entitlements.py, held on this side of the wire.
    assert.equal(warnings[0].includes("workos-session-token-canary"), false);
  });
});

test("a non-provider sign-in is named as itself, not reported as a GitHub failure", async () => {
  // The rate is the signal, so the line has to carry enough to separate the
  // expected case from the one worth acting on. A Password sign-in reaching
  // here is routine; a GitHubOAuth one is the #167 symptom.
  const { recordProviderEntitlements } = await import("./entitlements.ts?skip-names-provider");
  await withEntitlementServer(async () => {
    const warnings = await withCapturedWarnings(async () => {
      await recordProviderEntitlements({
        accessToken: "workos-session-token",
        authenticationMethod: "Password",
        oauthTokens: undefined,
      });
    });
    const entry = JSON.parse(warnings[0]);
    assert.equal(entry.provider, "Password");
    // Absent user id must not print as "undefined" or crash the line — a log
    // that throws inside a callback would take a valid sign-in down with it.
    assert.equal(entry.workos_user_id, "unknown");
  });
});
