import Link from "next/link";

import { CheckRunCard } from "@/components/landing/check-run-card";
import { LifecycleRail } from "@/components/landing/lifecycle-rail";
import { ScoreStrip } from "@/components/score-strip";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { getQueue, getScoreboard } from "@/lib/api";
import { GITHUB_REPO_URL } from "@/lib/links";

// The three rules, verbatim from the README. Not numbered on the page: they
// are commitments, not steps, and a 01/02/03 would claim an order that does
// not exist.
const RULES = [
  {
    title: "Route, never block",
    body: "Doug orders attention. It holds no merge hostage, gates no pipeline, and adds zero seconds to a cleared PR.",
  },
  {
    title: "Never writes code",
    body: "A reviewer that also writes is marking its own homework. Doug decides where eyes go — it never generates a fix.",
  },
  {
    title: "Will publish its miss rate",
    body: "Every escaped defect Doug cleared will be counted, dated, and published on the locked cadence. If the number is bad, you'll see it here first.",
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
    title: "Every merge starts a clock",
    body: "Every merge starts a clock. At 14 and 60 days the verdict is graded against what actually happened — reverted, or survived the window. The scoreboard starts at zero and says so.",
  },
  {
    tag: "accruing",
    title: "Remembers it",
    body: "Every verdict is a ledger row — dated, immutable, waiting to be graded. A repo running Doug for a year holds a calibrated risk record of itself that no point-in-time reviewer can replicate.",
  },
  {
    tag: "planned · no dates promised",
    title: "Tells your agents",
    body: "The graded history, served to coding agents before they type: “this migration shape reverted here 7 of 9 times — the two that survived used dual-write.” Ships when there is adjudicated data to serve, not before.",
  },
];

// The cost argument, row by row. Structural on purpose: no dollar figures,
// because ADR-0004 records that Doug's COGS scale with PR volume too when
// the reader is on — the honest claim is BOUNDED spend and ROUTED attention,
// not a skipped model call. `doug` cells that quote a live number are built
// in the component, where the queue is in scope.
const COST_ROWS: { what: string; everything: string; doug: string }[] = [
  {
    what: "Model spend per PR",
    everything:
      "A full agentic read of the branch, as large as the branch is. Run it twice, pay twice.",
    doug: "One read of the diff, capped at 100k characters at a fixed effort. The look-up passes that follow run a cheaper model.",
  },
  {
    what: "Where the spend shows",
    everything: "On a bill, later.",
    doug: "On the check run itself: “deep reads 143/200 this cycle.” The meter is the surface you already read.",
  },
  {
    what: "When it runs",
    everything: "When someone remembers to run it.",
    doug: "On every push, as a GitHub check. Nobody has to remember, and nobody can forget.",
  },
  {
    what: "The merge button",
    everything: "Whatever the tool decides that day.",
    doug: "Untouched. The check is neutral, every time, by design.",
  },
  {
    what: "When the read fails",
    everything: "You re-run it, or it ships unread.",
    doug: "The deterministic tier scores it without a model and the check says so. A downgrade is never silent.",
  },
  {
    what: "After the merge",
    everything: "Nothing. The comments were the product.",
    doug: "A 14- and 60-day clock, graded against this repository's own reverts, published on a date.",
  },
];

export default async function Home() {
  // The landing page never needs per-request freshness: 30s of staleness is
  // invisible here, and it means a link-spike hits the queue API a couple of
  // times a minute instead of once per visitor. Both fetches share the
  // showcase micro-cache with /queue and /scoreboard.
  const [{ queue, source }, { scoreboard }] = await Promise.all([
    getQueue({ maxAgeMs: 30_000 }),
    getScoreboard({ maxAgeMs: 30_000 }),
  ]);
  const { summary } = queue;
  const live = source === "live";

  // The hero shows the check run for the riskiest open PR — the one a human
  // is about to be asked for — or the top of the queue when nothing is
  // flagged, or nothing at all when the queue is empty.
  const byRisk = [...queue.items].sort((a, b) => b.verdict.score - a.verdict.score);
  const heroItem = byRisk.find((i) => i.verdict.band === "flagged") ?? byRisk[0] ?? null;

  const cleared = summary.open === 0 ? 0 : Math.round((summary.cleared / summary.open) * 100);

  return (
    <>
      <SiteHeader maxWidthClassName="max-w-6xl" />
      <main className="mx-auto w-full max-w-6xl px-6">
        {/* ── Hero ─────────────────────────────────────────────────────── */}
        <section className="grid gap-12 py-16 md:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] md:items-center md:py-24">
          <div>
            {/* Same source-honesty rule as the queue page: this pill claimed
                "live" unconditionally, so an API outage showed a pulsing live
                dot over fixture numbers — a confident, false claim on the one
                page most likely to be shared. */}
            <p
              className="animate-rise panel inline-flex items-center gap-2 rounded-full px-3 py-1 font-mono text-xs text-muted-foreground"
              style={{ animationDelay: "0ms" }}
            >
              {live ? (
                <>
                  <span className="size-1.5 rounded-full bg-sheen" /> the
                  reader is live · scoring its own pull requests
                </>
              ) : (
                <>
                  <span className="size-1.5 rounded-full bg-muted-foreground" />{" "}
                  sample data · the live queue is a fetch away
                </>
              )}
            </p>
            <h1
              className="animate-rise display-condensed font-heading mt-7 max-w-2xl text-6xl leading-[0.94] font-semibold tracking-[-0.03em] md:text-8xl"
              style={{ animationDelay: "80ms" }}
            >
              Most PRs <span className="text-iridescent">don&rsquo;t</span>{" "}
              need you.
            </h1>
            <p
              className="animate-rise mt-7 max-w-lg text-lg leading-relaxed text-muted-foreground"
              style={{ animationDelay: "160ms" }}
            >
              Doug reads every pull request once, routes the few that need a
              human, and clears the rest. Every merge starts a clock against
              this repository&rsquo;s own reverts. When Doug is wrong, it
              says so — in public.
            </p>
            <div
              className="animate-rise mt-9 flex flex-wrap items-center gap-3"
              style={{ animationDelay: "240ms" }}
            >
              <Link
                href="/sign-in"
                className="rounded-full bg-primary px-6 py-3 text-sm font-medium text-primary-foreground transition-transform hover:-translate-y-0.5"
              >
                Get started
              </Link>
              <Link
                href="/queue"
                className="panel rounded-full px-6 py-3 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                See the queue
              </Link>
              <span className="ml-1 font-mono text-xs text-muted-foreground">
                GitHub App · never blocks · FSL source
              </span>
            </div>
          </div>

          <div className="animate-rise" style={{ animationDelay: "320ms" }}>
            <CheckRunCard item={heroItem} scoreboard={scoreboard} live={live} />
          </div>
        </section>

        {/* ── The instrument: today's queue ───────────────────────────── */}
        <section className="hairline-grid rounded-2xl md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <dl className="grid grid-cols-2 gap-px bg-border md:grid-cols-2">
            {[
              ["open", summary.open, ""],
              ["need you", summary.flagged, "data-flag"],
              ["cleared", summary.cleared, "data-clear"],
              ["flag line", summary.threshold.toFixed(2), ""],
            ].map(([k, v, tone]) => (
              <div key={k} className="bg-card p-6">
                <dt className="font-mono text-[11px] tracking-wider text-muted-foreground uppercase">
                  {k}
                </dt>
                <dd className={`mono mt-2 text-4xl font-medium ${tone}`}>{v}</dd>
              </div>
            ))}
          </dl>
          <div className="p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-mono text-[11px] tracking-wider text-muted-foreground uppercase">
                {live ? "The open queue, pinned by risk" : "A sample queue, pinned by risk"}
              </p>
              <p className="font-mono text-xs text-muted-foreground">
                {cleared}% cleared without a human
              </p>
            </div>
            <div className="mt-4">
              <ScoreStrip
                points={queue.items.map((i) => ({
                  score: i.verdict.score,
                  band: i.verdict.band,
                }))}
                threshold={summary.threshold}
              />
            </div>
          </div>
        </section>

        {/* ── How it works ────────────────────────────────────────────── */}
        <section className="py-24">
          <p className="font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase">
            One pull request, start to finish
          </p>
          <h2 className="font-heading mt-4 max-w-2xl text-3xl leading-tight font-semibold tracking-tight md:text-5xl">
            Read once. Route. Then{" "}
            <span className="text-iridescent">wait and see</span>.
          </h2>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-muted-foreground">
            Everything to the left of the merge is what a reviewer does.
            Everything to the right is what no reviewer does: keep the
            verdict, and find out whether it was right.
          </p>
          <div className="mt-14">
            <LifecycleRail />
          </div>
        </section>

        {/* ── Why: the three rules ────────────────────────────────────── */}
        <section className="pb-24">
          <p className="font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase">
            Three rules, in writing
          </p>
          <h2 className="font-heading mt-4 max-w-3xl text-3xl leading-tight font-semibold tracking-tight md:text-5xl">
            Built so nobody wants to switch it off.
          </h2>
          <div className="hairline-grid mt-10 rounded-2xl md:grid-cols-3">
            {RULES.map((r) => (
              <div key={r.title} className="p-8">
                <h3 className="font-heading text-xl font-semibold">{r.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  {r.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* ── The cost of reviewing everything ────────────────────────── */}
        <section className="pb-24">
          <p className="font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase">
            The cost of reviewing everything
          </p>
          <h2 className="font-heading mt-4 max-w-3xl text-3xl leading-tight font-semibold tracking-tight md:text-5xl">
            A review on every PR costs{" "}
            <span className="text-iridescent">a review on every PR</span>.
          </h2>
          <p className="mt-5 max-w-2xl text-base leading-relaxed text-muted-foreground">
            Coding agents multiplied pull requests. Tools that answer with a
            full model review of each one —{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.9em] text-foreground">
              /code-review
            </code>{" "}
            on every branch, a bot on every diff — scale their spend with
            exactly that number, and still leave a person reading comments
            on all of them. Doug spends one bounded read per PR, then spends
            your attention only above your flag line.
          </p>

          <div className="panel mt-10 overflow-x-auto rounded-2xl">
            <table className="w-full min-w-[40rem] table-fixed text-sm [&_td]:align-top [&_th]:align-top [&_tbody_tr]:border-t [&_tbody_tr]:border-border">
              <colgroup>
                <col className="w-[20%]" />
                <col className="w-[36%]" />
                <col className="w-[44%]" />
              </colgroup>
              <thead>
                <tr className="font-mono text-[11px] tracking-wider text-muted-foreground uppercase">
                  <th className="px-5 py-3 text-left font-normal">
                    Per pull request
                  </th>
                  <th className="px-5 py-3 text-left font-normal">
                    A model review of everything
                  </th>
                  <th className="border-l border-border bg-background/60 px-5 py-3 text-left font-normal text-foreground">
                    Doug
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th className="px-5 py-4 text-left font-medium">What a human reads</th>
                  <td className="px-5 py-4 text-muted-foreground">
                    The comments, on 100% of PRs.
                  </td>
                  <td className="border-l border-border bg-background/60 px-5 py-4">
                    The PRs above your flag line.{" "}
                    {live ? "On this repository today" : "In the sample queue"}:{" "}
                    <span className="mono data-flag">{summary.flagged}</span> of{" "}
                    <span className="mono">{summary.open}</span>.
                  </td>
                </tr>
                {COST_ROWS.map((r) => (
                  <tr key={r.what}>
                    <th className="px-5 py-4 text-left font-medium">{r.what}</th>
                    <td className="px-5 py-4 text-muted-foreground">{r.everything}</td>
                    <td className="border-l border-border bg-background/60 px-5 py-4">{r.doug}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 max-w-2xl font-mono text-xs leading-relaxed text-muted-foreground">
            Doug is not model-free. With the reader on, every PR costs a read;
            the deterministic tier is what runs when it is off or fails. The
            saving is bounded spend and routed attention, not a skipped
            model call.
          </p>
        </section>

        {/* ── What the reader sees / what is measured ─────────────────── */}
        <section className="hairline-grid rounded-2xl md:grid-cols-2">
          <div className="p-8 md:p-10">
            <p className="font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase">
              What the reader is given
            </p>
            <ul className="mt-5 flex flex-wrap gap-2">
              {READS.map((r) => (
                <li
                  key={r}
                  className="rounded-full border border-border bg-background px-3.5 py-1.5 font-mono text-xs"
                >
                  {r}
                </li>
              ))}
            </ul>
            <p className="mt-8 font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase">
              What the reader is not told
            </p>
            <ul className="mt-5 flex flex-wrap gap-2">
              {NOT_TOLD.map((r) => (
                <li
                  key={r}
                  className="rounded-full border border-dashed border-border px-3.5 py-1.5 font-mono text-xs text-muted-foreground/70 line-through decoration-muted-foreground/30"
                >
                  {r}
                </li>
              ))}
            </ul>
            <p className="mt-8 max-w-sm text-sm leading-relaxed text-muted-foreground">
              The judgment about the code is made without knowing who wrote
              it. That claim is narrow on purpose: it covers the read, not
              the whole of Doug.
            </p>
            <p className="mt-4 max-w-sm text-sm leading-relaxed text-muted-foreground">
              Doug does see authorship elsewhere. The deterministic fallback —
              used when a read fails — scores a PR higher when a bot opened
              it, and the queue tells you who wrote each one, because you
              need that to route. What it never does is let the reader grade
              the code against the author&rsquo;s reputation.
            </p>
          </div>

          <div className="relative overflow-hidden p-8 md:p-10">
            <div className="bg-iridescent absolute inset-x-0 top-0 h-px opacity-60" />
            <p className="font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase">
              What&rsquo;s actually measured
            </p>
            <p className="text-iridescent font-heading mt-4 text-6xl font-semibold">
              0.69
              <span className="ml-2 text-2xl text-muted-foreground">
                / 0.67
              </span>
            </p>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Ranking AUC on sentry and grafana, pre-registered before a
              single model call. The best deterministic baseline scored 0.59
              and 0.52 — on grafana every metadata method we tried lands at
              or below random. Reading the diff is the first thing that
              survived a second repo.
            </p>
            <p className="mt-3 text-sm leading-relaxed text-foreground">
              That&rsquo;s the 30,000-character probe reader, not the one
              running on your PRs — the shipped reader hasn&rsquo;t been
              measured by it.
            </p>
            <div className="mt-6 border-t border-border pt-5">
              <p className="font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase">
                Published miss rate
              </p>
              <p className="font-heading mt-2 text-3xl font-semibold text-muted-foreground">
                —
              </p>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                Not yet. The live counters — adjudicated, pending, first due —
                sit on the{" "}
                <Link
                  href="/scoreboard"
                  className="underline underline-offset-4 hover:text-foreground"
                >
                  scoreboard
                </Link>
                . The number lands here with a date next to it, good or bad.
              </p>
            </div>
          </div>
        </section>

        {/* ── Memory: what accrues ────────────────────────────────────── */}
        <section className="py-24">
          <p className="font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase">
            Others learn what reviewers say
          </p>
          <h2 className="font-heading mt-4 max-w-3xl text-3xl leading-tight font-semibold tracking-tight md:text-5xl">
            Doug grades what production did, remembers it, and will tell your
            agents <span className="text-iridescent">before they type</span>.
          </h2>
          <div className="hairline-grid mt-10 rounded-2xl md:grid-cols-3">
            {LAYERS.map((l) => (
              <div key={l.title} className="p-8">
                <span className="rounded-full border border-border px-2.5 py-1 font-mono text-[11px] tracking-wider text-muted-foreground uppercase">
                  {l.tag}
                </span>
                <h3 className="font-heading mt-5 text-xl font-semibold">
                  {l.title}
                </h3>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  {l.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* ── Close ───────────────────────────────────────────────────── */}
        <section className="panel relative mb-16 overflow-hidden rounded-3xl p-10 text-center md:p-16">
          <div className="bg-iridescent absolute inset-x-0 top-0 h-px opacity-70" />
          <div
            className="pointer-events-none absolute inset-0 opacity-20"
            style={{
              background:
                "radial-gradient(40rem 16rem at 50% 120%, var(--ring), transparent 70%)",
            }}
          />
          <h2 className="display-condensed font-heading mx-auto max-w-2xl text-4xl font-semibold tracking-tight md:text-6xl">
            Watch the queue <span className="text-iridescent">thin out</span>.
          </h2>
          <p className="mx-auto mt-5 max-w-md text-muted-foreground">
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
              href={GITHUB_REPO_URL}
              className="panel rounded-full px-6 py-3 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              Star on GitHub
            </a>
          </div>
        </section>

        <SiteFooter />
      </main>
    </>
  );
}
