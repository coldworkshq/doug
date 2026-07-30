import fixture from "./queue-fixture.json";

export type Band = "cleared" | "flagged";

export interface PRMetadata {
  number: number;
  title: string;
  author: string;
  author_type: "human" | "agent";
  additions: number;
  deletions: number;
  files: string[];
  approvals: number;
  approval_latency_s: number | null;
  days_since_last_human_commit: number | null;
  url: string | null;
}

export interface Reason {
  rule: string;
  label: string;
  weight: number;
}

export interface Verdict {
  score: number;
  band: Band;
  threshold: number;
  reasons: Reason[];
}

export interface QueueItem {
  pr: PRMetadata;
  verdict: Verdict;
}

export interface QueueResponse {
  summary: { open: number; flagged: number; cleared: number; threshold: number };
  items: QueueItem[];
}

export const API_URL = process.env.DOUG_API_URL ?? "http://localhost:8000";

/** Scope the dashboard's queue to one repo (e.g. "lemahq/lema"). Unset =
 *  the ledger's all-repos view, which mixes backfilled corpora in. */
const QUEUE_REPO = process.env.DOUG_QUEUE_REPO;

export async function getQueue(): Promise<{
  queue: QueueResponse;
  source: "live" | "fixture";
}> {
  try {
    const repoParam = QUEUE_REPO ? `?repo=${encodeURIComponent(QUEUE_REPO)}` : "";
    const res = await fetch(`${API_URL}/v1/queue${repoParam}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2000),
    });
    if (res.ok) return { queue: (await res.json()) as QueueResponse, source: "live" };
  } catch {
    // API down or unreachable — the bundled fixture keeps the demo alive.
  }
  return { queue: fixture as QueueResponse, source: "fixture" };
}

/** Re-band scored items against a caller-chosen threshold. Scores come from the
 *  API; only the cut line moves. Works identically on live and fixture data. */
export function applyThreshold(queue: QueueResponse, threshold: number): QueueResponse {
  const items = queue.items.map((i) => ({
    ...i,
    verdict: {
      ...i.verdict,
      threshold,
      band: (i.verdict.score >= threshold ? "flagged" : "cleared") as Band,
    },
  }));
  const flagged = items.filter((i) => i.verdict.band === "flagged").length;
  return {
    summary: { open: items.length, flagged, cleared: items.length - flagged, threshold },
    items,
  };
}
