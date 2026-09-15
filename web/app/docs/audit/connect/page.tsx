import { Chip } from "@/components/docs/badge";
import { Callout } from "@/components/docs/callout";
import { Cmd, CodeBlock, Comment, Hot, Prompt, Warm } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsPageHeader, H2, IC, OL, P, Small } from "@/components/docs/prose";
import { Table } from "@/components/docs/table";
import { AUDIT_PREVIEW_LABEL } from "@/lib/docs-nav";

export const metadata = {
  title: "Connect your traces · The audit",
  description:
    "How to connect Langfuse, LangSmith, or OpenTelemetry traces to the Coldworks audit — and what never leaves your machine.",
};

export default function AuditConnectPage() {
  return (
    <>
      <DocsPageHeader
        kicker="The audit · Getting started"
        title="Connect your traces"
        status="preview"
        statusLabel={AUDIT_PREVIEW_LABEL}
      >
        You already have the traces — your trace store has been writing your agent&apos;s
        judgments down the whole time. Coldworks reads them <b>where they live: on your
        machine</b>. A batch trace export is a file transfer, not an integration.
      </DocsPageHeader>

      <H2>The three steps</H2>
      <OL>
        <li>
          <b>Export</b> your traces from your store (about 30 seconds — every store already has
          this).
        </li>
        <li>
          <b>Run</b> <IC>uvx coldworks-audit run traces.jsonl</IC> locally.
        </li>
        <li>
          <b>Read</b> the report it writes next to the file.
        </li>
      </OL>
      <CodeBlock title="Illustrative — no real store behind this page">
        <Prompt>$</Prompt> <Cmd>uvx coldworks-audit run</Cmd>
        {" traces.jsonl\n\n"}
        <b>11.84%</b>
        {" of context sits in agreeing repeat groups "}
        <Comment>(band 11.80% to 12.02%)</Comment>
        {"\nMost of this figure is cross-run: the same call in a later run. A session cache cannot see it.\n\n  "}
        <Comment>
          214 repeat groups holding 2,871 calls · 41,218 spans · 9,406 tool calls · your tool names, kept
        </Comment>
        {"\n  "}
        <Cmd>→ tier-0 cache candidate: 131 agreeing groups holding 1,704 calls</Cmd>
        {"\n  "}
        <Warm>→ 83 groups holding 1,167 calls returned different results</Warm>
        {"  "}
        <Comment>nondeterminism findings</Comment>
        {"\n\nnot counted as findings, not hidden:\n  "}
        <Hot>322</Hot>
        {" calls carried no result · "}
        <Hot>118</Hot>
        {" carried no arguments\n\nreport: "}
        <Cmd>./coldworks-audit.html</Cmd>
      </CodeBlock>
      <Small>
        Candidates, never savings — a repeated judgment is a candidate for compilation, not a
        booked dollar. The report prints what it could not read in the same breath as what it
        could.
      </Small>

      <H2>From Langfuse</H2>
      <P>
        Langfuse observations carry name, input, output, and token usage — everything the audit
        needs. Three rungs, all running with your credentials on your compute:
      </P>
      <Table
        head={["Rung", "How it works", "Status"]}
        rows={[
          [
            <b key="r">File</b>,
            <>
              Traces → Export in the Langfuse UI, then <IC>coldworks-audit run</IC> on the
              downloaded file.
            </>,
            <Chip key="s" tone="ember">DESIGNED</Chip>,
          ],
          [
            <b key="r">Standing file</b>,
            <>
              Langfuse&apos;s scheduled export writes fresh traces to <em>your</em> S3 / GCS
              bucket on its own timer; your cron line re-audits whatever lands. Two schedulers,
              both yours — there is no Coldworks daemon.
            </>,
            <Chip key="s" tone="ember">DESIGNED</Chip>,
          ],
          [
            <b key="r">Direct pull</b>,
            <>
              <IC>coldworks-audit run --from langfuse</IC> reads <IC>LANGFUSE_PUBLIC_KEY</IC> /{" "}
              <IC>LANGFUSE_SECRET_KEY</IC> from your environment and pages the observations API
              itself — incremental via <IC>--since</IC>.
            </>,
            <Chip key="s" tone="coolant">PLANNED · AFTER FILE PATH</Chip>,
          ],
        ]}
      />

      <H2>From LangSmith</H2>
      <P>
        No LangSmith reader ships in release 1, and <IC>--format</IC> does not list one: for most
        plans no export file exists until a script writes one, and no LangSmith export has been
        read. The reader follows the first LangSmith export in hand.
      </P>

      <H2>From OpenTelemetry</H2>
      <P>Point your collector&apos;s file exporter at a directory and audit what lands there.</P>
      <P>
        Whatever the source, the headline is not token-weighted. No export measured so far pairs
        a character count with a token count of the same bytes, so the headline is a share of
        context in characters. Where an export carries token totals, the report prints them as
        totals, in their unit.
      </P>

      <H2>What leaves your machine: nothing</H2>
      <Table
        head={["Thing", "Where it goes", ""]}
        rows={[
          [
            <b key="t">Your traces</b>,
            "Read from your disk, never transmitted.",
            <Chip key="s" tone="molten">NEVER LEAVES</Chip>,
          ],
          [
            <>
              <b>Your documents</b> (<IC>--docs</IC>)
            </>,
            "Hashed and matched locally, never transmitted.",
            <Chip key="s" tone="molten">NEVER LEAVES</Chip>,
          ],
          [
            <b key="t">The audit report</b>,
            "An HTML file on your disk. Forward it yourself, or don't.",
            <Chip key="s" tone="molten">STAYS LOCAL</Chip>,
          ],
          [
            <b key="t">Derived figures</b>,
            <>
              A future opt-in <IC>--push</IC> could publish headline figures to a hosted registry
              page. It does not exist, and ships only under an explicitly signed exception.
            </>,
            <Chip key="s" tone="open">DOES NOT EXIST</Chip>,
          ],
        ]}
      />
      <P dim>
        This is doctrine, not a feature flag: Coldworks compiles judgments into code you own and
        you run. Auditing starts on the same side of the boundary the guards live on — yours.
      </P>

      <H2>Day 2: make it standing</H2>
      <P>
        The report footer prints one line for your scheduler — cron, GitHub Actions, or GitLab CI.
        A shell command in your infrastructure; never an app you install or a marketplace
        listing.
      </P>
      <CodeBlock title="Report footer · illustrative">
        <Comment># re-audit whatever lands in ./exports, every night at 02:10</Comment>
        {"\n10 2 * * *  "}
        <Cmd>uvx coldworks-audit run</Cmd>
        {" ./exports --diff >> audit.log"}
      </CodeBlock>
      <P>
        Each run appends to a local append-only ledger, and <IC>--diff</IC> reports what changed:{" "}
        <b>new repeated judgments since the last run</b>. That number rising is your agent
        re-buying the same decision with fresh tokens.
      </P>
      <Callout lead="Honest limit:">
        the cron line monitors only if fresh exports keep landing in that directory.
        Langfuse&apos;s scheduled bucket export, on the tiers that have it or self-hosted,
        supplies the files; no batch export has been read yet. The direct{" "}
        <IC>--from langfuse</IC> pull is the planned successor. There is no Coldworks daemon,
        resident process, or phone-home in any rung.
      </Callout>

      <DocsPager currentHref="/docs/audit/connect" />
    </>
  );
}
