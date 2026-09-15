import type { ReactNode } from "react";

import { CopyButton } from "./copy-button";
import styles from "./docs.module.css";

/** A terminal or JSON panel with a label in its bar. Ink in both themes: it
 *  stands in for a real terminal, and a terminal that goes pale in light mode
 *  is not one. `copyText` is optional because some panels are illustrative
 *  (an abridged real run, a JSON sketch), not something a reader would
 *  paste. */
export function CodeBlock({
  title,
  copyText,
  children,
}: {
  title: string;
  copyText?: string;
  children: ReactNode;
}) {
  return (
    <div className={styles.code}>
      <div className={styles.codebar}>
        <span>{title}</span>
        {copyText && <CopyButton text={copyText} />}
      </div>
      <pre>
        <code>{children}</code>
      </pre>
    </div>
  );
}

// Inline tones for the hand-authored examples: not a highlighter. The palette
// is the audit docs' (docs.module.css), picked against the fixed ink ground;
// `<b>` inside a panel is its bright, bold emphasis.
function tone(className: string) {
  return function Tone({ children }: { children: ReactNode }) {
    return <span className={className}>{children}</span>;
  };
}

/** A shell prompt, an arrow, punctuation. */
export const Prompt = tone(styles.tPrompt);
/** The command being run, or a tool being called. */
export const Cmd = tone(styles.tCmd);
export const Fn = Cmd;
/** A figure that came out well. */
export const Ok = Cmd;
/** A number, `null`, or `false` in a JSON sketch. */
export const Kw = tone(styles.tKw);
/** A string, or a result that disagrees. */
export const Warm = tone(styles.tWarm);
export const Str = Warm;
/** A count of what went wrong or could not be read. */
export const Hot = tone(styles.tHot);
/** A comment, or quieter output. */
export const Comment = tone(styles.tComment);
export const Dim = Comment;
export const Bright = tone(styles.tBright);
