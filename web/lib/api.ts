import fixture from "./queue-fixture.json";
import { isComparisonResponse, type ComparisonResponse } from "./comparison";

export { isComparisonResponse } from "./comparison";
export type {
  ComparisonCoverage,
  ComparisonGroup,
  ComparisonPresence,
  ComparisonResponse,
  ComparisonRun,
  ComparisonSummary,
  ComparisonView,
} from "./comparison";

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
  /** Reader findings only; deterministic rules carry a weight instead. */
  severity?: string | null;
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

/** Scope the dashboard's queue to one repo (e.g. "drewjst/doug"). Unset =
 *  the ledger's all-repos view, which mixes backfilled corpora in. */
const QUEUE_REPO = process.env.DOUG_QUEUE_REPO;

type QueueResult = { queue: QueueResponse; source: "live" | "fixture" };

export type ComparisonResult = {
  comparison: ComparisonResponse | null;
  source: "live" | "unavailable";
};

/** Structural check on exactly the fields the pages dereference. A 200
 *  with a drifted body used to be cast straight through and threw deep in
 *  server rendering — with no boundary to catch it, one renamed backend
 *  field took both routes down to Next's unstyled default error page. A
 *  body that fails this check is treated like an unreachable API. */
function isQueueResponse(data: unknown): data is QueueResponse {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  const s = d.summary as Record<string, unknown> | null | undefined;
  if (
    typeof s !== "object" || s === null ||
    typeof s.open !== "number" || typeof s.flagged !== "number" ||
    typeof s.cleared !== "number" || typeof s.threshold !== "number"
  )
    return false;
  if (!Array.isArray(d.items)) return false;
  return (d.items as unknown[]).every((it) => {
    if (typeof it !== "object" || it === null) return false;
    const { pr, verdict } = it as { pr?: unknown; verdict?: unknown };
    if (typeof pr !== "object" || pr === null) return false;
    if (typeof verdict !== "object" || verdict === null) return false;
    const p = pr as Record<string, unknown>;
    const v = verdict as Record<string, unknown>;
    return (
      typeof p.number === "number" &&
      Array.isArray(p.files) &&
      typeof v.score === "number" &&
      Array.isArray(v.reasons)
    );
  });
}

async function fetchQueue(): Promise<QueueResult> {
  try {
    const repoParam = QUEUE_REPO ? `?repo=${encodeURIComponent(QUEUE_REPO)}` : "";
    const res = await fetch(`${API_URL}/v1/queue${repoParam}`, {
      cache: "no-store",
      // 5s, up from 2s: a cold doug-web calling a cold doug-api overran 2s
      // and served the fixture to the first visitor after every
      // scale-to-zero. A rare slow first paint beats invented PRs.
      signal: AbortSignal.timeout(5000),
      // Server-only: this runs in a server component, so the token must
      // never carry a NEXT_PUBLIC_ prefix. A 401/503 falls through to the
      // fixture below, which the page labels "bundled fixture" — that
      // badge is the tell for a misconfigured deploy.
      headers: { "X-Doug-Token": process.env.DOUG_API_TOKEN ?? "" },
    });
    if (res.ok) {
      const body: unknown = await res.json();
      if (isQueueResponse(body)) return { queue: body, source: "live" };
    }
  } catch {
    // API down or unreachable — the bundled fixture keeps the demo alive.
  }
  return { queue: fixture as QueueResponse, source: "fixture" };
}

// Per-instance micro-cache. Deliberately not ISR/`next.revalidate`: caching
// the route would bake the build-time fixture into the prerender and brand
// the page "sample data" after every cold start. This keeps rendering
// dynamic while a traffic burst (the marketing page getting linked) hits
// the queue API a couple of times a minute instead of once per visitor.
// Concurrent misses share one in-flight fetch. A fixture result is kept
// only briefly so recovery from an outage is quick.
const FIXTURE_TTL_MS = 5_000;
let inflight: Promise<QueueResult> | null = null;
let last: { at: number; value: QueueResult } | null = null;

export async function getQueue(
  opts: { maxAgeMs?: number } = {},
): Promise<QueueResult> {
  const maxAge = opts.maxAgeMs ?? 0;
  if (last) {
    const ttl = last.value.source === "live" ? maxAge : Math.min(maxAge, FIXTURE_TTL_MS);
    if (Date.now() - last.at < ttl) return last.value;
  }
  if (!inflight) {
    inflight = fetchQueue().then((value) => {
      last = { at: Date.now(), value };
      inflight = null;
      return value;
    });
  }
  return inflight;
}

export async function getComparisons(): Promise<ComparisonResult> {
  try {
    const repoParam = QUEUE_REPO ? `?repo=${encodeURIComponent(QUEUE_REPO)}` : "";
    const res = await fetch(`${API_URL}/v1/comparisons${repoParam}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
      headers: { "X-Doug-Token": process.env.DOUG_API_TOKEN ?? "" },
    });
    if (res.ok) {
      const body: unknown = await res.json();
      if (isComparisonResponse(body)) return { comparison: body, source: "live" };
    }
  } catch {
    // The caller renders unavailable; comparison evidence is never fabricated.
  }
  return { comparison: null, source: "unavailable" };
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
