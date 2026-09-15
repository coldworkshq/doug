import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./docs.module.css";

/** A row of start-here cards: three across, two where a row names two
 *  things, one column on a phone. */
export function Cards({ columns = 3, children }: { columns?: 2 | 3; children: ReactNode }) {
  return <div className={columns === 2 ? `${styles.cards} ${styles.cards2}` : styles.cards}>{children}</div>;
}

/** One card: a title, a sentence, and where the link goes, in words. */
export function Card({
  href,
  title,
  cta,
  children,
}: {
  href: string;
  title: string;
  cta: string;
  children: ReactNode;
}) {
  return (
    <Link className={styles.card} href={href}>
      <b>{title}</b>
      <span>{children}</span>
      <em>{cta} →</em>
    </Link>
  );
}
