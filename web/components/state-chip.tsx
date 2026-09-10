import { CHIP_WORD, chipGloss, type ChipKind } from "@/lib/state-chip";

/** The chip and its sentence, always together (design lock T8, O1). The
 *  sentence is the chip's next sibling in the same container, at the same
 *  type size as the word, never a tooltip, so it cannot be cropped out of a
 *  screenshot. */
export function StateChip({
  kind,
  subject,
  detail,
}: {
  kind: ChipKind;
  subject: string;
  detail?: string;
}) {
  const gloss = chipGloss(kind, subject, detail);
  return (
    <span data-chip={kind} className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[12.5px] text-muted-foreground">
      <span className="mono rounded-[3px] border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-[.12em] text-muted-foreground">
        {CHIP_WORD[kind]}
      </span>
      <span className="text-[12.5px]">{gloss}</span>
    </span>
  );
}
