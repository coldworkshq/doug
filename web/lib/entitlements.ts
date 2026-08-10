type AuthSuccess = {
  accessToken: string;
  authenticationMethod?: string;
  oauthTokens?: { accessToken: string };
};

const ENTITLEMENT_FETCH_TIMEOUT_MS = 2_000;

/**
 * Derive the callback user's permitted installations while WorkOS still
 * exposes the upstream provider token. The API stores only that derived
 * scope; this request deliberately has no browser-facing caller or storage.
 * Failure leaves the valid WorkOS session signed in and stored scope unchanged:
 * a first-time user remains unscoped, while a returning user's prior scope
 * keeps its original TTL and live-ledger intersection. A later sign-in retries
 * without making authentication depend on the API.
 */
export async function recordProviderEntitlements({
  accessToken,
  authenticationMethod,
  oauthTokens,
}: AuthSuccess): Promise<void> {
  if (!oauthTokens) return;

  const apiUrl = process.env.DOUG_API_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(new URL("/v1/sessions/entitlements", apiUrl), {
      method: "POST",
      signal: AbortSignal.timeout(ENTITLEMENT_FETCH_TIMEOUT_MS),
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: authenticationMethod ?? "unknown",
        token: oauthTokens.accessToken,
      }),
    });

    if (response.status !== 204) {
      console.error(
        `doug: entitlement refresh failed; authentication succeeded; stored scope unchanged (HTTP ${response.status})`,
      );
    }
  } catch (error) {
    const kind = error instanceof Error ? error.name : typeof error;
    console.error(
      `doug: entitlement refresh failed; authentication succeeded; stored scope unchanged (${kind})`,
    );
  }
}
