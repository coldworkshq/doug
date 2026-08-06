import { coveragePercent, type RunCoverage } from "@/lib/runs";

/** Coverage gets no hue. A low read is alarmed by how empty the track
 *  looks plus a dotted underline — magnitude problems are shown with
 *  magnitude, which keeps hue reserved for Doug's routing decision. */
export function CoverageBar({
  coverage,
  changedFiles,
}: {
  coverage: RunCoverage | null;
  changedFiles: number | null;
}) {
  const result = coveragePercent(coverage, changedFiles);

  if (result.kind === "no-read") {
    return <span className="mono text-xs text-muted-foreground">no read</span>;
  }
  if (result.kind === "unknown-denominator") {
    return (
      <span className="mono text-xs text-muted-foreground" title="pr_meta.changed_files is absent on this row">
        denominator unknown
      </span>
    );
  }
  // Math.round alone would print a genuine 0.3% read as "0%" — the same
  // false claim of nothing-read that "no read" exists to avoid making.
  // Below half a point, say so without rounding it away.
  const pctLabel = result.pct > 0 && result.pct < 0.5 ? "<1%" : `${Math.round(result.pct)}%`;
  return (
    <span className="flex items-center gap-2">
      <span className="cov-track h-[7px] w-[62px] flex-none overflow-hidden rounded-[2px]">
        <span className="cov-fill block h-full" style={{ width: `${result.pct}%` }} />
      </span>
      <span
        className={
          "mono min-w-[34px] text-xs " +
          (result.low ? "font-semibold underline decoration-dotted underline-offset-[3px]" : "")
        }
      >
        {pctLabel}
      </span>
      {result.low && (
        <span className="text-[11px]" role="img" aria-label="low coverage">⚠</span>
      )}
    </span>
  );
}
