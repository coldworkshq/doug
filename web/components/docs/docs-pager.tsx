import Link from "next/link";

import { adjacentDocsPages, docsPageLabel, docsSectionOf, type DocsPage } from "@/lib/docs-nav";

import styles from "./docs.module.css";

/** Prev/next footer nav, derived from the same ordered tree the sidebar
 *  renders (lib/docs-nav.ts). Renders nothing at either end of reading order
 *  rather than wrapping. A neighbor in another section is named with its
 *  section: "Next: Quickstart" from Doug's changelog would read as Doug's
 *  quickstart, and it is the audit's. */
export function DocsPager({ currentHref }: { currentHref: string }) {
  const { prev, next } = adjacentDocsPages(currentHref);
  if (!prev && !next) return null;

  const here = docsSectionOf(currentHref);
  const label = (page: DocsPage) =>
    docsSectionOf(page.href) === here ? page.title : (docsPageLabel(page.href) ?? page.title);

  return (
    <nav aria-label="Docs pages" className={styles.pn}>
      {prev && (
        <Link href={prev.href}>
          <em>Previous</em>
          <b>{label(prev)}</b>
        </Link>
      )}
      {next && (
        <Link href={next.href} className={styles.next}>
          <em>Next</em>
          <b>{label(next)}</b>
        </Link>
      )}
    </nav>
  );
}
