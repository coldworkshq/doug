/**
 * The one state vocabulary for anything on a screen that is not yet real.
 *
 * Four kinds, closed (design lock T8): `later` (not built), `synthetic`
 * (engine data with its provenance), `unknown` (stale, failed, or a fetch that
 * completed and matched nothing), `off` (a claim gated for this installation,
 * with the flag named). Every chip carries a gloss: one sentence a person can
 * act on. A bare chip reads as a broken product, so `chipGloss` never returns
 * an empty string and the component never renders without one.
 *
 * Chips are chrome, never data: they take no `.data-*` colour, so the
 * design-system pin that closes the data palette at two colours is untouched.
 *
 * The rail's `later` on Evidence is the house convention this extends; its
 * word is kept so a reader learns one word once.
 */
export type ChipKind = "later" | "synthetic" | "unknown" | "off";

export const CHIP_KINDS: readonly ChipKind[] = ["later", "synthetic", "unknown", "off"];

export const CHIP_WORD: Record<ChipKind, string> = {
  later: "later",
  synthetic: "synthetic",
  unknown: "unknown",
  off: "off",
};

/** The sentence beside the word. `detail` is the reason, the provenance, or
 *  the flag, in the source's own words where it gave them. */
export function chipGloss(kind: ChipKind, subject: string, detail?: string): string {
  switch (kind) {
    case "later":
      if (subject === "guards") {
        // A2: the chip states the subtraction claim, so a screenshot beside an
        // incumbent's rules tab reads as a different category of claim, not a
        // missing feature.
        return "Guards remove reviewer work when proven; none proven yet for this repository.";
      }
      return `${capitalize(subject)} is not built yet.`;
    case "synthetic":
      return detail
        ? `Measured on ${detail}, not this repository's pull requests.`
        : "Measured on the engine's synthetic corpus, not this repository's pull requests.";
    case "unknown":
      return detail ? `Not asserted: ${detail}` : "Not asserted: the source did not answer.";
    case "off":
      return detail
        ? `Off for this installation: ${detail}`
        : "Off for this installation.";
  }
}

function capitalize(s: string): string {
  return s.length === 0 ? s : s[0].toUpperCase() + s.slice(1);
}
