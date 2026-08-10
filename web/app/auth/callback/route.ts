import { handleAuth } from "@workos-inc/authkit-nextjs";

import { recordProviderEntitlements } from "@/lib/entitlements";

// Cloud Run's request hostname is the container, not Doug's public callback
// origin. Bracket access keeps this deployment-time value out of Next's
// client-side NEXT_PUBLIC inlining path.
const redirectUri = process.env["NEXT_PUBLIC_WORKOS_REDIRECT_URI"];
const baseURL = redirectUri ? new URL(redirectUri).origin : "http://localhost:3000";

export const GET = handleAuth({
  baseURL,
  onSuccess: recordProviderEntitlements,
});
