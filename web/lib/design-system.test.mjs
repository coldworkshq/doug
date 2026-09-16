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

const LIGHT = ":root,\n.dashboard-surface,\n.surface-tokens";
const DARK = ".dark,\n.dark .dashboard-surface,\n.dark .surface-tokens";

/** The custom properties declared by the block whose whole selector list is
 *  `selector`, keyed without their dashes. A `var(--x)` value resolves against
 *  the same block, because the palette refers to itself (--destructive reads
 *  --flag); any other value, such as a gradient, stays as written. */
function tokens(css, selector) {
  const label = selector.replaceAll("\n", " ");
  const at = css.indexOf(`\n${selector} {`);
  assert.ok(at >= 0, `the ${label} block is gone`);
  const body = code(css.slice(at, css.indexOf("\n}", at)));
  const raw = Object.fromEntries([...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
  const resolve = (value, seen) => {
    const ref = /^var\(--([\w-]+)\)$/.exec(value);
    if (!ref) return value;
    assert.ok(raw[ref[1]] !== undefined && !seen.has(ref[1]), `var(--${ref[1]}) does not resolve inside ${label}`);
    return resolve(raw[ref[1]], new Set([...seen, ref[1]]));
  };
  return Object.fromEntries(Object.entries(raw).map(([name, value]) => [name, resolve(value, new Set())]));
}

// Colour arithmetic for the tests that compute the palette's figures. The
// figures used to be typed into globals.css, and two of them reproduced under
// no formula (#210), so they are computed here from the hexes instead.

function rgb(hex) {
  assert.match(hex, /^#[0-9a-f]{6}$/i, `${hex} is not a six-digit hex colour`);
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
}

const linear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);

/** The WCAG 2 contrast ratio between two sRGB colours. */
function contrast(a, b) {
  const luminance = (hex) => {
    const [r, g, bl] = rgb(hex).map(linear);
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** `ink` at `alpha` over `ground`, composited in sRGB the way a browser paints
 *  a translucent fill such as `bg-flag/15`. */
function over(ink, alpha, ground) {
  const [i, g] = [rgb(ink), rgb(ground)];
  const mixed = g.map((c, k) => Math.round((c * (1 - alpha) + i[k] * alpha) * 255));
  return `#${mixed.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

/** CIE Lab (D65) from linear sRGB. */
function lab([r, g, b]) {
  const x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b;
  const y = 0.2126729 * r + 0.7151522 * g + 0.072175 * b;
  const z = 0.0193339 * r + 0.119192 * g + 0.9503041 * b;
  const f = (t) => (t > (6 / 29) ** 3 ? Math.cbrt(t) : t / (3 * (6 / 29) ** 2) + 4 / 29);
  const [fx, fy, fz] = [f(x / 0.95047), f(y), f(z / 1.08883)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

/** CIEDE2000, as specified by Sharma, Wu and Dalal (2005). */
function deltaE2000([L1, a1, b1], [L2, a2, b2]) {
  const rad = Math.PI / 180;
  const C1 = Math.hypot(a1, b1);
  const C2 = Math.hypot(a2, b2);
  const Cb = (C1 + C2) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)));
  const a1p = (1 + G) * a1;
  const a2p = (1 + G) * a2;
  const C1p = Math.hypot(a1p, b1);
  const C2p = Math.hypot(a2p, b2);
  const hue = (bb, ap) => (ap === 0 && bb === 0 ? 0 : (((Math.atan2(bb, ap) / rad) % 360) + 360) % 360);
  const h1p = hue(b1, a1p);
  const h2p = hue(b2, a2p);
  const dL = L2 - L1;
  const dC = C2p - C1p;
  let dh = 0;
  if (C1p * C2p !== 0) {
    dh = h2p - h1p;
    if (dh > 180) dh -= 360;
    else if (dh < -180) dh += 360;
  }
  const dH = 2 * Math.sqrt(C1p * C2p) * Math.sin((dh / 2) * rad);
  const Lb = (L1 + L2) / 2;
  const Cbp = (C1p + C2p) / 2;
  let hb = h1p + h2p;
  if (C1p * C2p !== 0) {
    if (Math.abs(h1p - h2p) <= 180) hb = (h1p + h2p) / 2;
    else hb = h1p + h2p < 360 ? (h1p + h2p + 360) / 2 : (h1p + h2p - 360) / 2;
  }
  const T =
    1 -
    0.17 * Math.cos((hb - 30) * rad) +
    0.24 * Math.cos(2 * hb * rad) +
    0.32 * Math.cos((3 * hb + 6) * rad) -
    0.2 * Math.cos((4 * hb - 63) * rad);
  const dTheta = 30 * Math.exp(-(((hb - 275) / 25) ** 2));
  const Rc = 2 * Math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7));
  const Sl = 1 + (0.015 * (Lb - 50) ** 2) / Math.sqrt(20 + (Lb - 50) ** 2);
  const Sc = 1 + 0.045 * Cbp;
  const Sh = 1 + 0.015 * Cbp * T;
  const Rt = -Math.sin(2 * dTheta * rad) * Rc;
  return Math.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh));
}

/** Reference pairs from Sharma, Wu and Dalal (2005): Lab, Lab, ΔE2000. */
const SHARMA_2005 = [
  [[50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425],
  [[50, 0, 0], [50, -1, 2], 2.3669],
  [[50, 2.5, 0], [50, 0, -2.5], 4.3065],
  [[50, 2.5, 0], [73, 25, -18], 27.1492],
  [[60.2574, -34.0099, 36.2677], [60.4626, -34.1751, 39.4387], 1.2644],
];

/** Machado, Oliveira and Fernandes (2009), severity 1.0, applied in linear RGB. */
const MACHADO_2009 = {
  deuteranopia: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
  protanopia: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
};

/** A colour as it is seen, in CIE Lab: in normal vision, or under a simulated dichromacy. */
function seen(hex, vision) {
  const v = rgb(hex).map(linear);
  if (vision === "normal") return lab(v);
  return lab(MACHADO_2009[vision].map((row) => Math.min(1, Math.max(0, row[0] * v[0] + row[1] * v[1] + row[2] * v[2]))));
}

const separation = (a, b, vision) => deltaE2000(seen(a, vision), seen(b, vision));

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
  // Intent: the accent and the brand colours are chrome — navigation, focus,
  // hover, marks, display type — and never a .data-* colour. How far the
  // accent sits from --flag is measured in the separation test below.
  const css = code(await readFile(cssUrl, "utf8"));
  const dataRules = css.match(/\.data-[\w-]+[^{]*\{[^}]*\}/g) ?? [];
  // Non-vacuity guard only. How MANY data colours there may be is the
  // previous test's property; asserting it here too would make a third-colour
  // regression fail two tests and discriminate neither.
  assert.ok(dataRules.length >= 2, "no .data-* rules found — this test would pass vacuously");
  for (const rule of dataRules) {
    assert.equal(/--(coolant|molten|ember|ring|accent|thermal)\b/.test(rule), false, `data rule borrows chrome: ${rule}`);
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

test("the data-colour rule survives the port, and names where its figures are computed", async () => {
  // Intent: the comment IS the spec. A port that drops it leaves the next
  // reader with two hex values and no reason not to add a third.
  //
  // It no longer carries a figure (#210). "ΔE 6.1" reproduced under no
  // formula, its correction to 9.2 was about to go stale with the next
  // palette, and a number in prose is a number nothing recomputes. The rule
  // now names the test below that measures the distance, and a figure typed
  // back into it fails here.
  const css = await readFile(cssUrl, "utf8");
  const at = css.indexOf("  /* The two data colours.");
  assert.ok(at >= 0, "the data-colour rule is gone");
  const rule = css.slice(at, css.indexOf("*/", at));
  assert.match(rule, /NEVER add a third/);
  assert.match(rule, /never paint a verdict in\s+the chrome accent/);
  assert.match(rule, /computed from web's stylesheet by\s+web\/lib\/design-system\.test\.mjs/);
  assert.equal(/ΔE\S*\s*\d/.test(rule), false, "a separation figure is typed into the rule again");
  assert.match(css, /Coverage is a magnitude, not a judgement/);
});

test("the surface-scoped value is pinned exactly, in BOTH themes", async () => {
  // Intent (plan A5.6, controller ruling): dashboard.module.css carried values
  // with NO equivalent in the palette, and the ruling was that they live at an
  // exact hex inside the scoped surface block — never substituted for globals'
  // nearest neighbour, never left dangling.
  //
  // The ruling forbids SUBSTITUTION — swapping in a palette neighbour and
  // calling the difference close enough — not correction. The pin moves with
  // a corrected value rather than being loosened to a range.
  //
  // Both themes are pinned, because the console follows the toggle: a
  // light-only value is a light tint across a dark table, and nothing in this
  // suite renders to catch it.
  //
  // If a value here ever gains a real palette home, delete it from the block
  // AND from this list in the same commit; do not loosen the assertion.
  // ADR-0035 did exactly that for --dim and --rule-soft: the Coldworks palette
  // gave both a home as --faint and --line, because the docs set their faint
  // text and hairlines from the same two values. --row-hover is what remains.
  const css = await readFile(cssUrl, "utf8");
  const scope = (selector) => {
    const at = css.indexOf(selector);
    assert.ok(at >= 0, `the ${selector.trim()} scope block is gone`);
    return css.slice(at, css.indexOf("\n}", at));
  };

  const light = scope("\n.dashboard-surface {");
  assert.match(light, /--row-hover:\s*#f5f7f8/);

  const dark = scope("\n.dark .dashboard-surface {");
  assert.match(dark, /--row-hover:\s*#14252c/);

  // …and the coverage ramp stays OUT of both. It is a palette token
  // (--cov-track / --cov-fill), because the utilities that read it are under a
  // character-identical lockstep with console's and so could not hold two
  // per-theme values themselves. A copy inside this scope would be a second
  // source of truth for the ramp. The same holds for the two tokens that moved
  // to the palette.
  for (const [label, body] of [["light", light], ["dark", dark]]) {
    assert.equal(body.includes("--cov-track"), false, `${label} surface re-declares the coverage ramp`);
    assert.equal(body.includes("--cov-fill"), false, `${label} surface re-declares the coverage ramp`);
    assert.equal(/--(dim|rule-soft):/.test(code(body)), false, `${label} surface re-declares a token the palette owns`);
  }
});

test("the surface-scoped tokens are used only where the surface is mounted", async () => {
  // Doug, PR 102, reader:css-token-scope-coupling. --row-hover is declared
  // ONLY on .dashboard-surface. Anything using it outside that wrapper resolves
  // it to nothing and silently loses its hover tint — no build error, no test
  // failure, and nothing renders in this suite to catch it.
  //
  // So the blast radius is pinned instead. Extracting a piece of the dashboard
  // into components/ trips this test, which is the moment to decide — move the
  // token to :root, or pass the colour in, or mount the surface around the new
  // home. Do NOT just add the file here unless it genuinely renders inside
  // .dashboard-surface.
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
    // neither theme may leave `var(--row-hover)` undeclared.
    if (rel.endsWith(".test.mjs")) continue;
    const text = await readFile(new URL(rel, dir), "utf8");
    if (/var\(--row-hover\)/.test(text)) users.push(rel);
  }

  // The receipt, settings, memory, overview, and guards pages were on this
  // list for --dim, and left it when ADR-0035 moved --dim to the palette as
  // --faint. Each still mounts its own .dashboard-surface for its route chrome.
  assert.deepEqual(
    users.sort(),
    ["app/dashboard/page.tsx", "components/dashboard-rail.tsx"],
    "a file outside the dashboard surface now uses a token only declared on it",
  );

  // THE RAIL IS THE CASE THE COMMENT ABOVE WARNED ABOUT — a piece of the
  // dashboard extracted into components/. The decision it forces was taken
  // rather than waved through: the rail cannot mount the surface, because it is
  // a CHILD of the wrapper, so "move the token to :root" or "pass the colour
  // in" were the alternatives. Both were refused — the rail is dashboard
  // chrome and nothing else renders it — and the guarantee is kept in the shape
  // that actually protects it: every file that renders the rail must mount the
  // surface. A future page that imports it without the wrapper fails here,
  // which is the regression this test exists to catch.
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

test("every colour token holds a colour in both themes, and the one gradient is read only by .bg-thermal", async () => {
  // Doug, PR 102, reader:theme-inheritance-assumption, then ADR-0020. A token
  // read AS A COLOUR — `text-[var(--x)]`, `border-[var(--x)]`,
  // `color-mix(in srgb, var(--x) 35%, transparent)` — is invalid CSS when it
  // holds a gradient, and the browser drops the declaration without a word: a
  // focus ring stops rendering, with no build error and no failing test. The
  // previous palette's accent held a gradient in dark mode, and every focus
  // ring in the console depended on nobody reading it there.
  //
  // So every colour token resolves to a hex in both themes, and the brand's
  // gradient lives in --thermal, which only .bg-thermal reads.
  const css = await readFile(cssUrl, "utf8");
  const COLOURS = [
    "coolant", "coolant-soft", "molten", "molten-soft", "ember", "ember-soft",
    "ink-2", "faint", "line", "line-2", "paper-2", "flag", "clear",
    "background", "foreground", "card", "muted", "muted-foreground",
    "accent", "accent-foreground", "border", "input", "ring", "destructive",
  ];
  for (const [theme, selector] of [["light", LIGHT], ["dark", DARK]]) {
    const palette = tokens(css, selector);
    for (const name of COLOURS) {
      assert.match(palette[name] ?? "", /^#[0-9a-f]{6}$/i, `${theme}: --${name} holds "${palette[name]}", which is not a colour`);
    }
    assert.match(palette.thermal ?? "", /^linear-gradient\(/, `${theme}: --thermal is not the thermal gradient`);
  }
  const readers = [...code(css).matchAll(/([^{}]+)\{[^{}]*var\(--thermal\)[^{}]*\}/g)].map((m) => m[1].trim());
  assert.deepEqual(readers, [".bg-thermal"], "a rule other than .bg-thermal reads the gradient");
});

test("every ink clears AA on the grounds it renders on, in both themes", async () => {
  // THE PALETTE CARRIES NO FIGURES (ADR-0035, #210). The previous palette
  // typed its ratios into comments, and two of them did not reproduce. These
  // are computed from the hexes globals.css declares, so a palette change that
  // breaks one fails here instead of going stale in prose.
  //
  // Each ink is checked on the grounds it is drawn on. --faint is the smallest
  // chrome text and renders on the page, the card, and a hovered row, never on
  // a muted chip. The data colours are also checked on their own chip tints,
  // where they are hardest to read: band-chip.tsx paints them on a 9% tint, and
  // the queue on 15% (flag) and 10% (clear), over either the card or the page.
  const css = await readFile(cssUrl, "utf8");
  const AA = 4.5;
  const themes = [
    ["light", tokens(css, LIGHT), tokens(css, ".dashboard-surface")],
    ["dark", tokens(css, DARK), tokens(css, ".dark .dashboard-surface")],
  ];
  const INKS = {
    foreground: ["background", "card", "muted", "row-hover"],
    "muted-foreground": ["background", "card", "muted", "row-hover"],
    faint: ["background", "card", "row-hover"],
    coolant: ["background", "card", "muted"],
    "ink-2": ["background", "card"],
    flag: ["background", "card", "muted", "row-hover"],
    clear: ["background", "card", "muted", "row-hover"],
  };
  const TINTS = [["flag", [0.09, 0.15]], ["clear", [0.09, 0.1]]];
  for (const [theme, palette, surface] of themes) {
    const grounds = { ...palette, "row-hover": surface["row-hover"] };
    for (const [ink, on] of Object.entries(INKS)) {
      for (const ground of on) {
        const ratio = contrast(palette[ink], grounds[ground]);
        assert.ok(ratio >= AA, `${theme}: --${ink} on --${ground} is ${ratio.toFixed(2)}:1, under AA`);
      }
    }
    for (const [ink, alphas] of TINTS) {
      for (const alpha of alphas) {
        for (const ground of ["card", "background"]) {
          const ratio = contrast(palette[ink], over(palette[ink], alpha, palette[ground]));
          assert.ok(ratio >= AA, `${theme}: --${ink} on its own ${Math.round(alpha * 100)}% tint over --${ground} is ${ratio.toFixed(2)}:1, under AA`);
        }
      }
    }
    for (const [ink, ground] of [["accent-foreground", "accent"], ["primary-foreground", "primary"], ["secondary-foreground", "secondary"]]) {
      const ratio = contrast(palette[ink], palette[ground]);
      assert.ok(ratio >= AA, `${theme}: --${ink} on --${ground} is ${ratio.toFixed(2)}:1, under AA`);
    }
    // Molten is display type only — the headline words on /doug and /about —
    // where AA asks 3:1. Small text in molten is the flag token's job.
    for (const ground of ["background", "card"]) {
      const ratio = contrast(palette.molten, palette[ground]);
      assert.ok(ratio >= 3, `${theme}: --molten on --${ground} is ${ratio.toFixed(2)}:1, under AA for large text`);
    }
    // A row divider stays lighter than the edge of the table it sits in, and a
    // hovered row is a visible step off the card.
    assert.ok(contrast(palette.line, palette.card) < contrast(palette.border, palette.card), `${theme}: --line outweighs --border`);
    assert.ok(contrast(surface["row-hover"], palette.card) >= 1.03, `${theme}: --row-hover is no visible step off the card`);
  }
  // The floating bar is light in both themes and declares its own inks.
  const bar = tokens(css, ".site-bar");
  for (const [ink, ground] of [["foreground", "background"], ["muted-foreground", "background"], ["ink-2", "background"], ["accent-foreground", "accent"], ["primary-foreground", "primary"]]) {
    const ratio = contrast(bar[ink], bar[ground]);
    assert.ok(ratio >= AA, `.site-bar: --${ink} on --${ground} is ${ratio.toFixed(2)}:1, under AA`);
  }
});

test("the floating bar declares every colour token its markup paints with", async () => {
  // The bar does not invert with the theme, so a token it does NOT declare
  // keeps the PAGE's value: in dark mode that is a near-white ink on this
  // white bar, at 1.86:1. It happened to --ink-2 the day the nav took the
  // door's grammar, and the loop above could not catch it — that loop checks
  // the tokens someone remembered to list.
  //
  // This reads the markup instead. Every Tailwind colour utility in the header
  // and in the theme toggle it cannot pass classes into, whose name is a
  // palette token, must be declared inside the .site-bar block.
  const css = await readFile(cssUrl, "utf8");
  const light = tokens(css, LIGHT);
  const bar = ruleBody(code(css), ".site-bar") ?? "";
  const sources = await Promise.all(
    ["../components/site-header.tsx", "../components/theme-toggle.tsx"].map((rel) =>
      readFile(new URL(rel, import.meta.url), "utf8"),
    ),
  );
  const used = new Set();
  for (const src of sources) {
    for (const [, name] of src.matchAll(/\b(?:text|bg|border|fill|stroke|outline|ring|decoration|from|via|to)-([a-z0-9-]+)/g)) {
      if (name in light) used.add(name);
    }
  }
  assert.ok(used.size >= 6, `only ${used.size} palette tokens found in the bar's markup — the scan is broken`);
  const undeclared = [...used].filter((name) => !new RegExp(`--${name}\\s*:`).test(bar)).sort();
  assert.deepEqual(undeclared, [], "the bar paints with a token it does not declare, so dark mode keeps the page's value");
});

test("the data pair and the chrome accent stay separable in normal vision and under deuteranopia and protanopia", async () => {
  // The rule in the ported utilities block — two data colours, and no verdict
  // painted in chrome — is only as good as the distance between the colours it
  // names, so the distance is measured here rather than typed there (#210).
  //
  // ΔE2000 on sRGB to CIE Lab (D65), with dichromacy simulated by the Machado
  // (2009) matrices at full severity in linear RGB. The model is named because
  // the figures this file used to pin reproduced under no model anyone wrote
  // down.
  //
  // THE FLOORS. Under deuteranopia and protanopia, flag against clear must stay
  // at least as separable as the palette ADR-0035 replaced, whose weakest
  // figures were 11.6 under deuteranopia (dark) and 8.2 under protanopia
  // (light). In normal vision the floor is 40, far past the distance at which
  // two colours are mistaken for each other; the Coldworks light pair sits a
  // little closer there than the pair it replaced, and this floor does not
  // pretend otherwise. Chrome against flag has to clear a floor that palette
  // failed: its accent sat 9.2 from its flag in normal vision and 2.3 under
  // deuteranopia, the closeness the rule's own comment warned about.
  for (const [lab1, lab2, want] of SHARMA_2005) {
    const got = deltaE2000(lab1, lab2);
    assert.ok(Math.abs(got - want) < 1e-4, `CIEDE2000 gives ${got.toFixed(4)} where Sharma et al. give ${want}`);
  }
  const FLOORS = {
    data: { normal: 40, deuteranopia: 11.6, protanopia: 8.2 },
    chrome: { normal: 20, deuteranopia: 10, protanopia: 10 },
  };
  const clears = (a, b, floors) => Object.entries(floors).every(([vision, floor]) => separation(a, b, vision) >= floor);
  // The chrome floor discriminates: the previous palette's accent against its
  // flag fails it, so a return to that pair cannot pass.
  assert.equal(clears("#b0430d", "#bf3125", FLOORS.chrome), false, "the chrome floor admits the accent it exists to refuse");

  const css = await readFile(cssUrl, "utf8");
  for (const [theme, selector] of [["light", LIGHT], ["dark", DARK]]) {
    const palette = tokens(css, selector);
    for (const vision of ["normal", "deuteranopia", "protanopia"]) {
      const data = separation(palette.flag, palette.clear, vision);
      assert.ok(data >= FLOORS.data[vision], `${theme}: --flag against --clear is ΔE2000 ${data.toFixed(1)} in ${vision}, under ${FLOORS.data[vision]}`);
      const chrome = separation(palette.coolant, palette.flag, vision);
      assert.ok(chrome >= FLOORS.chrome[vision], `${theme}: --coolant against --flag is ΔE2000 ${chrome.toFixed(1)} in ${vision}, under ${FLOORS.chrome[vision]}`);
      // The accent is measured against the brand's display colour too. In dark
      // --flag IS --molten, byte for byte, which Doug read as the rule
      // weakening (360a71f, reader:design-token-collision): it is deliberate,
      // because both are the brand's heat and a second orange a shade away
      // reads as a mistake. The rule is about chrome, so chrome is what has to
      // stay far from both.
      const display = separation(palette.coolant, palette.molten, vision);
      assert.ok(display >= FLOORS.chrome[vision], `${theme}: --coolant against --molten is ΔE2000 ${display.toFixed(1)} in ${vision}, under ${FLOORS.chrome[vision]}`);
    }
  }
});

test("no font or token from Doug's look survives the move to the Coldworks look", async () => {
  // ADR-0035 retired Doug's look: Bricolage Grotesque and Geist, the rust
  // accent and its gradient, the slate sheen, the dot grid, and the glow. Each
  // is named here so none comes back through a copied component or a stale
  // utility. Comments are stripped, because a file that explains why a name
  // left may say the name.
  const retired = /Bricolage|Geist|--iridescent|--brand-wash|--sheen|--surface-dot|--atmosphere|display-condensed|\b(?:text|bg)-(?:iridescent|sheen)\b|var\(--(?:dim|rule-soft)\)/;
  const dir = new URL("../", import.meta.url);
  const files = new Set();
  async function walk(rel) {
    for (const entry of await readdir(new URL(rel, dir), { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      const next = `${rel}${entry.name}${entry.isDirectory() ? "/" : ""}`;
      if (entry.isDirectory()) await walk(next);
      else if (/\.(tsx?|css)$/.test(entry.name)) files.add(next);
    }
  }
  await walk("app/");
  await walk("components/");
  const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const survivors = [];
  for (const rel of files) {
    const found = strip(await readFile(new URL(rel, dir), "utf8")).match(retired);
    if (found) survivors.push(`${rel}: ${found[0]}`);
  }
  assert.deepEqual(survivors, [], "a retired font or token is back");
  assert.ok(files.has("app/globals.css") && files.size >= 40, `the scan only found ${files.size} files — the walk is broken`);
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

test("nothing rendered anywhere paints a one-theme hex, except where that is the point", async () => {
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
  // THE SCAN WALKS THE TREE; it does not read a list. The first version of
  // this test named eleven files, and Doug was right about it (PR 213,
  // reader:broad-visual-regression): components/doug-logo.tsx was not among
  // them and was carrying the PREVIOUS palette's ink and accent into every
  // surface that renders the mark. A hardcoded list can only catch the files
  // whoever wrote it already suspected, which is the opposite of what a guard
  // is for.
  //
  // Comments are stripped first: run-spine and coverage-ruler still NAME their
  // old hexes while explaining why they no longer use them, and a pin that
  // fired on prose would push the next author into deleting the explanation to
  // get green.
  const dir = new URL("../", import.meta.url);
  const sources = [];
  async function walk(rel) {
    for (const entry of await readdir(new URL(rel, dir), { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      const next = `${rel}${entry.name}${entry.isDirectory() ? "/" : ""}`;
      if (entry.isDirectory()) await walk(next);
      else if (/\.tsx?$/.test(entry.name)) sources.push(next);
    }
  }
  await walk("app/");
  await walk("components/");

  /** JS/TSX with comments removed. Deliberately not a parser: a `//` inside a
   *  string would over-strip, and over-stripping this scan can only produce a
   *  false PASS on a line that is already comment-shaped. */
  const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  // ONE EXEMPTION, BECAUSE THE COLOUR IS DELIBERATELY NOT THEMED — not
  // because the file is inconvenient to fix. It is asserted to still earn it
  // below, so the exemption cannot outlive its reason.
  //
  //  - The Doug mark is a logo. It carries its own white ground, which is why
  //    it has always rendered correctly on the dark public pages, and a dog
  //    that changes colour with the page is not a brand mark. Its colours are
  //    the palette's molten and ink, written into the file (#214, ADR-0035).
  //
  // The docs' code panels were a second exemption until 2026-09-15. Their
  // fixed terminal ink moved into components/docs/docs.module.css with the
  // rest of the docs' look, so no component paints a literal colour to draw a
  // terminal, and the next test holds the panel to ink in both themes.
  const BRAND_MARK = "components/doug-logo.tsx";
  const exempt = new Set([BRAND_MARK]);

  const offenders = [];
  for (const rel of sources) {
    if (rel.endsWith(".test.mjs") || exempt.has(rel)) continue;
    const source = await readFile(new URL(rel, dir), "utf8");
    for (const hex of strip(source).match(/#[0-9a-fA-F]{6}\b/g) ?? []) {
      offenders.push(`${rel}: ${hex}`);
    }
  }
  assert.deepEqual(
    offenders,
    [],
    "a rendered file paints a literal colour, which cannot invert with the theme",
  );

  // The exemption still earns itself. Without this, "exempt" becomes a place
  // to put a file that simply failed.
  const mark = await readFile(new URL(BRAND_MARK, dir), "utf8");
  assert.match(mark, /<svg/, "the brand-mark exemption no longer points at a mark");
  assert.match(
    mark,
    /fill="#fff"/,
    "the mark no longer carries its own ground, so it can no longer claim to work on any surface",
  );

  // And the walk actually walked. Without this, a rename that empties `sources`
  // turns the whole assertion into a tautology.
  assert.ok(sources.length >= 40, `the scan only found ${sources.length} files — the walk is broken`);
});

const docsCssUrl = new URL("../components/docs/docs.module.css", import.meta.url);

/** Innermost rules of comment-free CSS as { selector, body }; an @media
 *  wrapper contributes the rules inside it, not itself. */
function cssRules(css) {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ selector: m[1].trim(), body: m[2] }));
}

test("the docs' code panels are ink in both themes, dark enough to read their own text", async () => {
  // A terminal that goes pale in light mode is not one; that is why the docs'
  // code samples were exempt from the scan above while their colours lived in
  // components. The panel reads --cw-ink-panel, both theme scopes declare it,
  // and the value must stay dark: the panel's own ink needs 7:1 on it. A
  // declaration that exists only inside a comment does not count.
  const css = code(await readFile(docsCssUrl, "utf8"));
  assert.match(ruleBody(css, ".code") ?? "", /background:\s*var\(--cw-ink-panel\)/);
  for (const selector of [".root", ":global(.dark) .root"]) {
    const scope = ruleBody(css, selector);
    assert.ok(scope, `the ${selector} token scope is gone`);
    const panel = scope.match(/--cw-ink-panel:\s*(#[0-9a-f]{6})\b/i)?.[1];
    const ink = scope.match(/--cw-ink-panel-fg:\s*(#[0-9a-f]{6})\b/i)?.[1];
    assert.ok(panel && ink, `${selector} leaves the panel or its ink undeclared`);
    const ratio = contrast(panel, ink);
    assert.ok(ratio >= 7, `${selector}: ink ${ink} on panel ${panel} is ${ratio.toFixed(2)}:1, a pale terminal`);
  }
});

test("the docs' token scope never re-points a site token it also reads", async () => {
  // Doug's read of c17ec52, reader:css-variable-cycle. Before ADR-0035 the docs
  // pointed --foreground at --cw-fg; now --cw-fg reads --foreground, and
  // declaring both on .root would be a cycle. CSS resolves a cycle by voiding
  // BOTH properties, so the docs would lose their ink with no error anywhere.
  // The re-points that remain are one-way: they read --cw- tokens that read
  // palette tokens.
  const css = code(await readFile(docsCssUrl, "utf8"));
  const root = ruleBody(css, ".root");
  assert.ok(root, "the docs token scope is gone");
  const value = (name) => new RegExp(`--${name}:\\s*([^;]+);`).exec(root)?.[1]?.trim();
  for (const [, name, raw] of root.matchAll(/--([\w-]+):\s*([^;]+);/g)) {
    const read = /^var\(--([\w-]+)\)$/.exec(raw.trim())?.[1];
    if (!read) continue;
    const back = /^var\(--([\w-]+)\)$/.exec(value(read) ?? "")?.[1];
    assert.notEqual(back, name, `--${name} reads --${read}, which reads --${name} back: a cycle voids both`);
  }
  // …and the two that would cycle are not declared here at all.
  for (const [token, through] of [["foreground", "--cw-fg"], ["muted-foreground", "--cw-muted"]]) {
    assert.equal(value(token), undefined, `.root re-points --${token}, which ${through} reads`);
  }
});

test("the docs module paints theme colours only through its tokens", async () => {
  // The hex scan above reads components, not stylesheets. In docs.module.css
  // a literal colour belongs in the two token scopes, or on the code panel,
  // whose ink is fixed in both themes, or in the selection highlight's white
  // text. Anywhere else it paints one theme's colour into the other.
  const rules = cssRules(code(await readFile(docsCssUrl, "utf8")));
  assert.ok(rules.length > 50, `the rule walk found only ${rules.length} rules`);
  const allowed = /^(\.root|:global\(\.dark\) \.root|\.root ::selection|\.code b|\.codebar|\.t[A-Z]\w*|\.copy|\.copy:hover)$/;
  const offenders = rules
    .filter((r) => /#[0-9a-f]{3,8}\b/i.test(r.body) && !allowed.test(r.selector))
    .map((r) => r.selector);
  assert.deepEqual(offenders, [], "a docs rule paints a literal colour outside the token scopes and the code panel");
});

test("the floating nav bar's light surface is a token scope, and it re-substitutes the ink", async () => {
  // THE BAR IS LIGHT IN BOTH THEMES (components/site-header.tsx), and the
  // mechanism is a token scope — the same one .dashboard-surface uses. Two
  // ways to break it, both invisible in whichever theme you happened to be
  // developing in:
  //
  //  1. A TOKEN THE BAR READS IS LEFT UNDECLARED. It then resolves to the
  //     PAGE's value, which in dark mode is a colour picked to be seen against
  //     the dark page — put on a white bar. `--muted-foreground` alone is six
  //     nav links, the menu summary and the theme toggle going pale-on-white.
  //
  //  2. `text-foreground` IS DROPPED FROM THE BAR, and this is the subtle one.
  //     `body` sets `color: var(--foreground)`, which is substituted AT THE
  //     BODY: descendants inherit the resolved colour, not the variable, so
  //     re-declaring --foreground inside the bar does nothing for anything
  //     that merely inherits. The wordmark is the only control in the bar that
  //     names no ink of its own, and without this class it inherits the page's
  //     near-white into a near-white pill. Verified by deleting the class: the
  //     token scope is still perfectly correct and the wordmark disappears.
  const css = await readFile(cssUrl, "utf8");
  const at = css.indexOf("\n.site-bar {");
  assert.ok(at >= 0, "the .site-bar token scope is gone — the bar follows the theme again");
  const scope = css.slice(at, css.indexOf("\n}", at));

  // Every token the bar's own utilities read. Adding a utility to the header
  // that reads a token absent from this list is the regression above; adding
  // it here without declaring it fails on the next line.
  for (const token of [
    "background", "foreground", "muted-foreground", "border",
    "accent", "accent-foreground", "primary", "primary-foreground", "ring",
  ]) {
    assert.match(
      scope,
      new RegExp(`--${token}:\\s*#[0-9a-f]{3,6}`, "i"),
      `.site-bar leaves --${token} to the page's theme, on a surface that does not follow it`,
    );
  }

  const header = await readFile(new URL("../components/site-header.tsx", import.meta.url), "utf8");
  const bar = header.match(/className="site-bar[^"]*"/)?.[0];
  assert.ok(bar, "nothing in site-header.tsx mounts the site-bar scope");
  assert.match(
    bar,
    /\btext-foreground\b/,
    "the bar mounts the token scope but never re-substitutes --foreground; inherited ink does not follow a re-declared token",
  );
});
