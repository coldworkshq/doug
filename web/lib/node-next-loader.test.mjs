// Pins for the `@/*` alias rule in node-next-loader.mjs.
//
// The loader is test infrastructure, and it is pinned for the same reason the
// code it loads is: it grew one hand-written entry per module until a route's
// new `@/lib/links` import simply failed to resolve, taking a whole test file
// with it. The single rule that replaced those entries appends `.ts`, and this
// file exists to hold that append to the extensionless-ONLY rule the loader's
// own fallback states — appending to a specifier that already names its
// extension reports the wrong file missing and masks the real error.
import assert from "node:assert/strict";
import test from "node:test";

import { resolve } from "./node-next-loader.mjs";

/** Stands in for Node's resolver and records what it was handed. */
function spy() {
  const seen = [];
  const next = async (specifier) => {
    seen.push(specifier);
    return { url: specifier, shortCircuit: true };
  };
  return { seen, next };
}

test("an extensionless @/lib specifier resolves to the .ts sibling of the loader", async () => {
  // Resolved against THIS FILE, never the importer. Two of the three entries
  // this rule replaced walked `../../../lib/` up from the importing module,
  // which is correct only for an importer exactly three segments deep.
  const { seen, next } = spy();
  await resolve("@/lib/links", {}, next);
  await resolve("@/lib/install-flow", {}, next);
  assert.equal(seen.length, 2);
  assert.match(seen[0], /\/web\/lib\/links\.ts$/);
  assert.match(seen[1], /\/web\/lib\/install-flow\.ts$/);
});

test("a @/lib specifier that names its extension is resolved as written", async () => {
  // THE REGRESSION THIS FILE EXISTS TO CATCH. `web/lib` holds four .json
  // fixtures; resolving one to `<name>.json.ts` would report a file nobody
  // wrote as missing and hide the one that is.
  const { seen, next } = spy();
  await resolve("@/lib/queue-fixture.json", {}, next);
  assert.equal(seen.length, 1);
  assert.match(seen[0], /\/web\/lib\/queue-fixture\.json$/);
  assert.doesNotMatch(seen[0], /\.ts$/);
});
