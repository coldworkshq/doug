import { CodeBlock, Dim, Kw, Str } from "@/components/docs/code-block";
import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { DocsPageHeader, H2, IC, UL } from "@/components/docs/prose";

export const metadata = {
  title: "The report — Doug Documentation",
  description:
    "The four tables every doug-backtest run prints, and the JSON shape behind them.",
};

export default function ReportPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader
              kicker="Reference"
              title="The report"
              status="available"
            >
              Every run prints four tables; <IC>--output</IC> writes the same
              data as JSON. The report is designed to be{" "}
              <b className="font-semibold text-foreground">checked</b>, not
              admired — misses are listed by PR number so you can go read the
              ones Doug got wrong.
            </DocsPageHeader>

            <H2>Sections</H2>
            <UL>
              <li>
                <b className="font-semibold text-foreground">Capture curve</b> —
                doug vs size-only vs random, at each flag rate, plus AUC
              </li>
              <li>
                <b className="font-semibold text-foreground">Cleared band</b> —
                cleared count, missed defects, miss rate, density_lift per
                budget
              </li>
              <li>
                <b className="font-semibold text-foreground">
                  Per-rule precision
                </b>{" "}
                — every scoring rule: fired / hit / precision / lift. Dead rules
                stay in the table
              </li>
              <li>
                <b className="font-semibold text-foreground">
                  Time-split holdout
                </b>{" "}
                — hotspots learned on the older half only, scored on the newer
                half; requires ≥200 PRs and ≥8 defects with ≥4 in each half,
                otherwise it&rsquo;s honestly omitted
              </li>
            </UL>

            <div className="mt-6">
              <Callout lead="Schema stability:">
                early preview — field names may still move. The printed tables
                are the stable contract for now; treat the JSON as
                versioned-by-commit.
              </Callout>
            </div>
          </>
        }
        rail={
          <CodeBlock title="report.json (sketch)">
            {"{\n  "}
            <Str>&quot;repo&quot;</Str>
            {": "}
            <Str>&quot;getsentry/sentry&quot;</Str>
            {",\n  "}
            <Str>&quot;window&quot;</Str>
            {": { "}
            <Str>&quot;prs&quot;</Str>
            {": "}
            <Kw>5000</Kw>
            {", "}
            <Str>&quot;defects&quot;</Str>
            {": "}
            <Kw>67</Kw>
            {" },\n  "}
            <Str>&quot;capture&quot;</Str>
            {": { "}
            <Str>&quot;auc&quot;</Str>
            {": "}
            <Kw>0.640</Kw>
            {", "}
            <Str>&quot;at&quot;</Str>
            {": { "}
            <Str>&quot;0.2&quot;</Str>
            {": "}
            <Kw>0.36</Kw>
            {" } },\n  "}
            <Str>&quot;cleared_band&quot;</Str>
            {": [ { "}
            <Str>&quot;flag_rate&quot;</Str>
            {": "}
            <Kw>0.3</Kw>
            {",\n      "}
            <Str>&quot;density_lift&quot;</Str>
            {": "}
            <Kw>0.61</Kw>
            {", "}
            <Dim>&hellip;</Dim>
            {" } ],\n  "}
            <Str>&quot;rules&quot;</Str>
            {": [ { "}
            <Str>&quot;rule&quot;</Str>
            {": "}
            <Str>&quot;hotspot_path&quot;</Str>
            {",\n      "}
            <Str>&quot;lift&quot;</Str>
            {": "}
            <Kw>2.34</Kw>
            {", "}
            <Dim>&hellip;</Dim>
            {" } ],\n  "}
            <Str>&quot;holdout&quot;</Str>
            {": { "}
            <Dim>&hellip;</Dim>
            {" },\n  "}
            <Str>&quot;misses&quot;</Str>
            {": [ "}
            <Kw>4821</Kw>
            {", "}
            <Kw>3977</Kw>
            {", "}
            <Dim>&hellip;</Dim>
            {" ]\n}"}
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/report" />
    </>
  );
}
