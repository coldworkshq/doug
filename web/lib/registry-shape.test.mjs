// The read contract, from the consumer's side. Each test pins an intent:
// the two repos never disagree about what a field means (the schema and
// fixture are byte copies pinned by hash; the tables agree with the schema
// key for key and null for null); a figure cannot arrive without its
// sentence (a document with a snapshot and a missing declaration is
// rejected); a renamed or extra field fails here, never on a page.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  ENVELOPE,
  FIXTURE_SHA256,
  ROWS,
  SCHEMA_SHA256,
  isRegistrySnapshotV1,
} from "./registry-shape.ts";

const schemaText = await readFile(
  new URL("./registry-contract/registry-snapshot.v1.schema.json", import.meta.url),
  "utf8",
);
const fixtureText = await readFile(
  new URL("./registry-contract/registry-snapshot.v1.fixture.json", import.meta.url),
  "utf8",
);
const schema = JSON.parse(schemaText);
const sha = (text) => createHash("sha256").update(text).digest("hex");
const fixture = () => JSON.parse(fixtureText);

test("the schema and fixture are the registry's, byte for byte", () => {
  assert.equal(sha(schemaText), SCHEMA_SHA256, "copy the registry's file and re-pin on purpose");
  assert.equal(sha(fixtureText), FIXTURE_SHA256, "copy the registry's file and re-pin on purpose");
});

// The schema's subset: type, properties, required, additionalProperties,
// items, anyOf [X, null], const. Compare the table to it recursively so a
// nullability or shape change on either side fails here.
function compare(spec, node, path) {
  if (spec.t === "const") {
    assert.deepEqual(node, { const: spec.value }, path);
    return;
  }
  let inner = node;
  if (spec.nullable) {
    assert.ok(Array.isArray(node.anyOf) && node.anyOf.length === 2, `${path}: expected anyOf with null`);
    assert.deepEqual(node.anyOf[1], { type: "null" }, path);
    inner = node.anyOf[0];
  } else {
    assert.equal("anyOf" in node, false, `${path}: schema admits null, the table does not`);
  }
  assert.equal(inner.type, spec.t, path);
  if (spec.t === "array") compare(spec.items, inner.items, `${path}[]`);
  if (spec.t === "object") compareObject(spec.props, inner, path);
}

function compareObject(props, node, path) {
  assert.deepEqual(node.required, Object.keys(props), `${path}: required keys`);
  assert.equal(node.additionalProperties, false, `${path}: additionalProperties`);
  for (const [k, spec] of Object.entries(props)) compare(spec, node.properties[k], `${path}.${k}`);
}

test("the tables agree with the schema, key for key and null for null", () => {
  compareObject(ENVELOPE, schema, "envelope");
  for (const [name, props] of Object.entries(ROWS)) {
    compareObject(props, schema.$defs[name], `$defs.${name}`);
  }
  assert.deepEqual(Object.keys(schema.$defs).sort(), Object.keys(ROWS).sort());
});

test("the fixture passes the guard", () => {
  assert.equal(isRegistrySnapshotV1(fixture()), true);
});

test("mutation: a renamed envelope field is rejected", () => {
  const doc = fixture();
  doc.generatedAt = doc.generated_at;
  delete doc.generated_at;
  assert.equal(isRegistrySnapshotV1(doc), false);
});

test("mutation: an extra key on a row is rejected", () => {
  const doc = fixture();
  doc.guards[0].artifactBytes = "AAAA";
  assert.equal(isRegistrySnapshotV1(doc), false);
});

test("a document with a snapshot cannot drop a declaration", () => {
  for (const key of ["provenance", "synthetic", "tenant_id", "generated_at"]) {
    const doc = fixture();
    doc[key] = null;
    assert.equal(isRegistrySnapshotV1(doc), false, key);
  }
});

test("a refusal is a document with no snapshot and a reason, and nothing less", () => {
  const doc = fixture();
  doc.snapshot = null;
  doc.generated_at = null;
  doc.reason = "REGISTRY_DATA_PROVENANCE is not set.";
  assert.equal(isRegistrySnapshotV1(doc), true);
  doc.reason = null;
  assert.equal(isRegistrySnapshotV1(doc), false);
});

test("rejects null, a string, and an array, which JSON.parse can all produce", () => {
  for (const value of [null, "snapshot", [], 1]) assert.equal(isRegistrySnapshotV1(value), false);
});
