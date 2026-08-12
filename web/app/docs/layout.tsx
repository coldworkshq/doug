import { DocsSidebar } from "@/components/docs/docs-sidebar";
import { SiteHeader } from "@/components/site-header";

/** Shared chrome for the whole /docs surface: the same floating SiteHeader
 *  as /, then a sidebar + content grid.
 *
 *  Unlike the gh-pages source (sidebar hard-hidden below 900px, no
 *  replacement — see lib/docs-nav's sibling exploration notes), this
 *  degrades by falling out of the two-column grid entirely below `lg`, so
 *  the nav renders inline above the article instead of vanishing (the
 *  sidebar itself further collapses behind a toggle on top of that — see
 *  DocsSidebar).
 *
 *  The aside's sticky offset shares --docs-content-offset (globals.css) with
 *  H2's scroll-margin in components/docs/prose.tsx, so both clear the
 *  floating SiteHeader from one number instead of two independently
 *  hand-tuned ones. */
export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <SiteHeader maxWidthClassName="max-w-6xl" />
      <main className="mx-auto w-full max-w-6xl px-6">
        <div className="grid gap-10 py-12 lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-16 lg:py-16">
          <aside className="lg:sticky lg:top-[var(--docs-content-offset)] lg:h-[calc(100vh-8rem)] lg:overflow-y-auto">
            <DocsSidebar />
          </aside>
          <div className="min-w-0 pb-24">{children}</div>
        </div>
      </main>
    </>
  );
}
