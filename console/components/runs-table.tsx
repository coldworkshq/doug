"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { BandChip } from "@/components/band-chip";
import { CoverageBar } from "@/components/coverage-bar";
import { FacetBar } from "@/components/facet-bar";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { RunSummary } from "@/lib/api";
import {
  FACET_KEYS,
  type FacetKey,
  type FacetSelection,
  buildFacets,
  filterRuns,
  parseFacetSelection,
  serializeFacets,
} from "@/lib/facets";
import { type PrGroup, groupRunsByPr, runCountLabel } from "@/lib/grouping";
import {
  DEFAULT_PAGE_SIZE,
  pageRangeLabel,
  pageSlice,
  parsePage,
} from "@/lib/paging";
import {
  jobDuration,
  outcomeLabel,
  outcomeTone,
  outcomeToneClass,
  relativeAge,
  utcTimestamp,
} from "@/lib/runs";
import { filterRunsByQuery, normalizeQuery } from "@/lib/search";
import {
  type SortKey,
  type SortState,
  nextSort,
  parseSort,
  serializeSort,
  sortGroups,
} from "@/lib/sorting";

interface Column {
  label: string;
  cls: string;
  sort?: SortKey;
}

// 14d and 60d are two separate, always-shown, separately-labelled columns —
// never one column resolving to the strongest signal (RULING, plan
// D-outcome-surface). They are different observations of different windows:
// a row reading "clean" at 14d and "pending" at 60d is the honest picture,
// and collapsing them would let "clean" silently mean two different things
// depending on data the reader cannot see.
const COLUMNS: Column[] = [
  { label: "score", cls: "w-[78px] text-right", sort: "score" },
  { label: "pull request", cls: "" },
  // Wide enough for BandChip's "needs you" on one line — at 96px it wrapped
  // to two and dragged every flagged row taller than its neighbours.
  { label: "band", cls: "w-[112px]" },
  { label: "tier", cls: "w-[88px]" },
  { label: "read", cls: "w-[176px]", sort: "coverage" },
  { label: "14d outcome", cls: "w-[100px]" },
  { label: "60d outcome", cls: "w-[100px]" },
  { label: "job", cls: "w-[118px]" },
  { label: "age", cls: "w-[54px] text-right", sort: "age" },
];

// The rows are the one place real repo values exist (they come off the
// ledger, not a guess), so setting the filter belongs here rather than in
// ScopeSwitch — see ScopeSwitch's own comment for why it only clears.
// Preserves `tenant` (the only other scope param this page reads) and
// drops any existing `repo` in favour of the row's own. Facet params are
// deliberately NOT carried across: they were counted against a different
// scope, and a pill that survives into a set it was never measured on is a
// filter claiming a count it does not have.
function repoFilterHref(repo: string, tenant: string | null): string {
  const params = new URLSearchParams();
  if (tenant) params.set("tenant", tenant);
  params.set("repo", repo);
  return `/?${params}`;
}

export function RunsTable({
  runs,
  atCap,
  limit,
  tenant,
  scopeLabel,
}: {
  runs: RunSummary[];
  atCap: boolean;
  limit: number;
  tenant: string | null;
  scopeLabel: string;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // Sort travels in the URL for the same reason the facets do: a copied
  // link should restore the table the sender was looking at. Expansion
  // stays local — which rows you happened to open is a reading position,
  // not a view worth sharing, and it changes far too often to spend a
  // history entry on.
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());

  // The URL is the filter state, same as `repo`/`tenant` — an operator's
  // filtered view survives being copied to someone else. Writing it with
  // the native history API rather than router.push keeps `useSearchParams`
  // in sync WITHOUT a server round trip (Next 16 integrates both methods
  // into the router; see docs 01-app/01-getting-started/04-linking-and-navigating).
  // router.push here would refetch every run on every pill click.
  const selection = useMemo(
    () => parseFacetSelection((key) => searchParams.get(key)),
    [searchParams],
  );

  const sort = useMemo(() => parseSort(searchParams.get("sort")), [searchParams]);
  const query = useMemo(
    () => normalizeQuery(searchParams.get("q")),
    [searchParams],
  );
  const page = useMemo(() => parsePage(searchParams.get("page")), [searchParams]);

  const facetFiltering = Object.values(selection).some(
    (values) => values && values.length > 0,
  );
  const filtering = facetFiltering || query.length > 0;

  // Facets are built from the FULL fetched set, so a pill's count does not
  // change as other pills are pressed. Recomputing them against the
  // filtered set would zero out every unselected option the moment one
  // selection excluded it, which reads as "no such runs exist" rather than
  // "you have filtered them out". Search and paging do not affect counts.
  const facets = useMemo(() => buildFacets(runs), [runs]);

  const groups = useMemo(
    () =>
      sortGroups(
        groupRunsByPr(
          filterRunsByQuery(filterRuns(runs, selection), query),
          atCap,
        ),
        sort,
      ),
    [runs, selection, query, atCap, sort],
  );

  const pageWindow = useMemo(
    () => pageSlice(groups, page, DEFAULT_PAGE_SIZE),
    [groups, page],
  );

  const shown = useMemo(
    () => groups.reduce((total, group) => total + group.runCount, 0),
    [groups],
  );

  /** One writer for every URL-borne piece of view state. Callers go through
   *  it so a sort can never drop the filters, or a filter the sort.
   *  `repo`/`tenant` survive untouched: they are the server's scope, and
   *  rewriting them here would change what is fetched.
   *  Changing facets / sort / search resets `page` to 1 unless the caller
   *  is the pager itself. */
  function writeView(next: {
    selection: FacetSelection;
    sort: SortState;
    query: string;
    page: number;
  }) {
    const params = new URLSearchParams(searchParams);

    const serialized = serializeFacets(next.selection);
    for (const key of FACET_KEYS) {
      const value = serialized[key];
      if (value === undefined) params.delete(key);
      else params.set(key, value);
    }

    const sortParam = serializeSort(next.sort);
    if (sortParam === null) params.delete("sort");
    else params.set("sort", sortParam);

    const q = normalizeQuery(next.query);
    if (q === "") params.delete("q");
    else params.set("q", q);

    if (next.page <= 1) params.delete("page");
    else params.set("page", String(next.page));

    const queryString = params.toString();
    window.history.pushState(
      null,
      "",
      queryString ? `${pathname}?${queryString}` : pathname,
    );
  }

  function toggleFacet(key: FacetKey, value: string) {
    const current = selection[key] ?? [];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    writeView({
      selection: { ...selection, [key]: next },
      sort,
      query,
      page: 1,
    });
  }

  function toggleGroup(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <>
      <FacetBar
        facets={facets}
        selection={selection}
        // The counts on those pills were computed over `runs` (unfiltered),
        // so their denominator must be `runs.length` too. Passing the
        // filtered `shown` here paired an unfiltered numerator with a
        // filtered denominator.
        totalFetched={runs.length}
        atCap={atCap}
        onToggle={toggleFacet}
        onClear={() => writeView({ selection: {}, sort, query, page: 1 })}
      />

      <div className="flex flex-wrap items-center gap-3 py-5">
        <p className="mono flex min-w-0 flex-1 items-center gap-3 text-[10.5px] uppercase tracking-[.16em] text-muted-foreground">
          Runs — verdict history {scopeLabel}
          <span className="h-px flex-1 bg-border" />
          <CountLine
            shown={shown}
            total={runs.length}
            groups={groups.length}
            limit={limit}
            atCap={atCap}
            filtering={filtering}
          />
        </p>
        <label className="sr-only" htmlFor="runs-search">
          Search runs
        </label>
        <Input
          id="runs-search"
          type="search"
          placeholder="Search repo, PR, title…"
          defaultValue={query}
          key={query}
          className="mono h-8 w-full max-w-xs text-xs"
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            const value = (event.target as HTMLInputElement).value;
            writeView({ selection, sort, query: value, page: 1 });
          }}
          onBlur={(event) => {
            const value = event.target.value;
            if (normalizeQuery(value) === query) return;
            writeView({ selection, sort, query: value, page: 1 });
          }}
        />
      </div>

      {groups.length === 0 ? (
        // An empty result under a filter and an empty ledger are different
        // facts, and neither is a blank table with a header above it.
        <p className="mono py-8 text-center text-xs text-muted-foreground">
          {filtering
            ? "No run matches this filter. The runs are there — the filter excludes them."
            : "No runs in this scope."}
        </p>
      ) : (
        <>
          <Table className="table-fixed border-collapse">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                {COLUMNS.map((column) => (
                  <TableHead
                    key={column.label}
                    // px-2.5 matches the cells below. Without it the
                    // right-aligned "score" heading butted straight into
                    // "pull request" and the two read as one word.
                    aria-sort={
                      column.sort === undefined
                        ? undefined
                        : sort.key === column.sort
                          ? sort.dir === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                    }
                    className={`mono h-auto border-b border-border px-2.5 pb-[7px] text-[10px] font-medium uppercase tracking-[.13em] text-muted-foreground ${column.cls}`}
                  >
                    {column.sort === undefined ? (
                      column.label
                    ) : (
                      <button
                        type="button"
                        onClick={() =>
                          writeView({
                            selection,
                            sort: nextSort(sort, column.sort as SortKey),
                            query,
                            page: 1,
                          })
                        }
                        className={
                          "inline-flex items-center gap-1 uppercase tracking-[.13em] hover:text-foreground " +
                          (sort.key === column.sort ? "text-foreground" : "")
                        }
                      >
                        {column.label}
                        <span aria-hidden className="text-[9px] opacity-70">
                          {sort.key === column.sort
                            ? sort.dir === "desc"
                              ? "▾"
                              : "▴"
                            : "▿"}
                        </span>
                      </button>
                    )}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageWindow.items.map((group) => {
                const open = expanded.has(group.key);
                return (
                  <RunRows
                    key={group.key}
                    group={group}
                    open={open}
                    filtering={filtering}
                    tenant={tenant}
                    onToggle={() => toggleGroup(group.key)}
                  />
                );
              })}
            </TableBody>
          </Table>

          <Pager
            label={pageRangeLabel(pageWindow)}
            page={pageWindow.page}
            pageCount={pageWindow.pageCount}
            onPage={(nextPage) =>
              writeView({ selection, sort, query, page: nextPage })
            }
          />
        </>
      )}
    </>
  );
}

function Pager({
  label,
  page,
  pageCount,
  onPage,
}: {
  label: string;
  page: number;
  pageCount: number;
  onPage: (page: number) => void;
}) {
  if (pageCount <= 1) {
    return (
      <p className="mono mt-3 text-[10.5px] uppercase tracking-[.12em] text-muted-foreground">
        Showing {label}
      </p>
    );
  }
  return (
    <div className="mono mt-3 flex flex-wrap items-center gap-3 text-[10.5px] uppercase tracking-[.12em] text-muted-foreground">
      <span>
        Showing {label}
      </span>
      <span className="h-px flex-1 bg-border" />
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        className="rounded-md border border-border px-2 py-1 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
      >
        Prev
      </button>
      <span>
        Page {page} / {pageCount}
      </span>
      <button
        type="button"
        disabled={page >= pageCount}
        onClick={() => onPage(page + 1)}
        className="rounded-md border border-border px-2 py-1 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
      >
        Next
      </button>
    </div>
  );
}

/** Filter/fetched totals, not the viewport. After paging, the pager below
 *  the table is what states "showing X–Y of Z"; this line answers how many
 *  runs survived facets/search across the whole fetched set — the same
 *  honesty rule the facet pills use.
 *
 *  `total` is the fetched set and `shown` is what survived the filter; at
 *  the cap neither is a count of the scope, which is why "latest {limit}"
 *  replaces a bare total rather than qualifying it in a tooltip. */
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
  const prs = (
    <>
      {" "}
      across <b className="text-foreground">{groups}</b> {groups === 1 ? "pr" : "prs"}
    </>
  );

  if (filtering) {
    return (
      <span>
        <b className="text-foreground">{shown}</b> of{" "}
        {atCap ? (
          <>
            the latest <b className="text-foreground">{limit}</b>
          </>
        ) : (
          <b className="text-foreground">{total}</b>
        )}{" "}
        runs{prs}
      </span>
    );
  }

  return (
    <span>
      {atCap ? (
        <>
          latest <b className="text-foreground">{limit}</b>
        </>
      ) : (
        <b className="text-foreground">{total}</b>
      )}{" "}
      runs{prs}
    </span>
  );
}

function RunRows({
  group,
  open,
  filtering,
  tenant,
  onToggle,
}: {
  group: PrGroup;
  open: boolean;
  filtering: boolean;
  tenant: string | null;
  onToggle: () => void;
}) {
  const count = runCountLabel(group, filtering);
  // A PR with one run gets NO control and NO badge. A chevron that expands
  // to nothing claims there is more to see, and "1" beside every
  // single-run row is noise standing in for information.
  const hasHistory = group.children.length > 0;

  return (
    <>
      <TableRow className="border-b border-border/50 hover:bg-muted/40">
        <RunCells
          run={group.latest}
          tenant={tenant}
          disclosure={
            hasHistory ? (
              <button
                type="button"
                onClick={onToggle}
                aria-expanded={open}
                aria-label={`${open ? "Collapse" : "Expand"} the ${count.title} on ${group.repo} #${group.prNumber}`}
                title={count.title}
                // Taller than the text it holds: at px-1/text-[10px] the
                // control was a 26x15 target in a 34px row, which is a miss
                // waiting to happen on a table this dense.
                className="mono flex-none rounded-[3px] px-1.5 py-1 text-[10px] leading-none text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <span aria-hidden>{open ? "▾" : "▸"}</span> {count.text}
              </button>
            ) : null
          }
        />
      </TableRow>
      {open &&
        group.children.map((child) => (
          <TableRow
            key={child.verdict_id}
            className="border-b border-border/40 bg-muted/25"
          >
            <RunCells run={child} tenant={tenant} indented />
          </TableRow>
        ))}
    </>
  );
}

/** One outcome window's cell — 14-day or 60-day, or the absence of either.
 *  Every branch of the rule lives in lib/runs — `outcomeTone` decides the
 *  colour, `outcomeLabel` the marker and word — so this cell, its sibling
 *  window's cell, and the run detail tile cannot drift into describing the
 *  same row differently, and so the rule stays somewhere `node --test` can
 *  reach it.
 *
 *  Only `flag` gets the extra weight. Bold is emphasis, and the two muted
 *  states — no row yet, and a row recording that the PR left the risk set
 *  unobserved — are precisely the ones with nothing to emphasise. */
function OutcomeCell({ kind }: { kind: string | null }) {
  const tone = outcomeTone(kind);
  const weight = tone === "flag" ? " font-semibold" : "";
  return <span className={outcomeToneClass(tone) + weight}>{outcomeLabel(kind)}</span>;
}

/** The nine cells of one run. Children render the identical columns —
 *  an older run is a full verdict, not a summary of one — and are marked
 *  as history by indentation and a rule, never by dropping data. */
function RunCells({
  run,
  tenant,
  disclosure = null,
  indented = false,
}: {
  run: RunSummary;
  tenant: string | null;
  disclosure?: React.ReactNode;
  indented?: boolean;
}) {
  // A job row only carries a verdict_id once ingest.complete() sets it,
  // and that same UPDATE sets status="done" in the same statement
  // (api/doug/ingest.py:508-509); fail() only ever touches a row still
  // status="running" and a revive nulls verdict_id back out. So run.job,
  // when present here, is always "done" — there is no reachable "failed"
  // state to render on a verdict-keyed row. A failed attempt has no
  // verdict at all, and surfacing those needs a query keyed on jobs
  // instead of verdicts (Phase 2).
  const duration = run.job ? jobDuration(run.job.started_at, run.job.finished_at) : null;
  const jobLabel = run.job ? (duration ? `${run.job.status} · ${duration}` : run.job.status) : "—";

  return (
    <>
      <TableCell className="h-[34px] px-2.5 text-right">
        <span
          className={
            "mono text-[14.5px] font-semibold " +
            (run.band === "flagged" ? "data-flag" : "data-clear")
          }
        >
          {run.score.toFixed(2)}
        </span>
      </TableCell>
      <TableCell className="h-[34px] min-w-0 px-2.5 whitespace-normal">
        {indented ? (
          // A child row's repo, number and title are its parent's, verbatim
          // — rendering them again three rows deep is repetition, not
          // information. What distinguishes one run of a PR from the next is
          // WHEN it ran, so that is what the cell carries, still linking to
          // this run's own forensics.
          <div className="flex min-w-0 items-center gap-2 pl-3">
            <span className="min-w-[38px] flex-none" />
            <Link
              href={`/runs/${run.verdict_id}`}
              className="mono truncate text-[11px] text-muted-foreground hover:text-foreground hover:underline"
            >
              {utcTimestamp(run.scored_at)}
            </Link>
          </div>
        ) : (
        <div className="flex min-w-0 items-center gap-2">
          {/* The slot reserves its width whether or not a control lives in
              it, so a PR with history and a PR without one still start
              their repo name at the same x. Without the min-width the span
              collapsed to zero and every expandable row sat shifted right
              of its neighbours. min-w rather than w so an unusually large
              count nudges the row instead of being clipped. */}
          <span className="min-w-[38px] flex-none text-right">{disclosure}</span>
          <span className="mono flex-none whitespace-nowrap text-[11px] text-muted-foreground">
            <Link
              href={repoFilterHref(run.repo, tenant)}
              aria-label={`Filter runs to ${run.repo}`}
              className="hover:text-foreground hover:underline"
            >
              {run.repo}
            </Link>{" "}
            {/* The PR number is the route out to GitHub. `url` comes off
                pr_meta, or is derived from repo + pr_number when a row has
                none — both are real ledger values, never a guess. It is
                still typed nullable, so a row without one renders plain
                text rather than a link to nowhere. */}
            {run.url ? (
              <a
                href={run.url}
                target="_blank"
                rel="noreferrer"
                aria-label={`Open ${run.repo} #${run.pr_number} on GitHub`}
                className="font-medium text-foreground hover:underline"
              >
                #{run.pr_number}
              </a>
            ) : (
              <b className="font-medium text-foreground">#{run.pr_number}</b>
            )}
          </span>
          <Link
            href={`/runs/${run.verdict_id}`}
            className="min-w-0 flex-1 truncate text-[12.5px] hover:underline"
          >
            {run.title}
          </Link>
        </div>
        )}
      </TableCell>
      <TableCell className="h-[34px] px-2.5">
        <BandChip band={run.band} />
      </TableCell>
      <TableCell className="mono h-[34px] px-2.5 text-[11px] text-muted-foreground">
        {run.tier}
      </TableCell>
      <TableCell className="h-[34px] px-2.5">
        <CoverageBar coverage={run.coverage} changedFiles={run.changed_files} />
      </TableCell>
      {/* Two independent cells — deliberately not one window falling back to
          the other. See COLUMNS' docstring above for why a fallback would
          misrepresent the row. */}
      <TableCell className="mono h-[34px] px-2.5 text-xs">
        <OutcomeCell kind={run.outcome_14} />
      </TableCell>
      <TableCell className="mono h-[34px] px-2.5 text-xs">
        <OutcomeCell kind={run.outcome_60} />
      </TableCell>
      <TableCell className="mono h-[34px] px-2.5 text-[11px] text-muted-foreground">
        {jobLabel}
      </TableCell>
      <TableCell className="mono h-[34px] px-2.5 text-right text-[11px] text-muted-foreground">
        {relativeAge(run.scored_at)}
      </TableCell>
    </>
  );
}
