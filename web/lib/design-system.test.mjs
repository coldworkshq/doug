// Contract pins for the design-system utilities ported from
// console/app/globals.css. These are source-text pins, not render tests
// (house rule: no component render tests) — the utilities are CSS, and the
// properties below are honesty rules that a future edit could quietly break.
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
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

const bandChipUrl = new URL("../components/band-chip.tsx", import.meta.url);
const coverageRulerUrl = new URL("../components/coverage-ruler.tsx", import.meta.url);
const runSpineUrl = new URL("../components/run-spine.tsx", import.meta.url);

test("BandChip always says the word, in both colour branches", async () => {
  // Intent: --flag and --clear sit in the 6-8 CVD floor band, where secondary
  // encoding is not optional — the WORD is that encoding. A bare dot or a
  // colour swatch would leave a CVD reader with two chips they cannot tell
  // apart. Source pin rather than a render test (house rule).
  const chip = await readFile(bandChipUrl, "utf8");
  const branches = chip.match(/flagged \? "([^"]*)" : "([^"]*)"/);
  assert.ok(branches, "BandChip must pick its label with a flagged ? word : word ternary");
  assert.ok(branches[1].trim().length > 0, "the flagged branch renders no word");
  assert.ok(branches[2].trim().length > 0, "the cleared branch renders no word");
  // The reasoning has to survive too, or the next editor sees only two strings.
  assert.match(chip, /The colour is ALWAYS accompanied by its word/);
});

test("the coverage ruler never spends a judgement colour on a magnitude", async () => {
  // Intent: same rule dashboard-contract.test.mjs:60-61 pins for the CSS
  // module — the cut marker and the bar are measurements. Emptiness is the
  // alarm; hue stays reserved for Doug's routing decision.
  const ruler = await readFile(coverageRulerUrl, "utf8");
  assert.match(ruler, /budget cut/); // the marker exists to be constrained
  assert.equal(ruler.includes("var(--flag)"), false, "coverage ruler uses the flag colour");
  assert.equal(ruler.includes("var(--clear)"), false, "coverage ruler uses the clear colour");
  assert.equal(/className="[^"]*\bdata-(flag|clear)\b/.test(ruler), false);
});

test("no spine node carries a verdict colour", async () => {
  // Intent (RunSpine's own docstring): a graded outcome's kind is a judgment,
  // and that judgment already renders in colour WITH its word in the Outcome
  // block. Colouring the same fact again on a bare dot asserts it twice, and
  // a reverted PR's dot would have nothing to say why it is green.
  const spine = await readFile(runSpineUrl, "utf8");
  assert.equal(spine.includes("var(--flag)"), false, "a spine node uses the flag colour");
  assert.equal(spine.includes("var(--clear)"), false, "a spine node uses the clear colour");
  assert.equal(/\bdata-(flag|clear)\b/.test(spine), false);
  assert.match(spine, /Every node here is neutral \(done\) or hollow \(wait\)/);
});

test("the CVD reasoning survives the port from the console", async () => {
  // Intent: the comment IS the spec. A port that drops it leaves the next
  // reader with two hex values and no reason not to add a third.
  const css = await readFile(cssUrl, "utf8");
  assert.match(css, /fails CVD separation against --flag at ΔE 6\.1/);
  assert.match(css, /Coverage is a magnitude, not a judgement/);
});

test("the dashboard surface keeps the orphan values it inherited, exactly", async () => {
  // Intent (plan A5.6, controller ruling): dashboard.module.css carried values
  // with NO equivalent in the palette, and the ruling was that they keep their
  // exact hex inside the scoped surface block — never substituted for globals'
  // nearest neighbour, never left dangling.
  //
  // This is pinned because the failure is silent and visual. `--rule-soft`
  // alone draws every row divider in the run ledger; deleting it leaves
  // `var(--rule-soft)` undefined and the dividers simply stop rendering, while
  // substituting globals' `--muted`/`--secondary` (#f6f5f1, a visibly
  // different value) restyles the whole table. Neither shows up in any other
  // test, because no test renders. Before this test existed, removing the
  // token left all 153 green — verified, not assumed.
  //
  // Three, not the four the module carried: #d4d1c8 was the hand-rolled
  // ruler border and legend swatch, and both use sites ceased to exist when
  // CoverageRuler replaced them (it brings console's own #c9c6bd). A token
  // nobody references would be dead CSS, so it was correctly not carried.
  //
  // If a value here ever gains a real palette home, delete it from the block
  // AND from this list in the same commit; do not loosen the assertion.
  const css = await readFile(cssUrl, "utf8");
  const block = css.match(/\.dashboard-surface\s*\{[^}]+\}/g)?.join("\n") ?? "";
  assert.ok(block, "the .dashboard-surface scope block is gone");

  assert.match(block, /--rule-soft:\s*#f1efe9/);
  assert.match(block, /--dim:\s*#aaa79f/);
  assert.match(block, /--row-hover:\s*#faf9f5/);

  // …and the two that deliberately did NOT come here stay out: #eceae3 and
  // #3d403c are the console's .cov-track/.cov-fill, already global utilities.
  // A copy inside this scope would be a second source of truth for the
  // coverage ramp.
  assert.equal(block.includes("#eceae3"), false);
  assert.equal(block.includes("#3d403c"), false);
});

test("the surface-scoped tokens are used only where the surface is mounted", async () => {
  // Doug, PR 102, reader:css-token-scope-coupling. --rule-soft, --dim and
  // --row-hover are declared ONLY on .dashboard-surface. Anything using them
  // outside that wrapper resolves them to nothing and silently loses its row
  // dividers, muted text or hover tint — no build error, no test failure, and
  // nothing renders in this suite to catch it.
  //
  // So the blast radius is pinned instead: today exactly one source file
  // reaches for them, and it is the file that mounts the surface. Extracting a
  // piece of the dashboard into components/ trips this test, which is the
  // moment to decide — move the token to :root, or pass the colour in, or
  // mount the surface around the new home. Do NOT just add the file here
  // unless it genuinely renders inside .dashboard-surface.
  const dir = new URL("../", import.meta.url);
  const sources = [];
  async function walk(rel) {
    for (const entry of await readdir(new URL(rel, dir), { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      const next = `${rel}${entry.name}${entry.isDirectory() ? "/" : ""}`;
      if (entry.isDirectory()) await walk(next);
      else if (/\.(tsx?|mjs)$/.test(entry.name)) sources.push(next);
    }
  }
  await walk("");

  const users = [];
  for (const rel of sources) {
    if (rel.endsWith("lib/design-system.test.mjs")) continue;
    const text = await readFile(new URL(rel, dir), "utf8");
    if (/var\(--(rule-soft|dim|row-hover)\)/.test(text)) users.push(rel);
  }

  assert.deepEqual(
    users.sort(),
    ["app/dashboard/page.tsx", "app/dashboard/pr/[number]/page.tsx"],
    "a file outside the dashboard surface now uses a token only declared on it",
  );

  // And every file on that list still mounts the wrapper that declares them.
  // This is the decision the comment above demands, taken rather than skipped:
  // the receipt screen reuses the dashboard's BLOCK_HEADING verbatim (--dim on
  // its provenance sub-label) and earns the token by mounting its own
  // .dashboard-surface, not by being added here as an exemption. Asserting it
  // for EVERY entry rather than for the first is what keeps the second file
  // from weakening the pin.
  for (const rel of users) {
    const source = await readFile(new URL(rel, dir), "utf8");
    assert.match(
      source,
      /className="dashboard-surface/,
      `${rel} uses a surface-scoped token without mounting the surface`,
    );
  }
});

test("the dark palette never redeclares a token the dashboard surface pins", async () => {
  // Doug, PR 102, reader:theme-inheritance-assumption. The light pinning works
  // because .dashboard-surface redeclares these custom properties on the
  // dashboard's own wrapper, and an inherited value is the weakest source a
  // custom property can have. The previously pinned case was the literal
  // `.dark` selector gaining `dashboard-surface`; this widens it to the whole
  // mechanism — ANY rule under .dark that sets one of these tokens on a
  // descendant would win where inheritance does not.
  const css = await readFile(cssUrl, "utf8");
  const darkStart = css.search(/(?:^|\n)\.dark[^{]*\{/);
  assert.ok(darkStart >= 0, "globals.css lost its .dark block");

  // Every rule from the .dark block onward whose selector mentions .dark.
  const rules = [...css.slice(darkStart).matchAll(/(^|\n)([^{}\n][^{}]*)\{([^}]*)\}/g)];
  const darkRules = rules.filter(([, , selector]) => /\.dark\b/.test(selector));
  assert.ok(darkRules.length > 0, "no .dark rule found — the scan is vacuous");

  for (const [, , selector, body] of darkRules) {
    assert.equal(
      /--(rule-soft|dim|row-hover)\s*:/.test(body),
      false,
      `a .dark rule (${selector.trim()}) redeclares a dashboard-surface token`,
    );
    assert.equal(
      selector.includes("dashboard-surface"),
      false,
      `a .dark rule (${selector.trim()}) claims the dashboard surface`,
    );
  }
});

test("the per-PR disclosure fails open where :has() is unsupported", async () => {
  // Doug, PR 102, reader:css-only-state-loss. The collapse is `display: none`
  // undone by a `:has()` rule. Declared unconditionally, an engine without
  // `:has()` applies the hiding and never applies the rule that reverses it —
  // every earlier verdict hidden permanently, with no control on the page able
  // to reveal them, and the ledger silently under-reporting its own history
  // while looking complete.
  //
  // Pinned because the fix is invisible in every environment that HAS `:has()`,
  // which is every environment this suite and CI run in: deleting the @supports
  // wrapper leaves all tests green and the bug fully back. Verified.
  const css = code(await readFile(cssUrl, "utf8"));

  const supports = css.match(/@supports\s+selector\(:has\(\*\)\)\s*\{([\s\S]*?)\n\}/);
  assert.ok(supports, "the :has() collapse is no longer behind an @supports guard");
  assert.match(supports[1], /\.pr-history\s*\{[^}]*display:\s*none/);

  // …and it must not ALSO be declared outside the guard, which would restore
  // the unconditional hiding while leaving the guard in place as decoration.
  const outside = css.replace(/@supports[\s\S]*?\n\}/g, "");
  assert.equal(
    /\.pr-history\s*\{[^}]*display:\s*none/.test(outside),
    false,
    ".pr-history is hidden outside the @supports guard — the fallback is dead",
  );

  // Where it is unsupported the affordance is withdrawn, so no caret claims a
  // collapsed state it cannot produce.
  assert.match(css, /@supports\s+not\s+selector\(:has\(\*\)\)\s*\{[\s\S]*?\.pr-disclosure\s*\{[^}]*display:\s*none/);
});
