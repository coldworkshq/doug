import Link from "next/link";

import type { JobItem } from "@/lib/api";
import { overdueReason, pendingReason } from "@/lib/health";

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
}) {
  return (
    <section className="mt-8">
      <h2 className="mono text-xs uppercase tracking-[.08em] text-muted-foreground">
        {title}{" "}
        <span className="text-muted-foreground/70">
          {atCap ? `newest ${limit} fetched` : `${jobs.length} in scope`}
        </span>
      </h2>

      {jobs.length === 0 ? (
        // Empty is not zero, and this says which one it is.
        <p className="mono mt-3 text-xs text-muted-foreground">
          No jobs in this lane match the current filter.
        </p>
      ) : (
        <table className="mono mt-3 w-full text-left text-xs">
          <thead className="text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">
            <tr>
              <th className="py-1.5 pr-3 font-medium">id</th>
              <th className="py-1.5 pr-3 font-medium">repo / PR</th>
              <th className="py-1.5 pr-3 font-medium">state</th>
              <th className="py-1.5 pr-3 font-medium">attempts</th>
              <th className="py-1.5 font-medium">error</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={`${job.lane}-${job.id}`} className="border-t border-border/60 align-top">
                <td className="py-2 pr-3 tabular-nums text-muted-foreground">{job.id}</td>
                <td className="py-2 pr-3">
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
                </td>
                <td className="py-2 pr-3">{reason(job, asOf)}</td>
                <td className="py-2 pr-3 tabular-nums">
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
                </td>
                <td className="py-2 whitespace-pre-wrap break-all text-muted-foreground">
                  {/* Rendered in full, untruncated: an operator needs the whole
                      exception string, and this console is IAM-gated. */}
                  {job.error ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
