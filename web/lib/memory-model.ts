/**
 * What the Memory screen shows, decided here so the page stays a template.
 *
 * Three decisions, none of them the page's:
 *
 * - Which records the filter and the search keep. The status filter defaults
 *   to `accepted`, which is the only status the reader is fed (`BINDING` in
 *   the API); `all` shows history too, with its status beside it. The search
 *   is lexical over id, title, and body, in the browser's copy of the list,
 *   because the whole list is already here and a round trip would buy
 *   nothing.
 * - Which zero a zero is. `matched_nothing` is the walk's own answer and
 *   renders the `unknown` chip naming where it looked; a filter or a search
 *   that keeps nothing is a different sentence, not a chip, because the
 *   records exist.
 * - What the honesty line says. It follows the three flags, all three; the
 *   list never does.
 */
import type { DecisionRecord, ReadsBeforeDiff, RepositoryDecisions } from "./session-api";

export type StatusFilter = "accepted" | "all";

export function parseStatusFilter(raw: string | string[] | undefined): StatusFilter {
  return raw === "all" ? "all" : "accepted";
}

export function normalizeQuery(raw: string | string[] | undefined): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return (value ?? "").trim().toLowerCase();
}

export function matchesQuery(record: DecisionRecord, query: string): boolean {
  if (query === "") return true;
  const haystack = `${record.id}\n${record.title}\n${record.body}`.toLowerCase();
  return query.split(/\s+/).every((term) => haystack.includes(term));
}

export function selectRecords(
  records: DecisionRecord[],
  status: StatusFilter,
  query: string,
): DecisionRecord[] {
  return records
    .filter((r) => status === "all" || r.status.toLowerCase() === "accepted")
    .filter((r) => matchesQuery(r, query))
    .sort((a, b) => a.id.localeCompare(b.id));
}

/** The honest-zero gloss: where Doug looked, in the API's own order. */
export function matchedNothingGloss(decisions: RepositoryDecisions): string {
  const where = decisions.directories_searched.join(", ");
  const skipped =
    decisions.files_seen > 0
      ? ` ${decisions.files_seen} markdown file${decisions.files_seen === 1 ? "" : "s"} were there and none carried a title and a status in frontmatter.`
      : "";
  return `no decision records were found in the usual locations (${where}).${skipped}`;
}

/** The line, with the flag that turns it off named in the API's terms. */
export function readsBeforeDiffLine(flags: ReadsBeforeDiff): { on: boolean; detail: string } {
  if (flags.value) {
    return { on: true, detail: "Doug reads these records before it reads a diff." };
  }
  const off: string[] = [];
  if (!flags.deep_read) off.push("deep read is off for this repository");
  if (!flags.allowlisted) off.push("the intent tier is not enabled for this installation");
  if (!flags.reader_enabled) off.push("the reader is off for this service");
  return { on: false, detail: off.join("; ") + "." };
}

/** The GitHub page for a record at the default branch's HEAD. */
export function recordHref(fullName: string, ref: string): string {
  return `https://github.com/${fullName}/blob/HEAD/${ref.split("/").map(encodeURIComponent).join("/")}`;
}
