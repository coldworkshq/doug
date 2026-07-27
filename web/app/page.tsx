import Link from "next/link";

import { ScoreStrip } from "@/components/score-strip";
import { getQueue } from "@/lib/api";

const RULES = [
  {
    n: "01",
    title: "Route, never block",
    body: "Magpie orders attention. It holds no merge hostage, gates no pipeline, and adds zero seconds to a cleared PR.",
  },
  {
    n: "02",
    title: "Never writes code",
    body: "A reviewer that also writes is marking its own homework. Magpie decides where eyes go — it never generates a fix.",
  },
  {
    n: "03",
    title: "Publishes its miss rate",
    body: "Every escaped defect Magpie cleared is counted, dated, and published. If the number is bad, you'll see it here first.",
  },
];

const READS = [
  "paths touched",
  "diff shape",
  "lockfiles & manifests",
  "migrations",
  "approval latency",
  "authorship — human or agent",
  "module recency",
];

export default async function Home() {
  const { queue } = await getQueue();
  const { summary } = queue;

  return (
    <main className="mx-auto w-full max-w-5xl px-6">
      <nav className="flex items-baseline justify-between border-b py-5">
        <span className="font-mono text-sm font-semibold tracking-tight">
          <span className="text-sheen">✦</span> magpie
        </span>
        <span className="flex gap-6 font-mono text-xs uppercase tracking-widest">
          <Link href="/queue" className="hover:text-sheen">
            Queue
          </Link>
          <a
            href="https://github.com/drewjst/magpie"
            className="hover:text-sheen"
          >
            GitHub
          </a>
        </span>
      </nav>

      <section className="grid gap-10 border-b py-20 md:grid-cols-[1fr_auto]">
        <div>
          <p
            className="animate-rise font-mono text-xs uppercase tracking-[0.25em] text-muted-foreground"
            style={{ animationDelay: "0ms" }}
          >
            Field notes on code review · No. 001
          </p>
          <h1
            className="animate-rise mt-6 max-w-xl text-5xl leading-[1.05] font-medium tracking-tight md:text-6xl"
            style={{ animationDelay: "80ms" }}
          >
            Most pull requests <em className="text-sheen">don&rsquo;t</em> need
            you.
          </h1>
          <p
            className="animate-rise mt-6 max-w-md text-lg leading-relaxed text-muted-foreground"
            style={{ animationDelay: "160ms" }}
          >
            Magpie reads the metadata, scores the risk, and routes the handful
            that need human eyes. Everything else clears. When it&rsquo;s
            wrong, it says so — in public.
          </p>
          <div
            className="animate-rise mt-10 flex gap-4"
            style={{ animationDelay: "240ms" }}
          >
            <Link
              href="/queue"
              className="bg-primary px-5 py-2.5 font-mono text-sm text-primary-foreground transition-colors hover:bg-sheen"
            >
              See the queue
            </Link>
            <a
              href="https://github.com/drewjst/magpie"
              className="border px-5 py-2.5 font-mono text-sm transition-colors hover:border-sheen hover:text-sheen"
            >
              Read the thesis →
            </a>
          </div>
        </div>

        <div
          className="animate-rise self-end border p-6 md:w-64"
          style={{ animationDelay: "320ms" }}
        >
          <p className="font-mono text-xs uppercase tracking-[0.25em] text-muted-foreground">
            Today&rsquo;s ledger
          </p>
          <dl className="mt-4 space-y-3 font-mono">
            <div className="flex items-baseline justify-between">
              <dt className="text-xs text-muted-foreground">open</dt>
              <dd className="text-3xl">{summary.open}</dd>
            </div>
            <div className="flex items-baseline justify-between">
              <dt className="text-xs text-muted-foreground">need you</dt>
              <dd className="text-3xl text-flag">{summary.flagged}</dd>
            </div>
            <div className="flex items-baseline justify-between">
              <dt className="text-xs text-muted-foreground">cleared</dt>
              <dd className="text-3xl text-clear">{summary.cleared}</dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="border-b py-14">
        <p className="font-mono text-xs uppercase tracking-[0.25em] text-muted-foreground">
          The open queue, pinned by risk
        </p>
        <div className="mt-6">
          <ScoreStrip
            points={queue.items.map((i) => ({
              score: i.verdict.score,
              band: i.verdict.band,
            }))}
            threshold={summary.threshold}
          />
        </div>
      </section>

      <section className="grid gap-px border-b bg-border py-0 md:grid-cols-3">
        {RULES.map((r) => (
          <div
            key={r.n}
            className="group bg-background p-8 transition-colors hover:bg-card"
          >
            <p className="font-mono text-xs text-muted-foreground">{r.n}</p>
            <h2 className="mt-3 text-xl font-medium group-hover:text-sheen">
              {r.title}
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              {r.body}
            </p>
          </div>
        ))}
      </section>

      <section className="grid gap-10 border-b py-14 md:grid-cols-2">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.25em] text-muted-foreground">
            What it reads
          </p>
          <ul className="mt-5 space-y-2 font-mono text-sm">
            {READS.map((r) => (
              <li key={r} className="flex items-baseline gap-3">
                <span className="text-sheen">✦</span> {r}
              </li>
            ))}
          </ul>
          <p className="mt-5 max-w-sm text-sm leading-relaxed text-muted-foreground">
            Metadata only. No model reads a diff unless the score says it
            should — that&rsquo;s the routing economics that make review free
            for the 90% that don&rsquo;t need it.
          </p>
        </div>

        <div className="border border-foreground p-8">
          <p className="font-mono text-xs uppercase tracking-[0.25em] text-muted-foreground">
            Specimen — miss rate
          </p>
          <p className="mt-6 font-mono text-7xl text-muted-foreground">—</p>
          <p className="mt-6 text-sm leading-relaxed text-muted-foreground">
            No production data yet. The number goes here, good or bad, with a
            date next to it. That&rsquo;s the product.
          </p>
        </div>
      </section>

      <footer className="flex flex-wrap items-baseline justify-between gap-2 py-8 font-mono text-xs text-muted-foreground">
        <span>
          <span className="text-sheen">✦</span> magpie · routes, never blocks
        </span>
        <span>
          FSL-1.1-ALv2 ·{" "}
          <a href="https://github.com/drewjst/magpie" className="hover:text-sheen">
            drewjst/magpie
          </a>
        </span>
      </footer>
    </main>
  );
}
