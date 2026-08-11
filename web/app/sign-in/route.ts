import { getSignInUrl } from "@workos-inc/authkit-nextjs";
import { type NextRequest, NextResponse } from "next/server";

import {
  configuredWorkOSRedirectUri,
  publicRequestOrigin,
} from "@/lib/auth-origin";

const UNAVAILABLE = "Sign-in is temporarily unavailable.";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const redirectUri = configuredWorkOSRedirectUri();
  if (!redirectUri) {
    return new NextResponse(UNAVAILABLE, {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }

  if (publicRequestOrigin(request) !== redirectUri.origin) {
    return NextResponse.redirect(new URL("/sign-in", redirectUri.origin));
  }

  const authorizationUrl = await getSignInUrl({
    redirectUri: redirectUri.toString(),
    returnTo: "/dashboard",
  });
  return NextResponse.redirect(authorizationUrl);
}
