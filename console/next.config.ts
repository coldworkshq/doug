import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appDir = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  output: "standalone",
  // Trace from the monorepo root so workspace-hoisted deps are included.
  outputFileTracingRoot: path.join(appDir, ".."),
};

export default nextConfig;
