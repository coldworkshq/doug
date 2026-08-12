"use client";

import { ChevronDown, FileText, Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";

import { filterDocsNav, flattenDocsNav } from "@/lib/docs-nav";

import { StatusDot } from "./badge";

/** The left nav: grouped links with status dots, plus a client-side title
 *  filter. Matches the gh-pages site's actual contract, not an upgraded
 *  one — that "Filter sections…" input only ever substring-matched link
 *  labels, never page content, and this doesn't either. A real search
 *  would need an index this app doesn't have yet.
 *
 *  Below `lg` the full section list collapses behind a "Sections · <current
 *  page>" toggle instead of always rendering inline above the article — a
 *  fifteen-link list ahead of any actual content read as a layout defect on
 *  a phone. Collapsed by default, and closes again on navigation (a Link tap
 *  changes the route and Next scrolls to top; leaving it open would land the
 *  reader back at the nav instead of the page they just chose). `lg:block`
 *  unconditionally overrides the mobile `hidden` at that breakpoint, so
 *  desktop is untouched regardless of `mobileOpen`. */
export function DocsSidebar() {
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const groups = useMemo(() => filterDocsNav(query), [query]);
  const currentTitle = useMemo(
    () => flattenDocsNav().find((p) => p.href === pathname)?.title,
    [pathname],
  );

  // Close the mobile panel on navigation — adjusted during render, not in an
  // effect (react-hooks/set-state-in-effect rejects the latter here, and
  // this is the React-documented shape for "reset state when a prop
  // changes": https://react.dev/learn/you-might-not-need-an-effect). A Link
  // tap changes `pathname` and Next scrolls to top; leaving the panel open
  // would land the reader back at the nav instead of the page they chose.
  const [lastPathname, setLastPathname] = useState(pathname);
  if (pathname !== lastPathname) {
    setLastPathname(pathname);
    setMobileOpen(false);
  }

  return (
    <nav aria-label="Docs sections" className="text-sm">
      <button
        type="button"
        onClick={() => setMobileOpen((open) => !open)}
        aria-expanded={mobileOpen}
        aria-controls="docs-sidebar-sections"
        className="mb-4 flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-foreground lg:hidden"
      >
        <span className="truncate">
          Sections{currentTitle ? ` · ${currentTitle}` : ""}
        </span>
        <ChevronDown
          className={
            "size-3.5 shrink-0 text-muted-foreground transition-transform" +
            (mobileOpen ? " rotate-180" : "")
          }
          aria-hidden="true"
        />
      </button>

      <div
        id="docs-sidebar-sections"
        className={(mobileOpen ? "block" : "hidden") + " lg:block"}
      >
        <div className="relative mb-5">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter sections…"
            aria-label="Filter docs sections"
            className="w-full rounded-lg border border-border bg-background py-1.5 pr-3 pl-8 font-mono text-xs text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30 focus-visible:outline-none"
          />
        </div>

        <div className="space-y-6">
          {groups.map((g) => (
            <div key={g.name}>
              <p className="mb-2 px-2.5 font-mono text-[11px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
                {g.name}
              </p>
              <ul className="space-y-0.5">
                {g.pages.map((p) => {
                  const active = pathname === p.href;
                  return (
                    <li key={p.href}>
                      <Link
                        href={p.href}
                        aria-current={active ? "page" : undefined}
                        className={
                          "flex items-center gap-2 rounded-md px-2.5 py-1.5 transition-colors " +
                          (active
                            ? "bg-accent font-medium text-accent-foreground"
                            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground")
                        }
                      >
                        <StatusDot status={p.status} />
                        <span className="truncate">{p.title}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}

          {groups.length === 0 && (
            <p className="px-2.5 text-xs text-muted-foreground">
              No sections match “{query}.”
            </p>
          )}
        </div>

        <div className="mt-8 border-t border-border pt-4">
          <a
            href="/llms.txt"
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 font-mono text-xs text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
          >
            <FileText className="size-3.5" aria-hidden="true" />
            View as llms.txt
          </a>
        </div>
      </div>
    </nav>
  );
}
