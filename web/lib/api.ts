import fixture from "./queue-fixture.json";
import { isQueueResponse } from "./queue-shape";

export type {
  Band,
  PRMetadata,
  Reason,
  Verdict,
  QueueItem,
  QueueResponse,
} from "./queue-shape";
import type { Band, QueueResponse } from "./queue-shape";

export const API_URL = process.env.DOUG_API_URL ?? "http://localhost:8000";

type QueueResult = { queue: QueueResponse; source: "live" | "fixture" };

async function fetchQueue(): Promise<QueueResult> {
  try {
    // The public showcase queue: unauthenticated, and pinned to one repo by
    // the API's own DOUG_SHOWCASE_REPO. doug-web sends no credential and no
    // repo selector, which is what lets this service hold no operator token.
    const res = await fetch(`${API_URL}/v1/showcase/queue`, {
      cache: "no-store",
      // 5s, up from 2s: a cold doug-web calling a cold doug-api overran 2s
      // and served the fixture to the first visitor after every
      // scale-to-zero. A rare slow first paint beats invented PRs.
      signal: AbortSignal.timeout(5000),
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
