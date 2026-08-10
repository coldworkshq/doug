import {
  CallbackError,
  getSignInUrl,
  handleAuth,
} from "@workos-inc/authkit-nextjs";
import { type NextRequest, NextResponse } from "next/server";

import { recordProviderEntitlements } from "@/lib/entitlements";
import {
  InstallFlowConfigurationError,
  sealInstallFlow,
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

  let retryToken: string;
  let remainingLifetime: number;
  try {
    const token = request.cookies.get(FLOW_COOKIE)?.value;
    const now = Math.floor(Date.now() / 1000);
    const flow = token ? verifyInstallFlow(token, { now }) : null;
    if (!flow || flow.installationId === null || flow.pkceRetried) {
      return message("Authentication could not be completed.", 400);
    }
    remainingLifetime = flow.expiresAt - now;
    retryToken = sealInstallFlow({
      nonce: flow.nonce,
      expiresAt: flow.expiresAt,
      subject: flow.subject,
      installationId: flow.installationId,
      pkceRetried: true,
    });
  } catch (caught) {
    if (caught instanceof InstallFlowConfigurationError) {
      return message("Repository setup is temporarily unavailable. Please retry.", 503);
    }
    return message("Authentication could not be completed.", 400);
  }

  try {
    const response = NextResponse.redirect(
      await getSignInUrl({ returnTo: "/install/callback" }),
    );
    response.cookies.set(FLOW_COOKIE, retryToken, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: remainingLifetime,
      secure: process.env.NODE_ENV === "production",
    });
    return response;
  } catch {
    return message("Repository setup is temporarily unavailable. Please retry.", 503);
  }
}

export const GET = handleAuth({
  baseURL,
  onSuccess: recordProviderEntitlements,
  onError: recoverExpiredPkce,
});
