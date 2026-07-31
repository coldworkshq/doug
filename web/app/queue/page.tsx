import Link from "next/link";

import { DougLogo } from "@/components/doug-logo";
import { ScoreStrip } from "@/components/score-strip";
import { applyThreshold, getQueue, type Reason } from "@/lib/api";

const PRESETS = [0.5, 0.62, 0.8];

/** Preset cut lines, always including the one in force — otherwise clicking
 *  a preset is a one-way trip away from the queue's real threshold. */
function presets(active: number): number[] {
  return [...new Set([...PRESETS, active])].sort((a, b) => a - b);
}

/** Reader findings always carry weight 0 and a severity; deterministic rules
 *  carry a weight and no severity. Showing "+0.00" beside every reader
 *  finding printed a number that was constant by construction. */
function marker(r: Reason): string {
  if (r.severity) return r.severity;
  return r.weight ? `+${r.weight.toFixed(2)}` : "·";
}

function severityTone(r: Reason): string {
  if (r.severity === "high") return "text-flag";
  if (r.severity === "medium") return "text-sheen";
  return "text-muted-foreground";
}

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
      <nav className="flex items-center justify-between py-6">
        <Link
          href="/"
          className="font-heading flex items-center gap-2 text-lg font-semibold tracking-tight"
        >
          <DougLogo /> doug
        </Link>
        <span className="glass flex items-center gap-2 rounded-full px-3 py-1.5 font-mono text-xs text-muted-foreground">
          <span
            className={
              "size-1.5 rounded-full " +
              (source === "live" ? "animate-pulse bg-clear" : "bg-muted-foreground")
            }
          />
          {source === "live" ? "live api" : "bundled fixture"}
        </span>
      </nav>

      <section className="py-10">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Review queue
            </p>
            <h1 className="font-heading mt-2 text-4xl font-semibold tracking-tight md:text-5xl">
              {queue.summary.open} open.{" "}
              <span className="text-flag">
                {queue.summary.flagged} need you.
              </span>
            </h1>
          </div>
          <div className="glass flex items-center gap-1 rounded-full p-1.5 font-mono text-xs">
            <span className="px-2 uppercase tracking-widest text-muted-foreground">
              threshold
            </span>
            {presets(queue.summary.threshold).map((t) => (
              <Link
                key={t}
                href={`/queue?threshold=${t}`}
                className={
                  "rounded-full px-3 py-1 transition-colors " +
                  (t === threshold
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-white/10")
                }
              >
                {t.toFixed(2)}
              </Link>
            ))}
          </div>
        </div>
        <div className="glass mt-8 rounded-2xl p-6">
          <ScoreStrip
            points={queue.items.map((i) => ({
              score: i.verdict.score,
              band: i.verdict.band,
            }))}
            threshold={threshold}
          />
        </div>
      </section>

      <section className="space-y-3 pb-10">
        {queue.items.map(({ pr, verdict }) => (
          <article
            key={pr.number}
            className={
              "glass grid gap-3 rounded-2xl p-6 transition-transform hover:-translate-y-0.5 md:grid-cols-[5rem_1fr_auto] " +
              (verdict.band === "flagged" ? "border-flag/30" : "")
            }
          >
            <p
              className={
                "font-mono text-2xl " +
                (verdict.band === "flagged" ? "text-flag" : "text-clear")
              }
            >
              {verdict.score.toFixed(2)}
            </p>
            <div>
              <h2 className="font-heading text-lg font-medium">
                <a
                  href={pr.url ?? "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="transition-colors hover:text-sheen"
                >
                  <span className="mr-2 font-mono text-sm text-muted-foreground">
                    #{pr.number}
                  </span>
                  {pr.title}
                </a>
              </h2>
              <p className="mt-1 font-mono text-xs text-muted-foreground">
                {pr.author_type === "agent" ? "◆ agent" : "○ human"} {pr.author}{" "}
                · +{pr.additions} −{pr.deletions} · {pr.files.length}{" "}
                {pr.files.length === 1 ? "file" : "files"} ·{" "}
                {latency(pr.approval_latency_s)}
              </p>
              {verdict.reasons.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {verdict.reasons.map((r, i) => (
                    <li
                      key={`${r.rule}-${i}`}
                      className="font-mono text-xs text-muted-foreground"
                    >
                      <span className={severityTone(r)}>{marker(r)}</span>{" "}
                      {r.label}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <span
              className={
                "h-fit self-start rounded-full px-3 py-1 font-mono text-xs uppercase tracking-wide " +
                (verdict.band === "flagged"
                  ? "bg-flag/15 text-flag"
                  : "bg-clear/10 text-clear")
              }
            >
              {verdict.band === "flagged" ? "needs you" : "cleared"}
            </span>
          </article>
        ))}
      </section>

      <footer className="border-t border-white/5 py-8 font-mono text-xs text-muted-foreground">
        Every finding names the pattern it matched, so a score can be argued
        with. Reader findings come from a model reading the diff; the
        deterministic fallback names a weighted rule instead.
      </footer>
    </main>
  );
}
