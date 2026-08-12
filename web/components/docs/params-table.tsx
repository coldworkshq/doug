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
          <dt className="font-mono text-[13px] text-foreground">
            {r.name}
            {r.meta && (
              <span className="ml-2 text-xs text-muted-foreground">
                {r.meta}
              </span>
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
