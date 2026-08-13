import type { ReactNode } from "react";

export interface ParamRow {
  name: string;
  meta?: string;
  description: ReactNode;
}

/** The name/type-left, description-right definition list used for CLI
 *  flags, label sources, MCP tools, API endpoints, and changelog entries —
 *  the one real tabular component in the ported docs (the source's other
 *  "tables" are hand-aligned monospace text inside code blocks, not
 *  markup, so those are ported as CodeBlock content instead of a table). */
export function ParamsTable({ rows }: { rows: ParamRow[] }) {
  return (
    <dl className="divide-y divide-border border-y border-border">
      {rows.map((r) => (
        <div
          key={r.name}
          className="grid gap-1 py-3.5 sm:grid-cols-[13rem_1fr] sm:gap-6"
        >
          {/* Three things have to hold at once in a fixed 13rem track:

              min-w-0 — a grid item's min-width defaults to auto, so without
              this it refuses to shrink below its content and a long name
              (`GET /v1/prs/:number/receipt`) escapes the track and overlaps
              the description.

              an explicit {" "} — name and meta are adjacent JSX expressions
              with NO whitespace text node between them, and the old ml-2 is a
              margin, not a soft-wrap opportunity. That made the two one
              unbreakable run, so the browser had to split mid-token and
              rendered "pl/anned". A real space is a break opportunity, so a
              meta that will not fit moves to the next line whole. (A
              flex-wrap version also fixes the break, but items-baseline
              inflates the line box of a name that wraps to two lines — 42px
              of dead space between name and meta.)

              break-words — lets a single token too long for the track split
              rather than overflow. Not whitespace-nowrap on the meta, which
              forbids wrapping outright and pushes a long one ("git | api |
              both · default git", 216px) back out of the 208px track. */}
          <dt className="min-w-0 font-mono text-[13px] break-words text-foreground">
            {r.name}{" "}
            {r.meta && (
              <span className="text-xs text-muted-foreground">{r.meta}</span>
            )}
          </dt>
          <dd className="text-sm leading-relaxed text-muted-foreground">
            {r.description}
          </dd>
        </div>
      ))}
    </dl>
  );
}
