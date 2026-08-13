import Link from "next/link";

import { DougLogo } from "@/components/doug-logo";
import { ThemeToggle } from "@/components/theme-toggle";

const NAV_LINKS = [
  { href: "/docs", label: "Docs" },
  { href: "/scoreboard", label: "Scoreboard" },
  { href: "/queue", label: "Queue" },
] as const;

/** Floating site chrome for the public marketing surface (/, /docs/*).
 *
 *  Deliberately NOT used on /queue (forced-dark, its own minimal live-badge
 *  nav) or /dashboard (its own signed-in "forensic ledger" shell with a
 *  tenant/repo selector) — both have chrome that earned its own design and
 *  this component would be the wrong fit for either.
 *
 *  `position: sticky` + `top-4` rather than `fixed`: it still reserves its
 *  own space in flow (no content jumps under it, no scroll-lock JS), but
 *  the moment its natural position would land closer than 1rem to the
 *  viewport top, it holds there — which in practice means it reads as
 *  floating from the very first frame, not only once you scroll.
 *
 *  Sign in is the one filled, colored control in the bar — everything else
 *  (Docs/Queue/GitHub, the theme toggle) stays low-contrast text until
 *  hovered, so the one action that actually converts a stranger doesn't
 *  have to compete with three links that don't.
 *
 *  Changing this bar's padding/height changes how much of the page it can
 *  cover while floating — /docs's sticky sidebar and its H2 scroll-margin
 *  both clear it using --docs-content-offset (globals.css); re-check that
 *  value against this component's actual rendered height if either changes.
 */
export function SiteHeader({
  maxWidthClassName = "max-w-5xl",
}: {
  maxWidthClassName?: string;
}) {
  return (
    <header className={`sticky top-4 z-50 mx-auto w-full ${maxWidthClassName} px-6`}>
      <div className="flex items-center justify-between gap-3 rounded-full border border-border bg-background/75 py-2 pr-2.5 pl-4 shadow-lg shadow-black/[0.04] backdrop-blur-md dark:shadow-black/30">
        <Link
          href="/"
          className="font-heading flex shrink-0 items-center gap-2 text-base font-semibold tracking-tight"
        >
          <DougLogo size={20} /> doug
        </Link>

        <div className="flex items-center gap-1">
          <nav className="hidden items-center gap-0.5 font-mono text-xs text-muted-foreground sm:flex">
            {NAV_LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className="rounded-full px-3 py-1.5 transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                {l.label}
              </Link>
            ))}
            <a
              href="https://github.com/drewjst/doug"
              className="rounded-full px-3 py-1.5 whitespace-nowrap transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              GitHub
            </a>
          </nav>

          <span
            className="mx-1 hidden h-4 border-l border-border sm:block"
            aria-hidden="true"
          />

          <ThemeToggle />

          <Link
            href="/sign-in"
            className="ml-1 rounded-full bg-primary px-4 py-1.5 font-mono text-xs font-medium whitespace-nowrap text-primary-foreground transition-transform hover:-translate-y-0.5"
          >
            Sign in
          </Link>
        </div>
      </div>
    </header>
  );
}
