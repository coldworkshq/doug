// Intents: one closed vocabulary; every chip has a sentence; the Guards
// `later` states the subtraction claim (design lock, A2); chips are chrome,
// never data colour.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { CHIP_KINDS, CHIP_WORD, chipGloss } from "./state-chip.ts";

const component = await readFile(new URL("../components/state-chip.tsx", import.meta.url), "utf8");

test("the set is closed at four and every kind has a word", () => {
  assert.deepEqual([...CHIP_KINDS], ["later", "synthetic", "unknown", "off"]);
  for (const kind of CHIP_KINDS) assert.equal(typeof CHIP_WORD[kind], "string");
});

test("every kind has a gloss, with or without a detail", () => {
  for (const kind of CHIP_KINDS) {
    assert.ok(chipGloss(kind, "guards").length > 10, kind);
    assert.ok(chipGloss(kind, "guards", "a reason").length > 10, kind);
  }
});

test("the Guards later chip states the subtraction claim, not a bare have-not-run line", () => {
  const gloss = chipGloss("later", "guards");
  assert.match(gloss, /remove reviewer work when proven/);
  assert.match(gloss, /none proven yet/);
  assert.equal(/have not run/.test(gloss), false);
});

test("unknown and off carry the source's own words", () => {
  assert.match(chipGloss("unknown", "decisions", "the read answered 502"), /the read answered 502/);
  assert.match(chipGloss("off", "reads before the diff", "the reader is off"), /the reader is off/);
  assert.match(chipGloss("synthetic", "T", "the wind tunnel corpus"), /wind tunnel corpus/);
});

test("the component renders the word and the sentence together, and no tooltip", () => {
  assert.match(component, /chipGloss\(kind, subject, detail\)/);
  assert.match(component, /\{CHIP_WORD\[kind\]\}/);
  assert.match(component, /\{gloss\}/);
  assert.equal(component.includes("title="), false, "a gloss in a tooltip can be cropped out of a screenshot");
  assert.equal(/data-\w+-color|\.data-/.test(component), false, "chips are chrome, not data");
});
