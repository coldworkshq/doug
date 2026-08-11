import Link from "next/link";
import { notFound } from "next/navigation";

import { ExamplePackDetailView } from "@/components/example-pack-detail";
import { Shell } from "@/components/shell";
import { getExamplePackDetail, isError } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ExamplePackPage({
  params,
  searchParams,
}: {
  params: Promise<{ packHash: string }>;
  searchParams: Promise<{ cohort?: string | string[] }>;
}) {
  const { packHash } = await params;
  const cohortQuery = (await searchParams).cohort;
  const cohortId = typeof cohortQuery === "string" ? cohortQuery : "";
  if (!/^[0-9a-f]{64}$/.test(packHash) || !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(cohortId)) {
    notFound();
  }
  const detail = await getExamplePackDetail(cohortId, packHash);
  const scope = { tenant: null, repo: null };
  return (
    <Shell scope={scope} active="example-packs">
      <header className="border-b border-border py-5">
        <p className="mono text-[10px] text-muted-foreground">
          <Link href={`/example-packs?cohort=${encodeURIComponent(cohortId)}`} className="text-foreground hover:text-[var(--iridescent)]">← {cohortId}</Link>
          <span className="mx-2">·</span>case file
        </p>
        <h1 className="font-heading mt-1 text-xl font-semibold tracking-tight">Pack {packHash.slice(0, 12)}</h1>
        {!isError(detail) && (
          <p className="mono mt-1 text-[10px] text-muted-foreground">{detail.pack.scope.repository_full_name} #{detail.pack.scope.pull_number} · {detail.pack.capture_status} · {detail.pack.run_id}</p>
        )}
      </header>
      {isError(detail) ? (
        <div className="mono mt-10 border-l-2 border-[var(--flag)] bg-[color-mix(in_srgb,var(--flag)_5%,transparent)] p-4 text-xs">
          <p className="font-semibold text-[var(--flag)]">This exact pack is unavailable.</p>
          <p className="mt-1 text-muted-foreground">{detail.error}</p>
        </div>
      ) : (
        <div className="pt-6"><ExamplePackDetailView cohortId={cohortId} detail={detail} /></div>
      )}
    </Shell>
  );
}
