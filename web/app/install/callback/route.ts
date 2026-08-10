import { randomBytes } from "node:crypto";

import { getSignInUrl, withAuth } from "@workos-inc/authkit-nextjs";
import { type NextRequest, NextResponse } from "next/server";

import { sealInstallFlow, verifyInstallFlow } from "@/lib/install-flow";

const FLOW_COOKIE = "doug_install_flow";
const FLOW_MAX_AGE = 1800;

function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/install",
    maxAge,
    secure: process.env.NODE_ENV === "production",
  };
}

function setFlow(response: NextResponse, token: string): NextResponse {
  response.cookies.set(FLOW_COOKIE, token, cookieOptions(FLOW_MAX_AGE));
  return response;
}

function clearFlow(response: NextResponse): NextResponse {
  response.cookies.set(FLOW_COOKIE, "", cookieOptions(0));
  return response;
}

function message(body: string, status = 200): NextResponse {
  return new NextResponse(body, {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

function html(body: string, status = 200): NextResponse {
  return new NextResponse(body, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

function invalidFlow(): NextResponse {
  return clearFlow(message("This repository connection could not be verified.", 400));
}

function queryInstallationId(request: NextRequest): number | null | undefined {
  const values = request.nextUrl.searchParams.getAll("installation_id");
  if (values.length === 0) return undefined;
  if (values.length !== 1 || !/^[1-9][0-9]*$/.test(values[0])) return null;
  const parsed = Number(values[0]);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const setupAction = request.nextUrl.searchParams.get("setup_action");
  if (setupAction === "request") {
    return clearFlow(
      message(
        "Doug is waiting for your organization admin to approve the repository connection.",
      ),
    );
  }
  if (setupAction === "update") {
    const signInUrl = await getSignInUrl({ prompt: "consent", returnTo: "/dashboard" });
    return clearFlow(NextResponse.redirect(signInUrl));
  }
  if (request.nextUrl.searchParams.get("reauth") === "github") {
    const token = request.cookies.get(FLOW_COOKIE)?.value;
    try {
      const flow = token ? verifyInstallFlow(token) : null;
      if (!flow || flow.installationId === null) return invalidFlow();
    } catch {
      return invalidFlow();
    }
    const signInUrl = await getSignInUrl({
      prompt: "consent",
      returnTo: "/install/callback",
    });
    return NextResponse.redirect(signInUrl);
  }

  const queryId = queryInstallationId(request);
  if (queryId === null) return invalidFlow();
  const cookieToken = request.cookies.get(FLOW_COOKIE)?.value;
  let pending;
  try {
    pending = cookieToken
      ? verifyInstallFlow(cookieToken)
      : {
          nonce: Uint8Array.from(randomBytes(32)),
          expiresAt: Math.floor(Date.now() / 1000) + FLOW_MAX_AGE,
          subject: null,
          installationId: null,
        };
  } catch {
    return invalidFlow();
  }

  if (
    queryId !== undefined &&
    pending.installationId !== null &&
    queryId !== pending.installationId
  ) {
    return invalidFlow();
  }
  const installationId = queryId ?? pending.installationId;
  if (installationId === null || installationId === undefined) return invalidFlow();

  const auth = await withAuth();
  if (auth.user && pending.subject !== null && pending.subject !== auth.user.id) {
    return invalidFlow();
  }

  if (!auth.user) {
    const token = sealInstallFlow({
      nonce: pending.nonce,
      expiresAt: pending.expiresAt,
      subject: pending.subject,
      installationId,
    });
    const signInUrl = await getSignInUrl({ returnTo: "/install/callback" });
    return setFlow(NextResponse.redirect(signInUrl), token);
  }
  if (!auth.accessToken) {
    return message("Repository setup is temporarily unavailable. Please retry.", 503);
  }

  const completedToken = sealInstallFlow({
    nonce: pending.nonce,
    expiresAt: pending.expiresAt,
    subject: auth.user.id,
    installationId,
  });
  const apiUrl = process.env.DOUG_API_URL ?? "http://localhost:8000";
  let response: Response;
  try {
    response = await fetch(new URL("/v1/installations/bind/complete", apiUrl), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${auth.accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        installation_id: installationId,
        flow_token: completedToken,
      }),
    });
  } catch {
    return message("Repository setup is temporarily unavailable. Please retry.", 503);
  }

  if (response.status === 204) {
    return clearFlow(
      NextResponse.redirect(new URL("/dashboard", request.url)),
    );
  }
  if (response.status === 404) {
    return html(
      "<p>A GitHub connection is required only to connect repositories. " +
        "Your Doug account remains available.</p>" +
        '<p><a href="/install/callback?reauth=github">Continue with the GitHub account that installed Doug</a></p>',
      403,
    );
  }
  if (response.status === 409) {
    return clearFlow(message("This repository connection is already assigned.", 409));
  }
  return message("Repository setup is temporarily unavailable. Please retry.", 503);
}
