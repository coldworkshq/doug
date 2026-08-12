// The needs-you line as a VIEW, not a setting.
//
// It is not a setting because it cannot be: `api/doug/scoring.py:21` reads
// DOUG_THRESHOLD (default 0.62) from the environment, `api/doug/reader.py:347`
// reads DOUG_READER_THRESHOLD, and the resolved value is stamped onto each
// verdict row at scoring time (`api/doug/store.py:74`). `band` is decided
// server-side, once. Nothing on this page can change what Doug did, and a
// control that implied otherwise would be the dishonesty this surface exists
// to refuse.
//
// What it CAN do is re-derive a band from a score Doug already recorded,
// against a line the reader chooses — and say so on screen.
//
// WHY THE LENS IS APPLIED AT THE BOUNDARY, rewriting `band` on the rows,
// rather than threaded through as a parameter: `buildFacets`, `matchesFacets`,
// `groupRunsByPr`, `BandChip` and `runMatchesQuery` (lib/search.ts) all read
// `run.band`, and all five are byte-locked to console's copies by
// lib/console-lockstep.test.mjs. A `lens` parameter would have to be added to
// every one of them, and the lockstep would reject all of it.
//
// Rewriting at the boundary is also what makes the page COHERENT rather than
// merely possible. Because every downstream reader sees the same rewritten
// rows, the band pills, their counts, the chips in the table and the count
// line cannot disagree: there is no state where the "needs you" pill says 12
// and the table shows a different 12.
//
// One consequence of rewriting rather than threading: with a lens active, the
// search box searches what you SEE, not what Doug recorded. Typing "cleared"
// matches rows whose recorded verdict was flagged but that the lens re-banded
// to cleared — `runMatchesQuery` reads the same rewritten `run.band` as
// everything else past the boundary, on purpose. That is the intended
// behaviour, the same coherence this comment argues for above; it was simply
// undocumented until now.
import type { RunSummary } from "./session-api";

/** Scores are 0..1 — `scoring.py` caps its total at 0.99 and `reader.py`
 *  divides risk_score by 100 — so the lens shares that range, endpoints
 *  included. 0 ("flag everything") and 1 ("flag nothing this ledger reaches")
 *  are both legitimate things to ask to see. */
const MIN_LENS = 0;
const MAX_LENS = 1;

/** Query-string value → lens, or null for "no lens".
 *
 *  Unreadable input is ABSENT input, never an error and never a default. The
 *  dangerous default here is 0: `score >= 0` is true of every run, so a
 *  missing param silently coerced to zero would render a ledger in which
 *  everything needs you. Absent is the only honest reading of absent.
 *
 *  Number() is deliberately not used alone: it accepts "", " ", "0x1f" and
 *  "Infinity". The finite check and the range check together are what make
 *  "62" (someone typing the percentage) fail closed rather than flag nothing. */
export function parseThresholdLens(raw: string | undefined): number | null {
  if (raw === undefined) return null;
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return null;
  if (value < MIN_LENS || value > MAX_LENS) return null;
  return value;
}

/** Lens → query-string value, or null when there is no lens.
 *
 *  Unlike `serializeSort`, there is no default to omit. The server's line is
 *  per-verdict and this page never knows a single one for the whole ledger, so
 *  there is no value that means "the same as no lens" — every lens is a
 *  deliberate choice and every one of them is written. */
export function serializeThresholdLens(lens: number | null): string | null {
  return lens === null ? null : String(lens);
}

/** The band this lens assigns to a score.
 *
 *  `>=`, matching `api/doug/scoring.py:146` and `api/doug/reader.py:957`. A run
 *  sitting exactly on the line needs you, on both sides of the system. */
function lensBand(score: number, lens: number): RunSummary["band"] {
  return score >= lens ? "flagged" : "cleared";
}

/** Re-band every row against the lens.
 *
 *  Returns the INPUT ARRAY UNCHANGED when there is no lens, so the default
 *  render is structurally identical to the one that shipped — not merely
 *  claimed to be.
 *
 *  Copies rather than writing through. That is not a style preference: page.tsx
 *  resolves the selected run's summary from the unlensed array so the evidence
 *  pane keeps printing the verdict Doug actually recorded, and a mutating lens
 *  would silently poison it. */
export function applyLens<T extends RunSummary>(rows: T[], lens: number | null): T[] {
  if (lens === null) return rows;
  return rows.map((row) => ({ ...row, band: lensBand(row.score, lens) }));
}

/** How many rows the lens MOVED — not how many it flagged.
 *
 *  The banner prints this number, and it has to be the size of the lens's
 *  effect. Printing the flagged count instead would report a ledger's normal
 *  state as though the lens had caused it.
 *
 *  Compared positionally because `applyLens` is a `map`: index i of the output
 *  is index i of the input, by construction. */
export function rebandedCount(
  before: readonly RunSummary[],
  after: readonly RunSummary[],
): number {
  let moved = 0;
  for (let i = 0; i < before.length && i < after.length; i += 1) {
    if (before[i].band !== after[i].band) moved += 1;
  }
  return moved;
}
