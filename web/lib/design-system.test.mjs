// Contract pins for the design-system utilities ported from
// console/app/globals.css. These are source-text pins, not render tests
// (house rule: no component render tests) — the utilities are CSS, and the
// properties below are honesty rules that a future edit could quietly break.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const cssUrl = new URL("../app/globals.css", import.meta.url);

/** CSS with comments removed, so selector counts cannot be fooled by prose
 *  that happens to mention a class name. */
function code(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** The declarations of the first rule whose selector list contains `selector`. */
function ruleBody(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? null;
}

test("number columns align: .mono pins tabular numerals", async () => {
  // Intent: a score column that does not align is unreadable at 34px rows.
  const body = ruleBody(code(await readFile(cssUrl, "utf8")), ".mono");
  assert.ok(body, ".mono utility is missing from web/app/globals.css");
  assert.match(body, /font-variant-numeric:\s*tabular-nums/);
});

test("there are exactly two data colours, and they are --flag and --clear", async () => {
  // Intent: NEVER a third data colour. Made mechanical: the set of .data-*
  // selectors in the stylesheet is closed at these two.
  const css = code(await readFile(cssUrl, "utf8"));
  const selectors = [...new Set(css.match(/\.data-[\w-]+/g) ?? [])].sort();
  assert.deepEqual(selectors, [".data-clear", ".data-flag"]);
  assert.match(ruleBody(css, ".data-flag") ?? "", /var\(--flag\)/);
  assert.match(ruleBody(css, ".data-clear") ?? "", /var\(--clear\)/);
});

test("coverage is a magnitude, not a judgement", async () => {
  // Intent: the coverage ramp is a neutral sequential scale. Low coverage is
  // alarmed by how empty the track looks, never by borrowing the flag/clear hue.
  const css = code(await readFile(cssUrl, "utf8"));
  for (const selector of [".cov-track", ".cov-fill"]) {
    const body = ruleBody(css, selector);
    assert.ok(body, `${selector} utility is missing from web/app/globals.css`);
    assert.equal(body.includes("var(--flag)"), false, `${selector} must not use the flag colour`);
    assert.equal(body.includes("var(--clear)"), false, `${selector} must not use the clear colour`);
  }
});

test("chrome never becomes a data verdict", async () => {
  // Intent: --iridescent fails CVD separation against --flag at ΔE 6.1 in
  // NORMAL vision, so it is chrome only — never a .data-* colour.
  const css = code(await readFile(cssUrl, "utf8"));
  const dataRules = css.match(/\.data-[\w-]+[^{]*\{[^}]*\}/g) ?? [];
  // Non-vacuity guard only. How MANY data colours there may be is the
  // previous test's property; asserting it here too would make a third-colour
  // regression fail two tests and discriminate neither.
  assert.ok(dataRules.length >= 2, "no .data-* rules found — this test would pass vacuously");
  for (const rule of dataRules) {
    assert.equal(rule.includes("--iridescent"), false, `data rule borrows chrome: ${rule}`);
  }
});

test("the CVD reasoning survives the port from the console", async () => {
  // Intent: the comment IS the spec. A port that drops it leaves the next
  // reader with two hex values and no reason not to add a third.
  const css = await readFile(cssUrl, "utf8");
  assert.match(css, /fails CVD separation against --flag at ΔE 6\.1/);
  assert.match(css, /Coverage is a magnitude, not a judgement/);
});
