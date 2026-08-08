import Link from "next/link";

import type { JobItem } from "@/lib/api";
import { ADJUDICATOR_GRACE_HOURS } from "@/lib/health";
import { parseUtc } from "@/lib/runs";

/** The store marks a row overdue with NO grace — `job_rows`'s predicate is
 *  `status='pending' AND due_at < now`, the same query the health strip
 *  applies `ADJUDICATOR_GRACE_HOURS` on top of before calling anything
 *  "failing" (`lib/health.ts`). The API can't own that grace itself: the
 *  adjudicator's schedule lives in Cloud Scheduler, not in Python. So every
 *  row the adjudicator hasn't reached yet TODAY lands here labelled overdue
 *  right alongside rows a pass has genuinely missed for days — and this page
 *  rendered no timestamp at all, so an operator could not tell "came due
 *  this morning, fine" from "three days past a pass that never ran".
 *
 *  The bare, alarming "clock overdue" wording (this strip's language for a
 *  row past grace) is reserved for exactly that: past-grace rows only.
 *  Within grace it reads the neutral "overdue 2h" — armed, not failing,
 *  same as the strip beside it.
 *
 *  Ages go through `parseUtc`, never `Date.parse` / `new Date(iso)` — see
 *  `lib/runs.ts:141` for why a second parser is the specific hazard, and
 *  `health-strip.tsx`'s own `age()` for the twin of this ladder rendering
 *  the strip's backward-looking cells. Not imported from there: that
 *  helper is module-private and this page has no other need of it, so a
 *  small local copy beats a new export whose only caller is this string.
 *
 *  `asOf` can be null: the health payload that carries it is fetched
 *  independently of these job rows (see the `maxAttempts` comment below),
 *  so one fetch can fail while the rows load fine. Degrade honestly rather
 *  than fabricate an age or a grace verdict with no clock to check it
 *  against — the same discipline the attempts-cap cell already applies. */
function overdueReason(dueAt: string | null, asOf: string | null): string {
  if (dueAt === null || asOf === null) return "overdue";
  const ms = parseUtc(asOf).getTime() - parseUtc(dueAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "overdue";
  const mins = Math.floor(ms / 60_000);
  const hours = Math.floor(mins / 60);
  const age = mins < 60 ? `${mins}m` : hours < 48 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
  return ms > ADJUDICATOR_GRACE_HOURS * 3_600_000 ? `clock overdue ${age}` : `overdue ${age}`;
}

/** The reason a row is here, in words. Derived server-side against each
 *  lane's own lease and carried on the row, so this component never
 *  recomputes it — that is what keeps this page and the strip agreeing.
 *  The one exception is `overdue`: the server's predicate deliberately has
 *  no grace (see `overdueReason` above), so the wording — not the row's
 *  membership in the list — is what this component still owns. */
function reason(job: JobItem, asOf: string | null): string {
  if (job.status === "failed") return `failed after ${job.attempts}`;
  if (job.stalled) return "lease expired";
  if (job.overdue) return overdueReason(job.due_at, asOf);
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
