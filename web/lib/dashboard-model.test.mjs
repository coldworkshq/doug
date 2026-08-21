import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const rows = [
  {
    verdict_id: 1,
    repo: "acme/one",
    pr_number: 12,
    scored_at: "2026-08-06T10:00:00",
    band: "flagged",
    tier: "reader",
    coverage: { diff_chars: 100, sent_chars: 49, files_sent: 1, files_unseen: ["b"], file_cut: "b" },
    changed_files: 4,
    outcome_14: null,
    job: { error: null },
  },
  {
    verdict_id: 2,
    repo: "acme/two",
    pr_number: 34,
    scored_at: "2026-08-05T10:00:00",
    band: "cleared",
    tier: "deterministic",
    coverage: null,
    changed_files: null,
    outcome_14: "clean",
    job: { error: "timed out" },
  },
];

test("URL filters compose over already scoped rows without inventing a tenant selector", async () => {
  const { dashboardFilters, filterRuns } = await import("./dashboard-model.ts?filters");
  const filters = dashboardFilters({
    repo: "all",
    band: "flagged",
    tier: "reader",
    coverage: "low",
    error: "yes",
    tenant: "all",
  });
  // ONE filter model (RULING 4). The facet dimensions — band, tier, read,
  // outcome — are parsed once, by `parseFacetSelection`, and carried as a
  // selection; `repo` stays the server-side fetch scope and coverage/error
  // stay the dashboard's own two predicates. There is no second parser that
  // could read `band` differently from the pill bar that writes it.
  assert.deepEqual(filters, {
    repo: "all",
    facets: { band: ["flagged"], tier: ["reader"] },
    lowCoverage: true,
    hasError: true,
  });
  assert.deepEqual(filterRuns(rows, { ...filters, hasError: false }).map((row) => row.verdict_id), [1]);
});

test("a single-value band or tier param keeps behaving exactly as it does today", async () => {
  // BACKWARD COMPATIBILITY, required by RULING 4 and pinned here rather than
  // assumed. Every dashboard link shared or bookmarked before the facet bar
  // existed carries `?band=flagged` or `?tier=reader` as a single value. A
  // multi-value model that parsed those into anything other than a selection
  // of one would silently return a different row set to whoever opened the
  // link — a user-visible regression no other test would catch, because every
  // other test would be written against the new multi-value shape.
  const { dashboardFilters, filterRuns } = await import("./dashboard-model.ts?compat");

  const single = dashboardFilters({ band: "flagged" });
  assert.deepEqual(single.facets, { band: ["flagged"] });
  assert.deepEqual(filterRuns(rows, single).map((row) => row.verdict_id), [1]);

  assert.deepEqual(
    filterRuns(rows, dashboardFilters({ tier: "deterministic" })).map((row) => row.verdict_id),
    [2],
  );
  // …and the multi-value form the pill bar writes narrows to the union, which
  // is the whole reason the collision needed a ruling: read as a single value,
  // "flagged,cleared" matched no run at all and blanked the table while the
  // bar claimed two bands were selected.
  assert.deepEqual(
    filterRuns(rows, dashboardFilters({ band: "flagged,cleared" })).map((row) => row.verdict_id),
    [1, 2],
  );
  // No band param at all is no constraint, not an empty selection.
  assert.deepEqual(dashboardFilters({}).facets, {});
  assert.deepEqual(filterRuns(rows, dashboardFilters({})).map((row) => row.verdict_id), [1, 2]);
});

test("at-cap is one definition, so the count line and the group badges cannot disagree", async () => {
  // The page derives BOTH the "· latest 500" suffix and the per-PR group
  // badges' "8+" from the same two numbers. Two separate `>= limit`
  // comparisons is how a header saying "latest 500" ends up above a table
  // whose badges claim exact totals.
  const { isAtCap } = await import("./dashboard-model.ts?at-cap");
  const { groupRunsByPr } = await import("./grouping.ts?at-cap");

  assert.equal(groupRunsByPr(rows, isAtCap(500, 500))[0].countIsLowerBound, true);
  assert.equal(groupRunsByPr(rows, isAtCap(499, 500))[0].countIsLowerBound, false);
});

test("coverage percentage and file ruler use only real denominators", async () => {
  const { coverageView } = await import("./dashboard-model.ts?coverage");
  // The denominator is GitHub's changed_files (1 of 4 = 25%), never the chars
  // ratio (49 of 100) the dashboard used to print while the console printed
  // files — the divergence this view exists to end.
  assert.deepEqual(coverageView(rows[0]), {
    percent: 25,
    kind: "known",
    label: "25%",
    chars: "49 of 100 chars",
    files: "1 of 4 files",
    unseen: ["b"],
    fileCut: "b",
  });
  assert.deepEqual(coverageView(rows[1]), {
    percent: null,
    kind: "no-read",
    label: "—",
    chars: null,
    files: null,
    unseen: [],
    fileCut: null,
  });
  // A missing denominator is "unknown", never a fabricated 100% or 0%.
  const unknown = coverageView({ ...rows[0], changed_files: null });
  assert.equal(unknown.percent, null);
  assert.equal(unknown.kind, "unknown-denominator");
  assert.equal(unknown.label, "—");
});

test("a full page is marked as a cap, never reported as a total", async () => {
  // #90's rule, on the boolean that carries it since PR 2 moved the wording
  // into the page's CountLine. The boundary is `>=`, not `>`: a page holding
  // exactly `limit` rows is indistinguishable from a truncated one, and the
  // response says nothing about what lies past it.
  const { isAtCap } = await import("./dashboard-model.ts?cap");
  assert.equal(isAtCap(500, 500), true);
  assert.equal(isAtCap(501, 500), true);
  assert.equal(isAtCap(499, 500), false);
  assert.equal(isAtCap(0, 500), false);
  // No limit means no cap. page.tsx initialises `limit = 0` before the fetch,
  // and a bare `fetched >= limit` reports TRUE for (0, 0) — a page announcing
  // "latest 0" and marking every group's count a lower bound, on the strength
  // of an uninitialised variable. Unreachable today because the call sits
  // immediately after `limit = response.limit`; pinned so a render-path change
  // cannot quietly make it reachable.
  assert.equal(isAtCap(0, 0), false);
  assert.equal(isAtCap(12, 0), false);
});

test("selectors preserve installation boundaries and the exact Lema marker", async () => {
  const { connectionOptions, repositoryOptions } = await import(
    "./dashboard-model.ts?selectors"
  );
  const connections = [
    {
      installation_id: 101,
      organization_id: "org_acme",
      account_login: "acme",
      account_type: "Organization",
      status: "ready",
      label: null,
      repositories: [{ id: 11, full_name: "acme/one" }],
    },
    {
      installation_id: 202,
      organization_id: "org_lema",
      account_login: "LemaHQ",
      account_type: "Organization",
      status: "ready",
      label: "Lema — separate product",
      repositories: [{ id: 22, full_name: "lemahq/lema" }],
    },
  ];
  assert.deepEqual(connectionOptions(connections), [
    { value: "org_acme", login: "acme", label: null, accountType: "Organization" },
    {
      value: "org_lema",
      login: "LemaHQ",
      label: "Lema — separate product",
      accountType: "Organization",
    },
  ]);
  assert.deepEqual(repositoryOptions(connections[0]), [
    { value: "all", label: "all repositories" },
    { value: "acme/one", label: "acme/one" },
  ]);
  assert.equal(repositoryOptions(connections[0]).some((option) => option.value === "lemahq/lema"), false);
});

test("outcome tone follows the recorded result instead of treating every outcome as clear", async () => {
  const { outcomeTone } = await import("./dashboard-model.ts?outcome-tone");
  // The production vocabulary is exactly revert | clean | censored
  // (api/doug/adjudicate.py's OutcomeKind); the column also permits hotfix,
  // which the adjudicator deliberately never writes.
  assert.equal(outcomeTone("clean"), "clear");
  assert.equal(outcomeTone("revert"), "flag");
  assert.equal(outcomeTone("hotfix"), "flag");
  // Censored = the PR left the risk set unobserved (merged off the default
  // branch, or no clone reachable). Blindness is not a miss, so it never
  // takes the flag colour reserved for real ones.
  assert.equal(outcomeTone("censored"), "neutral");
  // An unrecognised kind flags. Silently neutralising it is how a genuinely
  // bad new outcome would arrive on the dashboard looking like nothing.
  assert.equal(outcomeTone("graded-miss"), "flag");
  assert.equal(outcomeTone("unknown-future-kind"), "flag");
  // No outcome recorded yet is the one honest neutral.
  assert.equal(outcomeTone(null), "neutral");
});

test("setup recovery accepts only a positive safe id on an exact visible pending connection", async () => {
  const {
    parseInstallationId,
    isFinishableSetupConnection,
    readyOrganizationAfterSetup,
  } = await import("./dashboard-model.ts?setup-recovery");
  const pending = {
    installation_id: 404,
    organization_id: null,
    status: "setup_required",
    repositories: [{ id: 41, full_name: "acme/pending" }],
  };
  assert.equal(parseInstallationId("404"), 404);
  for (const value of [null, "", "0", "-1", "1.5", "01", "9007199254740992"]) {
    assert.equal(parseInstallationId(value), null);
  }
  assert.equal(isFinishableSetupConnection([pending], 404), true);
  assert.equal(isFinishableSetupConnection([pending], 405), false);
  assert.equal(isFinishableSetupConnection([{ ...pending, status: "ready" }], 404), false);
  assert.equal(isFinishableSetupConnection([{ ...pending, repositories: [] }], 404), false);
  assert.equal(
    isFinishableSetupConnection([{ ...pending, organization_id: "org_caller" }], 404),
    false,
  );

  assert.equal(readyOrganizationAfterSetup([pending], 404), null);
  assert.equal(
    readyOrganizationAfterSetup([{
      ...pending,
      status: "ready",
      organization_id: "org_server_returned",
    }], 404),
    "org_server_returned",
  );
  assert.equal(
    readyOrganizationAfterSetup([{
      ...pending,
      status: "ready",
      organization_id: "",
    }], 404),
    null,
  );
});

// ---------------------------------------------------------------------------
// The front door: which of the four dashboard states a set of connections puts
// a signed-in person in. This exists because the states were an inline ternary
// chain in page.tsx, where `node --test` cannot reach them — and the bug this
// module now guards against lived exactly there: an operator with a bound
// installation whose derived scope had aged past entitlements.TTL was shown the
// never-connected welcome, a claim about them that was false.

const READY = {
  installation_id: 101,
  organization_id: "org_acme",
  account_login: "acme",
  account_type: "Organization",
  status: "ready",
  label: null,
  repositories: [{ id: 11, full_name: "acme/one" }],
};

test("an expired scope is told the truth, never shown the never-connected welcome", async () => {
  const { frontDoor } = await import("./dashboard-model.ts?front-door-expired");
  const expired = { ...READY, status: "reauthorize_required", repositories: [] };

  const door = frontDoor([expired], "org_acme");

  // The whole point: NOT "welcome". This person has a connection; Doug just
  // cannot vouch for its scope any more.
  assert.equal(door.state, "reauthorize");
  assert.deepEqual(door.expired, [expired]);

  // And the truly never-connected case still reaches the welcome, because that
  // state is honest for them.
  assert.equal(frontDoor([], "org_acme").state, "welcome");
  assert.equal(frontDoor([], null).state, "welcome");
  assert.deepEqual(frontDoor([], null).expired, []);
});

test("an expired connection can never become the selected space, even on an exact org match", async () => {
  const { frontDoor } = await import("./dashboard-model.ts?front-door-selection");
  const expired = { ...READY, status: "reauthorize_required", repositories: [] };

  // `organization_id` still matches the session's org claim — the row is bound,
  // it is only the DERIVED SCOPE that died. Selecting it would open a run
  // ledger against a scope the API will refuse anyway (session_auth.py:188
  // fails resolve_session closed on a stale claim), so the honest answer is to
  // refuse it here and say why, not to render a page that 401s underneath.
  const door = frontDoor([expired], "org_acme");
  assert.equal(door.current, null);
  assert.notEqual(door.state, "runs");
});

test("a live connection still opens its ledger, and a stale sibling never blocks it", async () => {
  const { frontDoor } = await import("./dashboard-model.ts?front-door-live");
  const expired = {
    ...READY,
    installation_id: 202,
    organization_id: "org_stale",
    account_login: "stale",
    status: "reauthorize_required",
    repositories: [],
  };

  const door = frontDoor([READY, expired], "org_acme");
  assert.equal(door.state, "runs");
  assert.equal(door.current, READY);
  assert.deepEqual(door.expired, [expired]);

  // Signed in, connections readable, but no org selected yet: still the
  // existing "choose a space" state, not a reauthorize claim.
  const choosing = frontDoor([READY, expired], null);
  assert.equal(choosing.state, "choose");
  assert.equal(choosing.current, null);
});

test("parseFlagLine: 0..1 numbers, '' clears, everything else is invalid", async () => {
  // The FLAG LINE is a setting, not the lens — but it shares the lens's
  // grammar on purpose. `Number()` alone accepts "", " ", "0x1f" and
  // "Infinity", and a percentage typed as "62" would sail through a bare
  // `>= 0` check and silently mean "flag nothing" on every future review of
  // that repository. Refusing it is the only reading that fails closed.
  //
  // The three-way return is the point: "" is a real instruction (clear the
  // override, go back to Doug's defaults) and must never be confused with
  // garbage, which the action refuses outright rather than treating as a clear.
  const { parseFlagLine } = await import("./dashboard-model.ts?flag-line");
  assert.equal(parseFlagLine("0.9"), 0.9);
  assert.equal(parseFlagLine("0"), 0);
  assert.equal(parseFlagLine("1"), 1);
  assert.equal(parseFlagLine(""), null);
  for (const bad of ["62", "1.5", "-0.1", "abc", "0x1", " ", null]) {
    assert.equal(parseFlagLine(bad), undefined, String(bad));
  }
});

test("parseBool: only the two words a checkbox-free toggle can send", async () => {
  // The toggle posts a hidden field carrying the literal "true" or "false" —
  // the OPPOSITE of what the button reads — so those two strings are the whole
  // grammar. Everything else is undefined, meaning INVALID, which the action
  // refuses outright: the same fail-closed reading parseFlagLine takes, and for
  // the same reason. `Boolean("false")` is true, so a parser that leaned on
  // JavaScript's own coercion would turn "off" into "on" and report success.
  const { parseBool } = await import("./dashboard-model.ts?pr-comment-bool");
  assert.equal(parseBool("true"), true);
  assert.equal(parseBool("false"), false);
  for (const bad of ["TRUE", "False", "1", "0", "on", "off", "yes", "", " true", "true ", null, undefined]) {
    assert.equal(parseBool(bad), undefined, String(bad));
  }
});

test("parseGithubRepoId: only a positive safe integer names a repository", async () => {
  // This id is the path segment of a PATCH against another person's data. The
  // API authorises it, but a parser that let "1e3", "0" or a float through
  // would send a request Doug cannot describe — so the id that reaches
  // setRepositoryThreshold is either a real repository id or nothing at all.
  const { parseGithubRepoId } = await import("./dashboard-model.ts?repo-id");
  assert.equal(parseGithubRepoId("42"), 42);
  for (const bad of ["0", "-1", "1.5", "1e3", " 42", "", "abc", null, undefined]) {
    assert.equal(parseGithubRepoId(bad), null, String(bad));
  }
  // Past 2^53 the digits stop naming one integer, so the value cannot be
  // trusted to be the repository the operator was looking at.
  assert.equal(parseGithubRepoId("9007199254740993"), null);
});

test("a connection still waiting on setup outranks a stale one for the front door", async () => {
  const { frontDoor } = await import("./dashboard-model.ts?front-door-setup");
  const pending = {
    ...READY,
    installation_id: 303,
    organization_id: null,
    status: "setup_required",
  };
  const expired = { ...READY, status: "reauthorize_required", repositories: [] };

  // There is something actionable that is not "sign out and back in", so the
  // page must land on the choose state where PendingConnections is rendered —
  // telling this person to re-authenticate would send them away from the button
  // that actually finishes their setup.
  const door = frontDoor([pending, expired], null);
  assert.equal(door.state, "choose");
  assert.deepEqual(door.expired, [expired]);
});

test("a declined session and a dead deployment are never told as the same failure", async () => {
  const { ledgerFailure } = await import("./dashboard-model.ts?ledger-failure-arms");

  // 401 is the only route to `declined`. The arm's copy says a new session
  // renews the token and re-derives the scope, which is advice — so any status
  // that reaches it must actually be a statement about the session.
  assert.equal(ledgerFailure(401), "declined");

  // 503 is a deployment fault, and api/doug/api.py checks for it BEFORE the
  // token precisely so a missing ledger is not reported as a bad credential.
  // Collapsing these two would rebuild that confusion on the front door and
  // send someone to sign out over an operator secret they cannot fix.
  assert.equal(ledgerFailure(503), "unavailable");
  assert.notEqual(ledgerFailure(503), ledgerFailure(401));
});

test("no status Doug did not choose is ever reported as a declined session", async () => {
  const { ledgerFailure } = await import("./dashboard-model.ts?ledger-failure-default");

  // THE CLAIM THIS GUARDS. `sessionJson` throws status:null for a transport
  // failure, a timeout against a cold Cloud Run container, AND a body this
  // build's validator rejects (#149). None of those is a fact about the
  // reader's session, so none may reach an arm that tells them to sign out.
  assert.equal(ledgerFailure(null), "unreachable");

  // Nor may any other code. An allowlist that named only the codes known on
  // the day it was written is how a new failure arrives wearing someone else's
  // explanation; the default is the safe arm, not the interesting one.
  for (const status of [400, 403, 404, 422, 429, 500, 502, 504]) {
    assert.equal(ledgerFailure(status), "unreachable", `status ${status} must claim no cause`);
  }
});
