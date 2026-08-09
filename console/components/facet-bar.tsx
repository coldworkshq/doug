"use client";

import type { Facet, FacetKey } from "@/lib/facets";

/** The pill row above the table.
 *
 *  These are NOT the scope chips in the shell. Scope (`?repo=`, `?tenant=`)
 *  decides what the server fetches; these narrow what is already fetched,
 *  in the browser, with no round trip. Keeping them visually distinct — a
 *  flat row under the header rather than bordered chips in the shell — is
 *  what stops an operator reading a pill as a change of scope.
 *
 *  Counts are over the full fetched set, so they do not move as other pills
 *  are pressed. At the page cap that set is only the newest N runs, and the
 *  title says so rather than calling it the scope.
 */
export function FacetBar({
  facets,
  selection,
  totalFetched,
  atCap,
  onToggle,
  onClear,
}: {
  facets: Facet[];
  selection: Partial<Record<FacetKey, string[]>>;
  /** The size of the population the option counts were computed over —
   *  the full fetched set, NOT what survives the current filter. A count
   *  and its denominator must come from the same population; pairing an
   *  unfiltered numerator with a filtered denominator let a pill read
   *  "32 of the 37 runs shown" while zero of those 37 were cleared, and
   *  could print a count larger than the total beside it. */
  totalFetched: number;
  /** Whether that fetched set is the whole scope or only its newest page.
   *  Without this the title said "in scope" over a truncated page — a
   *  scope-wide claim from a partial count, which is exactly what the
   *  header's "latest 500" and the group badge's "8+" refuse to make. */
  atCap: boolean;
  onToggle: (key: FacetKey, value: string) => void;
  onClear: () => void;
}) {
  if (facets.length === 0) return null;

  const active = Object.values(selection).some((values) => values && values.length > 0);

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border py-3">
      {facets.map((facet) => (
        <div key={facet.key} className="flex flex-wrap items-center gap-1.5">
          <span className="mono text-[10px] uppercase tracking-[.13em] text-muted-foreground">
            {facet.label}
          </span>
          {facet.options.map((option) => {
            const on = (selection[facet.key] ?? []).includes(option.value);
            // Frame and ink are computed separately and each utility is
            // emitted exactly once. Concatenating a second `text-*` onto a
            // string that already has one does NOT override it — Tailwind
            // resolves that collision by stylesheet order, not by the order
            // of the class attribute, so the winner is whichever utility
            // happens to be generated later.
            const frame = on
              ? "border-[var(--iridescent)] bg-accent"
              : "border-border bg-card hover:border-[var(--iridescent)]";
            // The two data colours, each still carrying its word — the
            // pill's label IS the secondary encoding the CVD floor
            // requires, exactly as in BandChip. No third data colour enters
            // here: every other facet stays on ink.
            const ink =
              facet.key === "band"
                ? option.value === "flagged"
                  ? "text-[var(--flag)]"
                  : "text-[var(--clear)]"
                : on
                  ? "text-foreground"
                  : "text-muted-foreground";
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => onToggle(facet.key, option.value)}
                aria-pressed={on}
                title={
                  atCap
                    ? `${option.count} of the newest ${totalFetched} runs fetched — the scope may hold more`
                    : `${option.count} of ${totalFetched} runs in scope`
                }
                className={`mono inline-flex items-center gap-1.5 rounded-[4px] border px-[7px] py-[3px] text-[11px] transition-colors ${frame} ${ink}`}
              >
                {option.label}
                <span className="text-[10px] tabular-nums opacity-60">{option.count}</span>
              </button>
            );
          })}
        </div>
      ))}

      {active && (
        <button
          type="button"
          onClick={onClear}
          className="mono ml-auto text-[10.5px] uppercase tracking-[.1em] text-muted-foreground underline decoration-dotted underline-offset-[3px] hover:text-foreground"
        >
          clear filters
        </button>
      )}
    </div>
  );
}
