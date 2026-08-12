import Link from "next/link";

import { Bright, CodeBlock, Comment, Dim } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import type { ParamRow } from "@/components/docs/params-table";
import { ParamsTable } from "@/components/docs/params-table";
import { DocsPageHeader, IC } from "@/components/docs/prose";

export const metadata = {
  title: "CLI · doug-backtest — Doug Documentation",
  description:
    "Flag reference and usage examples for doug-backtest, the CLI that replays a repo's merged history.",
};

const FLAGS: ParamRow[] = [
  {
    name: "repo",
    meta: "positional · required",
    description: (
      <>
        <IC>owner/repo</IC>, e.g. <IC>astral-sh/ruff</IC>
      </>
    ),
  },
  {
    name: "--limit",
    meta: "int · default 300",
    description: "Merged PRs to harvest, newest-first within the window.",
  },
  {
    name: "--before",
    meta: "YYYY-MM-DD",
    description:
      "Only harvest PRs created before this date — the right-censoring guard.",
  },
  {
    name: "--labels",
    meta: "git | api | both · default git",
    description: (
      <>
        Defect label source. See{" "}
        <Link
          href="/docs/defect-labels"
          className="text-accent-foreground hover:underline"
        >
          Defect labels
        </Link>
        .
      </>
    ),
  },
  {
    name: "--token",
    meta: "string",
    description: (
      <>
        GitHub token. Default: environment, then the <IC>gh</IC> CLI.
      </>
    ),
  },
  {
    name: "--cache-dir",
    meta: "path · default .backtest-cache",
    description:
      "Harvest cache location. Safe to reuse across runs; seeds bigger runs from smaller ones.",
  },
  {
    name: "--output",
    meta: "path",
    description: "Write the full JSON report here as well as printing tables.",
  },
  {
    name: "--backfill-details",
    meta: "flag",
    description:
      "Fetch per-file stats + patch text for cached PRs missing them (~1 request/PR; checkpointed, resumable).",
  },
];

const EXAMPLES = `# quick look, 300 PRs
$ doug-backtest astral-sh/ruff

# serious run: deep window, censoring guard,
# patch-level detail, JSON report
$ doug-backtest grafana/grafana \\
    --limit 12000 \\
    --before 2026-06-15 \\
    --labels git \\
    --backfill-details \\
    --output report.json

# resume after a kill — same command, cache does the rest
$ doug-backtest grafana/grafana --limit 12000 \\
    --before 2026-06-15`;

export default function CliPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader
              kicker="Reference"
              title="CLI · doug-backtest"
              status="available"
            >
              Replay a repository&rsquo;s merged-PR history and print the full
              scoreboard. Harvests are cached and checkpointed — kill it and
              relaunch any time; it resumes.
            </DocsPageHeader>

            <ParamsTable rows={FLAGS} />
          </>
        }
        rail={
          <CodeBlock title="Examples" copyText={EXAMPLES}>
            <Comment># quick look, 300 PRs</Comment>
            {"\n"}
            <Dim>$</Dim> <Bright>doug-backtest astral-sh/ruff</Bright>
            {"\n\n"}
            <Comment>
              {"# serious run: deep window, censoring guard,\n# patch-level detail, JSON report"}
            </Comment>
            {"\n"}
            <Dim>$</Dim> <Bright>
              {"doug-backtest grafana/grafana \\\n    --limit 12000 \\\n    --before 2026-06-15 \\\n    --labels git \\\n    --backfill-details \\\n    --output report.json"}
            </Bright>
            {"\n\n"}
            <Comment>
              # resume after a kill — same command, cache does the rest
            </Comment>
            {"\n"}
            <Dim>$</Dim> <Bright>
              {"doug-backtest grafana/grafana --limit 12000 \\\n    --before 2026-06-15"}
            </Bright>
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/cli" />
    </>
  );
}
