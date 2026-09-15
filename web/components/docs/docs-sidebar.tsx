"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";

import {
  DOCS_HOME,
  docsPageLabel,
  filterDocsNav,
  isDocsPage,
  matchesDocsQuery,
  sidebarTag,
} from "@/lib/docs-nav";

import styles from "./docs.module.css";

/** The left nav: the overview, then each section with its groups, plus a
 *  client-side title filter. The filter only ever substring-matches titles,
 *  never page content; a real search would need an index this app does not
 *  have.
 *
 *  Below 900px the list collapses behind a "Sections · <section · page>"
 *  toggle rather than rendering seventeen entries ahead of the article. It
 *  is collapsed by default and closes again on navigation: a Link tap changes
 *  the route and Next scrolls to top, so leaving it open would land the
 *  reader back on the nav instead of the page they chose. */
export function DocsSidebar() {
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const sections = useMemo(() => filterDocsNav(query), [query]);
  const showHome = matchesDocsQuery(DOCS_HOME.title, query);
  const current = docsPageLabel(pathname);

  // Close the mobile panel on navigation, adjusted during render rather than
  // in an effect (react-hooks/set-state-in-effect rejects the latter; this is
  // the React-documented shape for resetting state when a prop changes).
  const [lastPathname, setLastPathname] = useState(pathname);
  if (pathname !== lastPathname) {
    setLastPathname(pathname);
    setMobileOpen(false);
  }

  const pageClass = (active: boolean) => (active ? `${styles.page} ${styles.on}` : styles.page);

  return (
    <nav aria-label="Docs sections">
      <button
        type="button"
        onClick={() => setMobileOpen((open) => !open)}
        aria-expanded={mobileOpen}
        aria-controls="docs-sidebar-sections"
        className={styles.sideToggle}
      >
        <span>Sections{current ? ` · ${current}` : ""}</span>
        <ChevronDown
          className="size-3.5 shrink-0"
          style={mobileOpen ? { transform: "rotate(180deg)" } : undefined}
          aria-hidden="true"
        />
      </button>

      <div id="docs-sidebar-sections" className={styles.sideBody} data-open={mobileOpen}>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter sections…"
          aria-label="Filter docs sections"
          className={styles.filter}
        />

        {showHome && (
          <Link
            href={DOCS_HOME.href}
            aria-current={pathname === DOCS_HOME.href ? "page" : undefined}
            className={pageClass(pathname === DOCS_HOME.href)}
          >
            {DOCS_HOME.title}
          </Link>
        )}

        {sections.map((section) => (
          <div key={section.name}>
            <Link href={section.href} className={styles.section}>
              {section.name}
              {section.status && <span className={styles.soon}> · {section.status}</span>}
            </Link>
            {section.groups.map((group) => (
              <div key={group.name}>
                <div className={styles.sec}>{group.name}</div>
                {group.entries.map((entry) => {
                  const tag = sidebarTag(entry, section);
                  if (!isDocsPage(entry)) {
                    // Named, not linked: the page is not written yet.
                    return (
                      <span key={entry.title} className={`${styles.page} ${styles.dead}`}>
                        {entry.title}
                        {tag && <span className={styles.soon}>{tag}</span>}
                      </span>
                    );
                  }
                  const active = pathname === entry.href;
                  return (
                    <Link
                      key={entry.href}
                      href={entry.href}
                      aria-current={active ? "page" : undefined}
                      className={pageClass(active)}
                    >
                      {entry.title}
                      {tag && <span className={styles.soon}>{tag}</span>}
                    </Link>
                  );
                })}
              </div>
            ))}
          </div>
        ))}

        {!showHome && sections.length === 0 && (
          <p className={styles.empty}>No sections match “{query}.”</p>
        )}

        <div className={styles.sideFoot}>
          <a href="/llms.txt">View as llms.txt</a>
        </div>
      </div>
    </nav>
  );
}
