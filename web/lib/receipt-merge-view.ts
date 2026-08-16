import { outcomeTone } from "./dashboard-model";
import type {
  ReceiptMerge,
  ReceiptPreregistration,
  ReceiptWindow,
} from "./receipt-shape";
// The union is declared once, in `runs-time.ts`, beside `outcomeToneClass`
// which consumes it. A second identical declaration here typechecked and
// exported cleanly — structural typing makes the two interchangeable — which
// is exactly why nothing would have caught the day one of them widened.
import type { OutcomeTone } from "./runs-time";

/** §6.2 keeps two vocabularies apart and so does this: `status` is the JOB's
 *  (pending | running | done | failed), `kind` is the ADJUDICATION's
 *  (revert | clean | censored). A null `kind` means the window is still open
 *  or the job never completed — which is not a clean result and is never
 *  substituted with one. That WORD is this function's own decision; the TONE
 *  is not.
 *
 *  The tone mapping is the rule ruled in the two-lane plan and shipped in #93:
 *  `clean` → clear, `censored` → NEUTRAL, any other non-null → flag, null →
 *  neutral. `censored` is an UNOBSERVED outcome; painting it in the miss
 *  colour reports a non-observation as a miss.
 *
 *  That rule is NOT reimplemented here. It lives in `outcomeTone`
 *  (dashboard-model.ts), which `outcome-tone-parity.test.mjs` holds against
 *  console's copy over the whole vocabulary — and a third copy would have been
 *  tied to neither, so a future edit to the shared rule would have left this
 *  receipt behind, showing one colour for `censored` on the ledger and another
 *  on the receipt for the same row. `kind` is `string | null`, exactly
 *  `outcomeTone`'s parameter, and its branches are the four above; the
 *  delegation is behaviour-preserving on every input this function can see.
 *
 *  KNOWN LATENT CASE: `store.py:126-129` documents that `outcomes.kind` is
 *  wide enough to hold `hotfix` — "permitted, not produced", and explicitly
 *  NOT a miss. Nothing writes it today (prereg §10 says it is deliberately
 *  never written), so the default branch never sees it. If that ever changes,
 *  `hotfix` would land in `flag` and repeat #93's error on a new value. Add
 *  its branch at the same time as its writer, not before — an unreachable
 *  branch is untestable, and this comment is the reminder. Delegating makes
 *  that a ONE-place fix that this surface inherits, rather than a fourth site
 *  someone has to remember. */
export function windowOutcome(w: Pick<ReceiptWindow, "status" | "kind">): {
  text: string;
  tone: OutcomeTone;
} {
  // The job's status when there is no adjudication word to print, the
  // adjudication's own word otherwise. Never a substitute for either.
  return { text: w.kind ?? w.status, tone: outcomeTone(w.kind) };
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

/** A merged PR with no governing verdict says so — UNCONDITIONALLY, and in
 *  those words. Falling back to `latest_verdict` here would claim advice was
 *  standing at a merge it was not standing at.
 *
 *  `publication_note` is not an acceptable substitute for that sentence, and
 *  the `merge.publication_note || …` this replaces never actually reached the
 *  sentence at all. The API sends one of exactly two NON-EMPTY constants
 *  (`api.py:744-753`), chosen by `publication_governing` alone and never by
 *  whether a governing verdict exists — so the fallback was unreachable and a
 *  merge with `governing_verdict: null` rendered the note verbatim. Under the
 *  label `governing`, with no verdict rendered beside it, the non-governing
 *  constant then read "The verdict shown here is historical context — what was
 *  standing when THIS commit merged": the page asserting a verdict was
 *  standing where the store says none was. `store.py:1795-1797` puts exactly
 *  that PR in the pre-registration's §2.4 EXCLUDED bucket, and
 *  `api/tests/test_receipts.py`'s
 *  test_merged_pr_without_a_reader_verdict_reports_null_governing produces the
 *  payload, so this was reachable, not theoretical. Same defect #93 and
 *  `09ab52b` each fixed once; this is its last hiding place.
 *
 *  The merge's ROLE is not lost with the note: `mergeCaption` names it
 *  ("governs the published record" / "not the governing merge") wherever there
 *  is more than one merge to disambiguate. */
export function governingLine(
  merge: Pick<ReceiptMerge, "governing_verdict" | "publication_note">,
): string {
  if (merge.governing_verdict === null) return "no governing verdict at this merge";
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
  // The ROLE only. `governingLine` already renders `publication_note`, and a
  // page that calls both would print the same sentence twice per merge.
  return merge.publication_governing
    ? "governs the published record"
    : "not the governing merge";
}
