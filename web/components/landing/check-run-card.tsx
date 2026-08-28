import { DougLogo } from "@/components/doug-logo";
import type { QueueItem, ScoreboardResponse } from "@/lib/api";

/** The landing hero's object: a facsimile of the neutral `Doug` check run,
 *  rendered from the same queue and scoreboard the live pages read.
 *
 *  The shape mirrors api/doug/check_run.py deliberately — headline, the
 *  Risk / Flag line / Read / Findings table, the "Needs you" note for a
 *  flagged band, the findings list, and the two footer lines
 *  (`adjudicated N · pending N · as of DATE`, `deep reads N/CAP this cycle`).
 *  Those footer lines are the point of putting this in the hero: no other
 *  reviewer can render them, because no other reviewer grades itself.
 *
 *  Strings that are load-bearing claims (NEEDS_YOU, CLEARED_NOTE, the read
 *  cell) are copied from check_run.py rather than paraphrased, so the hero
 *  cannot promise something the real check does not say. When they change
 *  there, change them here.
 *
 *  Server component; no state, no client JS. */

const NEEDS_YOU =
  "Needs you. Risk is above this repository's flag line, so Doug is asking for a human read. It does not block: this check is neutral and the merge button is unchanged.";

const CLEARED_NOTE =
  "Cleared means Doug found nothing it wanted a human to look at; it is not a statement that the change is safe.";

const SEVERITY_ORDER = ["high", "medium", "low"] as const;

function day(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "—";
}

/** The Findings cell: counts per severity from the fixed vocabulary, or a
 *  bare count when a reason carries no severity (the deterministic tier). */
function findingCounts(reasons: QueueItem["verdict"]["reasons"]): string {
  if (reasons.length === 0) return "none";
  const bySeverity = SEVERITY_ORDER.map((s) => [s, reasons.filter((r) => r.severity === s).length] as const)
    .filter(([, n]) => n > 0);
  const total = bySeverity.reduce((acc, [, n]) => acc + n, 0);
  if (total !== reasons.length) return String(reasons.length);
  return bySeverity.map(([s, n]) => `${n} ${s}`).join(" · ");
}

export function CheckRunCard({
  item,
  scoreboard,
  live,
}: {
  item: QueueItem | null;
  scoreboard: ScoreboardResponse;
  live: boolean;
}) {
  // Tier is not on the queue payload; a reader finding is the one thing
  // that carries a severity, so its presence is the tier's fingerprint.
  const reader = item?.verdict.reasons.some((r) => r.severity != null) ?? false;
  const band = item?.verdict.band === "flagged" ? "Flagged" : "Cleared";
  const score = item ? item.verdict.score.toFixed(2) : "—";
  const headline = item
    ? reader
      ? `${band} · risk ${score} · diff read`
      : `Deterministic fallback · ${band} · risk ${score}`
    : "No open pull requests to read";
  const reasons = item?.verdict.reasons ?? [];
  const shown = reasons.slice(0, 3);
  const folded = reasons.length - shown.length;

  return (
    <figure className="panel relative overflow-hidden rounded-2xl text-sm shadow-xl shadow-black/[0.05] dark:shadow-black/40">
      <div className="bg-iridescent absolute inset-x-0 top-0 h-px opacity-70" />

      {/* Check-run chrome: what GitHub puts around the summary. */}
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3 font-mono text-xs">
        <span className="flex min-w-0 items-center gap-2 text-foreground">
          <DougLogo size={16} />
          <span className="font-medium">Doug</span>
          <span className="text-muted-foreground">· check run</span>
        </span>
        <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
          neutral
        </span>
      </div>

      <div className="px-5 pt-4 pb-5">
        {item ? (
          <p className="truncate font-mono text-xs text-muted-foreground">
            #{item.pr.number} · {item.pr.title}
          </p>
        ) : null}
        <p className="font-heading mt-1.5 text-lg leading-snug font-semibold tracking-tight">
          {headline}
        </p>

        {item ? (
          <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border font-mono text-xs">
            {[
              ["Risk", score, item.verdict.band === "flagged" ? "data-flag" : "data-clear"],
              ["Flag line", item.verdict.threshold.toFixed(2), ""],
              ["Read", reader ? "validated diff reader" : "none — scorer only", ""],
              ["Findings", findingCounts(reasons), ""],
            ].map(([k, v, tone]) => (
              <div key={k} className="min-w-0 bg-card px-2.5 py-2">
                <dt className="text-[10px] tracking-wider text-muted-foreground uppercase">{k}</dt>
                <dd className={`mt-0.5 font-medium break-words ${tone}`}>{v}</dd>
              </div>
            ))}
          </dl>
        ) : null}

        {item ? (
          <p
            className={`mt-4 border-l-2 pl-3 text-[13px] leading-relaxed ${
              item.verdict.band === "flagged"
                ? "border-[var(--iridescent)] text-foreground"
                : "border-border text-muted-foreground"
            }`}
          >
            {item.verdict.band === "flagged" ? (
              <>
                <strong className="font-semibold">Needs you.</strong>
                {NEEDS_YOU.slice("Needs you.".length)}
              </>
            ) : (
              CLEARED_NOTE
            )}
          </p>
        ) : (
          <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">
            The queue is empty. The next push gets a check like this one.
          </p>
        )}

        {shown.length > 0 ? (
          <div className="mt-4">
            <p className="font-mono text-[10px] tracking-wider text-muted-foreground uppercase">
              Findings
            </p>
            <ul className="mt-1.5 space-y-1 font-mono text-xs">
              {shown.map((r) => (
                <li key={r.rule} className="flex gap-2">
                  <span className="text-muted-foreground">–</span>
                  {/* Two lines, then a cut. A reader finding is a full
                      sentence (seen live: 60+ words), and three of them
                      unclamped make the hero taller than the viewport. The
                      real check run shows the whole sentence; this is a
                      facsimile, and the queue page has the rest. */}
                  <span className="line-clamp-2 min-w-0">
                    {r.severity ? (
                      <span className="text-muted-foreground">{r.severity} · </span>
                    ) : null}
                    <span className="text-foreground">{r.label}</span>
                    <span className="text-muted-foreground"> · {r.rule}</span>
                  </span>
                </li>
              ))}
              {folded > 0 ? (
                <li className="text-muted-foreground">
                  ▸ {folded} more finding{folded === 1 ? "" : "s"}
                </li>
              ) : null}
            </ul>
          </div>
        ) : null}

        {/* The two lines no other reviewer can print. */}
        <div className="mt-5 border-t border-border pt-3 font-mono text-xs text-muted-foreground">
          <p>
            adjudicated{" "}
            <span className="text-foreground">{scoreboard.adjudicated}</span> · pending{" "}
            <span className="text-foreground">{scoreboard.pending}</span> · as of{" "}
            {day(scoreboard.as_of)}
            {scoreboard.adjudicated === 0 && scoreboard.first_due
              ? ` · first due ${day(scoreboard.first_due)}`
              : null}
          </p>
          {scoreboard.deep_reads !== null ? (
            <p className="mt-0.5">
              deep reads{" "}
              <span className="text-foreground">
                {scoreboard.deep_reads}/{scoreboard.deep_read_cap}
              </span>{" "}
              this cycle
            </p>
          ) : null}
        </div>
      </div>

      <figcaption className="border-t border-border bg-background/60 px-5 py-2 font-mono text-[11px] text-muted-foreground">
        {live
          ? `What lands on every PR in ${scoreboard.repo}. Live.`
          : "What lands on every PR. Sample data — the live check is a fetch away."}
      </figcaption>
    </figure>
  );
}
