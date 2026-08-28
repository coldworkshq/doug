/** One pull request, start to finish: the six stations a PR passes through
 *  under Doug, drawn as a rail with the clock on its right half.
 *
 *  This is the one place the landing page numbers anything, and it does so
 *  because the content IS a sequence: nothing here can happen out of order.
 *  The rail's right half carries day marks because that half is literally
 *  time — the 14- and 60-day windows the outcome loop grades against.
 *
 *  Copy is held to what is live. The read and the routing are shipped; the
 *  clock starts at merge and grades at the windows (outcome-loop lane);
 *  the miss rate publishes on its date and has not yet. Nothing here says
 *  "learned", "caught", "prevented", or "safe" (experience.md copy rules). */

const STATIONS = [
  {
    mark: "open",
    title: "A PR opens",
    body: "Or a push lands. The GitHub App takes the webhook and queues one job. Nothing else in your pipeline changes.",
  },
  {
    mark: "read",
    title: "Doug reads the diff",
    body: "Title, files, patch — capped at 100k characters in a fixed order, and the check says when the cut fell short. No author, no dates.",
  },
  {
    mark: "route",
    title: "Needs you, or cleared",
    body: "Scored against the flag line you set for that repository. One neutral check, one sticky comment. Never a red X.",
  },
  {
    mark: "d0",
    title: "Merge starts the clock",
    body: "The verdict becomes a dated row that nobody can edit — threshold, findings, and what the reader was shown, pinned.",
  },
  {
    mark: "d14 · d60",
    title: "Graded against production",
    body: "At each window the row is adjudicated: reverted, or survived. The scoreboard counts it either way.",
  },
  {
    mark: "publish",
    title: "The number goes out",
    body: "The miss rate publishes on its pre-committed date with its N, whatever it says. Until then it renders as a dash.",
  },
] as const;

export function LifecycleRail() {
  return (
    <ol className="relative grid gap-x-3 gap-y-8 md:grid-cols-6">
      {/* The rail. Solid through routing; from the merge it is the clock,
          and draws in on load. Desktop only — below md the list is vertical
          and each station carries its own tick. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-[7px] right-0 left-0 hidden h-px md:block"
      >
        <div className="absolute inset-y-0 left-0 w-1/2 bg-border" />
        <div className="animate-draw absolute inset-y-0 left-1/2 w-1/2 bg-[var(--iridescent)]" />
      </div>
      {STATIONS.map((s, i) => {
        const clock = i >= 3;
        return (
          <li key={s.mark} className="relative flex gap-3 md:block">
            <span
              aria-hidden="true"
              className={`relative z-10 mt-[3px] block size-2.5 shrink-0 rounded-full border-2 bg-card md:mt-0 ${
                clock ? "border-[var(--iridescent)]" : "border-muted-foreground"
              }`}
            />
            <div className="min-w-0 md:mt-4">
              <p
                className={`font-mono text-[11px] tracking-wider uppercase ${
                  clock ? "text-[var(--iridescent)]" : "text-muted-foreground"
                }`}
              >
                {s.mark}
              </p>
              <h3 className="font-heading mt-1.5 text-base leading-snug font-semibold">
                {s.title}
              </h3>
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                {s.body}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
