import { classify, type HealthPayload } from "@/lib/health";
import { parseUtc } from "@/lib/runs";

const LEVEL_CLASS: Record<string, string> = {
  // Colour is never the only carrier — every cell renders its word too.
  failing: "text-[var(--flag)]",
  degraded: "text-[var(--iridescent)]",
  clear: "text-muted-foreground",
  unknown: "text-muted-foreground/60",
};

/** Ages are rendered against the server's as_of, never the browser clock.
 *
 *  Both operands go through `parseUtc`, not raw `Date.parse`: job_health's
 *  lane timestamps can cross the wire with no zone suffix at all (see
 *  `parseUtc`'s own docstring in lib/runs.ts), which `Date.parse` reads as
 *  local time instead of UTC. `lib/health.ts` already parses these same
 *  timestamps through `parseUtc` to classify them — a second parser here
 *  would let this component's rendered age and the classifier's verdict
 *  disagree about the same value with no error anywhere. */
function age(at: string | null, asOf: string): string | null {
  if (at === null) return null;
  const ms = parseUtc(asOf).getTime() - parseUtc(at).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  return hours < 48 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
}

export function HealthStrip({
  health,
}: {
  health: HealthPayload | { error: string };
}) {
  const verdict = classify(health);
  const asOf = "as_of" in health ? health.as_of : null;

  return (
    <div
      role="group"
      aria-label="Fleet health across every installation"
      className="mono ml-auto flex items-stretch overflow-hidden rounded-[5px] border border-border bg-card text-[11.5px]"
    >
      {verdict.cells.map((cell) => {
        // A detail that parses as a timestamp renders as an age against
        // as_of; anything else is already prose from the classifier.
        const detail =
          cell.detail && asOf && !Number.isNaN(parseUtc(cell.detail).getTime())
            ? age(cell.detail, asOf)
            : cell.detail;
        return (
          <span
            key={cell.key}
            className={`flex items-center gap-1.5 border-r border-border/70 px-[11px] py-[5px] last:border-r-0 ${LEVEL_CLASS[cell.level]}`}
            aria-label={
              cell.count === null
                ? `${cell.word}: not available`
                : `${cell.word}: ${cell.count}${detail ? `, ${detail}` : ""}`
            }
          >
            {/* Unknown renders neither a count nor a zero: those are
                different facts and must never be confused. */}
            <span aria-hidden="true" className="font-semibold tabular-nums">
              {cell.count === null ? "—" : cell.count}
            </span>
            <span className="text-[10.5px]">{cell.word}</span>
            {detail ? (
              <span className="text-[10px] text-muted-foreground/70">{detail}</span>
            ) : null}
          </span>
        );
      })}
      <span className="flex items-center border-l border-border px-[9px] text-[9px] uppercase tracking-[.04em] text-muted-foreground/60">
        all tenants
      </span>
    </div>
  );
}
