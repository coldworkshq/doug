export interface ScoreboardResponse {
  repo: string;
  adjudicated: number;
  pending: number;
  as_of: string;
  first_due: string | null;
  deep_reads: number | null;
  deep_read_cap: number;
  miss_rate: null;
  decidable: false;
  label: string;
}

/** Structural check on exactly the fields the scoreboard page dereferences.
 *  A 200 that claimed a miss rate or decidable=true would be a confident
 *  false claim — reject it the same way an unreachable API is rejected.
 *
 *  Lives apart from api.ts so a node test can import it without the JSON
 *  fixture that trips ESM import attributes. */
export function isScoreboardResponse(data: unknown): data is ScoreboardResponse {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.repo === "string" &&
    typeof d.adjudicated === "number" &&
    typeof d.pending === "number" &&
    typeof d.as_of === "string" &&
    (d.first_due === null || typeof d.first_due === "string") &&
    (d.deep_reads === null || typeof d.deep_reads === "number") &&
    typeof d.deep_read_cap === "number" &&
    d.miss_rate === null &&
    d.decidable === false &&
    typeof d.label === "string" &&
    d.label.length > 0
  );
}
