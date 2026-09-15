import { Chip } from "@/components/docs/badge";
import { Callout } from "@/components/docs/callout";
import { Cmd, CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsPageHeader, H2, IC, P, UL } from "@/components/docs/prose";
import { Table } from "@/components/docs/table";
import { AUDIT_PREVIEW_LABEL } from "@/lib/docs-nav";

export const metadata = {
  title: "The audit CLI",
  description:
    "Reference for the coldworks-audit command: every flag, every file it reads and writes, and what never leaves your machine.",
};

const designed = <Chip tone="ember">DESIGNED</Chip>;

export default function AuditCliPage() {
  return (
    <>
      <DocsPageHeader
        kicker="The audit · Reference"
        hot
        title="The audit CLI"
        status="preview"
        statusLabel={AUDIT_PREVIEW_LABEL}
      >
        One command with one job: read a trace export on your disk, write an audit report next to
        it. <b>This page documents the designed interface</b> — it is the contract the build is
        held to, published before the build so you can hold it to the contract too.
      </DocsPageHeader>

      <H2>coldworks-audit run</H2>
      <CodeBlock title="Signature">
        <Cmd>coldworks-audit run</Cmd>
        {" <PATH> [--docs DIR] [--diff] [--sample] [--open] [--format NAME]"}
      </CodeBlock>
      <P>
        Audits the export at <IC>PATH</IC> — a file, or a directory whose newest exports are
        audited together with span-level dedup across overlapping files.
      </P>
      <Table
        head={["Argument", "What it does", "Status"]}
        rows={[
          [
            <IC key="a">PATH</IC>,
            <>
              The export file or directory. Format is detected from the first record: OTel GenAI
              spans, Langfuse observations (verified on the API shape), or the span-tree shape{" "}
              <IC>--sample</IC> writes. Override with{" "}
              <IC>--format otlp_genai|langfuse|span_tree</IC>.
            </>,
            designed,
          ],
          [
            <IC key="a">--docs DIR</IC>,
            <>
              Anchor recovered judgments to lines in your own documents. Files are hashed and
              matched locally; anchors carry the provenance line &quot;matched by trial, not by
              export-carried reference.&quot; Multi-document traces are counted unanchorable with
              their own reason code.
            </>,
            designed,
          ],
          [
            <IC key="a">--diff</IC>,
            "Report what changed since the last run: new repeated judgments, from the local ledger.",
            designed,
          ],
          [
            <IC key="a">--sample</IC>,
            <>
              Run on a sample span export the package writes itself — a full report with nothing
              of yours involved, labeled as sample data on every screen. The release-1 sample is
              span-only; documents arrive with <IC>--docs</IC> in release 2.
            </>,
            designed,
          ],
          [<IC key="a">--open</IC>, "Open the HTML report when the run finishes.", designed],
          [
            <IC key="a">--from langfuse</IC>,
            <>
              Skip the manual export: page the Langfuse observations API with{" "}
              <IC>LANGFUSE_PUBLIC_KEY</IC> / <IC>LANGFUSE_SECRET_KEY</IC> from your environment,
              incremental via <IC>--since</IC>. Your credential, your machine.
            </>,
            <Chip key="s" tone="coolant">PLANNED · AFTER FILE PATH</Chip>,
          ],
        ]}
      />

      <H2>What the headline counts</H2>
      <P>
        The report opens with one sentence: &ldquo;This report is the first step of an audit, not
        a dashboard. Where your platform already prints this number, start from that number; what
        this adds is the groups that disagree and the populations it could not read.&rdquo;
      </P>
      <UL>
        <li>
          Tool calls are grouped by <b>(tool name, arguments digest)</b> — exact repetition, not
          similarity.
        </li>
        <li>
          A repeat group is a <b>tier-0 cache candidate</b> only when its results agree across
          every occurrence. Disagreeing groups are reported separately as nondeterminism
          findings. Beside the tier-0 cache candidate label the report prints the following,
          where N is the number of groups whose results disagree: &ldquo;Most of this figure is
          cross-run: the same call in a later run. A session cache cannot see it. A session cache
          scripted from this table captured 3–20% of context on the benchmark corpus and returned
          a stale result on 17–45% of its hits. Caching these across runs is safe only where the
          result depends on the arguments alone. This export cannot show that; the N groups below
          show the opposite, and a file read never qualifies.&rdquo;
        </li>
        <li>
          The headline is the share of <b>context</b> &mdash; the bytes fed back to the model
          &mdash; that sits in agreeing repeat groups. It is said as a share of context, never as
          a share of calls: on the one benchmark corpus measured so far it reads &ldquo;about 23
          percent of context,&rdquo; and most of that is cross-run &mdash; the same call repeated
          in a later run, which a session cache cannot see.
        </li>
        <li>
          It is not token-weighted. No export measured so far pairs a character count with a
          token count of the same bytes, so a chars-per-token ratio is not computable; where the
          export carries token totals they are printed as totals, and the report says which unit
          it is in.
        </li>
        <li>
          The <b>process share</b> and the <b>navigation share</b> are reported separately, where
          a reader declares the tools they count, and never folded into the headline. No release-1
          reader declares them. The process share is refused, with the tool list it would have
          used printed in its place, when more than 20% of shell calls chain commands. The
          navigation share is a bracket under declared rules, not a point figure.
        </li>
        <li>
          What the audit could not read is printed, not dropped, each with a count: records that
          did not parse, calls that carried no arguments or no result, and repeat groups without
          the start times to order them. Spans that cannot be anchored to a document arrive with{" "}
          <IC>--docs</IC> in release 2.
        </li>
      </UL>

      <H2>Files it reads and writes</H2>
      <Table
        head={["File", "Direction", "What it is"]}
        rows={[
          [<IC key="f">&lt;PATH&gt;</IC>, "reads", "Your export. Never modified, never transmitted."],
          [
            <>
              <IC>--docs</IC> directory
            </>,
            "reads",
            "Your documents. Hashed locally for anchoring.",
          ],
          [
            <IC key="f">./coldworks-audit.html</IC>,
            "writes",
            "The report. Self-contained, built to be forwarded — by you.",
          ],
          [
            <IC key="f">./.coldworks/audit/ledger.jsonl</IC>,
            "appends",
            <>
              Derived figures per run, append-only. What <IC>--diff</IC> reads. Delete it any
              time; you lose history, nothing else.
            </>,
          ],
        ]}
      />
      <Callout cold>
        <b>
          Network calls made by <IC>run</IC>: zero.
        </b>{" "}
        The one planned exception is <IC>--from langfuse</IC>, which calls Langfuse — your trace
        store — with your key, from your machine. Nothing calls Coldworks.
      </Callout>

      <H2>Exit codes</H2>
      <Table
        head={["Code", "Meaning"]}
        rows={[
          [<IC key="c">0</IC>, "Audit completed — including an honest zero with a field census."],
          [
            <IC key="c">1</IC>,
            "The export could not be parsed at all; the error names the first unreadable record.",
          ],
          [<IC key="c">2</IC>, "Usage error; help printed."],
        ]}
      />

      <DocsPager currentHref="/docs/audit/cli" />
    </>
  );
}
