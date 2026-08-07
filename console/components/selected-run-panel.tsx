"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { RunForensics, RunForensicsUnavailable } from "@/components/run-forensics";
import { isError, type RunDetail } from "@/lib/api";
import { loadRunDetail } from "@/lib/run-detail-action";
import { parseRunId } from "@/lib/selection";

export function SelectedRunPanel({
  initialDetail,
  clearHref,
}: {
  /** SSR payload for the first paint when ?run= was already in the URL. */
  initialDetail: RunDetail | { error: string } | null;
  clearHref: string;
}) {
  const searchParams = useSearchParams();
  const selectedId = parseRunId(searchParams.get("run"));
  if (selectedId === null) return null;

  // Only hand SSR data to the loader when it matches this id. Remount on id
  // change via key so we never need sync setState-in-effect to clear.
  const ssrMatch =
    initialDetail !== null &&
    (isError(initialDetail) || initialDetail.verdict_id === selectedId)
      ? initialDetail
      : null;

  return (
    <DetailBody
      key={selectedId}
      id={selectedId}
      initial={ssrMatch}
      clearHref={clearHref}
    />
  );
}

function DetailBody({
  id,
  initial,
  clearHref,
}: {
  id: number;
  initial: RunDetail | { error: string } | null;
  clearHref: string;
}) {
  const [detail, setDetail] = useState<RunDetail | { error: string } | null>(
    initial,
  );

  useEffect(() => {
    if (initial !== null) return;
    let cancelled = false;
    loadRunDetail(id).then((next) => {
      if (!cancelled) setDetail(next);
    });
    return () => {
      cancelled = true;
    };
  }, [id, initial]);

  if (detail === null) {
    return (
      <div className="mono mt-6 border-t border-border px-1 py-4 text-xs text-muted-foreground">
        Loading run {id}…
      </div>
    );
  }

  if (isError(detail)) {
    return (
      <div className="mt-6">
        <RunForensicsUnavailable error={detail.error} />
      </div>
    );
  }

  return (
    <div className="mt-6 border-t border-border">
      <RunForensics run={detail} clearHref={clearHref} />
    </div>
  );
}
