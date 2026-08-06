import type { RunDetail } from "@/lib/api";
import { jobDuration } from "@/lib/runs";

function Event({
  title,
  stamp,
  sub,
  state,
}: {
  title: string;
  stamp: string;
  sub: string;
  state: "done" | "now" | "wait";
}) {
  const node =
    state === "now"
      ? "bg-[var(--clear)] border-[var(--clear)]"
      : state === "done"
        ? "bg-[#3d403c] border-[#3d403c]"
        : "bg-background border-[#c9c6bd]";
  return (
    <li className="relative pb-5 pl-5 last:pb-0 [&:not(:last-child)]:before:absolute [&:not(:last-child)]:before:left-[3.5px] [&:not(:last-child)]:before:top-[11px] [&:not(:last-child)]:before:bottom-[-3px] [&:not(:last-child)]:before:w-px [&:not(:last-child)]:before:bg-border">
      <span className={`absolute left-0 top-[5px] size-2 rounded-full border-[1.5px] ${node}`} />
      <div className="mono flex items-baseline gap-[7px] text-xs font-medium">
        {title}
        <span className="ml-auto text-[10.5px] font-normal text-muted-foreground">{stamp}</span>
      </div>
      <div className="mono mt-0.5 text-[10.5px] text-muted-foreground">{sub}</div>
    </li>
  );
}

/** The literal answer to "what did Doug do": webhook through outcome clock,
 *  with the real timestamps and durations from review_jobs. */
export function RunSpine({ run }: { run: RunDetail }) {
  const t = (iso: string | null) => (iso ? iso.slice(11, 19) : "—");
  const readDuration = jobDuration(run.job?.started_at ?? null, run.job?.finished_at ?? null);
  // run.pr is independently nullable from run.coverage — a deterministic
  // run can have pr_meta, and a read run can lack it. changed_files lives
  // only on pr, so a null pr here means the denominator is unknown, not
  // zero: the existing "?" fallback (also used when pr is present but
  // changed_files itself is null) covers both without ever printing 0.
  const changedFiles = run.pr?.changed_files ?? null;
  return (
    <aside className="border-r border-border pr-6 pt-5">
      <h2 className="mono mb-4 text-[10px] font-medium uppercase tracking-[.16em] text-muted-foreground">
        The run
      </h2>
      <ol>
        <Event title="job enqueued" stamp={t(run.job?.enqueued_at ?? null)} sub={`attempt ${run.job?.attempts ?? "?"} · gen ${run.job?.claim_generation ?? "?"}`} state="done" />
        <Event title="claimed" stamp={t(run.job?.started_at ?? null)} sub={run.job?.status ?? "no job row"} state="done" />
        <Event
          title="read"
          stamp={readDuration ?? "—"}
          sub={run.coverage ? `${run.coverage.files_sent} of ${changedFiles ?? "?"} files sent` : "no read — deterministic tier"}
          state="done"
        />
        <Event title={`verdict ${run.verdict_id}`} stamp={t(run.scored_at)} sub={`${run.tier} · ${run.score.toFixed(2)} ${run.band}`} state="done" />
        {run.outcomes.map((o) => (
          <Event key={o.window_days} title={`${o.window_days}d outcome`} stamp={o.observed_at.slice(5, 10)} sub={`graded ${o.kind}`} state="now" />
        ))}
        {run.outcome_jobs
          .filter((j) => !run.outcomes.some((o) => o.window_days === j.window_days))
          .map((j) => (
            <Event key={j.window_days} title={`${j.window_days}d outcome`} stamp={j.due_at.slice(5, 10)} sub={j.status} state="wait" />
          ))}
      </ol>
    </aside>
  );
}
