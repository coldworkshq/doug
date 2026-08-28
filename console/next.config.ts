import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appDir = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  output: "standalone",
  // Trace from the monorepo root so workspace-hoisted deps are included.
  outputFileTracingRoot: path.join(appDir, ".."),
  // Mirrors web/next.config.ts. DENY is deliberate: nothing embeds the
  // console in a frame (it is IAP-gated and has no embed surface), and it
  // holds the unscoped operator credential, so clickjacking is the risk
  // that matters. If an embedder ever appears, switch to a CSP
  // frame-ancestors allowlist rather than dropping the header.
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
