import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  filterJobsByQuery,
  filterRunsByQuery,
  jobMatchesQuery,
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

function job(overrides = {}) {
  return {
    id: 9,
    lane: "review",
    repo: "drewjst/doug",
    github_repo_id: 1,
    installation_id: 1,
    pr_number: 74,
    status: "pending",
    attempts: 1,
    error: "timeout waiting for model",
    started_at: null,
    finished_at: null,
    stalled: false,
    head_sha: null,
    enqueued_at: null,
    verdict_id: null,
    retrying: false,
    merge_commit_sha: null,
    window_days: null,
    due_at: null,
    merged_at: null,
    overdue: false,
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

describe("jobMatchesQuery", () => {
  it("matches reason text the table would show", () => {
    const j = job({ stalled: true, status: "running" });
    assert.equal(jobMatchesQuery(j, "lease", "lease expired"), true);
    assert.equal(jobMatchesQuery(j, "timeout", "lease expired"), true);
    assert.equal(jobMatchesQuery(j, "missing", "lease expired"), false);
  });
});

describe("filterJobsByQuery", () => {
  it("uses the reason callback for matching", () => {
    const jobs = [job(), job({ id: 10, error: null, status: "failed" })];
    const filtered = filterJobsByQuery(jobs, "failed after", (j) =>
      j.status === "failed" ? `failed after ${j.attempts}` : j.status,
    );
    assert.equal(filtered.length, 1);
    assert.equal(filtered[0].id, 10);
  });
});
