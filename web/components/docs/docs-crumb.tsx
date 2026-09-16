"use client";

import { usePathname } from "next/navigation";

import styles from "./docs.module.css";

/** "/ docs / audit / cli": where the reader is, in the path's own words. */
export function DocsCrumb() {
  const parts = (usePathname() ?? "/docs").split("/").filter(Boolean);
  return <span className={styles.crumb}>/ {parts.join(" / ")}</span>;
}
