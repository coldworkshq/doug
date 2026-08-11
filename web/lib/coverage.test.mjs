import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

test("coverage uses GitHub's changed_files as denominator, never the fetched list", async () => {
  const { coveragePercent } = await import("./coverage.ts?denominator");
  const cov = { diff_chars: 100, sent_chars: 100, files_sent: 3, files_unseen: [], file_cut: null };
  assert.deepEqual(coveragePercent(cov, 6), { kind: "known", pct: 50, low: false });
  assert.deepEqual(coveragePercent(cov, null), { kind: "unknown-denominator" });
  assert.deepEqual(coveragePercent(null, 6), { kind: "no-read" });
});

test("coverageLabel refuses the false 100% and the false 0%", async () => {
  const { coverageLabel } = await import("./coverage.ts?label-guards");
  assert.equal(coverageLabel({ kind: "known", pct: 99.6, low: false }), "<100%");
  assert.equal(coverageLabel({ kind: "known", pct: 0.3, low: false }), "<1%");
  assert.equal(coverageLabel({ kind: "unknown-denominator" }), "—");
});
