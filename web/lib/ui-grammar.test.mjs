// The grammar guard.
//
// ONE typographic rule runs the whole surface, and it is load-bearing rather
// than cosmetic: uppercase tracked mono is reserved for CLOSED MACHINE
// VOCABULARIES and nothing else — a run's band, a guard's state, a finding's
// severity, an ADR's status. English goes in sentence case. Before this rule
// the app set a section heading, a nav entry and a refusal-to-measure
// identically, which is the confusion a review surface exists to prevent.
//
// The rule is enforceable because it is a CLASS. `.vocab` in app/globals.css
// is the only declaration of `text-transform: uppercase` in web/, so a page
// that wants caps has to say which vocabulary it is rendering, by name, in a
// list this file pins. A page cannot drift back to the old grammar by copying
// a className from a neighbour.
//
// These are source-text pins, not render tests (house rule: no component
// render tests). What they protect is a claim about meaning — caps mean "this
// word came out of a CHECK constraint" — and a claim like that is broken by
// an edit, not by a render.
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

const dir = new URL("../", import.meta.url);

/** The two scopes the scan skips, each with the reason it is skipped. Neither
 *  is an exception to the RULE — both render closed vocabularies or a
 *  separately ruled look — and both are named here rather than left to a
 *  reader to discover.
 *
 *  A third scope does not exist: everything else under app/ and components/
 *  is scanned, and the last test in this file fails if the walk stops finding
 *  files. */
const SKIPPED = {
  // /docs wears the audit docs' look, ported wholesale by #350 the day before
  // this rule landed, and its caps are Archivo section markers rather than the
  // tracked mono this rule is about. Bringing that surface onto the rule is
  // doug#362, not a silent edit inside a look Andrew signed off separately.
  "components/docs/": "the /docs surface, ruled by #350",
  // Character-identical to console/components/band-chip.tsx — the lockstep
  // guard in console-lockstep.test.mjs compares the two as text, so this file
  // cannot take `.vocab` unless console's stylesheet grows the class too. The
  // word it sets in caps IS a closed vocabulary (the band), so it follows the
  // rule; only the mechanism differs, and the lockstep is why.
  "components/band-chip.tsx": "frozen by the console lockstep",
};

/** Every source file under app/ and components/, minus the skipped scopes. */
async function sources() {
  const files = new Map();
  async function walk(rel) {
    for (const entry of await readdir(new URL(rel, dir), { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      const next = `${rel}${entry.name}${entry.isDirectory() ? "/" : ""}`;
      if (Object.keys(SKIPPED).some((s) => next.startsWith(s))) continue;
      if (entry.isDirectory()) await walk(next);
      else if (/\.(tsx?|css)$/.test(entry.name)) {
        files.set(next, await readFile(new URL(next, dir), "utf8"));
      }
    }
  }
  await walk("app/");
  await walk("components/");
  return files;
}

/** Source with comments removed. A file that explains why the old grammar left
 *  is allowed to name it; only what ships is scanned. */
function code(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

test("`.vocab` is the one place in the app that sets uppercase", async () => {
  const css = code(await readFile(new URL("app/globals.css", dir), "utf8"));
  const rules = [...css.matchAll(/([^{}]+)\{([^}]*text-transform\s*:\s*uppercase[^}]*)\}/g)];
  assert.deepEqual(
    rules.map((m) => m[1].trim()),
    [".vocab"],
    "another rule sets uppercase — the grammar is no longer in one place",
  );
  // The chip's tracking is the registry surface's .07em, and it is part of the
  // device: caps without tracking read as shouting rather than as a token.
  assert.match(rules[0][2], /letter-spacing:\s*0\.07em/);
  assert.match(rules[0][2], /font-family:\s*var\(--mono-face\)/);
});

test("no page sets uppercase or tracks a label out on its own", async () => {
  // Tailwind's `uppercase`, and the four ways to track a label out: an
  // explicit positive em/px value, and the three named utilities. Negative
  // tracking is display typography (a 64px headline at -.05em) and is not
  // what this rule is about.
  const retired = /\buppercase\b|\btracking-(?:wide|wider|widest)\b|\btracking-\[0?\.\d/;
  const offenders = [];
  for (const [rel, src] of await sources()) {
    // The stylesheet is where the one rule lives; the test above pins that it
    // is the only rule there.
    if (rel === "app/globals.css") continue;
    const found = code(src).match(retired);
    if (found) offenders.push(`${rel}: ${found[0]}`);
  }
  assert.deepEqual(offenders, [], "a page is wearing the retired grammar");
});

/** Every `.vocab` on the surface, with the vocabulary it renders and where
 *  that vocabulary is closed. A new entry here is a claim that a CHECK
 *  constraint, a union type or the store's own column decides the word — not
 *  that the word looks good in caps. */
const VOCABULARIES = {
  "components/state-chip.tsx": "ChipKind: later | synthetic | unknown | off",
  "app/queue/page.tsx": "RunSummary.band",
  "app/dashboard/guards/page.tsx": "the engine's guard state",
  "app/dashboard/page.tsx": "a finding's severity, and a deviation's",
  "app/dashboard/memory/page.tsx": "an ADR's status",
  "app/dashboard/pr/[number]/page.tsx": "RunSummary.band",
};

test("every use of the vocabulary class names the vocabulary it renders", async () => {
  const users = [];
  for (const [rel, src] of await sources()) {
    if (rel === "app/globals.css") continue;
    if (/className=[^\n]*\bvocab\b|"vocab /.test(code(src))) users.push(rel);
  }
  assert.deepEqual(
    users.sort(),
    Object.keys(VOCABULARIES).sort(),
    "a file wears `.vocab` without declaring which closed vocabulary it renders",
  );
});

test("the scan reads the surface it claims to read", async () => {
  // The control on the three tests above: each of them passes vacuously if the
  // walk returns nothing, which is exactly what a moved directory or a changed
  // extension would cause.
  const files = await sources();
  assert.ok(files.has("app/globals.css"), "the stylesheet is not in the scan");
  assert.ok(files.has("app/dashboard/page.tsx"), "the ledger is not in the scan");
  assert.ok(files.size >= 40, `the scan only found ${files.size} files — the walk is broken`);
  for (const skipped of Object.keys(SKIPPED)) {
    assert.ok(
      ![...files.keys()].some((f) => f.startsWith(skipped)),
      `${skipped} is in the scan, and the reason it is skipped no longer applies`,
    );
  }
});
