// Pins for the public surfaces that shipped in #101/#106 and then sat
// undocumented, unreachable on a phone, or described as if they did not
// exist. Source-text pins, not render tests (house rule).
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

// None of these reads depend on another's result — run them concurrently
// rather than paying 12 sequential round trips.
const [
  header,
  landing,
  queue,
  loading,
  intro,
  rest,
  mcp,
  changelog,
  llms,
  nav,
  about,
  layout,
  quickstart,
  risk,
  wrong,
  report,
  readme,
  apiReadme,
] = await Promise.all([
  readFile(new URL("../components/site-header.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/queue/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/loading.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/docs/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/docs/rest-api/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/docs/mcp/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/docs/changelog/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../public/llms.txt", import.meta.url), "utf8"),
  readFile(new URL("./docs-nav.ts", import.meta.url), "utf8"),
  readFile(new URL("../app/about/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/docs/quickstart/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/docs/risk-routing/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/docs/what-doug-gets-wrong/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/docs/report/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../../README.md", import.meta.url), "utf8"),
  readFile(new URL("../../api/README.md", import.meta.url), "utf8"),
]);

/** The field of ONE record, or null.
 *
 *  These files are arrays of `{ key: "value", … }` object literals. Matching
 *  `anchor …lazy… field` across the whole source reads as a per-record
 *  assertion and is not one: the lazy span crosses record boundaries, so it
 *  is satisfied by the NEXT record's field and passes on the exact
 *  regression it exists to catch. That is not hypothetical — flipping the
 *  receipt row to `meta: "planned"` left this suite green until this helper
 *  landed, and the sibling row only failed because it happened to sit last.
 *  Slicing to the record first makes the assertion positional-order-proof.
 */
function fieldOf(source, anchorKey, anchorValue, field) {
  const start = source.indexOf(`${anchorKey}: ${JSON.stringify(anchorValue)}`);
  if (start === -1) return null;
  const next = source.indexOf(`${anchorKey}: "`, start + 1);
  const record = source.slice(start, next === -1 ? undefined : next);
  return record.match(new RegExp(`${field}: "([^"]*)"`))?.[1] ?? null;
}

test("the header's public routes survive below the sm breakpoint", () => {
  // Desktop nav is `hidden sm:flex`. If that is the only iterator over
  // NAV_LINKS, a phone cannot reach Docs, Scoreboard, or Queue from the
  // chrome — and the request that produced this pin came from a phone.
  assert.match(header, /hidden sm:flex/);
  assert.match(header, /<details className="[^"]*sm:hidden/);
  const maps = header.match(/NAV_LINKS\.map/g) ?? [];
  assert.equal(
    maps.length,
    2,
    "desktop nav and the mobile disclosure must both iterate NAV_LINKS",
  );
});

test("nav order puts the live product surfaces before reference material, About last", () => {
  // Scoreboard and Queue are the live showcase surfaces, Docs is reference
  // material — those three are NAV_LINKS entries. GitHub and About are each
  // hardcoded separately after the NAV_LINKS.map, in that order, so they're
  // matched by their literal JSX (not the `href: "…"` object-literal shape
  // NAV_LINKS entries use). Regressing this ordering is exactly the kind of
  // silent reshuffle a diff review wouldn't catch without a pin.
  const order = [
    'href: "/scoreboard"',
    'href: "/queue"',
    'href: "/docs"',
    "href={GITHUB_REPO_URL}",
    'href="/about"',
  ];
  const positions = order.map((marker) => header.indexOf(marker));
  assert.ok(
    positions.every((p) => p !== -1),
    "every nav link must be present in the header",
  );
  for (let i = 1; i < positions.length; i++) {
    assert.ok(
      positions[i] > positions[i - 1],
      `${order[i]} must come after ${order[i - 1]} in the header`,
    );
  }
});

test("the links NOT carried by NAV_LINKS still exist in BOTH navs", () => {
  // NAV_LINKS entries get mobile reachability for free — the test above pins
  // that both navs iterate it. GitHub and About are hardcoded per-nav
  // instead, so they have no such guarantee: deleting either one from the
  // <details> block leaves a link that is unreachable on a phone, which is
  // the exact bug class this file was opened to catch. Verified by mutation:
  // dropping the mobile About link passed all 15 tests before this pin.
  // Anchor on `<details className=` — the docblock above the component also
  // says the word "<details>" in prose, and matching that instead silently
  // slices the desktop region down to just the imports, which fails for a
  // reason that has nothing to do with the nav.
  const detailsAt = header.indexOf("<details className=");
  const detailsEnd = header.indexOf("</details>");
  assert.ok(detailsAt !== -1 && detailsEnd > detailsAt, "mobile disclosure must exist");
  const desktopNav = header.slice(0, detailsAt);
  const mobileNav = header.slice(detailsAt, detailsEnd);

  for (const [label, marker] of [
    ["GitHub", "href={GITHUB_REPO_URL}"],
    ["About", 'href="/about"'],
  ]) {
    assert.ok(desktopNav.includes(marker), `${label} must be in the desktop nav`);
    assert.ok(mobileNav.includes(marker), `${label} must be in the mobile disclosure`);
  }
});

test("about page exists, wears the shared chrome, and is reachable from the header", () => {
  assert.match(header, /href="\/about"/);
  assert.match(about, /<SiteHeader/);
  assert.equal(about.includes('className="dark'), false);
});

test("about page tells the naming story, and every gallery photo actually exists", () => {
  assert.match(about, /Saint Bernard/);

  // Matching the `/about/doug/` prefix in source text proved nothing: it
  // stayed true for weeks while the directory held only a README and the
  // page shipped four broken-image icons. Resolve each src against
  // web/public and stat it, so a missing file or a typo'd extension fails
  // here instead of in a visitor's browser.
  const srcs = [...about.matchAll(/src: "(\/about\/doug\/[^"]+)"/g)].map((m) => m[1]);
  assert.equal(srcs.length, 4, "expected four gallery photos in PHOTOS");
  for (const src of srcs) {
    const onDisk = new URL(`../public${src}`, import.meta.url);
    assert.ok(existsSync(onDisk), `${src} is referenced but not in web/public`);
  }
});

test("the landing miss-rate panel points at the live scoreboard", () => {
  assert.match(landing, /Published miss rate/);
  assert.match(landing, /href="\/scoreboard"/);
});

test("the queue follows the site theme and shares the public header", () => {
  // Forced-dark + .glass made /queue the one public page that did not
  // look like Doug. SiteHeader carries Docs/Scoreboard/Queue; this file
  // must not re-hide them behind a private nav.
  assert.equal(queue.includes('className="dark'), false);
  assert.match(queue, /<SiteHeader/);
  assert.equal(queue.includes("glass"), false);
});

test("the root loading skeleton is chrome-neutral", () => {
  // web/app/loading.tsx also covers /dashboard, which has its own shell.
  // Public SiteHeader here flashes Sign in / Docs / Queue on a signed-in
  // ledger. "fetching the queue" invents a page this skeleton is not.
  assert.equal(loading.includes('from "@/components/site-header"'), false);
  assert.equal(loading.includes("<SiteHeader"), false);
  assert.equal(loading.includes("fetching the queue"), false);
});

test("the queue footnoted the cleared band, not just the score", () => {
  // experience.md: cleared = not deeply inspected; on one research repo
  // the band was not safer than merging blind. A footer that only explains
  // the score leaves the product claim unstated on the surface that makes it.
  assert.match(queue, /not safer than merging blind/);
});

test("docs intro does not claim the public surface is only the CLI", () => {
  assert.equal(intro.includes("Today the public surface is the"), false);
  assert.match(intro, /\/scoreboard/);
  assert.match(intro, /\/queue/);
  // experience.md: banned verb "caught". Routing language, not capture.
  assert.equal(intro.includes("caught"), false);
  assert.match(intro, /would have routed/);
});

test("REST API docs name the live showcase routes and do not pretend none of this is live", () => {
  assert.equal(rest.includes("none of this is live"), false);
  assert.match(rest, /\/v1\/showcase\/queue/);
  assert.match(rest, /\/v1\/showcase\/scoreboard/);
  // Honesty contract: per-author-type rates are never published. Banning the
  // literal "per author type" pinned the DELETION of the July sketch's
  // wording and nothing else — both files now write the phrase hyphenated,
  // so the ban could not fire on a reintroduction spelled the way the file
  // already spells it. Pin the disclaimer instead: republishing the rates
  // means deleting or contradicting this sentence, and both fail here.
  assert.match(rest, /Per-author-type rates are not published/);
  assert.doesNotMatch(rest, /(?:published|publish(?:es|ing)?) [^.]*?per[-\s]author[-\s]type/i);
  assert.equal(rest.includes("api.doug.dev"), false);
});

test("REST API docs do not mark live tenant routes as planned or preview", () => {
  // GET /v1/queue and GET /v1/prs/:number/receipt are token/session-gated
  // and shipped. Tenant scoreboard is the remaining planned surface.
  assert.equal(fieldOf(rest, "name", "GET /v1/queue", "meta"), "live");
  assert.equal(
    fieldOf(rest, "name", "GET /v1/prs/:number/receipt", "meta"),
    "live",
  );
  assert.equal(fieldOf(rest, "name", "GET /v1/showcase/queue", "meta"), "live");
  assert.equal(
    fieldOf(rest, "name", "GET /v1/showcase/scoreboard", "meta"),
    "live",
  );
  assert.equal(fieldOf(rest, "name", "GET /v1/scoreboard", "meta"), "planned");
  assert.equal(rest.includes("Tenant REST is still planned"), false);
  assert.equal(rest.includes("Tenant REST is still the planned"), false);
  assert.match(rest, /\$DOUG_API_URL/);
  assert.match(rest, /SAMPLE — empty-ledger snapshot/);
});

test("REST API sits in Coming up as preview, not planned — showcase is live", () => {
  assert.equal(fieldOf(nav, "href", "/docs/rest-api", "status"), "preview");
});

test("the MCP sketch does not invent a garden that has no rows", () => {
  // 412 episodes · 87 repos trained the wrong expectation on a preview
  // that is gated on min-n adjudications. Empty is the product.
  assert.equal(mcp.includes("87 repos"), false);
  assert.equal(mcp.includes("412 episodes"), false);
});

test("the changelog records the instrument becoming visible", () => {
  assert.match(changelog, /2026-08-13/);
  assert.match(changelog, /scoreboard/i);
});

test("about page does not call Doug pre-build", () => {
  // The App path is live on this repo. "pre-build" on a header-linked page
  // is the same class of publicly false maturity claim as README "Pre-build".
  assert.equal(/pre-build/i.test(about), false);
});

test("root layout meta does not say scoring is from metadata", () => {
  // Shipped path reads the diff (ADR-0004). OG/meta must not re-derive a
  // different scoring story from the landing hero.
  assert.equal(layout.includes("from metadata"), false);
});

test("landing rule 03 does not claim the miss rate is already published", () => {
  assert.equal(landing.includes("Publishes its miss rate"), false);
  assert.match(landing, /Will publish its miss rate/);
});

test("MCP garden is planned, not preview — no server exists to preview", () => {
  assert.equal(fieldOf(nav, "href", "/docs/mcp", "status"), "planned");
  assert.match(mcp, /status="planned"/);
  assert.equal(mcp.includes("tool · preview"), false);
  assert.match(llms, /MCP — Pattern Garden \(PLANNED/);
});

test("quickstart and llms.txt require Python 3.14, matching the API package", () => {
  assert.equal(quickstart.includes("3.12"), false);
  assert.match(quickstart, /3\.14/);
  assert.equal(llms.includes("3.12"), false);
  assert.match(llms, /3\.14/);
});

test("risk-routing does not present the live scorer as model-free", () => {
  assert.equal(risk.includes("no model in the hot path"), false);
});

test("what Doug gets wrong uses the current findings-log counts", () => {
  assert.equal(wrong.includes("Roughly half"), false);
  assert.equal(wrong.includes("12 rows today"), false);
  assert.equal(llms.includes("Roughly half"), false);
});

test("the report does not invent a misses-by-PR list the CLI does not print", () => {
  assert.equal(report.includes("misses are listed by PR number"), false);
  assert.equal(report.includes('"misses"'), false);
});

test("README is not the pre-build stub era", () => {
  assert.equal(readme.includes("Pre-build"), false);
  assert.equal(readme.includes("HMAC-verified stub"), false);
});

test("llms.txt matches the live showcase surface, not the July sketch", () => {
  assert.equal(llms.includes("public surface today is the backtest CLI"), false);
  assert.match(llms, /\/v1\/showcase\/scoreboard/);
  // Same reasoning as the rest-api pin above: disclaimer, not spelling.
  assert.match(llms, /Per-author-type rates are not published/);
  assert.doesNotMatch(llms, /(?:published|publish(?:es|ing)?) [^.]*?per[-\s]author[-\s]type/i);
  assert.match(llms, /tenant queue and receipt live/);
  assert.match(llms, /Planned: tenant-scoped GET \/v1\/scoreboard/);
  assert.equal(llms.includes("Planned: tenant-scoped GET /v1/queue"), false);
});

test("what Doug gets wrong does not claim every log row is backfill", () => {
  // 123 of 135 rows are prospective. A callout that still says every row is
  // backfill contradicts the rail on the same page.
  assert.equal(wrong.includes("Every row in the log today is backfill"), false);
  assert.match(wrong, /123 prospective/);
});

test("llms.txt does not present the July probe as the live scorer, or hotspots as a live learner", () => {
  // ADR-0004: reader is the live path when enabled. ADR-0012: probe AUC is
  // that probe, not a measurement of the shipped 100k-char reader.
  assert.equal(llms.includes("not in the shipped scorer"), false);
  assert.equal(llms.includes("research, not the shipped scorer"), false);
  assert.match(llms, /static hotspot/);
  assert.equal(llms.includes("learned per repo from a rolling window"), false);
  // JSON is always written; --output only chooses the path.
  assert.equal(llms.includes("also write the full JSON report"), false);
});

test("docs intro does not offer a self-serve GitHub App install", () => {
  assert.equal(intro.includes("sign in to install"), false);
  assert.match(intro, /not a self-serve product/);
});

test("MCP copy does not wear preview language for a server that does not exist", () => {
  assert.equal(mcp.includes("In training."), false);
  assert.equal(intro.includes("[in training]"), false);
  assert.equal(landing.includes("preview · no dates promised"), false);
  assert.match(landing, /planned · no dates promised/);
});

test("API README does not say the webhook scores inline through features.py", () => {
  assert.equal(apiReadme.includes("the webhook both call this"), false);
  assert.equal(apiReadme.includes("path the webhook will"), false);
  assert.match(apiReadme, /enqueues a review job/);
});

test("quickstart does not offer pip next to a uv-only 3.14 pin", () => {
  assert.equal(quickstart.includes("or pip"), false);
});

test("risk-routing meta does not call live hotspots learned", () => {
  assert.equal(risk.includes("learned hotspots"), false);
});
