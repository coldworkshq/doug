import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { ParamsTable } from "@/components/docs/params-table";
import { DocsPageHeader, IC } from "@/components/docs/prose";

export const metadata = {
  title: "Changelog — Doug Documentation",
  description:
    "Dated record of what shipped, what was measured, and one design that was reviewed and cut.",
};

export default function ChangelogPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader kicker="Meta" title="Changelog" />

            <ParamsTable
              rows={[
                {
                  name: "2026-08-23",
                  description: (
                    <>
                      Settings get a page. <IC>/dashboard/settings</IC> lists
                      every connected repository with its flag line, its PR
                      comment toggle and a new deep read toggle, and the site
                      header links to the dashboard. Deep read off means Doug
                      scores that repository on structural signals alone — no
                      diff leaves it. On a repository with no flag line of its
                      own that also moves the line Doug bands against, from the
                      deep-read default to the fallback one, so it asks for a
                      human less often rather than merely differently.
                    </>
                  ),
                },
                {
                  name: "2026-08-23",
                  description: (
                    <>
                      The reader reads harder and spends less doing it. Its
                      reasoning effort goes to <IC>high</IC>, and the two
                      mechanical passes behind it — the one that checks a
                      finding against the file it cites, and the one that
                      places a finding on a hunk — move to a cheaper model
                      than the frozen reader (ADR-0016, ADR-0018). Grounding
                      switches on for one named installation rather than for
                      everyone at once (ADR-0017).
                    </>
                  ),
                },
                {
                  name: "2026-08-21",
                  description: (
                    <>
                      Doug stops forgetting what he already said. When the
                      code a finding cited is byte-unchanged in the next
                      push, he carries that finding forward by construction
                      and reports it under{" "}
                      <IC>### Since &lt;sha&gt;</IC>, with a count of how many
                      of his own earlier findings on untouched code he did not
                      mention again. Nothing is ever marked{" "}
                      <em>resolved</em>: evidence that code was edited is not
                      evidence it was fixed, and a sampled hand-check said so
                      before this shipped.
                    </>
                  ),
                },
                {
                  name: "2026-08-20",
                  description: (
                    <>
                      The sticky PR comment finishes rolling out. It is on for
                      every repository Doug reviews, and the per-repository
                      toggle beside the flag line is the only thing that turns
                      it off.
                    </>
                  ),
                },
                {
                  name: "2026-08-19",
                  description: (
                    <>
                      Doug leaves one sticky comment on each reviewed PR that
                      repeats its check run word for word, edited in place on
                      every push — on by default, opt-out per repository
                      beside the flag line.
                    </>
                  ),
                },
                {
                  name: "2026-08-13",
                  description: (
                    <>
                      The outcome instrument is visible. Every check run
                      ends with{" "}
                      <IC>adjudicated N · pending M · as of &lt;date&gt;</IC>{" "}
                      and a deep-read meter; the public{" "}
                      <IC>/scoreboard</IC> page shows the same counters from
                      the same query, empty and dated. Bot-authored PRs no
                      longer buy a deep read. Hosted <IC>/docs</IC> actually
                      serves — Cloud Build had been stripping it. Finding{" "}
                      <IC>file</IC> is carried on the Reason rather than
                      rematched by description.
                    </>
                  ),
                },
                {
                  name: "2026-08-12",
                  description: (
                    <>
                      Dashboard rebuilt on the console&rsquo;s design grammar:
                      a bounded table, a threshold view lens, a larger type
                      scale, a space picker that navigates on selection.
                      Floating header with separated sign-in. Hosted docs
                      section.
                    </>
                  ),
                },
                {
                  name: "2026-08",
                  description: (
                    <>
                      Doug&rsquo;s own findings now get a durable disposition —
                      real / disproved / adjacent, plus whether anything changed
                      and which file settled it (
                      <IC>docs/findings-log.jsonl</IC>). Every row at the
                      time was backfill and excluded from every rate; the
                      prospective denominator opened later. A design for an
                      agent review crew with a falsifier-adjudicated ledger was
                      put through six independent reviewers and <em>cut</em>:
                      four of six proposed &ldquo;agent lenses&rdquo; turned out
                      to be checks that already run or free platform features,
                      and the ledger&rsquo;s own motivating case — a finding
                      that draws a conclusion from an absence in the diff — is
                      one its mechanism could not have fixed, because the
                      obvious falsifier restates the error. What survived is the
                      log and one reviewing rule.
                    </>
                  ),
                },
                {
                  name: "2026-07",
                  description: (
                    <>
                      Phase-1 entry experiments, pre-registered end to end.
                      RandomForest on Kamei&rsquo;s 14 confirms the metadata
                      ceiling (a plain size sort still wins). An LLM diff-read
                      probe out-ranks every deterministic baseline on{" "}
                      <em>both</em> repos — AUC 0.69 sentry / 0.67 grafana, the
                      first method here that held up on repo #2 — and survives a
                      polarity-inversion counterfactual (findings track change
                      semantics, not diff surface). Finding-pattern
                      distillation: marginal pass on sentry, coverage fail on
                      grafana. Scripts: <IC>api/scripts/rf_kamei.py</IC>,{" "}
                      <IC>api/scripts/llm_probe.py</IC>.
                    </>
                  ),
                },
                {
                  name: "2026-07",
                  description: (
                    <>
                      Backtest hardening: checkpoint/resume harvests, cache
                      seeding, listing dedupe, <IC>--backfill-details</IC>{" "}
                      (per-file stats + patch text). Cleared-band metric
                      shipped. Rolling-window hotspot learning built; verdict
                      pending deeper history. This docs site.
                    </>
                  ),
                },
                {
                  name: "2026-07",
                  description:
                    "Renamed to Doug (after a Saint Bernard). Landing page live. Replays published for sentry, grafana, ruff.",
                },
              ]}
            />
          </>
        }
      />
      <DocsPager currentHref="/docs/changelog" />
    </>
  );
}
