import Link from "next/link";

import { ScoreStrip } from "@/components/score-strip";
import { Badge } from "@/components/ui/badge";
import { applyThreshold, getQueue } from "@/lib/api";

const PRESETS = [0.5, 0.62, 0.8];

function latency(s: number | null): string {
  if (s === null) return "unapproved";
  if (s < 3600) return `approved in ${Math.round(s / 60)}m`;
  return `approved in ${Math.round(s / 3600)}h`;
}

export default async function QueuePage({
  searchParams,
}: {
  searchParams: Promise<{ threshold?: string }>;
}) {
  const params = await searchParams;
  const { queue: raw, source } = await getQueue();
  const parsed = Number(params.threshold);
  const threshold =
    Number.isFinite(parsed) && parsed > 0 && parsed < 1
      ? parsed
      : raw.summary.threshold;
  const queue = applyThreshold(raw, threshold);

  return (
    <main className="mx-auto w-full max-w-5xl px-6">
      <nav className="flex items-baseline justify-between border-b py-5">
        <Link
          href="/"
          className="font-mono text-sm font-semibold tracking-tight"
        >
          <span className="text-sheen">✦</span> magpie
        </Link>
        <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          {source === "live" ? "live api" : "bundled fixture"}
        </span>
      </nav>

      <section className="border-b py-10">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.25em] text-muted-foreground">
              Review queue
            </p>
            <h1 className="mt-2 text-4xl font-medium tracking-tight">
              {queue.summary.open} open.{" "}
              <span className="text-flag">{queue.summary.flagged} need you.</span>
            </h1>
          </div>
          <div className="font-mono text-xs">
            <span className="mr-3 uppercase tracking-widest text-muted-foreground">
              threshold
            </span>
            {PRESETS.map((t) => (
              <Link
                key={t}
                href={`/queue?threshold=${t}`}
                className={
                  "mr-2 border px-2 py-1 transition-colors hover:border-sheen hover:text-sheen " +
                  (t === threshold ? "border-sheen text-sheen" : "")
                }
              >
                {t.toFixed(2)}
              </Link>
            ))}
          </div>
        </div>
        <div className="mt-8">
          <ScoreStrip
            points={queue.items.map((i) => ({
              score: i.verdict.score,
              band: i.verdict.band,
            }))}
            threshold={threshold}
          />
        </div>
      </section>

      <section className="divide-y">
        {queue.items.map(({ pr, verdict }) => (
          <article key={pr.number} className="grid gap-3 py-6 md:grid-cols-[5rem_1fr_auto]">
            <p
              className={
                "font-mono text-2xl " +
                (verdict.band === "flagged" ? "text-flag" : "text-clear")
              }
            >
              {verdict.score.toFixed(2)}
            </p>
            <div>
              <h2 className="text-lg font-medium">
                <span className="mr-2 font-mono text-sm text-muted-foreground">
                  #{pr.number}
                </span>
                {pr.title}
              </h2>
              <p className="mt-1 font-mono text-xs text-muted-foreground">
                {pr.author_type === "agent" ? "◆ agent" : "○ human"} {pr.author}{" "}
                · +{pr.additions} −{pr.deletions} · {pr.files.length}{" "}
                {pr.files.length === 1 ? "file" : "files"} ·{" "}
                {latency(pr.approval_latency_s)}
              </p>
              {verdict.reasons.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {verdict.reasons.map((r) => (
                    <li
                      key={r.rule}
                      className="font-mono text-xs text-muted-foreground"
                    >
                      <span className="text-sheen">+{r.weight.toFixed(2)}</span>{" "}
                      {r.label}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <Badge
              variant="outline"
              className={
                "h-fit self-start font-mono uppercase " +
                (verdict.band === "flagged"
                  ? "border-flag text-flag"
                  : "border-clear/50 text-clear")
              }
            >
              {verdict.band === "flagged" ? "needs you" : "cleared"}
            </Badge>
          </article>
        ))}
      </section>

      <footer className="border-t py-8 font-mono text-xs text-muted-foreground">
        Scores are deterministic and legible — every point of weight is a named
        rule. No model read any of this code.
      </footer>
    </main>
  );
}
