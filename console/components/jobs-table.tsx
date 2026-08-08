import Link from "next/link";

import type { JobItem } from "@/lib/api";

/** The reason a row is here, in words. Derived server-side against each
 *  lane's own lease and carried on the row, so this component never
 *  recomputes it — that is what keeps this page and the strip agreeing. */
function reason(job: JobItem): string {
  if (job.status === "failed") return `failed after ${job.attempts}`;
  if (job.stalled) return "lease expired";
  if (job.overdue) return "clock overdue";
  if (job.retrying) return `retrying, attempt ${job.attempts}`;
  if (job.status === "done" && job.verdict_id === null) return "skipped, no verdict";
  return job.status;
}

export function JobsTable({
  title,
  jobs,
  atCap,
  limit,
  maxAttempts,
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
                <td className="py-2 pr-3">{reason(job)}</td>
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
