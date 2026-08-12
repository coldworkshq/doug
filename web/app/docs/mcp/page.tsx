import { CodeBlock, Comment, Dim, Fn, Hot, Ok, Str } from "@/components/docs/code-block";
import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { ParamsTable } from "@/components/docs/params-table";
import { DocsPageHeader, H2, P } from "@/components/docs/prose";

export const metadata = {
  title: "MCP · Pattern Garden — Doug Documentation",
  description:
    "The Pattern Garden: an MCP server that serves outcome-anchored code patterns to an agent before it writes.",
};

export default function McpPatternGardenPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader
              kicker="Coming up"
              title="MCP · Pattern Garden"
              status="preview"
            >
              <i>In training.</i> The Pattern Garden is an MCP server your
              coding agent queries{" "}
              <b className="font-semibold text-foreground">before it writes</b>.
              It serves{" "}
              <b className="font-semibold text-foreground">
                outcome-anchored patterns
              </b>{" "}
              distilled from public-repo history: for a given problem shape,
              the solution variants people actually write — each carrying its
              revert record, its survival record, and citations to real PRs.
            </DocsPageHeader>

            <P>
              Base models trained on public code learned what&rsquo;s{" "}
              <i>common</i>. The garden knows what&rsquo;s <i>fit</i>, because
              every pattern is joined to what production did next. Frequency
              isn&rsquo;t fitness.
            </P>

            <H2>Planned tools</H2>
            <ParamsTable
              rows={[
                {
                  name: "doug.ask",
                  meta: "tool · preview",
                  description: (
                    <>
                      Describe the change you&rsquo;re about to make; get known
                      variants ranked by outcome evidence, with failure modes
                      and citations.
                    </>
                  ),
                },
                {
                  name: "doug.check",
                  meta: "tool · planned",
                  description:
                    "Submit a draft diff; get back any losing-variant matches with the cross-repo record attached.",
                },
              ]}
            />

            <div className="mt-6">
              <Callout lead="Status, honestly:">
                The garden is gated on our own evidence bar — patterns ship
                only after their outcome deltas replicate across repos. First
                domain: schema migrations. No dates promised until the probes
                pass.
              </Callout>
            </div>
          </>
        }
        rail={
          <CodeBlock title="MCP · PREVIEW">
            <Fn>doug.ask</Fn>
            {"("}
            <Str>&quot;backfill a NOT NULL column on a hot table&quot;</Str>
            {")"}
            {"\n\n"}
            <Comment>→ 2 variants known · 412 episodes · 87 repos</Comment>
            {"\n"}
            <Ok>✓ dual-write → backfill → enforce</Ok>
            {"\n  "}
            <Dim>survives 3.1yr median under churn · 289 receipts</Dim>
            {"\n"}
            <Hot>✗ single-pass ALTER + backfill</Hot>
            {"\n  "}
            <Dim>{"reverted 31/123 · lock storms on >10M rows"}</Dim>
            {"\n\n"}
            <Comment>
              {"→ failure modes: lock timeout · replica lag\n→ citations: sentry#38112 · grafana#71204 · +29"}
            </Comment>
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/mcp" />
    </>
  );
}
