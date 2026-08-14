import { SiteHeader } from "@/components/site-header";

// Streams immediately while a page's fetch is in flight, so a slow
// backend costs a skeleton instead of a blank tab. Kept to the shared nav
// shell — a fake queue here would be one more place inventing data.
export default function Loading() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl px-6">
        <section className="space-y-3 py-10">
          <div className="panel h-28 animate-pulse rounded-2xl" />
          <div className="panel h-28 animate-pulse rounded-2xl opacity-70" />
          <div className="panel h-28 animate-pulse rounded-2xl opacity-40" />
        </section>
      </main>
    </>
  );
}
