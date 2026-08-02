import Link from "next/link";

import { DougLogo } from "@/components/doug-logo";
import {
  getComparisons,
  type ComparisonCoverage,
  type ComparisonGroup,
  type ComparisonPresence,
  type ComparisonRun,
} from "@/lib/api";
import { summarizeComparisons } from "@/lib/comparison";

function formatGap(value: number | null): string {
  if (value === null) return "—";
  const rounded = value.toFixed(3);
  return value > 0 ? `+${rounded}` : rounded;
}

function formatTime(value: string): string {
  return `${new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value))} UTC`;
}

function coveragePercent(coverage: ComparisonCoverage): number {
  if (coverage.diff_chars === 0) return 0;
  return Math.round((coverage.sent_chars / coverage.diff_chars) * 100);
}

function SourceBadge({ live }: { live: boolean }) {
  return (
    <span className="glass inline-flex items-center gap-2 rounded-full px-3 py-1.5 font-mono text-xs text-muted-foreground">
      <span
        className={
          "size-1.5 rounded-full " +
          (live ? "animate-pulse bg-clear" : "bg-flag")
        }
      />
      {live ? "live api" : "api unavailable"}
    </span>
  );
}

function PageShell({
  live,
  children,
}: {
  live: boolean;
  children: React.ReactNode;
}) {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 sm:px-6">
      <nav className="flex flex-wrap items-center justify-between gap-3 py-6">
        <Link
          href="/"
          className="font-heading flex items-center gap-2 text-lg font-semibold tracking-tight"
        >
          <DougLogo /> doug
        </Link>
        <div className="flex items-center gap-2">
          <span className="glass flex items-center gap-1 rounded-full p-1 font-mono text-xs">
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
          <SourceBadge live={live} />
        </div>
      </nav>
      {children}
    </main>
  );
}

function EvidenceState({
  eyebrow,
  title,
  body,
  unavailable = false,
}: {
  eyebrow: string;
  title: string;
  body: string;
  unavailable?: boolean;
}) {
  return (
    <section className="py-16 sm:py-24">
      <div
        className={
          "glass relative overflow-hidden rounded-2xl p-8 sm:p-12 " +
          (unavailable ? "border-flag/40" : "")
        }
      >
        <div
          className={
            "absolute inset-x-0 top-0 h-px " +
            (unavailable ? "bg-flag" : "bg-iridescent")
          }
        />
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
          {eyebrow}
        </p>
        <h1 className="font-heading mt-4 max-w-2xl text-4xl font-semibold tracking-tight sm:text-5xl">
          {title}
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-muted-foreground">
          {body}
        </p>
      </div>
    </section>
  );
}

function SummaryCard({
  label,
  value,
  detail,
  priority = "normal",
}: {
  label: string;
  value: string | number;
  detail: string;
  priority?: "normal" | "high" | "watch";
}) {
  return (
    <div
      className={
        "glass relative min-w-0 rounded-xl p-4 " +
        (priority === "high"
          ? "border-flag/50"
          : priority === "watch"
            ? "border-white/20"
            : "")
      }
    >
      <dt className="flex items-start justify-between gap-2">
        <span className="font-mono text-[0.68rem] uppercase tracking-[0.16em] text-muted-foreground">
          {label}
        </span>
        {priority !== "normal" && (
          <span
            className={
              "font-mono text-[0.62rem] uppercase tracking-wider " +
              (priority === "high" ? "text-flag" : "text-muted-foreground")
            }
          >
            {priority === "high" ? "high priority" : "watch"}
          </span>
        )}
      </dt>
      <dd
        className={
          "mt-3 font-mono text-2xl font-medium tabular-nums " +
          (priority === "high" ? "text-flag" : "")
        }
      >
        {value}
      </dd>
      <dd className="mt-1 font-mono text-[0.68rem] leading-relaxed text-muted-foreground">
        {detail}
      </dd>
    </div>
  );
}

function PresenceBadge({ presence }: { presence: ComparisonPresence }) {
  const copy: Record<ComparisonPresence, { label: string; tone: string }> = {
    paired: {
      label: "exact head present on both paths",
      tone: "bg-clear/10 text-clear",
    },
    "app-only": {
      label: "App only · CI absent",
      tone: "bg-white/5 text-muted-foreground",
    },
    "ci-only": {
      label: "CI only · App absent",
      tone: "bg-flag/15 text-flag",
    },
    "head-unknown": {
      label: "unpaired · head unknown",
      tone: "bg-white/5 text-muted-foreground",
    },
  };
  const { label, tone } = copy[presence];
  return (
    <span
      className={
        "rounded-full px-2.5 py-1 font-mono text-[0.68rem] uppercase tracking-wide " +
        tone
      }
    >
      {label}
    </span>
  );
}

function Coverage({ coverage }: { coverage: ComparisonCoverage | null }) {
  if (coverage === null) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        coverage unavailable
      </p>
    );
  }

  return (
    <div className="space-y-1 font-mono text-xs leading-relaxed text-muted-foreground">
      <p>
        <span className="text-foreground">
          {coveragePercent(coverage)}% coverage
        </span>{" "}
        · {coverage.sent_chars.toLocaleString("en-US")}/
        {coverage.diff_chars.toLocaleString("en-US")} characters ·{" "}
        {coverage.files_sent} {coverage.files_sent === 1 ? "file" : "files"} sent
      </p>
      {coverage.file_cut !== null && (
        <p className="break-all">
          cut file <span className="text-foreground">{coverage.file_cut}</span>
        </p>
      )}
      {coverage.files_unseen.length > 0 && (
        <p className="break-words">
          unseen files{" "}
          <span className="text-foreground">
            {coverage.files_unseen.join(", ")}
          </span>
        </p>
      )}
    </div>
  );
}

function RunCard({
  run,
  attempt,
  total,
}: {
  run: ComparisonRun;
  attempt: number;
  total: number;
}) {
  const pathLabel = run.path === "app" ? "App" : "CI";
  return (
    <div className="rounded-xl border border-white/10 bg-black/10 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            {pathLabel} run{total > 1 ? ` · attempt ${attempt}/${total}` : ""}
          </p>
          <p className="mt-1 font-mono text-3xl font-medium tabular-nums">
            {String(run.score)}
          </p>
        </div>
        <span
          className={
            "rounded-full px-2.5 py-1 font-mono text-[0.68rem] uppercase tracking-wide " +
            (run.band === "flagged"
              ? "bg-flag/15 text-flag"
              : "bg-clear/10 text-clear")
          }
        >
          {run.band}
        </span>
      </div>
      <dl className="mt-4 grid gap-2 border-t border-white/5 pt-3 font-mono text-xs sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">tier</dt>
          <dd className="mt-0.5 break-words text-foreground">{run.tier}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">scored</dt>
          <dd className="mt-0.5 text-foreground">{formatTime(run.scored_at)}</dd>
        </div>
      </dl>
      <div className="mt-3 border-t border-white/5 pt-3">
        <Coverage coverage={run.coverage} />
      </div>
    </div>
  );
}

function MissingRun({
  path,
  headUnknown = false,
}: {
  path: "app" | "ci";
  headUnknown?: boolean;
}) {
  if (headUnknown) {
    return (
      <div className="flex min-h-36 items-center justify-center rounded-xl border border-dashed border-white/15 bg-white/[0.02] p-5 text-center text-muted-foreground">
        <div>
          <p className="font-mono text-sm font-medium">counterpart unknown</p>
          <p className="mt-1 font-mono text-[0.68rem] uppercase tracking-wider">
            head identity unavailable
          </p>
        </div>
      </div>
    );
  }
  const app = path === "app";
  return (
    <div
      className={
        "flex min-h-36 items-center justify-center rounded-xl border border-dashed p-5 text-center " +
        (app
          ? "border-flag/50 bg-flag/5 text-flag"
          : "border-white/15 bg-white/[0.02] text-muted-foreground")
      }
    >
      <div>
        <p className="font-mono text-sm font-medium">
          {app ? "missing App run" : "missing CI run"}
        </p>
        <p className="mt-1 font-mono text-[0.68rem] uppercase tracking-wider">
          {app ? "cutover signal absent" : "baseline signal absent"}
        </p>
      </div>
    </div>
  );
}

function ScoreRail({ app, ci }: { app: ComparisonRun; ci: ComparisonRun }) {
  const position = (score: number) => `${Math.min(1, Math.max(0, score)) * 100}%`;

  return (
    <figure className="rounded-xl border border-white/10 bg-black/15 px-4 py-4 sm:px-5">
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-[0.68rem] uppercase tracking-[0.16em] text-muted-foreground">
          dual-trace score rail · 0—1
        </span>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          App <span className="text-sheen">{String(app.score)}</span> · CI{" "}
          <span className="text-foreground">{String(ci.score)}</span>
        </span>
      </figcaption>
      <div className="mt-5 space-y-4">
        <div className="grid grid-cols-[2.5rem_1fr] items-center gap-3">
          <span className="font-mono text-xs text-sheen">App</span>
          <div className="relative h-px bg-white/15">
            <span
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-sheen shadow-[0_0_0_3px_oklch(0.82_0.12_190/0.18)]"
              style={{ left: position(app.score) }}
            />
          </div>
        </div>
        <div className="grid grid-cols-[2.5rem_1fr] items-center gap-3">
          <span className="font-mono text-xs text-foreground">CI</span>
          <div className="relative h-px bg-white/15">
            <span
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-foreground shadow-[0_0_0_3px_oklch(0.93_0.01_260/0.14)]"
              style={{ left: position(ci.score) }}
            />
          </div>
        </div>
      </div>
      <div className="ml-[3.25rem] mt-3 flex justify-between font-mono text-[0.62rem] text-muted-foreground">
        <span>0</span>
        <span>0.5</span>
        <span>1</span>
      </div>
    </figure>
  );
}

function RevisionCard({ group }: { group: ComparisonGroup }) {
  const exactPair =
    group.delta !== null && group.app.length === 1 && group.ci.length === 1;

  return (
    <article className="glass overflow-hidden rounded-2xl">
      <div className="bg-iridescent h-px opacity-40" />
      <div className="p-4 sm:p-6">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[0.68rem] uppercase tracking-[0.16em] text-muted-foreground">
              <span className="break-all">{group.repo}</span> · #{group.pr_number}
            </p>
            <h2 className="font-heading mt-2 min-w-0 text-xl font-medium leading-snug">
              <a
                href={group.url}
                target="_blank"
                rel="noreferrer"
                className="break-words transition-colors hover:text-sheen"
              >
                {group.title}
              </a>
            </h2>
            <p className="mt-2 font-mono text-xs text-muted-foreground">
              {group.head_sha === null ? (
                "head unknown"
              ) : (
                <span title={group.head_sha}>head {group.head_sha.slice(0, 8)}</span>
              )}
            </p>
          </div>
          <div className="flex max-w-full flex-wrap items-center justify-end gap-2">
            <PresenceBadge presence={group.presence} />
            {group.duplicate && (
              <span className="rounded-full bg-white/5 px-2.5 py-1 font-mono text-[0.68rem] uppercase tracking-wide text-foreground">
                duplicate attempts
              </span>
            )}
            {group.delta !== null && (
              <span className="rounded-full bg-white/5 px-2.5 py-1 font-mono text-[0.68rem] tabular-nums text-foreground">
                App − CI {formatGap(group.delta)}
              </span>
            )}
          </div>
        </div>

        {exactPair && <div className="mt-5"><ScoreRail app={group.app[0]} ci={group.ci[0]} /></div>}

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <section aria-label="App runs" className="min-w-0">
            <h3 className="mb-2 font-mono text-[0.68rem] uppercase tracking-[0.16em] text-sheen">
              App delivery · {group.app.length} {group.app.length === 1 ? "run" : "runs"}
            </h3>
            {group.app.length === 0 ? (
              <MissingRun path="app" headUnknown={group.presence === "head-unknown"} />
            ) : (
              <div className="space-y-3">
                {group.app.map((run, index) => (
                  <RunCard
                    key={run.id}
                    run={run}
                    attempt={index + 1}
                    total={group.app.length}
                  />
                ))}
              </div>
            )}
          </section>
          <section aria-label="CI runs" className="min-w-0">
            <h3 className="mb-2 font-mono text-[0.68rem] uppercase tracking-[0.16em] text-muted-foreground">
              CI delivery · {group.ci.length} {group.ci.length === 1 ? "run" : "runs"}
            </h3>
            {group.ci.length === 0 ? (
              <MissingRun path="ci" headUnknown={group.presence === "head-unknown"} />
            ) : (
              <div className="space-y-3">
                {group.ci.map((run, index) => (
                  <RunCard
                    key={run.id}
                    run={run}
                    attempt={index + 1}
                    total={group.ci.length}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </article>
  );
}

export default async function ComparePage() {
  const { comparison, source } = await getComparisons();

  if (comparison === null) {
    return (
      <PageShell live={false}>
        <EvidenceState
          eyebrow="Cutover comparison · unavailable"
          title="Two paths. No evidence claimed."
          body="Doug could not read the comparison ledger. No soak evidence is being shown, and queue fixture data is never substituted here."
          unavailable
        />
      </PageShell>
    );
  }

  if (comparison.runs.length === 0) {
    return (
      <PageShell live={source === "live"}>
        <EvidenceState
          eyebrow="Cutover comparison · connected"
          title="Waiting for both instruments."
          body="The comparison ledger is configured, but it has no qualifying App or CI runs yet. Summary zeroes would look observed, so this view stays empty until evidence lands."
        />
      </PageShell>
    );
  }

  const { groups, summary } = summarizeComparisons(comparison.runs);

  return (
    <PageShell live={source === "live"}>
      <header className="py-10 sm:py-14">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
          Operational cutover measurement
        </p>
        <div className="mt-3 grid gap-5 md:grid-cols-[1fr_auto] md:items-end">
          <div>
            <h1 className="font-heading max-w-3xl text-5xl font-semibold tracking-tight sm:text-6xl">
              Two paths. <span className="text-iridescent">One head.</span>
            </h1>
            <p className="mt-5 max-w-2xl leading-relaxed text-muted-foreground">
              App and CI delivery are shown as separate reads of the same pull
              request head. Score gaps are descriptive; tier and coverage stay
              visible because a close score does not establish equivalence.
            </p>
          </div>
          <p className="font-mono text-xs text-muted-foreground md:text-right">
            {comparison.runs.length} runs
            <br />
            {groups.length} revision groups
          </p>
        </div>
      </header>

      <section aria-labelledby="summary-heading">
        <div className="mb-3 flex items-center justify-between gap-4">
          <h2
            id="summary-heading"
            className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground"
          >
            Instrument summary
          </h2>
          <span className="font-mono text-[0.68rem] text-muted-foreground">
            gaps use singleton exact-head pairs only
          </span>
        </div>
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard
            label="exact pairs"
            value={summary.exactPairs}
            detail="one App run + one CI run"
          />
          <SummaryCard
            label="missing App"
            value={summary.missingApp}
            detail="known heads without cutover delivery"
            priority="high"
          />
          <SummaryCard
            label="missing CI"
            value={summary.missingCi}
            detail="known heads without baseline delivery"
            priority="watch"
          />
          <SummaryCard
            label="duplicate groups"
            value={summary.duplicateGroups}
            detail="multiple attempts on either path"
          />
          <SummaryCard
            label="signed mean gap"
            value={formatGap(summary.meanSignedGap)}
            detail={`App − CI · ${summary.exactPairs} exact ${summary.exactPairs === 1 ? "pair" : "pairs"}`}
          />
          <SummaryCard
            label="mean absolute gap"
            value={formatGap(summary.meanAbsoluteGap)}
            detail={`${summary.exactPairs} exact ${summary.exactPairs === 1 ? "pair" : "pairs"}`}
          />
          <SummaryCard
            label="maximum absolute gap"
            value={formatGap(summary.maxAbsoluteGap)}
            detail={`${summary.exactPairs} exact ${summary.exactPairs === 1 ? "pair" : "pairs"}`}
          />
        </dl>
      </section>

      <section className="py-12" aria-labelledby="revisions-heading">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Revision evidence
            </p>
            <h2 id="revisions-heading" className="font-heading mt-2 text-3xl font-semibold">
              Newest evidence group first
            </h2>
          </div>
          <p className="max-w-md font-mono text-[0.68rem] leading-relaxed text-muted-foreground">
            Duplicate attempts remain visible and never contribute a score gap.
            Unknown heads remain visible but cannot form pairs.
          </p>
        </div>
        <div className="space-y-4">
          {groups.map((group) => (
            <RevisionCard key={group.key} group={group} />
          ))}
        </div>
      </section>

      <footer className="border-t border-white/5 py-8 font-mono text-xs leading-relaxed text-muted-foreground">
        This view describes observed App and CI verdicts. It does not label a
        gap as noise or claim equivalent instruments; compare score, tier, and
        coverage together.
      </footer>
    </PageShell>
  );
}
