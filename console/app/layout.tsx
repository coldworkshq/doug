import type { Metadata } from "next";
import { Bricolage_Grotesque, Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
});

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  // The console's outcome column sets ✓ ○ ↩ — three glyphs the latin subset
  // does not carry — so each one falls back. Without this chain next/font
  // lists its own `local(Arial)` at size-adjust 134.59% immediately after the
  // face, and the glyph renders proportional and oversized inside a monospace
  // grid. web/app/layout.tsx carries the same fix for IBM Plex Mono and is
  // where it was found (doug#350, doug#361); the figures in that comment are
  // Plex Mono's and are not restated here for a face nobody has measured.
  // This file is not under the CSS lockstep, but the defect was shared,
  // because both apps set the same three glyphs in a monospace column.
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: "doug-console",
};

// No ThemeProvider: the console has no theme toggle anywhere in scope, so
// there is nothing to switch. :root (light) is the only palette applied —
// see app/globals.css for why .dark exists but is never triggered.
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${bricolage.variable} ${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
