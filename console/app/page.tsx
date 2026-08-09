import { Suspense } from "react";

import { RunsTable } from "@/components/runs-table";
import { Shell } from "@/components/shell";
import { getRuns, isError } from "@/lib/api";
import { parseTenantId } from "@/lib/runs";

export const dynamic = "force-dynamic";

/** The API's own ceiling. Grouping, sorting and facet counts are all
 *  computed in the browser over whatever this returns, and every one of
 *  them is exactly true only while that IS the complete set for the scope —
 *  so the honest move is to fetch as much of it as the API will give,
 *  and to degrade visibly (see `atCap`) rather than silently when it is
 *  still not all of it. */
const PAGE_LIMIT = 500;

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<{ repo?: string; tenant?: string }>;
}) {
  const params = await searchParams;
  const scope = { tenant: params.tenant ?? null, repo: params.repo ?? null };

  // A tenant that doesn't parse to a real installation id (blank,
  // whitespace, "0", non-numeric, fractional — see parseTenantId) must not
  // silently fall back to "no filter": that would fetch every
  // installation's rows while the scope chip above still claims one. Same
  // error class as a rate rendered without its denominator, so it fails
  // the same way — the explicit panel, never a table under a false claim.
  const tenant = parseTenantId(params.tenant);

  const result =
    tenant.kind === "invalid"
      ? { error: `tenant=${params.tenant} is not a valid installation id` }
      : await getRuns({
          repo: params.repo,
          installationId: tenant.kind === "present" ? tenant.id : undefined,
          limit: PAGE_LIMIT,
        });

  // limit/offset round-trip the request: items.length hitting the
  // requested limit means there may be more than what's shown, and the
  // header must not claim that number IS the total run count when it
  // might only be the page size. Below the cap, items.length is the exact
  // and complete count (offset is always 0 here) — which is also what
  // makes the client-side grouping, sorting and facet counts true rather
  // than merely plausible.
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
        // RunsTable reads `useSearchParams`, which Next requires to sit
        // under a Suspense boundary or be excluded from prerender. Today
        // `dynamic = "force-dynamic"` above satisfies that — but it makes
        // this component's correctness depend on a page-level export three
        // dozen lines away, so deleting that line would break the BUILD,
        // not just the rendering. The boundary makes RunsTable stand on its
        // own. The fallback is deliberately empty: on a dynamic route it
        // never paints, and a skeleton row would be the console showing a
        // shape of data it does not have.
        <Suspense fallback={null}>
          <RunsTable
            runs={result.items}
            atCap={atCap}
            limit={result.limit}
            tenant={scope.tenant}
            scopeLabel={scopeLabel}
          />
        </Suspense>
      )}
    </Shell>
  );
}
