import Link from "next/link";

import { BandChip } from "@/components/band-chip";
import { CoverageBar } from "@/components/coverage-bar";
import { Shell } from "@/components/shell";
import { getRuns, isError } from "@/lib/api";
import { jobDuration, relativeAge } from "@/lib/runs";

export const dynamic = "force-dynamic";

// The rows are the one place real repo values exist (they come off the
// ledger, not a guess), so setting the filter belongs here rather than in
// ScopeSwitch — see ScopeSwitch's own comment for why it only clears.
// Preserves `tenant` (the only other scope param this page reads) and
// drops any existing `repo` in favour of the row's own.
function repoFilterHref(repo: string, tenant: string | null): string {
  const params = new URLSearchParams();
  if (tenant) params.set("tenant", tenant);
  params.set("repo", repo);
  return `/?${params}`;
}

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<{ repo?: string; tenant?: string }>;
}) {
  const params = await searchParams;
  const scope = { tenant: params.tenant ?? null, repo: params.repo ?? null };

  // A non-numeric tenant (?tenant=abc) makes Number(tenant) NaN, which is
  // falsy — getRuns would silently drop the installation_id filter and
  // fetch every installation's rows while the chip above still claims one.
  // That is a fabricated scope claim, the same error class as a rate
  // rendered without its denominator, so it fails the same way: the
  // explicit panel, not a table quietly showing the wrong tenant's runs.
  // (A non-integer numeric string like "12.5" is already caught downstream
  // — the API 422s on a non-int query param — but NaN never reaches the
  // API at all, so it needs its own check.)
  const tenantValid = params.tenant === undefined || Number.isInteger(Number(params.tenant));

  const result = tenantValid
    ? await getRuns({
        repo: params.repo,
        installationId: params.tenant ? Number(params.tenant) : undefined,
      })
    : { error: `tenant=${params.tenant} is not a valid installation id` };

  // limit/offset round-trip the request: items.length hitting the
  // requested limit means there may be more than what's shown, and the
  // header must not claim that number IS the total run count when it
  // might only be the page size. Below the cap, items.length is the exact
  // and complete count (offset is always 0 here).
  const atCap = !isError(result) && result.items.length >= result.limit;

  const scopeLabel = scope.repo
    ? `for ${scope.repo}`
    : scope.tenant
      ? `for tenant ${scope.tenant}`
      : "across every installation";

  return (
    <Shell scope={scope} active="runs">
      {isError(result) ? (
        // Never a number, never an empty table. An unreachable API and a
        // ledger with no runs are different facts.
        <div className="mono mt-10 rounded-[6px] border border-[var(--flag)]/40 bg-[color-mix(in_srgb,var(--flag)_6%,transparent)] p-4 text-xs">
          <p className="font-semibold text-[var(--flag)]">The API did not answer.</p>
          <p className="mt-1 text-muted-foreground">{result.error}</p>
          <p className="mt-2 text-muted-foreground">
            Nothing is rendered below because nothing is known. This console has no
            fixture fallback by design.
          </p>
        </div>
      ) : (
        <>
          <p className="mono flex items-center gap-3 py-5 text-[10.5px] uppercase tracking-[.16em] text-muted-foreground">
            Runs — verdict history {scopeLabel}
            <span className="h-px flex-1 bg-border" />
            {atCap ? (
              <>
                latest <b className="text-foreground">{result.limit}</b> runs
              </>
            ) : (
              <>
                <b className="text-foreground">{result.items.length}</b> runs
              </>
            )}
          </p>
          <table className="w-full table-fixed border-collapse">
            <thead>
              <tr>
                {[
                  ["score", "w-[66px] text-right"],
                  ["pull request", ""],
                  ["band", "w-[96px]"],
                  ["tier", "w-[88px]"],
                  ["read", "w-[176px]"],
                  ["outcome", "w-[104px]"],
                  ["job", "w-[118px]"],
                  ["age", "w-[46px] text-right"],
                ].map(([label, cls]) => (
                  <th
                    key={label}
                    className={`mono border-b border-border pb-[7px] text-left text-[10px] font-medium uppercase tracking-[.13em] text-muted-foreground ${cls}`}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.items.map((run) => {
                // A job row only carries a verdict_id once ingest.complete()
                // sets it, and that same UPDATE sets status="done" in the
                // same statement (api/doug/ingest.py:508-509); fail() only
                // ever touches a row still status="running" and a revive
                // nulls verdict_id back out. So run.job, when present here,
                // is always "done" — there is no reachable "failed" state
                // to render on a verdict-keyed row. A failed attempt has no
                // verdict at all, and surfacing those needs a query keyed
                // on jobs instead of verdicts (Phase 2).
                const duration = run.job ? jobDuration(run.job.started_at, run.job.finished_at) : null;
                const jobLabel = run.job ? (duration ? `${run.job.status} · ${duration}` : run.job.status) : "—";
                return (
                  <tr key={run.verdict_id} className="border-b border-border/50 hover:bg-muted/40">
                    <td className="h-[34px] px-2.5 text-right">
                      <span
                        className={
                          "mono text-[14.5px] font-semibold " +
                          (run.band === "flagged" ? "data-flag" : "data-clear")
                        }
                      >
                        {run.score.toFixed(2)}
                      </span>
                    </td>
                    <td className="h-[34px] min-w-0 px-2.5">
                      <div className="flex min-w-0 items-baseline gap-2">
                        <span className="mono flex-none whitespace-nowrap text-[11px] text-muted-foreground">
                          <Link
                            href={repoFilterHref(run.repo, scope.tenant)}
                            aria-label={`Filter runs to ${run.repo}`}
                            className="hover:text-foreground hover:underline"
                          >
                            {run.repo}
                          </Link>{" "}
                          <b className="font-medium text-foreground">#{run.pr_number}</b>
                        </span>
                        <Link
                          href={`/runs/${run.verdict_id}`}
                          className="min-w-0 flex-1 truncate text-[12.5px] hover:underline"
                        >
                          {run.title}
                        </Link>
                      </div>
                    </td>
                    <td className="h-[34px] px-2.5">
                      <BandChip band={run.band} />
                    </td>
                    <td className="mono h-[34px] px-2.5 text-[11px] text-muted-foreground">{run.tier}</td>
                    <td className="h-[34px] px-2.5">
                      <CoverageBar coverage={run.coverage} changedFiles={run.changed_files} />
                    </td>
                    <td className="mono h-[34px] px-2.5 text-xs">
                      {run.outcome_14 === null ? (
                        <span className="text-muted-foreground">◷ pending</span>
                      ) : run.outcome_14 === "clean" ? (
                        <span className="data-clear">✓ clean</span>
                      ) : (
                        <span className="data-flag font-semibold">↩ {run.outcome_14}</span>
                      )}
                    </td>
                    <td className="mono h-[34px] px-2.5 text-[11px] text-muted-foreground">{jobLabel}</td>
                    <td className="mono h-[34px] px-2.5 text-right text-[11px] text-muted-foreground">
                      {relativeAge(run.scored_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </Shell>
  );
}
