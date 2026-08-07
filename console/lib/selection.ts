export const RUN_PARAM = "run";

/** Positive integer verdict ids only. Blank, zero, negative, and non-integers
 *  are "no selection" — never coerce them into a fetch. */
export function parseRunId(raw: string | null | undefined): number | null {
  if (raw == null) return null;
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  if (!/^\d+$/.test(trimmed)) return null;
  const id = Number(trimmed);
  if (!Number.isInteger(id) || id < 1) return null;
  return id;
}

export function applyRunParam(params: URLSearchParams, id: number | null): void {
  if (id === null) params.delete(RUN_PARAM);
  else params.set(RUN_PARAM, String(id));
}
