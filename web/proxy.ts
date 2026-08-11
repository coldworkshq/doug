import {
  authkit,
  handleAuthkitProxy,
} from "@workos-inc/authkit-nextjs";
import { NextRequest, NextResponse } from "next/server";

import {
  configuredWorkOSRedirectUri,
  requestHostMatches,
} from "@/lib/auth-origin";

const UNAVAILABLE = "Authentication is temporarily unavailable.";

export default async function proxy(request: NextRequest): Promise<NextResponse> {
  const redirectUri = configuredWorkOSRedirectUri();
  if (!redirectUri) {
    return new NextResponse(UNAVAILABLE, {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }

  if (!requestHostMatches(request, redirectUri)) {
    const canonical = new URL(
      `${request.nextUrl.pathname}${request.nextUrl.search}`,
      redirectUri.origin,
    );
    return NextResponse.redirect(canonical);
  }

  // Cloud Run terminates TLS before the container. Build the SDK-facing URL
  // from the configured public origin so missing proxy protocol metadata can
  // neither self-redirect forever nor downgrade the PKCE cookie's Secure bit.
  const authRequest = new NextRequest(
    new URL(`${request.nextUrl.pathname}${request.nextUrl.search}`, redirectUri.origin),
    { method: request.method, headers: request.headers },
  );
  const { session, headers, authorizationUrl } = await authkit(authRequest, {
    redirectUri: redirectUri.toString(),
  });
  if (request.nextUrl.pathname.startsWith("/dashboard") && !session.user) {
    if (!authorizationUrl) {
      return new NextResponse(UNAVAILABLE, {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    return handleAuthkitProxy(authRequest, headers, { redirect: authorizationUrl });
  }

  return handleAuthkitProxy(authRequest, headers);
}

// This must remain literal: Next statically analyzes proxy configuration.
export const config = {
  matcher: ["/dashboard/:path*", "/install/start", "/install/callback"],
};
