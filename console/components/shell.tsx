import Link from "next/link";

import { DougLogo } from "@/components/doug-logo";

export interface ShellScope {
  tenant: string | null;
  repo: string | null;
}

export function Shell({
  scope,
  active,
  children,
}: {
  scope: ShellScope;
  active: "runs";
  children: React.ReactNode;
}) {
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
          <ScopeSwitch label="tenant" value={scope.tenant ?? "all"} />
          <ScopeSwitch label="repo" value={scope.repo ?? "all"} />
        </div>
        <HealthStrip />
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

function ScopeSwitch({ label, value }: { label: string; value: string }) {
  return (
    <span className="mono inline-flex items-center gap-[7px] rounded-[5px] border border-border bg-card px-[9px] py-[5px] text-xs">
      <span className="text-[10px] uppercase tracking-[.1em] text-muted-foreground">
        {label}
      </span>
      {value}
    </span>
  );
}

// Markup only — no data source exists yet. Tasks 1-5 shipped GET /v1/runs
// and GET /v1/runs/{verdict_id}; neither is a health/status feed. Showing
// "0 pending" for a metric nobody measured would be exactly the fabricated
// state this console exists to refuse, so every value is an em dash, never
// a number, and the pips carry no hue: there is no known state to assert,
// and hue is reserved for Doug's routing decision. Ghosted with the same
// "phase N" treatment the Repos/Evidence tabs use below for the same
// reason — unwired, not empty. Phase 2 drops real numbers into this exact
// layout; nothing here claims a fact we don't have.
function HealthStrip() {
  return (
    <div className="mono ml-auto flex cursor-not-allowed items-stretch overflow-hidden rounded-[5px] border border-border bg-card text-[11.5px] text-muted-foreground/50">
      <HealthCell label="running" />
      <HealthCell label="pending" />
      <HealthCell label="failed 24h" />
      <HealthCell label="clocks due" />
      <span className="flex items-center border-l border-border px-[9px] text-[9px] uppercase tracking-[.04em] text-muted-foreground/50">
        phase 2
      </span>
    </div>
  );
}

function HealthCell({ label }: { label: string }) {
  return (
    <span
      className="flex items-center gap-1.5 border-r border-border/70 px-[11px] py-[5px] last:border-r-0"
      aria-label={`${label}: not yet available`}
    >
      <span aria-hidden="true">—</span>
      <span className="text-[10.5px]">{label}</span>
    </span>
  );
}
