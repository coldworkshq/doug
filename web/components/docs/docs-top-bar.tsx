import Link from "next/link";

import { NAV_LINKS } from "@/components/site-header";
import { ThemeToggle } from "@/components/theme-toggle";
import { GITHUB_REPO_URL } from "@/lib/links";

import { DocsCrumb } from "./docs-crumb";
import styles from "./docs.module.css";

/** The docs' top bar: the audit docs' flat, full-width bar, carrying the
 *  public header's nav. The links are SiteHeader's own NAV_LINKS, never a
 *  copy, so the docs and every other public page cannot disagree about the
 *  door's nav (ADR-0034); only the presentation is the docs'.
 *
 *  Below 1180px the links move into a native <details> menu, which works
 *  without JavaScript. GitHub and About are in both navs, like SiteHeader's.
 *  The bar is session-free: Sign in is a plain link, and reading the session
 *  to choose a word would render every docs page per request (ADR-0019). */
export function DocsTopBar() {
  return (
    <header className={styles.top}>
      <Link className={styles.wm} href="/">
        COLDWORKS
      </Link>
      <DocsCrumb />
      <div className={styles.topEnd}>
        <nav aria-label="Site" className={styles.navlinks}>
          {NAV_LINKS.map((l) => (
            <Link key={l.href} href={l.href}>
              {l.label}
            </Link>
          ))}
          <a href={GITHUB_REPO_URL}>GitHub</a>
          <Link href="/about">About</Link>
        </nav>
        <details className={styles.menu}>
          <summary>Menu</summary>
          <nav aria-label="Site sections">
            {NAV_LINKS.map((l) => (
              <Link key={l.href} href={l.href}>
                {l.label}
              </Link>
            ))}
            <a href={GITHUB_REPO_URL}>GitHub</a>
            <Link href="/about">About</Link>
          </nav>
        </details>
        <ThemeToggle />
        <Link className={styles.toplink} href="/sign-in">
          Sign in
        </Link>
      </div>
    </header>
  );
}
