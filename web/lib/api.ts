import fixture from "./queue-fixture.json";
import scoreboardFixture from "./scoreboard-fixture.json";
import { isQueueResponse } from "./queue-shape";
import { isScoreboardResponse } from "./scoreboard-shape";

export type {
  Band,
  PRMetadata,
  Reason,
  Verdict,
  QueueItem,
  QueueResponse,
} from "./queue-shape";
export type { ScoreboardResponse } from "./scoreboard-shape";
import type { Band, QueueResponse } from "./queue-shape";
import type { ScoreboardResponse } from "./scoreboard-shape";

export const API_URL = process.env.DOUG_API_URL ?? "http://localhost:8000";

type QueueResult = { queue: QueueResponse; source: "live" | "fixture" };
type ScoreboardResult = { scoreboard: ScoreboardResponse; source: "live" | "fixture" };

type Sourced<T> = { value: T; source: "live" | "fixture" };

// A fixture result is kept only briefly so recovery from an outage is quick.
const FIXTURE_TTL_MS = 5_000;

// One fetcher for every public showcase endpoint, so the tuning below stays
// in one place: the queue and scoreboard pages must degrade identically
// under the same outage, and a fix that lands on only one of two copies is
// how they wouldn't.
//
// The endpoints are unauthenticated and pinned to one repo by the API's own
// DOUG_SHOWCASE_REPO. doug-web sends no credential and no repo selector,
// which is what lets this service hold no operator token.
//
// Per-instance micro-cache. Deliberately not ISR/`next.revalidate`: caching
// the route would bake the build-time fixture into the prerender and brand
// the page "sample data" after every cold start. This keeps rendering
// dynamic while a traffic burst (the marketing page getting linked) hits
// the API a couple of times a minute instead of once per visitor.
// Concurrent misses share one in-flight fetch.
function cachedShowcaseFetch<T>(
  path: string,
  guard: (body: unknown) => body is T,
  fallback: T,
): (opts?: { maxAgeMs?: number }) => Promise<Sourced<T>> {
  let inflight: Promise<Sourced<T>> | null = null;
  let last: { at: number; value: Sourced<T> } | null = null;

  async function fetchOnce(): Promise<Sourced<T>> {
    try {
      const res = await fetch(`${API_URL}${path}`, {
        cache: "no-store",
        // 5s, up from 2s: a cold doug-web calling a cold doug-api overran 2s
        // and served the fixture to the first visitor after every
        // scale-to-zero. A rare slow first paint beats invented data.
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        const body: unknown = await res.json();
        if (guard(body)) return { value: body, source: "live" };
      }
    } catch {
      // API down or unreachable — the bundled fixture keeps the page alive.
    }
    return { value: fallback, source: "fixture" };
  }

  return async (opts = {}) => {
    const maxAge = opts.maxAgeMs ?? 0;
    if (last) {
      const ttl = last.value.source === "live" ? maxAge : Math.min(maxAge, FIXTURE_TTL_MS);
      if (Date.now() - last.at < ttl) return last.value;
    }
    if (!inflight) {
      inflight = fetchOnce().then((value) => {
        last = { at: Date.now(), value };
        inflight = null;
        return value;
      });
    }
    return inflight;
  };
}

const cachedQueue = cachedShowcaseFetch(
  "/v1/showcase/queue",
  isQueueResponse,
  fixture as QueueResponse,
);
const cachedScoreboard = cachedShowcaseFetch(
  "/v1/showcase/scoreboard",
  isScoreboardResponse,
  scoreboardFixture as ScoreboardResponse,
);

export async function getQueue(
  opts: { maxAgeMs?: number } = {},
): Promise<QueueResult> {
  const { value, source } = await cachedQueue(opts);
  return { queue: value, source };
}

export async function getScoreboard(
  opts: { maxAgeMs?: number } = {},
): Promise<ScoreboardResult> {
  const { value, source } = await cachedScoreboard(opts);
  return { scoreboard: value, source };
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
