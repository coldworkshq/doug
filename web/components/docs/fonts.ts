import localFont from "next/font/local";

/** The docs' three faces, from the same woff2 files public/landing.html
 *  inlines (byte-identical subsets, extracted from the audit docs'
 *  stylesheet), so the docs and the door set type from one source. Loaded
 *  here rather than in the root layout, so only /docs preloads them.
 *  docs.module.css reads the three variables. */
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
});
