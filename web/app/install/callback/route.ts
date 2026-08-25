import { randomBytes } from "node:crypto";

import { getSignInUrl, withAuth } from "@workos-inc/authkit-nextjs";
import { type NextRequest, NextResponse } from "next/server";

import {
  InstallFlowConfigurationError,
  assertInstallFlowConfigured,
  sealInstallFlow,
  verifyInstallFlow,
} from "@/lib/install-flow";
import { GITHUB_REPO_SLUG, GITHUB_REPO_URL } from "@/lib/links";

const FLOW_COOKIE = "doug_install_flow";
const FLOW_MAX_AGE = 1800;

function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
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

function unavailable(): NextResponse {
  return message("Repository setup is temporarily unavailable. Please retry.", 503);
}

function queryInstallationId(request: NextRequest): number | null | undefined {
  const values = request.nextUrl.searchParams.getAll("installation_id");
  if (values.length === 0) return undefined;
  if (values.length !== 1 || !/^[1-9][0-9]*$/.test(values[0])) return null;
  const parsed = Number(values[0]);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    assertInstallFlowConfigured();
  } catch (error) {
    if (error instanceof InstallFlowConfigurationError) return unavailable();
    throw error;
  }
  const setupAction = request.nextUrl.searchParams.get("setup_action");
  if (setupAction === "request") {
    return clearFlow(
      message(
        "Doug is waiting for your organization admin to approve the repository connection.",
      ),
    );
  }
  if (setupAction === "update") {
    // `prompt: "consent"` DOES NOT REACH GITHUB, and no remedy may be built on
    // the belief that it does. WorkOS honours the parameter itself and never
    // forwards it; GitHub's authorize endpoint accepts only
    // `prompt=select_account`. Measured in production on 2026-08-21 (#167):
    // this arm and a plain /sign-in both completed through WorkOS in about 15
    // seconds with no consent screen, and GitHub's security log recorded no new
    // token. The parameter is kept because it is inert, not because it works —
    // this arm only needs to land the reader on /dashboard. #172 carries the
    // real question of refreshing a derived scope.
    const signInUrl = await getSignInUrl({ prompt: "consent", returnTo: "/dashboard" });
    return clearFlow(NextResponse.redirect(signInUrl));
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
          pkceRetried: false,
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
      pkceRetried: pending.pkceRetried,
    });
    const signInUrl = await getSignInUrl({ returnTo: "/install/callback" });
    return setFlow(NextResponse.redirect(signInUrl), token);
  }
  if (!auth.accessToken) {
    return unavailable();
  }

  const completedToken = sealInstallFlow({
    nonce: pending.nonce,
    expiresAt: pending.expiresAt,
    subject: auth.user.id,
    installationId,
    pkceRetried: pending.pkceRetried,
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
    return unavailable();
  }

  if (response.status === 204) {
    return clearFlow(
      NextResponse.redirect(new URL("/dashboard", request.url)),
    );
  }
  if (response.status === 404) {
    // NO LINK HERE MAY RETURN THE READER TO THIS PAGE. This arm used to offer
    // /install/callback?reauth=github as its only action, which re-signed the
    // reader in through WorkOS with `prompt: "consent"` and came straight back
    // to this same 403 — see the comment on the `update` arm earlier for the
    // production measurement, and #176 for the loop it created.
    //
    // The copy names a remedy that can actually change the answer, and states
    // the one case where nothing the reader does will. The API answers every
    // authority failure with the same 404 on purpose (api._prove_installer), so
    // this page CANNOT tell the three causes apart — a wrong GitHub account, a
    // Doug session with no GitHub identity, or an installation predating the
    // installer-id capture, which no re-authorization can repair. Copy that
    // asserted one of them would be wrong two times in three.
    return html(
      "<p>Only the GitHub account that installed Doug here can connect " +
        "repositories, and this sign-in is not confirmed as that account. " +
        "Your Doug account remains available.</p>" +
        "<p>Signing in to Doug again does not change this, because it returns " +
        "the same GitHub account. To connect this repository, sign out of Doug, " +
        "sign in to GitHub as the account that installed Doug, and start the " +
        "connection again.</p>" +
        '<p><a href="/dashboard">Go to your dashboard</a> to sign out. ' +
        "Sign out is in the account menu.</p>" +
        "<p>If you did install Doug from this account, this connection needs an " +
        `operator. Report it at <a href="${GITHUB_REPO_URL}/issues">` +
        `${GITHUB_REPO_SLUG} issues</a>.</p>`,
      403,
    );
  }
  if (response.status === 409) {
    return clearFlow(message("This repository connection is already assigned.", 409));
  }
  return unavailable();
}
