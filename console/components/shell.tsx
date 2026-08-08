import Link from "next/link";
import { Suspense } from "react";

import { DougLogo } from "@/components/doug-logo";
import { HealthStrip } from "@/components/health-strip";
import { ScopeSwitch, ScopeSwitchStatic } from "@/components/scope-switch";
import { getHealth } from "@/lib/api";

export interface ShellScope {
  tenant: string | null;
  repo: string | null;
}

export async function Shell({
  scope,
  active,
  children,
}: {
  scope: ShellScope;
  active: "runs" | "jobs";
  children: React.ReactNode;
}) {
  // Server-rendered per page load. No polling: the pages are already
  // force-dynamic so a refresh is a fresh read, and a polling client
  // component would need its own stale and error states — one more thing
  // that can render "clear" while being wrong.
  const health = await getHealth();

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-20 flex h-[52px] items-center gap-[18px] border-b border-border bg-background/[.86] px-5 backdrop-blur-[10px]">
        <span className="font-heading flex items-center gap-2 text-base font-bold tracking-tight">
          <DougLogo size={19} /> doug
          <span className="mono rounded-[3px] bg-accent px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[.12em] text-accent-foreground">
            console
          </span>
        </span>
        <div className="flex items-center gap-1.5">
          <Suspense fallback={<ScopeSwitchStatic label="tenant" value={scope.tenant ?? "all"} />}>
            <ScopeSwitch paramKey="tenant" label="tenant" value={scope.tenant} />
          </Suspense>
          <Suspense fallback={<ScopeSwitchStatic label="repo" value={scope.repo ?? "all"} />}>
            <ScopeSwitch paramKey="repo" label="repo" value={scope.repo} />
          </Suspense>
        </div>
        <HealthStrip health={health} />
      </header>
      <nav className="flex items-end gap-0.5 border-b border-border px-5">
        <Link
          href="/"
          aria-current={active === "runs" ? "page" : undefined}
          className="mono -mb-px border-b-2 border-transparent px-3 pt-2 pb-2 text-xs uppercase tracking-[.06em] text-muted-foreground aria-[current]:border-b-[var(--iridescent)] aria-[current]:font-semibold aria-[current]:text-foreground"
        >
          Runs
        </Link>
        <span className="mono -mb-px cursor-not-allowed px-3 pt-2 pb-2 text-xs uppercase tracking-[.06em] text-muted-foreground/50">
          Repos <span className="text-[9px]">phase 2</span>
        </span>
        <span className="mono -mb-px cursor-not-allowed px-3 pt-2 pb-2 text-xs uppercase tracking-[.06em] text-muted-foreground/50">
          Evidence <span className="text-[9px]">phase 3</span>
        </span>
      </nav>
      <main className="mx-auto max-w-[1440px] px-5">{children}</main>
    </div>
  );
}
