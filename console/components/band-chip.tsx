import type { Band } from "@/lib/api";

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
        "mono inline-flex items-center rounded-[3px] px-[7px] py-0.5 text-[11.5px] uppercase tracking-[.06em] " +
        (flagged
          ? "bg-[color-mix(in_srgb,var(--flag)_9%,transparent)] text-[var(--flag)]"
          : "bg-[color-mix(in_srgb,var(--clear)_9%,transparent)] text-[var(--clear)]")
      }
    >
      {flagged ? "needs you" : "cleared"}
    </span>
  );
}
