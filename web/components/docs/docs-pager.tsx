import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

import { adjacentDocsPages } from "@/lib/docs-nav";

/** Prev/next footer nav, derived from the same ordered tree the sidebar
 *  renders — see lib/docs-nav.ts. Renders nothing at either end of reading
 *  order rather than wrapping (a "next" from Changelog back to Introduction
 *  would read as a bug). */
export function DocsPager({ currentHref }: { currentHref: string }) {
  const { prev, next } = adjacentDocsPages(currentHref);
  if (!prev && !next) return null;

  return (
    <nav
      aria-label="Docs pages"
      className="mt-16 flex items-center justify-between gap-4 border-t border-border pt-6"
    >
      {prev ? (
        <Link
          href={prev.href}
          className="group flex flex-col items-start gap-1 rounded-xl px-4 py-3 transition-colors hover:bg-accent"
        >
          <span className="flex items-center gap-1 font-mono text-[11px] tracking-wide text-muted-foreground uppercase">
            <ChevronLeft className="size-3" /> Previous
          </span>
          <span className="font-heading font-medium text-foreground group-hover:text-accent-foreground">
            {prev.title}
          </span>
        </Link>
      ) : (
        <span />
      )}
      {next ? (
        <Link
          href={next.href}
          className="group flex flex-col items-end gap-1 rounded-xl px-4 py-3 text-right transition-colors hover:bg-accent"
        >
          <span className="flex items-center gap-1 font-mono text-[11px] tracking-wide text-muted-foreground uppercase">
            Next <ChevronRight className="size-3" />
          </span>
          <span className="font-heading font-medium text-foreground group-hover:text-accent-foreground">
            {next.title}
          </span>
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}
