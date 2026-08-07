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

/** Live query string for client URL writers. Prefer this over a possibly
 *  stale useSearchParams snapshot when mixing pushState updates. */
export function currentSearchParams(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams();
  return new URLSearchParams(window.location.search);
}

/** Build a same-page href with `run` set or cleared, preserving other params. */
export function runHref(id: number | null, base?: URLSearchParams): string {
  const params = new URLSearchParams(base ?? currentSearchParams());
  applyRunParam(params, id);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}
