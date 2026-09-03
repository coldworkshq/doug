import { DougLogo } from "@/components/doug-logo";
import {
  COLDWORKS_URL,
  GITHUB_REPO_SLUG,
  GITHUB_REPO_URL,
} from "@/lib/links";

/** The brand footer shared by the landing page and /about — logo, tagline,
 *  parent company, license, repo link. /queue has its own content-specific
 *  footer (a scoring disclaimer, not brand chrome) and deliberately does not
 *  use this one.
 *
 *  THE ATTRIBUTION SITS WITH THE LICENSE, not with the tagline, and the row
 *  stays two groups rather than three. The left group is what Doug is; the
 *  right group is where Doug comes from and what you may do with it — who
 *  built it, under what license, from which repo, in that order. A third
 *  flex child under `justify-between` would park one item dead centre, which
 *  reads as a layout accident rather than a decision, and it is the wrap
 *  behaviour below `sm` that actually settles it: two groups wrap into two
 *  legible lines, three wrap into a ragged stack.
 *
 *  "A Coldworks product" is a claim of parentage, not of dependency. Doug
 *  ships independently, its records stay Doug-native, and nothing under
 *  `web/` imports from Coldworks — see docs/repos.md, which records the
 *  subtree-lift plan as superseded on exactly that ground.
 */
export function SiteFooter() {
  return (
    <footer className="flex flex-wrap items-baseline justify-between gap-2 border-t border-border py-8 font-mono text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <DougLogo size={16} /> doug · routes, never blocks
      </span>
      <span>
        <a
          href={COLDWORKS_URL}
          className="transition-colors hover:text-foreground"
        >
          A Coldworks product
        </a>{" "}
        · FSL-1.1-ALv2 ·{" "}
        <a
          href={GITHUB_REPO_URL}
          className="transition-colors hover:text-foreground"
        >
          {GITHUB_REPO_SLUG}
        </a>
      </span>
    </footer>
  );
}
