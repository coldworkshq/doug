import type { ReactNode } from "react";

import type { DocsStatus } from "@/lib/docs-nav";

import styles from "./docs.module.css";

export type ChipTone = "coolant" | "ember" | "molten" | "open";

const TONE: Record<ChipTone, string> = {
  coolant: styles.chipCoolant,
  ember: styles.chipEmber,
  molten: styles.chipMolten,
  open: styles.chipOpen,
};

/** A state, said in words. The colour never carries the state alone: every
 *  chip prints its label, so a reader who cannot tell ember from molten
 *  still reads "designed" or "not yet". */
export function Chip({ tone, children }: { tone: ChipTone; children: ReactNode }) {
  return <span className={`${styles.chip} ${TONE[tone]}`}>{children}</span>;
}

const STATUS: Record<DocsStatus, { label: string; tone: ChipTone }> = {
  available: { label: "Available", tone: "coolant" },
  preview: { label: "Preview", tone: "ember" },
  planned: { label: "Planned", tone: "open" },
};

/** The chip beside a page's eyebrow: "this claim is live," "this is a
 *  preview," or "this doesn't exist yet." `label` replaces the word, never
 *  the tone, so a page can say what kind of preview it is. */
export function StatusBadge({ status, label }: { status: DocsStatus; label?: string }) {
  const { label: word, tone } = STATUS[status];
  return <Chip tone={tone}>{label ?? word}</Chip>;
}
