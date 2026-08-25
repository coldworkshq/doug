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
  // Intent: a score column that does not align is unreadable at 38px rows.
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
  //
  // THE RULE IS PINNED HERE; THE NUMBER IN IT IS DISPUTED — see issue #210.
  // "ΔE 6.1" does not reproduce from the values the sentence describes: the
  // pair measured ΔE2000 10.8 / ΔE76 16.7 before the 2026-08-24 palette shift
  // and 9.2 after. The rule it justifies (chrome is never a data colour) is
  // sound and is why this assertion stays. Correcting the digits means editing
  // two stylesheets and this line together, which is #210's job, not a silent
  // fix inside an unrelated commit.
  const css = await readFile(cssUrl, "utf8");
  assert.match(css, /fails CVD separation against --flag at ΔE 6\.1/);
  assert.match(css, /Coverage is a magnitude, not a judgement/);
});

test("the surface-scoped values are pinned exactly, in BOTH themes", async () => {
  // Intent (plan A5.6, controller ruling): dashboard.module.css carried values
  // with NO equivalent in the palette, and the ruling was that they live at an
  // exact hex inside the scoped surface block — never substituted for globals'
  // nearest neighbour, never left dangling.
  //
  // The ruling forbids SUBSTITUTION — swapping in a palette neighbour and
  // calling the difference close enough — not correction. They have now been
  // corrected twice, and the pin moved with them rather than being loosened to
  // a range: once when --dim shipped at 2.3:1 and --rule-soft at 1.11:1, and
  // again when the palette raised --border and gave the divider room it had
  // never had. globals.css carries the arithmetic.
  //
  // THE SECOND BLOCK IS NEW AND IS THE POINT. While the console was pinned
  // light, one declaration was enough. Now that it follows the toggle, a
  // light-only --rule-soft is a near-white rule across a #14161a table — a
  // defect that is invisible to every other test here, because nothing in this
  // suite renders. Both directions are pinned so neither can rot.
  //
  // If a value here ever gains a real palette home, delete it from the block
  // AND from this list in the same commit; do not loosen the assertion.
  const css = await readFile(cssUrl, "utf8");
  const scope = selector => {
    const at = css.indexOf(selector);
    assert.ok(at >= 0, `the ${selector.trim()} scope block is gone`);
    return css.slice(at, css.indexOf("\n}", at));
  };

  const light = scope("\n.dashboard-surface {");
  assert.match(light, /--rule-soft:\s*#dbe0e5/);
  assert.match(light, /--dim:\s*#666c73/);
  assert.match(light, /--row-hover:\s*#f6f7f8/);

  const dark = scope("\n.dark .dashboard-surface {");
  assert.match(dark, /--rule-soft:\s*#2a2f36/);
  assert.match(dark, /--dim:\s*#858d96/);
  assert.match(dark, /--row-hover:\s*#23272d/);

  // …and the coverage ramp stays OUT of both. It is a palette token now
  // (--cov-track / --cov-fill), because the utilities that read it are under a
  // character-identical lockstep with console's and so could not hold two
  // per-theme values themselves. A copy inside this scope would be a second
  // source of truth for the ramp.
  for (const [label, body] of [["light", light], ["dark", dark]]) {
    assert.equal(body.includes("--cov-track"), false, `${label} surface re-declares the coverage ramp`);
    assert.equal(body.includes("--cov-fill"), false, `${label} surface re-declares the coverage ramp`);
  }
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
    // Tests NAME these tokens while pinning them and render nothing at all, so
    // scanning them would demand a .dashboard-surface in a file that draws
    // none. This is the same exemption the CHILD_OF_SURFACE scan below already
    // makes, applied at the same breadth rather than to one file by name —
    // dashboard-contract.test.mjs earned it the moment it started pinning that
    // neither theme may leave `var(--rule-soft)` undeclared.
    if (rel.endsWith(".test.mjs")) continue;
    const text = await readFile(new URL(rel, dir), "utf8");
    if (/var\(--(rule-soft|dim|row-hover)\)/.test(text)) users.push(rel);
  }

  assert.deepEqual(
    users.sort(),
    [
      "app/dashboard/page.tsx",
      "app/dashboard/pr/[number]/page.tsx",
      "app/dashboard/settings/page.tsx",
      "components/dashboard-rail.tsx",
    ],
    "a file outside the dashboard surface now uses a token only declared on it",
  );

  // And every file on that list still mounts the wrapper that declares them.
  // This is the decision the comment above demands, taken rather than skipped:
  // the receipt screen reuses the dashboard's BLOCK_HEADING verbatim (--dim on
  // its provenance sub-label) and earns the token by mounting its own
  // .dashboard-surface, not by being added here as an exemption. Asserting it
  // for EVERY entry rather than for the first is what keeps the second file
  // from weakening the pin.
  //
  // The settings page is the third, and took the same decision the same way:
  // it wears the ledger's route chrome (--dim on the /settings breadcrumb
  // row) and earns it by mounting its own .dashboard-surface. It is a
  // /dashboard route rendering the dashboard's own surface, not a component
  // lifted out of one.
  //
  // THE RAIL IS THE FOURTH AND IS THE CASE THE COMMENT ABOVE WARNED ABOUT — a
  // piece of the dashboard extracted into components/. The decision it forces
  // was taken rather than waved through: the rail cannot mount the surface,
  // because it is a CHILD of the wrapper, so "move the token to :root" or
  // "pass the colour in" were the alternatives. Both were refused — the rail
  // is dashboard chrome and nothing else renders it — and the guarantee is
  // kept in the shape that actually protects it: every file that renders the
  // rail must mount the surface. A future page that imports it without the
  // wrapper fails here, which is the regression this test exists to catch.
  const CHILD_OF_SURFACE = { "components/dashboard-rail.tsx": "<DashboardRail" };
  for (const rel of users) {
    const source = await readFile(new URL(rel, dir), "utf8");
    const tag = CHILD_OF_SURFACE[rel];
    if (!tag) {
      assert.match(
        source,
        /className="dashboard-surface/,
        `${rel} uses a surface-scoped token without mounting the surface`,
      );
      continue;
    }
    const mounts = [];
    for (const other of sources) {
      // Tests NAME the tag while pinning it; they do not render it. Scanning
      // them would demand a .dashboard-surface in a file that draws nothing.
      if (other === rel || other.endsWith(".test.mjs")) continue;
      const text = await readFile(new URL(other, dir), "utf8");
      if (text.includes(tag)) mounts.push({ other, text });
    }
    assert.ok(mounts.length > 0, `${rel} is rendered by nothing`);
    for (const { other, text } of mounts) {
      assert.match(
        text,
        /className="dashboard-surface/,
        `${other} renders ${rel}, which uses a surface-scoped token, without mounting the surface`,
      );
    }
  }
});

test("--iridescent is a COLOUR in every theme, and the gradient is a separate token", async () => {
  // Doug, PR 102, reader:theme-inheritance-assumption, inverted by the toggle.
  //
  // The old pin here said .dark must never redeclare a surface token, because
  // doing so would defeat the light pinning. That pin is obsolete: defeating
  // it is now the FEATURE, and lib/dashboard-contract.test.mjs pins the
  // mechanism instead. What replaces it is the defect that mechanism uncovered
  // and that nothing anywhere was guarding.
  //
  // .dark used to set `--iridescent: linear-gradient(...)`. That was harmless
  // only for as long as the console could not go dark, because the console is
  // the only place that reads the token AS A COLOUR — 30-odd call sites of
  // `text-[var(--iridescent)]`, `border-[var(--iridescent)]` and
  // `color-mix(in srgb, var(--iridescent) 35%, transparent)`. A gradient is
  // not a valid colour in any of them, so the declaration is dropped and the
  // focus ring simply stops rendering — no build error, no failing test, and
  // an invisible keyboard focus indicator, which is an accessibility
  // regression rather than a cosmetic one.
  //
  // So: --iridescent is a colour everywhere, and the gradient moved to
  // --brand-wash, which only background-clip:text ever reads.
  const css = await readFile(cssUrl, "utf8");

  const declarations = [...css.matchAll(/--iridescent:\s*([^;]+);/g)].map(m => m[1].trim());
  assert.ok(declarations.length >= 2, "expected --iridescent in both palette blocks");
  for (const value of declarations) {
    assert.match(value, /^#[0-9a-f]{6}$/i, `--iridescent holds "${value}", which is not a colour`);
  }

  // The gradient still exists — it is the brand — just under a name nothing
  // reads as a colour.
  const wash = [...css.matchAll(/--brand-wash:\s*([^;]+);/g)].map(m => m[1].trim());
  assert.ok(wash.some(v => v.startsWith("linear-gradient")), "the brand gradient was lost, not moved");

  // And the two utilities that want the gradient read the wash, never the
  // colour — the one direction that would silently reintroduce the bug.
  // Anchored on the rules, not on the palette comment that also names them.
  const ruleAt = css.indexOf("  .text-iridescent {");
  assert.ok(ruleAt >= 0, "the .text-iridescent utility is gone");
  const washBlock = css.slice(ruleAt, css.indexOf("}", css.indexOf("  .bg-iridescent {")));
  assert.match(washBlock, /background:\s*var\(--brand-wash\)/);
  assert.equal(
    washBlock.includes("var(--iridescent)"),
    false,
    ".text-iridescent/.bg-iridescent read the colour token again",
  );
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

test("nothing rendered on the console surface paints a one-theme hex", async () => {
  // THE DEFECT CLASS THE DARK TOGGLE CREATED, pinned so it cannot come back.
  //
  // While the console was pinned to light (RULING 1), a literal hex in a
  // className was defensible, and two files said so in as many words:
  // run-spine drew its nodes `bg-[#3d403c]` / `border-[#c9c6bd]` and
  // coverage-ruler hatched the never-read band in #c9c6bd, each above a
  // comment explaining that there was no dark variant to invent. Both were
  // correct at the time and both became wrong in the same commit — a
  // near-black dot on a near-black card, and a warm-beige hatch over #1e2127.
  //
  // The rule is a token or nothing. A hex cannot know what it is sitting on,
  // and NOTHING in this suite renders, so the failure is invisible until
  // somebody opens the page in the other theme. Comments are stripped first:
  // the two files above still NAME their old hexes while explaining why they
  // no longer use them, and a pin that fired on prose would push the next
  // author into deleting the explanation to get green.
  const dir = new URL("../", import.meta.url);
  const surface = [
    "app/dashboard/page.tsx",
    "app/dashboard/settings/page.tsx",
    "app/dashboard/pr/[number]/page.tsx",
    "components/dashboard-rail.tsx",
    "components/coverage-ruler.tsx",
    "components/run-spine.tsx",
    "components/census-panel.tsx",
    "components/flag-line-control.tsx",
    "components/threshold-gear.tsx",
    "components/band-chip.tsx",
    "components/score-strip.tsx",
  ];

  /** JS/TSX with comments removed. Deliberately not a parser: a `//` inside a
   *  string would over-strip, and over-stripping this scan can only produce a
   *  false PASS on a line that is already comment-shaped. */
  const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  const offenders = [];
  for (const rel of surface) {
    let source;
    try {
      source = await readFile(new URL(rel, dir), "utf8");
    } catch {
      // A file that moved is not this test's business to fail on, but a list
      // that has quietly emptied itself IS — see the vacuity guard below.
      continue;
    }
    for (const hex of strip(source).match(/#[0-9a-fA-F]{6}\b/g) ?? []) {
      offenders.push(`${rel}: ${hex}`);
    }
  }
  assert.deepEqual(
    offenders,
    [],
    "a console-surface file paints a literal colour, which cannot invert with the theme",
  );

  // The scan must actually be reading files. Without this, renaming every
  // entry on the list above turns the assertion into a tautology.
  const present = await Promise.all(
    surface.map((rel) =>
      readFile(new URL(rel, dir), "utf8").then(() => true, () => false),
    ),
  );
  assert.ok(
    present.filter(Boolean).length >= 8,
    "the surface file list has gone stale — most of these no longer exist",
  );
});

test("the console's dot grid does not ride on --border", async () => {
  // Doug would call this a coupling, and it cost a visible regression before
  // it was caught: the surface paints its paper texture with a radial-gradient
  // whose colour was `var(--border)`. That was invisible at --border's old
  // 1.23:1, and at the 1.43:1 the palette shift needed for item separation the
  // same rule turned a 20px dot grid across the whole viewport into noise.
  //
  // The two properties pull in opposite directions BY DEFINITION — a border
  // exists to be seen, a texture exists to be barely felt — so they must not
  // share a token, however similar the two values look on any given day.
  const css = await readFile(cssUrl, "utf8");
  // ruleBody escapes the selector itself, so this is passed raw. It matches
  // the paint rule rather than the palette block, because only the paint rule
  // has `.dashboard-surface` sitting directly against its brace.
  const surface = ruleBody(code(css), ".dashboard-surface");
  assert.ok(surface, "the .dashboard-surface paint block is gone");
  assert.match(surface, /background:\s*radial-gradient\(var\(--surface-dot\)/);
  assert.equal(
    /radial-gradient\(var\(--border\)/.test(surface),
    false,
    "the dot grid is painting with --border again",
  );

  // And the token it uses instead is declared in BOTH themes, or the grid
  // silently stops rendering in whichever one forgot.
  for (const [label, selector] of [["light", "\n.dashboard-surface {"], ["dark", "\n.dark .dashboard-surface {"]]) {
    const at = css.indexOf(selector);
    assert.ok(at >= 0, `the ${label} surface block is gone`);
    assert.match(css.slice(at, css.indexOf("\n}", at)), /--surface-dot:\s*#/, `${label} leaves --surface-dot undeclared`);
  }
});
