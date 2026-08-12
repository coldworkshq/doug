// Ported verbatim from console/components/band-chip.tsx — keep the two in lockstep.
import type { RunSummary } from "@/lib/session-api";

// console imports a named `Band` alias from its lib/api. Web's session API
// inlines the same union on RunSummary and exports no `Band`, so the prop is
// typed off the row itself — the exact union the dashboard's rows carry,
// with no new type invented to bridge them.
type Band = RunSummary["band"];

/** The colour is ALWAYS accompanied by its word.
 *
 *  --flag and --clear sit in the 6-8 CVD floor band, where secondary
 *  encoding is not optional — the word IS that encoding. Never render this
 *  as a bare dot or a colour swatch. */
export function BandChip({ band }: { band: Band | null }) {
  if (band === null) {
    return <span className="mono text-xs text-muted-foreground">—</span>;
  }
  const flagged = band === "flagged";
  return (
    <span
      className={
        "mono inline-flex items-center rounded-[3px] px-[7px] py-0.5 text-[10.5px] uppercase tracking-[.06em] " +
        (flagged
          ? "bg-[color-mix(in_srgb,var(--flag)_9%,transparent)] text-[var(--flag)]"
          : "bg-[color-mix(in_srgb,var(--clear)_9%,transparent)] text-[var(--clear)]")
      }
    >
      {flagged ? "needs you" : "cleared"}
    </span>
  );
}
