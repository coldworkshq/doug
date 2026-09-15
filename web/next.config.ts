import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { COLDWORKS_URL } from "./lib/links";

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
  // page lives one link in, at /doug.
  //
  // A rewrite, not a redirect, and after the app's own routes: `/` has no
  // page, so the rewrite fires. Nothing is rewritten under /docs: every docs
  // page is a route of the docs shell (app/docs/layout.tsx).
  async rewrites() {
    return [{ source: "/", destination: "/landing.html" }];
  },
  // The subdomain redirects to the apex, path-preserving (ADR-0034,
  // decision 1). `doug.coldworks.dev` keeps its Cloud Run mapping so every
  // link already written into a pull request keeps resolving; each page
  // path on it is answered with a 308 to the same path and query on the
  // apex (Next exempts `/_next/*` from custom redirects). Keyed on that one
  // host, never a catch-all: the deploy smokes the run.app host and expects
  // 200 (`api/deploy/gcp.sh` promote_if_healthy and
  // `web/scripts/smoke-auth-entry.sh`), and the apex itself must serve, not
  // loop. Next compiles `has[].value` into `new RegExp(`^${value}$`)` and
  // matches it against the Host header the container receives (the mapped
  // domain on Cloud Run; `x-forwarded-host` is not consulted), so the dots
  // are escaped: unescaped, `doug-coldworks.dev` would match too. Config
  // redirects run before `proxy.ts`, so `/dashboard/*` and `/sign-in` on the
  // subdomain take this 308 instead of the 307 to the configured origin.
  //
  // Not keyed on `DOUG_WEB_DOMAIN`: deploy.yml already sets it, so an
  // env-keyed redirect would fire on merge. Two controls hold it until the
  // apex is mapped onto doug-web: `api/deploy/gcp.sh` refuses the web deploy
  // while the apex is not among the service's mappings, and
  // `web/lib/auth-origin.ts` refuses a redirect URI on the retired host so
  // this 308 and the proxy's 307 can never chase each other. Pinned by the
  // single-host suite in `lib/auth-entry.integration.test.mjs`.
  //
  // `www.coldworks.dev` is the alias and redirects to the apex the same way
  // (doug#333), once the founder maps it onto this service; until then the
  // rule is inert, because the host never reaches this container. That host
  // served the registry's landing and the audit CLI's docs, so its docs URLs
  // mean the audit docs, which live at /docs/audit here: a path-preserving
  // rule alone would send www/docs/cli.html to a 404 and www/docs/cli to
  // Doug's own CLI page (probed on the apex 2026-09-14). The docs rules
  // mirror the forwards the registry answered and come before the catch-all,
  // because the first matching rule wins. Permanent, like the subdomain's:
  // the alias is settled. The apex rules after them take each forward the
  // rest of the way.
  //
  // The audit's docs moved inside the one docs site on 2026-09-15: its
  // overview is the second half of /docs, and its pages are routes. The
  // static documents they replaced answered at /docs/audit,
  // /docs/audit/index.html, and /docs/audit/<page>.html, and those URLs are
  // in pull requests, issues, and the www forwards above, so each redirects
  // to what replaced it. After the www rules, so they only ever answer the
  // apex. Temporary: the docs' shape is new, and a 308 is cached with no
  // expiry. No rule for the old stylesheet: no page links it.
  async redirects() {
    const www = [{ type: "host" as const, value: "www\\.coldworks\\.dev" }];
    return [
      {
        source: "/:path*",
        has: [{ type: "host", value: "doug\\.coldworks\\.dev" }],
        destination: `${COLDWORKS_URL}/:path*`,
        permanent: true,
      },
      { source: "/landing.html", has: www, destination: `${COLDWORKS_URL}/`, permanent: true },
      { source: "/docs", has: www, destination: `${COLDWORKS_URL}/docs/audit`, permanent: true },
      { source: "/docs/:path*", has: www, destination: `${COLDWORKS_URL}/docs/audit/:path*`, permanent: true },
      { source: "/:path*", has: www, destination: `${COLDWORKS_URL}/:path*`, permanent: true },
      { source: "/docs/audit", destination: "/docs#the-audit", permanent: false },
      { source: "/docs/audit/index.html", destination: "/docs#the-audit", permanent: false },
      {
        source: "/docs/audit/:page(quickstart|connect|cli).html",
        destination: "/docs/audit/:page",
        permanent: false,
      },
    ];
  },
  async headers() {
    return [
      // The door is a static document served by rewrite. Next gives public
      // files no caching of its own; a short shared max-age lets the address
      // that gets pasted into an email serve from a cache for a few minutes
      // and revalidate after, while a deploy still lands within the hour.
      {
        source: "/",
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
