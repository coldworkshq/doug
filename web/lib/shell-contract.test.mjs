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
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const [landing, config, rail, slots, overview, guards, dougPage, signIn, header, memory, workspace, sidebar, pager, docsNav, receipt, queue, scoreboard, adr34, adr19, adr06, gcp] = await Promise.all([
  readFile(new URL("../public/landing.html", import.meta.url), "utf8"),
  readFile(new URL("../next.config.ts", import.meta.url), "utf8"),
  readFile(new URL("../components/dashboard-rail.tsx", import.meta.url), "utf8"),
  readFile(new URL("../components/overview-slots.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/dashboard/overview/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/dashboard/guards/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/doug/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/sign-in/route.ts", import.meta.url), "utf8"),
  readFile(new URL("../components/site-header.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/dashboard/memory/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("./workspace.ts", import.meta.url), "utf8"),
  readFile(new URL("../components/docs/docs-sidebar.tsx", import.meta.url), "utf8"),
  readFile(new URL("../components/docs/docs-pager.tsx", import.meta.url), "utf8"),
  readFile(new URL("./docs-nav.ts", import.meta.url), "utf8"),
  readFile(new URL("../app/dashboard/pr/[number]/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/queue/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/scoreboard/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../../docs/decisions/ADR-0034-the-web-app-serves-coldworks-dev-and-reads-the-registry-over-a-versioned-public-contract.md", import.meta.url), "utf8"),
  readFile(new URL("../../docs/decisions/ADR-0019-the-deep-read-is-a-per-repository-setting.md", import.meta.url), "utf8"),
  readFile(new URL("../../docs/decisions/ADR-0006-doug-does-not-depend-on-lema.md", import.meta.url), "utf8"),
  readFile(new URL("../../api/deploy/gcp.sh", import.meta.url), "utf8"),
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
  // The scoreboard link sits in the Reviews row: the same wrapper element
  // holds both links, as siblings, never one nested in the other.
  const rowStart = rail.lastIndexOf("<div", rail.indexOf("Reviews</Link>"));
  const rowEnd = rail.indexOf("</div>", rowStart);
  const row = rail.slice(rowStart, rowEnd);
  assert.match(row, /Reviews<\/Link>/);
  assert.match(row, /href="\/scoreboard"/);
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

test("Guards is one code path: the mapping decides the read, the reader decides the tenant, one state drives the render", () => {
  assert.match(guards, /const mapping = resolveGuardsMapping\(installationId\)/);
  assert.match(guards, /getRegistrySnapshot\(\{ expectTenant: mapping\.tenant \}\)/);
  assert.equal(guards.includes("tenant_id ==="), false, "the tenant check has one owner, the reader");
  assert.match(guards, /state\.kind === "unmapped"/);
  assert.match(guards, /state\.kind === "unknown"/);
  assert.match(guards, /state\.kind === "snapshot"/);
  assert.match(guards, /<StateChip kind="later" subject="guards" \/>/);
  assert.match(guards, /href="\/docs\/audit"/);
  assert.match(guards, /section="guards"/);
  assert.equal(guards.includes("Promote"), false, "no promotion affordance");
  assert.equal(/have not run/.test(guards), false, "the chip states the subtraction claim, not a bare have-not-run line");
  // A malformed mapping env is a chip and a log line, never a throw into the render.
  assert.equal(guards.includes("engineTenantFor("), false);
  assert.equal(overview.includes("engineTenantFor("), false);
  assert.match(overview, /resolveGuardsMapping\(connection\.installation_id\)/);
  assert.match(overview, /getRegistrySnapshot\(\{ expectTenant: mapping\.tenant \}\)/);
});

test("the shell's screens share one prelude and one route chip", () => {
  for (const [name, source] of [["overview", overview], ["guards", guards], ["memory", memory]]) {
    assert.match(source, /await loadWorkspace\(\)/, `${name} carries its own prelude`);
    assert.match(source, /ROUTE_CHIP/, `${name} carries its own route chip`);
    assert.equal(source.includes("withAuth("), false, `${name} reads the session itself`);
  }
  assert.match(workspace, /console\.error\("doug: connections read failed/);
  assert.match(overview, /console\.error\(`doug: overview \$\{what\} read failed`/);
});

test("the Overview says 500+ over a full page, never a total", () => {
  assert.match(overview, /reviewedSlot\(runs, SESSION_RUNS_LIMIT\)/);
});

test("every workspace entry lands on the Overview, and the receipt returns into the workspace", () => {
  assert.match(signIn, /returnTo: "\/dashboard\/overview"/);
  assert.match(receipt, /href="\/dashboard\/overview"/);
  assert.match(receipt, /← reviews/);
  assert.equal(receipt.includes("← runs"), false);
  assert.equal(receipt.includes("DougLogo"), false);
});

test("Doug's public surfaces carry their own names under the product's root metadata", () => {
  assert.match(queue, /title: "Queue — Doug reviews"/);
  assert.match(scoreboard, /title: "Scoreboard — Doug reviews"/);
});

test("the audit docs are external to the docs shell: last in order, plain anchors, never a Link", () => {
  assert.match(docsNav, /external\?: true;/);
  const groups = [...docsNav.matchAll(/name: "([^"]+)"/g)].map((m) => m[1]);
  assert.equal(groups.at(-1), "The audit");
  assert.match(sidebar, /p\.external \? \(\s*<a/);
  assert.match(pager, /next && next\.external \? \(/);
  assert.match(pager, /<a\s+href=\{next\.href\}/);
});

test("the door and the audit docs carry a short shared cache; the deploy env survives a second mapping", () => {
  assert.match(config, /source: "\/",\s*headers: \[\{ key: "Cache-Control"/);
  assert.match(config, /source: "\/docs\/audit\/:path\*",\s*headers: \[\{ key: "Cache-Control"/);
  assert.match(gcp, /--set-env-vars "\^;\^DOUG_API_URL=/);
  assert.match(gcp, /COLDWORKS_REGISTRY_URL=\$\{COLDWORKS_REGISTRY_URL:-\};/);
  assert.equal(gcp.includes("COLDWORKS_REGISTRY_URL:-https://coldworks.dev"), false, "the default would point the read at ourselves after the cutover");
});

test("ADR-0034 amends ADR-0019 and ADR-0006, and both are marked on both sides", () => {
  assert.match(adr34, /^amends: ADR-0006, ADR-0019$/m);
  assert.match(adr34, /The marketing header's plain `Dashboard` link is retired, amending\s+ADR-0019/);
  assert.match(adr19, /^amended_by: ADR-0020, ADR-0034$/m);
  assert.match(adr19, /Amended by ADR-0034/);
  assert.match(adr06, /^amended_by: ADR-0022, ADR-0034$/m);
});

test("the public header wears the door's nav and the Coldworks wordmark", () => {
  assert.match(header, /label: "Doug reviews"/);
  assert.match(header, /Coldworks\s*<\/Link>/);
  assert.equal(header.includes("DougLogo"), false);
});

test("every nav target is distinct and exists on the door", () => {
  const hrefs = [...header.matchAll(/\{ href: "([^"]+)", label: "[^"]+" \}/g)].map((m) => m[1]);
  assert.ok(hrefs.length >= 6, "the nav list was not read");
  assert.equal(new Set(hrefs).size, hrefs.length, `two labels on one target: ${hrefs.join(" ")}`);
  for (const href of hrefs.filter((h) => h.startsWith("/#"))) {
    assert.match(landing, new RegExp(`id="${href.slice(2)}"`), `${href} names no element on the door`);
  }
  assert.match(header, /key=\{l\.href\}/, "the key is the target, so a duplicate fails loud in development");
});

test("the door is the rewrite: no root page may shadow it", async () => {
  // Next checks pages before an array-form rewrite, so a future app/page.tsx
  // would silently take the apex from landing.html. Fail here instead.
  assert.match(config, /\{ source: "\/", destination: "\/landing\.html" \}/);
  await assert.rejects(access(new URL("../app/page.tsx", import.meta.url)), "app/page.tsx exists and shadows the door");
});

test("the ledger is the terminus of every non-runs state; it never bounces back to the workspace", async () => {
  // loadWorkspace sends a failed connections read and every front-door state
  // but `runs` to /dashboard, which renders those states in place. A redirect
  // from /dashboard into the workspace would be a loop for those users.
  const ledger = await readFile(new URL("../app/dashboard/page.tsx", import.meta.url), "utf8");
  const targets = [...ledger.matchAll(/redirect\(\s*"([^"]+)"/g)].map((m) => m[1]);
  assert.ok(targets.length > 0, "the ledger's redirects were not read");
  assert.deepEqual([...new Set(targets)], ["/sign-in"]);
  assert.match(workspace, /if \(connections === null\) redirect\("\/dashboard"\)/);
  assert.match(workspace, /if \(door\.state !== "runs"\) redirect\("\/dashboard"\)/);
});
