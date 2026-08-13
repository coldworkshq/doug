import type { ReceiptRead, ReceiptResponse, ReceiptVerdict } from "./receipt-shape";

/** What the reader was configured to see.
 *
 *  `recorded` is the API's own AND of both columns, and this function trusts
 *  it rather than re-deriving: a budget with no ordering does not say which
 *  part of the diff the model saw, and an ordering with no budget does not
 *  say how much of it. Quoting either half alone would let a reader cite a
 *  budget nothing was actually read under. */
export function readLine(read: Pick<ReceiptRead, "diff_budget" | "read_order" | "recorded">): string {
  if (!read.recorded) return "not recorded";
  return `${read.diff_budget} chars · ${read.read_order} order`;
}

/** Null means the row predates prompt-hash stamping on the worker path. It is
 *  NOT a match against the frozen prompt and must never render as one. */
export function promptHashLine(verdict: Pick<ReceiptVerdict, "prompt_hash">): string {
  return verdict.prompt_hash ?? "not stamped";
}

/** `latest_verdict` excludes `tier='external'` (`store.py:1786-1798`), and the
 *  reason is not tidiness: `save_external_review` fires on every
 *  `pull_request_review` and writes a row stamped with the human reviewer's
 *  `submitted_at` and 0.0/0.0 score/threshold placeholders, because no model
 *  ran and no diff was read. On a PR approved after Doug's last score that row
 *  is newest and would win the sort. So this is not "the newest verdict on
 *  this PR" — a human approval may well be newer. */
export function latestVerdictCaption(): string {
  return "Doug's most recent score. Excludes external reviews, which carry no read.";
}

export interface VerdictGap {
  latestId: number;
  governingId: number;
  mergeSha: string;
}

/** The gap a reader of an incident review came for: what Doug says NOW versus
 *  what was standing when a human chose to merge. Read from the
 *  publication-governing merge specifically — with several merges, the first
 *  is not necessarily the one that governs. */
export function verdictGap(
  receipt: Pick<ReceiptResponse, "latest_verdict" | "merges">,
): VerdictGap | null {
  const latest = receipt.latest_verdict;
  if (!latest) return null;
  const governingMerge = receipt.merges.find((merge) => merge.publication_governing);
  const governing = governingMerge?.governing_verdict;
  if (!governingMerge || !governing) return null;
  if (governing.verdict_id === latest.verdict_id) return null;
  return {
    latestId: latest.verdict_id,
    governingId: governing.verdict_id,
    mergeSha: governingMerge.merge_commit_sha,
  };
}
