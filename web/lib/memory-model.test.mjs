// Intents: the list follows the filter and the search and nothing else; a
// zero says which zero; the line follows all three flags and names the one
// that is off, in the API's terms.
import assert from "node:assert/strict";
import test from "node:test";

import {
  fileAccounting,
  matchedNothingGloss,
  matchesQuery,
  parseStatusFilter,
  queryFromParams,
  readsBeforeDiffLine,
  recordHref,
  selectRecords,
} from "./memory-model.ts";

const rec = (id, status, title = "Title", body = "Body") => ({ id, title, status, date: null, ref: `docs/decisions/${id}.md`, body });

test("the status filter defaults to accepted, and reads a repeated param the way Next hands it", () => {
  assert.equal(parseStatusFilter(undefined), "accepted");
  assert.equal(parseStatusFilter("all"), "all");
  assert.equal(parseStatusFilter(["all", "all"]), "all");
  assert.equal(parseStatusFilter("anything-else"), "accepted");
});

test("the binding filter uses the word the API counts with, so the count and the list are one definition", () => {
  const records = [rec("ADR-0002", "superseded"), rec("ADR-0001", "accepted"), rec("ADR-0003", "Accepted")];
  assert.deepEqual(selectRecords(records, "accepted", "", "accepted").map((r) => r.id), ["ADR-0001", "ADR-0003"]);
  assert.deepEqual(selectRecords(records, "all", "", "accepted").map((r) => r.id), ["ADR-0001", "ADR-0002", "ADR-0003"]);
  // Mutation: a literal "accepted" in the filter would ignore a changed binding word.
  assert.deepEqual(selectRecords(records, "accepted", "", "superseded").map((r) => r.id), ["ADR-0002"]);
});

test("search is lexical over id, title, and body, every term required", () => {
  const r = rec("ADR-0004", "accepted", "The reader is in the scoring path", "Cost wedge dead.");
  assert.equal(matchesQuery(r, queryFromParams("reader scoring")), true);
  assert.equal(matchesQuery(r, queryFromParams("adr-0004")), true);
  assert.equal(matchesQuery(r, queryFromParams("wedge")), true);
  assert.equal(matchesQuery(r, queryFromParams("wedge alive")), false);
  assert.equal(matchesQuery(r, queryFromParams(["  Reader "])), true);
});

test("a zero names where the walk looked, and never calls an unread file unparseable", () => {
  const base = {
    github_repo_id: 1, full_name: "acme/repo", items: [], binding_status: "accepted", count_accepted: 0,
    matched_nothing: true, directory: null, directories_searched: ["docs/decisions", "docs/adr"],
    files_seen: 0, files_unparseable: 0, files_unread: 0,
    reads_before_diff: { value: false, deep_read: true, allowlisted: false, reader_enabled: false },
    fetched_at: "2026-09-10T00:00:00Z", cached: false,
  };
  assert.match(matchedNothingGloss(base), /docs\/decisions, docs\/adr/);
  assert.equal(matchedNothingGloss(base).includes("frontmatter"), false);
  const unparseable = { ...base, files_seen: 2, files_unparseable: 2 };
  assert.match(matchedNothingGloss(unparseable), /2 markdown files carried no title and status in frontmatter/);
  // Mutation: the earlier gloss said "none carried a title and a status" for
  // any seen file, absolving a transport error.
  const unread = { ...base, files_seen: 2, files_unparseable: 1, files_unread: 1 };
  const gloss = matchedNothingGloss(unread);
  assert.match(gloss, /1 markdown file carried no title and status/);
  assert.match(gloss, /1 could not be read/);
  assert.equal(fileAccounting({ ...base, files_unparseable: 0, files_unread: 0 }), "");
  assert.equal(fileAccounting({ ...base, files_unparseable: 2, files_unread: 1 }), "; 2 files without frontmatter, 1 unread");
});

test("the line is on only when all three flags are, and names the off ones", () => {
  assert.equal(readsBeforeDiffLine({ value: true, deep_read: true, allowlisted: true, reader_enabled: true }).on, true);
  const off = readsBeforeDiffLine({ value: false, deep_read: true, allowlisted: false, reader_enabled: false });
  assert.equal(off.on, false);
  assert.match(off.detail, /intent tier is not enabled/);
  assert.match(off.detail, /reader is off/);
  assert.equal(off.detail.includes("deep read"), false);
  // Mutation: a line that ignored the reader switch would be "on" here.
  const readerOff = readsBeforeDiffLine({ value: false, deep_read: true, allowlisted: true, reader_enabled: false });
  assert.equal(readerOff.on, false);
  assert.match(readerOff.detail, /reader is off/);
});

test("a record opens on GitHub at HEAD, path segments encoded", () => {
  assert.equal(
    recordHref("acme/repo", "docs/decisions/ADR-0001 a.md"),
    "https://github.com/acme/repo/blob/HEAD/docs/decisions/ADR-0001%20a.md",
  );
});
