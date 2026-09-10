/**
 * The one reader of the registry's read contract.
 *
 * Product reads engine, never the reverse (ADR-0034): this is a runtime
 * fetch of a public JSON document, not an import, and it is the only place
 * in `web/` that names the registry. Everything it can return is one of two
 * shapes, and a page renders exactly one of two things from them: a figure
 * with the sentence the document carried for it, or a chip with a reason.
 *
 * There is deliberately no fixture fallback, unlike `api.ts`'s showcase
 * fetchers. A bundled snapshot would be a figure with no sentence, which is
 * the one thing the contract exists to prevent. Any failure is `unknown`
 * with its reason: the base URL unset, the fetch failing, a non-200, a body
 * the guard rejects, a schema version this build does not know, a document
 * that says it is stale, or one older than its own window when it reaches
 * us.
 *
 * The bearer is unused today. The route is public read; when a per-tenant
 * figure exists (FD5) it moves behind IAM, and the slot is where the token
 * goes so that change is an environment variable, not a signature change.
 */
import { isRegistrySnapshotV1, SCHEMA_VERSION, type RegistrySnapshotV1 } from "./registry-shape";

export const REGISTRY_PATH = "/api/registry/v1/snapshot";

export type RegistryResult =
  | { kind: "snapshot"; snapshot: RegistrySnapshotV1 }
  | { kind: "unknown"; reason: string };

export interface RegistryClientOptions {
  baseUrl: string | undefined;
  bearer?: string | undefined;
  fetchImpl?: typeof fetch;
  now?: () => number;
  timeoutMs?: number;
}

/** Reads one document and decides what it is. Exported for the tests; pages use `getRegistrySnapshot`. */
export async function readRegistrySnapshot(opts: RegistryClientOptions): Promise<RegistryResult> {
  const now = opts.now ?? Date.now;
  const fetchImpl = opts.fetchImpl ?? fetch;
  if (!opts.baseUrl) {
    return { kind: "unknown", reason: "COLDWORKS_REGISTRY_URL is not set; the registry is not connected" };
  }

  let res: Response;
  try {
    const headers: Record<string, string> = { accept: "application/json" };
    if (opts.bearer) headers.authorization = `Bearer ${opts.bearer}`;
    res = await fetchImpl(`${opts.baseUrl.replace(/\/$/, "")}${REGISTRY_PATH}`, {
      cache: "no-store",
      headers,
      signal: AbortSignal.timeout(opts.timeoutMs ?? 5000),
    });
  } catch (error) {
    const name = error instanceof Error ? error.name : "Error";
    return { kind: "unknown", reason: `the registry could not be reached (${name})` };
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    return { kind: "unknown", reason: `the registry answered ${res.status} with a body that is not JSON` };
  }

  // A refusal is the same document with a reason. Read it before the status
  // so the reason the registry gave is the reason the chip shows.
  if (isRegistrySnapshotV1(body) && body.snapshot === null) {
    return { kind: "unknown", reason: body.reason ?? `the registry answered ${res.status} with no snapshot` };
  }
  if (!res.ok) {
    return { kind: "unknown", reason: `the registry answered ${res.status}` };
  }
  if (!isRegistrySnapshotV1(body)) {
    const version =
      typeof body === "object" && body !== null && "schema_version" in body
        ? (body as { schema_version: unknown }).schema_version
        : undefined;
    if (version !== undefined && version !== SCHEMA_VERSION) {
      return {
        kind: "unknown",
        reason: `the registry serves schema_version ${String(version)} and this build reads ${SCHEMA_VERSION}`,
      };
    }
    return { kind: "unknown", reason: "the registry's document did not match the contract this build carries" };
  }
  if (body.stale) {
    return { kind: "unknown", reason: body.reason ?? "the registry reports its snapshot as stale" };
  }
  const generatedAt = Date.parse(body.generated_at ?? "");
  if (!Number.isFinite(generatedAt)) {
    return { kind: "unknown", reason: "the registry's document carries no readable generated_at" };
  }
  const ageSeconds = Math.max(0, (now() - generatedAt) / 1000);
  if (ageSeconds > body.stale_after_seconds) {
    return {
      kind: "unknown",
      reason:
        `the snapshot is ${Math.round(ageSeconds)}s old when read and its window is ` +
        `${body.stale_after_seconds}s; no figure from it is asserted`,
    };
  }
  return { kind: "snapshot", snapshot: body };
}

// Per-instance micro-cache with one shared in-flight read, the shape
// `api.ts` uses for the same reason: a burst of page views should cost the
// registry a couple of reads a minute, not one per visitor, and two panels on
// one page should never disagree about which snapshot they show.
let inflight: Promise<RegistryResult> | null = null;
let last: { at: number; value: RegistryResult } | null = null;

export async function getRegistrySnapshot(opts: { maxAgeMs?: number } = {}): Promise<RegistryResult> {
  const maxAge = opts.maxAgeMs ?? 0;
  if (last && Date.now() - last.at < maxAge) return last.value;
  if (!inflight) {
    inflight = readRegistrySnapshot({
      baseUrl: process.env.COLDWORKS_REGISTRY_URL,
      bearer: process.env.COLDWORKS_REGISTRY_BEARER,
    }).then((value) => {
      last = { at: Date.now(), value };
      inflight = null;
      return value;
    });
  }
  return inflight;
}
