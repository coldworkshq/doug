import { withAuth } from "@workos-inc/authkit-nextjs";
import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { signOutAction } from "@/app/auth/actions";
import { BandChip } from "@/components/band-chip";
import { AutoSubmitSelect } from "@/components/auto-submit-select";
import { CensusPanel } from "@/components/census-panel";
import { CoverageRuler } from "@/components/coverage-ruler";
import { DougLogo } from "@/components/doug-logo";
import { FlagLineControl } from "@/components/flag-line-control";
import { NoJsSubmit } from "@/components/no-js-submit";
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
  type LedgerFailure,
  ledgerFailure,
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
import {
  bandCensus,
  censusScope,
  countedOver,
  repoRollup,
  repositoryTable,
  type RepoRowView,
  severityCensus,
} from "@/lib/ledger-census";
import { type PageWindow, pageRangeLabel, pageSlice, parsePage } from "@/lib/paging";
import { outcomeLabel, outcomeToneClass, relativeAge, utcTimestamp } from "@/lib/runs-time";
import { filterRunsByQuery, normalizeQuery } from "@/lib/search";
import { type SortKey, type SortState, nextSort, parseSort, sortGroups } from "@/lib/sorting";
import { applyLens, parseThresholdLens, rebandedCount } from "@/lib/threshold-lens";
import {
  type ConnectionsResponse,
  SessionApiError,
  getConnections,
  getSessionRun,
  getSessionRuns,
  type RepositoryConnection,
  type RunDetail,
  type RunSummary,
} from "@/lib/session-api";

import { finishSetupAction, switchConnectionAction } from "./actions";

const LEMA_LABEL = "Lema — separate product";

/** The reference canvas width the empty states are measured at. The RUNS state
 *  no longer centres on it: a three-column instrument shell (rail · ledger ·
 *  dock) is a full-bleed layout, and capping it at 1440 would have spent the
 *  width the dock exists to use. The states that are a single column of prose —
 *  welcome, choose, reauthorize — still centre here, because a paragraph read
 *  across 1900px is not a paragraph. */
const CANVAS = "mx-auto w-full max-w-[1440px]";

/** THE DOCK'S BREAKPOINT is 1620px, and it is written out literally at all
 *  five sites below rather than hoisted into a constant, because Tailwind finds
 *  classes by scanning source text: `${DOCK_AT}:h-screen` is assembled at
 *  runtime, matches nothing at build time, and ships a class that no stylesheet
 *  defines. The failure is silent — the markup looks right and the rule is
 *  simply absent — so the repetition is the safe form, not the sloppy one.
 *
 *  Four rules share the stop: the ledger/dock grid gains its second column, the
 *  ledger becomes viewport-tall with its own scroll, the table drops its `vh`
 *  bound, and the dock pins itself. Below it the dock is a full-width block
 *  under the ledger and the page scrolls as one document — the layout this page
 *  had before, kept as the narrow-viewport answer rather than reinvented.
 *
 *  1620 was MEASURED against a 940px table, not chosen. The ledger's chrome —
 *  212 of rail, a 400 dock, 40 of gutter, two container borders and the
 *  table's own ~15px vertical scrollbar — costs 669px. The table now needs
 *  876 (see COLUMNS) after dropping a 64px scoring-tier column, so the dock
 *  can appear from 1545 up. 1620 stays: it is the measured stop, and it
 *  still carries slack for a platform whose scrollbars are wider.
 *  Arithmetic alone said 1600 and was wrong by 9px, which is exactly the
 *  kind of error that ships as "why does this scroll sideways".
 *
 *  Tried at 1360 first, which was worse than a small scroll: the ledger got 708,
 *  the eight fixed columns then in the grid do not shrink, and the whole
 *  shortfall came out of the one flexible column — the pull request title
 *  rendered 40px wide, i.e. "feat(…". A split view whose master column cannot
 *  say what a row is about is not a split view, so the dock waits until there
 *  is room for both. Eight data columns and a 400px pane genuinely do not fit
 *  a 1440 laptop; below 1620 the ledger takes the whole width and the title
 *  is generous, which is the better half of a trade that has no free side. */

/** A bordered control that wraps a <select>. The focus ring is on the wrapper,
 *  not the select, because the label and its value read as one control — and
 *  it is not optional: this is what changes whose data you are looking at.
 *  Stacked label-over-value in the rail, where the column is 212px and a
 *  side-by-side label would leave the org name six characters wide. */
const SWITCH_CONTROL =
  "mono flex w-full flex-col gap-[3px] rounded-[5px] border border-border bg-card px-2 py-[5px] " +
  "focus-within:border-[var(--iridescent)] focus-within:outline-2 focus-within:outline-offset-2 " +
  "focus-within:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]";

const SWITCH_LABEL = "text-[9px] uppercase tracking-[.14em] text-[var(--dim)]";

const SWITCH_SELECT =
  "w-full max-w-full border-0 bg-transparent text-[12px] text-foreground outline-0";

const SUBMIT_BUTTON =
  "mono cursor-pointer rounded-[4px] border border-border bg-card px-2 py-[5px] text-[11px] " +
  "text-muted-foreground hover:border-[var(--iridescent)] hover:text-foreground " +
  "focus-visible:border-[var(--iridescent)] focus-visible:text-foreground";

/** One row of the settings menu — the connect link and the sign-out button
 *  share it so a <Link> and a <button type="submit"> render as one list.
 *
 *  Hoisted so each tag stays short and legible. The reachability pin in
 *  lib/dashboard-contract.test.mjs deliberately does NOT read this string — it
 *  pins the href and the label, so restyling can never fail an ordering
 *  guarantee. */
const MENU_ITEM =
  "mono block w-full cursor-pointer rounded-[3px] border-0 bg-transparent px-2 py-[7px] " +
  "text-left text-[11px] text-muted-foreground no-underline hover:bg-accent " +
  "hover:text-[var(--iridescent)] focus-visible:bg-accent focus-visible:outline-2 " +
  "focus-visible:-outline-offset-2 focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]";

/** A rail entry. The current section is marked by a filled tick in the left
 *  gutter AND by weight and ink — three carriers, because the tick is 2px wide
 *  and the accent is the one colour on this page that is not allowed to mean
 *  anything about a verdict. */
const RAIL_ITEM =
  "mono relative flex items-center gap-2 border-l-2 border-transparent py-[7px] pr-2 pl-[13px] " +
  "text-[11px] uppercase tracking-[.09em] text-[var(--dim)] no-underline " +
  "hover:bg-[var(--row-hover)] hover:text-foreground " +
  "aria-[current]:border-l-[var(--iridescent)] aria-[current]:bg-accent " +
  "aria-[current]:font-semibold aria-[current]:text-foreground";

/** The evidence pane's section headings. The `<span>` inside each one is a
 *  provenance sub-label, styled here rather than at the call site so the
 *  headings' own markup stays the plain sentence it claims to be. */
const BLOCK_HEADING =
  "mono mb-3 flex items-center gap-2.5 text-[10px] font-medium uppercase tracking-[.16em] " +
  "text-muted-foreground [&_span]:text-[9.5px] [&_span]:normal-case [&_span]:tracking-[.04em] " +
  "[&_span]:text-[var(--dim)]";

const BLOCK = "border-b border-border px-5 py-[18px]";

/** The route chip — a monospace breadcrumb in the accent wash. */
const ROUTE = "rounded-[3px] bg-accent px-[7px] py-0.5 text-[var(--iridescent)] tracking-[.06em]";

const EMPTY_PAGE = "mx-auto max-w-[760px] px-6 py-[110px]";
const EMPTY_HEADING =
  "font-heading mt-[18px] text-[clamp(36px,7vw,64px)] font-semibold tracking-[-.05em]";
const EMPTY_BODY = "mt-4 max-w-[620px] text-base text-muted-foreground";

const EMPTY_NOTE = "text-xs text-muted-foreground";

/** A finding or a deviation: the marker column, then the rule and its words. */
const FINDING = "grid grid-cols-[54px_minmax(0,1fr)] gap-2.5 border-t border-[var(--rule-soft)] py-[10px]";

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
    <form action={switchConnectionAction} className="flex flex-col gap-1.5 max-lg:w-[200px]">
      <label className={SWITCH_CONTROL}>
        <span className={SWITCH_LABEL}>space</span>
        <AutoSubmitSelect
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
        </AutoSubmitSelect>
      </label>
      {/* Not deleted — rendered until the client proves it is not needed. It
          used to be wrapped in a script-absent element, which covered strictly
          less: that only renders when scripting is DISABLED, so it did nothing
          in the two cases that actually happen — the seconds before hydration,
          and a bundle that loaded and threw. In both, this form had no working
          control at all and an operator could not switch spaces (Doug PR 103,
          reader:js-dependency-regression). */}
      <NoJsSubmit className={`${SUBMIT_BUTTON} w-full`}>open</NoJsSubmit>
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
      className="mono grid w-full grid-cols-[210px_minmax(0,1fr)] gap-[18px] border-b border-border bg-background/[.91] px-5 py-2.5 max-[900px]:grid-cols-1"
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

/** The rail's live readout: what is in view, in four numbers.
 *
 *  The same functions the dock's census panel calls, over the same array, so
 *  the rail and the panel cannot report one ledger differently — they are not
 *  two counts of the same thing, they are one count rendered twice.
 *
 *  `scope` is the denominator sentence, carried onto the group's `title` rather
 *  than printed: the rail has 212px and the sentence is a paragraph, but a
 *  count with no reachable denominator is the thing this page refuses. The dock
 *  prints it in full, three hundred pixels away. */
function RailReadout({ runs, scope }: { runs: RunSummary[]; scope: string }) {
  const band = bandCensus(runs);
  const severity = severityCensus(runs);
  const rows: Array<{ word: string; count: number; tone: string }> = [
    { word: "needs you", count: band.flagged, tone: "data-flag" },
    { word: "cleared", count: band.cleared, tone: "data-clear" },
    { word: "findings", count: severity.total, tone: "text-foreground" },
    { word: "near the line", count: band.nearLine, tone: "text-foreground" },
  ];
  return (
    <div className="px-4 py-3.5" title={scope}>
      <p className="mono mb-2 text-[9px] uppercase tracking-[.15em] text-[var(--dim)]">In view</p>
      <dl className="mono m-0 flex flex-col gap-[5px] text-[10.5px]">
        {rows.map((row) => (
          <div key={row.word} className="flex items-baseline gap-2">
            <dt className={`${row.tone} w-[30px] flex-none text-right text-[14px] font-medium tabular-nums`}>{row.count}</dt>
            <dd className="m-0 min-w-0 truncate text-muted-foreground">{row.word}</dd>
          </div>
        ))}
      </dl>
    </div>
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
      className="mono rounded-[4px] border border-border bg-card px-[9px] py-1 text-[11.5px] text-muted-foreground no-underline hover:border-[var(--iridescent)] hover:text-foreground [&[data-active]]:border-foreground [&[data-active]]:bg-foreground [&[data-active]]:text-background"
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
  if (view.kind === "no-read") return <span className="mono text-[11px] text-muted-foreground">no read</span>;
  return (
    <div className="mono flex items-center gap-[6px] text-[11px] text-foreground" title={view.chars ?? undefined}>
      <span className="cov-track block h-1.5 w-[46px]">
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
 *  These are NOT the scope controls in the rail. Scope (`?repo=`) decides what
 *  the server fetches; these narrow what was already fetched. Keeping them
 *  visually distinct — a flat row over the ledger rather than bordered controls
 *  in the rail — is what stops an operator reading a pill as a change of scope.
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
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border pb-2.5">
      {facets.map((facet) => (
        <div key={facet.key} className="flex flex-wrap items-center gap-1.5">
          <span className="mono text-[10px] uppercase tracking-[.13em] text-[var(--dim)]">{facet.label}</span>
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
                className={`mono inline-flex items-center gap-1.5 rounded-[4px] border px-[7px] py-[2px] text-[11.5px] no-underline ${frame} ${ink}`}
              >
                {option.label}
                <span className="text-[10.5px] tabular-nums opacity-60">{option.count}</span>
              </Link>
            );
          })}
        </div>
      ))}
      {active && (
        <Link
          href={href(params, facetClearChanges())}
          className="mono ml-auto text-[11px] uppercase tracking-[.1em] text-muted-foreground underline decoration-dotted underline-offset-[3px] hover:text-foreground"
        >clear filters</Link>
      )}
    </div>
  );
}

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
  atCap,
  limit,
  params,
}: {
  lens: number;
  reband: number;
  atCap: boolean;
  limit: number;
  params: DashboardParams;
}) {
  return (
    <div className="mono mb-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-[5px] border border-[var(--iridescent)] bg-accent px-3 py-1.5 text-[11px] text-foreground">
      <span className="font-medium text-[var(--iridescent)]">Viewing at {lens.toFixed(2)}</span>
      <span className="text-muted-foreground">
        {/* The count is of rows the lens MOVED, not of rows it flagged — the
            size of the lens's effect, so the banner cannot report a ledger's
            normal state as though this control had caused it.

            Qualified at the cap the same way CountLine qualifies its own
            total: `rebandedCount` only ever sees `fetched`, which at the page
            cap is the newest `limit` runs, not the whole scope. Every other
            count on this page already says so — CountLine replaces the total
            with "latest N", FacetBar's pill titles name the newest N fetched —
            so a bare "31 rows re-banded" here would be the one number on the
            page that let an operator read a fraction of the scope as the
            whole of it. */}
        Doug scored these against its own line —{" "}
        {atCap ? (
          <>
            <b className="font-medium text-foreground">{reband}</b> of the latest{" "}
            <b className="font-medium text-foreground">{limit}</b> rows re-banded by this view.
          </>
        ) : (
          <>
            <b className="font-medium text-foreground">{reband}</b>
            {reband === 1 ? " row" : " rows"} re-banded by this view.
          </>
        )}
      </span>
      <Link
        href={href(params, thresholdChanges(null))}
        className="ml-auto underline decoration-dotted underline-offset-[3px] hover:text-[var(--iridescent)] max-[900px]:ml-0"
      >Clear the lens</Link>
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

/** The repositories view's count line — deliberately NOT CountLine.
 *
 *  It states two things that come from two different places, and keeping them
 *  in one sentence is the whole point: the repository total is the
 *  installation's own list and is complete, while every per-row number beside
 *  it is counted over the runs that came back, which at the page cap is the
 *  newest N and not the scope. Reusing CountLine would have printed one
 *  unqualified total and let the row counts inherit its authority.
 *
 *  `repos` can exceed `connected` — a repository with runs that the
 *  installation no longer lists still gets a row (see `repositoryTable`), and
 *  the extra is named rather than quietly folded into the total. */
function RepoCountLine({
  repos,
  connected,
  shown,
  total,
  limit,
  atCap,
  filtering,
}: {
  repos: number;
  connected: number;
  shown: number;
  total: number;
  limit: number;
  atCap: boolean;
  filtering: boolean;
}) {
  const orphans = repos - connected;
  // `countedOver` owns the branch order. This line used to test `atCap` first and,
  // with a filter active at the page cap, announced "counts over the latest 500
  // runs fetched" while every number beside it was counted over the filtered
  // subset — and the dock's census panel, branching the other way, printed a
  // different denominator for the same rows on the same screen. One function now
  // answers for both, so the disagreement is unrepresentable rather than fixed.
  const over = countedOver({ shown, fetched: total, limit, atCap, filtering });
  return (
    <span>
      <b className="text-foreground">{connected}</b> {connected === 1 ? "repository" : "repositories"} connected
      {orphans > 0 && <> · <b className="text-foreground">{orphans}</b> with runs but no longer listed</>}
      {" "}· counts over {over}
    </span>
  );
}

/** Column widths are the console's, tightened for the split layout: the ledger
 *  now shares its row with a 400px dock, so every fixed column gave up what it
 *  could without truncating its own content. band is the one column that did
 *  NOT shrink to fit: BandChip's "needs you" measures 86px of set text and the
 *  cell adds 16px of padding, so anything under 102 wraps it to two lines and
 *  drags every flagged row taller than its neighbours. Measured in a browser
 *  at 92px — where it did exactly that — not estimated.
 *
 *  The two outcome columns took their width back from `read` and `job` for the
 *  same reason, one step milder: at 76px `◷ pending` truncated to `◷ pendi…`,
 *  and pending is the value most rows carry while the clocks are still running.
 *  Truncation states its own overflow and is the right failure mode, but a
 *  column that truncates its MODAL value is a column that is simply too narrow.
 *  `read` gave up 8px it was not using (a 46px bar and a 4-character percentage)
 *  and `job` gave up 8px it wraps anyway.
 *
 *  THE TABLE'S 876px MINIMUM falls out of these widths and is not a round
 *  number: the seven fixed columns claim 562, the cell padding 16, and the pull
 *  request cell spends 200 more on its disclosure slot, its `repo #n`, its
 *  receipt link and three gaps before the title gets anything. 876 is the
 *  previous 940px floor minus the 64px scoring-tier column. Hosted production
 *  sets DOUG_READER=1, so most rows are reader-grade; a deterministic fallback
 *  still exists, and the selected-run pane is the surface for it.
 *  Below that the table scrolls horizontally, which states the
 *  shortfall; crushing the title hides it.
 *
 *  Only three columns are sortable. band and the two outcome columns are
 *  categories, and sorting a category alphabetically implies a ranking that
 *  does not exist — narrowing those is what the pills do.
 *
 *  14d and 60d are two separate, always-shown, separately-labelled columns —
 *  never one column resolving to the strongest signal (RULING, plan D-outcome-
 *  surface). They are different observations of different windows: a row
 *  reading "clean" at 14d and "pending" at 60d is the honest picture, and
 *  collapsing them would let "clean" silently mean two different things
 *  depending on data the reader cannot see. */
const COLUMNS: Array<{ label: string; cls: string; sort?: SortKey }> = [
  { label: "score", cls: "w-[58px] text-right", sort: "score" },
  { label: "pull request", cls: "" },
  { label: "band", cls: "w-[106px]" },
  { label: "read", cls: "w-[104px]", sort: "coverage" },
  { label: "14d outcome", cls: "w-[88px]" },
  { label: "60d outcome", cls: "w-[88px]" },
  { label: "job", cls: "w-[76px]" },
  { label: "age", cls: "w-[42px] text-right" , sort: "age" },
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
  "mono sticky top-0 z-10 border-b border-border bg-background px-2 pt-[7px] pb-[6px] text-left " +
  "text-[10px] font-medium uppercase tracking-[.13em] text-muted-foreground";
const TD = "h-[34px] border-b border-[var(--rule-soft)] px-2 align-middle";

/** The eight cells of one run. Children render the identical columns — an
 *  older run is a full verdict, not a summary of one — and are marked as
 *  history by indentation and a tint, never by dropping data. */
function RunCells({
  run,
  params,
  selected = false,
  disclosure = null,
  receipt = null,
  indented = false,
}: {
  run: RunSummary;
  params: DashboardParams;
  selected?: boolean;
  disclosure?: React.ReactNode;
  receipt?: React.ReactNode;
  indented?: boolean;
}) {
  return (
    <>
      <TableCell className={`${TD} relative text-right`}>
        {/* The selection marker is a rule in the gutter, not a row tint: the
            row's own background is already carrying hover, and a second wash
            over it makes "selected" and "hovered" the same colour at the exact
            moment a reader is moving between them. Chrome, never a data
            colour — which run you are reading is not a verdict about it. */}
        {selected && <span aria-hidden className="absolute inset-y-0 left-0 w-[2px] bg-[var(--iridescent)]" />}
        <span className={"mono text-[14px] font-semibold " + (run.band === "flagged" ? "data-flag" : "data-clear")}>
          {run.score.toFixed(2)}
        </span>
      </TableCell>
      <TableCell className={`${TD} min-w-0`}>
        <div className="flex min-w-0 items-baseline gap-2">
          {/* The slot reserves its width whether or not a control lives in it,
              so a PR with history and a PR without still start their repo name
              at the same x. */}
          <span className="min-w-[34px] flex-none text-right">{disclosure}</span>
          {indented ? (
            // A child row's repo, number and title are its parent's, verbatim.
            // What distinguishes one run of a PR from the next is WHEN it ran,
            // so that is what the cell carries — still linking to this run's
            // own evidence.
            <Link className="mono truncate pl-3 text-[11px] text-muted-foreground no-underline hover:text-foreground" href={href(params, { run: String(run.verdict_id) })}>
              {relativeAge(run.scored_at)} ago
            </Link>
          ) : (
            <Link className="flex min-w-0 items-baseline gap-2 text-inherit no-underline" href={href(params, { run: String(run.verdict_id) })}>
              <span className="mono flex-none text-[11px] text-muted-foreground"><b className="font-medium text-foreground">{run.repo}</b> #{run.pr_number}</span>
              <strong className="min-w-0 flex-1 truncate text-[13px] font-normal">{run.title}</strong>
            </Link>
          )}
          {/* The PR's receipt, not this run's evidence — a second, separate
              destination, so it is a sibling of the link above rather than
              nested inside it. Passed only by the group row (a child row's
              PR identity is its parent's, and the receipt is per PR, not per
              run); absent everywhere else, which is why this slot is a
              rendered node and not a branch. */}
          {receipt}
        </div>
      </TableCell>
      <TableCell className={TD}><BandChip band={run.band} /></TableCell>
      <TableCell className={TD}><CoverageCell run={run} /></TableCell>
      {/* Two independent cells — deliberately not one window falling back to
          the other. 14d and 60d are different observations of different
          windows, and a fallback would let one cell's "clean" silently stand
          in for the other's "pending" (see COLUMNS' docstring). Each goes
          through the same outcomeTone/outcomeLabel rule the detail tile
          uses, so all three render sites cannot drift into describing one
          row differently. truncate: shadcn's TableCell brings
          `whitespace-nowrap`, so a longer-than-expected outcome overflows
          its fixed column instead of wrapping (Doug PR 103). */}
      <TableCell className={`mono ${TD} truncate text-[11.5px]`}>
        <span className={outcomeToneClass(outcomeTone(run.outcome_14))}>{outcomeLabel(run.outcome_14)}</span>
      </TableCell>
      <TableCell className={`mono ${TD} truncate text-[11.5px]`}>
        <span className={outcomeToneClass(outcomeTone(run.outcome_60))}>{outcomeLabel(run.outcome_60)}</span>
      </TableCell>
      {/* whitespace-normal, against TableCell's nowrap base: this is the one
          cell holding an arbitrary-length string (a job error), in a fixed
          84px column. Nowrap spills it across the age column — and these are
          the rows an operator most needs to read. */}
      <TableCell className={`mono ${TD} whitespace-normal break-words text-[10.5px] leading-[1.25] ` + (run.job?.error ? "data-flag" : "text-muted-foreground")}>
        {run.job?.error ? `${run.job.attempts}× · ${run.job.error}` : (run.job?.status ?? "—")}
      </TableCell>
      <TableCell className={`mono ${TD} text-right text-[11px] text-muted-foreground`}>{relativeAge(run.scored_at)}</TableCell>
    </>
  );
}

function RunTable({
  window,
  params,
  sort,
  filtering,
  selectedId,
}: {
  window: PageWindow<PrGroup>;
  params: DashboardParams;
  sort: SortState;
  filtering: boolean;
  selectedId: number | null;
}) {
  return (
    // The ledger fills whatever height the shell leaves it and scrolls inside
    // that bound, so the dock beside it never moves and the page itself does
    // not scroll at all on a wide screen. `max-h-[62vh]` is the fallback for
    // viewports below 1620px, where the shell is one scrolling document and
    // an unbounded table would push the dock a full screen below the fold —
    // the failure the old 55vh bound was added to fix, kept for the layout
    // that still has it.
    <Table
      containerClassName="min-h-0 max-h-[62vh] flex-1 overflow-auto rounded-[5px] border border-border bg-background min-[1620px]:max-h-none"
      className="min-w-[876px] table-fixed border-separate border-spacing-0 text-xs"
    >
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
                  className="text-inherit no-underline hover:text-foreground"
                >
                  {column.label}
                  <span aria-hidden className="ml-1 opacity-60">
                    {sort.key === column.sort ? (sort.dir === "asc" ? "▲" : "▼") : "▾"}
                  </span>
                </Link>
              )}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      {window.items.map((group) => {
        const hasHistory = group.children.length > 0;
        const count = runCountLabel(group, filtering);
        return (
          <tbody key={group.key} className="pr-group">
            <TableRow className="border-0 hover:bg-[var(--row-hover)]">
              <RunCells
                run={group.latest}
                params={params}
                selected={group.latest.verdict_id === selectedId}
                receipt={
                  // The receipt is the PR's evidentiary record and lives on its
                  // own route — a different destination from this run's
                  // evidence, which is why it is a second link rather than a
                  // section of the first one's target.
                  <Link
                    className="mono ml-auto flex-none text-[10.5px] text-muted-foreground no-underline underline-offset-[3px] hover:text-[var(--iridescent)] hover:underline"
                    aria-label={`Receipt for ${group.repo} #${group.prNumber}`}
                    href={`/dashboard/pr/${group.prNumber}?repo=${encodeURIComponent(group.repo)}`}
                  >receipt</Link>
                }
                disclosure={hasHistory ? (
                  <label
                    title={count.title}
                    className="pr-disclosure mono inline-flex cursor-pointer items-center gap-1 rounded-[3px] px-1.5 py-1 text-[10.5px] leading-none text-muted-foreground hover:bg-muted hover:text-foreground"
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
                <RunCells
                  run={child}
                  params={params}
                  selected={child.verdict_id === selectedId}
                  indented
                />
              </TableRow>
            ))}
          </tbody>
        );
      })}
    </Table>
  );
}

/** Paging is a property of a WINDOW, not of what is in it — the runs ledger and
 *  the repositories table page identically, so this reads only the paging
 *  fields and never the items. */
/** Column widths for the repositories view. Narrower than the ledger's — eight
 *  columns, none of them holding an arbitrary-length string, so the whole table
 *  fits the ledger column at every width the dock allows.
 *
 *  "flag line" sits DIRECTLY BESIDE "needs you" on purpose: one is the count of
 *  runs that asked for a human, the other is the line that decides who asks
 *  next. Reading them together is the whole reason the setting lives on this
 *  table rather than behind a settings page. */
const REPO_COLUMNS: Array<{ label: string; cls: string }> = [
  { label: "repository", cls: "" },
  { label: "runs", cls: "w-[58px] text-right" },
  { label: "prs", cls: "w-[52px] text-right" },
  { label: "needs you", cls: "w-[82px] text-right" },
  // 210px, not 150: the unset summary reads "default · 0.30 deep read / 0.62
  // fallback" — ~40 monospace characters, which wrapped to three lines in a
  // 150px table-fixed cell and took the whole row's height with it.
  { label: "flag line", cls: "w-[210px]" },
  { label: "findings", cls: "w-[76px] text-right" },
  { label: "read", cls: "w-[104px]" },
  { label: "errors", cls: "w-[62px] text-right" },
];

/** One repository's flag line, keyed by `full_name` because that is the only
 *  name the rollup rows carry — the ledger joins runs to repositories by name,
 *  and the numeric id exists only on the connection's own list. */
type FlagLineSetting = { id: number; needs_you_threshold: number | null; pr_comment: boolean };

/** The flag-line cell, and the one row shape that gets no control.
 *
 *  A repository with runs in the ledger but no entry on the installation's list
 *  — the "not connected" row — has no `installation_repos` row behind it, so
 *  there is no id to PATCH and no setting to state. It gets an em dash, the
 *  same answer the read column gives for a fact it does not have, rather than a
 *  control that would fail on submit. */
function FlagLineCell({
  setting,
  defaults,
}: {
  setting: FlagLineSetting | null;
  defaults: { reader: number; fallback: number };
}) {
  if (!setting) return <span className="mono text-[12px] text-[var(--dim)]">—</span>;
  return (
    <FlagLineControl
      githubRepoId={setting.id}
      value={setting.needs_you_threshold}
      prComment={setting.pr_comment}
      defaults={defaults}
    />
  );
}

/** D8. The toggle above says "on"; this says whether anything is actually
 *  landing. Without it the failure mode is a setting that reads on, a comment
 *  that never appears, and a stderr line in a project with no alerting — the
 *  operator's only evidence being an absence they would have to go looking for.
 *
 *  It names the USUAL cause and refuses to assert it. GitHub answers 403 for the
 *  App permission never having been re-accepted, for a locked conversation, for
 *  an archived repository and for secondary rate limiting alike; the token names
 *  the code and nothing more, so the banner hedges exactly as far as the
 *  evidence does. Naming one cause with confidence would send someone to the
 *  App settings for a repository they archived last week.
 *
 *  The timestamp is the LAST refusal, not a count: `pr_comment_denied_at` is
 *  cleared by the next successful post, so a stamp here means the most recent
 *  attempt failed — which is the fact worth acting on. */
function PrCommentDenialBanner({ deniedAt }: { deniedAt: string }) {
  return (
    <div className="mono mb-2.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-[5px] border border-[var(--flag)] px-3 py-1.5 text-[11px] text-foreground">
      <span className="font-medium data-flag">PR comments are not posting</span>
      <span className="text-muted-foreground">
        Doug&apos;s last attempt was refused (403) at{" "}
        <b className="font-medium text-foreground">{utcTimestamp(deniedAt)}</b>. The usual cause is the
        pull-requests write permission not being re-accepted in GitHub; a locked conversation, an
        archived repository, or secondary rate limiting produce the same code.
      </span>
    </div>
  );
}

/** Every repository the installation covers, against what the ledger says.
 *
 *  A zero is a real answer here and is rendered as one: a connected repository
 *  with no runs in view is the row an operator is looking for, and it must not
 *  be dimmed into invisibility or sorted away. What IS dimmed is the count
 *  itself — muted ink on a 0, full ink on a number — so the eye lands on the
 *  repositories Doug is actually working in without the quiet ones leaving the
 *  page.
 *
 *  No data colour on the read column (a magnitude, on the neutral ramp) and
 *  none on `runs`/`prs`/`findings` (quantities, not verdicts). `needs you` and
 *  `errors` take --flag ONLY when non-zero, because there a number IS the
 *  verdict — it is the count of runs this repository is asking a human for. */
function RepositoryTable({
  window,
  params,
  settings,
  defaults,
}: {
  window: PageWindow<RepoRowView>;
  params: DashboardParams;
  settings: Map<string, FlagLineSetting>;
  defaults: { reader: number; fallback: number };
}) {
  return (
    <Table
      containerClassName="min-h-0 max-h-[62vh] flex-1 overflow-auto rounded-[5px] border border-border bg-background min-[1620px]:max-h-none"
      className="min-w-[820px] table-fixed border-separate border-spacing-0 text-xs"
    >
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {REPO_COLUMNS.map((column) => (
            <TableHead key={column.label} className={`${TH} ${column.cls}`}>{column.label}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <tbody>
        {window.items.map((row) => (
          <TableRow key={row.repo} className="border-0 hover:bg-[var(--row-hover)]">
            <TableCell className={`${TD} min-w-0`}>
              <div className="flex min-w-0 items-baseline gap-2">
                {/* The row's action: narrow the ledger to this repository. It
                    writes `repo`, which is the SERVER's fetch scope — so this
                    is the one control on the page that changes what comes back
                    rather than what survives, and it drops the view and the
                    page with it. */}
                {/* `min-w-0 truncate` and NOT `flex-1`: the repository column is
                    the flexible one and runs to ~570px, so a growing link pushed
                    the marker beside it to the far edge of the cell, half a
                    screen from the name it describes. Sized to its text, the
                    marker sits against the name and the slack falls after both. */}
                <Link
                  href={href(params, { repo: row.repo, view: null, page: null })}
                  className="mono min-w-0 truncate text-[12px] text-foreground no-underline hover:text-[var(--iridescent)] hover:underline underline-offset-[3px]"
                >{row.repo}</Link>
                {/* Runs exist for a repository the installation no longer
                    lists. The verdicts are real; the row says why it looks
                    odd rather than disappearing. Chrome, not a data colour —
                    this is a fact about the connection, not about a PR. */}
                {!row.connected && (
                  <span
                    title="This repository has runs in the ledger but the installation no longer lists it — renamed, removed, or access revoked."
                    className="mono flex-none rounded-[3px] border border-border px-1.5 py-px text-[9.5px] uppercase tracking-[.08em] text-muted-foreground"
                  >not connected</span>
                )}
              </div>
            </TableCell>
            <TableCell className={`mono ${TD} text-right text-[12px] ` + (row.runs === 0 ? "text-[var(--dim)]" : "text-foreground")}>{row.runs}</TableCell>
            <TableCell className={`mono ${TD} text-right text-[12px] ` + (row.prs === 0 ? "text-[var(--dim)]" : "text-muted-foreground")}>{row.prs}</TableCell>
            <TableCell className={`mono ${TD} text-right text-[12px] ` + (row.flagged > 0 ? "data-flag font-medium" : "text-[var(--dim)]")}>{row.flagged}</TableCell>
            <TableCell className={TD}>
              <FlagLineCell setting={settings.get(row.repo) ?? null} defaults={defaults} />
            </TableCell>
            <TableCell className={`mono ${TD} text-right text-[12px] ` + (row.findings === 0 ? "text-[var(--dim)]" : "text-muted-foreground")}>{row.findings}</TableCell>
            <TableCell className={TD}>
              {/* Chars, on the neutral ramp, and null renders "—". A repository
                  Doug has never read and one it read nothing of are different
                  facts, and 0% asserts the second. */}
              {row.coveragePct === null ? (
                <span className="mono text-[11px] text-[var(--dim)]">—</span>
              ) : (
                <div className="mono flex items-center gap-[6px] text-[11px] text-foreground" title="share of changed characters sent to the reader">
                  <span className="cov-track block h-1.5 w-[46px]">
                    <span className="cov-fill block h-full" style={{ width: `${row.coveragePct}%` }} />
                  </span>
                  <span>{Math.round(row.coveragePct)}%</span>
                </div>
              )}
            </TableCell>
            <TableCell className={`mono ${TD} text-right text-[12px] ` + (row.errored > 0 ? "data-flag font-medium" : "text-[var(--dim)]")}>{row.errored}</TableCell>
          </TableRow>
        ))}
      </tbody>
    </Table>
  );
}

function Pager({ window, params }: { window: PageWindow<unknown>; params: DashboardParams }) {
  const label = pageRangeLabel(window);
  if (window.pageCount <= 1) {
    return <p className="mono mt-2.5 text-[10.5px] uppercase tracking-[.12em] text-[var(--dim)]">Showing {label}</p>;
  }
  const step = (page: number) => href(params, { page: page <= 1 ? null : String(page) });
  const control = "rounded-[4px] border border-border px-2 py-1 no-underline";
  return (
    <div className="mono mt-2.5 flex flex-wrap items-center gap-3 text-[10.5px] uppercase tracking-[.12em] text-muted-foreground">
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

/** One run's record, in the dock.
 *
 *  Single column at every width. The two-column spine/blocks split this pane
 *  used to run belonged to a 1440px canvas; inside a 400px dock a viewport
 *  breakpoint would have put two columns in a container that never has room for
 *  them, because `lg:` asks about the window and the dock's width is set by the
 *  grid. One column is right at 400px and merely generous at 900.
 *
 *  The three links in the header are the run's ACTIONS — the PR itself, the
 *  PR's receipt, and the way back out of the pane. `summary.url` has been on
 *  every row of the runs response since the endpoint existed and nothing has
 *  ever rendered it; it is nullable, so the link is a rendered node rather than
 *  a disabled control, and a run with no recorded URL simply does not offer
 *  one. */
function Evidence({
  detail,
  summary,
  params,
}: {
  detail: RunDetail;
  summary: RunSummary;
  params: DashboardParams;
}) {
  const action =
    "mono rounded-[3px] border border-border px-[7px] py-[3px] text-[10px] uppercase tracking-[.08em] " +
    "text-muted-foreground no-underline hover:border-[var(--iridescent)] hover:text-[var(--iridescent)]";
  return (
    <section aria-labelledby="run-evidence-title" className="pb-16">
      <header className="border-b border-border px-5 pt-5 pb-4">
        <div className="mono mb-2 flex items-center gap-2 text-[10.5px] text-muted-foreground">
          <span className={ROUTE}>/runs/{detail.verdict_id}</span>
          <span className="truncate">{detail.repo} · #{detail.pr_number}</span>
          <Link href={href(params, { run: null })} className="ml-auto flex-none text-[14px] leading-none text-muted-foreground no-underline hover:text-foreground" aria-label="Close this run">×</Link>
        </div>
        <div className="flex items-start justify-between gap-4">
          <h2 id="run-evidence-title" className="font-heading min-w-0 text-[19px] font-semibold leading-[1.15] tracking-[-.03em]">{summary.title}</h2>
          <div className="mono flex flex-none flex-col items-end">
            <strong className={"text-[28px] font-medium leading-none " + (detail.band === "flagged" ? "data-flag" : "data-clear")}>
              {detail.score.toFixed(2)}
            </strong>
            <span className="mt-1 text-[9.5px] text-muted-foreground">{detail.band === "flagged" ? "needs you" : "cleared"} · threshold {detail.threshold.toFixed(2)}</span>
          </div>
        </div>
        <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
          {summary.url && (
            <a href={summary.url} target="_blank" rel="noreferrer" className={action}>open pull request ↗</a>
          )}
          <Link href={`/dashboard/pr/${detail.pr_number}?repo=${encodeURIComponent(detail.repo)}`} className={action}>receipt</Link>
        </div>
      </header>

      <div className={BLOCK}>
        <h3 className={BLOCK_HEADING}>What the reader was given <span>reader evidence</span></h3>
        {detail.coverage ? (
          // The ruler renders the run's own file list, so it needs the PR's
          // dropped files as well as its coverage — two separate holes in the
          // same read.
          <CoverageRuler
            coverage={detail.coverage}
            changedFiles={summary.changed_files}
            filesDropped={detail.pr?.files_dropped ?? []}
          />
        ) : <p className={EMPTY_NOTE}>No reader coverage was recorded for this run.</p>}
      </div>

      <div className={BLOCK}>
        <h3 className={BLOCK_HEADING}>What Doug did <span>review job</span></h3>
        <RunSpine run={detail} />
      </div>

      <div className={BLOCK}>
        <h3 className={BLOCK_HEADING}>The read</h3>
        <dl className="mono grid grid-cols-[92px_minmax(0,1fr)] gap-x-3 gap-y-2 text-[11px]">
          <dt className="uppercase text-muted-foreground">tier</dt><dd className="m-0 break-words whitespace-pre-wrap">{detail.tier}</dd>
          <dt className="uppercase text-muted-foreground">model</dt><dd className="m-0 break-words whitespace-pre-wrap">{detail.model ?? "not recorded"}</dd>
          <dt className="uppercase text-muted-foreground">prompt hash</dt><dd className="m-0 break-all whitespace-pre-wrap">{detail.prompt_hash ?? "not stamped"}</dd>
          <dt className="uppercase text-muted-foreground">risk score</dt><dd className="m-0 break-words whitespace-pre-wrap">{detail.risk_score ?? "not recorded"}</dd>
          <dt className="uppercase text-muted-foreground">head sha</dt><dd className="m-0 break-all whitespace-pre-wrap">{detail.head_sha ?? "not recorded"}</dd>
          <dt className="uppercase text-muted-foreground">rationale</dt><dd className="m-0 break-words whitespace-pre-wrap">{detail.rationale ?? "No rationale was recorded."}</dd>
        </dl>
      </div>

      <div className={BLOCK}>
        <h3 className={BLOCK_HEADING}>Findings <span>{detail.reasons.length}</span></h3>
        {detail.reasons.map((reason) => (
          <div className={FINDING} key={`${reason.rule}-${reason.label}`}>
            <span className="mono data-flag text-[10px] uppercase">{reason.severity ?? "rule"}</span>
            <div><code className="mono text-[11px] break-words">{reason.rule}</code><p className="mt-[3px] text-[12.5px] text-muted-foreground">{reason.label}</p></div>
          </div>
        ))}
        {detail.reasons.length === 0 && <p className={EMPTY_NOTE}>No findings recorded.</p>}
      </div>

      <div className={BLOCK}>
        <h3 className={BLOCK_HEADING}>Deviations <span>separate stream</span></h3>
        {detail.deviations.map((deviation) => (
          <div className={FINDING} key={`${deviation.type}-${deviation.description}`}>
            <span className="mono data-flag text-[10px] uppercase">{deviation.severity}</span>
            <div><code className="mono text-[11px] break-words">{deviation.type}</code><p className="mt-[3px] text-[12.5px] text-muted-foreground">{deviation.description}</p></div>
          </div>
        ))}
        {detail.deviations.length === 0 && <p className={EMPTY_NOTE}>No deviations recorded.</p>}
      </div>

      <div className={BLOCK}>
        <h3 className={BLOCK_HEADING}>Outcome</h3>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2">
          {detail.outcomes.map((outcome) => (
            <div key={`${outcome.window_days}-${outcome.observed_at}`} className="flex flex-col rounded-[4px] border border-border bg-card p-2.5">
              <span className="mono text-[10px] text-muted-foreground">{outcome.window_days ?? "?"}-day window</span>
              {/* Tone and word both come from the shared rule, so this tile
                  and the outcome column above cannot describe the same row
                  differently — and neither can the console, which renders
                  through the very same two functions. */}
              <strong className={"mono my-1 text-[15px] " + outcomeToneClass(outcomeTone(outcome.kind))}>{outcomeLabel(outcome.kind)}</strong>
              <small className="mono text-[10px] text-muted-foreground">observed {new Date(outcome.observed_at).toLocaleDateString()}</small>
            </div>
          ))}
          {detail.outcomes.length === 0 && <p className={EMPTY_NOTE}>No outcome recorded yet.</p>}
        </div>
      </div>
    </section>
  );
}

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

/** Three arms because the API states three different things, and the same
 *  discipline the receipt page applies to its five
 *  (`dashboard/pr/[number]/page.tsx:126-152`): each arm may claim only what its
 *  status supports, and the arm reached without a status the API chose claims
 *  nothing at all. Which status reaches which arm is `ledgerFailure`'s call, in
 *  dashboard-model.ts beside `frontDoor`, so a test can reach it.
 *
 *  Before this existed, every one of these fell to `app/error.tsx`, which says
 *  "This page failed to render." and offers a Try again button. Both claims are
 *  false here. The page rendered fine — the API declined the request or did not
 *  answer — and re-running a 401 cannot clear a 401. The likeliest trigger is
 *  the one `lib/entitlements.ts` already budgets 8 seconds and a retry for: a
 *  Cloud Run container scaled to zero, holding the request through a boot. */
const LEDGER_UNREACHABLE: Record<
  LedgerFailure,
  { route: string; heading: string; body: string; signOut: boolean }
> = {
  // 401 ONLY, and it names no cause for the same reason the receipt page's
  // `unauthorized` arm does not: `api/doug/session_auth.py:164-195` returns
  // None — 401 — for five different states, and this page is told the request
  // was declined, not which one it was.
  declined: {
    route: "/spaces",
    heading: "Doug would not answer for this session.",
    body:
      "The API declined it, and that one answer covers several different states: a " +
      "sign-in token it will not verify, no space selected yet, no installation bound " +
      "to the space you are in, and a repository scope that has aged past its " +
      "eight-hour life. This page is told that the request was declined, not which of " +
      "those it was, so it does not pick one. Signing out and signing back in renews " +
      "the token and re-derives the scope, which covers most of them.",
    signOut: true,
  },
  // 503 is a deployment fault — no ledger, or no operator secret. The API
  // checks for it BEFORE the token so a misconfiguration is never reported as
  // a bad credential, and this arm must not undo that by offering sign-out.
  unavailable: {
    route: "/spaces",
    heading: "The ledger is not answering.",
    body:
      "This is a deployment fault — no ledger, or no operator secret — and not a " +
      "problem with your session. Signing out would not help. Nothing is listed " +
      "because nothing is known.",
    signOut: false,
  },
  // Everything else: a transport failure, a timeout against a cold container,
  // a 500, or a body this build's validator rejects (#149). None of those is a
  // statement about the reader, so this arm makes none. Telling someone their
  // session was declined over a dropped connection is the confident false
  // claim the typed arms exist to refuse.
  unreachable: {
    route: "/spaces",
    heading: "Doug could not load your connected spaces.",
    body:
      "The request did not come back with an answer Doug can use. That is all this " +
      "page knows — it is not a claim about your session, your connection, or your " +
      "repositories. Reloading in a moment is worth a try; the first request after an " +
      "idle period waits on a container start.",
    signOut: false,
  },
};

function LedgerUnreachable({ failure }: { failure: LedgerFailure }) {
  const copy = LEDGER_UNREACHABLE[failure];
  return (
    <div className="dashboard-surface">
      <main className={EMPTY_PAGE}>
        <p className={`mono inline-block text-[10px] uppercase ${ROUTE}`}>{copy.route}</p>
        <h1 className={EMPTY_HEADING}>{copy.heading}</h1>
        <p className={EMPTY_BODY}>{copy.body}</p>
        {/* Only the arm whose cause sign-out can actually address offers it.
            The rail that normally carries this control is built from the
            connections this page could not read, so without it there is no way
            out of the two arms that a new session would fix. */}
        {copy.signOut && (
          <form action={signOutAction} className="mt-[26px]">
            <button
              type="submit"
              className="mono cursor-pointer rounded-[4px] border-0 bg-foreground px-3.5 py-2.5 text-[11px] text-background"
            >Sign out</button>
          </form>
        )}
      </main>
    </div>
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
  // ONE variable, not two, and no JSX inside the try — the same shape and the
  // same reasons as the receipt page's `loaded` (dashboard/pr/[number]/
  // page.tsx:508-515). Two independent `let`s would type as `data: … | null`
  // beside `failure: … | null`, whose fourth combination — nothing loaded and
  // no reason why — cannot happen but would still demand copy.
  let session:
    | { data: ConnectionsResponse; failure: null }
    | { data: null; failure: LedgerFailure };
  try {
    session = { data: await getConnections(accessToken), failure: null };
  } catch (error) {
    // A throw that is not a SessionApiError carries no status Doug chose, so
    // it reads as null and lands on the arm that names no cause.
    const status = error instanceof SessionApiError ? error.status : null;
    session = { data: null, failure: ledgerFailure(status) };
  }
  // Early, because every line below this one reads the connections. The rail,
  // the scope picker and the settings menu are all built from them, so there
  // is no partial page to render: the honest thing is the whole screen.
  if (session.data === null) return <LedgerUnreachable failure={session.failure} />;

  // The whole response, not just `connections`: the repositories view prints
  // Doug's OWN two defaults beside every unset repository, and they are the
  // API's to state — the reader's line and the deterministic fallback are
  // environment values on the API, and a copy of them here would drift the
  // moment either is retuned.
  const { connections, default_needs_you_threshold: flagLineDefaults } = session.data;
  const door = frontDoor(connections, organizationId);
  const current = door.current;
  const userLabel = user.firstName || user.email || "You";
  const scopeUnconfirmed = (await cookies()).has(SCOPE_UNCONFIRMED_COOKIE);

  let fetched: RunSummary[] = [];
  let limit = 0;
  let atCap = false;
  let facets: Facet[] = [];
  let groups: PrGroup[] = [];
  /** The flat rows the table is rendering, before they are grouped by PR. The
   *  census panel and the rail readout both count THIS array — not `fetched`,
   *  and not the page slice. Not `fetched`, because a reader who has narrowed
   *  to one repository is asking about that repository; not the page slice,
   *  because page 2 of the same filter is the same question with a different
   *  fifty rows in front of it. `censusScope` names whichever set this is. */
  let visible: RunSummary[] = [];
  /** Every repository the installation covers, joined to what the fetched
   *  ledger says about each. Built even in the runs view — it is a `map` over
   *  data already in memory, and computing it in one place keeps the two views
   *  reading one join rather than two. */
  let repoRows: RepoRowView[] = [];
  /** The per-repository flag lines, for the rows that have one. Built from the
   *  CONNECTION's list rather than from the ledger: a repository Doug has never
   *  reviewed still has a line worth setting, and a repository with runs but no
   *  connection row has no id to write. */
  let flagLines = new Map<string, FlagLineSetting>();
  let shown = 0;
  let reband = 0;
  let selectedSummary: RunSummary | null = null;
  let detail: RunDetail | null = null;

  const filters = dashboardFilters(params);
  /** Which of the two ledger views is open. A query param rather than a route:
   *  both views read the SAME fetch, the same filters and the same lens, and a
   *  second route would either duplicate this page's shell or need a layout
   *  that cannot see the page's own rows to fill the rail's readout. Unknown
   *  values fall back to runs — `?view=nonsense` must not blank the page. */
  const view = value(params, "view") === "repositories" ? "repositories" : "runs";
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
    // The lens re-bands a COPY. Everything downstream of this line — the pill
    // counts, the table, the census — reads the lensed rows, so the whole view
    // agrees about every row's band; the selected run is deliberately resolved
    // from `fetched` below, so the evidence pane still shows the recorded
    // verdict rather than the one being looked through.
    const lensed = applyLens(fetched, lens);
    reband = rebandedCount(fetched, lensed);
    facets = withSelectedOptions(buildFacets(lensed), filters.facets);
    visible = filterRunsByQuery(filterRuns(lensed, filters), query);
    groups = sortGroups(groupRunsByPr(visible, atCap), sort);
    shown = groups.reduce((total, group) => total + group.runCount, 0);
    // The connection's list is authoritative about what Doug COULD review; the
    // rollup is only ever about the runs that came back. `repositoryTable`
    // keeps both sides, which is what lets this screen show a connected repo
    // with no runs at all.
    repoRows = repositoryTable(
      door.current.repositories.map((repository) => repository.full_name),
      repoRollup(visible),
    );
    flagLines = new Map(
      door.current.repositories.map((repository): [string, FlagLineSetting] => [
        repository.full_name,
        {
          id: repository.id,
          needs_you_threshold: repository.needs_you_threshold,
          pr_comment: repository.pr_comment,
        },
      ]),
    );
    // Resolved from the UNLENSED set: the evidence pane is a record of one run
    // and `detail.threshold` is the line Doug actually scored it against.
    const selectedId = Number(value(params, "run"));
    selectedSummary = Number.isInteger(selectedId)
      ? fetched.find((run) => run.verdict_id === selectedId) ?? null
      : null;
    if (selectedSummary) detail = await getSessionRun(accessToken, selectedSummary.verdict_id);
  }
  // One page number, two windows — only one is ever rendered. `pageSlice`
   // clamps out of range, so landing on page 7 of the runs view and switching
   // to a two-page repositories list shows page 2 rather than nothing; the nav
   // links drop `page` anyway, because a page number does not survive a change
   // of what is being paged.
  const pageNumber = parsePage(value(params, "page"));
  const pageWindow = pageSlice(groups, pageNumber);
  const repoWindow = pageSlice(repoRows, pageNumber);
  const scope = censusScope({ shown, fetched: fetched.length, limit, atCap, filtering });

  return (
    <div className="dashboard-surface">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[212px_minmax(0,1fr)]">
        {/* THE RAIL. Scope lives here and filters do not: what this column
            holds — which space, which repository — decides what the server
            fetches, and everything over the ledger narrows what came back.
            Separating them by a border rather than by wording is what stops a
            pill being read as a change of scope.

            Sticky and viewport-tall from `lg` up, a plain block below it, so
            on a narrow screen the whole page is one document again. */}
        {/* Below `lg` the rail is not a rail. Stacked as a column it filled an
            entire 800px-tall screen with chrome and pushed the ledger under the
            fold — so under 1024 it lays itself out as one wrapping horizontal
            bar, which is the header this page had before the redesign. The
            in-view readout is the one thing dropped rather than reflowed: it is
            a convenience duplicate of numbers the census panel states in full,
            and at this width the census panel is directly below the table. */}
        <aside
          aria-label="Dashboard navigation"
          className="flex flex-col border-b border-border bg-card max-lg:flex-row max-lg:flex-wrap max-lg:items-center max-lg:gap-x-4 max-lg:gap-y-2 max-lg:px-4 max-lg:py-2.5 lg:sticky lg:top-0 lg:h-screen lg:self-start lg:overflow-y-auto lg:border-r lg:border-b-0"
        >
          <div className="border-b border-border px-4 py-3.5 max-lg:border-0 max-lg:p-0">
            <Link href="/" className="font-heading flex items-center gap-2 text-[15px] font-bold text-inherit no-underline">
              <DougLogo size={19} /> doug
              <span className="mono ml-0.5 rounded-[3px] bg-accent px-1.5 py-0.5 text-[8.5px] font-medium uppercase tracking-[.12em] text-[var(--iridescent)]">dashboard</span>
            </Link>
          </div>

          <div className="flex flex-col gap-2 border-b border-border px-4 py-3.5 max-lg:flex-row max-lg:items-start max-lg:border-0 max-lg:p-0">
            <ScopePicker connections={connections} current={current} />
            {/* Stacked, not side by side: a 212px rail minus a submit button
                leaves ~115px of select, and "all repositories" — the DEFAULT
                value — truncates inside it. A scope control whose current value
                cannot be read is one you have to open to learn the state of. */}
            {current && <form method="GET" className="flex flex-col gap-1.5 max-lg:w-[210px]">
              <label className={SWITCH_CONTROL}>
                <span className={SWITCH_LABEL}>repo</span>
                <select name="repo" defaultValue={filters.repo} aria-label="Repository" className={SWITCH_SELECT}>
                  {repositoryOptions(current).map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <button type="submit" className={`${SUBMIT_BUTTON} w-full`}>filter</button>
            </form>}
          </div>

          <nav className="flex flex-col border-b border-border py-1.5 max-lg:flex-row max-lg:border-0 max-lg:py-0" aria-label="Dashboard sections">
            {/* Both entries carry the current filters across, and both drop
                `page`: a page number is a position in one list and means
                nothing in the other. */}
            <Link
              href={href(params, { view: null, page: null })}
              aria-current={view === "runs" ? "page" : undefined}
              className={RAIL_ITEM}
            >Runs</Link>
            <Link
              href={href(params, { view: "repositories", page: null })}
              aria-current={view === "repositories" ? "page" : undefined}
              className={RAIL_ITEM}
            >Repositories</Link>
            {/* Still not built, and still said so. A nav entry that navigates
                nowhere is a lie about the product; one that names itself as
                unbuilt is a roadmap. */}
            <span className={RAIL_ITEM}>Evidence <small className="ml-auto text-[8px] tracking-normal normal-case">later</small></span>
            {/* Docs is a REAL destination and the only entry here that leaves
                the dashboard, so it sits below a rule rather than in the run of
                sections — and it takes no `aria-current`, because no /dashboard
                URL is ever the docs page. Grouping it with the two unbuilt
                placeholders would read as a fourth thing that might also be a
                promise; it is the one link on this list that works today. */}
            <Link href="/docs" className={`${RAIL_ITEM} mt-1.5 border-t border-t-border pt-[9px] max-lg:mt-0 max-lg:border-t-0 max-lg:pt-[7px]`}>Docs</Link>
          </nav>

          {door.state === "runs" && <div className="border-b border-border max-lg:hidden"><RailReadout runs={visible} scope={scope} /></div>}

          {/* THE SETTINGS MENU is a <details>, not a popover.
              /dashboard is a server component and must stay one (RULING 2), and
              the two things behind this gear are the two that most need to work
              on an unhydrated page: signing out, and connecting a repository.
              The threshold gear can afford to be a Radix client leaf because a
              view control that does not load costs you a view; a sign-out that
              does not load strands you signed in. <details> is HTML, so the
              menu works before hydration, after a bundle throws, and with
              scripting off entirely.

              It opens UPWARD on the rail (it sits at the bottom of a full-height
              column) and downward in the narrow horizontal bar, where there is
              nothing above it. Clicking away does not close it — the honest cost
              of not reaching for JavaScript, and the gear toggles it back. */}
          {/* `relative` is on the ROW, not on the <details>. The rail is an
              overflow:auto container, so a panel that spills past it is clipped
              rather than shown — and anchored to the gear (a ~25px box at the
              right edge) a 196px panel hung 1px off the rail's left edge. Against
              the row's padding box, `inset-x-4` makes the panel exactly the
              rail's content width whatever that width becomes. */}
          <div className="mono relative mt-auto flex items-center gap-2 border-t border-border px-4 py-3 text-[10.5px] text-muted-foreground max-lg:mt-0 max-lg:border-0 max-lg:p-0">
            <span className="min-w-0 flex-1 truncate" title={user.email}>{user.email}</span>
            <details className="flex-none">
              <summary
                aria-label="Settings"
                className="flex cursor-pointer list-none items-center rounded-[4px] border border-transparent p-1 text-muted-foreground hover:border-border hover:text-foreground focus-visible:border-[var(--iridescent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)] [&::-webkit-details-marker]:hidden"
              >
                {/* The same cog the threshold gear draws, at the same weight —
                    two gears on one screen that were drawn differently would
                    read as two different kinds of control. */}
                <svg viewBox="0 0 16 16" aria-hidden className="size-[15px]" fill="none" stroke="currentColor" strokeWidth="1.4">
                  <circle cx="8" cy="8" r="2.1" />
                  <path d="M8 1.4v2M8 12.6v2M1.4 8h2M12.6 8h2M3.3 3.3l1.4 1.4M11.3 11.3l1.4 1.4M12.7 3.3l-1.4 1.4M4.7 11.3l-1.4 1.4" strokeLinecap="round" />
                </svg>
              </summary>
              <div className="absolute inset-x-4 bottom-[calc(100%+6px)] z-30 rounded-[5px] border border-border bg-card p-1 shadow-[0_10px_28px_-10px_rgba(0,0,0,.22)] max-lg:inset-x-auto max-lg:right-0 max-lg:top-[calc(100%+6px)] max-lg:bottom-auto max-lg:w-[196px]">
                <Link href="/install/start" prefetch={false} className={MENU_ITEM}>Connect repositories</Link>
                <form action={signOutAction}><button type="submit" className={MENU_ITEM}>Sign out</button></form>
              </div>
            </details>
          </div>
        </aside>

        <div className="min-w-0">
          <PendingConnections connections={connections} />

          {/* Four states, not three (#99). `frontDoor` owns the precedence and
              the selectability of an expired connection; this only dispatches. */}
          {door.state === "welcome" ? <NoConnection userLabel={userLabel} scopeUnconfirmed={scopeUnconfirmed} />
            : door.state === "reauthorize" ? <ScopeExpired connections={door.expired} />
            : door.state === "choose" ? (
            <main className={`${CANVAS} ${EMPTY_PAGE}`}>
              <p className={`mono inline-block text-[10px] uppercase ${ROUTE}`}>/spaces</p>
              <h1 className={EMPTY_HEADING}>Choose a connected space.</h1>
              <p className={EMPTY_BODY}>Each space stays separate. Runs from one installation never join another.</p>
              <div className="mt-7 max-w-[320px]"><ScopePicker connections={connections} current={null} /></div>
            </main>
          ) : (
            <main className="grid min-[1620px]:grid-cols-[minmax(0,1fr)_400px] min-[1800px]:grid-cols-[minmax(0,1fr)_480px]">
              {/* THE LEDGER. Viewport-tall from 1620px up, so the table's own
                  scroll is the only one on this column and the dock beside it
                  never moves. */}
              <section className="flex min-w-0 flex-col px-5 pt-4 pb-5 min-[1620px]:h-screen">
                <div className="mono mb-2.5 flex items-center gap-3 text-[10.5px] uppercase tracking-[.15em] text-[var(--dim)]">
                  {/* `door.current`, not the hoisted `current`: only the
                      discriminated union narrows away null on this arm, which is
                      the reason #99 gave one member per state instead of
                      Exclude<> on a shared one. The hoisted binding is widened
                      and would need an assertion. */}
                  <span className={ROUTE}>{view === "repositories" ? "/repositories" : "/runs"}</span>
                  <span className="truncate">{connectionLabel(door.current)}</span>
                  <span className="h-px flex-1 bg-border" />
                  <span className="mono flex-none normal-case tracking-normal text-muted-foreground">
                    {view === "repositories" ? (
                      // TWO SOURCES, SAID OUT LOUD. The repository count is
                      // authoritative — it is the installation's own list. Every
                      // other number on the row beside it is counted over the
                      // runs that came back, which at the cap is a window and not
                      // the scope. One line cannot be allowed to lend the first
                      // number's completeness to the rest.
                      <RepoCountLine
                        repos={repoRows.length}
                        connected={door.current.repositories.length}
                        shown={shown}
                        total={fetched.length}
                        limit={limit}
                        atCap={atCap}
                        filtering={filtering}
                      />
                    ) : (
                      <CountLine shown={shown} total={fetched.length} groups={groups.length} limit={limit} atCap={atCap} filtering={filtering} />
                    )}
                  </span>
                </div>

                {lens !== null && <LensBanner lens={lens} reband={reband} atCap={atCap} limit={limit} params={params} />}
                <FacetBar
                  facets={facets}
                  selection={filters.facets}
                  // The pill counts were computed over `lensed` (post-lens,
                  // still unfiltered), so their denominator must match its
                  // length — which is `fetched.length`: applyLens is a `map`,
                  // so `lensed.length === fetched.length` always, lens or no
                  // lens. Passing the filtered count here would pair an
                  // unfiltered numerator with a filtered denominator, and could
                  // print a count larger than the total beside it.
                  totalFetched={fetched.length}
                  atCap={atCap}
                  params={params}
                />
                <div className="flex flex-wrap items-center gap-[7px] py-2.5">
                  {/* The dashboard's own two predicates. Not pills in the bar
                      above: neither is a value a run carries on some dimension,
                      so neither has a partition to count over. */}
                  <FilterChip active={filters.lowCoverage} target={href(params, predicateChanges("coverage", filters.lowCoverage ? null : "low"))}>coverage &lt; 50%</FilterChip>
                  <FilterChip active={filters.hasError} target={href(params, predicateChanges("error", filters.hasError ? null : "yes"))}>has error</FilterChip>
                  <form method="GET" action="/dashboard" className="flex items-center gap-1.5">
                    {/* A GET form submits ONLY its own controls, so without
                        these the search box would silently clear every pill set
                        above it. `run` is deliberately not carried: a search can
                        exclude the very run whose evidence pane is open. */}
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
                      className="mono h-[28px] w-[200px] rounded-[5px] border border-border bg-card px-2 text-[12px] text-foreground focus:border-[var(--iridescent)] focus:outline-2 focus:outline-offset-2 focus:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]"
                    />
                    <button type="submit" className={SUBMIT_BUTTON}>search</button>
                  </form>
                  <ThresholdGear key={lens === null ? "none" : String(lens)} lens={lens} carried={carriedParams(params, ["threshold", "page"], { keepRun: true })} />
                </div>
                {view === "repositories" ? (
                  <>
                  {/* Above the table, not inside it: the denial is a fact about
                      the whole installation (`installations.pr_comment_denied_at`),
                      not about one row, and it is shown on the empty-list arm too
                      — a space whose repositories all fell away is exactly where a
                      silent 403 would otherwise go unread. */}
                  {door.current.pr_comment_denied_at && (
                    <PrCommentDenialBanner deniedAt={door.current.pr_comment_denied_at} />
                  )}
                  {repoRows.length === 0 ? (
                    // Reachable only when the installation lists no repositories
                    // AND the ledger holds none either — a bound install that
                    // covers nothing. Not the same as "no runs yet", which is a
                    // repository list with an empty ledger and still has rows.
                    <p className="mono rounded-[5px] border border-border px-2.5 py-9 text-center text-[12.5px] text-muted-foreground">
                      This space has no repositories. Connect one to give Doug something to review.
                    </p>
                  ) : (
                    <>
                      <RepositoryTable
                        window={repoWindow}
                        params={params}
                        settings={flagLines}
                        defaults={flagLineDefaults}
                      />
                      <Pager window={repoWindow} params={params} />
                    </>
                  )}
                  </>
                ) : groups.length === 0 ? (
                  // An empty result under a filter and an empty ledger are
                  // different facts, and neither is a blank table under a header.
                  <p className="mono rounded-[5px] border border-border px-2.5 py-9 text-center text-[12.5px] text-muted-foreground">
                    {filtering
                      ? "No run matches this filter. The runs are there — the filter excludes them."
                      : "No runs in this space yet."}
                  </p>
                ) : (
                  <>
                    <RunTable
                      window={pageWindow}
                      params={params}
                      sort={sort}
                      filtering={filtering}
                      selectedId={selectedSummary?.verdict_id ?? null}
                    />
                    <Pager window={pageWindow} params={params} />
                  </>
                )}
              </section>

              {/* THE DOCK. A run's record when one is open, and what the rows
                  in view add up to when none is — never blank. Its own scroll
                  container from 1620px up, so reading evidence never moves the
                  ledger and paging the ledger never moves the evidence. */}
              <aside className="border-border bg-card max-[1619px]:border-t min-[1620px]:sticky min-[1620px]:top-0 min-[1620px]:h-screen min-[1620px]:self-start min-[1620px]:overflow-y-auto min-[1620px]:border-l">
                {detail && selectedSummary
                  ? <Evidence detail={detail} summary={selectedSummary} params={params} />
                  : <CensusPanel runs={visible} scope={scope} />}
              </aside>
            </main>
          )}
        </div>
      </div>
    </div>
  );
}
