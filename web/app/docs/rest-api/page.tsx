import { Bright, CodeBlock, Dim, Kw, Str } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { DocsTwoCol } from "@/components/docs/docs-two-col";
import { ParamsTable } from "@/components/docs/params-table";
import { DocsPageHeader, IC, P } from "@/components/docs/prose";

export const metadata = {
  title: "REST API — Doug Documentation",
  description:
    "Public showcase endpoints are live. Tenant queue and receipt are live, gated. A tenant scoreboard is still planned.",
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
              status="preview"
            >
              The unauthenticated showcase endpoints are live — they are what{" "}
              <b className="font-semibold text-foreground">/queue</b> and{" "}
              <b className="font-semibold text-foreground">/scoreboard</b>{" "}
              render. Tenant queue and receipt are live behind a session or
              a token. A scoreboard of <em>your</em> clocks is still planned.
            </DocsPageHeader>

            <P>
              Both showcase routes ignore <IC>?repo=</IC>. The bound is the
              API&rsquo;s <IC>DOUG_SHOWCASE_REPO</IC>, not a query string a
              stranger can widen. Per-author-type rates are not published.
            </P>

            <ParamsTable
              rows={[
                {
                  name: "GET /v1/showcase/queue",
                  meta: "live",
                  description:
                    "Open PRs for the showcase repo, scored, with reasons. Unauthenticated. What /queue renders.",
                },
                {
                  name: "GET /v1/showcase/scoreboard",
                  meta: "live",
                  description:
                    "Prospective counters from the ledger: adjudicated, pending, first due, deep-read meter. miss_rate is null until the pre-registered interval fires. Label: not yet decidable — a count, not a rate.",
                },
                {
                  name: "GET /v1/prs/:number/receipt",
                  meta: "live",
                  description:
                    "The evidence trail behind a verdict. Session or a token with receipt:read. Not a public showcase route.",
                },
                {
                  name: "GET /v1/queue",
                  meta: "live",
                  description:
                    "Tenant-scoped routed queue. Session or token. The showcase route is pinned to one repo by design and is not this.",
                },
                {
                  name: "GET /v1/scoreboard",
                  meta: "planned",
                  description:
                    "Tenant-scoped clocks: your adjudicated / pending / miss_rate. The showcase route is pinned to one repo by design and is not this.",
                },
              ]}
            />
          </>
        }
        rail={
          <CodeBlock title="RESPONSE SHAPE — run it for the numbers">
            <Dim>$</Dim>{" "}
            <Bright>curl &quot;$DOUG_API_URL/v1/showcase/scoreboard&quot;</Bright>
            {"\n{\n  "}
            <Str>&quot;repo&quot;</Str>
            {": "}
            <Str>&quot;drewjst/doug&quot;</Str>
            {",\n  "}
            <Str>&quot;adjudicated&quot;</Str>
            {": "}
            <Dim>&lt;int&gt;</Dim>
            {",\n  "}
            <Str>&quot;pending&quot;</Str>
            {": "}
            <Dim>&lt;int&gt;</Dim>
            {",\n  "}
            <Str>&quot;as_of&quot;</Str>
            {": "}
            <Dim>&lt;iso8601&gt;</Dim>
            {",\n  "}
            <Str>&quot;first_due&quot;</Str>
            {": "}
            <Dim>&lt;iso8601 | null&gt;</Dim>
            {",\n  "}
            <Str>&quot;deep_reads&quot;</Str>
            {": "}
            <Dim>&lt;int&gt;</Dim>
            {", "}
            <Str>&quot;deep_read_cap&quot;</Str>
            {": "}
            <Dim>&lt;int&gt;</Dim>
            {",\n  "}
            <Str>&quot;miss_rate&quot;</Str>
            {": "}
            <Kw>null</Kw>
            {",\n  "}
            <Str>&quot;decidable&quot;</Str>
            {": "}
            <Kw>false</Kw>
            {",\n  "}
            <Str>&quot;label&quot;</Str>
            {": "}
            <Str>&quot;not yet decidable — a count, not a rate&quot;</Str>
            {"\n}\n\n"}
            <Dim>
              {"# The counters move; a number printed here would\n"}
              {"# be stale by the time you read it, so this shows\n"}
              {"# the shape and the route is unauthenticated.\n"}
              {"# miss_rate does NOT move: null until the\n"}
              {"# pre-registered interval fires."}
            </Dim>
          </CodeBlock>
        }
      />
      <DocsPager currentHref="/docs/rest-api" />
    </>
  );
}
