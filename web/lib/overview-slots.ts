/**
 * The Overview's four slots, decided here so the component stays a template.
 *
 * One component, four slots, each real or a chip with a reason (design lock
 * T3). What makes a slot real is its source, not a build flag:
 *
 * - Reviewed, and how many needed a reader: the ledger. Real for every
 *   installation the moment Doug has reviewed anything.
 * - Decisions on record: the intent read of one repository, the one Memory
 *   opens first. A count of the binding status, never a "cited" figure.
 * - Settled by guards, and T: the engine's read contract, only for an
 *   installation the founder has mapped to an engine tenant, only when the
 *   payload names that tenant, and only when a guard has dispatched. The
 *   figure is the engine's, and its sentence says so at the figure's own
 *   size (O1). Everyone else sees the chip.
 */
import type { RegistryResult } from "./registry-api";
import type { RegistrySnapshotV1 } from "./registry-shape";
import type { RepositoryDecisionsResult, RunSummary } from "./session-api";
import { matchedNothingGloss } from "./memory-model";
import type { ChipKind } from "./state-chip";

export type SlotKey = "reviewed" | "decisions" | "settled" | "t";

export interface Slot {
  key: SlotKey;
  label: string;
  href: string;
  /** The figure, or null when the chip renders instead. */
  figure: string | null;
  /** The sentence beside the figure. Rendered at the figure's size. */
  sentence: string;
  chip: { kind: ChipKind; subject: string; detail?: string } | null;
}

export function reviewedSlot(runs: RunSummary[]): Slot {
  const needed = runs.filter((r) => r.band === "flagged").length;
  return {
    key: "reviewed",
    label: "Pull requests reviewed",
    href: "/dashboard",
    figure: String(runs.length),
    sentence:
      runs.length === 0
        ? "no reviews recorded for this space yet"
        : `${needed} needed a reader, over the last ${runs.length} on the ledger`,
    chip: null,
  };
}

export function decisionsSlot(result: RepositoryDecisionsResult | null, fullName: string | null): Slot {
  const base = { key: "decisions" as const, label: "Decisions on record", href: "/dashboard/memory" };
  if (result === null || fullName === null) {
    return { ...base, figure: null, sentence: "", chip: { kind: "unknown", subject: "decisions", detail: "no repository is connected in this space" } };
  }
  if (!result.ok) {
    return { ...base, figure: null, sentence: "", chip: { kind: "unknown", subject: "decisions", detail: result.failure.reason } };
  }
  const d = result.decisions;
  if (d.matched_nothing) {
    return { ...base, figure: null, sentence: "", chip: { kind: "unknown", subject: "decisions", detail: matchedNothingGloss(d) } };
  }
  return {
    ...base,
    figure: String(d.count_accepted),
    sentence: `${d.binding_status} records in ${fullName}; other repositories on Memory`,
    chip: null,
  };
}

function metric(snapshot: RegistrySnapshotV1, key: string) {
  return snapshot.metrics.find((m) => m.key === key) ?? null;
}

function dispatches(snapshot: RegistrySnapshotV1): number {
  return snapshot.landings.reduce((n, l) => n + l.compiledDecisions, 0);
}

/** Both engine slots from one decision, so they can never disagree about why. */
export function guardSlots(mapping: string | null, registry: RegistryResult | null): { settled: Slot; t: Slot } {
  const settledBase = { key: "settled" as const, label: "Settled by guards", href: "/dashboard/guards" };
  const tBase = { key: "t" as const, label: "Temperature", href: "/dashboard/guards" };
  const chipped = (chip: Slot["chip"]) => ({
    settled: { ...settledBase, figure: null, sentence: "", chip },
    t: { ...tBase, figure: null, sentence: "", chip },
  });

  if (mapping === null) {
    return chipped({ kind: "later", subject: "guards" });
  }
  if (registry === null || registry.kind === "unknown") {
    return chipped({ kind: "unknown", subject: "guards", detail: registry?.reason ?? "the registry was not read" });
  }
  const s = registry.snapshot;
  if (s.tenant_id !== mapping) {
    return chipped({
      kind: "unknown",
      subject: "guards",
      detail: `the registry serves tenant ${s.tenant_id ?? "unknown"}; this installation is mapped to ${mapping}`,
    });
  }
  if (dispatches(s) === 0) {
    return chipped({ kind: "unknown", subject: "guards", detail: "no guard has dispatched on this tenant's work yet" });
  }
  const provenance = s.provenance ?? "an undeclared corpus";
  const sentence = s.synthetic
    ? `measured on ${provenance}, not this repository's pull requests`
    : `measured on ${provenance}`;
  const coverage = metric(s, "coverage");
  const t = metric(s, "t");
  const figure = (m: ReturnType<typeof metric>, fmt: (v: number) => string) =>
    m !== null && m.status === "measured" && m.value !== null ? fmt(m.value) : null;
  const settledFigure = figure(coverage, (v) => `${Math.round(v * 100)}%`);
  const tFigure = figure(t, (v) => v.toFixed(2));
  const notAsserted = (m: ReturnType<typeof metric>) =>
    m === null ? "the registry carries no such figure" : (m.note ?? `the figure is ${m.status}`);
  return {
    settled:
      settledFigure === null
        ? { ...settledBase, figure: null, sentence: "", chip: { kind: "unknown", subject: "guards", detail: notAsserted(coverage) } }
        : { ...settledBase, figure: settledFigure, sentence, chip: null },
    t:
      tFigure === null
        ? { ...tBase, figure: null, sentence: "", chip: { kind: "unknown", subject: "guards", detail: notAsserted(t) } }
        : { ...tBase, figure: tFigure, sentence, chip: null },
  };
}
