import localFont from "next/font/local";

/** The docs' three faces, the same subsets public/landing.html inlines as
 *  base64 (byte-identical, extracted from the audit docs' stylesheet), so
 *  the docs and the door set the same type. Same bytes, not one download: the
 *  door stays a self-contained document (ADR-0034), so a visitor who reads
 *  both fetches these files once more. Loaded here rather than in the root
 *  layout, so only /docs preloads them. docs.module.css reads the three
 *  variables. */
export const docsDisplay = localFont({
  src: [{ path: "./fonts/Archivo-800-900.woff2", weight: "800 900", style: "normal" }],
  variable: "--cw-font-display",
});

export const docsBody = localFont({
  src: [{ path: "./fonts/InstrumentSans-400-500.woff2", weight: "400 500", style: "normal" }],
  variable: "--cw-font-body",
});

export const docsMono = localFont({
  src: [
    { path: "./fonts/PlexMono-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/PlexMono-600.woff2", weight: "600", style: "normal" },
  ],
  variable: "--cw-font-mono",
  // No size-adjusted Arial fallback. The subset has no arrows or box
  // drawing (→, ─), and next/font's default puts local(Arial) before
  // ui-monospace and Menlo, so those glyphs rendered proportional and
  // oversized and broke the panels' one-cell grid.
  adjustFontFallback: false,
});
