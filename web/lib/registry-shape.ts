/**
 * The registry read contract, as this app understands it.
 *
 * `registry-contract/registry-snapshot.v1.{schema,fixture}.json` are byte
 * copies of the files the registry generates (coldworks `apps/registry/
 * contract/`), pinned here by hash. The spec tables below are this app's own
 * hand-written description of the same shape, in the style of the exact-key
 * guards in `session-api.ts`: the test asserts the tables agree with the
 * schema key for key and null for null, so a field that moves on either side
 * fails a test rather than a page.
 *
 * Why a second description at all, rather than validating against the schema
 * at runtime: the schema is the registry's statement, the tables are ours,
 * and the test that they match is the contract. ADR-0034.
 */

export const SCHEMA_VERSION = 1 as const;

/** Pinned to the registry's `npm run contract` output. Re-pin on purpose, never in passing. */
export const SCHEMA_SHA256 = "a41e9d6642cd197017c34a8de8d4fe381727b065cec94816fa1957ae04b649ec";
export const FIXTURE_SHA256 = "d4587bb825dea93c4006a9473274199b9d30959868a57578f1e61925aa071a10";

// ---------------------------------------------------------------- spec

export type FieldSpec =
  | { t: "string" | "number" | "boolean"; nullable?: boolean }
  | { t: "array"; nullable?: boolean; items: FieldSpec }
  | { t: "object"; nullable?: boolean; props: Record<string, FieldSpec> }
  | { t: "const"; value: number };

const NAME_VERSION: FieldSpec = {
  t: "object",
  props: { name: { t: "string" }, version: { t: "number" } },
};

/** The row shapes, keyed as the schema's `$defs` are. */
export const ROWS: Record<string, Record<string, FieldSpec>> = {
  snapshot: {
    id: { t: "string" },
    tenantName: { t: "string" },
    capturedAt: { t: "string" },
    ageSeconds: { t: "number" },
    stale: { t: "boolean" },
    staleAfterSeconds: { t: "number" },
    producerVersion: { t: "string" },
    streamTasks: { t: "number" },
    windowTasks: { t: "number", nullable: true },
    subtractionConstraintConvalidated: { t: "boolean" },
  },
  pack: {
    pack: { t: "string" },
    guardsActive: { t: "number" },
    guardsTotal: { t: "number" },
    clustersTotal: { t: "number" },
    decisionsWindow: { t: "number" },
  },
  metric: {
    key: { t: "string" },
    pack: { t: "string", nullable: true },
    status: { t: "string" },
    value: { t: "number", nullable: true },
    denominator: { t: "number", nullable: true },
    note: { t: "string", nullable: true },
  },
  series: {
    pack: { t: "string" },
    key: { t: "string" },
    position: { t: "number" },
    value: { t: "number" },
  },
  guard: {
    guardId: { t: "string" },
    guardVersion: { t: "number" },
    pack: { t: "string" },
    clusterId: { t: "string" },
    subjectType: { t: "string" },
    target: { t: "string" },
    state: { t: "string" },
    artifactDigestAlgo: { t: "string" },
    artifactDigestValue: { t: "string" },
    eligibilityCel: { t: "string" },
    abstainBehavior: { t: "string" },
    auditRate: { t: "number" },
    owner: { t: "string" },
    promotedBy: { t: "string", nullable: true },
    rollback: { t: "string" },
    createdAt: { t: "string" },
    enforces: { t: "array", nullable: true, items: NAME_VERSION },
    subtracts: {
      t: "object",
      nullable: true,
      props: { mode: { t: "string" }, population: { t: "array", items: NAME_VERSION } },
    },
    subtractsStatus: { t: "string" },
    replayVerdict: { t: "string", nullable: true },
    replayReasons: { t: "array", nullable: true, items: { t: "string" } },
    shadowRecorded: { t: "boolean" },
    auditAttributable: { t: "boolean" },
    auditAgreed: { t: "number" },
    auditDisagreed: { t: "number" },
    auditInconclusive: { t: "number" },
    decisionsWindow: { t: "number" },
    lane: { t: "string" },
    ageDays: { t: "number", nullable: true },
  },
  cluster: {
    clusterId: { t: "string" },
    clusterVersion: { t: "number" },
    pack: { t: "string" },
    state: { t: "string" },
    shapePredicate: { t: "string" },
    shapeSubjectType: { t: "string" },
    memberCount: { t: "number" },
    unprovenReason: { t: "string", nullable: true },
    ageDays: { t: "number", nullable: true },
  },
  landing: {
    pack: { t: "string" },
    subjectType: { t: "string" },
    guardId: { t: "string", nullable: true },
    guardVersion: { t: "number", nullable: true },
    compiledDecisions: { t: "number" },
    agentDecisions: { t: "number" },
    humanDecisions: { t: "number" },
    runsOn: { t: "string" },
    lane: { t: "string" },
  },
  deopt: {
    pack: { t: "string" },
    guardId: { t: "string", nullable: true },
    reason: { t: "string" },
    occurredAt: { t: "string" },
    position: { t: "number" },
  },
  counts: {
    signatures_owed: { t: "number" },
    unproven: { t: "number" },
    in_flight: { t: "number" },
  },
};

/** The envelope. Every key always present; four are null only in a refusal. */
export const ENVELOPE: Record<string, FieldSpec> = {
  schema_version: { t: "const", value: SCHEMA_VERSION },
  tenant_id: { t: "string", nullable: true },
  generated_at: { t: "string", nullable: true },
  served_at: { t: "string" },
  stale: { t: "boolean" },
  stale_after_seconds: { t: "number" },
  reason: { t: "string", nullable: true },
  provenance: { t: "string", nullable: true },
  synthetic: { t: "boolean", nullable: true },
  snapshot: { t: "object", nullable: true, props: ROWS.snapshot },
  packs: { t: "array", items: { t: "object", props: ROWS.pack } },
  metrics: { t: "array", items: { t: "object", props: ROWS.metric } },
  series: { t: "array", items: { t: "object", props: ROWS.series } },
  guards: { t: "array", items: { t: "object", props: ROWS.guard } },
  clusters: { t: "array", items: { t: "object", props: ROWS.cluster } },
  landings: { t: "array", items: { t: "object", props: ROWS.landing } },
  deopts: { t: "array", items: { t: "object", props: ROWS.deopt } },
  counts: { t: "object", props: ROWS.counts },
};

// ---------------------------------------------------------------- types

export interface RegistrySnapshotRow {
  id: string;
  tenantName: string;
  capturedAt: string;
  ageSeconds: number;
  stale: boolean;
  staleAfterSeconds: number;
  producerVersion: string;
  streamTasks: number;
  windowTasks: number | null;
  subtractionConstraintConvalidated: boolean;
}

export interface RegistryPackRow {
  pack: string;
  guardsActive: number;
  guardsTotal: number;
  clustersTotal: number;
  decisionsWindow: number;
}

export type RegistryMetricStatus = "measured" | "unknown" | "unproven" | "not_recorded";

export interface RegistryMetric {
  key: string;
  pack: string | null;
  status: RegistryMetricStatus | string;
  value: number | null;
  denominator: number | null;
  note: string | null;
}

export interface RegistrySeriesPoint {
  pack: string;
  key: string;
  position: number;
  value: number;
}

export interface RegistryGuardRow {
  guardId: string;
  guardVersion: number;
  pack: string;
  clusterId: string;
  subjectType: string;
  target: string;
  state: string;
  artifactDigestAlgo: string;
  artifactDigestValue: string;
  eligibilityCel: string;
  abstainBehavior: string;
  auditRate: number;
  owner: string;
  promotedBy: string | null;
  rollback: string;
  createdAt: string;
  enforces: { name: string; version: number }[] | null;
  subtracts: { mode: string; population: { name: string; version: number }[] } | null;
  subtractsStatus: string;
  replayVerdict: string | null;
  replayReasons: string[] | null;
  shadowRecorded: boolean;
  auditAttributable: boolean;
  auditAgreed: number;
  auditDisagreed: number;
  auditInconclusive: number;
  decisionsWindow: number;
  lane: string;
  ageDays: number | null;
}

export interface RegistryClusterRow {
  clusterId: string;
  clusterVersion: number;
  pack: string;
  state: string;
  shapePredicate: string;
  shapeSubjectType: string;
  memberCount: number;
  unprovenReason: string | null;
  ageDays: number | null;
}

export interface RegistryLandingRow {
  pack: string;
  subjectType: string;
  guardId: string | null;
  guardVersion: number | null;
  compiledDecisions: number;
  agentDecisions: number;
  humanDecisions: number;
  runsOn: string;
  lane: string;
}

export interface RegistryDeoptRow {
  pack: string;
  guardId: string | null;
  reason: string;
  occurredAt: string;
  position: number;
}

export interface RegistrySnapshotV1 {
  schema_version: typeof SCHEMA_VERSION;
  tenant_id: string | null;
  generated_at: string | null;
  served_at: string;
  stale: boolean;
  stale_after_seconds: number;
  reason: string | null;
  provenance: string | null;
  synthetic: boolean | null;
  snapshot: RegistrySnapshotRow | null;
  packs: RegistryPackRow[];
  metrics: RegistryMetric[];
  series: RegistrySeriesPoint[];
  guards: RegistryGuardRow[];
  clusters: RegistryClusterRow[];
  landings: RegistryLandingRow[];
  deopts: RegistryDeoptRow[];
  counts: { signatures_owed: number; unproven: number; in_flight: number };
}

// ---------------------------------------------------------------- guard

function matches(value: unknown, spec: FieldSpec): boolean {
  if (value === null) return spec.t !== "const" && spec.nullable === true;
  switch (spec.t) {
    case "const":
      return value === spec.value;
    case "string":
    case "boolean":
      return typeof value === spec.t;
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "array":
      return Array.isArray(value) && value.every((v) => matches(v, spec.items));
    case "object":
      return matchesObject(value, spec.props);
  }
}

function matchesObject(value: unknown, props: Record<string, FieldSpec>): boolean {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj);
  const wanted = Object.keys(props);
  if (keys.length !== wanted.length) return false;
  return wanted.every((k) => k in obj && matches(obj[k], props[k]));
}

/**
 * Exact keys, exact types, nulls only where declared, and the honesty rule:
 * a document with a snapshot carries every declaration, and a document
 * without one carries a reason.
 */
export function isRegistrySnapshotV1(value: unknown): value is RegistrySnapshotV1 {
  if (!matchesObject(value, ENVELOPE)) return false;
  const v = value as RegistrySnapshotV1;
  if (v.snapshot !== null) {
    return (
      v.tenant_id !== null &&
      v.generated_at !== null &&
      v.provenance !== null &&
      v.synthetic !== null
    );
  }
  return v.reason !== null;
}
