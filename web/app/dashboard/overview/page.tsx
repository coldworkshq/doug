import { withAuth } from "@workos-inc/authkit-nextjs";
import { redirect } from "next/navigation";

import { DashboardRail } from "@/components/dashboard-rail";
import { OverviewSlots } from "@/components/overview-slots";
import { frontDoor } from "@/lib/dashboard-model";
import { engineTenantFor } from "@/lib/guards-mapping";
import { decisionsSlot, guardSlots, reviewedSlot } from "@/lib/overview-slots";
import { getRegistrySnapshot } from "@/lib/registry-api";
import { getConnections, getRepositoryDecisions, getSessionRuns } from "@/lib/session-api";

/** The route chip, matching the ledger's; declared here for the reason the
 *  settings page gives. */
const ROUTE = "rounded-[3px] bg-accent px-[7px] py-0.5 text-[var(--iridescent)] tracking-[.06em]";

/** The one screen (ADR-0034): the organization's week in four slots, each a
 *  figure beside its sentence or a chip with its reason. Depth is one click
 *  down at every slot: Reviews to the ledger and a receipt, Memory to the
 *  records, Guards to the registry.
 *
 *  Nothing here is a build flag. The reviewed slot is real when the ledger
 *  has rows; decisions when the intent read finds records; the two engine
 *  slots when the founder has mapped this installation to an engine tenant,
 *  the registry names that tenant, and a guard has dispatched. The same
 *  component renders every installation; the data decides which branch. */
export default async function OverviewPage() {
  const { user, accessToken, organizationId } = await withAuth();
  if (!user || !accessToken) redirect("/sign-in");

  let connections: Awaited<ReturnType<typeof getConnections>> | null = null;
  try {
    connections = await getConnections(accessToken);
  } catch {
    // Swallowed on purpose, for the reason the settings page gives: /dashboard
    // owns the three arms a failed connections read can land on and renders
    // them inline, so this cannot loop. The redirect is outside the catch
    // because `redirect` works by throwing.
    connections = null;
  }
  if (connections === null) redirect("/dashboard");

  const door = frontDoor(connections.connections, organizationId);
  if (door.state !== "runs") redirect("/dashboard");
  const connection = door.current;

  const repositories = [...connection.repositories].sort((a, b) =>
    a.full_name.localeCompare(b.full_name),
  );
  const first = repositories[0] ?? null;
  const mapping = engineTenantFor(connection.installation_id);

  // The three reads are independent, so they run together. Each failure is a
  // chip on its own slot, never a failed page.
  const [runs, decisions, registry] = await Promise.all([
    getSessionRuns(accessToken, "all").then((r) => r.items).catch(() => null),
    first ? getRepositoryDecisions(accessToken, first.id).catch(() => null) : Promise.resolve(null),
    mapping ? getRegistrySnapshot().catch(() => null) : Promise.resolve(null),
  ]);

  const reviewed =
    runs === null
      ? { ...reviewedSlot([]), figure: null, chip: { kind: "unknown" as const, subject: "reviews", detail: "the ledger did not answer" } }
      : reviewedSlot(runs);
  const engine = guardSlots(mapping, registry);
  const slots = [reviewed, decisionsSlot(decisions, first?.full_name ?? null), engine.settled, engine.t];

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
            <span className={ROUTE}>/overview</span>
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
