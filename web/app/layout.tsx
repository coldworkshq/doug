import type { Metadata } from "next";
import { Bricolage_Grotesque, Geist, Geist_Mono } from "next/font/google";
import { AuthKitProvider } from "@workos-inc/authkit-nextjs/components";
import "./globals.css";

import { ThemeProvider } from "@/components/theme-provider";

// The width and optical-size axes are loaded on purpose: the landing hero
// sets its headline at wdth 85 (globals.css `.display-condensed`), which is
// a cut of this face nothing else on the site uses. Without the axes the
// declaration is inert and the headline silently renders at the default
// width — so if the hero ever looks like every other Bricolage site, check
// here first.
const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
  axes: ["opsz", "wdth"],
});

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Doug — most pull requests don't need you",
  description:
    "Risk-routed code review. Doug reads the diff, routes the handful that need human eyes, and will publish its miss rate.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${bricolage.variable} ${geistSans.variable} ${geistMono.variable} h-full antialiased`}
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
