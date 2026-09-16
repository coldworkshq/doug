import type { ReactNode } from "react";

import styles from "./docs.module.css";

/** A notice: an ember stripe for a caution or a limit, a coolant stripe
 *  (`cold`) for a fact about what the software does. It opens with a bold
 *  lead-in phrase when it has one ("Honest limit:", "Schema stability:"). */
export function Callout({
  lead,
  cold = false,
  children,
}: {
  lead?: string;
  cold?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={cold ? `${styles.note} ${styles.cold}` : styles.note}>
      {lead && <b>{lead}</b>} {children}
    </div>
  );
}
