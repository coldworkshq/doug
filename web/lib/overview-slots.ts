/**
 * The Overview's four slots, decided here so the component stays a template.
 *
 * One component, four slots, each real or a chip with a reason (design lock
 * T3). What makes a slot real is its source, not a build flag:
 *
 * - Reviewed, and how many needed a reader: the ledger. Real for every
 *   installation the moment Doug has reviewed anything. The ledger read is
 *   one page of at most 500, so a full page is said as "500+" over "the
 *   most recent 500", never as a total.
 * - Decisions on record: the intent read of one repository, the one Memory
 *   opens first. A count of the binding status, never a "cited" figure.
 * - Settled by guards, and T: the engine's read contract, only for an
 *   installation the founder has mapped to an engine tenant, only when the
 *   read names that tenant (the reader checks), and only when a guard has
 *   dispatched. The figure is the engine's, and its sentence says so at the
 *   figure's own size (O1). Everyone else sees the chip.
 */
import type { RegistryResult } from "./registry-api";
import type { RegistryMetric, RegistrySnapshotV1 } from "./registry-shape";
import type { RepositoryDecisionsResult, RunSummary } from "./session-api";
import { matchedNothingGloss } from "./memory-model";
import type { ChipKind } from "./state-chip";

export type SlotKey = "reviewed" | "decisions" | "settled" | "t";

export type SlotChip = { kind: ChipKind; subject: string; detail?: string };

export type Slot = { key: SlotKey; label: string; href: string } & (
  | { figure: string; sentence: string; chip: null }
  | { figure: null; sentence: null; chip: SlotChip }
);

const chip = (base: { key: SlotKey; label: string; href: string }, c: SlotChip): Slot => ({
  ...base,
  figure: null,
  sentence: null,
  chip: c,
});

const REVIEWED = { key: "reviewed" as const, label: "Pull requests reviewed", href: "/dashboard" };

/** `runs` is the ledger's first page, or null when the read failed. */
export function reviewedSlot(runs: RunSummary[] | null, limit: number): Slot {
  if (runs === null) {
    return chip(REVIEWED, { kind: "unknown", subject: "reviews", detail: "the ledger did not answer" });
  }
  const needed = runs.filter((r) => r.band === "flagged").length;
  const capped = runs.length >= limit;
  return {
    ...REVIEWED,
    figure: capped ? `${limit}+` : String(runs.length),
    sentence:
      runs.length === 0
        ? "no reviews recorded for this space yet"
        : capped
          ? `${needed} needed a reader, over the most recent ${limit} on the ledger`
          : `${needed} needed a reader, over the ${runs.length} on the ledger`,
    chip: null,
  };
}

const DECISIONS = { key: "decisions" as const, label: "Decisions on record", href: "/dashboard/memory" };

/** `result` is null when the read threw; `fullName` is null when no
 *  repository is connected. The two are different zeros. */
export function decisionsSlot(result: RepositoryDecisionsResult | null, fullName: string | null): Slot {
  if (fullName === null) {
    return chip(DECISIONS, { kind: "unknown", subject: "decisions", detail: "no repository is connected in this space" });
  }
  if (result === null) {
    return chip(DECISIONS, { kind: "unknown", subject: "decisions", detail: `the read of ${fullName} did not answer` });
  }
  if (!result.ok) {
    return chip(DECISIONS, { kind: "unknown", subject: "decisions", detail: result.failure.reason });
  }
  const d = result.decisions;
  if (d.matched_nothing) {
    return chip(DECISIONS, { kind: "unknown", subject: "decisions", detail: matchedNothingGloss(d) });
  }
  return {
    ...DECISIONS,
    figure: String(d.count_accepted),
    sentence: `${d.binding_status} records in ${fullName}; other repositories on Memory`,
    chip: null,
  };
}

/** One metric by key. A tenant-level figure (no pack) wins; else the single
 *  pack that carries it; a key carried by several packs is not one number
 *  and is reported as such rather than picked by array order. */
export function pickMetric(
  snapshot: RegistrySnapshotV1,
  key: string,
): { metric: RegistryMetric | null; ambiguous: string[] } {
  const matches = snapshot.metrics.filter((m) => m.key === key);
  const tenantLevel = matches.find((m) => m.pack === null);
  if (tenantLevel) return { metric: tenantLevel, ambiguous: [] };
  if (matches.length === 1) return { metric: matches[0], ambiguous: [] };
  if (matches.length === 0) return { metric: null, ambiguous: [] };
  return { metric: null, ambiguous: matches.map((m) => m.pack ?? "?") };
}

function dispatches(snapshot: RegistrySnapshotV1): number {
  return snapshot.landings.reduce((n, l) => n + l.compiledDecisions, 0);
}

const SETTLED = { key: "settled" as const, label: "Settled by guards", href: "/dashboard/guards" };
const T = { key: "t" as const, label: "Temperature", href: "/dashboard/guards" };

/** Both engine slots from one decision, so they can never disagree about why.
 *  `mapping` is what `resolveGuardsMapping` returned; `registry` is the
 *  reader's answer for that tenant (the reader owns the tenant check). */
export function guardSlots(
  mapping: { tenant: string | null; error: string | null },
  registry: RegistryResult | null,
): { settled: Slot; t: Slot } {
  const both = (c: SlotChip) => ({ settled: chip(SETTLED, c), t: chip(T, c) });

  if (mapping.error !== null) {
    return both({ kind: "unknown", subject: "guards", detail: mapping.error });
  }
  if (mapping.tenant === null) {
    return both({ kind: "later", subject: "guards" });
  }
  if (registry === null || registry.kind === "unknown") {
    return both({ kind: "unknown", subject: "guards", detail: registry?.reason ?? "the registry was not read" });
  }
  const s = registry.snapshot;
  if (dispatches(s) === 0) {
    return both({ kind: "unknown", subject: "guards", detail: "no guard has dispatched on this tenant's work yet" });
  }
  const provenance = s.provenance ?? "an undeclared corpus";
  const sentence = s.synthetic
    ? `measured on ${provenance}, not this repository's pull requests`
    : `measured on ${provenance}`;

  const slot = (base: typeof SETTLED | typeof T, key: string, fmt: (v: number) => string): Slot => {
    const { metric, ambiguous } = pickMetric(s, key);
    if (ambiguous.length > 0) {
      return chip(base, { kind: "unknown", subject: "guards", detail: `the registry carries ${key} for several packs (${ambiguous.join(", ")}); no single figure` });
    }
    if (metric === null) {
      return chip(base, { kind: "unknown", subject: "guards", detail: `the registry carries no ${key} figure` });
    }
    if (metric.status !== "measured" || metric.value === null) {
      return chip(base, { kind: "unknown", subject: "guards", detail: metric.note ?? `the ${key} figure is ${metric.status}` });
    }
    return { ...base, figure: fmt(metric.value), sentence, chip: null };
  };
  return {
    settled: slot(SETTLED, "coverage", (v) => `${Math.round(v * 100)}%`),
    t: slot(T, "t", (v) => v.toFixed(2)),
  };
}
