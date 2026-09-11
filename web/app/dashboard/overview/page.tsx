import { DashboardRail, ROUTE_CHIP } from "@/components/dashboard-rail";
import { OverviewSlots } from "@/components/overview-slots";
import { resolveGuardsMapping } from "@/lib/guards-mapping";
import { decisionsSlot, guardSlots, reviewedSlot } from "@/lib/overview-slots";
import { getRegistrySnapshot } from "@/lib/registry-api";
import { SESSION_RUNS_LIMIT, getRepositoryDecisions, getSessionRuns } from "@/lib/session-api";
import { loadWorkspace, sortedRepositories } from "@/lib/workspace";

/** The one screen (ADR-0034): the organization's week in four slots, each a
 *  figure beside its sentence or a chip with its reason. Depth is one click
 *  down at every slot: Reviews to the ledger and a receipt, Memory to the
 *  records, Guards to the registry.
 *
 *  Nothing here is a build flag. The reviewed slot is real when the ledger
 *  has rows; decisions when the intent read finds records; the two engine
 *  slots when the founder has mapped this installation to an engine tenant,
 *  the registry names that tenant, and a guard has dispatched. The same
 *  component renders every installation; the data decides which branch.
 *
 *  Each read fails alone. A failure is a chip on its own slot and a line in
 *  the logs, never a failed page and never a silent one. */
export default async function OverviewPage() {
  const { user, connections, connection, accessToken } = await loadWorkspace();
  const repositories = sortedRepositories(connection);
  const first = repositories[0] ?? null;
  const mapping = resolveGuardsMapping(connection.installation_id);

  const failed = (what: string) => (error: unknown) => {
    console.error(`doug: overview ${what} read failed`, error);
    return null;
  };
  // The three reads are independent, so they run together.
  const [runs, decisions, registry] = await Promise.all([
    getSessionRuns(accessToken, "all").then((r) => r.items).catch(failed("ledger")),
    first ? getRepositoryDecisions(accessToken, first.id).catch(failed("decisions")) : Promise.resolve(null),
    mapping.tenant
      ? getRegistrySnapshot({ expectTenant: mapping.tenant }).catch(failed("registry"))
      : Promise.resolve(null),
  ]);

  const engine = guardSlots(mapping, registry);
  const slots = [
    reviewedSlot(runs, SESSION_RUNS_LIMIT),
    decisionsSlot(decisions, first?.full_name ?? null),
    engine.settled,
    engine.t,
  ];

  return (
    <div className="dashboard-surface">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[212px_minmax(0,1fr)]">
        <DashboardRail
          connections={connections.connections}
          current={connection}
          userEmail={user.email}
          section="overview"
          runsHref="/dashboard"
          repositoriesHref="/dashboard?view=repositories"
        />

        <main className="mx-auto w-full max-w-[820px] px-6 py-10">
          <div className="mono mb-6 flex items-center gap-3 text-[10.5px] uppercase tracking-[.15em] text-[var(--dim)]">
            <span className={ROUTE_CHIP}>/overview</span>
            <span className="truncate normal-case tracking-normal text-muted-foreground">
              {connection.account_login}
            </span>
            <span className="h-px flex-1 bg-border" />
          </div>

          <h1 className="font-heading text-[32px] font-semibold tracking-[-.03em]">Overview</h1>
          <p className="mt-3 max-w-[620px] text-sm text-muted-foreground">
            {repositories.length} {repositories.length === 1 ? "repository" : "repositories"} connected. Every figure
            here is one click from its evidence; every one that is not yet real says so.
          </p>

          <OverviewSlots slots={slots} />
        </main>
      </div>
    </div>
  );
}
