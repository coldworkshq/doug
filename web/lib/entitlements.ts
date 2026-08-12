import { cookies } from "next/headers";

type AuthSuccess = {
  accessToken: string;
  authenticationMethod?: string;
  oauthTokens?: { accessToken: string };
  user?: { id?: string };
};

type CookieWriter = {
  set: (name: string, value: string, options: Record<string, unknown>) => unknown;
};

/** Test seam, same shape and same rule as `store.replace_session_entitlements`'s
 *  `now`: production passes nothing and gets the constants below. Only the
 *  deadline test overrides them, so the path these tests exercise is the path
 *  that runs. */
export type DerivationLimits = {
  budgetMs?: number;
  backoffMs?: number;
  cookieStore?: () => Promise<CookieWriter>;
};

/** A TOTAL budget across both attempts, not a per-attempt one.
 *
 *  It was 2s, and 2s is shorter than a cold start. `api/deploy/gcp.sh` deploys
 *  the API with `--max-instances 2` and no `--min-instances`, so Cloud Run
 *  scales it to zero; the first request after an idle period waits for a
 *  container boot and a Cloud SQL connection before any handler runs. Cloud Run
 *  HOLDS that request rather than refusing it, so the cold start looked exactly
 *  like a hang, the 2s deadline fired, the failure was swallowed, and the person
 *  signed in with no derived scope — which the dashboard then rendered as
 *  "you have never connected anything".
 *
 *  8s is chosen to clear a cold start, not measured against one; the number is
 *  a judgement, the reason is not. It stays a TOTAL because the cost is paid by
 *  someone waiting on a sign-in redirect: a dead API must not be able to charge
 *  them twice for the same silence. */
const ENTITLEMENT_BUDGET_MS = 8_000;

/** One retry, and it is for the fast failures — a 503 while Cloud Run is at its
 *  2-instance ceiling, a connection reset, an instance recycled mid-request.
 *  A first attempt that spends the whole budget leaves nothing to retry with,
 *  which is deliberate: retrying a timeout would double the wait for the case
 *  where waiting is exactly what did not work. */
const ENTITLEMENT_BACKOFF_MS = 400;

/** Set only when derivation has finally failed, so the dashboard can say
 *  "Doug could not confirm your repositories" instead of the first-run welcome,
 *  which would be a claim about this person that Doug cannot support.
 *
 *  Short-lived because a Server Component cannot delete a cookie (Next only
 *  permits writes from Server Functions and Route Handlers), so it has to
 *  expire on its own rather than outlive the sign-in it describes. */
export const SCOPE_UNCONFIRMED_COOKIE = "doug_scope_unconfirmed";
const SCOPE_UNCONFIRMED_MAX_AGE_S = 120;

/** One attempt. Returns null on success, or a SHORT description of the failure
 *  that contains nothing the caller sent — no token, no bearer, no response
 *  body. */
async function attempt(
  { accessToken, authenticationMethod, oauthTokens }: AuthSuccess,
  timeoutMs: number,
): Promise<string | null> {
  const apiUrl = process.env.DOUG_API_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(new URL("/v1/sessions/entitlements", apiUrl), {
      method: "POST",
      signal: AbortSignal.timeout(timeoutMs),
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: authenticationMethod ?? "unknown",
        token: oauthTokens?.accessToken ?? "",
      }),
    });
    return response.status === 204 ? null : `HTTP ${response.status}`;
  } catch (error) {
    return error instanceof Error ? error.name : typeof error;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Leave the dashboard something honest to render. Best-effort by construction:
 *  `cookies()` throws outside a request scope, and a sign-in must not fail
 *  because a hint could not be written. */
async function markScopeUnconfirmed(
  cookieStore: () => Promise<CookieWriter>,
): Promise<void> {
  try {
    const store = await cookieStore();
    store.set(SCOPE_UNCONFIRMED_COOKIE, "1", {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: SCOPE_UNCONFIRMED_MAX_AGE_S,
      secure: process.env.NODE_ENV === "production",
    });
  } catch {
    // Deliberately silent. The structured line above already recorded the
    // failure that matters; this one only affects whether the dashboard can
    // phrase itself well.
  }
}

/**
 * Derive the callback user's permitted installations while WorkOS still
 * exposes the upstream provider token. The API stores only that derived
 * scope; this request deliberately has no browser-facing caller or storage.
 *
 * NEVER REJECTS, AND THAT IS DESIGN-LOCKED. `handleAuth` awaits this inside its
 * own try/catch (authkit-callback-route.ts), so a throw here would turn a valid
 * sign-in into a callback error. Failure leaves the WorkOS session signed in and
 * stored scope unchanged: a first-time user remains unscoped, while a returning
 * user's prior scope keeps its original TTL and live-ledger intersection.
 *
 * WHAT FAILURE NOW COSTS, WHICH IS THE POINT OF THIS FILE. This is the only
 * moment a provider token exists — `authkit-nextjs` hands `oauthTokens` to
 * `onSuccess` and nowhere else, and the session never carries them (verified in
 * node_modules: the refresh path at session.ts:277 destructures them away, and
 * `onSessionRefreshSuccess` cannot carry them). So there is no later request
 * that can quietly fix this, and until the next sign-in the person's scope is
 * whatever it was. A failure here therefore has to be survivable (retry),
 * findable (structured log), and visible (the cookie) — silence was all three
 * of those things going wrong at once.
 */
export async function recordProviderEntitlements(
  data: AuthSuccess,
  limits: DerivationLimits = {},
): Promise<void> {
  if (!data.oauthTokens) return;

  const budgetMs = limits.budgetMs ?? ENTITLEMENT_BUDGET_MS;
  const backoffMs = limits.backoffMs ?? ENTITLEMENT_BACKOFF_MS;
  const cookieStore = limits.cookieStore ?? cookies;
  const started = Date.now();
  const remaining = () => budgetMs - (Date.now() - started);

  const first = await attempt(data, budgetMs);
  if (first === null) return;

  let attempts = 1;
  let last = first;
  const left = remaining() - backoffMs;
  if (left > 0) {
    await sleep(backoffMs);
    attempts = 2;
    const second = await attempt(data, left);
    if (second === null) return;
    last = second;
  }

  console.error(
    JSON.stringify({
      severity: "ERROR",
      event: "entitlement_derivation_failed",
      message:
        "doug: entitlement derivation failed; authentication succeeded and stored scope is unchanged. " +
        "This user's repository scope is not refreshed until they sign in again.",
      workos_user_id: data.user?.id ?? "unknown",
      provider: data.authenticationMethod ?? "unknown",
      attempts,
      first_failure: first,
      last_failure: last,
      budget_ms: budgetMs,
    }),
  );

  await markScopeUnconfirmed(cookieStore);
}
