import type { ReactNode } from "react";

/** A doc page's body: the prose, then its examples. One column, as the audit
 *  docs set it. The examples used to sit in a sticky rail beside Doug's
 *  prose; they follow it now, so a panel is read after the sentence that
 *  introduces it and is never squeezed beside a 760px reading column. */
export function DocsArticle({
  prose,
  examples,
}: {
  prose: ReactNode;
  examples?: ReactNode;
}) {
  return (
    <>
      {prose}
      {examples}
    </>
  );
}
