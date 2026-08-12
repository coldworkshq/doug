/** The docs sidebar's shape: source of truth for nav, prev/next paging, and
 *  the sidebar filter — all three derive from this one ordered tree instead
 *  of each guessing at page order independently.
 *
 *  Mirrors drewjst.github.io/doug/docs's five sidebar groups and eleven
 *  sections, but as real routes (one per page) instead of scrollspy anchors
 *  over one long document — see docs/superpowers/specs for why.
 */

export type DocsStatus = "available" | "preview" | "planned";

export interface DocsPage {
  href: string;
  title: string;
  /** Absent on pages that never carried a status badge upstream either
   *  (Introduction, Changelog) — not every doc is a claim about the product. */
  status?: DocsStatus;
}

export interface DocsGroup {
  name: string;
  pages: DocsPage[];
}

export const DOCS_NAV: readonly DocsGroup[] = [
  {
    name: "Getting started",
    pages: [
      { href: "/docs", title: "Introduction" },
      { href: "/docs/quickstart", title: "Quickstart", status: "available" },
    ],
  },
  {
    name: "Concepts",
    pages: [
      { href: "/docs/risk-routing", title: "Risk routing", status: "available" },
      { href: "/docs/defect-labels", title: "Defect labels", status: "available" },
      { href: "/docs/cleared-band", title: "The cleared band", status: "available" },
      {
        href: "/docs/what-doug-gets-wrong",
        title: "What Doug gets wrong",
        status: "available",
      },
    ],
  },
  {
    name: "Reference",
    pages: [
      { href: "/docs/cli", title: "CLI · doug-backtest", status: "available" },
      { href: "/docs/report", title: "The report", status: "available" },
    ],
  },
  {
    name: "Coming up",
    pages: [
      { href: "/docs/mcp", title: "MCP · Pattern Garden", status: "preview" },
      { href: "/docs/rest-api", title: "REST API", status: "planned" },
    ],
  },
  {
    name: "Meta",
    pages: [{ href: "/docs/changelog", title: "Changelog" }],
  },
] as const;

/** Reading order, flattened — the one thing prev/next and "does this href
 *  exist" both need and must never independently redefine. */
export function flattenDocsNav(groups: readonly DocsGroup[] = DOCS_NAV): DocsPage[] {
  return groups.flatMap((g) => g.pages);
}

/** Neighbors in reading order, for a page footer's prev/next links. Both are
 *  `null` off the ends rather than wrapping — a "next" link from Changelog
 *  back to Introduction would read as a bug, not a feature. */
export function adjacentDocsPages(
  href: string,
  groups: readonly DocsGroup[] = DOCS_NAV,
): { prev: DocsPage | null; next: DocsPage | null } {
  const flat = flattenDocsNav(groups);
  const i = flat.findIndex((p) => p.href === href);
  if (i === -1) return { prev: null, next: null };
  return { prev: flat[i - 1] ?? null, next: flat[i + 1] ?? null };
}

/** The sidebar filter's match rule: substring, case-insensitive, title only —
 *  same contract as the gh-pages site's filter (it never indexed body copy,
 *  so this doesn't either; a query that reads like real search would over-
 *  promise). A group with zero surviving pages is dropped, not shown empty. */
export function filterDocsNav(
  query: string,
  groups: readonly DocsGroup[] = DOCS_NAV,
): DocsGroup[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...groups];
  return groups
    .map((g) => ({
      ...g,
      pages: g.pages.filter((p) => p.title.toLowerCase().includes(q)),
    }))
    .filter((g) => g.pages.length > 0);
}
