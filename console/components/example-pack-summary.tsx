import { cohortMetric, type CohortDetail } from "@/lib/example-packs";

function Fact({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="min-w-0 border-l border-border px-4 first:border-l-0 first:pl-0">
      <dt className="mono text-[9px] uppercase tracking-[.14em] text-muted-foreground">{label}</dt>
      <dd className="mono mt-1 text-sm font-semibold">{value}</dd>
      {note && <p className="mt-1 text-[11px] leading-snug text-muted-foreground">{note}</p>}
    </div>
  );
}

export function ExamplePackSummary({ cohort }: { cohort: CohortDetail }) {
  const missing = cohort.completeness.missing.length;
  const extra = cohort.completeness.extra.length;
  return (
    <>
      <dl className="grid gap-y-4 border-y border-border py-4 sm:grid-cols-2 lg:grid-cols-5">
        <Fact
          label="availability"
          value={cohort.availability.status}
          note={cohort.availability.reason ?? "evidence set validated"}
        />
        <Fact
          label="eligible / member"
          value={`${cohort.completeness.completed_jobs} / ${cohort.completeness.members}`}
          note={`${missing} missing · ${extra} extra`}
        />
        <Fact
          label="adjudicated"
          value={`${cohort.adjudicated_findings} / ${cohort.total_findings}`}
          note="effective heads / findings"
        />
        <Fact
          label="instruments"
          value={String(cohort.instruments.length)}
          note="never pooled across revisions"
        />
        <Fact
          label="window"
          value={`${cohort.manifest.capture_started_at.slice(0, 10)} → ${cohort.manifest.capture_until.slice(0, 10)}`}
          note="half-open UTC admission"
        />
      </dl>

      <div className="mt-5 space-y-3">
        {cohort.availability.status === "incomplete" && (
          <div className="mono border-l-2 border-[var(--flag)] bg-[color-mix(in_srgb,var(--flag)_5%,transparent)] px-3 py-2 text-xs text-[var(--flag)]">
            Scorecards blocked: {missing} completed job{missing === 1 ? " is" : "s are"} missing a member pack.
          </div>
        )}
        {cohort.instruments.map((instrument) => {
          const yieldMetric = cohortMetric(
            cohort.availability.status,
            instrument.scorecard.validated_actionable,
            instrument.scorecard.yield_denominator,
          );
          const burdenMetric = cohortMetric(
            cohort.availability.status,
            instrument.scorecard.unsupported,
            instrument.scorecard.burden_denominator,
          );
          return (
            <section key={instrument.instrument_id} className="grid gap-3 border-b border-border pb-3 md:grid-cols-[minmax(0,1fr)_170px_170px]">
              <div className="min-w-0">
                <p className="mono truncate text-[10px] text-muted-foreground" title={instrument.instrument_id}>
                  instrument {instrument.instrument_id}
                </p>
                <p className="mt-1 text-xs">
                  {instrument.manifest.provider} · {instrument.manifest.pinned_model_id} · {instrument.manifest.effort}
                </p>
              </div>
              <div>
                <p className="mono text-[9px] uppercase tracking-[.12em] text-muted-foreground">validated yield</p>
                <p className={`mono mt-1 text-xs ${yieldMetric.kind === "rate" ? "data-clear" : "text-muted-foreground"}`}>
                  {yieldMetric.label}
                </p>
              </div>
              <div>
                <p className="mono text-[9px] uppercase tracking-[.12em] text-muted-foreground">unsupported burden</p>
                <p className={`mono mt-1 text-xs ${burdenMetric.kind === "rate" ? "data-flag" : "text-muted-foreground"}`}>
                  {burdenMetric.label}
                </p>
              </div>
            </section>
          );
        })}
      </div>
    </>
  );
}
