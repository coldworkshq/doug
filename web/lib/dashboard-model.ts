import { coverageLabel, coveragePercent } from "./coverage";
import { type FacetSelection, matchesFacets, parseFacetSelection } from "./facets";
import type { OutcomeTone } from "./runs-time";
import type { ConnectionStatus, RunSummary } from "./session-api";

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
 *  itself here as the boolean both consumers read.)
 *
 *  `limit > 0` is not defensive noise: with a bare `fetched >= limit`,
 *  `isAtCap(0, 0)` is TRUE, and page.tsx initialises both `limit = 0` and an
 *  empty run list before the fetch. Today the call happens immediately after
 *  `limit = response.limit` (validated 1..500 by the API), so the zero case is
 *  unreachable — but the failure it would produce is a page announcing "latest
 *  0" and marking every PR group's count as a lower bound, i.e. an honesty
 *  claim manufactured out of an uninitialised variable. A cap is a statement
 *  that a real limit was hit; no limit means no cap. */
export function isAtCap(fetched: number, limit: number): boolean {
  return limit > 0 && fetched >= limit;
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

// One declaration, in the module that also holds the two helpers which
// consume it (`outcomeToneClass`, `outcomeLabel` — console's runs.ts keeps all
// three together and so does runs-time.ts). Re-exported because this module is
// where the rule below lives and callers reach for the type beside it.
export type { OutcomeTone } from "./runs-time";

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

/** The GitHub repository id a flag-line form names.
 *
 *  It becomes the path segment of a PATCH, so it is either a real id or
 *  nothing: `0` is not a repository, a float is not an id, and past 2^53 the
 *  digits stop naming one integer. The API authorises the write; this only
 *  refuses to send a request Doug could not describe afterwards. */
export function parseGithubRepoId(value: FormDataEntryValue | null): number | null {
  if (typeof value !== "string" || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/** '' → null (clear the override). A 0..1 decimal → that number. Anything else
 *  → undefined, meaning INVALID, which the action refuses outright.
 *
 *  Three outcomes rather than two because "clear" and "unreadable" are
 *  different instructions and the second must never be performed as the first.
 *
 *  Same grammar as `parseThresholdLens`, deliberately: `Number()` alone accepts
 *  "", " ", "0x1f" and "Infinity", and the range check is what makes "62" —
 *  someone typing the percentage — fail closed instead of quietly meaning
 *  "flag nothing" on every future review of that repository. The lens can
 *  afford to read garbage as absent because it only re-bands a view; this
 *  writes a setting, so garbage is an error, not a default.
 *
 *  CLEAR IS THE EXACT EMPTY STRING, tested BEFORE the trim. `"  "` is not a
 *  clear: nothing in this form can produce it — the reset button carries a
 *  literal `value=""` and a number input submits either "" or digits — so a
 *  blank-looking value arriving here came from somewhere Doug does not model,
 *  and silently reading it as "reset this repository to the defaults" is a
 *  write nobody asked for. Trimming still applies to the numeric path, where
 *  it only forgives padding around a value the person did type. */
export function parseFlagLine(value: FormDataEntryValue | null): number | null | undefined {
  if (typeof value !== "string") return undefined;
  if (value === "") return null;
  const trimmed = value.trim();
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return undefined;
  const n = Number(trimmed);
  return Number.isFinite(n) && n >= 0 && n <= 1 ? n : undefined;
}

/** '"true"' → true. '"false"' → false. Anything else → undefined, meaning
 *  INVALID, which the action refuses outright.
 *
 *  Same fail-closed grammar as `parseFlagLine`, and for the same reason: this
 *  writes a setting. JavaScript's own coercion is the trap — `Boolean("false")`
 *  is `true`, so a parser leaning on it would read "turn the comment off" as
 *  "turn it on" and report success. The two exact words are the entire
 *  vocabulary because the toggle is JS-free and posts a hidden input carrying
 *  one of them; a "1", an "on" or a padded " true" came from somewhere Doug
 *  does not model, and guessing which way it meant is a write nobody asked for. */
export function parseBool(value: FormDataEntryValue | null): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
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
