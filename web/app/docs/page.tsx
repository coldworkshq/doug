import Link from "next/link";

import { Chip, StatusBadge } from "@/components/docs/badge";
import { Callout } from "@/components/docs/callout";
import { Card, Cards } from "@/components/docs/cards";
import { Bright, Cmd, CodeBlock, Comment, Dim, Fn, Prompt, Str } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsPageHeader, H2, H3, IC, P } from "@/components/docs/prose";
import { Table } from "@/components/docs/table";
import { AUDIT_PREVIEW_LABEL } from "@/lib/docs-nav";

export const metadata = {
  title: "Coldworks docs",
  description:
    "Documentation for Coldworks: Doug, the risk-routed code reviewer, and the audit that reads your agents' traces on your own machine.",
};

/** The one overview. Doug's introduction and the audit's overview are its
 *  two halves, each under the anchor its sidebar section links to
 *  (lib/docs-nav.ts); /docs/audit redirects to the second. */
export default function DocsOverviewPage() {
  return (
    <>
      <DocsPageHeader kicker="Documentation" title="Use AI to need less AI.">
        Coldworks reviews your pull requests, remembers what your team decided, and turns the
        judgments it keeps repeating into checks you own. These docs cover two parts of it:{" "}
        <b>Doug</b>, the reviewer, and <b>the audit</b>, which reads the traces your agents
        already produce.
      </DocsPageHeader>

      <Cards columns={2}>
        <Card href="/docs#doug-reviews" title="Doug reviews" cta="Read the section">
          Risk-routed code review for the agent era. He scores every pull request, clears the
          majority, and routes the risky few to a human.
        </Card>
        <Card href="/docs#the-audit" title="The audit" cta="Read the section">
          Reads your trace exports on your machine and finds the judgments your agents keep
          re-buying. A design preview: not installable yet.
        </Card>
      </Cards>

      <H2 id="doug-reviews">Doug reviews</H2>
      <P>
        <b>Doug is risk-routed code review for the agent era.</b> He scores every pull request,
        clears the majority, and routes the risky few to a human — with evidence attached. Every
        merge starts a clock against this repo&rsquo;s reverts. He never blocks a merge.
      </P>
      <P>
        Watch Doug score its own pull requests on the <Link href="/queue">queue</Link>, read
        the <Link href="/scoreboard">scoreboard</Link> (adjudicated and pending counters tick
        there now; <IC>miss_rate</IC> stays null until the pre-registered interval fires, and a
        count is not a rate). The GitHub App is dogfooding on this repository and is
        not a self-serve product for other orgs yet. The self-serve measurement tool is still
        the <b>backtest CLI</b>: replay your repo&rsquo;s merged history, label defect-inducing
        PRs from revert anchors in git, and measure which PRs Doug would have routed. The report
        is the demo — and the same numbers we publish for ourselves.
      </P>

      <Cards>
        <Card href="/docs/quickstart" title="Quickstart" cta="Start here">
          Backtest any public repository in one command — no account, no server.
        </Card>
        <Card href="/docs/what-doug-gets-wrong" title="What Doug gets wrong" cta="Honesty">
          Doug reviews his own pull requests, and the team logs what he got wrong.
        </Card>
        <Card href="/docs/cli" title="CLI · doug-backtest" cta="Reference">
          Every flag, with examples, for the CLI that replays a repo&rsquo;s merged history.
        </Card>
      </Cards>

      <Callout lead="Early preview.">
        Doug is in active development. Everything marked <StatusBadge status="available" /> works
        today; things marked <StatusBadge status="preview" /> or <StatusBadge status="planned" />{" "}
        are described so you can see where this is going — not to pretend they exist.
      </Callout>

      <CodeBlock title="The shape of Doug">
        <Comment># 1 · replay history, honestly</Comment>
        {"\n"}
        <Bright>doug-backtest</Bright> <Str>your-org/your-repo</Str>
        {"\n\n"}
        <Comment># 2 · route the live queue</Comment>
        {"\n"}
        <Dim>62 open → 5 need you · rest cleared w/ receipts</Dim>
        {"\n\n"}
        <Comment># 3 · ask before you write             [planned]</Comment>
        {"\n"}
        <Fn>doug.ask</Fn>
        {"("}
        <Str>&quot;backfill NOT NULL on a hot table&quot;</Str>
        {")"}
      </CodeBlock>

      <H2 id="the-audit">The audit</H2>
      <P>
        <StatusBadge status="preview" label={AUDIT_PREVIEW_LABEL} />
      </P>
      <P>
        Coldworks reads the traces your agents already produce, finds the judgments they keep
        re-buying, and compiles the repeats into deterministic code <b>you own and you run</b>.
        These pages cover the part you touch: getting your traces in, running the audit, and
        reading what it finds.
      </P>

      <Cards>
        <Card href="/docs/audit/quickstart" title="Quickstart" cta="Start here">
          One command, no signup, no install step. See a full audit on sample data in under a
          minute.
        </Card>
        <Card href="/docs/audit/connect" title="Connect your traces" cta="Three steps">
          Langfuse, LangSmith, or OpenTelemetry. A batch export is a file transfer, not an
          integration.
        </Card>
        <Card href="/docs/audit/cli" title="The audit CLI" cta="Reference">
          Every command, flag, and file the audit reads or writes — and what never leaves your
          machine.
        </Card>
      </Cards>

      <H3 id="the-shape-of-it">The shape of it</H3>
      <P>
        Everything below runs on <b>your</b> machine. Coldworks hosts one thing: a read-only
        registry page for figures you choose to publish. It cannot receive your traces, your
        documents, or your code — by architecture, not by policy.
      </P>
      <CodeBlock title="The whole pipeline">
        <Comment>your trace store</Comment>
        {"  "}
        <Prompt>──export──▶</Prompt>
        {"  "}
        <Comment>a file on your disk</Comment>
        {"  "}
        <Prompt>──</Prompt>
        <Cmd>coldworks-audit</Cmd>
        <Prompt>──▶</Prompt>
        {"  "}
        <Comment>a report on your disk</Comment>
        {"\n\n"}
        <Prompt>nothing crosses the boundary. the report is yours to forward, or not.</Prompt>
      </CodeBlock>

      <H3 id="what-is-real-right-now">What is real right now</H3>
      <P dim>These docs hold themselves to the same rule as the audit: states are answers.</P>
      <Table
        head={["Claim", "State"]}
        rows={[
          [
            "The connection flow in these docs is the front-door design under review.",
            <Chip key="s" tone="ember">DESIGNED</Chip>,
          ],
          [
            "The recovery engine behind the audit exists and is deterministic.",
            <Chip key="s" tone="coolant">BUILT · UNRELEASED</Chip>,
          ],
          [
            <>
              <IC>coldworks-audit</IC> is installable.
            </>,
            <Chip key="s" tone="molten">NOT YET</Chip>,
          ],
          [
            "Validated against a real Langfuse / LangSmith export.",
            <Chip key="s" tone="open">GATED · NEXT STEP</Chip>,
          ],
          [
            "Anything in these docs uploads your data.",
            <Chip key="s" tone="molten">NO — BY DESIGN</Chip>,
          ],
        ]}
      />

      <DocsPager currentHref="/docs" />
    </>
  );
}
