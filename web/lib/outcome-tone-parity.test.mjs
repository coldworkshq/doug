import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

/** Every input the two surfaces must answer identically: the production
 *  vocabulary (`api/doug/adjudicate.py`'s OutcomeKind — revert | clean |
 *  censored), the permitted-but-never-written `hotfix`, the absent row, and
 *  kinds neither build has heard of. The case variants are here because a
 *  copy that drifted to case-insensitive matching would still pass every
 *  same-workspace test on both sides while disagreeing with the other copy. */
const KINDS = [
  null,
  "clean",
  "censored",
  "revert",
  "hotfix",
  "graded-miss",
  "unknown-future-kind",
  "",
  "CLEAN",
  "Censored",
];

test("the web and console outcome tone rules agree on every kind, including ones neither build knows", async () => {
  // The honesty property this pins is CROSS-surface, and it was the one
  // thing neither suite could see. Each workspace's own test pins its own
  // copy to itself; both stayed green while the console painted `censored`
  // in the flag colour and the dashboard did not. Nothing failed, because
  // nothing compared them. This is that comparison.
  //
  // It imports console's module directly rather than re-deriving the rule:
  // a third copy of the expectation would be one more thing to drift.
  // The import only works in this direction — console/lib/runs.ts has zero
  // imports, so it resolves standalone, while web/lib/dashboard-model.ts
  // imports "./coverage" extensionless and needs the loader registered
  // above. Hence this file lives in web/lib, not console/lib.
  const { outcomeTone: webTone } = await import("./dashboard-model.ts?tone-parity");
  const { outcomeTone: consoleTone } = await import("../../console/lib/runs.ts");

  for (const kind of KINDS) {
    // Agreement, not a hardcoded expected list — deliberately. This test's
    // job is to fail when the two copies diverge, whichever one moved, and
    // to stay silent about which answer is right. The ruled mapping itself
    // is pinned separately on each side (dashboard-model.test.mjs and
    // console/lib/runs.test.mjs), so a hardcoded list here would only add a
    // third copy that could itself go stale.
    assert.equal(
      consoleTone(kind),
      webTone(kind),
      `console and web disagree on outcome kind ${JSON.stringify(kind)}: ` +
        `console says "${consoleTone(kind)}", web says "${webTone(kind)}"`,
    );
  }

  // Guard the guard: if either export vanished or stopped being callable,
  // every assertion above would compare undefined to undefined and pass.
  assert.equal(typeof consoleTone, "function");
  assert.equal(typeof webTone, "function");
  assert.equal(consoleTone("clean"), "clear");
  assert.equal(webTone("censored"), "neutral");
});
