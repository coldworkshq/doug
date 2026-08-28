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
                Just under a third of prospective findings are disproved by
                code he wasn&rsquo;t shown
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
                Backfill was reconstructed from write-ups after the fact
                and is excluded from every rate by construction; the
                denominator is the prospective rows, scoped to one
                repository and one instrument, because a rate computed
                across two of either describes neither. The counts beside this paragraph are a{" "}
                <b className="font-semibold text-foreground">
                  dated snapshot, not a live counter
                </b>
                &nbsp;— the log grows every time a finding is settled, and a
                number printed here cannot follow it. Read the current one off
                the log yourself; it ships in the repo and the command is in
                the panel. When there is a rate, it will not be called
                precision: whether a finding is <i>true</i> is a different
                quantity from whether it <i>predicted a defect</i>, and a
                finding can be true and worthless or false and load-bearing.
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
              {"# as of 2026-08-27 — a snapshot, not a\n#   counter. 205 rows; 193 prospective,\n#   12 backfill excluded from every rate.\n#   The reader on doug is 176 of those:\n#   54 disproved, 85 real, 37 adjacent.\n#   The plan lane writes here too, in its\n#   own vocabulary, and is not in that\n#   figure.\n\n# today's number, from the log itself:\n# python -m doug.findings_log rate \\\n#     --repo doug --rule-prefix reader:"}
            </Comment>
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/what-doug-gets-wrong" />
    </>
  );
}
