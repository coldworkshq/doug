import { JobsTable } from "@/components/jobs-table";
import { Shell } from "@/components/shell";
import { getHealth, getJobs, isError } from "@/lib/api";
import { parseTenantId } from "@/lib/runs";

export const dynamic = "force-dynamic";

const PAGE_LIMIT = 500;

/** Builds the toggle href explicitly rather than spreading `params` into
 *  `URLSearchParams` — `params` is `{ repo?: string; tenant?: string }`,
 *  optional properties, and `URLSearchParams` stringifies an `undefined`
 *  value as the literal text "undefined" rather than dropping the key. On
 *  an unfiltered `/jobs`, `new URLSearchParams({ ...params, view })` would
 *  produce `?repo=undefined`, which `getJobs` reads as a real (if odd) repo
 *  filter and returns an empty, filtered-looking list — "the job I expected
 *  does not exist" indistinguishable from "the toggle is broken". Same
 *  explicit-presence discipline as `getJobs`'s `installationId` check. */
function toggleHref(
  params: { repo?: string; tenant?: string },
  view: "unhealthy" | "all",
): string {
  const q = new URLSearchParams();
  if (params.repo) q.set("repo", params.repo);
  if (params.tenant) q.set("tenant", params.tenant);
  q.set("view", view);
  return `?${q}`;
}

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<{ repo?: string; tenant?: string; view?: string }>;
}) {
  const params = await searchParams;
  const scope = { tenant: params.tenant ?? null, repo: params.repo ?? null };
  const view = params.view === "all" ? "all" : "unhealthy";

  // Same contract as the Runs page: a tenant that does not parse to a real
  // installation id must not silently fall back to "no filter".
  const tenant = parseTenantId(params.tenant);
  const installationId = tenant.kind === "present" ? tenant.id : undefined;

  const [review, outcome, health] =
    tenant.kind === "invalid"
      ? [
          { error: `tenant=${params.tenant} is not a valid installation id` },
          { error: `tenant=${params.tenant} is not a valid installation id` },
          await getHealth(),
        ]
      : await Promise.all([
          getJobs({ lane: "review", view, repo: params.repo, installationId, limit: PAGE_LIMIT }),
          getJobs({ lane: "outcome", view, repo: params.repo, installationId, limit: PAGE_LIMIT }),
          getHealth(),
        ]);

  // The caps come from the health payload, not from a literal here: the two
  // lanes differ (3 vs 10) and the console must never hardcode either.
  const caps = isError(health)
    ? { review: 0, outcome: 0 }
    : { review: health.review.max_attempts, outcome: health.outcome.max_attempts };

  return (
    <Shell scope={scope} active="jobs">
      <div className="mono mt-6 flex items-center gap-3 text-xs">
        <span className="text-muted-foreground">showing</span>
        <a
          href={toggleHref(params, "unhealthy")}
          aria-current={view === "unhealthy" ? "true" : undefined}
          className="rounded-[4px] border border-border px-2 py-1 aria-[current]:border-[var(--iridescent)] aria-[current]:font-semibold"
        >
          unhealthy only
        </a>
        <a
          href={toggleHref(params, "all")}
          aria-current={view === "all" ? "true" : undefined}
          className="rounded-[4px] border border-border px-2 py-1 aria-[current]:border-[var(--iridescent)] aria-[current]:font-semibold"
        >
          every job
        </a>
      </div>

      {[
        { key: "review", title: "Review lane", result: review, cap: caps.review },
        { key: "outcome", title: "Outcome lane (adjudicator)", result: outcome, cap: caps.outcome },
      ].map(({ key, title, result, cap }) =>
        isError(result) ? (
          // Never a number, never an empty table. An unreachable API and a
          // lane with no unhealthy jobs are different facts.
          <div
            key={key}
            className="mono mt-8 rounded-[6px] border border-[var(--flag)]/40 bg-[color-mix(in_srgb,var(--flag)_6%,transparent)] p-4 text-xs"
          >
            <p className="font-semibold text-[var(--flag)]">
              {title}: the API did not answer.
            </p>
            <p className="mt-1 text-muted-foreground">{result.error}</p>
          </div>
        ) : (
          <JobsTable
            key={key}
            title={title}
            jobs={result.items}
            atCap={result.items.length >= result.limit}
            limit={result.limit}
            maxAttempts={cap}
          />
        ),
      )}
    </Shell>
  );
}
