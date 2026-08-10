type AuthSuccess = {
  accessToken: string;
  authenticationMethod?: string;
  oauthTokens?: { accessToken: string };
};

/**
 * Derive the callback user's permitted installations while WorkOS still
 * exposes the upstream provider token. The API stores only that derived
 * scope; this request deliberately has no browser-facing caller or storage.
 */
export async function recordProviderEntitlements({
  accessToken,
  authenticationMethod,
  oauthTokens,
}: AuthSuccess): Promise<void> {
  if (!oauthTokens) return;

  const apiUrl = process.env.DOUG_API_URL ?? "http://localhost:8000";
  const response = await fetch(new URL("/v1/sessions/entitlements", apiUrl), {
    method: "POST",
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
    throw new Error("entitlement derivation failed");
  }
}
