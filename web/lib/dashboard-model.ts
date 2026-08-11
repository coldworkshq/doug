import { coverageLabel, coveragePercent } from "./coverage";

type FilterableRun = {
  verdict_id: number;
  repo: string;
  band: "flagged" | "cleared";
  tier: string;
  coverage: {
    diff_chars: number;
    sent_chars: number;
    files_sent: number;
    files_unseen: string[];
    file_cut: string | null;
  } | null;
  changed_files: number | null;
  job: { error?: string | null } | null;
};

type SearchValues = Record<string, string | string[] | undefined>;

export type DashboardFilters = {
  repo: string;
  band: "all" | "flagged" | "cleared";
  tier: "all" | "reader" | "deterministic";
  lowCoverage: boolean;
  hasError: boolean;
};

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function dashboardFilters(values: SearchValues): DashboardFilters {
  const band = one(values.band);
  const tier = one(values.tier);
  return {
    repo: one(values.repo) || "all",
    band: band === "flagged" || band === "cleared" ? band : "all",
    tier: tier === "reader" || tier === "deterministic" ? tier : "all",
    lowCoverage: one(values.coverage) === "low",
    hasError: one(values.error) === "yes",
  };
}

export function coverageView(run: Pick<FilterableRun, "coverage" | "changed_files">) {
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

/** Suffix for the run-count line: at the fetch cap, say so — a capped page
 *  presented as a total is the lie the console's CountLine exists to refuse. */
export function capSuffix(fetched: number, limit: number): string {
  return fetched >= limit ? ` · latest ${limit}` : "";
}

export function filterRuns<T extends FilterableRun>(
  rows: T[],
  filters: DashboardFilters,
): T[] {
  return rows.filter((row) => {
    if (filters.repo !== "all" && row.repo !== filters.repo) return false;
    if (filters.band !== "all" && row.band !== filters.band) return false;
    if (filters.tier !== "all" && row.tier !== filters.tier) return false;
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

export type OutcomeTone = "clear" | "flag" | "neutral";

export function outcomeTone(kind: string | null): OutcomeTone {
  if (kind === "clean" || kind === "clear") return "clear";
  if (kind === "revert" || kind === "hotfix") return "flag";
  return "neutral";
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
