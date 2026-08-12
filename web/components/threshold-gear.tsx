"use client";

// The control that composes a threshold lens. The LENS itself is a query param
// the server reads (lib/threshold-lens.ts); this is only the thing that writes
// it, which is why the client boundary stops here and does not reach the page.
//
// Radix's Popover and Slider both need JavaScript, so this control does too.
// The lens does not: it is a URL param, rendered on the server, and the banner
// the page draws when one is active carries its own reset <Link>. Without
// JavaScript the gear is simply absent — an active lens is still visible,
// still correct and still clearable. That is stated rather than papered over;
// a control that silently does nothing is the failure being avoided.
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Slider } from "@/components/ui/slider";

/** Doug's own default deterministic line (api/doug/scoring.py:16). Used ONLY
 *  as the slider's starting position when there is no lens yet — never
 *  rendered as a claim about the runs on screen, because the line a given
 *  verdict was scored against is stamped per-row and this page does not know a
 *  single one for the whole ledger. */
const SUGGESTED_START = 0.62;

export function ThresholdGear({
  lens,
  carried,
}: {
  lens: number | null;
  carried: Array<[string, string]>;
}) {
  const [draft, setDraft] = React.useState(lens ?? SUGGESTED_START);

  // The lens can change under this component without it unmounting — the page
  // re-renders on the server after every navigation. Re-seed the draft from the
  // prop so reopening the gear shows the lens that is actually applied, rather
  // than the last position the slider happened to be dragged to.
  React.useEffect(() => {
    setDraft(lens ?? SUGGESTED_START);
  }, [lens]);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Adjust the needs-you line"
          className="mono relative flex h-[30px] cursor-pointer items-center gap-1.5 rounded-[5px] border border-border bg-card px-2 text-[11px] text-muted-foreground hover:border-[var(--iridescent)] hover:text-foreground focus-visible:border-[var(--iridescent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color-mix(in_srgb,var(--iridescent)_35%,transparent)]"
        >
          <svg viewBox="0 0 16 16" aria-hidden className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.4">
            <circle cx="8" cy="8" r="2.1" />
            <path d="M8 1.4v2M8 12.6v2M1.4 8h2M12.6 8h2M3.3 3.3l1.4 1.4M11.3 11.3l1.4 1.4M12.7 3.3l-1.4 1.4M4.7 11.3l-1.4 1.4" strokeLinecap="round" />
          </svg>
          needs-you line
          {/* The dot is never the ONLY signal that a lens is on — the page
              draws a full banner above the table. It is a locator for the
              control that set it, not the disclosure itself. */}
          {lens !== null && (
            <span aria-hidden className="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-[var(--iridescent)]" />
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[290px]">
        <form method="GET" action="/dashboard" className="flex flex-col gap-3">
          {/* A GET form submits only its own controls. Without these, setting a
              lens would silently clear every pill, the sort and the search. */}
          {carried.map(([key, item]) => (
            <input key={key} type="hidden" name={key} value={item} />
          ))}
          <div>
            <p className="mono text-[11px] font-medium text-foreground">Show needs-you at</p>
            <p className="mono mt-1 text-[10px] leading-[1.45] text-muted-foreground">
              Re-bands this ledger from the scores Doug already recorded. It does not
              change how Doug scores, and the run detail keeps its own recorded line.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Slider
              value={[draft]}
              onValueChange={([next]) => setDraft(next)}
              min={0}
              max={1}
              step={0.01}
              aria-label="Needs-you threshold"
              className="flex-1"
            />
            <span className="mono w-9 text-right text-[13px] tabular-nums text-foreground">
              {draft.toFixed(2)}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {/* The two submit buttons OWN this field between them — there is no
                hidden input, deliberately. A named submit button contributes its
                entry at its own position in the form, without replacing anything
                else, so a hidden `threshold` alongside them would submit BOTH and
                the page's `value()` helper takes the first: "Clear" would have
                silently re-applied the current lens. Exactly one button submits,
                so exactly one value travels.

                Apply is first, so Enter-to-submit inside the popover applies the
                draft rather than clearing it. */}
            <Button
              type="submit"
              name="threshold"
              value={String(draft)}
              size="sm"
              className="mono flex-1 text-[11px]"
            >Apply</Button>
            {/* An empty value is how the lens is removed: parseThresholdLens
                reads blank as no lens, and thresholdChanges drops the param.
                Rendered only when there is something to clear. */}
            {lens !== null && (
              <Button
                type="submit"
                name="threshold"
                value=""
                size="sm"
                variant="ghost"
                className="mono text-[11px] text-muted-foreground"
              >Clear</Button>
            )}
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
