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

/** Structural check on exactly the fields the pages dereference. A 200
 *  with a drifted body used to be cast straight through and threw deep in
 *  server rendering — with no boundary to catch it, one renamed backend
 *  field took both routes down to Next's unstyled default error page. A
 *  body that fails this check is treated like an unreachable API.
 *
 *  This lives apart from api.ts on purpose: api.ts imports a JSON fixture,
 *  and a node test importing that module trips ESM's JSON import
 *  attributes. Keep it standalone so it stays directly testable. */
export function isQueueResponse(data: unknown): data is QueueResponse {
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
