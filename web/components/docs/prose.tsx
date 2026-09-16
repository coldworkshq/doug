import type { ReactNode } from "react";

import type { DocsStatus } from "@/lib/docs-nav";

import { StatusBadge } from "./badge";
import styles from "./docs.module.css";

/** Eyebrow, status chip, H1, and lede, repeated at the top of every doc page.
 *  One component, so the pages cannot drift on spacing or heading scale
 *  relative to each other. `hot` sets the eyebrow in molten, for a page that
 *  is a published contract rather than a description. */
export function DocsPageHeader({
  kicker,
  title,
  status,
  statusLabel,
  hot = false,
  children,
}: {
  kicker?: string;
  title: string;
  status?: DocsStatus;
  statusLabel?: string;
  hot?: boolean;
  children?: ReactNode;
}) {
  return (
    <header>
      {(kicker || status) && (
        <div className={styles.eyebrowRow}>
          {kicker && (
            <span className={hot ? `${styles.eyebrow} ${styles.hot}` : styles.eyebrow}>{kicker}</span>
          )}
          {status && <StatusBadge status={status} label={statusLabel} />}
        </div>
      )}
      <h1>{title}</h1>
      {children && <div className={styles.lede}>{children}</div>}
    </header>
  );
}

/** A section heading. Its scroll margin clears the sticky top bar, so an
 *  anchor link (/docs#the-audit) lands on the heading, not under the bar. */
export function H2({ id, children }: { id?: string; children: ReactNode }) {
  return <h2 id={id}>{children}</h2>;
}

export function H3({ id, children }: { id?: string; children: ReactNode }) {
  return <h3 id={id}>{children}</h3>;
}

export function P({ dim = false, children }: { dim?: boolean; children: ReactNode }) {
  return <p className={dim ? styles.dim : undefined}>{children}</p>;
}

/** Fine print under a panel or a table. */
export function Small({ children }: { children: ReactNode }) {
  return <p className={styles.small}>{children}</p>;
}

export function UL({ children }: { children: ReactNode }) {
  return <ul>{children}</ul>;
}

export function OL({ start, children }: { start?: number; children: ReactNode }) {
  return <ol start={start}>{children}</ol>;
}

export function IC({ children }: { children: ReactNode }) {
  return <code>{children}</code>;
}
