import type { ReactNode } from "react";

import styles from "./docs.module.css";

export interface ParamRow {
  name: string;
  meta?: string;
  description: ReactNode;
}

/** The name-left, description-right list used for CLI flags, label sources,
 *  MCP tools, API endpoints, and changelog entries.
 *
 *  The meta sits on its own line under the name. Inline beside the name it
 *  had to share a 13rem track with it, and a long meta ("git | api | both ·
 *  default git") either split mid-token or pushed out of the track.
 *
 *  Rows are keyed by position as well as name: the changelog repeats a date
 *  ("2026-07" three times), and a key that repeats is a React warning and a
 *  row React may reuse for the wrong entry. */
export function ParamsTable({ rows }: { rows: ParamRow[] }) {
  return (
    <dl className={styles.params}>
      {rows.map((r, i) => (
        <div key={`${i}-${r.name}`} className={styles.param}>
          <dt>
            {r.name}
            {r.meta && <span>{r.meta}</span>}
          </dt>
          <dd>{r.description}</dd>
        </div>
      ))}
    </dl>
  );
}
