import Link from "next/link";

import { DougLogo } from "@/components/doug-logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { GITHUB_REPO_URL } from "@/lib/links";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/scoreboard", label: "Scoreboard" },
  { href: "/queue", label: "Queue" },
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
 *  Order is deliberate: Dashboard first, then the two live public surfaces
 *  (Scoreboard, Queue), Docs next as reference material, GitHub after that as
 *  the escape hatch to source, About last.
 *
 *  DASHBOARD IS A PLAIN LINK, not a signed-in state. This bar renders on
 *  /docs/* and /about, which are static; reading the session here to choose
 *  between "Dashboard" and "Sign in" would make every one of those pages
 *  render per request, which is a real cost for one word. It is not a dead end
 *  for a signed-out visitor either — proxy.ts matches /dashboard/:path* and
 *  hands an unauthenticated request to AuthKit, which returns to /dashboard
 *  after sign-in. It is first because it is the only entry here addressed to
 *  someone who already has Doug, and because it being hard to find is the
 *  reason it was added: everything Doug can be told to do — the flag line and
 *  the PR comment — is set behind it, and until this link existed the only
 *  route back to that page from the marketing site was the URL bar.
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
                  key={l.href}
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
