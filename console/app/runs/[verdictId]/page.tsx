import { notFound } from "next/navigation";

import { RunForensics, RunForensicsUnavailable } from "@/components/run-forensics";
import { Shell } from "@/components/shell";
import { getRunDetail, isError } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ verdictId: string }>;
}) {
  const { verdictId } = await params;
  const id = Number(verdictId);
  if (!Number.isInteger(id) || id < 1) notFound();

  const run = await getRunDetail(id);
  const scope = { tenant: null, repo: null };

  if (isError(run)) {
    return (
      <Shell scope={scope} active="runs">
        <RunForensicsUnavailable error={run.error} />
      </Shell>
    );
  }

  return (
    <Shell scope={scope} active="runs">
      <RunForensics run={run} clearHref="/" />
    </Shell>
  );
}
