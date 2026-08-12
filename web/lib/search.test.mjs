// Ported from console/lib/search.test.mjs — run-search half only.
//
// Console has 9 tests here; this file has 7. The two dropped ones cover
// jobMatchesQuery/filterJobsByQuery, which are not ported: web has no jobs
// surface and console's JobItem type has no web equivalent (plan D6). The
// job() fixture goes with them. Every remaining test name and comment is
// the console's, verbatim.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  filterRunsByQuery,
  normalizeQuery,
  runMatchesQuery,
} from "./search.ts";

function run(overrides = {}) {
  return {
    verdict_id: 1,
    repo: "drewjst/doug",
    installation_id: 1,
    github_repo_id: 1,
    pr_number: 74,
    title: "add security headers and npm workspaces",
    url: null,
    scored_at: "2026-08-08T00:00:00Z",
    tier: "deep",
    source: null,
    score: 0.4,
    band: "flagged",
    threshold: 0.3,
    coverage: null,
    changed_files: 10,
    finding_counts: { total: 0, high: 0, medium: 0, low: 0 },
    job: null,
    outcome_14: "clean",
    ...overrides,
  };
}

describe("normalizeQuery", () => {
  it("trims and lowercases", () => {
    assert.equal(normalizeQuery("  Foo BAR  "), "foo bar");
  });
  it("treats blank as empty", () => {
    assert.equal(normalizeQuery("   "), "");
    assert.equal(normalizeQuery(null), "");
  });
});

describe("runMatchesQuery", () => {
  it("matches everything when the query is empty", () => {
    assert.equal(runMatchesQuery(run(), ""), true);
    assert.equal(runMatchesQuery(run(), "  "), true);
  });
  it("matches repo, PR number, title, band, and tier", () => {
    const r = run();
    assert.equal(runMatchesQuery(r, "doug"), true);
    assert.equal(runMatchesQuery(r, "74"), true);
    assert.equal(runMatchesQuery(r, "security"), true);
    assert.equal(runMatchesQuery(r, "flagged"), true);
    assert.equal(runMatchesQuery(r, "deep"), true);
    assert.equal(runMatchesQuery(r, "missing-token"), false);
  });
  it("requires every whitespace token to match", () => {
    assert.equal(runMatchesQuery(run(), "doug 74"), true);
    assert.equal(runMatchesQuery(run(), "doug absent"), false);
  });
});

describe("filterRunsByQuery", () => {
  it("returns the original array when there is no query", () => {
    const runs = [run(), run({ verdict_id: 2, pr_number: 75 })];
    assert.equal(filterRunsByQuery(runs, ""), runs);
  });
  it("filters to matching runs", () => {
    const runs = [
      run({ title: "workspaces" }),
      run({ verdict_id: 2, title: "unrelated", pr_number: 1 }),
    ];
    assert.equal(filterRunsByQuery(runs, "workspaces").length, 1);
  });
});
