import assert from "node:assert/strict";
import { test } from "node:test";

// The console serves under the unscoped operator credential, so its
// browser-side posture must match web's: no framing, no MIME sniffing, no
// full-URL referrers to other origins. This pins the headers so a config
// refactor cannot drop them silently.
test("every console response refuses framing and MIME sniffing, matching web", async () => {
  const { default: config } = await import("../next.config.ts");
  assert.equal(typeof config.headers, "function");
  const rules = await config.headers();
  const globalRule = rules.find((rule) => rule.source === "/:path*");
  assert.ok(globalRule, "expected a /:path* header rule");

  const headers = new Map(globalRule.headers.map((h) => [h.key, h.value]));
  assert.equal(headers.get("X-Frame-Options"), "DENY");
  assert.equal(headers.get("X-Content-Type-Options"), "nosniff");
  assert.equal(headers.get("Referrer-Policy"), "strict-origin-when-cross-origin");
});
