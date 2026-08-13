import Link from "next/link";

import { SiteHeader } from "@/components/site-header";
import { getScoreboard } from "@/lib/api";

function day(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

export default async function ScoreboardPage() {
  const { scoreboard, source } = await getScoreboard({ maxAgeMs: 30_000 });
  const live = source === "live";

  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl px-6 py-16">
        <p
          className="panel inline-flex items-center gap-2 rounded-full px-3 py-1 font-mono text-xs text-muted-foreground"
        >
          {live ? (
            <>
              <span className="size-1.5 rounded-full bg-sheen" /> live · {scoreboard.repo}
            </>
          ) : (
            <>
              <span className="size-1.5 rounded-full bg-muted-foreground" />{" "}
              sample data · the live scoreboard is a fetch away
            </>
          )}
        </p>
        <p className="font-mono mt-8 text-xs uppercase tracking-[0.2em] text-muted-foreground">
          Prospective
        </p>
        <h1 className="font-heading mt-2 max-w-xl text-4xl font-semibold tracking-tight md:text-5xl">
          {scoreboard.adjudicated} adjudicated.{" "}
          <span className="text-muted-foreground">{scoreboard.pending} pending.</span>
        </h1>
        <p className="mt-4 max-w-lg text-sm leading-relaxed text-muted-foreground">
          {scoreboard.label}. Replay of the last 90 days is a later surface and
          is not mixed into these numbers.
        </p>

        <dl className="panel mt-10 grid gap-6 rounded-2xl p-8 sm:grid-cols-2">
          <div>
            <dt className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Adjudicated
            </dt>
            <dd className="font-heading mt-2 text-5xl font-semibold">
              {scoreboard.adjudicated}
            </dd>
          </div>
          <div>
            <dt className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Pending
            </dt>
            <dd className="font-heading mt-2 text-5xl font-semibold">
              {scoreboard.pending}
            </dd>
          </div>
          <div>
            <dt className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              As of
            </dt>
            <dd className="mt-2 font-mono text-lg">{day(scoreboard.as_of)}</dd>
          </div>
          <div>
            <dt className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              First due
            </dt>
            <dd className="mt-2 font-mono text-lg">{day(scoreboard.first_due)}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Deep reads this cycle
            </dt>
            <dd className="mt-2 font-mono text-lg">
              {scoreboard.deep_reads === null
                ? "not recorded"
                : `${scoreboard.deep_reads}/${scoreboard.deep_read_cap}`}
            </dd>
          </div>
        </dl>

        <p className="mt-8 font-mono text-xs text-muted-foreground">
          Published miss rate: — · {scoreboard.label}
        </p>
        <p className="mt-6">
          <Link
            href="/queue"
            className="font-mono text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            The queue is a different surface →
          </Link>
        </p>
      </main>
    </>
  );
}
