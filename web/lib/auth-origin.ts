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

export function publicRequestOrigin(request: NextRequest): string | null {
  const host = firstForwardedValue(request.headers.get("x-forwarded-host"))
    ?? firstForwardedValue(request.headers.get("host"));
  const protocol = firstForwardedValue(request.headers.get("x-forwarded-proto"))
    ?? request.nextUrl.protocol.replace(/:$/, "");
  if (!host || !(["http", "https"].includes(protocol))) return null;

  try {
    return new URL(`${protocol}://${host}`).origin;
  } catch {
    return null;
  }
}
