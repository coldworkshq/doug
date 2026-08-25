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
  findingsLog,
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
  readFile(new URL("../../docs/findings-log.jsonl", import.meta.url), "utf8"),
]);

/** The log's own shape, for the pins below.
 *
 *  Three designs were tried here and the third is the one that holds. A
 *  LITERAL ("123 prospective") cannot fail when the log grows, which is the
 *  only way these numbers go wrong — it stayed green through 55 appended rows.
 *  Deriving the literal and pinning it EXACTLY fails correctly, but fails on
 *  every settle forever, so the copy becomes a chore attached to unrelated
 *  PRs; Doug called that on #211 (`reader:brittle-test-coupling`) and was
 *  right. The page cannot compute the number at render time either: `/docs` is
 *  excluded from the web image's build context (`.dockerignore`), so the file
 *  is not there to read.
 *
 *  So the copy states a DATED SNAPSHOT and names the command that yields
 *  today's figure, and these pins check the things that stay true as the log
 *  grows: a snapshot cannot exceed the present, backfill is closed, the
 *  verdicts partition the scope, and the copy must keep saying it is a
 *  snapshot.
 *
 *  `repo` defaults to "doug" because it was optional in the file before the
 *  field existed (docs/REVIEWING.md:211) — same default the CLI applies, so
 *  this scope matches `findings_log rate --repo doug`. */
const logRows = findingsLog
  .split("\n")
  .filter((line) => line.trim())
  .map((line) => JSON.parse(line));
const prospective = logRows.filter((r) => r.source !== "backfill");
const dougRows = prospective.filter((r) => (r.repo ?? "doug") === "doug");
const counts = {
  total: logRows.length,
  prospective: prospective.length,
  backfill: logRows.length - prospective.length,
  doug: dougRows.length,
  disproved: dougRows.filter((r) => r.verdict === "disproved").length,
  real: dougRows.filter((r) => r.verdict === "real").length,
  adjacent: dougRows.filter((r) => r.verdict === "adjacent").length,
};

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
  // NAV_LINKS, a phone cannot reach Dashboard, Docs, Scoreboard, or Queue
  // from the chrome — and the request that produced this pin came from a
  // phone.
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
  // Dashboard is first and is the only entry addressed to someone who already
  // has Doug: every setting — the flag line, the PR comment — is behind it,
  // and until it existed the only route back from the marketing site was the
  // URL bar. Scoreboard and Queue are the live public surfaces, Docs is
  // reference material — those four are NAV_LINKS entries. GitHub and About
  // are each hardcoded separately after the NAV_LINKS.map, in that order, so
  // they're matched by their literal JSX (not the `href: "…"` object-literal
  // shape NAV_LINKS entries use). Regressing this ordering is exactly the kind
  // of silent reshuffle a diff review wouldn't catch without a pin.
  const order = [
    'href: "/dashboard"',
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
  // The sample used to be pinned as an "empty-ledger snapshot". That stopped
  // being what the endpoint returns the moment the first outcome adjudicated,
  // and a label describing a state the ledger has left reads as today's
  // reading. What is durable is the null: miss_rate stays null and decidable
  // stays false until the pre-registered interval fires, whatever the
  // counters say. Pin that, and pin that the sample shows the whole shape.
  assert.equal(rest.includes("empty-ledger snapshot"), false);
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

test("what Doug gets wrong quotes a dated snapshot, not a live count", () => {
  assert.equal(wrong.includes("Roughly half"), false);
  assert.equal(wrong.includes("12 rows today"), false);
  assert.equal(llms.includes("Roughly half"), false);

  for (const [source, name] of [
    [wrong, "what-doug-gets-wrong"],
    [llms, "llms.txt"],
  ]) {
    // A number with no date reads as current, and cannot be. Both surfaces
    // must date the figure and say in words that it does not track the log.
    assert.match(source, /as of 20\d\d-\d\d-\d\d/i, `${name}: as-of date`);
    assert.match(source, /snapshot/i, `${name}: says it is a snapshot`);
    // And must hand the reader the instrument, so a stale figure is
    // recoverable without waiting for anyone to edit this page.
    assert.match(
      source,
      /findings_log rate --repo doug/,
      `${name}: names the command that prints today's figure`,
    );
  }

  // The snapshot's own arithmetic, against the log as it stands now. These
  // survive growth: a snapshot taken in the past cannot exceed the present,
  // and backfill is closed by construction — the denominator starts at the
  // first prospective row and no new backfill row is ever appended.
  const snapshot = {
    total: Number(/([\d,]+) rows/.exec(wrong)?.[1]?.replace(/,/g, "")),
    prospective: Number(/([\d,]+) prospective/.exec(wrong)?.[1]?.replace(/,/g, "")),
    backfill: Number(/([\d,]+) backfill/.exec(wrong)?.[1]?.replace(/,/g, "")),
    doug: Number(/repo is ([\d,]+) of those/.exec(wrong)?.[1]?.replace(/,/g, "")),
    disproved: Number(/([\d,]+) disproved/.exec(wrong)?.[1]?.replace(/,/g, "")),
    real: Number(/([\d,]+) real/.exec(wrong)?.[1]?.replace(/,/g, "")),
    adjacent: Number(/([\d,]+) adjacent/.exec(wrong)?.[1]?.replace(/,/g, "")),
  };
  for (const [k, v] of Object.entries(snapshot)) {
    assert.ok(Number.isInteger(v), `snapshot ${k} did not parse out of the copy`);
  }
  assert.equal(snapshot.total, snapshot.prospective + snapshot.backfill);
  assert.equal(
    snapshot.doug,
    snapshot.disproved + snapshot.real + snapshot.adjacent,
    "the three verdicts must partition the doug-scoped rows",
  );
  assert.ok(snapshot.doug <= snapshot.prospective);
  assert.ok(
    snapshot.total <= counts.total,
    `the snapshot claims ${snapshot.total} rows but the log holds ${counts.total} — a snapshot cannot exceed the present`,
  );
  assert.equal(
    snapshot.backfill,
    counts.backfill,
    "backfill is closed; a change here means a backfill row was appended, which the denominator rule forbids",
  );
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
  // Most rows are prospective. A callout that still says every row is
  // backfill contradicts the rail on the same page.
  assert.ok(counts.prospective > counts.backfill);
  assert.equal(wrong.includes("Every row in the log today is backfill"), false);
  assert.equal(changelog.includes("All rows today are backfill"), false);
});

test("the scoreboard sample shows a shape, not a reading that decays", () => {
  // The first pass at this replaced an "empty-ledger snapshot" showing 0/0
  // with the live counters, which are stale the moment they are printed —
  // the same drift class this file exists to stop, reintroduced by the fix
  // for it. Doug caught it on #211 (`reader:docs-sample-drift`).
  assert.doesNotMatch(
    rest,
    /"adjudicated"[^\n]*<Kw>\s*\d/,
    "the sample must not print a concrete adjudicated count",
  );
  assert.doesNotMatch(rest, /2026-08-25T/, "no frozen timestamp in the sample");
  // What is durable: every field, and the two values that do not move.
  for (const field of ["repo", "adjudicated", "pending", "as_of", "first_due",
    "deep_reads", "deep_read_cap", "miss_rate", "decidable", "label"]) {
    assert.match(rest, new RegExp(`&quot;${field}&quot;`), `sample: ${field}`);
  }
  assert.match(rest, /<Kw>null<\/Kw>/);
  assert.match(rest, /<Kw>false<\/Kw>/);
});

test("llms.txt names both sanctioned homes for the per-repo settings", () => {
  // ADR-0019: "The repositories table KEEPS its control: ADR-0013's adjacency
  // argument is untouched." Naming only /dashboard/settings describes one of
  // two shipped surfaces. Doug's `contradicts-ticket` on #211.
  assert.match(llms, /\/dashboard\/settings/);
  assert.match(llms, /repositories table/);
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

test("the AUC panel says whose number 0.69 / 0.67 is", () => {
  // ADR-0012: the shipped reader reads up to 100,000 chars in tiered order,
  // so "the shipped reader is the one that scored 0.687/0.668" is false. The
  // panel keeps the figures — the probe did score them — but under a heading
  // reading "What's actually measured" a visitor reads them as the number for
  // the reader on their PRs unless the panel names the configuration that
  // produced them. The sentence is pre-registered in
  // docs/design/competitor-imports/design-lock.md open risk #4, so pin the
  // whole of it, not a phrase — a half-kept caveat is the same defect back.
  // Normalized before matching so the pin fails on wording, not typography:
  // whitespace collapsed (re-wrapping the JSX is not an edit), entities
  // folded to their characters, and either dash accepted. A change to the
  // words is meant to fail here — that is the point of pinning a
  // pre-registered sentence.
  const oneLine = landing
    .replace(/&rsquo;/g, "\u2019")
    .replace(/&mdash;/g, "\u2014")
    .replace(/\s+/g, " ");
  assert.match(
    oneLine,
    /That\u2019s the 30,000-character probe reader, not the one running on your PRs [\u2014-] the shipped reader hasn\u2019t been measured by it\./,
  );
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
