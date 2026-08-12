import { withAuth } from "@workos-inc/authkit-nextjs";
import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { signOutAction } from "@/app/auth/actions";
import { BandChip } from "@/components/band-chip";
import { CoverageRuler } from "@/components/coverage-ruler";
import { DougLogo } from "@/components/doug-logo";
import { RunSpine } from "@/components/run-spine";
import { ThresholdGear } from "@/components/threshold-gear";
import { Table, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SCOPE_UNCONFIRMED_COOKIE } from "@/lib/entitlements";
import {
  coverageView,
  dashboardFilters,
  filterRuns,
  frontDoor,
  isAtCap,
  outcomeTone,
  repositoryOptions,
} from "@/lib/dashboard-model";
import {
  carriedParams,
  facetClearChanges,
  facetToggleChanges,
  predicateChanges,
  sortChanges,
  thresholdChanges,
  withSelectedOptions,
} from "@/lib/dashboard-view";
import { type Facet, type FacetSelection, buildFacets } from "@/lib/facets";
import { type PrGroup, groupRunsByPr, runCountLabel } from "@/lib/grouping";
import { type PageWindow, pageRangeLabel, pageSlice, parsePage } from "@/lib/paging";
import { outcomeLabel, outcomeToneClass, relativeAge } from "@/lib/runs-time";
import { filterRunsByQuery, normalizeQuery } from "@/lib/search";
import { type SortKey, type SortState, nextSort, parseSort, sortGroups } from "@/lib/sorting";
import { applyLens, parseThresholdLens, rebandedCount } from "@/lib/threshold-lens";
import {
  getConnections,
  getSessionRun,
  getSessionRuns,
  type RepositoryConnection,
  type RunDetail,
  type RunSummary,
} from "@/lib/session-api";

import { finishSetupAction, switchConnectionAction } from "./actions";

const LEMA_LABEL = "Lema — separate product";

/** The reference canvas width the whole design was measured at. Every band
 *  that spans the viewport centres its content on it, which is why it repeats
 *  rather than living on one outer wrapper: the header's and the tab strip's
 *  hairlines run edge to edge while their contents stop here. */
const CANVAS = "mx-auto w-full max-w-[1440px]";

/** A bordered control that wraps a <select>. The focus ring is on the wrapper,
 *  not the select, because the label and its value read as one control — and
 *  it is not optional: this is what changes whose data you are looking at. */
const SWITCH_CONTROL =
  "mono flex min-h-[30px] items-center gap-[7px] rounded-[5px] border border-border bg-card px-2 py-1 " +
  "focus-within:border-[var(--iridescent)] focus-within:outline-2 focus-within:outline-offset-2 " +
  "focus-within:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]";

const SWITCH_LABEL = "text-[10px] uppercase tracking-[.11em] text-muted-foreground";

const SWITCH_SELECT =
  "max-w-[270px] max-[900px]:max-w-[180px] border-0 bg-transparent text-[12.5px] text-foreground outline-0";

const SUBMIT_BUTTON =
  "mono cursor-pointer rounded-[4px] border border-border bg-card px-2 py-[5px] text-[11.5px] " +
  "text-muted-foreground hover:border-[var(--iridescent)] hover:text-foreground " +
  "focus-visible:border-[var(--iridescent)] focus-visible:text-foreground";

/** Hoisted so the link's own tag stays short and legible. The reachability
 *  pin in lib/dashboard-contract.test.mjs deliberately does NOT read this
 *  string — it pins the href and the label, so restyling the link can never
 *  fail an ordering guarantee. */
const CONNECT_LINK =
  "mono text-[11.5px] text-[var(--iridescent)] underline underline-offset-[3px] max-[900px]:ml-auto " +
  "focus-visible:outline-2 focus-visible:outline-offset-[3px] " +
  "focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]";

const TAB =
  "mono -mb-px border-b-2 border-transparent px-[13px] pt-[9px] pb-2 text-[11.5px] uppercase " +
  "tracking-[.08em] text-[var(--dim)] no-underline aria-[current]:border-b-[var(--iridescent)] " +
  "aria-[current]:font-semibold aria-[current]:text-foreground";

/** The evidence pane's section headings. The `<span>` inside each one is a
 *  provenance sub-label, styled here rather than at the call site so the
 *  headings' own markup stays the plain sentence it claims to be. */
const BLOCK_HEADING =
  "mono mb-3 flex items-center gap-2.5 text-[11px] font-medium uppercase tracking-[.16em] " +
  "text-muted-foreground [&_span]:text-[9.5px] [&_span]:normal-case [&_span]:tracking-[.04em] " +
  "[&_span]:text-[var(--dim)]";

const BLOCK = "border-b border-border py-[22px]";

/** The route chip — a monospace breadcrumb in the accent wash. */
const ROUTE = "rounded-[3px] bg-accent px-[7px] py-0.5 text-[var(--iridescent)] tracking-[.06em]";

const EMPTY_PAGE = "mx-auto max-w-[760px] px-6 py-[110px]";
const EMPTY_HEADING =
  "font-heading mt-[18px] text-[clamp(36px,7vw,64px)] font-semibold tracking-[-.05em]";
const EMPTY_BODY = "mt-4 max-w-[620px] text-base text-muted-foreground";

const EMPTY_NOTE = "text-xs text-muted-foreground";

/** A finding or a deviation: the marker column, then the rule and its words. */
const FINDING = "grid grid-cols-[62px_minmax(0,1fr)] gap-3 border-t border-[var(--rule-soft)] py-[11px]";

type DashboardParams = Record<string, string | string[] | undefined>;

function value(params: DashboardParams, key: string): string | undefined {
  const found = params[key];
  return Array.isArray(found) ? found[0] : found;
}

function href(params: DashboardParams, changes: Record<string, string | null>): string {
  const next = new URLSearchParams();
  for (const [key, raw] of Object.entries(params)) {
    const item = Array.isArray(raw) ? raw[0] : raw;
    if (item) next.set(key, item);
  }
  for (const [key, item] of Object.entries(changes)) {
    if (item === null) next.delete(key);
    else next.set(key, item);
  }
  const query = next.toString();
  return query ? `/dashboard?${query}` : "/dashboard";
}

function connectionLabel(connection: RepositoryConnection): string {
  const label = connection.account_login.toLowerCase() === "lemahq"
    ? LEMA_LABEL
    : connection.label;
  return label ? `${connection.account_login} · ${label}` : connection.account_login;
}

function ScopePicker({
  connections,
  current,
}: {
  connections: RepositoryConnection[];
  current: RepositoryConnection | null;
}) {
  const ready = connections.filter(
    (connection) => connection.status === "ready" && connection.organization_id,
  );
  if (ready.length === 0) return null;
  return (
    <form action={switchConnectionAction} className="flex items-center gap-1.5">
      <label className={SWITCH_CONTROL}>
        <span className={SWITCH_LABEL}>space</span>
        <select
          name="organization_id"
          defaultValue={current?.organization_id ?? ""}
          aria-label="Connected space"
          className={SWITCH_SELECT}
        >
          {!current && <option value="" disabled>choose</option>}
          {ready.map((connection) => (
            <option key={connection.installation_id} value={connection.organization_id ?? ""}>
              {connectionLabel(connection)}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className={SUBMIT_BUTTON}>open</button>
    </form>
  );
}

function PendingConnections({ connections }: { connections: RepositoryConnection[] }) {
  const pending = connections.filter(
    (connection) => connection.status === "setup_required",
  );
  if (pending.length === 0) return null;
  return (
    <section
      className="mono mx-auto grid w-full max-w-[1400px] grid-cols-[210px_minmax(0,1fr)] gap-[18px] border-b border-border bg-background/[.91] px-5 py-2.5 max-[900px]:grid-cols-1"
      aria-labelledby="pending-connections-title"
    >
      <div className="flex flex-col justify-center gap-[3px]">
        <span id="pending-connections-title" className="text-[10.5px] uppercase tracking-[.12em] text-[var(--iridescent)]">setup required</span>
        <small className="text-[10.5px] leading-[1.35] text-muted-foreground">Finish binding these installations before opening their run ledger.</small>
      </div>
      <div className="flex flex-col">
        {pending.map((connection) => (
          <div
            className="flex min-h-[38px] items-center justify-between gap-4 border-t border-[var(--rule-soft)] py-[5px] first:border-t-0"
            key={connection.installation_id}
          >
            <span className="flex min-w-0 flex-col gap-0.5">
              <strong className="truncate text-[11.5px] font-medium">{connectionLabel(connection)}</strong>
              <small className="text-[10.5px] text-muted-foreground">{connection.account_type.toLowerCase()} · {connection.repositories.length} repositories</small>
            </span>
            <form action={finishSetupAction}>
              <input type="hidden" name="installation_id" value={connection.installation_id} />
              <button
                type="submit"
                className="cursor-pointer rounded-[3px] border border-[var(--iridescent)] bg-transparent px-2 py-[5px] text-[10.5px] uppercase text-[var(--iridescent)] hover:bg-accent focus-visible:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_30%,transparent)]"
              >finish setup</button>
            </form>
          </div>
        ))}
      </div>
    </section>
  );
}

function FilterChip({
  active,
  children,
  target,
}: {
  active: boolean;
  children: React.ReactNode;
  target: string;
}) {
  return (
    <Link
      className="mono rounded-[4px] border border-border bg-card px-[9px] py-1 text-[12px] text-muted-foreground no-underline hover:border-[var(--iridescent)] hover:text-foreground [&[data-active]]:border-foreground [&[data-active]]:bg-foreground [&[data-active]]:text-background"
      data-active={active || undefined}
      href={target}
    >{children}</Link>
  );
}

/** The read column's miniature of the forensic ruler. Coverage is a magnitude:
 *  it renders on globals' neutral sequential ramp (.cov-track / .cov-fill) and
 *  never on --flag or --clear. Low coverage is alarmed by how empty the track
 *  looks, not by hue — the same rule CoverageRuler's cut marker follows. */
function CoverageCell({ run }: { run: RunSummary }) {
  const view = coverageView(run);
  if (view.kind === "no-read") return <span className="mono text-[11.5px] text-muted-foreground">no read</span>;
  return (
    <div className="mono flex items-center gap-[7px] text-[11.5px] text-foreground" title={view.chars ?? undefined}>
      <span className="cov-track block h-1.5 w-[62px]">
        <span className="cov-fill block h-full" style={{ width: `${view.percent ?? 0}%` }} />
      </span>
      <span>{view.label}</span>
    </div>
  );
}

/** The pill row above the table — console's FacetBar, adapted from a client
 *  component to a server one (RULING 2). Each pill is a <Link> whose target is
 *  computed by `facetToggleChanges`, so the selection stays in the URL and
 *  survives being copied to someone else; console's version writes the same
 *  query string with `history.pushState` instead.
 *
 *  These are NOT the scope controls in the header. Scope (`?repo=`) decides
 *  what the server fetches; these narrow what was already fetched. Keeping
 *  them visually distinct — a flat row under the header rather than bordered
 *  controls in the bar — is what stops an operator reading a pill as a change
 *  of scope.
 *
 *  Counts are over the FULL fetched set, so they do not move as other pills
 *  are pressed, and their denominator is that same set. At the page cap the
 *  set is only the newest N runs, and the title says so rather than calling it
 *  the scope. */
function FacetBar({
  facets,
  selection,
  totalFetched,
  atCap,
  params,
}: {
  facets: Facet[];
  selection: FacetSelection;
  totalFetched: number;
  atCap: boolean;
  params: DashboardParams;
}) {
  if (facets.length === 0) return null;
  const active = Object.values(selection).some((values) => values && values.length > 0);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border py-3">
      {facets.map((facet) => (
        <div key={facet.key} className="flex flex-wrap items-center gap-1.5">
          <span className="mono text-[11px] uppercase tracking-[.13em] text-muted-foreground">{facet.label}</span>
          {facet.options.map((option) => {
            const on = (selection[facet.key] ?? []).includes(option.value);
            // Frame and ink are computed separately and each utility is
            // emitted exactly once. Concatenating a second `text-*` onto a
            // string that already has one does NOT override it — Tailwind
            // resolves that collision by stylesheet order, not by the order of
            // the class attribute.
            const frame = on
              ? "border-[var(--iridescent)] bg-accent"
              : "border-border bg-card hover:border-[var(--iridescent)]";
            // The two data colours, each still carrying its word — the pill's
            // label IS the secondary encoding the CVD floor requires, exactly
            // as in BandChip. No third data colour enters here: every other
            // facet stays on ink.
            // A pill for a value the data does not carry (count 0, appended by
            // withSelectedOptions) takes NO data colour: `?band=foo` is not a
            // band, and painting it clear-green would assert a verdict about a
            // value no run has. It stays on ink and its 0 does the talking.
            const known = option.value === "flagged" || option.value === "cleared";
            const ink = facet.key === "band" && known
              ? (option.value === "flagged" ? "text-[var(--flag)]" : "text-[var(--clear)]")
              : on ? "text-foreground" : "text-muted-foreground";
            return (
              <Link
                key={option.value}
                href={href(params, facetToggleChanges(selection, facet.key, option.value))}
                aria-current={on ? "true" : undefined}
                title={atCap
                  ? `${option.count} of the newest ${totalFetched} runs fetched — the scope may hold more`
                  : `${option.count} of ${totalFetched} runs in scope`}
                className={`mono inline-flex items-center gap-1.5 rounded-[4px] border px-[7px] py-[3px] text-[12px] no-underline ${frame} ${ink}`}
              >
                {option.label}
                <span className="text-[11px] tabular-nums opacity-60">{option.count}</span>
              </Link>
            );
          })}
        </div>
      ))}
      {active && (
        <Link
          href={href(params, facetClearChanges())}
          className="mono ml-auto text-[11.5px] uppercase tracking-[.1em] text-muted-foreground underline decoration-dotted underline-offset-[3px] hover:text-foreground"
        >clear filters</Link>
      )}
    </div>
  );
}

/** Filter/fetched totals, not the viewport. The pager below the table states
 *  "showing X–Y of Z"; this answers how many runs survived the filters across
 *  the whole fetched set.
 *
 *  `total` is the fetched set and `shown` is what survived; at the cap neither
 *  is a count of the scope, which is why "latest {limit}" REPLACES a bare total
 *  rather than qualifying it in a tooltip. Same numbers and same words as
 *  console's CountLine, so the two surfaces cannot report one ledger
 *  differently. */
/** The lens, said out loud.
 *
 *  `--iridescent` and `bg-accent` — chrome, never `--flag`/`--clear`. The two
 *  data colours are verdicts, and which line the reader is *looking through* is
 *  not one. A banner painted in the miss colour would read as an alarm about
 *  the runs rather than a statement about the view.
 *
 *  The reset is a <Link> to `thresholdChanges(null)`, so it works with no
 *  JavaScript at all — which matters here more than anywhere else on the page,
 *  because the gear that SETS the lens is a Radix popover and does not. An
 *  active lens must always be clearable by whoever is looking at it. */
function LensBanner({
  lens,
  reband,
  params,
}: {
  lens: number;
  reband: number;
  params: DashboardParams;
}) {
  return (
    <div className="mono flex flex-wrap items-center gap-x-2 gap-y-1 rounded-[5px] border border-[var(--iridescent)] bg-accent px-3 py-2 text-[11px] text-foreground">
      <span className="font-medium text-[var(--iridescent)]">Viewing at {lens.toFixed(2)}</span>
      <span className="text-muted-foreground">
        {/* The count is of rows the lens MOVED, not of rows it flagged — the
            size of the lens's effect, so the banner cannot report a ledger's
            normal state as though this control had caused it. */}
        Doug scored these against its own line — <b className="font-medium text-foreground">{reband}</b>
        {reband === 1 ? " row" : " rows"} re-banded by this view.
      </span>
      <Link
        href={href(params, thresholdChanges(null))}
        className="ml-auto underline decoration-dotted underline-offset-[3px] hover:text-[var(--iridescent)] max-[900px]:ml-0"
      >Clear the lens</Link>
    </div>
  );
}

function CountLine({
  shown,
  total,
  groups,
  limit,
  atCap,
  filtering,
}: {
  shown: number;
  total: number;
  groups: number;
  limit: number;
  atCap: boolean;
  filtering: boolean;
}) {
  const prs = <> across <b className="text-foreground">{groups}</b> {groups === 1 ? "pr" : "prs"}</>;
  const fetched = atCap
    ? <>the latest <b className="text-foreground">{limit}</b></>
    : <b className="text-foreground">{total}</b>;
  if (filtering) {
    return <span><b className="text-foreground">{shown}</b> of {fetched} runs{prs} · filters live in the URL</span>;
  }
  return (
    <span>
      {atCap ? <>latest <b className="text-foreground">{limit}</b></> : <b className="text-foreground">{total}</b>}
      {" "}runs{prs} · filters live in the URL
    </span>
  );
}

/** Column widths are the console's, not the deleted module's. They travel with
 *  the cell components this table now renders: band is 112px because BandChip's
 *  "needs you" wrapped to two lines at 96 and dragged every flagged row taller
 *  than its neighbours.
 *
 *  Only three columns are sortable. band, tier and outcome are categories, and
 *  sorting a category alphabetically implies a ranking that does not exist —
 *  narrowing those is what the pills do. */
const COLUMNS: Array<{ label: string; cls: string; sort?: SortKey }> = [
  { label: "score", cls: "w-[78px] text-right", sort: "score" },
  { label: "pull request", cls: "" },
  { label: "band", cls: "w-[112px]" },
  { label: "tier", cls: "w-[88px]" },
  { label: "read", cls: "w-[176px]", sort: "coverage" },
  { label: "outcome", cls: "w-[104px]" },
  { label: "job", cls: "w-[118px]" },
  { label: "age", cls: "w-[54px] text-right", sort: "age" },
];

/** The header is STICKY inside the bounded container, so it needs its own
 *  opaque background — a transparent header lets the rows scroll visibly
 *  underneath it. `--background` rather than `--card`: the ledger sits directly
 *  on the dashboard surface, not on a panel.
 *
 *  The bottom border is on the cell rather than the row because the table uses
 *  the SEPARATED border model (see RunTable): in the collapsed model the
 *  border belongs to the table, and a sticky header leaves it behind. */
const TH =
  "mono sticky top-0 z-10 border-b border-border bg-background px-2.5 pt-2 pb-[7px] text-left " +
  "text-[11px] font-medium uppercase tracking-[.13em] text-muted-foreground";
const TD = "h-10 border-b border-[var(--rule-soft)] px-2.5 align-middle";

/** The eight cells of one run. Children render the identical columns — an
 *  older run is a full verdict, not a summary of one — and are marked as
 *  history by indentation and a tint, never by dropping data. */
function RunCells({
  run,
  params,
  disclosure = null,
  indented = false,
}: {
  run: RunSummary;
  params: DashboardParams;
  disclosure?: React.ReactNode;
  indented?: boolean;
}) {
  return (
    <>
      <TableCell className={`${TD} text-right`}>
        <span className={"mono text-[16px] font-semibold " + (run.band === "flagged" ? "data-flag" : "data-clear")}>
          {run.score.toFixed(2)}
        </span>
      </TableCell>
      <TableCell className={`${TD} min-w-0`}>
        <div className="flex min-w-0 items-baseline gap-2">
          {/* The slot reserves its width whether or not a control lives in it,
              so a PR with history and a PR without still start their repo name
              at the same x. */}
          <span className="min-w-[38px] flex-none text-right">{disclosure}</span>
          {indented ? (
            // A child row's repo, number and title are its parent's, verbatim.
            // What distinguishes one run of a PR from the next is WHEN it ran,
            // so that is what the cell carries — still linking to this run's
            // own evidence.
            <Link className="mono truncate pl-3 text-[11.5px] text-muted-foreground no-underline hover:text-foreground" href={href(params, { run: String(run.verdict_id) })}>
              {relativeAge(run.scored_at)} ago
            </Link>
          ) : (
            <Link className="flex min-w-0 items-baseline gap-2 text-inherit no-underline" href={href(params, { run: String(run.verdict_id) })}>
              <span className="mono flex-none text-[11.5px] text-muted-foreground"><b className="font-medium text-foreground">{run.repo}</b> #{run.pr_number}</span>
              <strong className="min-w-0 flex-1 truncate text-[14px] font-normal">{run.title}</strong>
            </Link>
          )}
        </div>
      </TableCell>
      <TableCell className={TD}><BandChip band={run.band} /></TableCell>
      <TableCell className={`mono ${TD} text-[11.5px] text-muted-foreground`}>{run.tier}</TableCell>
      <TableCell className={TD}><CoverageCell run={run} /></TableCell>
      <TableCell className={`mono ${TD} text-[13px]`}>
        <span className={outcomeToneClass(outcomeTone(run.outcome_14))}>{outcomeLabel(run.outcome_14)}</span>
      </TableCell>
      <TableCell className={`mono ${TD} text-[11.5px] ` + (run.job?.error ? "data-flag" : "text-muted-foreground")}>
        {run.job?.error ? `${run.job.attempts}× · ${run.job.error}` : (run.job?.status ?? "—")}
      </TableCell>
      <TableCell className={`mono ${TD} text-right text-[11.5px] text-muted-foreground`}>{relativeAge(run.scored_at)}</TableCell>
    </>
  );
}

function RunTable({
  window,
  params,
  sort,
  filtering,
}: {
  window: PageWindow<PrGroup>;
  params: DashboardParams;
  sort: SortState;
  filtering: boolean;
}) {
  return (
    // The vertical bound is the point of this container: 50 rows of ledger
    // pushed the evidence pane a full screen below the fold, so opening a run
    // scrolled the thing you were reading out of view. 55vh keeps both on
    // screen. The horizontal scroll it already had is unchanged — eight
    // columns still do not fit below 980px.
    <Table
      containerClassName="max-h-[55vh] overflow-y-auto rounded-[5px] border border-border"
      className="min-w-[980px] table-fixed border-separate border-spacing-0 text-xs"
    >
      {/* TH (below) is what makes this header sticky — `sticky top-0` plus the
          opaque background it needs so rows don't scroll visibly underneath it.
          See TH's own doc comment for why that pin lives on the cell. */}
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {COLUMNS.map((column) => (
            <TableHead
              key={column.label}
              aria-sort={column.sort === undefined
                ? undefined
                : sort.key === column.sort ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
              className={`${TH} ${column.cls}`}
            >
              {column.sort === undefined ? column.label : (
                <Link
                  href={href(params, sortChanges(nextSort(sort, column.sort)))}
                  className={"inline-flex items-center gap-1 no-underline hover:text-foreground " + (sort.key === column.sort ? "text-foreground" : "")}
                >
                  {column.label}
                  <span aria-hidden className="text-[10px] opacity-70">
                    {sort.key === column.sort ? (sort.dir === "desc" ? "▾" : "▴") : "▿"}
                  </span>
                </Link>
              )}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      {window.items.map((group) => {
        const count = runCountLabel(group, filtering);
        // A PR with one run gets NO control and NO badge. A chevron that
        // expands to nothing claims there is more to see, and "1" beside
        // every single-run row is noise standing in for information.
        const hasHistory = group.children.length > 0;
        // Each PR group is its own <tbody> — several are valid in one table —
        // so the :has() disclosure selector never reaches past its own group.
        // TableBody is NOT used here: it ships `[&_tr:last-child]:border-0`,
        // which would strip the divider from the last row of every group
        // rather than from the last row of the table.
        return (
          <tbody key={group.key} className="pr-group">
            <TableRow className="border-0 hover:bg-[var(--row-hover)]">
              <RunCells
                run={group.latest}
                params={params}
                disclosure={hasHistory ? (
                  <label
                    title={count.title}
                    className="pr-disclosure mono inline-flex cursor-pointer items-center gap-1 rounded-[3px] px-1.5 py-1 text-[11px] leading-none text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    <input
                      type="checkbox"
                      className="pr-toggle sr-only"
                      aria-label={`Show the ${count.title} on ${group.repo} #${group.prNumber}`}
                    />
                    <span aria-hidden className="pr-caret-closed">▸</span>
                    <span aria-hidden className="pr-caret-open">▾</span>
                    {count.text}
                  </label>
                ) : null}
              />
            </TableRow>
            {group.children.map((child) => (
              <TableRow key={child.verdict_id} className="pr-history border-0 bg-muted/40">
                <RunCells run={child} params={params} indented />
              </TableRow>
            ))}
          </tbody>
        );
      })}
    </Table>
  );
}

function Pager({ window, params }: { window: PageWindow<PrGroup>; params: DashboardParams }) {
  const label = pageRangeLabel(window);
  if (window.pageCount <= 1) {
    return <p className="mono mt-3 text-[11.5px] uppercase tracking-[.12em] text-muted-foreground">Showing {label}</p>;
  }
  const step = (page: number) => href(params, { page: page <= 1 ? null : String(page) });
  const control = "rounded-[4px] border border-border px-2 py-1 no-underline";
  return (
    <div className="mono mt-3 flex flex-wrap items-center gap-3 text-[11.5px] uppercase tracking-[.12em] text-muted-foreground">
      <span>Showing {label}</span>
      <span className="h-px flex-1 bg-border" />
      {/* At a boundary the control renders as text, not a disabled link: a
          <Link> cannot be disabled, and one that navigates to the page you are
          already on is a control that lies about having an effect. */}
      {window.page <= 1
        ? <span className={`${control} opacity-40`}>Prev</span>
        : <Link href={step(window.page - 1)} className={`${control} hover:text-foreground`}>Prev</Link>}
      <span>Page {window.page} / {window.pageCount}</span>
      {window.page >= window.pageCount
        ? <span className={`${control} opacity-40`}>Next</span>
        : <Link href={step(window.page + 1)} className={`${control} hover:text-foreground`}>Next</Link>}
    </div>
  );
}

function Evidence({ detail, summary }: { detail: RunDetail; summary: RunSummary }) {
  return (
    <section className={`${CANVAS} px-5 pt-[18px] pb-12`} aria-labelledby="run-evidence-title">
      <header className="flex items-end justify-between gap-6 border-t border-border pt-4 pb-[22px] max-[900px]:flex-col max-[900px]:items-start">
        <div>
          <p className="mono mb-[7px] text-[11.5px] text-muted-foreground">/runs/{detail.verdict_id} · {detail.repo} · #{detail.pr_number}</p>
          <h2 id="run-evidence-title" className="font-heading max-w-[980px] text-[clamp(22px,2.2vw,30px)] font-semibold leading-[1.1] tracking-[-.035em]">{summary.title}</h2>
        </div>
        <div className="mono flex flex-none flex-col items-end max-[900px]:items-start">
          <strong className={"text-[36px] font-medium " + (detail.band === "flagged" ? "data-flag" : "data-clear")}>
            {detail.score.toFixed(2)}
          </strong>
          <span className="text-[10.5px] text-muted-foreground">{detail.band === "flagged" ? "needs you" : "cleared"} · threshold {detail.threshold.toFixed(2)}</span>
        </div>
      </header>

      <div className="grid grid-cols-1 border-t border-border lg:grid-cols-[230px_minmax(0,1fr)]">
        <RunSpine run={detail} />

        <div className="min-w-0 lg:pl-6">
          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>What the reader was given <span>reader evidence</span></h3>
            {detail.coverage ? (
              // changed_files comes off the summary row, the same denominator
              // the read column above used for this run — one number, so the
              // table and the pane can never print two different rates for it.
              <CoverageRuler
                coverage={detail.coverage}
                changedFiles={summary.changed_files}
                filesDropped={detail.pr?.files_dropped ?? []}
              />
            ) : <p className={EMPTY_NOTE}>No reader coverage was recorded for this run.</p>}
          </section>

          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>The read</h3>
            <dl className="mono grid grid-cols-[130px_1fr] gap-x-[18px] gap-y-2 text-[12px]">
              <dt className="uppercase text-muted-foreground">tier</dt><dd className="m-0 whitespace-pre-wrap">{detail.tier}</dd>
              <dt className="uppercase text-muted-foreground">model</dt><dd className="m-0 whitespace-pre-wrap">{detail.model ?? "not recorded"}</dd>
              <dt className="uppercase text-muted-foreground">prompt hash</dt><dd className="m-0 whitespace-pre-wrap">{detail.prompt_hash ?? "not stamped"}</dd>
              <dt className="uppercase text-muted-foreground">risk score</dt><dd className="m-0 whitespace-pre-wrap">{detail.risk_score ?? "not recorded"}</dd>
              <dt className="uppercase text-muted-foreground">head sha</dt><dd className="m-0 whitespace-pre-wrap">{detail.head_sha ?? "not recorded"}</dd>
              <dt className="uppercase text-muted-foreground">rationale</dt><dd className="m-0 whitespace-pre-wrap">{detail.rationale ?? "No rationale was recorded."}</dd>
            </dl>
          </section>

          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>Findings <span>{detail.reasons.length}</span></h3>
            {detail.reasons.map((reason) => (
              <div className={FINDING} key={`${reason.rule}-${reason.label}`}>
                <span className="mono data-flag text-[10.5px] uppercase">{reason.severity ?? "rule"}</span>
                <div><code className="mono text-[11.5px]">{reason.rule}</code><p className="mt-[3px] text-[13px] text-muted-foreground">{reason.label}</p></div>
              </div>
            ))}
            {detail.reasons.length === 0 && <p className={EMPTY_NOTE}>No findings recorded.</p>}
          </section>

          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>Deviations <span>separate stream</span></h3>
            {detail.deviations.map((deviation) => (
              <div className={FINDING} key={`${deviation.type}-${deviation.description}`}>
                <span className="mono data-flag text-[10.5px] uppercase">{deviation.severity}</span>
                <div><code className="mono text-[11.5px]">{deviation.type}</code><p className="mt-[3px] text-[13px] text-muted-foreground">{deviation.description}</p></div>
              </div>
            ))}
            {detail.deviations.length === 0 && <p className={EMPTY_NOTE}>No deviations recorded.</p>}
          </section>

          <section className={BLOCK}>
            <h3 className={BLOCK_HEADING}>Outcome</h3>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-2.5">
              {detail.outcomes.map((outcome) => (
                <div key={`${outcome.window_days}-${outcome.observed_at}`} className="flex flex-col border border-border bg-card p-3">
                  <span className="mono text-[10.5px] text-muted-foreground">{outcome.window_days ?? "?"}-day window</span>
                  {/* Tone and word both come from the shared rule, so this tile
                      and the outcome column above cannot describe the same row
                      differently — and neither can the console, which renders
                      through the very same two functions. */}
                  <strong className={"mono my-1 text-[16px] " + outcomeToneClass(outcomeTone(outcome.kind))}>{outcomeLabel(outcome.kind)}</strong>
                  <small className="mono text-[10.5px] text-muted-foreground">observed {new Date(outcome.observed_at).toLocaleDateString()}</small>
                </div>
              ))}
              {detail.outcomes.length === 0 && <p className={EMPTY_NOTE}>No outcome recorded yet.</p>}
            </div>
          </section>
        </div>
      </div>
    </section>
  );
}

/** The state that used to be silence. The API can still see these connections;
 *  what expired is the repository scope derived from GitHub at sign-in, which
 *  `entitlements.TTL` caps at 8h. Showing the connection and naming what went
 *  stale is the whole point — the alternative, shipped until now, was to drop
 *  these rows and greet a bound operator as though they had never connected.
 *
 *  No repository names are listed, and that is not an oversight: the API sends
 *  none for an expired connection, because the 8h ceiling exists precisely so a
 *  scope nobody has re-proven stops being repeated back. */
function ScopeExpired({ connections }: { connections: RepositoryConnection[] }) {
  return (
    <main className={EMPTY_PAGE}>
      <p className={`mono inline-block text-[10px] uppercase ${ROUTE}`}>/spaces</p>
      <h1 className={EMPTY_HEADING}>Sign back in to refresh this.</h1>
      <p className={EMPTY_BODY}>
        Doug still has your connection. What expired is the repository scope
        GitHub granted when you signed in — it lasts eight hours, and only a new
        sign-in can renew it.
      </p>
      <div className="mt-7 flex flex-col gap-px">
        {connections.map((connection) => (
          <div
            className="mono flex items-center gap-3 border-t border-[var(--rule-soft)] py-2.5 text-[11px] first:border-t-0"
            key={connection.installation_id}
          >
            <span className="flex flex-col gap-0.5">
              <strong className="font-semibold text-foreground">{connectionLabel(connection)}</strong>
              <small className="text-[10px] text-muted-foreground">
                session scope expired — sign out and sign back in to refresh
              </small>
            </span>
          </div>
        ))}
      </div>
      <form action={signOutAction} className="mt-[26px]">
        <button
          type="submit"
          className="mono cursor-pointer rounded-[4px] border-0 bg-foreground px-3.5 py-2.5 text-[11px] text-background"
        >Sign out</button>
      </form>
    </main>
  );
}

function NoConnection({
  userLabel,
  scopeUnconfirmed,
}: {
  userLabel: string;
  scopeUnconfirmed: boolean;
}) {
  return (
    <main className={EMPTY_PAGE}>
      <p className={`mono inline-block text-[10px] uppercase ${ROUTE}`}>/account</p>
      <h1 className={EMPTY_HEADING}>{userLabel}, you&apos;re in.</h1>
      <p className={EMPTY_BODY}>{"You're in. Connect GitHub only when you want Doug to review repositories."}</p>
      {/* This screen otherwise claims "you have not connected anything", which
          is only true if Doug asked. When the sign-in derivation failed it never
          asked, and `lib/entitlements.ts` leaves this signal precisely so the
          difference is not papered over. (#99, carried through the Phase B
          rebuild — the claim is the point, the CSS module it used is gone.) */}
      {scopeUnconfirmed && (
        <p className={`${EMPTY_NOTE} mt-4`}>
          Doug could not confirm your repositories when you signed in, so this page may be
          missing connections you already have. Try again in a moment, or sign out and back in.
        </p>
      )}
      <Link
        href="/install/start"
        prefetch={false}
        className="mono mt-[26px] inline-block rounded-[4px] bg-foreground px-3.5 py-2.5 text-[11px] text-background no-underline"
      >Connect GitHub</Link>
    </main>
  );
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<DashboardParams>;
}) {
  const params = await searchParams;
  const auth = await withAuth();
  const { user, accessToken, organizationId } = auth;
  if (!user || !accessToken) redirect("/sign-in");
  const { connections } = await getConnections(accessToken);
  const door = frontDoor(connections, organizationId);
  const current = door.current;
  const userLabel = user.firstName || user.email || "You";
  const scopeUnconfirmed = (await cookies()).has(SCOPE_UNCONFIRMED_COOKIE);

  let fetched: RunSummary[] = [];
  let limit = 0;
  let atCap = false;
  let facets: Facet[] = [];
  let groups: PrGroup[] = [];
  let shown = 0;
  let reband = 0;
  let selectedSummary: RunSummary | null = null;
  let detail: RunDetail | null = null;

  const filters = dashboardFilters(params);
  const query = normalizeQuery(value(params, "q"));
  const sort = parseSort(value(params, "sort") ?? null);
  const lens = parseThresholdLens(value(params, "threshold"));
  const filtering =
    query.length > 0 ||
    filters.lowCoverage ||
    filters.hasError ||
    Object.values(filters.facets).some((values) => values && values.length > 0);

  if (current) {
    const response = await getSessionRuns(accessToken, filters.repo);
    fetched = response.items;
    limit = response.limit;
    atCap = isAtCap(fetched.length, limit);
    // Facets are built from the FULL fetched set, so a pill's count does not
    // change as other pills are pressed. Recomputing them against the filtered
    // set would zero out every unselected option the moment one selection
    // excluded it, which reads as "no such runs exist" rather than "you have
    // filtered them out".
    // Built from the FULL fetched set, then merged with any selection the data
    // does not carry — a stale `?band=foo` is a real constraint and has to be
    // visible and clickable, not just true (Doug PR 102,
    // reader:query-param-contract-change).
    // THE LENS IS APPLIED HERE, at the boundary, and everything below reads the
    // rewritten rows. That is what makes the pills, their counts, the chips and
    // the count line agree: there is no state where the "needs you" pill says
    // 12 and the table shows a different 12. See lib/threshold-lens.ts for why
    // this is a rewrite rather than a parameter (five byte-locked modules).
    const lensed = applyLens(fetched, lens);
    reband = rebandedCount(fetched, lensed);
    facets = withSelectedOptions(buildFacets(lensed), filters.facets);
    groups = sortGroups(
      groupRunsByPr(filterRunsByQuery(filterRuns(lensed, filters), query), atCap),
      sort,
    );
    shown = groups.reduce((total, group) => total + group.runCount, 0);
    // Resolved from `fetched`, NOT `lensed`. The evidence pane is a record of
    // what Doug did, and `detail.threshold` is the line it actually scored
    // against; feeding it a re-banded summary would destroy the one place on
    // the page where the real verdict can still be read.
    const selectedId = Number(value(params, "run"));
    selectedSummary = Number.isInteger(selectedId)
      ? fetched.find((run) => run.verdict_id === selectedId) ?? null
      : null;
    if (selectedSummary) detail = await getSessionRun(accessToken, selectedSummary.verdict_id);
  }
  const pageWindow = pageSlice(groups, parsePage(value(params, "page")));

  return (
    <div className="dashboard-surface">
      <header className={`${CANVAS} sticky top-0 z-20 flex min-h-[52px] items-center gap-[18px] border-b border-border bg-background/[.88] px-5 py-2 backdrop-blur-[10px] max-[900px]:static max-[900px]:flex-wrap max-[900px]:items-start`}>
        <Link href="/" className="font-heading flex items-center gap-2 text-base font-bold text-inherit no-underline">
          <DougLogo size={20} /> doug <span className="mono ml-0.5 rounded-[3px] bg-accent px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[.12em] text-[var(--iridescent)]">dashboard</span>
        </Link>
        <ScopePicker connections={connections} current={current} />
        {current && <form method="GET" className="flex items-center gap-1.5">
          <label className={SWITCH_CONTROL}>
            <span className={SWITCH_LABEL}>repo</span>
            <select name="repo" defaultValue={filters.repo} aria-label="Repository" className={SWITCH_SELECT}>
              {repositoryOptions(current).map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <button type="submit" className={SUBMIT_BUTTON}>filter</button>
        </form>}
        <Link href="/install/start" prefetch={false} className={CONNECT_LINK}>Connect repositories</Link>
        <div className="mono ml-auto flex items-center gap-2.5 text-[11.5px] text-muted-foreground max-[900px]:ml-0 max-[900px]:w-full max-[900px]:justify-end">
          <span>{user.email}</span>
          <form action={signOutAction}><button type="submit" className="cursor-pointer border-0 bg-transparent text-inherit underline">sign out</button></form>
        </div>
      </header>
      <nav className={`${CANVAS} flex gap-0.5 border-b border-border bg-background px-5`} aria-label="Dashboard sections">
        <Link href="/dashboard" aria-current="page" className={TAB}>Runs</Link>
        <span className={TAB}>Repositories <small className="text-[8px]">later</small></span>
        <span className={TAB}>Evidence <small className="text-[8px]">later</small></span>
      </nav>
      <PendingConnections connections={connections} />

      {/* Four states, not three (#99). `frontDoor` owns the precedence and the
          selectability of an expired connection; this only dispatches. */}
      {door.state === "welcome" ? <NoConnection userLabel={userLabel} scopeUnconfirmed={scopeUnconfirmed} />
        : door.state === "reauthorize" ? <ScopeExpired connections={door.expired} />
        : door.state === "choose" ? (
        <main className={EMPTY_PAGE}>
          <p className={`mono inline-block text-[10px] uppercase ${ROUTE}`}>/spaces</p>
          <h1 className={EMPTY_HEADING}>Choose a connected space.</h1>
          <p className={EMPTY_BODY}>Each space stays separate. Runs from one installation never join another.</p>
          <div className="mt-7"><ScopePicker connections={connections} current={null} /></div>
        </main>
      ) : (
        <main>
          <div className={`mono ${CANVAS} flex items-center gap-3 px-5 pt-[26px] pb-3 text-[11px] uppercase tracking-[.15em] text-muted-foreground`}>
            {/* `door.current`, not the hoisted `current`: only the discriminated
                union narrows away null on this arm, which is the reason #99
                gave one member per state instead of Exclude<> on a shared one.
                The hoisted binding is widened and would need an assertion. */}
            <span className={ROUTE}>/runs</span> Verdict history for {connectionLabel(door.current)}
            <span className="h-px flex-1 bg-border" />
          </div>
          <section className={`${CANVAS} px-5 pb-6`}>
            {lens !== null && <LensBanner lens={lens} reband={reband} params={params} />}
            <FacetBar
              facets={facets}
              selection={filters.facets}
              // The pill counts were computed over `fetched` (unfiltered), so
              // their denominator must be `fetched.length` too. Passing the
              // filtered count here would pair an unfiltered numerator with a
              // filtered denominator, and could print a count larger than the
              // total beside it.
              totalFetched={fetched.length}
              atCap={atCap}
              params={params}
            />
            <div className="flex flex-wrap items-center gap-[7px] py-3">
              {/* The dashboard's own two predicates. Not pills in the bar
                  above: neither is a value a run carries on some dimension, so
                  neither has a partition to count over. */}
              <FilterChip active={filters.lowCoverage} target={href(params, predicateChanges("coverage", filters.lowCoverage ? null : "low"))}>coverage &lt; 50%</FilterChip>
              <FilterChip active={filters.hasError} target={href(params, predicateChanges("error", filters.hasError ? null : "yes"))}>has error</FilterChip>
              <form method="GET" action="/dashboard" className="flex items-center gap-1.5">
                {/* A GET form submits ONLY its own controls, so without these
                    the search box would silently clear every pill set above
                    it. `run` is deliberately not carried: a search can exclude
                    the very run whose evidence pane is open. */}
                {carriedParams(params, ["q", "page"]).map(([key, item]) => (
                  <input key={key} type="hidden" name={key} value={item} />
                ))}
                <label className="sr-only" htmlFor="runs-search">Search runs</label>
                <input
                  id="runs-search"
                  type="search"
                  name="q"
                  defaultValue={query}
                  placeholder="Search repo, PR, title…"
                  className="mono h-[30px] w-[220px] rounded-[5px] border border-border bg-card px-2 text-[12.5px] text-foreground focus:border-[var(--iridescent)] focus:outline-2 focus:outline-offset-2 focus:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]"
                />
                <button type="submit" className={SUBMIT_BUTTON}>search</button>
              </form>
              <ThresholdGear lens={lens} carried={carriedParams(params, ["threshold", "page"])} />
              <span className="mono ml-auto text-[12px] text-muted-foreground max-[900px]:ml-0 max-[900px]:mt-1 max-[900px]:w-full">
                <CountLine shown={shown} total={fetched.length} groups={groups.length} limit={limit} atCap={atCap} filtering={filtering} />
              </span>
            </div>
            {groups.length === 0 ? (
              // An empty result under a filter and an empty ledger are
              // different facts, and neither is a blank table under a header.
              <p className="mono border-b border-border px-2.5 py-9 text-center text-[13px] text-muted-foreground">
                {filtering
                  ? "No run matches this filter. The runs are there — the filter excludes them."
                  : "No runs in this space yet."}
              </p>
            ) : (
              <>
                <RunTable window={pageWindow} params={params} sort={sort} filtering={filtering} />
                <Pager window={pageWindow} params={params} />
              </>
            )}
          </section>
          {detail && selectedSummary && <Evidence detail={detail} summary={selectedSummary} />}
        </main>
      )}
    </div>
  );
}
