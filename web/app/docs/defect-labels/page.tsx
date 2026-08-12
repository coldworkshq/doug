import { Bright, CodeBlock, Comment, Dim, Hot, Str } from "@/components/docs/code-block";
import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { ParamsTable } from "@/components/docs/params-table";
import { DocsPageHeader, H2, IC } from "@/components/docs/prose";

export const metadata = {
  title: "Defect labels — Doug Documentation",
  description:
    "How Doug labels a PR defect-inducing from revert anchors in git and GitHub history.",
};

export default function DefectLabelsPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader
              kicker="Concepts"
              title="Defect labels"
              status="available"
            >
              A backtest is only as honest as its labels. Doug labels a PR{" "}
              <b className="font-semibold text-foreground">defect-inducing</b>{" "}
              when later history reverts it — the revert is an
              engineer&rsquo;s own on-the-record verdict that the change was
              bad.
            </DocsPageHeader>

            <H2>
              Label sources (<IC>--labels</IC>)
            </H2>
            <div className="mt-4">
              <ParamsTable
                rows={[
                  {
                    name: "git",
                    meta: "default",
                    description:
                      "Parse revert anchors out of git history directly. Dense, zero API quota, and reproducible from a clone alone.",
                  },
                  {
                    name: "api",
                    description:
                      'Search GitHub for revert PRs via the API. Sparser but catches reverts that never say "revert" in the commit subject.',
                  },
                  {
                    name: "both",
                    description:
                      "Union of the two. Labels are intersected with the harvested window — no outcome-dependent injection, which would bias the capture numbers.",
                  },
                ]}
              />
            </div>

            <div className="mt-6">
              <Callout lead="Known limits, stated plainly:">
                Reverts under-count defects (hotfixes without reverts are
                missed), and ~6% of git labels on sentry show timestamp
                anomalies we&rsquo;re still triaging. The labels are good
                enough to rank on; we publish their weaknesses along with the
                wins.
              </Callout>
            </div>
          </>
        }
        rail={
          <CodeBlock title="How a label is born">
            <Comment>
              # merged PR #4821 — &quot;migrate retry-queue table&quot;
            </Comment>
            {"\n"}
            <Dim>{"merge  2026-03-02"}</Dim>
            {"  "}
            <Bright>a41f9c2</Bright>
            {"\n\n"}
            <Comment># nine days later:</Comment>
            {"\n"}
            <Dim>{"commit 2026-03-11"}</Dim>
            {"  "}
            <Bright>e77d201</Bright>
            {"\n"}
            <Str>
              &quot;Revert &apos;migrate retry-queue table&apos; (#4821)&quot;
            </Str>
            {"\n\n"}
            <Hot>→ #4821 labeled defect-inducing</Hot>
            {"\n"}
            <Comment># an engineer said so, in the record, at the time</Comment>
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/defect-labels" />
    </>
  );
}
