/** The ⓘ, and it is the only affordance in the ledger whose whole job is to
 *  explain a word rather than to show one.
 *
 *  WHY IT EXISTS. `clean` and `pending` are the two most-rendered words in the
 *  runs table and the two most misread: "clean" looks like a verdict about the
 *  code, and "pending" looks like Doug still owes the PR a review. Neither is
 *  what the column means — lib/runs.ts's `outcomeMeaning` carries the
 *  sentences and the reasoning. Every other column names a thing the reader
 *  can see (a score, a repo, a percentage), so none of them needs one, and
 *  none of them gets one.
 *
 *  A NATIVE `title`, not a popover. The cost is a delay before the browser
 *  shows it, which is acceptable for a definition nobody needs mid-scan, and
 *  the gain is that it costs no client state, no portal and no layer above a
 *  table that already scrolls under a sticky header.
 *
 *  `tabIndex={0}` so it is reachable without a mouse, and the aria-label
 *  repeats the hint because a `title` alone is not reliably announced. The
 *  circle is drawn with `border-current`: it is chrome inside whatever ink
 *  already renders it, and it must never look like one of the two data
 *  colours a cell beside it might be carrying.
 *
 *  `tracking-normal` cancels the header's .13em, which would otherwise push
 *  the `i` off the centre of its own circle. */
export function InfoDot({ label, hint }: { label: string; hint: string }) {
  return (
    <span
      tabIndex={0}
      title={hint}
      aria-label={`${label}: ${hint}`}
      className="mono ml-[5px] inline-flex size-[13px] flex-none cursor-help items-center justify-center rounded-full border border-current align-[-2px] text-[9px] leading-none font-normal tracking-normal normal-case opacity-60 hover:opacity-100 focus-visible:opacity-100"
    >i</span>
  );
}
