import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";
import { GITHUB_REPO_URL } from "@/lib/links";

/** The door's own nav, in its order (public/landing.html): the three
 *  moments, the audit, the docs. Doug reviews is a real page; Memory and
 *  Guards are sections of the door until their workspace screens are the
 *  thing a stranger should see first. ADR-0034. */
const NAV_LINKS = [
  { href: "/doug", label: "Doug reviews" },
  { href: "/#moments", label: "Memory" },
  { href: "/#moments", label: "Guards" },
  { href: "/#audit", label: "The audit" },
  // The published miss rate is the trust instrument (Doug's third rule); it
  // stays one click from every public page, not only from the ledger.
  { href: "/scoreboard", label: "Scoreboard" },
  { href: "/docs", label: "Docs" },
] as const;

/** Floating site chrome for the public marketing surface (/, /docs/*,
 *  /scoreboard, /queue, /about).
 *
 *  Deliberately NOT used on /dashboard (its own signed-in "forensic ledger"
 *  shell with a tenant/repo selector) — that chrome earned its own design
 *  and this component would be the wrong fit.
 *
 *  `position: sticky` + `top-4` rather than `fixed`: it still reserves its
 *  own space in flow (no content jumps under it, no scroll-lock JS), but
 *  the moment its natural position would land closer than 1rem to the
 *  viewport top, it holds there — which in practice means it reads as
 *  floating from the very first frame, not only once you scroll.
 *
 *  Sign in is the one filled, colored control in the bar — everything else
 *  (Dashboard/Scoreboard/Queue/Docs/GitHub/About, the theme toggle) stays
 *  low-contrast text until hovered, so the one action that actually converts a
 *  stranger doesn't have to compete with six links that don't. Below `sm`
 *  those links live in a native <details> disclosure rather than vanishing.
 *
 *  THE BAR IS LIGHT IN BOTH THEMES, and `site-bar` is what makes it so — a
 *  token scope in globals.css, not a pile of `dark:` overrides here. It was
 *  `bg-background/75`, the page's own ground: in light that is #eef0f2 over
 *  #eef0f2, so nothing but the border separated the two, and in dark it was a
 *  dark pill floating over a dark page under a dark glow. Chrome that floats
 *  has to read as a separate plane, and light is the cheapest way to say so.
 *  Re-declaring the palette on this one element is also the only way the theme
 *  toggle follows: it is a client component this file cannot pass classes
 *  into, and it paints in --muted-foreground/--accent like everything else in
 *  the bar. globals.css carries the values and the ratios.
 *
 *  `text-foreground` ON THE BAR IS NOT REDUNDANT and is the one thing the
 *  token scope cannot do for itself. `body` sets `color: var(--foreground)`,
 *  which is substituted at the BODY — descendants inherit the resolved colour,
 *  not the variable — so re-declaring --foreground further down changes
 *  nothing an element merely inherits. Every other control in here names its
 *  own ink (`text-muted-foreground`, `text-primary-foreground`); the wordmark
 *  did not, and in dark mode it would have inherited the page's near-white ink
 *  onto a near-white bar and vanished. This line re-substitutes the token
 *  where the scope can reach it.
 *
 *  Order is the door's: Doug reviews, Memory, Guards, The audit, then the
 *  Scoreboard (the published miss rate, one click from everywhere), Docs; then
 *  GitHub as the escape hatch to source and About last. The Dashboard link
 *  that used to lead this bar is gone because Sign in now does its job: a
 *  session that already exists returns straight to /dashboard/overview, and
 *  reading the session here to choose a word would make every static page
 *  render per request.
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
      <div className="site-bar flex items-center justify-between text-foreground gap-3 rounded-full border border-border bg-background/90 py-2 pr-2.5 pl-4 shadow-lg shadow-black/[0.06] backdrop-blur-md dark:shadow-black/40">
        <Link
          href="/"
          className="font-heading flex shrink-0 items-center gap-2 text-base font-semibold tracking-tight"
        >
          Coldworks
        </Link>

        <div className="flex items-center gap-1">
          <nav className="hidden items-center gap-0.5 font-mono text-xs text-muted-foreground sm:flex">
            {NAV_LINKS.map((l) => (
              <Link
                key={l.label}
                href={l.href}
                className="rounded-full px-3 py-1.5 transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                {l.label}
              </Link>
            ))}
            <a
              href={GITHUB_REPO_URL}
              className="rounded-full px-3 py-1.5 whitespace-nowrap transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              GitHub
            </a>
            <Link
              href="/about"
              className="rounded-full px-3 py-1.5 transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              About
            </Link>
          </nav>

          {/* Native disclosure, not a client menu: works without JS, matches
              the dashboard's no-JS ethic, and is the only way Dashboard /
              Scoreboard / Queue / Docs exist below `sm` — the nav above is
              `hidden sm:flex`. */}
          <details className="relative sm:hidden">
            <summary className="cursor-pointer list-none rounded-full px-3 py-1.5 font-mono text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground [&::-webkit-details-marker]:hidden">
              Menu
            </summary>
            <nav
              aria-label="Site sections"
              className="absolute top-[calc(100%+0.5rem)] right-0 z-50 flex w-44 flex-col rounded-2xl border border-border bg-background/95 p-1.5 shadow-lg shadow-black/[0.06] backdrop-blur-md dark:shadow-black/40"
            >
              {NAV_LINKS.map((l) => (
                <Link
                  key={l.label}
                  href={l.href}
                  className="rounded-full px-3 py-1.5 font-mono text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                >
                  {l.label}
                </Link>
              ))}
              <a
                href={GITHUB_REPO_URL}
                className="rounded-full px-3 py-1.5 font-mono text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                GitHub
              </a>
              <Link
                href="/about"
                className="rounded-full px-3 py-1.5 font-mono text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                About
              </Link>
            </nav>
          </details>

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
