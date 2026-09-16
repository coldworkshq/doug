import Link from "next/link";

import { Callout } from "@/components/docs/callout";
import { Cmd, CodeBlock, Comment, Prompt } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsPageHeader, H2, IC, OL, P, UL } from "@/components/docs/prose";
import { AUDIT_PREVIEW_LABEL } from "@/lib/docs-nav";

export const metadata = {
  title: "Quickstart · The audit",
  description:
    "Run your first Coldworks audit in under a minute: what to download, how to start, and what you get back.",
};

export default function AuditQuickstartPage() {
  return (
    <>
      <DocsPageHeader
        kicker="The audit · Getting started"
        title="Quickstart"
        status="preview"
        statusLabel={AUDIT_PREVIEW_LABEL}
      >
        First audit in under a minute. There is <b>nothing to install and no account to make</b>{" "}
        — the only prerequisite is <a href="https://docs.astral.sh/uv/">uv</a>, which most Python
        developers already carry.
      </DocsPageHeader>

      <H2>What to download</H2>
      <P>
        Nothing, in the usual sense. <IC>uvx</IC> fetches and runs the audit in one step, in an
        isolated environment it cleans up itself. If you prefer a persistent install:
      </P>
      <CodeBlock title="Either works">
        <Prompt>$</Prompt> <Cmd>uvx coldworks-audit</Cmd>
        {" --help          "}
        <Comment># run without installing</Comment>
        {"\n"}
        <Prompt>$</Prompt> <Cmd>uv tool install coldworks-audit</Cmd>
        {"     "}
        <Comment># or keep it on your PATH</Comment>
      </CodeBlock>
      <Callout lead="No API key, no signup, no Docker, no database.">
        The audit is a program that reads a file on your disk and writes a report next to it.
      </Callout>

      <H2>See it work before you export anything</H2>
      <P>
        Empty-handed? The package writes a sample span export itself, so the first report costs
        you nothing but the command:
      </P>
      <CodeBlock title="Sample run">
        <Prompt>$</Prompt> <Cmd>uvx coldworks-audit run</Cmd>
        {" --sample --open"}
      </CodeBlock>
      <P dim>
        This renders the full report — headline, repeat groups, nondeterminism findings, loss
        populations — on data we wrote, labeled as such on every screen. The release-1 sample
        is span-only; documents arrive with <IC>--docs</IC> in release 2.
      </P>

      <H2>Your first real audit</H2>
      <OL>
        <li>
          <b>Export traces</b> from wherever they live — takes about 30 seconds.
          See <Link href="/docs/audit/connect">Connect your traces</Link> for the Langfuse,
          LangSmith, and OpenTelemetry paths.
        </li>
        <li>
          <b>Run the audit</b> on the file:
        </li>
      </OL>
      <CodeBlock title="First real run">
        <Prompt>$</Prompt> <Cmd>uvx coldworks-audit run</Cmd>
        {" ~/Downloads/traces.jsonl --open"}
      </CodeBlock>
      <OL start={3}>
        <li>
          <b>Read the headline.</b> The share of your agent&apos;s context that sits in exact
          repeats of a judgment it already made — in your own tool vocabulary. Repeats count as
          cache candidates only when their results agree; disagreeing repeats are reported
          separately as nondeterminism findings. The report opens with one sentence: &ldquo;This
          report is the first step of an audit, not a dashboard. Where your platform already
          prints this number, start from that number; what this adds is the groups that disagree
          and the populations it could not read.&rdquo;
        </li>
      </OL>

      <H2>If the audit can&apos;t read your export</H2>
      <P>
        It doesn&apos;t report a silent zero. It prints a field census —{" "}
        <em>&quot;your spans carry tool names but not structured arguments&quot;</em> — so even a
        failed audit hands you a concrete, forwardable finding about your own telemetry.
      </P>

      <H2>Where to go next</H2>
      <UL>
        <li>
          <Link href="/docs/audit/connect">Connect your traces</Link> — the per-source paths, and
          how to make the audit standing instead of one-off.
        </li>
        <li>
          <Link href="/docs/audit/cli">The audit CLI</Link> — every flag, and the exact list of
          what never leaves your machine.
        </li>
      </UL>

      <DocsPager currentHref="/docs/audit/quickstart" />
    </>
  );
}
