import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  adjacentDocsPages,
  DOCS_HOME,
  DOCS_SECTIONS,
  docsPageLabel,
  docsSectionOf,
  filterDocsNav,
  flattenDocsNav,
  sidebarTag,
} from "./docs-nav.ts";

const overview = await readFile(new URL("../app/docs/page.tsx", import.meta.url), "utf8");
const pageSource = (href) => readFile(new URL(`../app${href}/page.tsx`, import.meta.url), "utf8");

test("every doc href is unique — a duplicate would make prev/next and the active-link check ambiguous", () => {
  const hrefs = flattenDocsNav().map((p) => p.href);
  assert.equal(new Set(hrefs).size, hrefs.length);
});

test("every linked entry is a page that exists — a nav entry is a promise the route renders", () => {
  // The audit's pages used to be static files reached by a rewrite, which no
  // route check could see. Every entry is an app route now, so a nav href
  // without its page.tsx is a 404 the sidebar advertises.
  for (const { href } of flattenDocsNav()) {
    const file = new URL(`../app${href}/page.tsx`, import.meta.url);
    assert.ok(existsSync(file), `${href} is in the nav but app${href}/page.tsx does not exist`);
  }
});

test("each section's href lands on its own half of the overview", () => {
  // /docs/audit redirects to /docs#the-audit (next.config.ts). An anchor with
  // no element behind it is a redirect that lands at the top of the wrong half.
  for (const section of DOCS_SECTIONS) {
    const [path, id] = section.href.split("#");
    assert.equal(path, "/docs", `${section.name} is introduced somewhere other than the overview`);
    assert.ok(id, `${section.name} names no anchor`);
    assert.match(overview, new RegExp(`id="${id}"`), `the overview has no element with id="${id}"`);
  }
});

test("every page's pager is told its own route — a copied page would page from someone else's place", async () => {
  // DocsPager takes the current href as a string each page types. A page
  // copied from another that keeps the other's href shows the wrong neighbors,
  // and a typo shows none; neither fails anything else.
  for (const { href } of flattenDocsNav()) {
    const source = await pageSource(href);
    assert.match(source, new RegExp(`<DocsPager currentHref="${href}" />`), `app${href}/page.tsx pages from somewhere else`);
  }
});

test("every page's header states its nav status, and the audit's pages say what their preview means", async () => {
  // When coldworks-audit ships, its status changes here first. A page that
  // still says "preview", or still prints "has not shipped", would then fail
  // this test instead of shipping a stale claim.
  for (const section of DOCS_SECTIONS) {
    for (const group of section.groups) {
      for (const entry of group.entries) {
        if (!entry.href || !entry.status) continue;
        const source = await pageSource(entry.href);
        assert.match(source, new RegExp(`status="${entry.status}"`), `app${entry.href}/page.tsx does not state ${entry.status}`);
        const labelled = source.includes("statusLabel={AUDIT_PREVIEW_LABEL}");
        const shouldLabel = section.name === "The audit" && entry.status === "preview";
        assert.equal(labelled, shouldLabel, `app${entry.href}/page.tsx ${shouldLabel ? "omits" : "prints"} the audit's preview label`);
      }
    }
  }
});

test("the overview opens reading order; Doug reviews comes before the audit, in the door's order", () => {
  const flat = flattenDocsNav();
  assert.equal(flat[0], DOCS_HOME);
  assert.equal(adjacentDocsPages("/docs").prev, null);
  assert.equal(adjacentDocsPages("/docs").next?.href, "/docs/quickstart");
  assert.deepEqual(DOCS_SECTIONS.map((s) => s.name), ["Doug reviews", "The audit"]);
});

test("the audit overview is not a page of its own — it is part of /docs", () => {
  const hrefs = flattenDocsNav().map((p) => p.href);
  assert.equal(hrefs.includes("/docs/audit"), false);
  assert.ok(hrefs.includes("/docs/audit/quickstart"));
});

test("the last page has no next — prev/next must not wrap around to the overview", () => {
  const last = flattenDocsNav().at(-1);
  assert.equal(adjacentDocsPages(last.href).next, null);
});

test("prev/next cross a group boundary and a section boundary, not just neighbors within one group", () => {
  assert.equal(adjacentDocsPages("/docs/what-doug-gets-wrong").next?.href, "/docs/cli");
  assert.equal(adjacentDocsPages("/docs/changelog").next?.href, "/docs/audit/quickstart");
  assert.equal(adjacentDocsPages("/docs/audit/quickstart").prev?.href, "/docs/changelog");
});

test("an href with no match returns nulls instead of a false neighbor", () => {
  const { prev, next } = adjacentDocsPages("/docs/nonexistent");
  assert.equal(prev, null);
  assert.equal(next, null);
});

test("an upcoming entry is listed but never linked and never in reading order", () => {
  const upcoming = DOCS_SECTIONS.flatMap((s) => s.groups.flatMap((g) => g.entries)).filter((e) => e.upcoming);
  assert.ok(upcoming.length > 0, "no upcoming entries — this test would pass vacuously");
  const titles = new Set(flattenDocsNav().map((p) => p.title));
  for (const entry of upcoming) {
    assert.equal("href" in entry, false, `${entry.title} is upcoming but carries an href`);
    assert.equal(titles.has(entry.title), false, `${entry.title} is upcoming but in reading order`);
  }
});

test("an empty query returns every section unfiltered", () => {
  assert.deepEqual(filterDocsNav(""), [...DOCS_SECTIONS]);
});

test("filtering is case-insensitive and matches mid-title", () => {
  const titles = filterDocsNav("CLEARED").flatMap((s) => s.groups.flatMap((g) => g.entries.map((e) => e.title)));
  assert.deepEqual(titles, ["The cleared band"]);
});

test("a query for a section's name finds every page of it, even where the title does not say so", () => {
  // The audit's pages lost their "Audit ·" prefixes when they joined the one
  // site; a title-only filter then hid the audit's Quickstart under a section
  // header that still looked complete.
  const sections = filterDocsNav("audit");
  assert.deepEqual(sections.map((s) => s.name), ["The audit"]);
  const found = sections[0].groups.flatMap((g) => g.entries.map((e) => e.title));
  const all = DOCS_SECTIONS[1].groups.flatMap((g) => g.entries.map((e) => e.title));
  assert.deepEqual(found, all);
});

test("a query reaches both sections, so a shared title is not hidden in one", () => {
  const sections = filterDocsNav("quickstart");
  assert.deepEqual(sections.map((s) => s.name), ["Doug reviews", "The audit"]);
});

test("a group or section with zero surviving matches is dropped, not rendered empty", () => {
  const sections = filterDocsNav("changelog");
  assert.equal(sections.length, 1);
  assert.equal(sections[0].name, "Doug reviews");
  assert.deepEqual(sections[0].groups.map((g) => g.name), ["Meta"]);
});

test("a query matching nothing returns no sections at all", () => {
  assert.deepEqual(filterDocsNav("xyz-does-not-exist"), []);
});

test("Coming up is preview or planned only — an available page there would be a false signal", () => {
  const comingUp = DOCS_SECTIONS[0].groups.find((g) => g.name === "Coming up");
  for (const entry of comingUp.entries) {
    assert.notEqual(entry.status, "available", `${entry.title} is in "Coming up" but marked available`);
  }
});

test("a page's sidebar tag says only what its section does not already say", () => {
  const [doug, audit] = DOCS_SECTIONS;
  assert.equal(sidebarTag({ href: "/docs/quickstart", title: "Quickstart", status: "available" }, doug), null);
  assert.equal(sidebarTag({ href: "/docs/mcp", title: "MCP", status: "planned" }, doug), "planned");
  assert.equal(sidebarTag({ href: "/docs/audit/cli", title: "The audit CLI", status: "preview" }, audit), null);
  // A page that differs from its preview section is tagged, in either direction.
  assert.equal(sidebarTag({ href: "/docs/x", title: "X", status: "available" }, audit), "available");
  assert.equal(sidebarTag({ title: "The audit report", upcoming: true }, audit), "soon");
  assert.equal(sidebarTag({ href: "/docs/changelog", title: "Changelog" }, doug), null);
});

test("a page's section is found by its href; the overview belongs to none", () => {
  assert.equal(docsSectionOf("/docs/audit/cli")?.name, "The audit");
  assert.equal(docsSectionOf("/docs/changelog")?.name, "Doug reviews");
  assert.equal(docsSectionOf("/docs"), null);
  assert.equal(docsSectionOf("/docs/nonexistent"), null);
});

test("the collapsed sidebar names the section, because two sections each have a Quickstart", () => {
  assert.equal(docsPageLabel("/docs"), "Overview");
  assert.equal(docsPageLabel("/docs/quickstart"), "Doug reviews · Quickstart");
  assert.equal(docsPageLabel("/docs/audit/quickstart"), "The audit · Quickstart");
  assert.equal(docsPageLabel("/docs/nonexistent"), null);
});
