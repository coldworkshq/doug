/** The docs' shape: the one ordered tree the sidebar, prev/next paging, the
 *  sidebar filter, and the mobile section label all derive from, instead of
 *  each guessing at page order independently.
 *
 *  One site. Everything under /docs is a page of it: the overview at /docs,
 *  then one section per thing a reader can run, in the door's order (Doug
 *  reviews, then the audit). Until 2026-09-15 the audit's pages were static
 *  documents with their own chrome, linked from here as external anchors;
 *  they are routes in this shell now, and the audit's overview is the
 *  second half of /docs (next.config.ts redirects /docs/audit there).
 *
 *  The shape of Doug's section came from the GitHub Pages docs this app
 *  replaced; that site was retired to a redirect on 2026-08-24, so this tree
 *  is the only docs structure there is.
 */

export type DocsStatus = "available" | "preview" | "planned";

export interface DocsPage {
  href: string;
  title: string;
  /** Absent on pages that are not a claim about the product (the overview,
   *  the changelog). */
  status?: DocsStatus;
}

/** A page a section names before it is written: listed in the sidebar,
 *  never linked, never in reading order. It has no href by construction, so
 *  nothing can link to a page that does not exist. */
export interface DocsUpcoming {
  title: string;
  upcoming: true;
}

export type DocsEntry = DocsPage | DocsUpcoming;

export interface DocsGroup {
  name: string;
  entries: readonly DocsEntry[];
}

export interface DocsSection {
  name: string;
  /** Where the section is introduced: its half of the overview. */
  href: string;
  /** The status every page in the section shares unless it says otherwise. */
  status?: DocsStatus;
  groups: readonly DocsGroup[];
}

export const DOCS_HOME: DocsPage = { href: "/docs", title: "Overview" };

/** What the audit section's preview status means, said on every page of it
 *  and on its half of the overview. */
export const AUDIT_PREVIEW_LABEL = "Design preview · coldworks-audit has not shipped";

export const DOCS_SECTIONS: readonly DocsSection[] = [
  {
    name: "Doug reviews",
    href: "/docs#doug-reviews",
    groups: [
      {
        name: "Getting started",
        entries: [{ href: "/docs/quickstart", title: "Quickstart", status: "available" }],
      },
      {
        name: "Concepts",
        entries: [
          { href: "/docs/risk-routing", title: "Risk routing", status: "available" },
          { href: "/docs/defect-labels", title: "Defect labels", status: "available" },
          { href: "/docs/cleared-band", title: "The cleared band", status: "available" },
          { href: "/docs/what-doug-gets-wrong", title: "What Doug gets wrong", status: "available" },
        ],
      },
      {
        name: "Reference",
        entries: [
          { href: "/docs/cli", title: "CLI · doug-backtest", status: "available" },
          { href: "/docs/report", title: "The report", status: "available" },
        ],
      },
      {
        name: "Coming up",
        entries: [
          { href: "/docs/mcp", title: "MCP · Pattern Garden", status: "planned" },
          { href: "/docs/rest-api", title: "REST API", status: "preview" },
        ],
      },
      {
        name: "Meta",
        entries: [{ href: "/docs/changelog", title: "Changelog" }],
      },
    ],
  },
  {
    // A design preview: `coldworks-audit` is not installable yet, and every
    // page of the section says so.
    name: "The audit",
    href: "/docs#the-audit",
    status: "preview",
    groups: [
      {
        name: "Getting started",
        entries: [
          { href: "/docs/audit/quickstart", title: "Quickstart", status: "preview" },
          { href: "/docs/audit/connect", title: "Connect your traces", status: "preview" },
        ],
      },
      {
        name: "Reference",
        entries: [
          { href: "/docs/audit/cli", title: "The audit CLI", status: "preview" },
          { title: "The audit report", upcoming: true },
          { title: "Guards & subtraction", upcoming: true },
        ],
      },
    ],
  },
];

export function isDocsPage(entry: DocsEntry): entry is DocsPage {
  return !("upcoming" in entry);
}

/** Reading order, flattened: the overview, then every written page in tree
 *  order. The one thing prev/next and "does this href exist" both need and
 *  must never independently redefine. */
export function flattenDocsNav(sections: readonly DocsSection[] = DOCS_SECTIONS): DocsPage[] {
  return [
    DOCS_HOME,
    ...sections.flatMap((s) => s.groups.flatMap((g) => g.entries.filter(isDocsPage))),
  ];
}

/** Neighbors in reading order, for a page footer's prev/next links. Both are
 *  `null` off the ends rather than wrapping: a "next" from the last page back
 *  to the overview would read as a bug. */
export function adjacentDocsPages(
  href: string,
  sections: readonly DocsSection[] = DOCS_SECTIONS,
): { prev: DocsPage | null; next: DocsPage | null } {
  const flat = flattenDocsNav(sections);
  const i = flat.findIndex((p) => p.href === href);
  if (i === -1) return { prev: null, next: null };
  return { prev: flat[i - 1] ?? null, next: flat[i + 1] ?? null };
}

/** The sidebar filter's match rule: substring, case-insensitive, title only.
 *  It never indexed body copy, so a query that reads like real search would
 *  over-promise. */
export function matchesDocsQuery(title: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  return !q || title.toLowerCase().includes(q);
}

/** The tree with only matching entries. A group with none left is dropped,
 *  and a section with no group left is dropped, never shown empty. */
export function filterDocsNav(
  query: string,
  sections: readonly DocsSection[] = DOCS_SECTIONS,
): DocsSection[] {
  if (!query.trim()) return [...sections];
  return sections
    .map((s) => ({
      ...s,
      groups: s.groups
        .map((g) => ({ ...g, entries: g.entries.filter((e) => matchesDocsQuery(e.title, query)) }))
        .filter((g) => g.entries.length > 0),
    }))
    .filter((s) => s.groups.length > 0);
}

/** The small tag beside a sidebar entry, or null. A page carries a tag only
 *  where its status differs from the section's, so a preview section says
 *  "preview" once, not once per page; an upcoming entry always says so. */
export function sidebarTag(entry: DocsEntry, section: DocsSection): string | null {
  if (!isDocsPage(entry)) return "soon";
  if (!entry.status) return null;
  return entry.status === (section.status ?? "available") ? null : entry.status;
}

/** The section a page belongs to, or null for the overview and for an href
 *  the tree does not list. */
export function docsSectionOf(
  href: string,
  sections: readonly DocsSection[] = DOCS_SECTIONS,
): DocsSection | null {
  return (
    sections.find((s) => s.groups.some((g) => g.entries.some((e) => isDocsPage(e) && e.href === href))) ?? null
  );
}

/** What the page at `pathname` is called where the sidebar is collapsed:
 *  "Overview", or the section and the page ("The audit · Quickstart"),
 *  because two sections each have a Quickstart. */
export function docsPageLabel(
  pathname: string,
  sections: readonly DocsSection[] = DOCS_SECTIONS,
): string | null {
  if (pathname === DOCS_HOME.href) return DOCS_HOME.title;
  for (const s of sections) {
    for (const g of s.groups) {
      const page = g.entries.filter(isDocsPage).find((p) => p.href === pathname);
      if (page) return `${s.name} · ${page.title}`;
    }
  }
  return null;
}
