import type {
  ReceiptMerge,
  ReceiptPreregistration,
  ReceiptWindow,
} from "./receipt-shape";

export type OutcomeTone = "clear" | "flag" | "neutral";

/** §6.2 keeps two vocabularies apart and so does this: `status` is the JOB's
 *  (pending | running | done | failed), `kind` is the ADJUDICATION's
 *  (revert | clean | censored). A null `kind` means the window is still open
 *  or the job never completed — which is not a clean result and is never
 *  substituted with one.
 *
 *  The tone mapping is the rule ruled in the two-lane plan and shipped in #93:
 *  `clean` → clear, `censored` → NEUTRAL, any other non-null → flag, null →
 *  neutral. `censored` is an UNOBSERVED outcome; painting it in the miss
 *  colour reports a non-observation as a miss.
 *
 *  KNOWN LATENT CASE: `store.py:126-129` documents that `outcomes.kind` is
 *  wide enough to hold `hotfix` — "permitted, not produced", and explicitly
 *  NOT a miss. Nothing writes it today (prereg §10 says it is deliberately
 *  never written), so the default branch never sees it. If that ever changes,
 *  `hotfix` would land in `flag` and repeat #93's error on a new value. Add
 *  its branch at the same time as its writer, not before — an unreachable
 *  branch is untestable, and this comment is the reminder. */
export function windowOutcome(w: Pick<ReceiptWindow, "status" | "kind">): {
  text: string;
  tone: OutcomeTone;
} {
  if (w.kind === null) return { text: w.status, tone: "neutral" };
  if (w.kind === "clean") return { text: "clean", tone: "clear" };
  if (w.kind === "censored") return { text: "censored", tone: "neutral" };
  return { text: w.kind, tone: "flag" };
}

/** Which methodology document governs this window.
 *
 *  A window's own stamp is authoritative for it forever. Reprinting the
 *  in-force hash over an already-adjudicated window would manufacture a
 *  confident-but-derived claim about which document actually governed it —
 *  the one thing the receipt design exists to prevent. A pending window has
 *  no stamp, so it names what WILL govern it, in those words. */
export function windowPreregLine(
  w: Pick<ReceiptWindow, "prereg_hash">,
  inForce: ReceiptPreregistration,
): string {
  if (w.prereg_hash !== null) return `${w.prereg_hash} · stamped at adjudication`;
  if (!inForce.in_force || inForce.hash === null) return "no pre-registration in force";
  return `${inForce.hash} · will govern this window`;
}

/** A merged PR with no governing verdict says so. Falling back to
 *  `latest_verdict` here would claim advice was standing at a merge it was
 *  not standing at. */
export function governingLine(
  merge: Pick<ReceiptMerge, "governing_verdict" | "publication_note">,
): string {
  if (merge.governing_verdict === null) {
    return merge.publication_note || "no governing verdict at this merge";
  }
  return merge.publication_note;
}

/** Null on merges recorded before migration 008, and on any payload carrying
 *  no `pull_request.head` (a deleted fork branch). Never inferred. */
export function mergedHeadLine(merge: Pick<ReceiptMerge, "merged_head_sha">): string {
  return merge.merged_head_sha ?? "not recorded";
}

/** A PR can carry several merges — `uq_outcome_job` includes
 *  `merge_commit_sha`, and revert-and-reland is the ordinary case. Exactly one
 *  is publication-governing. Every merge renders; this caption is what stops a
 *  non-governing one from reading as though it were the record, and what stops
 *  the page from quietly showing only one.
 *
 *  Silent above a single merge: there is nothing to disambiguate, and a
 *  "governs" badge on the only merge present would imply a choice was made. */
export function mergeCaption(
  merge: Pick<ReceiptMerge, "publication_governing" | "publication_note">,
  totalMerges: number,
): string {
  if (totalMerges <= 1) return "";
  const role = merge.publication_governing
    ? "governs the published record"
    : "not the governing merge";
  return merge.publication_note ? `${role} — ${merge.publication_note}` : role;
}
