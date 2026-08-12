import { Bright, CodeBlock, Comment, Str } from "@/components/docs/code-block";
import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { DocsPageHeader, P, UL } from "@/components/docs/prose";

export const metadata = {
  title: "What Doug gets wrong — Doug Documentation",
  description:
    "Doug reviews his own pull requests, and the team logs what he got wrong — disposition, not just a tally.",
};

export default function WhatDougGetsWrongPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader
              kicker="Honesty"
              title="What Doug gets wrong"
              status="available"
            >
              Doug reviews every pull request in his own repository, and we
              write down what he got wrong.{" "}
              <b className="font-semibold text-foreground">
                Roughly half his findings are disproved by code he wasn&rsquo;t
                shown
              </b>{" "}
              — he reads a diff, not a repository, and he does not reliably
              distinguish what the diff <i>proves</i> from what it merely{" "}
              <i>permits</i>.
            </DocsPageHeader>

            <P>Two failure classes recur often enough to have names:</P>
            <UL>
              <li>
                <b className="font-semibold text-foreground">
                  A conclusion drawn from an absence in the diff.
                </b>{" "}
                “This name is used and no import was added” — when the import
                was already there, three files away.
              </li>
              <li>
                <b className="font-semibold text-foreground">
                  Re-reporting a tradeoff the code already documents
                </b>
                , as though it were news.
              </li>
            </UL>

            <P>
              The first one produced a rule worth more than the bug it came
              from:{" "}
              <b className="font-semibold text-foreground">
                a claim about an absence cannot be settled by looking at the
                same place the claim came from.
              </b>{" "}
              “No import was added” is a fact about the diff; whether the import
              exists is a fact about the repo. Re-reading the diff confirms the
              finding every time and proves nothing — the check and the error
              are the same observation. In that particular case the linter had
              already answered it, green, before Doug ever spoke.
            </P>

            <P>
              So every finding now gets a line at disposition time: was it{" "}
              <b className="font-semibold text-foreground">real</b>,{" "}
              <b className="font-semibold text-foreground">disproved</b>, or{" "}
              <b className="font-semibold text-foreground">adjacent</b> — wrong
              as stated, right about something nearby — and separately, did
              anything in the codebase actually change because of it.
            </P>

            <P>
              Two axes, deliberately, because one column loses the cases that
              matter. A true finding that changed nothing is a re-report of
              something the code already says. A false finding that changed
              something found a real gap by the wrong route. Doug&rsquo;s
              strongest mode is <i>“this code does not justify itself”</i> — and
              a single score would grade that as failure.
            </P>

            <div className="mt-6">
              <Callout lead="There is no rate here yet, and that is the point.">
                Every row in the log today is backfilled — reconstructed from
                write-ups after the fact, not recorded at the time — so every
                one of them is excluded from every rate by construction. The
                denominator starts at the first finding logged prospectively.
                When there is a number, it will not be called precision: whether
                a finding is <i>true</i> is a different quantity from whether it{" "}
                <i>predicted a defect</i>, and a finding can be true and
                worthless or false and load-bearing.
              </Callout>
            </div>
          </>
        }
        rail={
          <CodeBlock title="FINDINGS LOG · ONE LINE PER FINDING">
            <Bright>{"{"}</Bright>
            <Str>&quot;pr&quot;</Str>
            {": 28,\n "}
            <Str>&quot;rule&quot;</Str>
            {": "}
            <Str>&quot;reader:missing-import&quot;</Str>
            {",\n "}
            <Str>&quot;verdict&quot;</Str>
            {": "}
            <Str>&quot;disproved&quot;</Str>
            {",\n "}
            <Str>&quot;changed&quot;</Str>
            {": false,\n "}
            <Str>&quot;settled_by&quot;</Str>
            {": "}
            <Str>
              {'"api/doug/api.py:7 —\n   already imported; ruff F821 was\n   green before the finding"'}
            </Str>
            <Bright>{"}"}</Bright>
            {"\n\n"}
            <Comment>
              {"# 12 rows today, every one backfill:\n#   9 disproved · 2 adjacent · 1 real\n#\n# excluded from every rate.\n# the denominator starts at row 13."}
            </Comment>
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/what-doug-gets-wrong" />
    </>
  );
}
