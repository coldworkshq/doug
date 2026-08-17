import { DougLogo } from "@/components/doug-logo";
import { GITHUB_REPO_SLUG, GITHUB_REPO_URL } from "@/lib/links";

/** The brand footer shared by the landing page and /about — logo, tagline,
 *  license, repo link. /queue has its own content-specific footer (a
 *  scoring disclaimer, not brand chrome) and deliberately does not use
 *  this one. */
export function SiteFooter() {
  return (
    <footer className="flex flex-wrap items-baseline justify-between gap-2 border-t border-border py-8 font-mono text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <DougLogo size={16} /> doug · routes, never blocks
      </span>
      <span>
        FSL-1.1-ALv2 ·{" "}
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
