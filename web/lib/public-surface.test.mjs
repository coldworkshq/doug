// Pins for the public surfaces that shipped in #101/#106 and then sat
// undocumented, unreachable on a phone, or described as if they did not
// exist. Source-text pins, not render tests (house rule).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const header = await readFile(
  new URL("../components/site-header.tsx", import.meta.url),
  "utf8",
);
const landing = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
const queue = await readFile(new URL("../app/queue/page.tsx", import.meta.url), "utf8");
const loading = await readFile(new URL("../app/loading.tsx", import.meta.url), "utf8");
const intro = await readFile(new URL("../app/docs/page.tsx", import.meta.url), "utf8");
const rest = await readFile(
  new URL("../app/docs/rest-api/page.tsx", import.meta.url),
  "utf8",
);
const mcp = await readFile(new URL("../app/docs/mcp/page.tsx", import.meta.url), "utf8");
const changelog = await readFile(
  new URL("../app/docs/changelog/page.tsx", import.meta.url),
  "utf8",
);
const llms = await readFile(new URL("../public/llms.txt", import.meta.url), "utf8");
const nav = await readFile(new URL("./docs-nav.ts", import.meta.url), "utf8");

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
  assert.equal(loading.includes("SiteHeader"), false);
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
  // Banned: per-author-type miss rates (honesty contract) and an invented host.
  assert.equal(rest.includes("per author type"), false);
  assert.equal(rest.includes("api.doug.dev"), false);
});

test("REST API docs do not mark live tenant routes as planned or preview", () => {
  // GET /v1/queue and GET /v1/prs/:number/receipt are token/session-gated
  // and shipped. Tenant scoreboard is the remaining planned surface.
  assert.match(rest, /name: "GET \/v1\/queue"[\s\S]*?meta: "live"/);
  assert.match(rest, /name: "GET \/v1\/prs\/:number\/receipt"[\s\S]*?meta: "live"/);
  assert.match(rest, /name: "GET \/v1\/scoreboard"[\s\S]*?meta: "planned"/);
  assert.equal(rest.includes("Tenant REST is still planned"), false);
  assert.equal(rest.includes("Tenant REST is still the planned"), false);
  assert.match(rest, /\$DOUG_API_URL/);
  assert.match(rest, /SAMPLE — empty-ledger snapshot/);
});

test("REST API sits in Coming up as preview, not planned — showcase is live", () => {
  assert.match(nav, /href: "\/docs\/rest-api"[\s\S]*?status: "preview"/);
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
  assert.equal(llms.includes("per author type"), false);
  assert.match(llms, /tenant queue and receipt live/);
  assert.match(llms, /Planned: tenant-scoped GET \/v1\/scoreboard/);
  assert.equal(llms.includes("Planned: tenant-scoped GET /v1/queue"), false);
});
