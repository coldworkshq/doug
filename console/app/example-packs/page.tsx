import Link from "next/link";

import { ExamplePackSummary } from "@/components/example-pack-summary";
import { ExamplePackTable } from "@/components/example-pack-table";
import { Shell } from "@/components/shell";
import { getExamplePackCohort, getExamplePackCohorts, isError } from "@/lib/api";
import type { CohortSummary } from "@/lib/example-packs";

export const dynamic = "force-dynamic";

function newestAvailable(summaries: CohortSummary[]): CohortSummary | null {
  return summaries
    .filter((summary) => summary.manifest !== null)
    .sort((left, right) => {
      const byStart = right.manifest!.capture_started_at.localeCompare(left.manifest!.capture_started_at);
      return byStart || left.cohort_id.localeCompare(right.cohort_id);
    })[0] ?? null;
}

function Failure({ error }: { error: string }) {
  return (
    <div className="mono mt-10 border-l-2 border-[var(--flag)] bg-[color-mix(in_srgb,var(--flag)_5%,transparent)] p-4 text-xs">
      <p className="font-semibold text-[var(--flag)]">Example Pack evidence is unavailable.</p>
      <p className="mt-1 text-muted-foreground">{error}</p>
      <p className="mt-2 text-muted-foreground">No cohort counts or scorecards are inferred.</p>
    </div>
  );
}

export default async function ExamplePacksPage({
  searchParams,
}: {
  searchParams: Promise<{ cohort?: string | string[] }>;
}) {
  const query = (await searchParams).cohort;
  const requested = typeof query === "string" ? query : null;
  const summaries = await getExamplePackCohorts();
  const scope = { tenant: null, repo: null };

  if (isError(summaries)) {
    return <Shell scope={scope} active="example-packs"><Failure error={summaries.error} /></Shell>;
  }
  const selected = requested
    ? summaries.find((summary) => summary.cohort_id === requested) ?? null
    : newestAvailable(summaries);

  if (selected === null) {
    return (
      <Shell scope={scope} active="example-packs">
        <header className="py-7"><h1 className="font-heading text-2xl font-semibold tracking-tight">Example Pack docket</h1></header>
        <Failure error={requested ? `Unknown cohort ${requested}` : "No hosted cohort is configured."} />
      </Shell>
    );
  }

  const cohort = selected.manifest === null
    ? { error: selected.availability.reason ?? `Cohort is ${selected.availability.status}` }
    : await getExamplePackCohort(selected.cohort_id);

  return (
    <Shell scope={scope} active="example-packs">
      <header className="flex flex-col gap-4 py-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="mono text-[10px] uppercase tracking-[.15em] text-muted-foreground">private evidence docket</p>
          <h1 className="font-heading mt-1 text-2xl font-semibold tracking-tight">{selected.cohort_id}</h1>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted-foreground">Exact captured inputs and outputs, completeness against durable jobs, and append-only human judgment.</p>
        </div>
        <nav aria-label="Cohorts" className="mono flex max-w-full gap-1 overflow-x-auto text-[10px]">
          {summaries.map((summary) => (
            <Link key={summary.cohort_id} href={`/example-packs?cohort=${encodeURIComponent(summary.cohort_id)}`} aria-current={summary.cohort_id === selected.cohort_id ? "page" : undefined} className="whitespace-nowrap rounded-[3px] border border-border px-2 py-1 text-muted-foreground aria-[current]:border-[var(--iridescent)] aria-[current]:text-foreground">
              {summary.cohort_id}
            </Link>
          ))}
        </nav>
      </header>
      {isError(cohort) ? <Failure error={cohort.error} /> : (
        <>
          <ExamplePackSummary cohort={cohort} />
          <ExamplePackTable cohortId={cohort.manifest.cohort_id} members={cohort.members} nonMembers={cohort.non_member_attempts} />
        </>
      )}
    </Shell>
  );
}
