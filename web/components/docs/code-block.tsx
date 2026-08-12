import type { ReactNode } from "react";

import { CopyButton } from "./copy-button";

/** A terminal/JSON example panel, matching the gh-pages docs site's
 *  code-rail treatment — see .code-rail/.code-rail-head in globals.css for
 *  why it's always dark regardless of site theme. `copyText` is optional
 *  because a couple of source blocks (an abridged real run, a JSON shape
 *  sketch) are illustrative, not something a reader would paste. */
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
    <div className="code-rail overflow-hidden rounded-xl">
      <div className="code-rail-head flex items-center justify-between gap-3 px-4 py-2 font-mono text-[11px] font-medium tracking-wide uppercase">
        <span className="truncate">{title}</span>
        {copyText && <CopyButton text={copyText} />}
      </div>
      <pre className="overflow-x-auto px-4 py-4 font-mono text-[12.5px] leading-[1.75]">
        <code>{children}</code>
      </pre>
    </div>
  );
}

// Inline syntax-color spans for the hand-authored examples below — not a
// real highlighter. Same fixed palette the gh-pages docs site hardcoded for
// its terminal/JSON blocks (that source hardcodes these hexes too, rather
// than theming them — code-rail is a fixed "terminal," not a themed
// surface, so this matches rather than fights it).
function tone(hex: string) {
  return function Tone({ children }: { children: ReactNode }) {
    return <span style={{ color: hex }}>{children}</span>;
  };
}

export const Comment = tone("#79817a");
export const Dim = tone("#79817a");
export const Fn = tone("#efa167");
export const Str = tone("#a8c7a0");
export const Ok = tone("#5cc98b");
export const Hot = tone("#ef7b66");
export const Kw = tone("#8fbbd9");
export const Bright = tone("#edefea");
