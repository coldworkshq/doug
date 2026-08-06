import { coverageLabel, coveragePercent, type RunCoverage } from "@/lib/runs";

/** The console's signature element: every file the reader was given, in
 *  budget-consumption order, sized by share of the diff. Read is solid;
 *  never-read is hatched. The emptiness of the right-hand side IS the
 *  alarm — no hue is spent here; a low reading also gets a dotted
 *  underline and a warning glyph on the headline number, a structural
 *  mark rather than a colour one.
 *
 *  The unseen remainder is ONE block sized by `unseenShare`
 *  (`diff_chars - sent_chars`), not one box per `files_unseen` entry. The
 *  payload carries no per-file char count for anything unseen, so
 *  dividing evenly by file count would draw invented magnitude — a 40k-char
 *  lockfile and a 200-char `__init__.py` would get identical widths. The
 *  block instead carries thin hairline dividers, one per extra file, as a
 *  count cue rather than a measurement. Sizing it by `unseenShare` (rather
 *  than being present only when `files_unseen` is non-empty) also covers
 *  the case `files_unseen` can't: a budget that runs out mid-file, on the
 *  very last file, cuts real content while leaving `files_unseen` empty —
 *  every file's header still arrived, so none of them is "unseen" by name,
 *  but `sent_chars < diff_chars` all the same. Without this block that
 *  case rendered as a silent 100%-filled bar.
 *
 *  The cut marker (and its "budget cut" label) only renders when
 *  `coverage.file_cut` is set, matching the header's own "cut at …" gate —
 *  a complete read, or one whose budget happened to land clean between two
 *  whole files, has no single file to point the marker at. */
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
  const unseenCount = coverage.files_unseen.length;

  // Files, not chars, headline this ruler — changed_files gives files a
  // trustworthy denominator and a file count is what an operator acts on.
  // coverageLabel carries both rounding guards (see its docstring) — this
  // used to round in place with only the "<100%" guard, which silently
  // printed a false "0%" for a real-but-tiny read.
  const pctLabel = coverageLabel(result);
  const low = result.kind === "known" && result.low;

  return (
    <div className="panel rounded-[6px] p-4">
      <div className="mono mb-3 flex items-baseline gap-2.5 text-xs text-muted-foreground">
        <span
          className={
            "text-[19px] font-semibold text-foreground" +
            (low ? " underline decoration-dotted underline-offset-[4px]" : "")
          }
        >
          {pctLabel}
        </span>
        <span>
          of files · {coverage.files_sent} of {changedFiles ?? "?"} ·{" "}
          {coverage.sent_chars.toLocaleString()} of {coverage.diff_chars.toLocaleString()} chars in
          the bar below
        </span>
        {low && (
          <span className="text-[11px]" role="img" aria-label="low coverage">
            ⚠
          </span>
        )}
        {coverage.file_cut && (
          <span className="ml-auto">
            cut at <code>{coverage.file_cut}</code>
          </span>
        )}
      </div>

      {/* mb-6 clears the "budget cut ↑" label, which is absolutely
          positioned below the bar (top: calc(100% + 4px), inside a marker
          div stretched taller than the bar by -my-[7px] on top of that) —
          it needs room below the bar regardless of what renders next.
          Moving that margin onto the legend below and leaving none here
          let the label overprint the legend's in-flow text whenever the
          cut lands in roughly the left quarter of the track — precisely
          the low-coverage case this page exists to explain. */}
      <div className="mb-6 flex h-[26px] items-stretch gap-0.5">
        <div className="cov-fill min-w-0.5 rounded-[2px]" style={{ flex: `${seenShare} 1 0` }} />
        {coverage.file_cut && (
          <div className="relative -my-[7px] mx-[3px] w-px flex-none bg-foreground">
            <span className="mono absolute left-[-2px] top-[calc(100%+4px)] whitespace-nowrap text-[9px] uppercase tracking-[.08em]">
              budget cut ↑
            </span>
          </div>
        )}
        {unseenShare > 0 && (
          <div
            className="relative min-w-0.5 overflow-hidden rounded-[2px] border border-dashed border-[#c9c6bd] bg-[repeating-linear-gradient(135deg,#c9c6bd_0_1.5px,transparent_1.5px_5px)]"
            style={{ flex: `${unseenShare} 1 0` }}
            title={
              unseenCount
                ? `${unseenCount} file${unseenCount === 1 ? "" : "s"} never read — widths inside this block are even, not measured per file`
                : `never read past the cut${coverage.file_cut ? ` in ${coverage.file_cut}` : ""}`
            }
          >
            {Array.from({ length: Math.max(0, unseenCount - 1) }).map((_, i) => (
              <span
                key={i}
                aria-hidden="true"
                className="absolute top-0 bottom-0 w-px bg-background/70"
                style={{ left: `${((i + 1) / unseenCount) * 100}%` }}
              />
            ))}
          </div>
        )}
      </div>

      <div className="mono mb-4 flex items-center gap-4 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="cov-fill inline-block size-2 rounded-[2px]" aria-hidden="true" /> sent to
          the reader
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block size-2 rounded-[2px] border border-dashed border-[#c9c6bd] bg-[repeating-linear-gradient(135deg,#c9c6bd_0_1.5px,transparent_1.5px_5px)]"
            aria-hidden="true"
          />{" "}
          never read — budget
        </span>
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
