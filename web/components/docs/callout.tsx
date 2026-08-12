import type { ReactNode } from "react";

/** An admonition box — always opens with a bold lead-in phrase, same
 *  convention as the source docs ("Tip —", "Known limits, stated plainly:").
 *  The accent stripe uses --ring rather than a hardcoded brand hex on
 *  purpose: --ring is already this app's "current accent" per theme (the
 *  brand orange in light, the iridescent cyan in dark), so the callout
 *  shifts with the rest of the page instead of fighting dark mode. */
export function Callout({
  lead,
  children,
}: {
  lead?: string;
  children: ReactNode;
}) {
  return (
    <div className="panel rounded-xl border-l-[3px] border-l-ring px-5 py-4 text-sm leading-relaxed text-muted-foreground">
      {lead && <p className="mb-1 font-medium text-foreground">{lead}</p>}
      {children}
    </div>
  );
}
