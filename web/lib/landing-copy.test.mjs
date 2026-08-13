import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

test("landing copy does not imply a cross-repo result we have not measured", () => {
  assert.equal(page.includes("repos like yours"), false);
});

test("landing copy does not use learns as a marketing verb", () => {
  // experience.md: counts and dates, never verbs of ability. "Others learn
  // what reviewers say" is about incumbents and stays.
  assert.equal(/title:\s*"Learns /.test(page), false);
  assert.equal(page.includes("Doug learns what production did"), false);
});

test("rule 03 is a promise on a cadence, not a claim that the number is live", () => {
  assert.equal(
    page.includes("is counted, dated, and published"),
    false,
  );
  assert.match(page, /will be counted, dated, and published/);
});

test("the evidence panel still withholds the unpublished miss rate", () => {
  assert.match(page, /Published miss rate/);
  assert.match(page, />\s*—\s*</);
});
