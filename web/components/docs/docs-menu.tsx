"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import styles from "./docs.module.css";

/** The top bar's narrow-screen menu: a native <details>, so it opens without
 *  JavaScript. It is keyed by the pathname, because the docs layout that
 *  renders the bar persists across navigations; an uncontrolled <details>
 *  would stay open over the next page, and a new key remounts it closed. */
export function DocsMenu({ children }: { children: ReactNode }) {
  return (
    <details key={usePathname()} className={styles.menu}>
      <summary>Menu</summary>
      <nav aria-label="Site sections">{children}</nav>
    </details>
  );
}
