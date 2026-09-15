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
// `<b>` inside a panel is its bright, bold emphasis. The audit palette has six
// tones, so several names share one: Doug's pages kept their names (Fn, Ok,
// Str, Dim) when they moved onto it, and each alias below says which tone it
// renders, not a color of its own.
function tone(className: string) {
  return function Tone({ children }: { children: ReactNode }) {
    return <span className={className}>{children}</span>;
  };
}

/** A shell prompt, an arrow, punctuation. */
export const Prompt = tone(styles.tPrompt);
/** The command being run, or a tool being called. */
export const Cmd = tone(styles.tCmd);
/** A function or tool name: renders as Cmd. */
export const Fn = Cmd;
/** A figure that came out well: renders as Cmd, set apart from Hot. */
export const Ok = Cmd;
/** A number, `null`, or `false` in a JSON sketch. */
export const Kw = tone(styles.tKw);
/** A result that disagrees, in the audit's panels. */
export const Warm = tone(styles.tWarm);
/** A string literal: renders as Warm, set apart from Kw. */
export const Str = Warm;
/** A count of what went wrong or could not be read. */
export const Hot = tone(styles.tHot);
/** A comment, or quieter output. */
export const Comment = tone(styles.tComment);
/** Quieter output: renders as Comment. */
export const Dim = Comment;
export const Bright = tone(styles.tBright);
