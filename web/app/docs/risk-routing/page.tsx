import { Bright, CodeBlock, Comment, Hot, Ok } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { DocsPageHeader, P, UL } from "@/components/docs/prose";

export const metadata = {
  title: "Risk routing — Doug Documentation",
  description:
    "How Doug's capture curve, learned hotspots, and the mandatory size-only baseline work.",
};

export default function RiskRoutingPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader
              kicker="Concepts"
              title="Risk routing"
              status="available"
            >
              Doug&rsquo;s core claim is a{" "}
              <b className="font-semibold text-foreground">capture curve</b>:
              reading only the top-scored <i>N</i>% of PRs (the
              &ldquo;budget&rdquo;), what share of defect-inducing PRs land
              inside that band?
            </DocsPageHeader>

            <P>
              Scoring is{" "}
              <b className="font-semibold text-foreground">deterministic</b> —
              no model in the hot path, nothing leaves your machine. The signal
              that carries most of the weight is{" "}
              <b className="font-semibold text-foreground">learned hotspots</b>
              : path segments where your repo&rsquo;s own past defects cluster.
              On sentry, PRs touching learned hotspots revert at{" "}
              <b className="font-semibold text-foreground">2.34×</b> the base
              rate; hotspots drift over time, so they&rsquo;re learned from a
              rolling window, not hard-coded.
            </P>

            <UL>
              <li>
                <b className="font-semibold text-foreground">capture@budget</b>{" "}
                — headline routing metric: % of defect PRs caught at a given
                flag rate
              </li>
              <li>
                <b className="font-semibold text-foreground">AUC</b> —
                budget-independent summary across all flag rates
              </li>
              <li>
                <b className="font-semibold text-foreground">
                  size-only baseline
                </b>{" "}
                — every report shows it; if Doug can&rsquo;t beat
                &ldquo;biggest diff first,&rdquo; you should not pay for Doug
              </li>
            </UL>
          </>
        }
        rail={
          <CodeBlock title="Per-rule precision (sentry, train half)">
            <Bright>{"rule                    fired   hit   lift"}</Bright>
            {"\n"}
            {"hotspot_path              581    19  "}
            <Ok>2.34x</Ok>
            {"\n"}
            {"refactor_pure_mod         332     9  1.94x"}
            {"\n"}
            {"deletion_leaning          214     4  "}
            <Hot>0.82x</Hot>
            {"  "}
            <Comment># dead — kept honest</Comment>
            {"\n\n"}
            <Comment>
              {"# every rule ships with its receipts;"}
              {"\n"}
              {"# rules that don't pay get reported, not hidden"}
            </Comment>
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/risk-routing" />
    </>
  );
}
