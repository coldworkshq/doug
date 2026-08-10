import {
  CallbackError,
  getSignInUrl,
  handleAuth,
} from "@workos-inc/authkit-nextjs";
import { type NextRequest, NextResponse } from "next/server";

import { recordProviderEntitlements } from "@/lib/entitlements";
import {
  InstallFlowConfigurationError,
  verifyInstallFlow,
} from "@/lib/install-flow";

// Cloud Run's request hostname is the container, not Doug's public callback
// origin. Bracket access keeps this deployment-time value out of Next's
// client-side NEXT_PUBLIC inlining path.
const redirectUri = process.env["NEXT_PUBLIC_WORKOS_REDIRECT_URI"];
const baseURL = redirectUri ? new URL(redirectUri).origin : "http://localhost:3000";

const FLOW_COOKIE = "doug_install_flow";

function message(body: string, status: number): NextResponse {
  return new NextResponse(body, {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

async function recoverExpiredPkce({
  error,
  request,
}: {
  error?: unknown;
  request: NextRequest;
}): Promise<Response> {
  if (!(error instanceof CallbackError) || error.code !== "missing_pkce_cookie") {
    return message("Authentication could not be completed.", 400);
  }

  try {
    const token = request.cookies.get(FLOW_COOKIE)?.value;
    const flow = token ? verifyInstallFlow(token) : null;
    if (!flow || flow.installationId === null) {
      return message("Authentication could not be completed.", 400);
    }
  } catch (caught) {
    if (caught instanceof InstallFlowConfigurationError) {
      return message("Repository setup is temporarily unavailable. Please retry.", 503);
    }
    return message("Authentication could not be completed.", 400);
  }

  try {
    return NextResponse.redirect(await getSignInUrl({ returnTo: "/install/callback" }));
  } catch {
    return message("Repository setup is temporarily unavailable. Please retry.", 503);
  }
}

export const GET = handleAuth({
  baseURL,
  onSuccess: recordProviderEntitlements,
  onError: recoverExpiredPkce,
});
