// Pins for /dashboard/memory, the visible half of the record.
//
// Source-text pins, not render tests (house rule). Each protects one of the
// design lock's rulings for this screen: the list is never gated by the
// review-time flags and the line always is; a zero says which zero and is
// never a bare 0; the page wears the rail; the records open at HEAD.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [page, rail, sessionApi] = await Promise.all([
  readFile(new URL("../app/dashboard/memory/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../components/dashboard-rail.tsx", import.meta.url), "utf8"),
  readFile(new URL("./session-api.ts", import.meta.url), "utf8"),
]);

test("the page wears the rail, marked current, and the rail links to it once", () => {
  assert.match(page, /<DashboardRail/);
  assert.match(page, /section="memory"/);
  const entries = [...rail.matchAll(/href="\/dashboard\/memory"/g)];
  assert.equal(entries.length, 1);
  assert.match(rail, /aria-current=\{section === "memory" \? "page" : undefined\}/);
  // Between Repositories and the unbuilt Evidence entry, above Settings.
  const repositories = rail.indexOf(">Repositories</Link>");
  const memory = rail.indexOf('href="/dashboard/memory"');
  const evidence = rail.indexOf("Evidence <small");
  assert.ok(repositories > 0 && memory > repositories && evidence > memory);
});

test("the list is never gated by the flags; only the line reads them, from a success or a 502", () => {
  // The flags feed `line` and nothing else; the list's rendering condition
  // names only the loaded data.
  assert.match(page, /const line = flags \? readsBeforeDiffLine\(flags\) : null;/);
  assert.match(page, /decisions\?\.failure\.reads_before_diff/);
  assert.match(page, /loaded && !loaded\.matched_nothing && \(/);
  assert.equal(page.includes("line.on &&"), false, "the list is conditioned on the line");
  assert.equal(page.includes("line?.on"), false, "the list is conditioned on the line");
  assert.equal(/shown = .*reads_before_diff/.test(page), false);
});

test("a bookmarked repository outside this space is said so, never silently swapped", () => {
  assert.match(page, /repositories\.find\(\(r\) => r\.id === requested\) \?\? null/);
  assert.match(page, /StateChip kind="unknown" subject="repository"/);
});

test("a zero says which zero, and there is no bare 0 for decisions", () => {
  assert.match(page, /loaded\.matched_nothing && \(/);
  assert.match(page, /StateChip kind="unknown" subject="decisions" detail=\{matchedNothingGloss\(loaded\)\}/);
  assert.equal(page.includes("0 decisions"), false);
  assert.equal(page.includes("0 accepted"), false);
  // A filter that keeps nothing is a sentence about the filter, not a chip.
  assert.match(page, /No record matches this filter\. The records are there/);
});

test("the honesty line is an off chip with the flag named, never a hidden line", () => {
  assert.match(page, /StateChip kind="off" subject="reads before the diff" detail=\{line\.detail\}/);
  assert.match(sessionApi, /reads_before_diff: ReadsBeforeDiff/);
  assert.match(sessionApi, /READS_BEFORE_DIFF_KEYS = \["value", "deep_read", "allowlisted", "reader_enabled"\]/);
  // The count and the list are one definition: the page filters by the word
  // the API counts with.
  assert.match(page, /selectRecords\(loaded\.items, status, query, loaded\.binding_status\)/);
});

test("a record opens on GitHub at HEAD, and a failed read is an unknown chip with its status", () => {
  assert.match(page, /recordHref\(loaded\.full_name, record\.ref\)/);
  assert.match(page, /Open on GitHub at HEAD/);
  assert.match(page, /StateChip kind="unknown" subject="decisions" detail=\{readFailure\}/);
});

test("the client guard is exact-key over the endpoint's shape", () => {
  assert.match(sessionApi, /exact\(value, REPOSITORY_DECISIONS_KEYS\)/);
  assert.match(sessionApi, /\/v1\/sessions\/repositories\/\$\{githubRepoId\}\/decisions/);
});
