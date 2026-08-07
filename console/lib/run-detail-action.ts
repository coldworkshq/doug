"use server";

import { getRunDetail, type RunDetail } from "@/lib/api";

/** Server-only detail fetch for client selection (pushState does not re-run
 *  the page). Same honesty contract as getRunDetail — errors are returned,
 *  never fabricated runs. */
export async function loadRunDetail(
  id: number,
): Promise<RunDetail | { error: string }> {
  return getRunDetail(id);
}
