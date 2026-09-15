"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import styles from "./docs.module.css";

/** Copies a code panel's text. Its ink is the panel's, from docs.module.css,
 *  because the panel is ink in both themes. */
export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // Clipboard access can be denied or unavailable (insecure
          // context, permission policy) — a copy button failing silently
          // beats one that throws in the console.
        }
      }}
      aria-label="Copy to clipboard"
      className={styles.copy}
    >
      {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
      {copied ? "copied" : "copy"}
    </button>
  );
}
