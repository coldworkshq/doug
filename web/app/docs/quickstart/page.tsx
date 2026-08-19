import { Bright, CodeBlock, Comment, Dim, Ok } from "@/components/docs/code-block";
import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { DocsPageHeader, H2, IC, UL } from "@/components/docs/prose";

export const metadata = {
  title: "Quickstart — Doug Documentation",
  description:
    "Backtest any public repository in one command — no account, no server.",
};

const TERMINAL = `# install (from the repo, for now)
$ git clone https://github.com/drewjst/doug && cd doug/api
$ uv sync

# backtest a year of history
$ uv run doug-backtest getsentry/sentry \\
    --limit 5000 --before 2026-06-15 --labels git`;

export default function QuickstartPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader
              kicker="Getting started"
              title="Quickstart"
              status="available"
            >
              Backtest any public repository in one command. No account, no
              server — the CLI talks to GitHub, caches locally, and prints
              the full scoreboard.
            </DocsPageHeader>

            <H2>Requirements</H2>
            <UL>
              <li>
                Python 3.14+ and <IC>uv</IC> (or pip)
              </li>
              <li>
                A GitHub token — picked up from the environment or the{" "}
                <IC>gh</IC> CLI. Without one you get the unauthenticated 60
                req/hr limit, which is only enough for tiny runs.
              </li>
            </UL>

            <H2>What a run does</H2>
            <UL>
              <li>
                Labels defect-inducing PRs from{" "}
                <b className="font-semibold text-foreground">
                  revert anchors in git history
                </b>{" "}
                (dense, zero API quota)
              </li>
              <li>
                Harvests merged PRs into a resumable local cache (
                <IC>.backtest-cache/</IC>)
              </li>
              <li>
                Replays Doug&rsquo;s scoring over the window and prints
                capture, cleared-band, per-rule, and holdout tables
              </li>
            </UL>

            <div className="mt-6">
              <Callout lead="Tip — dodge right-censoring:">
                Young PRs haven&rsquo;t had time to be reverted yet. Pass{" "}
                <IC>--before</IC> with a date at least a few weeks back so
                every PR in the window had a fair chance to fail.
              </Callout>
            </div>
          </>
        }
        rail={
          <>
            <CodeBlock title="Terminal" copyText={TERMINAL}>
              <Comment># install (from the repo, for now)</Comment>
              {"\n"}
              <Dim>$</Dim> <Bright>
                git clone https://github.com/drewjst/doug && cd doug/api
              </Bright>
              {"\n"}
              <Dim>$</Dim> <Bright>uv sync</Bright>
              {"\n\n"}
              <Comment># backtest a year of history</Comment>
              {"\n"}
              <Dim>$</Dim> <Bright>
                {"uv run doug-backtest getsentry/sentry \\\n    --limit 5000 --before 2026-06-15 --labels git"}
              </Bright>
            </CodeBlock>

            <CodeBlock title="Output (abridged, real run)">
              <Dim>5000 scored PRs · 67 in-window labeled defect-inducing</Dim>
              {"\n\n"}
              <Bright> flag rate     doug  size-only   random</Bright>
              {"\n"}
              {"      10%      14%         8%      10%\n"}
              {"      20%     "}
              <Ok>36%</Ok>
              {"        19%      20%\n"}
              {"      30%     "}
              <Ok>57%</Ok>
              {"        31%      30%"}
              {"\n\n"}
              <Dim>AUC — doug 0.640 · size-only 0.552 · random 0.500</Dim>
            </CodeBlock>
          </>
        }
      />
      <DocsPager currentHref="/docs/quickstart" />
    </>
  );
}
