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
                      <IC>docs/findings-log.jsonl</IC>). All rows today are
                      backfill and excluded from every rate. A design for an
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
