// Intents: the list follows the filter and the search and nothing else; a
// zero says which zero; the line follows all three flags and names the one
// that is off, in the API's terms.
import assert from "node:assert/strict";
import test from "node:test";

import {
  matchedNothingGloss,
  matchesQuery,
  normalizeQuery,
  parseStatusFilter,
  readsBeforeDiffLine,
  recordHref,
  selectRecords,
} from "./memory-model.ts";

const rec = (id, status, title = "Title", body = "Body") => ({ id, title, status, date: null, ref: `docs/decisions/${id}.md`, body });

test("the status filter defaults to accepted, which is what the reader is fed", () => {
  assert.equal(parseStatusFilter(undefined), "accepted");
  assert.equal(parseStatusFilter("all"), "all");
  assert.equal(parseStatusFilter("anything-else"), "accepted");
});

test("accepted hides history; all shows it; both sort by id", () => {
  const records = [rec("ADR-0002", "superseded"), rec("ADR-0001", "accepted"), rec("ADR-0003", "Accepted")];
  assert.deepEqual(selectRecords(records, "accepted", "").map((r) => r.id), ["ADR-0001", "ADR-0003"]);
  assert.deepEqual(selectRecords(records, "all", "").map((r) => r.id), ["ADR-0001", "ADR-0002", "ADR-0003"]);
});

test("search is lexical over id, title, and body, every term required", () => {
  const r = rec("ADR-0004", "accepted", "The reader is in the scoring path", "Cost wedge dead.");
  assert.equal(matchesQuery(r, normalizeQuery("reader scoring")), true);
  assert.equal(matchesQuery(r, normalizeQuery("adr-0004")), true);
  assert.equal(matchesQuery(r, normalizeQuery("wedge")), true);
  assert.equal(matchesQuery(r, normalizeQuery("wedge alive")), false);
  assert.equal(matchesQuery(r, normalizeQuery(["  Reader "])), true);
});

test("a zero names where the walk looked, and says when files were there but unparseable", () => {
  const base = {
    github_repo_id: 1, full_name: "acme/repo", items: [], count_accepted: 0, matched_nothing: true,
    directory: null, directories_searched: ["docs/decisions", "docs/adr"], files_seen: 0, files_skipped: 0,
    reads_before_diff: { value: false, deep_read: true, allowlisted: false, reader_enabled: false },
    fetched_at: "2026-09-10T00:00:00Z", cached: false,
  };
  assert.match(matchedNothingGloss(base), /docs\/decisions, docs\/adr/);
  assert.equal(matchedNothingGloss(base).includes("were there"), false);
  const unparseable = { ...base, files_seen: 2, files_skipped: 2 };
  assert.match(matchedNothingGloss(unparseable), /2 markdown files were there and none carried a title and a status/);
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
