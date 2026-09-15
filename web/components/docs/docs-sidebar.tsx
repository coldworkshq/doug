"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useState, type MouseEvent } from "react";

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
 *  client-side filter over page titles and their section names. It never
 *  indexes page content; a real search would need an index this app does not
 *  have.
 *
 *  Below 900px the list collapses behind a "Sections · <section · page>"
 *  toggle rather than rendering seventeen entries ahead of the article. It
 *  is collapsed by default and closes when a link in it is followed: a tap on
 *  a page changes the route, and a tap on a section header only moves to an
 *  anchor on the same page, so closing on a pathname change alone would leave
 *  it open for the second. */
export function DocsSidebar() {
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const sections = useMemo(() => filterDocsNav(query), [query]);
  const showHome = matchesDocsQuery(DOCS_HOME.title, query);
  const current = docsPageLabel(pathname);

  // Back and forward change the pathname without a tap on a link, so reset on
  // that too, adjusted during render rather than in an effect
  // (react-hooks/set-state-in-effect rejects the latter; this is the
  // React-documented shape for resetting state when a prop changes).
  const [lastPathname, setLastPathname] = useState(pathname);
  if (pathname !== lastPathname) {
    setLastPathname(pathname);
    setMobileOpen(false);
  }

  const closeOnLink = (e: MouseEvent<HTMLDivElement>) => {
    if ((e.target as Element).closest("a")) setMobileOpen(false);
  };

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

      <div id="docs-sidebar-sections" className={styles.sideBody} data-open={mobileOpen} onClick={closeOnLink}>
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
            {/* The top bar also links "Doug reviews" and "The audit", to the
                door; the hidden word keeps this link's name distinct. */}
            <Link href={section.href} className={styles.section}>
              {section.name}
              <span className="sr-only"> docs</span>
              {section.status && <span className={styles.soon}> · {section.status}</span>}
            </Link>
            {section.groups.map((group) => (
              <div key={group.name}>
                <div className={styles.sec}>{group.name}</div>
                <ul className={styles.entries}>
                  {group.entries.map((entry) => {
                    const tag = sidebarTag(entry, section);
                    if (!isDocsPage(entry)) {
                      // Named, not linked: the page is not written yet.
                      return (
                        <li key={entry.title}>
                          <span className={`${styles.page} ${styles.dead}`}>
                            {entry.title}
                            {tag && <span className={styles.soon}>{tag}</span>}
                          </span>
                        </li>
                      );
                    }
                    const active = pathname === entry.href;
                    return (
                      <li key={entry.href}>
                        <Link
                          href={entry.href}
                          aria-current={active ? "page" : undefined}
                          className={pageClass(active)}
                        >
                          {entry.title}
                          {tag && <span className={styles.soon}>{tag}</span>}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
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
