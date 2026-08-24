import { utcTimestamp } from "@/lib/runs-time";

/** D8. The PR-comment toggle says "on"; this says whether anything is actually
 *  landing. Without it the failure mode is a setting that reads on, a comment
 *  that never appears, and a stderr line in a project with no alerting — the
 *  operator's only evidence being an absence they would have to go looking for.
 *
 *  ITS OWN FILE because the toggle now has two homes — the repositories table
 *  and /dashboard/settings — and a denial stated on only one of them recreates
 *  exactly the silence this component exists to break. Both surfaces render it
 *  from the same `pr_comment_denied_at`.
 *
 *  It names the USUAL cause and refuses to assert it. GitHub answers 403 for the
 *  App permission never having been re-accepted, for a locked conversation, for
 *  an archived repository and for secondary rate limiting alike; the token names
 *  the code and nothing more, so the banner hedges exactly as far as the
 *  evidence does. Naming one cause with confidence would send someone to the
 *  App settings for a repository they archived last week.
 *
 *  The timestamp is the LAST refusal, not a count: `pr_comment_denied_at` is
 *  cleared by the next successful post, so a stamp here means the most recent
 *  attempt failed — which is the fact worth acting on. */
export function PrCommentDenialBanner({ deniedAt }: { deniedAt: string }) {
  return (
    <div className="mono mb-2.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-[5px] border border-[var(--flag)] px-3 py-1.5 text-[11px] text-foreground">
      <span className="font-medium data-flag">PR comments are not posting</span>
      <span className="text-muted-foreground">
        Doug&apos;s last attempt was refused (403) at{" "}
        <b className="font-medium text-foreground">{utcTimestamp(deniedAt)}</b>. The usual cause is the
        pull-requests write permission not being re-accepted in GitHub; a locked conversation, an
        archived repository, or secondary rate limiting produce the same code.
      </span>
    </div>
  );
}
