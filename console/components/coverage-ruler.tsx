import { coveragePercent, type RunCoverage } from "@/lib/runs";

/** The console's signature element: every file the reader was given, in
 *  budget-consumption order, sized by share of the diff. Read is solid;
 *  never-read is hatched. The emptiness of the right-hand side IS the
 *  alarm — no hue is spent here.
 *
 *  Segments use flex-grow with a zero basis so the 2px gaps are subtracted
 *  from the track rather than added to it; percentage bases plus gaps
 *  overflow by exactly the sum of the gaps. The cut marker is an in-flow
 *  flex item, so it lands between the last read file and the first unread
 *  one by construction rather than by a hand-computed offset.
 *
 *  Unseen files carry no sensitive marking — see run-spine.tsx's sibling
 *  page for why: features._is_sensitive fires on zero of the files that
 *  motivated this page (tenancy.py, keyformat.py, migrations.py), so
 *  marking on it would be inert exactly when it matters. */
export function CoverageRuler({
  coverage,
  changedFiles,
}: {
  coverage: RunCoverage;
  changedFiles: number | null;
}) {
  const result = coveragePercent(coverage, changedFiles);
  const seenShare = coverage.sent_chars;
  const unseenShare = Math.max(0, coverage.diff_chars - coverage.sent_chars);
  const perUnseen = coverage.files_unseen.length
    ? unseenShare / coverage.files_unseen.length
    : 0;

  return (
    <div className="panel rounded-[6px] p-4">
      <div className="mono mb-3 flex items-baseline gap-2.5 text-xs text-muted-foreground">
        <span className="text-[19px] font-semibold text-foreground">
          {result.kind === "known" ? `${Math.round(result.pct)}%` : "—"}
        </span>
        <span>
          of the diff · {coverage.files_sent} of {changedFiles ?? "?"} files ·{" "}
          {coverage.sent_chars.toLocaleString()} of {coverage.diff_chars.toLocaleString()} chars
        </span>
        {coverage.file_cut && (
          <span className="ml-auto">
            cut at <code>{coverage.file_cut}</code>
          </span>
        )}
      </div>

      <div className="mb-6 flex h-[26px] items-stretch gap-0.5">
        <div className="cov-fill min-w-0.5 rounded-[2px]" style={{ flex: `${seenShare} 1 0` }} />
        <div className="relative -my-[7px] mx-[3px] w-px flex-none bg-foreground">
          <span className="mono absolute left-[-2px] top-[calc(100%+4px)] whitespace-nowrap text-[9px] uppercase tracking-[.08em]">
            budget cut ↑
          </span>
        </div>
        {coverage.files_unseen.map((path) => (
          <div
            key={path}
            title={`${path} — never read`}
            className="min-w-0.5 rounded-[2px] border border-dashed border-[#c9c6bd] bg-[repeating-linear-gradient(135deg,#c9c6bd_0_1.5px,transparent_1.5px_5px)]"
            style={{ flex: `${perUnseen} 1 0` }}
          />
        ))}
      </div>

      <div className="mono border-t border-border pt-3 text-[10px] uppercase tracking-[.12em] text-muted-foreground">
        Unseen — {coverage.files_unseen.length} files
      </div>
      <ul>
        {coverage.files_unseen.map((path) => (
          <li key={path} className="mono flex items-center gap-2.5 py-[3px] text-xs">
            <span className="text-muted-foreground">{path}</span>
            <span className="ml-auto text-[10.5px] text-muted-foreground/60">cut by file order</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
