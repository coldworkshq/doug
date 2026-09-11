import Link from "next/link";

import { StateChip } from "@/components/state-chip";
import type { Slot } from "@/lib/overview-slots";

/** One type size for the figure AND its sentence (design lock, O1): the
 *  sentence is the figure's next sibling in the same container, at the same
 *  size, never a tooltip, so a screenshot cannot show the number without the
 *  words. The size is a constant so the two cannot drift apart. */
const SLOT_TYPE = "text-[22px] leading-[1.2] tracking-[-.01em]";

export function OverviewSlots({ slots }: { slots: Slot[] }) {
  return (
    <div className="mt-8 grid grid-cols-1 gap-0 border-t border-border sm:grid-cols-2">
      {slots.map((slot) => (
        <div key={slot.key} data-slot={slot.key} className="border-b border-border py-5 sm:pr-8">
          <Link href={slot.href} className="mono text-[10.5px] uppercase tracking-[.15em] text-muted-foreground no-underline hover:text-foreground">
            {slot.label}
          </Link>
          {slot.figure !== null ? (
            <p className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className={`${SLOT_TYPE} font-semibold text-foreground`}>{slot.figure}</span>
              <span className={`${SLOT_TYPE} text-muted-foreground`}>{slot.sentence}</span>
            </p>
          ) : (
            <p className="mt-2 text-sm">
              <StateChip kind={slot.chip?.kind ?? "unknown"} subject={slot.chip?.subject ?? slot.label} detail={slot.chip?.detail} />
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
