"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

// The one scope-switch affordance Phase 1 can honestly offer: clearing a
// filter. The URL is the filter state, so "switching" tenant/repo means
// linking to a URL — but a real option list would mean guessing at which
// tenants/repos exist, and this console has no endpoint that reads that.
// That's the same fabrication problem as the health strip. Clearing has
// no such gap: it always resolves to "no filter", a state that needs no
// invented data. Picking a *different* value happens where real values
// exist — Task 8's rows, each linking to `?repo=<that row's repo>`.
//
// Client Component: building "current URL minus this one param" needs the
// full query string (any other filters a page has set), which Shell's
// scope prop deliberately doesn't carry — useSearchParams reads it
// directly instead of widening Shell's contract for this alone.
export function ScopeSwitch({
  paramKey,
  label,
  value,
}: {
  paramKey: "tenant" | "repo";
  label: string;
  value: string | null;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // A bare `?tenant=` (present, blank) is a different string than absent
  // (null) but the same fact for this chip: there is nothing to clear. Not
  // treating it as unset used to render a live chip with a blank label
  // instead of the static "all" state — same empty-vs-absent confusion as
  // the tenant-id parsing this bug sits next to.
  if (value === null || value.trim() === "") {
    return <ScopeSwitchStatic label={label} value="all" />;
  }

  const params = new URLSearchParams(searchParams);
  params.delete(paramKey);
  const query = params.toString();

  return (
    <Link
      href={query ? `${pathname}?${query}` : pathname}
      aria-label={`Clear ${label} filter — currently ${value}`}
      className="mono inline-flex items-center gap-[7px] rounded-[5px] border border-border bg-card px-[9px] py-[5px] text-xs transition-colors hover:border-[var(--iridescent)]"
    >
      <span className="text-[10px] uppercase tracking-[.1em] text-muted-foreground">
        {label}
      </span>
      {value}
    </Link>
  );
}

// Pre-hydration (and the unset case, where there's nothing to clear):
// identical markup, minus the link. Also doubles as the Suspense fallback
// below — accurate rather than a placeholder, since nothing is clickable
// until the client component mounts anyway.
export function ScopeSwitchStatic({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <span className="mono inline-flex items-center gap-[7px] rounded-[5px] border border-border bg-card px-[9px] py-[5px] text-xs">
      <span className="text-[10px] uppercase tracking-[.1em] text-muted-foreground">
        {label}
      </span>
      {value}
    </span>
  );
}
