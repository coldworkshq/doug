import type { ReactNode } from "react";

import styles from "./docs.module.css";

/** A bordered table with a mono header row, scrolling sideways inside its
 *  own frame on a narrow screen rather than widening the page. Cells are
 *  positional: every row carries one cell per heading. */
export function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className={styles.tblwrap}>
      <table className={styles.tbl}>
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, r) => (
            <tr key={r}>
              {cells.map((cell, c) => (
                <td key={c}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
