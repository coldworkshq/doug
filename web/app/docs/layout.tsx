import type { Metadata } from "next";

import styles from "@/components/docs/docs.module.css";
import { DocsSidebar } from "@/components/docs/docs-sidebar";
import { DocsTopBar } from "@/components/docs/docs-top-bar";

export const metadata: Metadata = {
  // Applies to every page below /docs; /docs itself names its own title,
  // because a template never applies to its own segment's page.
  title: { template: "%s — Coldworks docs", default: "Coldworks docs" },
};

/** Shared chrome for the whole /docs surface, in the audit docs' look: the
 *  gradient rail at the left edge, the top bar, then a sidebar and one
 *  reading column. Every docs page renders inside it, the audit's included;
 *  nothing under /docs brings its own chrome.
 *
 *  The top bar's height is one token, --cw-top-h in docs.module.css, which the
 *  sidebar's sticky offset and the headings' scroll margin both read. */
export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.root}>
      <div className={styles.rail} aria-hidden="true" />
      <DocsTopBar />
      <div className={styles.shell}>
        <aside className={styles.side}>
          <DocsSidebar />
        </aside>
        <main className={styles.doc}>{children}</main>
      </div>
    </div>
  );
}
