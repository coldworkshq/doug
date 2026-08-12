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
  distDir: process.env.DOUG_WEB_DIST_DIR ?? ".next",
  output: "standalone",
  // Trace from the monorepo root so workspace-hoisted deps are included.
  outputFileTracingRoot: path.join(appDir, ".."),
  async headers() {
    return [
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
