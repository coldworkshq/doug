"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

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
      className="flex items-center gap-1 rounded-md px-1.5 py-1 font-mono text-[11px] normal-case text-[#9aa298] transition-colors hover:bg-white/10 hover:text-[#edefea]"
    >
      {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
      {copied ? "copied" : "copy"}
    </button>
  );
}
