import { DougLogo } from "@/components/doug-logo";

// Streams immediately while a page's queue fetch is in flight, so a slow
// backend costs a skeleton instead of a blank tab. Kept to the shared nav
// shell — a fake queue here would be one more place inventing data.
export default function Loading() {
  return (
    <main className="mx-auto w-full max-w-5xl px-6">
      <nav className="flex items-center justify-between py-6">
        <span className="font-heading flex items-center gap-2 text-lg font-semibold tracking-tight">
          <DougLogo /> doug
        </span>
        <span className="glass flex items-center gap-2 rounded-full px-3 py-1.5 font-mono text-xs text-muted-foreground">
          <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
          fetching the queue…
        </span>
      </nav>
      <section className="space-y-3 py-10">
        <div className="glass h-28 animate-pulse rounded-2xl" />
        <div className="glass h-28 animate-pulse rounded-2xl opacity-70" />
        <div className="glass h-28 animate-pulse rounded-2xl opacity-40" />
      </section>
    </main>
  );
}
