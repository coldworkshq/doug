import { AdjudicationForm } from "@/components/adjudication-form";
import { plainCapturedText, type ExampleAdjudication, type PackDetail } from "@/lib/example-packs";

function ExactBlock({ label, children }: { label: string; children: string }) {
  return (
    <details className="evidence-step border-b border-border py-3" open={label === "Evidence diff"}>
      <summary className="mono cursor-pointer text-[10px] font-medium uppercase tracking-[.12em] text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {label}
      </summary>
      <pre className="mono mt-3 max-h-[34rem] overflow-auto whitespace-pre-wrap break-words rounded-[4px] bg-muted/65 p-3 text-[10.5px] leading-relaxed">
        {plainCapturedText(children)}
      </pre>
    </details>
  );
}

function currentFor(detail: PackDetail, findingId: string): ExampleAdjudication | null {
  return detail.effective_adjudications.find((item) => item.finding_id === findingId) ?? null;
}

export function ExamplePackDetailView({ cohortId, detail }: { cohortId: string; detail: PackDetail }) {
  const { pack } = detail;
  return (
    <div className="grid gap-8 pb-16 lg:grid-cols-[minmax(0,1.25fr)_minmax(320px,.75fr)]">
      <section className="evidence-seam min-w-0 pl-6">
        <ExactBlock label="Exact request">
          {detail.request === null ? "No model request was made." : JSON.stringify(detail.request, null, 2)}
        </ExactBlock>
        <ExactBlock label="Evidence diff">{detail.evidence_text}</ExactBlock>
        <ExactBlock label="Selected raw output">
          {detail.raw_output_text ?? "No text output was selected."}
        </ExactBlock>
        <ExactBlock label="Parsed output">
          {pack.parsed_output === null ? "No parsed output." : JSON.stringify(pack.parsed_output, null, 2)}
        </ExactBlock>
      </section>

      <aside className="min-w-0">
        <h2 className="font-heading text-lg font-semibold tracking-tight">Finding docket</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          Each judgment appends a receipt. Corrections name the head visible on this page.
        </p>
        {pack.findings.length === 0 ? (
          <p className="mono mt-4 border-y border-border py-4 text-xs text-muted-foreground">
            Stored zero-finding result. This pack remains in the denominator.
          </p>
        ) : (
          <div className="mt-4 space-y-6">
            {pack.findings.map((finding) => {
              const current = currentFor(detail, finding.finding_id);
              return (
                <article key={finding.finding_id} className="border-t-2 border-foreground pt-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="mono text-[9px] uppercase tracking-[.12em] text-muted-foreground">finding {finding.ordinal + 1}</span>
                    <span className={`mono text-[9px] uppercase tracking-[.08em] ${current?.disposition === "verified_actionable" ? "data-clear" : current ? "data-flag" : "text-muted-foreground"}`}>
                      {current?.disposition.replaceAll("_", " ") ?? "unadjudicated"}
                    </span>
                  </div>
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words text-xs leading-relaxed">{JSON.stringify(finding.finding, null, 2)}</pre>
                  {current && (
                    <dl className="mono mt-3 grid grid-cols-[74px_1fr] gap-x-2 gap-y-1 border-l border-border pl-3 text-[9px] text-muted-foreground">
                      <dt>head</dt><dd className="truncate" title={current.adjudication_id}>{current.adjudication_id}</dd>
                      <dt>by</dt><dd>{current.adjudicator} · {current.adjudicated_at}</dd>
                      <dt>receipts</dt><dd>{current.evidence.length + current.verifier_receipts.length}</dd>
                    </dl>
                  )}
                  <AdjudicationForm cohortId={cohortId} packHash={pack.pack_hash} findingId={finding.finding_id} current={current} />
                </article>
              );
            })}
          </div>
        )}
      </aside>
    </div>
  );
}
