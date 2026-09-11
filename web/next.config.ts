import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appDir = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  // `lib/auth-entry.integration.test.mjs` runs a real `next build` and serves it
  // with `next start`. Sharing `.next` with every other build in the workspace
  // made that test lose races it could not see: `next build` wipes the dist dir
  // immediately after taking the dist lock, while `next start` takes no lock and
  // reads BUILD_ID ~80ms after it has already reported "Ready". Any other build
  // waiting on the lock therefore deletes BUILD_ID inside that window, and the
  // server dies with "Could not find a production build in the '.next'
  // directory". Giving the test its own dist dir makes it the only writer.
  // Unset everywhere that ships, so the deploy path stays exactly `.next`.
  distDir: process.env.DOUG_WEB_DIST_DIR ?? ".next",
  output: "standalone",
  // Trace from the monorepo root so workspace-hoisted deps are included.
  outputFileTracingRoot: path.join(appDir, ".."),
  // The door is the Coldworks landing page, served verbatim out of public/
  // as the self-contained document it has always been (its fonts, styles and
  // lattice are inlined), rewritten onto the bare origin so the address that
  // gets pasted into an email is the origin itself. ADR-0034. Doug's own
  // page lives one link in, at /doug. The audit CLI's docs are the same
  // shape under /docs/audit, beside Doug's docs rather than inside them.
  //
  // Rewrites, not redirects, and after the app's own routes: `/` has no
  // page, so the rewrite fires; `/docs/audit/*` has no route either.
  async rewrites() {
    return [
      { source: "/", destination: "/landing.html" },
      { source: "/docs/audit", destination: "/docs/audit/index.html" },
      { source: "/docs/audit/:page", destination: "/docs/audit/:page.html" },
    ];
  },
  // The subdomain redirects to the apex, path-preserving (ADR-0034,
  // decision 1). `doug.coldworks.dev` keeps its Cloud Run mapping so every
  // link already written into a pull request keeps resolving; each one is
  // answered with a 308 to the same path on `coldworks.dev`. Keyed on that
  // one host, never a catch-all: the deploy smokes the run.app host and
  // expects 200 (`api/deploy/gcp.sh` promote_if_healthy and
  // `web/scripts/smoke-auth-entry.sh`), and the apex itself must serve, not
  // loop. Next matches `has: host` against the Host header the container
  // receives, which is the mapped domain on Cloud Run; `x-forwarded-host` is
  // not consulted here. Config redirects run before `proxy.ts`, so
  // `/dashboard/*` and `/sign-in` on the subdomain take this 308 instead of
  // the proxy's and the route handler's 307 to the configured origin.
  //
  // Not keyed on `DOUG_WEB_DOMAIN`: deploy.yml already sets it, so an
  // env-keyed redirect would fire on merge. This merges only after the apex
  // is mapped onto doug-web and cut over; until then the redirect would
  // send tenants to the registry. Pinned by the single-host suite in
  // `lib/auth-entry.integration.test.mjs`.
  async redirects() {
    return [
      {
        source: "/:path*",
        has: [{ type: "host", value: "doug.coldworks.dev" }],
        destination: "https://coldworks.dev/:path*",
        permanent: true,
      },
    ];
  },
  async headers() {
    return [
      // The door and the audit docs are static documents served by rewrite.
      // Next gives public files no caching of its own; a short shared max-age
      // lets the address that gets pasted into an email serve from a cache
      // for a few minutes and revalidate after, while a deploy still lands
      // within the hour.
      {
        source: "/",
        headers: [{ key: "Cache-Control", value: "public, max-age=300, stale-while-revalidate=3600" }],
      },
      {
        source: "/docs/audit/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=300, stale-while-revalidate=3600" }],
      },
      {
        source: "/:path*",
        headers: [
          {
            key: "X-Frame-Options",
            value: "DENY",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
