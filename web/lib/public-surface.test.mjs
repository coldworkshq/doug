// Pins for the public surfaces that shipped in #101/#106 and then sat
// undocumented, unreachable on a phone, or described as if they did not
// exist. Source-text pins, not render tests (house rule).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// None of these reads depend on another's result — run them concurrently
// rather than paying 12 sequential round trips.
const [header, landing, queue, loading, intro, rest, mcp, changelog, llms, nav, about] =
  await Promise.all([
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

test("about page exists, wears the shared chrome, and is reachable from the header", () => {
  assert.match(header, /href="\/about"/);
  assert.match(about, /<SiteHeader/);
  assert.equal(about.includes('className="dark'), false);
});

test("about page tells the naming story and wires the photo gallery to a real path", () => {
  assert.match(about, /Saint Bernard/);
  assert.match(about, /\/about\/doug\//);
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
