import type { NextRequest } from "next/server";

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
