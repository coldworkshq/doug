import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const rows = [
  {
    verdict_id: 1,
    repo: "acme/one",
    band: "flagged",
    tier: "reader",
    coverage: { diff_chars: 100, sent_chars: 49, files_sent: 2, files_unseen: ["b"], file_cut: "b" },
    changed_files: 4,
    job: { error: null },
  },
  {
    verdict_id: 2,
    repo: "acme/two",
    band: "cleared",
    tier: "deterministic",
    coverage: null,
    changed_files: null,
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
  assert.deepEqual(filters, {
    repo: "all",
    band: "flagged",
    tier: "reader",
    lowCoverage: true,
    hasError: true,
  });
  assert.deepEqual(filterRuns(rows, { ...filters, hasError: false }).map((row) => row.verdict_id), [1]);
});

test("coverage percentage and file ruler use only real denominators", async () => {
  const { coverageView } = await import("./dashboard-model.ts?coverage");
  assert.deepEqual(coverageView(rows[0]), {
    percent: 49,
    chars: "49 of 100 chars",
    files: "2 of 4 files",
    unseen: ["b"],
    fileCut: "b",
  });
  assert.deepEqual(coverageView(rows[1]), {
    percent: null,
    chars: null,
    files: null,
    unseen: [],
    fileCut: null,
  });
  assert.equal(
    coverageView({ ...rows[0], coverage: { ...rows[0].coverage, diff_chars: 0 } }).percent,
    null,
  );
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
  assert.equal(outcomeTone("clean"), "clear");
  assert.equal(outcomeTone("clear"), "clear");
  assert.equal(outcomeTone("revert"), "flag");
  assert.equal(outcomeTone("hotfix"), "flag");
  assert.equal(outcomeTone("scheduled"), "neutral");
  assert.equal(outcomeTone("unknown-future-kind"), "neutral");
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
