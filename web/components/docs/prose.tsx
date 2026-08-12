import type { ReactNode } from "react";

import { StatusBadge } from "./badge";
import type { DocsStatus } from "@/lib/docs-nav";

/** Kicker + H1 + status badge + optional dek, repeated at the top of every
 *  doc page. Kept as one component so the eleven pages can't drift on
 *  spacing or heading scale relative to each other. */
export function DocsPageHeader({
  kicker,
  title,
  status,
  children,
}: {
  kicker?: string;
  title: string;
  status?: DocsStatus;
  children?: ReactNode;
}) {
  return (
    <header className="mb-10">
      {kicker && (
        <p className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
          {kicker}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-heading text-3xl font-semibold tracking-tight sm:text-4xl">
          {title}
        </h1>
        {status && <StatusBadge status={status} />}
      </div>
      {children && (
        <div className="mt-4 max-w-2xl text-base leading-relaxed text-muted-foreground">
          {children}
        </div>
      )}
    </header>
  );
}

export function H2({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <h2
      id={id}
      className="font-heading mt-12 scroll-mt-28 text-xl font-semibold tracking-tight first:mt-0 sm:text-2xl"
    >
      {children}
    </h2>
  );
}

export function H3({ children }: { children: ReactNode }) {
  return (
    <h3 className="font-heading mt-8 text-base font-semibold">{children}</h3>
  );
}

export function P({ children }: { children: ReactNode }) {
  return (
    <p className="mt-4 text-[15px] leading-relaxed text-muted-foreground">
      {children}
    </p>
  );
}

export function UL({ children }: { children: ReactNode }) {
  return (
    <ul className="mt-4 list-disc space-y-2 pl-5 text-[15px] leading-relaxed text-muted-foreground marker:text-border">
      {children}
    </ul>
  );
}

export function IC({ children }: { children: ReactNode }) {
  return (
    <code className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-accent-foreground">
      {children}
    </code>
  );
}
