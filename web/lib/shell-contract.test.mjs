// Pins for the one shell (ADR-0034): the door, the rail, the Overview, the
// Guards page. Source-text pins, not render tests (house rule). Each protects
// a ruling in the design lock:
//   the door at / is the Coldworks landing with its day-one copy (T1, O2);
//   the rail is Overview, Reviews, Repositories, Memory, Guards, with the
//   scoreboard one click from Reviews (T7);
//   a figure never renders without its sentence at its own size (O1);
//   Guards is one code path decided by the mapping and the tenant (T2).
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [landing, config, rail, slots, overview, guards, dougPage, signIn, header] = await Promise.all([
  readFile(new URL("../public/landing.html", import.meta.url), "utf8"),
  readFile(new URL("../next.config.ts", import.meta.url), "utf8"),
  readFile(new URL("../components/dashboard-rail.tsx", import.meta.url), "utf8"),
  readFile(new URL("../components/overview-slots.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/dashboard/overview/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/dashboard/guards/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/doug/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/sign-in/route.ts", import.meta.url), "utf8"),
  readFile(new URL("../components/site-header.tsx", import.meta.url), "utf8"),
]);

test("the door is the Coldworks landing, served by a rewrite, with Doug's page one link in", () => {
  // verify_registry_surface.sh criterion 10, moved here with the landing.
  assert.match(landing, /Use AI to/);
  assert.match(landing, /href="\/sign-in"/);
  assert.match(landing, /href="\/dashboard\/overview"/);
  assert.match(config, /\{ source: "\/", destination: "\/landing\.html" \}/);
  assert.equal(existsSync(new URL("../app/page.tsx", import.meta.url)), false, "a page at / would shadow the rewrite");
  assert.match(dougPage, /export const metadata/);
  assert.match(signIn, /returnTo: "\/dashboard\/overview"/);
});

test("the day-one copy: every sentence the shell made false is gone", () => {
  for (const gone of [
    "No accounts yet",
    "Accounts do not exist yet",
    "no account exists yet",
    "Cited 6 times",
    "read the same record",
    "public registry behind it",
    'href="/login"',
    'href="/overview"',
    "Open the registry surface",
    "/docs/cli.html",
  ]) {
    assert.equal(landing.includes(gone), false, gone);
  }
  // O2: the hero claims no single shared record; the page's own framing stays.
  assert.match(landing, /each work from the record of what your team decides/);
  assert.match(landing, /One record of what your team decides/);
  assert.match(landing, /Open the workspace/);
  assert.match(landing, /href="\/docs\/audit\/cli"/);
});

test("the rail is Overview, Reviews, Repositories, Memory, Guards, in that order, under the Coldworks wordmark", () => {
  const order = [
    'href="/dashboard/overview"',
    "Reviews</Link>",
    ">Repositories</Link>",
    'href="/dashboard/memory"',
    'href="/dashboard/guards"',
    "Evidence <small",
    'href="/dashboard/settings"',
  ];
  const positions = order.map((m) => rail.indexOf(m));
  assert.ok(positions.every((p) => p !== -1), "every rail entry is present");
  for (let i = 1; i < positions.length; i++) assert.ok(positions[i] > positions[i - 1], order[i]);
  assert.match(rail, /Coldworks\s*<span/);
  assert.equal(rail.includes("DougLogo"), false);
  assert.match(rail, /aria-current=\{section === "overview" \? "page" : undefined\}/);
  assert.match(rail, /aria-current=\{section === "guards" \? "page" : undefined\}/);
});

test("the published miss rate is one click from Reviews and from Doug's page", () => {
  // The scoreboard link sits in the Reviews row, a sibling of the Reviews
  // link, never nested inside it.
  const reviews = rail.indexOf("Reviews</Link>");
  const scoreboard = rail.indexOf('href="/scoreboard"');
  assert.ok(reviews > 0 && scoreboard > reviews && scoreboard - reviews < 400, "scoreboard is beside Reviews");
  assert.equal(/<Link[^>]*>[^<]*<Link/.test(rail), false, "a link nested in a link");
  assert.match(dougPage, /href="\/scoreboard"/);
  // And from the door's own Doug section.
  assert.match(landing, /published on the scoreboard/);
});

test("O1: a figure and its sentence share one type size, are siblings in one slot, and never use a tooltip", () => {
  assert.match(slots, /const SLOT_TYPE = "/);
  assert.match(slots, /data-slot=\{slot\.key\}/);
  assert.match(
    slots,
    /<span className=\{`\$\{SLOT_TYPE\} font-semibold text-foreground`\}>\{slot\.figure\}<\/span>\s*<span className=\{`\$\{SLOT_TYPE\} text-muted-foreground`\}>\{slot\.sentence\}<\/span>/,
  );
  assert.equal(slots.includes("title="), false, "a sentence in a tooltip can be cropped out of a screenshot");
  assert.equal(/import .*Tooltip/.test(slots), false, "a tooltip component would hide the sentence behind a hover");
  assert.match(slots, /<StateChip/);
  assert.match(overview, /<OverviewSlots slots=\{slots\} \/>/);
  assert.match(overview, /section="overview"/);
  assert.equal([...overview.matchAll(/<OverviewSlots/g)].length, 1, "one component renders every installation");
});

test("Guards is one code path: the mapping decides the read, the tenant decides the render", () => {
  assert.match(guards, /const mapping = engineTenantFor\(connection\.installation_id\)/);
  assert.match(guards, /if \(mapping\) \{\s*registry = await getRegistrySnapshot\(\)/);
  assert.match(guards, /registry\.snapshot\.tenant_id === mapping \? registry\.snapshot : null/);
  assert.match(guards, /<StateChip kind="later" subject="guards" \/>/);
  assert.match(guards, /href="\/docs\/audit"/);
  assert.match(guards, /section="guards"/);
  assert.equal(guards.includes("Promote"), false, "no promotion affordance");
  assert.equal(/have not run/.test(guards), false, "the chip states the subtraction claim, not a bare have-not-run line");
});

test("the public header wears the door's nav and the Coldworks wordmark", () => {
  assert.match(header, /label: "Doug reviews"/);
  assert.match(header, /Coldworks\s*<\/Link>/);
  assert.equal(header.includes("DougLogo"), false);
});
