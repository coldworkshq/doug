import assert from "node:assert/strict";
import test from "node:test";

import { groupRunsByPr, runCountLabel } from "./grouping.ts";

function run(overrides) {
  return {
    verdict_id: 1,
    repo: "drewjst/doug",
    installation_id: 150424894,
    github_repo_id: 1,
    pr_number: 56,
    title: "route read budget by file tier",
    url: "https://github.com/drewjst/doug/pull/56",
    scored_at: "2026-08-05T10:00:00",
    tier: "code",
    source: "app",
    score: 0.38,
    band: "flagged",
    threshold: 0.3,
    coverage: null,
    changed_files: null,
    finding_counts: { total: 0, high: 0, medium: 0, low: 0 },
    job: null,
    outcome_14: null,
    ...overrides,
  };
}

test("runs on one PR collapse into a single group, newest run first", () => {
  // The whole point of the accordion: #56 was pushed eight times and ate
  // half the first screen as eight sibling rows. Collapsed, the operator
  // sees one row per PR and opts into the history.
  const groups = groupRunsByPr(
    [
      run({ verdict_id: 3, scored_at: "2026-08-05T12:00:00" }),
      run({ verdict_id: 2, scored_at: "2026-08-05T11:00:00" }),
      run({ verdict_id: 1, scored_at: "2026-08-05T10:00:00" }),
    ],
    false,
  );

  assert.equal(groups.length, 1);
  assert.equal(groups[0].latest.verdict_id, 3);
  assert.deepEqual(
    groups[0].children.map((r) => r.verdict_id),
    [2, 1],
  );
  assert.equal(groups[0].runCount, 3);
});

test("the same PR number in two repos stays two groups", () => {
  // Doug spans installations by design — drewjst/doug and lemahq/lema-verify
  // both have a #12. Keying on pr_number alone would merge two unrelated
  // pull requests into one row and attribute one repo's runs to the other,
  // which is the console asserting a fact that is simply false.
  const groups = groupRunsByPr(
    [
      run({ verdict_id: 1, repo: "drewjst/doug", pr_number: 12 }),
      run({ verdict_id: 2, repo: "lemahq/lema-verify", pr_number: 12 }),
    ],
    false,
  );

  assert.equal(groups.length, 2);
  assert.deepEqual(new Set(groups.map((g) => g.repo)), new Set(["drewjst/doug", "lemahq/lema-verify"]));
});

test("group order is derived from each group's newest run, not from input order", () => {
  // run_history returns newest-first today, so first-seen order and
  // newest-first agree and a bug here would be invisible. Feeding
  // deliberately shuffled input is the only way this assertion can fail
  // when the implementation starts trusting arrival order.
  const groups = groupRunsByPr(
    [
      run({ verdict_id: 1, pr_number: 10, scored_at: "2026-08-05T09:00:00" }),
      run({ verdict_id: 2, pr_number: 20, scored_at: "2026-08-05T15:00:00" }),
      run({ verdict_id: 3, pr_number: 10, scored_at: "2026-08-05T18:00:00" }),
    ],
    false,
  );

  assert.deepEqual(
    groups.map((g) => g.prNumber),
    [10, 20],
  );
  assert.equal(groups[0].latest.verdict_id, 3);
});

test("a zoneless timestamp is ordered as UTC, matching the age column", () => {
  // Same trap relativeAge documents: `new Date(iso)` on a zoneless string
  // reads it as the server's local zone. Ordering through a different
  // parser than the age label uses lets the table contradict itself — a
  // row printed "2h" sorting above one printed "1h".
  const groups = groupRunsByPr(
    [
      run({ verdict_id: 1, scored_at: "2026-08-05T10:00:00" }),
      run({ verdict_id: 2, scored_at: "2026-08-05T11:00:00Z" }),
    ],
    false,
  );

  assert.equal(groups[0].latest.verdict_id, 2);
});

test("a PR with one run has no children, so the UI renders no disclosure control", () => {
  // A chevron that expands to nothing is a control that lies about there
  // being more to see. The empty children array is what the table keys
  // that decision off.
  const groups = groupRunsByPr([run({ verdict_id: 1 })], false);

  assert.deepEqual(groups[0].children, []);
  assert.equal(groups[0].runCount, 1);
});

test("at the page cap every run count is a lower bound", () => {
  // The governing rule: never assert a fact you do not have. A capped page
  // is truncated at its OLDEST end, and any PR may have further runs past
  // that boundary — including one whose visible runs are all recent. There
  // is no way to tell which, so every count degrades together and the
  // table renders "3+" instead of "3".
  const rows = [
    run({ verdict_id: 3, scored_at: "2026-08-05T12:00:00" }),
    run({ verdict_id: 2, scored_at: "2026-08-05T11:00:00" }),
    run({ verdict_id: 1, scored_at: "2026-08-05T10:00:00" }),
  ];

  assert.equal(groupRunsByPr(rows, false)[0].countIsLowerBound, false);
  assert.equal(groupRunsByPr(rows, true)[0].countIsLowerBound, true);
});

test("no runs means no groups — never a fabricated empty group", () => {
  assert.deepEqual(groupRunsByPr([], false), []);
});

const threeRuns = [
  run({ verdict_id: 3, scored_at: "2026-08-05T12:00:00" }),
  run({ verdict_id: 2, scored_at: "2026-08-05T11:00:00" }),
  run({ verdict_id: 1, scored_at: "2026-08-05T10:00:00" }),
];

test("an unfiltered, uncapped count is stated plainly", () => {
  const [group] = groupRunsByPr(threeRuns, false);
  assert.deepEqual(runCountLabel(group, false), { text: "3", title: "3 runs" });
});

test("a filtered group counts MATCHES, and the badge says so", () => {
  // The group holds only the runs that survived the pill bar, so "3" is a
  // count of matches and not of the PR's runs. Without the title, a
  // filtered badge reading "3" on a PR with eight runs is simply wrong.
  const [group] = groupRunsByPr(threeRuns, false);
  assert.deepEqual(runCountLabel(group, true), {
    text: "3",
    title: "3 runs matching the current filter",
  });
});

test("a capped count renders as a lower bound in both the badge and its title", () => {
  const [group] = groupRunsByPr(threeRuns, true);
  assert.equal(runCountLabel(group, false).text, "3+");
  assert.match(runCountLabel(group, false).title, /at least 3 runs/);
});

test("cap and filter compose — the badge admits both at once", () => {
  // Neither qualifier may swallow the other: capped-and-filtered is a
  // count of matches that is ALSO a lower bound.
  const [group] = groupRunsByPr(threeRuns, true);
  const { text, title } = runCountLabel(group, true);
  assert.equal(text, "3+");
  assert.match(title, /at least 3 matching runs/);
  assert.match(title, /past the page limit/);
});

test("a one-run group says 'run', not 'runs'", () => {
  const [group] = groupRunsByPr([run({ verdict_id: 1 })], false);
  assert.equal(runCountLabel(group, false).title, "1 run");
});
