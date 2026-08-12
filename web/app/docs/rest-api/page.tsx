import { Bright, CodeBlock, Dim, Kw, Str } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { ParamsTable } from "@/components/docs/params-table";
import { DocsPageHeader } from "@/components/docs/prose";

export const metadata = {
  title: "REST API — Doug Documentation",
  description:
    "The planned REST surface for the hosted product — not live yet.",
};

export default function RestApiPage() {
  return (
    <>
      <DocsTwoCol
        prose={
          <>
            <DocsPageHeader
              kicker="Coming up"
              title="REST API"
              status="planned"
            >
              The hosted product will expose the same objects the CLI prints
              today. Sketched here so you can see the shape early —{" "}
              <b className="font-semibold text-foreground">
                none of this is live
              </b>
              .
            </DocsPageHeader>

            <ParamsTable
              rows={[
                {
                  name: "GET /v1/queue",
                  meta: "planned",
                  description:
                    "The routed queue: open PRs with scores, verdicts, and receipts.",
                },
                {
                  name: "GET /v1/prs/:number/receipt",
                  meta: "planned",
                  description:
                    "The full evidence trail behind a verdict — rules fired, hotspot history, pattern matches.",
                },
                {
                  name: "GET /v1/scoreboard",
                  meta: "planned",
                  description:
                    "Published calibration: miss rates per author type, over time. Public by design.",
                },
              ]}
            />
          </>
        }
        rail={
          <CodeBlock title="SKETCH — NOT LIVE">
            <Dim>$</Dim>{" "}
            <Bright>curl https://api.doug.dev/v1/prs/4821/receipt</Bright>
            {"\n{\n  "}
            <Str>&quot;verdict&quot;</Str>
            {": "}
            <Str>&quot;needs_human&quot;</Str>
            {",\n  "}
            <Str>&quot;routed_to&quot;</Str>
            {": "}
            <Str>&quot;maya&quot;</Str>
            {",\n  "}
            <Str>&quot;evidence&quot;</Str>
            {": [\n    { "}
            <Str>&quot;rule&quot;</Str>
            {": "}
            <Str>&quot;hotspot_path&quot;</Str>
            {", "}
            <Str>&quot;lift&quot;</Str>
            {": "}
            <Kw>2.34</Kw>
            {" },\n    { "}
            <Str>&quot;pattern&quot;</Str>
            {": "}
            <Str>&quot;dual_write_no_guard&quot;</Str>
            {",\n      "}
            <Str>&quot;seen&quot;</Str>
            {": "}
            <Kw>214</Kw>
            {", "}
            <Str>&quot;reverted&quot;</Str>
            {": "}
            <Kw>31</Kw>
            {" }\n  ]\n}"}
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/rest-api" />
    </>
  );
}
