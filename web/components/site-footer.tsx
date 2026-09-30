import { BrandMark } from "@/components/brand-mark";
import {
  COLDWORKS_URL,
  GITHUB_REPO_SLUG,
  GITHUB_REPO_URL,
} from "@/lib/links";

/** The brand footer shared by /reviews and /about — mark, tagline, the
 *  domain, license, repo link. /queue has its own content-specific
 *  footer (a scoring disclaimer, not brand chrome) and deliberately does not
 *  use this one.
 *
 *  THE ATTRIBUTION SITS WITH THE LICENSE, not with the tagline, and the row
 *  stays two groups rather than three. The left group is what this is; the
 *  right group is where it comes from and what you may do with it — whose
 *  site, under what license, from which repo, in that order. A third
 *  flex child under `justify-between` would park one item dead centre, which
 *  reads as a layout accident rather than a decision, and it is the wrap
 *  behaviour below `sm` that actually settles it: two groups wrap into two
 *  legible lines, three wrap into a ragged stack.
 *
 *  Coldworks is the only public name since the 2026-09-23 naming ruling; the
 *  reviewer is its Reviews capability, and "doug" survives here only as the
 *  repository's slug. The name is a claim of identity, not of code
 *  dependency: nothing under `web/` imports from the coldworks repository —
 *  see docs/repos.md, which records the subtree-lift plan as superseded on
 *  exactly that ground.
 */
export function SiteFooter() {
  return (
    <footer className="flex flex-wrap items-baseline justify-between gap-2 border-t border-border py-8 font-mono text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <BrandMark size={16} /> coldworks · routes, never blocks
      </span>
      <span>
        <a
          href={COLDWORKS_URL}
          className="transition-colors hover:text-foreground"
        >
          coldworks.dev
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
