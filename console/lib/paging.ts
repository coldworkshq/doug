/** Client-side page over an already-fetched list. 1-based pages. */

export const DEFAULT_PAGE_SIZE = 50;

export interface PageWindow<T> {
  items: T[];
  page: number;
  pageSize: number;
  pageCount: number;
  total: number;
  /** 1-based inclusive index of the first item on this page, or 0 when empty. */
  from: number;
  /** 1-based inclusive index of the last item on this page, or 0 when empty. */
  to: number;
}

/** Parse a URL `page` value. Non-positive / non-integer / missing → 1. */
export function parsePage(raw: string | null | undefined): number {
  if (raw === null || raw === undefined || raw.trim() === "") return 1;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1) return 1;
  return n;
}

/** Clamp `page` into `[1, pageCount]` (pageCount is at least 1). */
export function pageSlice<T>(
  items: readonly T[],
  page: number,
  pageSize: number = DEFAULT_PAGE_SIZE,
): PageWindow<T> {
  const size = pageSize < 1 ? DEFAULT_PAGE_SIZE : pageSize;
  const total = items.length;
  const pageCount = Math.max(1, Math.ceil(total / size) || 1);
  const safePage = Math.min(Math.max(1, page), pageCount);
  const start = (safePage - 1) * size;
  const sliced = items.slice(start, start + size);
  if (total === 0) {
    return {
      items: [],
      page: 1,
      pageSize: size,
      pageCount: 1,
      total: 0,
      from: 0,
      to: 0,
    };
  }
  return {
    items: sliced,
    page: safePage,
    pageSize: size,
    pageCount,
    total,
    from: start + 1,
    to: start + sliced.length,
  };
}

export function pageRangeLabel(window: PageWindow<unknown>): string {
  if (window.total === 0) return "0 of 0";
  return `${window.from}–${window.to} of ${window.total}`;
}
