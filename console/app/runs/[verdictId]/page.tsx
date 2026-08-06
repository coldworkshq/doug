import Link from "next/link";
import { notFound } from "next/navigation";

import { BandChip } from "@/components/band-chip";
import { CoverageRuler } from "@/components/coverage-ruler";
import { RunSpine } from "@/components/run-spine";
import { Shell } from "@/components/shell";
import { getRunDetail, isError } from "@/lib/api";

export const dynamic = "force-dynamic";

function Block({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mono mb-3 flex items-center gap-2.5 text-[10px] font-medium uppercase tracking-[.16em] text-muted-foreground">
        {title}
        {note && <span className="text-[10.5px] normal-case tracking-normal text-foreground">{note}</span>}
        <span className="h-px flex-1 bg-border/60" />
      </h2>
      {children}
    </section>
  );
}

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ verdictId: string }>;
}) {
  const { verdictId } = await params;
  const id = Number(verdictId);
  if (!Number.isInteger(id) || id < 1) notFound();

  const run = await getRunDetail(id);
  const scope = { tenant: null, repo: null };

  if (isError(run)) {
    return (
      <Shell scope={scope} active="runs">
        <div className="mono mt-10 rounded-[6px] border border-[var(--flag)]/40 bg-[color-mix(in_srgb,var(--flag)_6%,transparent)] p-4 text-xs">
          <p className="font-semibold text-[var(--flag)]">The API did not answer.</p>
          <p className="mt-1 text-muted-foreground">{run.error}</p>
          <p className="mt-2 text-muted-foreground">
            Nothing is rendered below because nothing is known.
          </p>
        </div>
      </Shell>
    );
  }

  // run.pr is independently nullable from run.coverage — a verdict row can
  // carry pr_meta=NULL (every worker-path row before pr_meta capture, and
  // every /v1/score caller). repo and pr_number still travel at the top
  // level, so identity is never lost; changed_files, which lives only on
  // pr, is what's lost — the coverage denominator becomes unknown, not
  // zero. See lib/api.ts's RunDetail docstring.
  const changedFiles = run.pr?.changed_files ?? null;

  return (
    <Shell scope={scope} active="runs">
      <header className="flex items-start gap-5 border-b border-border py-5">
        <div className="min-w-0 flex-1">
          <div className="mono flex items-center gap-[7px] text-xs text-muted-foreground">
            <Link href="/" className="text-foreground hover:text-[var(--iridescent)]">← runs</Link>
            <span>·</span>
            <span>{run.repo}</span>
            <span>·</span>
            {run.pr?.url ? (
              <a href={run.pr.url} target="_blank" rel="noreferrer" className="text-foreground hover:text-[var(--iridescent)]">
                #{run.pr_number} ↗
              </a>
            ) : (
              <span className="text-foreground">#{run.pr_number}</span>
            )}
            {run.source && (
              <span className="rounded-[3px] border border-border px-1.5 text-[9.5px] uppercase tracking-[.12em]">
                {run.source}
              </span>
            )}
          </div>
          <h1 className="font-heading mt-1.5 text-[21px] font-semibold leading-tight tracking-tight">
            {run.pr ? (
              run.pr.title
            ) : (
              <span className="text-base font-normal italic text-muted-foreground">
                no PR metadata recorded for this run
              </span>
            )}
          </h1>
        </div>
        <div className="flex-none text-right">
          <div className={"mono text-[34px] font-semibold leading-none " + (run.band === "flagged" ? "data-flag" : "data-clear")}>
            {run.score.toFixed(2)}
          </div>
          <div className="mono mt-1.5 text-[10.5px] text-muted-foreground">
            <BandChip band={run.band} /> · threshold {run.threshold.toFixed(2)}
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-0 pb-16 lg:grid-cols-[232px_1fr]">
        <RunSpine run={run} />

        <div className="flex flex-col gap-6 pt-5 lg:pl-6">
          <Block title="What the reader was given">
            {run.coverage ? (
              <CoverageRuler coverage={run.coverage} changedFiles={changedFiles} />
            ) : (
              <p className="mono rounded-[5px] bg-muted px-3 py-2.5 text-xs text-muted-foreground">
                No read. This run was scored by the deterministic tier, so the diff was
                never opened — not a 0% read of a diff Doug saw.
              </p>
            )}
          </Block>

          <Block title="The read">
            <dl className="grid grid-cols-[132px_1fr] items-baseline gap-x-4 gap-y-[7px]">
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">tier</dt>
              <dd className="mono text-xs">{run.tier}</dd>
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">model</dt>
              <dd className="mono text-xs">{run.model ?? "—"}</dd>
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">prompt hash</dt>
              {/* NULL is "unstamped", never a match. Historical App-path reader
                  verdicts carry NULL because the worker never stamped it — the
                  CI endpoint did, which masked the gap. Rendering that as a
                  match asserts the frozen prompt ran when nobody can know. */}
              {run.prompt_hash === null ? (
                <dd className="mono text-xs">
                  <span className="underline decoration-dotted underline-offset-[3px]">unstamped</span>{" "}
                  <span className="text-muted-foreground">— predates prompt-hash stamping on the worker path</span>
                </dd>
              ) : (
                <dd className="mono text-xs">
                  {run.prompt_hash} <span className="data-clear">✓</span>{" "}
                  <span className="text-muted-foreground">matches the ADR-0002 frozen prompt</span>
                </dd>
              )}
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">risk score</dt>
              <dd className="mono text-xs">{run.risk_score ?? "—"} <span className="text-muted-foreground">/ 100</span></dd>
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">scored at</dt>
              <dd className="mono text-xs">{run.scored_at}</dd>
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">head sha</dt>
              <dd className="mono text-xs">{run.head_sha?.slice(0, 7) ?? "—"}</dd>
              {run.rationale && (
                <>
                  <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">rationale</dt>
                  <dd className="border-l-2 border-border pl-3 text-[12.5px] leading-relaxed text-muted-foreground">
                    {run.rationale}
                  </dd>
                </>
              )}
            </dl>
          </Block>

          <Block title="Findings" note={`${run.reasons.length} · ${run.tier} tier`}>
            {run.reasons.length === 0 ? (
              <p className="mono rounded-[5px] bg-muted px-3 py-2.5 text-xs text-muted-foreground">
                No findings.
              </p>
            ) : (
              run.reasons.map((r, i) => (
                <div key={`${r.rule}-${i}`} className="grid grid-cols-[62px_1fr] items-baseline gap-3 border-b border-border/50 py-2.5 last:border-0">
                  {/* Reader findings carry a severity and weight 0; deterministic
                      rules carry a weight and no severity. Showing "+0.00" beside
                      every reader finding prints a number that is constant by
                      construction. */}
                  <span className="mono rounded-[3px] bg-muted px-1.5 text-center text-[9.5px] uppercase tracking-[.1em] text-muted-foreground">
                    {r.severity ?? (r.weight ? `+${r.weight.toFixed(2)}` : "·")}
                  </span>
                  <div>
                    <div className="mono text-xs">{r.rule}</div>
                    <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{r.label}</div>
                  </div>
                </div>
              ))
            )}
          </Block>

          <Block title="Deviations" note="ADR-0007 · separate stream">
            {/* An empty list is a STORED result, not a missing one. The
                kind="none" marker row records "the read ran and found
                nothing", and _verdict_bundle filters it out server-side. */}
            {run.deviations.length === 0 ? (
              <p className="mono rounded-[5px] bg-muted px-3 py-2.5 text-xs text-muted-foreground">
                No deviations recorded. The read completed and found none — this is a
                stored result, not a missing one.
              </p>
            ) : (
              run.deviations.map((d, i) => (
                <div key={i} className="border-b border-border/50 py-2.5 last:border-0">
                  <div className="mono text-xs">{d.type}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{d.description}</div>
                </div>
              ))
            )}
          </Block>

          <Block title="Outcome">
            <div className="flex gap-2.5">
              {run.outcomes.map((o) => (
                <div key={o.window_days} className="panel flex-1 rounded-[6px] px-3.5 py-3">
                  <div className="mono text-[10px] uppercase tracking-[.12em] text-muted-foreground">
                    {o.window_days}-day window
                  </div>
                  <div className={"mono mt-1.5 text-[17px] font-semibold " + (o.kind === "clean" ? "data-clear" : "data-flag")}>
                    {o.kind === "clean" ? "✓ clean" : `↩ ${o.kind}`}
                  </div>
                  <div className="mono mt-1 text-[10.5px] text-muted-foreground">
                    graded {o.observed_at.slice(0, 10)}
                  </div>
                </div>
              ))}
              {run.outcome_jobs
                .filter((j) => !run.outcomes.some((o) => o.window_days === j.window_days))
                .map((j) => (
                  <div key={j.window_days} className="panel flex-1 rounded-[6px] px-3.5 py-3">
                    <div className="mono text-[10px] uppercase tracking-[.12em] text-muted-foreground">
                      {j.window_days}-day window
                    </div>
                    {/* Ungraded is not clean. */}
                    <div className="mono mt-1.5 text-sm font-medium text-muted-foreground">◷ {j.status}</div>
                    <div className="mono mt-1 text-[10.5px] text-muted-foreground">
                      grades {j.due_at.slice(0, 10)}
                    </div>
                  </div>
                ))}
              {run.outcomes.length === 0 && run.outcome_jobs.length === 0 && (
                <p className="mono rounded-[5px] bg-muted px-3 py-2.5 text-xs text-muted-foreground">
                  No outcome clock. This PR has not merged, so no window has started.
                </p>
              )}
            </div>
          </Block>
        </div>
      </div>
    </Shell>
  );
}
