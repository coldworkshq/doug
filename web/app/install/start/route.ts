import { randomBytes } from "node:crypto";

import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";

import {
  InstallFlowConfigurationError,
  assertInstallFlowConfigured,
  sealInstallFlow,
} from "@/lib/install-flow";

const FLOW_COOKIE = "doug_install_flow";
const FLOW_MAX_AGE = 1800;

export async function GET(): Promise<NextResponse> {
  try {
    assertInstallFlowConfigured();
  } catch (error) {
    if (error instanceof InstallFlowConfigurationError) {
      return new NextResponse("Repository setup is temporarily unavailable. Please retry.", {
        status: 503,
      });
    }
    throw error;
  }
  const { user } = await withAuth({ ensureSignedIn: true });
  const slug = process.env.DOUG_GITHUB_APP_SLUG;
  if (!slug) {
    return new NextResponse("Repository setup is temporarily unavailable. Please retry.", {
      status: 503,
    });
  }

  const token = sealInstallFlow({
    nonce: randomBytes(32),
    expiresAt: Math.floor(Date.now() / 1000) + FLOW_MAX_AGE,
    subject: user.id,
    installationId: null,
  });
  const response = NextResponse.redirect(
    new URL(`https://github.com/apps/${encodeURIComponent(slug)}/installations/new`),
  );
  response.cookies.set(FLOW_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: FLOW_MAX_AGE,
    secure: process.env.NODE_ENV === "production",
  });
  return response;
}
