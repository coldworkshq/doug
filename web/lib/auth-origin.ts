import type { NextRequest } from "next/server";

// Retired as a sign-in origin by ADR-0034 decision 1: `next.config.ts`
// answers every path on it with a 308 to the apex. A redirect URI here would
// make the canonicalization below (a 307 to this origin) and that 308 chase
// each other forever, on every host. Refusing it fails closed instead:
// /sign-in answers 503 with its message, which the deploy smoke and
// `api/deploy/domains.sh` both name.
const RETIRED_HOSTS = new Set(["doug.coldworks.dev"]);

function firstForwardedValue(value: string | null): string | null {
  const first = value?.split(",", 1)[0]?.trim();
  return first || null;
}

export function configuredWorkOSRedirectUri(): URL | null {
  const value = process.env["NEXT_PUBLIC_WORKOS_REDIRECT_URI"];
  if (!value) return null;

  try {
    const url = new URL(value);
    if (!(["http:", "https:"].includes(url.protocol))) return null;
    if (url.username || url.password || url.search || url.hash) return null;
    if (url.pathname !== "/auth/callback") return null;
    if (RETIRED_HOSTS.has(url.host)) return null;
    return url;
  } catch {
    return null;
  }
}

export function requestHostMatches(
  request: NextRequest,
  redirectUri: URL,
): boolean {
  const host = firstForwardedValue(request.headers.get("x-forwarded-host"))
    ?? firstForwardedValue(request.headers.get("host"));
  if (!host) return false;

  try {
    const candidate = new URL(`${redirectUri.protocol}//${host}`);
    return !candidate.username
      && !candidate.password
      && candidate.pathname === "/"
      && !candidate.search
      && !candidate.hash
      && candidate.host === redirectUri.host;
  } catch {
    return false;
  }
}
