"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { JobItem } from "@/lib/api";
import { overdueReason, pendingReason } from "@/lib/health";
import {
  DEFAULT_PAGE_SIZE,
  pageRangeLabel,
  pageSlice,
  parsePage,
} from "@/lib/paging";
import { filterJobsByQuery, normalizeQuery } from "@/lib/search";

/** The reason a row is here, in words. Mostly derived server-side against
 *  each lane's own lease and carried on the row, so this component does not
 *  recompute it — that is what keeps this page and the strip agreeing.
 *
 *  The two exceptions are `overdue` and fresh `pending`, and they are the
 *  same exception twice: `store.job_rows` applies no grace and no threshold,
 *  because both describe things the ledger does not store (a Cloud Scheduler
 *  cron; how often the drain is kicked). So a clock the adjudicator simply
 *  has not reached today, and a job enqueued one second ago, both arrive in
 *  the "unhealthy only" list while the strip beside them reads clear.
 *
 *  Those rows do belong on a page whose question is "what is Doug waiting
 *  on" — it is the WORDING that must not overstate. Both labellers live in
 *  `lib/health.ts` beside the thresholds they compare against, so the table
 *  and the strip grade against one definition and cannot contradict each
 *  other about the same row. They are also the only logic here that a test
 *  can reach: this component has no render-test infrastructure. */
function reason(job: JobItem, asOf: string | null): string {
  if (job.status === "failed") return `failed after ${job.attempts}`;
  if (job.stalled) return "lease expired";
  if (job.overdue) return overdueReason(job.due_at, asOf);
  if (job.retrying) return `retrying, attempt ${job.attempts}`;
  if (job.status === "done" && job.verdict_id === null) return "skipped, no verdict";
  if (job.status === "pending") return pendingReason(job.enqueued_at, asOf);
  return job.status;
}

export function JobsTable({
  title,
  jobs,
  atCap,
  limit,
  maxAttempts,
  asOf,
  urlKey,
}: {
  title: string;
  jobs: JobItem[];
  atCap: boolean;
  limit: number;
  // Null, not a literal 0, when the health payload that carries this
  // lane's cap couldn't be read. getHealth() is fetched independently
  // here and in Shell (two round-trips, two 8s timeouts), so one can fail
  // while the job rows themselves load fine — the rows are still true and
  // worth showing, only the denominator is unknown. A 0 fallback would
  // render as a real-looking "2/0" cap; see the attempts cell below for
  // how null renders instead.
  maxAttempts: number | null;
  // Same independent-fetch caveat as maxAttempts, and the same reason: the
  // health payload that carries the server's clock can fail on its own.
  // Threaded through to overdueReason so this table's "clock overdue"
  // grace boundary can never drift from the strip's — see that function's
  // own comment for why null degrades to neutral wording rather than a
  // fabricated age.
  asOf: string | null;
  /** Distinguishes the two tables on /jobs so each keeps its own q/page. */
  urlKey: "review" | "outcome";
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const qParam = `${urlKey}_q`;
  const pageParam = `${urlKey}_page`;

  const query = useMemo(
    () => normalizeQuery(searchParams.get(qParam)),
    [searchParams, qParam],
  );
  const page = useMemo(
    () => parsePage(searchParams.get(pageParam)),
    [searchParams, pageParam],
  );

  const filtered = useMemo(
    () => filterJobsByQuery(jobs, query, (job) => reason(job, asOf)),
    [jobs, query, asOf],
  );
  const pageWindow = useMemo(
    () => pageSlice(filtered, page, DEFAULT_PAGE_SIZE),
    [filtered, page],
  );

  function writeView(nextQuery: string, nextPage: number) {
    const params = new URLSearchParams(searchParams);
    const q = normalizeQuery(nextQuery);
    if (q === "") params.delete(qParam);
    else params.set(qParam, q);
    if (nextPage <= 1) params.delete(pageParam);
    else params.set(pageParam, String(nextPage));
    const queryString = params.toString();
    window.history.pushState(
      null,
      "",
      queryString ? `${pathname}?${queryString}` : pathname,
    );
  }

  return (
    <section className="mt-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 className="mono text-xs uppercase tracking-[.08em] text-muted-foreground">
          {title}{" "}
          <span className="text-muted-foreground/70">
            {atCap ? `newest ${limit} fetched` : `${jobs.length} in scope`}
            {query
              ? ` · ${filtered.length} match${filtered.length === 1 ? "" : "es"}`
              : ""}
          </span>
        </h2>
        <label className="sr-only" htmlFor={`${urlKey}-jobs-search`}>
          Search {title}
        </label>
        <Input
          id={`${urlKey}-jobs-search`}
          type="search"
          placeholder="Search repo, status, error…"
          defaultValue={query}
          key={query}
          className="mono h-8 w-full max-w-xs text-xs"
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            writeView((event.target as HTMLInputElement).value, 1);
          }}
          onBlur={(event) => {
            if (normalizeQuery(event.target.value) === query) return;
            writeView(event.target.value, 1);
          }}
        />
      </div>

      {filtered.length === 0 ? (
        // Empty is not zero, and this says which one it is.
        <p className="mono mt-3 text-xs text-muted-foreground">
          {query
            ? "No jobs match this search. The lane still has rows — the query excludes them."
            : "No jobs in this lane match the current filter."}
        </p>
      ) : (
        <>
          <Table className="mono mt-3 w-full text-left text-xs">
            <TableHeader>
              <TableRow className="hover:bg-transparent text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">
                <TableHead className="h-auto py-1.5 pr-3 font-medium">id</TableHead>
                <TableHead className="h-auto py-1.5 pr-3 font-medium">
                  repo / PR
                </TableHead>
                <TableHead className="h-auto py-1.5 pr-3 font-medium">
                  state
                </TableHead>
                <TableHead className="h-auto py-1.5 pr-3 font-medium">
                  attempts
                </TableHead>
                <TableHead className="h-auto py-1.5 font-medium">error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageWindow.items.map((job) => (
                <TableRow
                  key={`${job.lane}-${job.id}`}
                  className="border-t border-border/60 align-top"
                >
                  <TableCell className="py-2 pr-3 tabular-nums text-muted-foreground">
                    {job.id}
                  </TableCell>
                  <TableCell className="py-2 pr-3 whitespace-normal">
                    {/* A missing repo name renders the bare id. installation_repos
                        can be stale or absent, and a guessed name would be the
                        console claiming something it does not know. */}
                    {job.repo ?? (
                      <span className="text-muted-foreground">
                        repo id {job.github_repo_id}
                      </span>
                    )}{" "}
                    <span className="text-muted-foreground">#{job.pr_number}</span>
                    {job.verdict_id !== null ? (
                      <Link
                        href={`/runs/${job.verdict_id}`}
                        className="ml-2 underline underline-offset-2"
                      >
                        forensics
                      </Link>
                    ) : null}
                  </TableCell>
                  <TableCell className="py-2 pr-3 whitespace-normal">
                    {reason(job, asOf)}
                  </TableCell>
                  <TableCell className="py-2 pr-3 tabular-nums">
                    {maxAttempts === null ? (
                      // Never a fraction over an absent denominator — "2/0" and
                      // "2/—" both read as a real cap. Say plainly that the cap
                      // itself is unknown, so this can't be mistaken for one.
                      <>
                        {job.attempts}{" "}
                        <span className="text-muted-foreground normal-case tracking-normal">
                          cap unknown
                        </span>
                      </>
                    ) : (
                      `${job.attempts}/${maxAttempts}`
                    )}
                  </TableCell>
                  <TableCell className="py-2 whitespace-pre-wrap break-all text-muted-foreground">
                    {/* Rendered in full, untruncated: an operator needs the whole
                        exception string, and this console is IAM-gated. */}
                    {job.error ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <JobsPager
            label={pageRangeLabel(pageWindow)}
            page={pageWindow.page}
            pageCount={pageWindow.pageCount}
            onPage={(nextPage) => writeView(query, nextPage)}
          />
        </>
      )}
    </section>
  );
}

function JobsPager({
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
      <span>Showing {label}</span>
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
