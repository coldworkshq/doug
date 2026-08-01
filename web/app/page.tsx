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

// Exactly what doug/reader.py's frozen prompt puts in front of the model,
// and exactly what it withholds. Both lists are load-bearing claims — keep
// them in sync with the prompt, not with the pitch.
//
// Scoped to the *read* on purpose. Doug as a whole does see authorship:
// scoring.py has an agent-authored rule (weight 0.12) in the deterministic
// tier, pr_meta carries the author into the ledger, and the queue page
// prints it. Claiming Doug "never sees who wrote it" was false — and most
// false exactly when the reader is unavailable and the deterministic tier
// is doing the scoring.
const READS = ["the diff itself", "the PR title", "the files it touches"];

const NOT_TOLD = [
  "who wrote it",
  "human or agent",
  "when it was opened",
  "who approved it",
  "what happened next",
];

// The positioning sentence, decomposed into its three claims. They are not
// equally true yet, so each carries its own status: the reader is live, the
// outcome loop is designed and landing (docs/design/outcome-loop/), and the
// garden is gated on adjudicated data existing. Keep the statuses in sync
// with reality, not ambition — this section overclaims the day they drift.
const LAYERS = [
  {
    tag: "landing",
    title: "Learns what production did",
    body: "Every merge starts a clock. At 14 and 60 days the verdict is graded against what actually happened — reverted, or survived the window. The scoreboard starts at zero and says so.",
  },
  {
    tag: "accruing",
    title: "Remembers it",
    body: "Every verdict is a ledger row — dated, immutable, waiting to be graded. A repo running Doug for a year holds a calibrated risk record of itself that no point-in-time reviewer can replicate.",
  },
  {
    tag: "preview · no dates promised",
    title: "Tells your agents",
    body: "The graded history, served to coding agents before they type: “this migration shape reverted here 7 of 9 times — the two that survived used dual-write.” Ships when there is adjudicated data to serve, not before.",
  },
];

export default async function Home() {
  // The landing page never needs per-request freshness: 30s of staleness is
  // invisible here, and it means a link-spike hits the queue API a couple of
  // times a minute instead of once per visitor.
  const { queue, source } = await getQueue({ maxAgeMs: 30_000 });
  const { summary } = queue;
  const live = source === "live";

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
          {/* Same source-honesty rule as the queue page: this pill claimed
              "live" unconditionally, so an API outage showed a pulsing live
              dot over fixture numbers — a confident, false claim on the one
              page most likely to be shared. */}
          <p
            className="animate-rise glass inline-flex items-center gap-2 rounded-full px-3 py-1 font-mono text-xs text-muted-foreground"
            style={{ animationDelay: "0ms" }}
          >
            {live ? (
              <>
                <span className="size-1.5 rounded-full bg-sheen" /> the reader
                is live · scoring its own pull requests
              </>
            ) : (
              <>
                <span className="size-1.5 rounded-full bg-muted-foreground" />{" "}
                sample data · the live queue is a fetch away
              </>
            )}
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
            Doug reads the diff, scores it against what actually reverted in
            repos like yours, and routes the handful that need human eyes.
            Everything else clears. When it&rsquo;s wrong, it says so — in
            public.
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
            {live ? "Today’s queue" : "Sample queue"}
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
          {live ? "The open queue, pinned by risk" : "A sample queue, pinned by risk"}
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
            What the reader is given
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
          <p className="mt-8 font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
            What the reader is not told
          </p>
          <ul className="mt-5 flex flex-wrap gap-2">
            {NOT_TOLD.map((r) => (
              <li
                key={r}
                className="rounded-full border border-white/10 px-3.5 py-1.5 font-mono text-xs text-muted-foreground/70 line-through decoration-white/20"
              >
                {r}
              </li>
            ))}
          </ul>
          <p className="mt-6 max-w-sm text-sm leading-relaxed text-muted-foreground">
            The judgment about the code is made without knowing who wrote it.
            That claim is narrow on purpose: it covers the read, not the whole
            of Doug.
          </p>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-muted-foreground">
            Doug does see authorship elsewhere. The deterministic fallback —
            used when a read fails — scores a PR higher when a bot opened it,
            and the queue tells you who wrote each one, because you need that
            to route. What it never does is let the reader grade the code
            against the author&rsquo;s reputation.
          </p>
        </div>

        <div className="glass relative overflow-hidden rounded-2xl p-8">
          <div className="bg-iridescent absolute inset-x-0 top-0 h-px opacity-60" />
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
            What&rsquo;s actually measured
          </p>
          <p className="text-iridescent font-heading mt-4 text-6xl font-semibold">
            0.69
            <span className="ml-2 text-2xl text-muted-foreground">/ 0.67</span>
          </p>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            Ranking AUC on sentry and grafana, pre-registered before a single
            model call. The best deterministic baseline scored 0.59 and 0.52 —
            on grafana every metadata method we tried lands at or below random.
            Reading the diff is the first thing that survived a second repo.
          </p>
          <div className="mt-6 border-t border-white/5 pt-5">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Published miss rate
            </p>
            <p className="font-heading mt-2 text-3xl font-semibold text-muted-foreground">
              —
            </p>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              Not yet. That needs verdicts joined to outcomes in production,
              and Doug has been live for days, not months. The number lands
              here with a date next to it, good or bad.
            </p>
          </div>
        </div>
      </section>

      <section className="pb-16">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
          Others learn what reviewers say
        </p>
        <h2 className="font-heading mt-4 max-w-3xl text-3xl leading-tight font-semibold tracking-tight md:text-4xl">
          Doug learns what production did, remembers it, and tells your agents{" "}
          <span className="text-iridescent">before they type</span>.
        </h2>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {LAYERS.map((l) => (
            <div
              key={l.title}
              className="glass group rounded-2xl p-8 transition-transform hover:-translate-y-1"
            >
              <span className="glass rounded-full px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                {l.tag}
              </span>
              <h3 className="font-heading mt-4 text-xl font-semibold">
                {l.title}
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                {l.body}
              </p>
            </div>
          ))}
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
          {live
            ? `${summary.open} scored ${summary.open === 1 ? "PR" : "PRs"}, ${summary.flagged} worth your time, and the receipts behind every score.`
            : "A sample queue with the receipts behind every score — the live ledger is a fetch away."}
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
