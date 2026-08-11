import {
  authkit,
  handleAuthkitProxy,
} from "@workos-inc/authkit-nextjs";
import { type NextRequest, NextResponse } from "next/server";

import {
  configuredWorkOSRedirectUri,
  publicRequestOrigin,
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

  if (publicRequestOrigin(request) !== redirectUri.origin) {
    const canonical = new URL(
      `${request.nextUrl.pathname}${request.nextUrl.search}`,
      redirectUri.origin,
    );
    return NextResponse.redirect(canonical);
  }

  const { session, headers, authorizationUrl } = await authkit(request, {
    redirectUri: redirectUri.toString(),
  });
  if (request.nextUrl.pathname.startsWith("/dashboard") && !session.user) {
    if (!authorizationUrl) {
      return new NextResponse(UNAVAILABLE, {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    return handleAuthkitProxy(request, headers, { redirect: authorizationUrl });
  }

  return handleAuthkitProxy(request, headers);
}

// This must remain literal: Next statically analyzes proxy configuration.
export const config = {
  matcher: ["/dashboard/:path*", "/install/start", "/install/callback"],
};
