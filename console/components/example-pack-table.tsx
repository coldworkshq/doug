import Link from "next/link";

import { memberAttemptLabel, type AttemptSummary } from "@/lib/example-packs";

function Status({ status }: { status: AttemptSummary["capture_status"] }) {
  const tone = status === "failed" ? "data-flag" : status === "captured" ? "data-clear" : "text-muted-foreground";
  return <span className={`mono text-[10px] uppercase tracking-[.08em] ${tone}`}>{status}</span>;
}

function AttemptRows({ cohortId, attempts }: { cohortId: string; attempts: AttemptSummary[] }) {
  return attempts.map((attempt) => (
    <tr key={`${attempt.pack_hash}-${attempt.member}`} className="border-b border-border/70 last:border-0 hover:bg-muted/40">
      <td className="px-3 py-2.5">
        <Link
          href={`/example-packs/${attempt.pack_hash}?cohort=${encodeURIComponent(cohortId)}`}
          className="mono text-xs font-medium hover:text-[var(--iridescent)]"
        >
          {attempt.repository_full_name} #{attempt.pull_number}
        </Link>
        <p className="mono mt-0.5 text-[9px] text-muted-foreground">{attempt.pack_hash.slice(0, 12)}</p>
      </td>
      <td className="mono px-3 py-2.5 text-[10px] text-muted-foreground">{memberAttemptLabel(attempt)}</td>
      <td className="px-3 py-2.5"><Status status={attempt.capture_status} /></td>
      <td className="mono px-3 py-2.5 text-right text-xs">{attempt.findings}</td>
      <td className="mono px-3 py-2.5 text-[10px] text-muted-foreground">{attempt.captured_at}</td>
    </tr>
  ));
}

export function ExamplePackTable({
  cohortId,
  members,
  nonMembers,
}: {
  cohortId: string;
  members: AttemptSummary[];
  nonMembers: AttemptSummary[];
}) {
  const byInstrument = new Map<string, AttemptSummary[]>();
  for (const attempt of members) {
    byInstrument.set(attempt.instrument_id, [...(byInstrument.get(attempt.instrument_id) ?? []), attempt]);
  }
  return (
    <div className="mt-7 space-y-7 pb-16">
      {[...byInstrument.entries()].map(([instrumentId, attempts]) => (
        <section key={instrumentId}>
          <h2 className="mono mb-2 flex items-center gap-2 text-[10px] uppercase tracking-[.14em] text-muted-foreground">
            <span>instrument {instrumentId.slice(0, 12)}</span><span className="h-px flex-1 bg-border" /><span>{attempts.length} member{attempts.length === 1 ? "" : "s"}</span>
          </h2>
          <div className="overflow-x-auto border-y border-border">
            <table className="w-full min-w-[760px] text-left">
              <thead className="mono bg-muted/45 text-[9px] uppercase tracking-[.12em] text-muted-foreground">
                <tr><th className="px-3 py-2">PR / pack</th><th className="px-3 py-2">admission</th><th className="px-3 py-2">capture</th><th className="px-3 py-2 text-right">findings</th><th className="px-3 py-2">captured UTC</th></tr>
              </thead>
              <tbody><AttemptRows cohortId={cohortId} attempts={attempts} /></tbody>
            </table>
          </div>
        </section>
      ))}

      {members.length === 0 && (
        <p className="mono border-y border-border py-5 text-xs text-muted-foreground">No admitted member packs.</p>
      )}

      {nonMembers.length > 0 && (
        <details className="border-y border-border py-3">
          <summary className="mono cursor-pointer text-[10px] uppercase tracking-[.12em] text-muted-foreground">
            {nonMembers.length} non-member attempt{nonMembers.length === 1 ? "" : "s"} · excluded from scorecards
          </summary>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[760px] text-left"><tbody><AttemptRows cohortId={cohortId} attempts={nonMembers} /></tbody></table>
          </div>
        </details>
      )}
    </div>
  );
}
