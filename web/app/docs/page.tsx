import { StatusBadge } from "@/components/docs/badge";
import { Bright, CodeBlock, Comment, Dim, Fn, Str } from "@/components/docs/code-block";
import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { DocsPageHeader, P } from "@/components/docs/prose";

export const metadata = {
  title: "Doug Documentation",
  description:
    "Doug is risk-routed code review for the agent era: deterministic scoring against your repo's own defect history, with the miss rate published.",
};

export default function DocsIntroductionPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader kicker="Getting started" title="Doug Documentation">
              <P>
                <b className="font-semibold text-foreground">
                  Doug is risk-routed code review for the agent era.
                </b>{" "}
                He scores every pull request deterministically against your
                repository&rsquo;s own defect history, clears the safe
                majority, and routes the risky few to a human — with evidence
                attached. He never blocks a merge.
              </P>
              <P>
                Today the public surface is the{" "}
                <b className="font-semibold text-foreground">backtest CLI</b>:
                replay your repo&rsquo;s merged history, label
                defect-inducing PRs from revert anchors in git, and measure
                exactly what Doug would have caught. The report is the demo —
                and the same numbers we publish for ourselves.
              </P>
            </DocsPageHeader>

            <Callout lead="Early preview.">
              Doug is in active development. Everything marked{" "}
              <StatusBadge status="available" /> works today; things marked{" "}
              <StatusBadge status="preview" /> or <StatusBadge status="planned" />{" "}
              are described so you can see where this is going — not to
              pretend they exist.
            </Callout>
          </>
        }
        rail={
          <CodeBlock title="The shape of Doug">
            <Comment># 1 · replay history, honestly</Comment>
            {"\n"}
            <Bright>doug-backtest</Bright> <Str>your-org/your-repo</Str>
            {"\n\n"}
            <Comment># 2 · route the live queue          [preview]</Comment>
            {"\n"}
            <Dim>62 open → 5 need you · rest cleared w/ receipts</Dim>
            {"\n\n"}
            <Comment># 3 · ask before you write          [in training]</Comment>
            {"\n"}
            <Fn>doug.ask</Fn>
            {"("}
            <Str>&quot;backfill NOT NULL on a hot table&quot;</Str>
            {")"}
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs" />
    </>
  );
}
