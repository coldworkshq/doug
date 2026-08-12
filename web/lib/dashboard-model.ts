import { coverageLabel, coveragePercent } from "./coverage";
import type { ConnectionStatus } from "./session-api";

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
  status: ConnectionStatus;
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

/** Which of the dashboard's four mutually exclusive states a person lands in.
 *  `reauthorize` is the one that did not exist: before it, a connection whose
 *  derived scope had aged out was dropped by the API and the page counted zero
 *  connections, so an operator with a bound installation was told *"You're in.
 *  Connect GitHub only when you want Doug to review repositories."* — a claim
 *  about them that was false, and unrecoverable from that screen. */
export type FrontDoorState = "runs" | "choose" | "reauthorize" | "welcome";

/** The state, the selected connection, and the connections Doug can no longer
 *  vouch for — decided in one place because these three answers have to agree.
 *
 *  PRECEDENCE, and each step is a claim about the person reading the screen:
 *  a live selected space wins (they can work); otherwise anything still usable
 *  wins (they can choose, or finish a setup — sending them to "sign out and
 *  back in" would walk them away from the button that finishes it); only when
 *  nothing is usable does an expired scope become the headline; and only with
 *  no connections at all is the never-connected welcome true.
 *
 *  A `reauthorize_required` connection is DELIBERATELY NOT SELECTABLE. The row
 *  is still bound — `organization_id` may match the session's org claim exactly
 *  — but `api/doug/session_auth.py:188` fails `resolve_session` closed on a
 *  stale claim, so opening its ledger would render a page whose every read 401s.
 *  Refusing it here and saying why is the honest version of what the API is
 *  going to do anyway.
 *
 *  In practice staleness is all-or-nothing per person: `store.py:2882` stamps
 *  every row of one `replace_session_entitlements` call with the same
 *  `derived_at`. The mixed cases below are still handled rather than assumed
 *  away — a partial write is the kind of thing that happens once, at 3am. */
/** One member per state rather than `Exclude<…>` on a shared member: the
 *  discriminant has to be a single literal on each arm for a `state === …`
 *  check to narrow `current` away from null, which is what lets the runs branch
 *  in page.tsx use the selected connection without a null assertion or a dead
 *  `: null` fallback standing in for a case that cannot happen. */
export type FrontDoor<T> =
  | { state: "runs"; current: T; expired: T[] }
  | { state: "choose"; current: null; expired: T[] }
  | { state: "reauthorize"; current: null; expired: T[] }
  | { state: "welcome"; current: null; expired: T[] };

export function frontDoor<T extends ConnectionLike>(
  connections: T[],
  organizationId: string | null | undefined,
): FrontDoor<T> {
  const expired = connections.filter(
    (connection) => connection.status === "reauthorize_required",
  );
  const current =
    connections.find(
      (connection) =>
        connection.status === "ready" &&
        Boolean(connection.organization_id) &&
        connection.organization_id === organizationId,
    ) ?? null;
  if (current) return { state: "runs", current, expired };

  const usable = connections.some(
    (connection) =>
      connection.status === "ready" || connection.status === "setup_required",
  );
  if (usable) return { state: "choose", current: null, expired };
  if (expired.length > 0) return { state: "reauthorize", current: null, expired };
  return { state: "welcome", current: null, expired };
}

export type OutcomeTone = "clear" | "flag" | "neutral";

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
  status: ConnectionStatus;
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
