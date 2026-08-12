import { coverageLabel, coveragePercent } from "./coverage";
import { type FacetSelection, matchesFacets, parseFacetSelection } from "./facets";
import type { OutcomeTone } from "./runs-time";
import type { RunSummary } from "./session-api";

type SearchValues = Record<string, string | string[] | undefined>;

/** ONE filter model over one query string (RULING 4).
 *
 *  `facets` covers every dimension the pill bar owns — band, tier, read,
 *  outcome — parsed by `parseFacetSelection`, the SAME function that reads the
 *  keys the bar writes. There is deliberately no second parser for `band`: the
 *  bar is multi-select and comma-joins its values, and a `band === "flagged"`
 *  reader beside it would match no run against `flagged,cleared` and blank the
 *  table while the bar claimed two bands were selected.
 *
 *  `repo` is not a facet. It is the SERVER's fetch scope — it decides which
 *  rows are requested, not which of the fetched rows survive — which is why
 *  facets.ts pins that no facet key may ever be named `repo`.
 *
 *  `lowCoverage` and `hasError` stay predicates rather than facets: neither is
 *  a value a run carries on some dimension, and building pills for them would
 *  claim counts over a partition that does not exist. */
export type DashboardFilters = {
  repo: string;
  facets: FacetSelection;
  lowCoverage: boolean;
  hasError: boolean;
};

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function dashboardFilters(values: SearchValues): DashboardFilters {
  return {
    repo: one(values.repo) || "all",
    // A single value parses as a selection of one, so `?band=flagged` — every
    // dashboard link shared before the pill bar existed — returns exactly the
    // rows it always did. Pinned by dashboard-model.test.mjs's own test.
    facets: parseFacetSelection((key) => one(values[key]) ?? null),
    lowCoverage: one(values.coverage) === "low",
    hasError: one(values.error) === "yes",
  };
}

export function coverageView(run: Pick<RunSummary, "coverage" | "changed_files">) {
  const read = run.coverage;
  const result = coveragePercent(read, run.changed_files);
  const percent = result.kind === "known" ? result.pct : null;
  const label = coverageLabel(result);
  if (!read) {
    return { percent, kind: result.kind, label, chars: null, files: null, unseen: [], fileCut: null };
  }
  return {
    percent,
    kind: result.kind,
    label,
    chars: `${read.sent_chars.toLocaleString("en-US")} of ${read.diff_chars.toLocaleString("en-US")} chars`,
    files: run.changed_files === null ? null : `${read.files_sent} of ${run.changed_files} files`,
    unseen: read.files_unseen,
    fileCut: read.file_cut,
  };
}

/** True when the fetched page hit the API's limit, so it holds only the newest
 *  `limit` runs and every count taken over it is a lower bound. At the cap the
 *  count line says "latest 500" INSTEAD of a total — a capped page presented
 *  as a total is the lie the console's CountLine exists to refuse.
 *
 *  One definition, deliberately: that count line and the per-PR group badges'
 *  "8+" are the same claim about the same page, and two independent
 *  `>= limit` comparisons is how a header saying "latest 500" ends up above a
 *  table whose badges claim exact totals.
 *
 *  (This replaced `capSuffix`, which returned the suffix as a string. Phase B
 *  PR 2 moved the wording into the page's CountLine — the console's, so the
 *  two surfaces report one ledger identically — leaving the honesty rule
 *  itself here as the boolean both consumers read.) */
export function isAtCap(fetched: number, limit: number): boolean {
  return fetched >= limit;
}

export function filterRuns<T extends RunSummary>(
  rows: T[],
  filters: DashboardFilters,
): T[] {
  return rows.filter((row) => {
    if (filters.repo !== "all" && row.repo !== filters.repo) return false;
    if (!matchesFacets(row, filters.facets)) return false;
    if (filters.lowCoverage) {
      const result = coveragePercent(row.coverage, row.changed_files);
      if (!(result.kind === "known" && result.low)) return false;
    }
    if (filters.hasError && !row.job?.error) return false;
    return true;
  });
}

type ConnectionLike = {
  organization_id: string | null;
  account_login: string;
  account_type: "User" | "Organization";
  label: string | null;
  status: "ready" | "setup_required";
  repositories: Array<{ full_name: string }>;
};

export function connectionOptions(connections: ConnectionLike[]) {
  return connections
    .filter((connection) => connection.status === "ready" && connection.organization_id)
    .map((connection) => ({
      value: connection.organization_id as string,
      login: connection.account_login,
      label: connection.label,
      accountType: connection.account_type,
    }));
}

export function repositoryOptions(connection: ConnectionLike) {
  return [
    { value: "all", label: "all repositories" },
    ...connection.repositories.map((repository) => ({
      value: repository.full_name,
      label: repository.full_name,
    })),
  ];
}

// One declaration, in the module that also holds the two helpers which
// consume it (`outcomeToneClass`, `outcomeLabel` — console's runs.ts keeps all
// three together and so does runs-time.ts). Re-exported because this module is
// where the rule below lives and callers reach for the type beside it.
export type { OutcomeTone } from "./runs-time";

/** One tone rule over the vocabulary the adjudicator actually writes —
 *  `api/doug/adjudicate.py`'s `OutcomeKind`: revert | clean | censored. The
 *  column also permits `hotfix`, which the adjudicator never writes because
 *  §10 of docs/design/outcome-loop/publication-preregistration.md rules that a
 *  hotfix is not a miss and that no detector here can tell one repairing this
 *  PR from one merely following it; it still flags if a row ever carries it.
 *
 *  `censored` is neutral, not flagged: it records that the PR left the risk
 *  set UNOBSERVED — the merge landed off the branch the treeless clone can
 *  see, or no clone was reachable at all. Painting a non-observation in the
 *  miss colour is the honesty failure this rule exists to refuse.
 *
 *  Everything else flags, including kinds this build has never heard of: an
 *  allowlist here is what let a genuinely bad outcome arrive looking neutral.
 *
 *  `console/lib/runs.ts` carries an identical copy — separate workspaces, no
 *  shared package. The two are held together by
 *  `web/lib/outcome-tone-parity.test.mjs`, which imports both and asserts
 *  they agree over the whole vocabulary. Edit this function and that test
 *  fails until the console's copy moves with it; that is the point, so do
 *  not "fix" it by relaxing the comparison. Neither workspace's own tests can
 *  see a divergence — both stayed green through exactly that split once. */
export function outcomeTone(kind: string | null): OutcomeTone {
  if (kind === null) return "neutral";
  if (kind === "clean") return "clear";
  if (kind === "censored") return "neutral";
  return "flag";
}

type SetupConnectionLike = {
  installation_id: number;
  organization_id: string | null;
  status: "ready" | "setup_required";
  repositories: Array<unknown>;
};

export function parseInstallationId(value: unknown): number | null {
  if (typeof value !== "string" || !/^[1-9]\d*$/.test(value)) return null;
  const installationId = Number(value);
  return Number.isSafeInteger(installationId) ? installationId : null;
}

export function isFinishableSetupConnection(
  connections: SetupConnectionLike[],
  installationId: number,
): boolean {
  return connections.some((connection) =>
    connection.installation_id === installationId &&
    connection.status === "setup_required" &&
    connection.organization_id === null &&
    connection.repositories.length > 0
  );
}

export function readyOrganizationAfterSetup(
  connections: SetupConnectionLike[],
  installationId: number,
): string | null {
  const connection = connections.find((candidate) =>
    candidate.installation_id === installationId &&
    candidate.status === "ready" &&
    typeof candidate.organization_id === "string" &&
    candidate.organization_id.length > 0 &&
    candidate.repositories.length > 0
  );
  return connection?.organization_id || null;
}
