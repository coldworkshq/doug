"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { adjudicateFinding, type AdjudicationActionState } from "@/app/example-packs/actions";
import type { ExampleAdjudication } from "@/lib/example-packs";

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="mono rounded-[4px] bg-foreground px-3 py-2 text-[10px] font-semibold uppercase tracking-[.1em] text-background outline-none hover:bg-[var(--iridescent)] focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:cursor-wait disabled:opacity-60"
    >
      {pending ? "recording…" : "append adjudication"}
    </button>
  );
}

export function AdjudicationForm({
  cohortId,
  packHash,
  findingId,
  current,
}: {
  cohortId: string;
  packHash: string;
  findingId: string;
  current: ExampleAdjudication | null;
}) {
  const action = adjudicateFinding.bind(null, cohortId, packHash, findingId);
  const [state, formAction] = useActionState<AdjudicationActionState, FormData>(action, {
    status: "idle",
    message: "",
  });
  return (
    <form action={formAction} className="mt-3 space-y-3 border-t border-border pt-3">
      <input type="hidden" name="expected_current_adjudication_id" value={current?.adjudication_id ?? ""} />
      <label className="block">
        <span className="mono text-[9px] uppercase tracking-[.12em] text-muted-foreground">disposition</span>
        <select name="disposition" defaultValue={current?.disposition ?? "unknown"} className="mt-1 w-full rounded-[4px] border border-input bg-background px-2.5 py-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <option value="verified_actionable">verified actionable</option>
          <option value="verified_accepted_nonactionable">verified accepted non-actionable</option>
          <option value="disproved">disproved</option>
          <option value="unknown">unknown</option>
        </select>
      </label>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <label className="block">
          <span className="mono text-[9px] uppercase tracking-[.12em] text-muted-foreground">receipt kind</span>
          <input name="receipt_kind" placeholder="source, test, trace" className="mt-1 w-full rounded-[4px] border border-input bg-background px-2.5 py-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </label>
        <label className="block">
          <span className="mono text-[9px] uppercase tracking-[.12em] text-muted-foreground">locator</span>
          <input name="receipt_locator" placeholder="path:line or receipt id" className="mt-1 w-full rounded-[4px] border border-input bg-background px-2.5 py-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </label>
      </div>
      <label className="block">
        <span className="mono text-[9px] uppercase tracking-[.12em] text-muted-foreground">receipt detail</span>
        <textarea name="receipt_detail" rows={2} placeholder="What this evidence proves" className="mt-1 w-full resize-y rounded-[4px] border border-input bg-background px-2.5 py-2 text-xs leading-relaxed outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      </label>
      <label className="block">
        <span className="mono text-[9px] uppercase tracking-[.12em] text-muted-foreground">receipt sha256 · optional</span>
        <input name="receipt_sha256" className="mono mt-1 w-full rounded-[4px] border border-input bg-background px-2.5 py-2 text-[10px] outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      </label>
      <div className="flex items-center gap-3">
        <Submit />
        <p aria-live="polite" className={`text-[11px] ${state.status === "error" ? "data-flag" : "data-clear"}`}>
          {state.message}
        </p>
      </div>
    </form>
  );
}
