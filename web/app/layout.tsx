import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono, Instrument_Sans } from "next/font/google";
import { AuthKitProvider } from "@workos-inc/authkit-nextjs/components";
import "./globals.css";

import { ThemeProvider } from "@/components/theme-provider";

// The three Coldworks faces (ADR-0035): Archivo for display, Instrument Sans
// for body, IBM Plex Mono for numbers and code. The landing page inlines the
// same families, and /docs reads these variables rather than loading its own.
//
// Loaded from Google at build time, not from the landing's woff2 subsets: the
// subsets stop at Instrument Sans 500, and the app sets 600 and 700
// (font-semibold, <b>, <strong>), which a 500 file can only fake. Archivo and
// Instrument Sans are variable, so each is one file for every weight. Plex
// Mono is static, so its weights are listed.
const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
});

const instrumentSans = Instrument_Sans({
  variable: "--font-instrument-sans",
  subsets: ["latin"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  // A glyph the latin subset lacks — an arrow, a box-drawing rule, the ledger's
  // ○ — has to fall back to a monospace face. next/font otherwise lists its own
  // `local(Arial)` fallback at size-adjust 134.59% immediately after the face,
  // and the glyph renders proportional and oversized inside a monospace grid.
  // #350 hit this in the docs' code panels; measured here on 2026-09-16.
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: "Coldworks — use AI to need less AI",
  description:
    "Coldworks reviews your pull requests, remembers what your team decided, and turns the judgments it keeps repeating into checks you own. One product, free to start.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${instrumentSans.variable} ${plexMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col">
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem={false}
        >
          <AuthKitProvider>{children}</AuthKitProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
