import Link from "next/link";

import { StatusBadge } from "@/components/docs/badge";
import { Bright, CodeBlock, Comment, Dim, Fn, Str } from "@/components/docs/code-block";
import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { DocsPageHeader, P } from "@/components/docs/prose";

export const metadata = {
  title: "Doug Documentation",
  description:
    "Doug is risk-routed code review: most PRs clear, a handful need a human, and the miss rate will be published on a locked cadence.",
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
                He scores every pull request, clears the majority, and routes
                the risky few to a human — with evidence attached. Every
                merge starts a clock against this repo&rsquo;s reverts. He
                never blocks a merge.
              </P>
              <P>
                Watch Doug score its own pull requests on the{" "}
                <Link href="/queue" className="underline underline-offset-4">
                  queue
                </Link>
                , read the empty{" "}
                <Link
                  href="/scoreboard"
                  className="underline underline-offset-4"
                >
                  scoreboard
                </Link>{" "}
                (the counters are the product until the first window closes),
                and install the GitHub App. The self-serve measurement tool is
                still the{" "}
                <b className="font-semibold text-foreground">
                  backtest CLI
                </b>
                : replay your repo&rsquo;s merged history, label
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
