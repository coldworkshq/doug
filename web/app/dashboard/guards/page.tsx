import { withAuth } from "@workos-inc/authkit-nextjs";
import Link from "next/link";
import { redirect } from "next/navigation";

import { DashboardRail } from "@/components/dashboard-rail";
import { StateChip } from "@/components/state-chip";
import { frontDoor } from "@/lib/dashboard-model";
import { engineTenantFor } from "@/lib/guards-mapping";
import { getRegistrySnapshot, type RegistryResult } from "@/lib/registry-api";
import { getConnections } from "@/lib/session-api";

/** The route chip, matching the ledger's; declared here for the reason the
 *  settings page gives. */
const ROUTE = "rounded-[3px] bg-accent px-[7px] py-0.5 text-[var(--iridescent)] tracking-[.06em]";

/** The guard registry, over the engine's read contract (ADR-0034).
 *
 *  One code path; data decides. The founder maps an installation to an
 *  engine tenant (DOUG_GUARDS_INSTALLATIONS). A mapped installation reads
 *  the registry and renders the list only when the payload names that
 *  tenant; every other installation, and every failed or stale read, renders
 *  a chip with its sentence. The registry today holds one tenant of
 *  synthetic wind-tunnel data, and the provenance sentence travels with
 *  every figure at the same size, so nothing on this screen can be
 *  screenshotted as a real installation's number.
 *
 *  What the list is: metadata and versions. No artifact executes here, no
 *  input state is accepted, nothing promotes and nothing is subtracted; the
 *  only affordance is a link. A stranger's honest entry is the local audit. */
export default async function GuardsPage() {
  const { user, accessToken, organizationId } = await withAuth();
  if (!user || !accessToken) redirect("/sign-in");

  let connections: Awaited<ReturnType<typeof getConnections>> | null = null;
  try {
    connections = await getConnections(accessToken);
  } catch {
    // Swallowed on purpose, for the reason the settings page gives: /dashboard
    // owns the three arms a failed connections read can land on and renders
    // them inline, so this cannot loop.
    connections = null;
  }
  if (connections === null) redirect("/dashboard");

  const door = frontDoor(connections.connections, organizationId);
  if (door.state !== "runs") redirect("/dashboard");
  const connection = door.current;

  const mapping = engineTenantFor(connection.installation_id);
  let registry: RegistryResult | null = null;
  if (mapping) {
    registry = await getRegistrySnapshot().catch(() => null);
  }
  const snapshot = registry?.kind === "snapshot" && registry.snapshot.tenant_id === mapping ? registry.snapshot : null;

  return (
    <div className="dashboard-surface">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[212px_minmax(0,1fr)]">
        <DashboardRail
          connections={connections.connections}
          current={connection}
          userEmail={user.email}
          section="guards"
          runsHref="/dashboard"
          repositoriesHref="/dashboard?view=repositories"
        />

        <main className="mx-auto w-full max-w-[980px] px-6 py-10">
          <div className="mono mb-6 flex items-center gap-3 text-[10.5px] uppercase tracking-[.15em] text-[var(--dim)]">
            <span className={ROUTE}>/guards</span>
            <span className="truncate normal-case tracking-normal text-muted-foreground">
              {connection.account_login}
            </span>
            <span className="h-px flex-1 bg-border" />
          </div>

          <h1 className="font-heading text-[32px] font-semibold tracking-[-.03em]">Guards</h1>
          <p className="mt-3 max-w-[620px] text-sm text-muted-foreground">
            Judgments that come back the same every time, compiled into guarded, tested checks. A
            maintainer signs each one; it runs first in your CI; the model is asked less.
          </p>

          {!mapping && (
            <div className="mt-8 max-w-[620px]">
              <p className="text-sm">
                <StateChip kind="later" subject="guards" />
              </p>
              <p className="mt-4 text-sm text-muted-foreground">
                Running agents you didn&apos;t write? The audit reads the traces you already export, on
                your own machine, with no account.{" "}
                <Link href="/docs/audit" className="text-foreground underline underline-offset-[3px]">
                  Start with the audit
                </Link>
                .
              </p>
            </div>
          )}

          {mapping && registry === null && (
            <p className="mt-8 text-sm">
              <StateChip kind="unknown" subject="guards" detail="the registry was not read" />
            </p>
          )}

          {mapping && registry?.kind === "unknown" && (
            <p className="mt-8 text-sm">
              <StateChip kind="unknown" subject="guards" detail={registry.reason} />
            </p>
          )}

          {mapping && registry?.kind === "snapshot" && snapshot === null && (
            <p className="mt-8 text-sm">
              <StateChip
                kind="unknown"
                subject="guards"
                detail={`the registry serves tenant ${registry.snapshot.tenant_id ?? "unknown"}; this installation is mapped to ${mapping}`}
              />
            </p>
          )}

          {snapshot && (
            <>
              <p className="mt-8 text-sm">
                {snapshot.synthetic ? (
                  <StateChip kind="synthetic" subject="guards" detail={snapshot.provenance ?? "an undeclared corpus"} />
                ) : (
                  <span className="text-muted-foreground">Measured on {snapshot.provenance}.</span>
                )}
              </p>

              <dl className="mono mt-6 grid grid-cols-3 gap-4 border-t border-border pt-4 text-[11px] uppercase tracking-[.12em] text-[var(--dim)]">
                <div>
                  <dt>Signatures owed</dt>
                  <dd className="mt-1 text-[22px] normal-case tracking-normal text-foreground">{snapshot.counts.signatures_owed}</dd>
                </div>
                <div>
                  <dt>Unproven</dt>
                  <dd className="mt-1 text-[22px] normal-case tracking-normal text-foreground">{snapshot.counts.unproven}</dd>
                </div>
                <div>
                  <dt>In flight</dt>
                  <dd className="mt-1 text-[22px] normal-case tracking-normal text-foreground">{snapshot.counts.in_flight}</dd>
                </div>
              </dl>

              {snapshot.guards.length === 0 ? (
                <p className="mt-6 text-sm text-muted-foreground">
                  The registry holds no guard for this tenant. Nothing has been mined, drafted, or
                  promoted yet.
                </p>
              ) : (
                <div className="mt-6 overflow-x-auto border-t border-border">
                  <table className="w-full text-left text-[12.5px]">
                    <thead className="mono text-[10px] uppercase tracking-[.12em] text-[var(--dim)]">
                      <tr>
                        <th className="py-2 pr-3">State</th>
                        <th className="py-2 pr-3">Guard</th>
                        <th className="py-2 pr-3">Pack · target</th>
                        <th className="py-2 pr-3">Enforces</th>
                        <th className="py-2 pr-3">Eligible when</th>
                        <th className="py-2 pr-3">Audit</th>
                        <th className="py-2 pr-3">Signed by</th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshot.guards.map((g) => {
                        const sampled = g.auditAgreed + g.auditDisagreed + g.auditInconclusive;
                        return (
                          <tr key={`${g.guardId}-${g.guardVersion}`} className="border-t border-border align-top">
                            <td className="mono py-2 pr-3 text-[10.5px] uppercase tracking-[.1em] text-[var(--dim)]">{g.state}</td>
                            <td className="mono py-2 pr-3 text-foreground">
                              {g.guardId.slice(0, 8)} v{g.guardVersion}
                              <div className="text-[10px] text-[var(--dim)]">{g.artifactDigestAlgo}:{g.artifactDigestValue.slice(0, 12)}</div>
                            </td>
                            <td className="py-2 pr-3">
                              {g.pack}
                              <div className="mono text-[10px] text-[var(--dim)]">{g.target}</div>
                            </td>
                            <td className="mono py-2 pr-3 text-[11px]">
                              {g.enforces && g.enforces.length > 0
                                ? g.enforces.map((p) => `${p.name} v${p.version}`).join(", ")
                                : "not recorded"}
                            </td>
                            <td className="mono max-w-[260px] py-2 pr-3 text-[11px] break-words text-muted-foreground">
                              {g.eligibilityCel.length > 190 ? `${g.eligibilityCel.slice(0, 190)}…` : g.eligibilityCel}
                            </td>
                            <td className="mono py-2 pr-3 text-[11px]">
                              {g.auditAttributable && sampled > 0
                                ? `${g.auditAgreed} agreed · ${g.auditDisagreed} disagreed · ${g.auditInconclusive} inconclusive`
                                : "not attributable"}
                            </td>
                            <td className="mono py-2 pr-3 text-[11px]">{g.promotedBy ?? "unsigned"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
