"use server";

import { revalidatePath } from "next/cache";

import { isError, postExamplePackAdjudication } from "@/lib/api";
import { adjudicationActionMessage, type Disposition } from "@/lib/example-packs";

export interface AdjudicationActionState {
  status: "idle" | "success" | "error";
  message: string;
}

const FIELD_NAMES = new Set([
  "disposition",
  "receipt_kind",
  "receipt_locator",
  "receipt_detail",
  "receipt_sha256",
  "expected_current_adjudication_id",
]);
const DISPOSITIONS = new Set<Disposition>([
  "disproved",
  "verified_actionable",
  "verified_accepted_nonactionable",
  "unknown",
]);

function one(form: FormData, name: string): string {
  const values = form.getAll(name);
  if (values.length !== 1 || typeof values[0] !== "string") {
    throw new TypeError(`${name} must appear exactly once`);
  }
  return values[0].trim();
}

function bounded(value: string, name: string, maximum: number): string {
  if (value.length > maximum) throw new TypeError(`${name} is too long`);
  return value;
}

export async function adjudicateFinding(
  cohortId: string,
  packHash: string,
  findingId: string,
  _previous: AdjudicationActionState,
  formData: FormData,
): Promise<AdjudicationActionState> {
  try {
    for (const key of formData.keys()) {
      if (!FIELD_NAMES.has(key) && !key.startsWith("$ACTION_")) {
        throw new TypeError(`unexpected field ${key}`);
      }
    }
    if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(cohortId)) {
      throw new TypeError("invalid cohort id");
    }
    if (!/^[0-9a-f]{64}$/.test(packHash) || !/^[0-9a-f]{64}$/.test(findingId)) {
      throw new TypeError("invalid evidence identity");
    }
    const dispositionValue = one(formData, "disposition");
    if (!DISPOSITIONS.has(dispositionValue as Disposition)) {
      throw new TypeError("invalid disposition");
    }
    const disposition = dispositionValue as Disposition;
    const kind = bounded(one(formData, "receipt_kind"), "receipt kind", 120);
    const locator = bounded(one(formData, "receipt_locator"), "receipt locator", 500);
    const detail = bounded(one(formData, "receipt_detail"), "receipt detail", 1000);
    const receiptSha = one(formData, "receipt_sha256");
    const expected = one(formData, "expected_current_adjudication_id");
    if (receiptSha && !/^[0-9a-f]{64}$/.test(receiptSha)) {
      throw new TypeError("receipt SHA-256 must be 64 lowercase hex characters");
    }
    if (expected && !/^[0-9a-f]{64}$/.test(expected)) {
      throw new TypeError("observed adjudication head is invalid");
    }
    const receiptStarted = Boolean(kind || locator || detail || receiptSha);
    if (receiptStarted && !(kind && locator && detail)) {
      throw new TypeError("a receipt needs kind, locator, and detail");
    }
    if (disposition !== "unknown" && !receiptStarted) {
      throw new TypeError("a conclusive disposition requires a receipt");
    }

    const result = await postExamplePackAdjudication(cohortId, packHash, findingId, {
      disposition,
      evidence: receiptStarted
        ? [{ kind, locator, detail, sha256: receiptSha || null }]
        : [],
      verifier_receipts: [],
      expected_current_adjudication_id: expected || null,
    });
    if (isError(result)) {
      return { status: "error", message: adjudicationActionMessage(result.error) };
    }
    revalidatePath("/example-packs");
    revalidatePath(`/example-packs/${packHash}`);
    return {
      status: "success",
      message: `Recorded ${result.disposition.replaceAll("_", " ")} · ${result.adjudication_id.slice(0, 10)}`,
    };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Invalid adjudication",
    };
  }
}
