import Link from "next/link";

import { DougLogo } from "@/components/doug-logo";
import { ScoreStrip } from "@/components/score-strip";
import { getQueue } from "@/lib/api";

const RULES = [
  {
    n: "01",
    title: "Route, never block",
    body: "Doug orders attention. It holds no merge hostage, gates no pipeline, and adds zero seconds to a cleared PR.",
  },
  {
    n: "02",
    title: "Never writes code",
    body: "A reviewer that also writes is marking its own homework. Doug decides where eyes go — it never generates a fix.",
  },
  {
    n: "03",
    title: "Publishes its miss rate",
    body: "Every escaped defect Doug cleared is counted, dated, and published. If the number is bad, you'll see it here first.",
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
      <nav className="flex items-center justify-between py-6">
        <span className="font-heading flex items-center gap-2 text-lg font-semibold tracking-tight">
          <DougLogo /> doug
        </span>
        <span className="glass flex items-center gap-1 rounded-full px-1.5 py-1.5 font-mono text-xs">
          <Link
            href="/queue"
            className="rounded-full px-3 py-1 transition-colors hover:bg-white/10"
          >
            Queue
          </Link>
          <a
            href="https://github.com/drewjst/doug"
            className="rounded-full px-3 py-1 transition-colors hover:bg-white/10"
          >
            GitHub
          </a>
        </span>
      </nav>

      <section className="grid gap-10 py-20 md:grid-cols-[1fr_auto] md:py-24">
        <div>
          <p
            className="animate-rise glass inline-flex items-center gap-2 rounded-full px-3 py-1 font-mono text-xs text-muted-foreground"
            style={{ animationDelay: "0ms" }}
          >
            <span className="size-1.5 rounded-full bg-sheen" /> pre-build · the
            backtest comes first
          </p>
          <h1
            className="animate-rise font-heading mt-6 max-w-xl text-5xl leading-[1.02] font-semibold tracking-tight md:text-7xl"
            style={{ animationDelay: "80ms" }}
          >
            Most PRs <span className="text-iridescent">don&rsquo;t</span> need
            you.
          </h1>
          <p
            className="animate-rise mt-6 max-w-md text-lg leading-relaxed text-muted-foreground"
            style={{ animationDelay: "160ms" }}
          >
            Doug reads the metadata, scores the risk, and routes the handful
            that need human eyes. Everything else clears. When it&rsquo;s
            wrong, it says so — in public.
          </p>
          <div
            className="animate-rise mt-10 flex flex-wrap gap-3"
            style={{ animationDelay: "240ms" }}
          >
            <Link
              href="/queue"
              className="rounded-full bg-primary px-6 py-3 text-sm font-medium text-primary-foreground transition-transform hover:-translate-y-0.5"
            >
              See the queue
            </Link>
            <a
              href="https://github.com/drewjst/doug"
              className="glass rounded-full px-6 py-3 text-sm font-medium transition-colors hover:bg-white/10"
            >
              Read the thesis →
            </a>
          </div>
        </div>

        <div
          className="animate-rise glass relative self-end overflow-hidden rounded-2xl p-6 md:w-64"
          style={{ animationDelay: "320ms" }}
        >
          <div className="bg-iridescent absolute inset-x-0 top-0 h-px opacity-60" />
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Today&rsquo;s queue
          </p>
          <dl className="mt-4 space-y-3 font-mono">
            <div className="flex items-baseline justify-between">
              <dt className="text-xs text-muted-foreground">open</dt>
              <dd className="text-3xl font-medium">{summary.open}</dd>
            </div>
            <div className="flex items-baseline justify-between">
              <dt className="text-xs text-muted-foreground">need you</dt>
              <dd className="text-3xl font-medium text-flag">
                {summary.flagged}
              </dd>
            </div>
            <div className="flex items-baseline justify-between">
              <dt className="text-xs text-muted-foreground">cleared</dt>
              <dd className="text-3xl font-medium text-clear">
                {summary.cleared}
              </dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="glass rounded-2xl p-8">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
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

      <section className="grid gap-4 py-16 md:grid-cols-3">
        {RULES.map((r) => (
          <div
            key={r.n}
            className="glass group rounded-2xl p-8 transition-transform hover:-translate-y-1"
          >
            <span className="text-iridescent font-mono text-sm">{r.n}</span>
            <h2 className="font-heading mt-3 text-xl font-semibold">
              {r.title}
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              {r.body}
            </p>
          </div>
        ))}
      </section>

      <section className="grid gap-10 pb-16 md:grid-cols-2">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
            What it reads
          </p>
          <ul className="mt-5 flex flex-wrap gap-2">
            {READS.map((r) => (
              <li
                key={r}
                className="glass rounded-full px-3.5 py-1.5 font-mono text-xs transition-colors hover:bg-white/10"
              >
                {r}
              </li>
            ))}
          </ul>
          <p className="mt-6 max-w-sm text-sm leading-relaxed text-muted-foreground">
            Metadata only. No model reads a diff unless the score says it
            should — that&rsquo;s the routing economics that make review free
            for the 90% that don&rsquo;t need it.
          </p>
        </div>

        <div className="glass relative overflow-hidden rounded-2xl p-8">
          <div className="bg-iridescent absolute inset-x-0 top-0 h-px opacity-60" />
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Published miss rate
          </p>
          <p className="text-iridescent font-heading mt-4 text-7xl font-semibold">
            —
          </p>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
            No production data yet. The number goes here, good or bad, with a
            date next to it. That&rsquo;s the product.
          </p>
        </div>
      </section>

      <section className="glass relative mb-16 overflow-hidden rounded-3xl p-10 text-center md:p-16">
        <div className="bg-iridescent absolute inset-x-0 top-0 h-px opacity-70" />
        <div
          className="pointer-events-none absolute inset-0 opacity-20"
          style={{
            background:
              "radial-gradient(40rem 16rem at 50% 120%, oklch(0.7 0.12 195 / 60%), transparent 70%)",
          }}
        />
        <h2 className="font-heading mx-auto max-w-lg text-3xl font-semibold tracking-tight md:text-4xl">
          Watch the queue <span className="text-iridescent">thin out</span>.
        </h2>
        <p className="mx-auto mt-4 max-w-md text-muted-foreground">
          The demo queue is live now — twelve PRs, two worth your time, and
          the receipts for every score.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <Link
            href="/queue"
            className="rounded-full bg-primary px-6 py-3 text-sm font-medium text-primary-foreground transition-transform hover:-translate-y-0.5"
          >
            Open the queue
          </Link>
          <a
            href="https://github.com/drewjst/doug"
            className="glass rounded-full px-6 py-3 text-sm font-medium transition-colors hover:bg-white/10"
          >
            Star on GitHub
          </a>
        </div>
      </section>

      <footer className="flex flex-wrap items-baseline justify-between gap-2 border-t border-white/5 py-8 font-mono text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <DougLogo size={16} /> doug · routes, never blocks
        </span>
        <span>
          FSL-1.1-ALv2 ·{" "}
          <a
            href="https://github.com/drewjst/doug"
            className="transition-colors hover:text-foreground"
          >
            drewjst/doug
          </a>
        </span>
      </footer>
    </main>
  );
}
