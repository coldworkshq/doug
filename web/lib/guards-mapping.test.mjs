// The mapping's intent: unset maps nobody; a typo refuses loudly rather
// than mapping nobody in silence; a stranger and the founder take the same
// lookup and get different answers from the data, not from a build flag.
import assert from "node:assert/strict";
import test from "node:test";

import { GuardsMappingError, engineTenantFor, parseGuardsMapping } from "./guards-mapping.ts";

test("unset or blank maps nobody", () => {
  assert.equal(engineTenantFor(150424894, undefined), null);
  assert.equal(engineTenantFor(150424894, "  "), null);
});

test("a mapped installation gets its engine tenant; every other one gets null", () => {
  const raw = "150424894:00000000-0000-0000-0000-000000000001, 7:tenant-b";
  assert.equal(engineTenantFor(150424894, raw), "00000000-0000-0000-0000-000000000001");
  assert.equal(engineTenantFor(7, raw), "tenant-b");
  assert.equal(engineTenantFor(8, raw), null);
  assert.equal(engineTenantFor(null, raw), null);
});

test("mutation: a malformed entry throws instead of quietly mapping nobody", () => {
  for (const raw of ["150424894", "abc:tenant", "150424894:", ":tenant"]) {
    assert.throws(() => parseGuardsMapping(raw), GuardsMappingError, raw);
  }
});

test("a trailing comma is not an entry", () => {
  assert.equal(parseGuardsMapping("1:a,").size, 1);
});
