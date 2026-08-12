import { Bright, CodeBlock, Comment, Ok } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { DocsPageHeader, IC, P, UL } from "@/components/docs/prose";

export const metadata = {
  title: "The cleared band — Doug Documentation",
  description:
    "The cleared band is Doug's real sales claim: defect density among the PRs he clears, not the ones he flags.",
};

export default function ClearedBandPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader
              kicker="Concepts"
              title="The cleared band"
              status="available"
            >
              Capture describes the flagged band. The product actually sells
              the{" "}
              <b className="font-semibold text-foreground">other one</b>:
              &ldquo;auto-merge what Doug cleared&rdquo; is a claim about
              defect density <i>among cleared PRs</i>.
            </DocsPageHeader>

            <P>
              The report&rsquo;s cleared-band table answers it directly: at
              each budget, how many PRs were cleared, how many defects slipped
              through (the{" "}
              <b className="font-semibold text-foreground">miss rate</b>), and
              the cleared band&rsquo;s defect density versus merging blind —{" "}
              <b className="font-semibold text-foreground">density_lift</b>.
            </P>

            <UL>
              <li>
                <IC>density_lift &lt; 1</IC> — clearing carries information;
                cleared PRs are safer than average
              </li>
              <li>
                <IC>density_lift = 1</IC> — Doug&rsquo;s clearance is
                worthless; you&rsquo;re merging blind
              </li>
            </UL>

            <P>
              This is the trust product&rsquo;s headline metric, the way
              capture@budget is the routing product&rsquo;s. It&rsquo;s also
              the number that decides whether an auto-merge claim would be
              honest at a given budget — and at tight budgets, today, it
              wouldn&rsquo;t be. We say so.
            </P>
          </>
        }
        rail={
          <CodeBlock title="CLEARED BAND (SHAPE)">
            <Bright> flag  cleared  missed  miss rate  vs base</Bright>
            {"\n"}
            {"  10%    4,500    ~58       86%      0.96x\n"}
            {"  20%    4,000    ~43       64%      0.80x\n"}
            {"  30%    3,500    ~29       43%     "}
            <Ok> 0.61x</Ok>
            {"\n\n"}
            <Comment>
              {"# reading: at a 30% budget the cleared band\n"}
              {"# carries 0.61× the blind-merge defect density.\n"}
              {"# honest, not yet publishable — n is small."}
            </Comment>
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/cleared-band" />
    </>
  );
}
