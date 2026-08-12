// Ported verbatim from console/lib/runs.ts — keep the two in lockstep.
//
// This is the time and provenance half (console/lib/runs.ts:60-186). The
// coverage half of the same console module already lives in web/lib/coverage.ts;
// parseTenantId is deliberately not ported (web's dashboard is scoped by
// session, not by a ?tenant= query param).
//
// Declaration order matches the source, so relativeAge's "defined below,
// hoisted" reference to parseUtc stays true.

/** "2h" / "3d" / "1w" since `iso`. Parsed via `parseUtc` (defined below,
 *  hoisted): run_history's `scored_at` crosses the wire with no zone
 *  designator on sqlite, same as every other timestamp this console
 *  renders — see `parseUtc`'s own docstring. Getting this wrong is worse
 *  here than elsewhere: `new Date(iso)` on a zoneless string reads it as
 *  the server's local time, and on a UTC-behind server every row's "then"
 *  lands after "now" — the `Math.max(0, …)` clamp below then prints "0m"
 *  for every row regardless of true age, not just a shifted one. */
export function relativeAge(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - parseUtc(iso).getTime()) / 1000);
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h`;
  if (seconds < 604_800) return `${Math.round(seconds / 86_400)}d`;
  return `${Math.round(seconds / 604_800)}w`;
}

/** "41s" / "1m12s" between a job's started_at and finished_at, or null when
 *  either is missing. Null, not a dash baked into the string here — the
 *  caller decides how an unmeasurable duration reads next to a status word,
 *  and this never guesses one. */
export function jobDuration(startedAt: string | null, finishedAt: string | null): string | null {
  if (startedAt === null || finishedAt === null) return null;
  const seconds = Math.max(
    0,
    Math.round((new Date(finishedAt).getTime() - new Date(startedAt).getTime()) / 1000),
  );
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m${s}s` : `${s}s`;
}

/** True when an ISO-ish datetime string carries an explicit zone designator
 *  (a trailing "Z", or a "+HH:MM"/"-HH:MM" offset) — the one thing that
 *  tells `Date`'s parser to read it as UTC rather than the runtime's own
 *  local zone. */
function hasZoneDesignator(iso: string): boolean {
  return /(Z|[+-]\d{2}:\d{2})$/.test(iso);
}

/** Parse an ISO-ish datetime as UTC, the way this ledger's own `_utc()`
 *  helper treats a naive value server-side (store.py: "sqlite hands back
 *  naive datetimes for DateTime(timezone=True) columns; every stored value
 *  is UTC, so naive means 'UTC, badly labelled'"). `_utc()` is applied only
 *  to token rows, never in `run_detail` — so on sqlite, every timestamp
 *  this page renders (scored_at, job/outcome timestamps) can cross the wire
 *  with no zone suffix at all.
 *
 *  `new Date(iso)` on a zoneless string parses it as LOCAL time per
 *  ECMA-262 (confirmed: `TZ=America/Los_Angeles node -e
 *  'new Date("2026-08-06T14:22:48").toISOString()'` prints
 *  `2026-08-06T21:22:48.000Z`, a 7-hour shift) — appending "Z" first is
 *  what makes this actually UTC instead of whatever zone the Next.js
 *  server process happens to be running in.
 *
 *  Exported because grouping and sorting order rows by the same timestamps
 *  this module renders as ages. A second parser — `new Date(iso)` inside a
 *  comparator — would order rows by local time while the age column labels
 *  them in UTC, so a row reading "2h" could sort above one reading "1h" and
 *  the table would contradict itself with no error anywhere. */
export function parseUtc(iso: string): Date {
  return new Date(hasZoneDesignator(iso) ? iso : `${iso}Z`);
}

/** "14:22:07 UTC" from an ISO datetime, or "—" for null/unparseable.
 *
 *  Genuinely parses (via `parseUtc`) and re-serializes through
 *  `toISOString()` rather than positionally slicing the source string. A
 *  raw slice would silently mislabel whatever zone the source happened to
 *  be in as UTC — correct only by accident, for whatever serialization is
 *  in use today. */
export function utcClock(iso: string | null): string {
  if (iso === null) return "—";
  const d = parseUtc(iso);
  return Number.isNaN(d.getTime()) ? "—" : `${d.toISOString().slice(11, 19)} UTC`;
}

/** "2026-08-03 14:22:48 UTC" from an ISO datetime — utcClock's full-stamp
 *  sibling, for the one place this page shows a date and not just a
 *  time-of-day. Falls back to the raw string on a value that doesn't
 *  parse, rather than hiding a malformed one behind an em dash. */
export function utcTimestamp(iso: string): string {
  const d = parseUtc(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 19)} UTC`;
}

/** "2026-08-17" — the date portion of an ISO-ish datetime, UTC-normalized
 *  through `parseUtc` rather than sliced from the source string: an
 *  offset-bearing timestamp near a UTC day boundary can name a different
 *  calendar date once actually converted, which slicing the source's own
 *  digits can't see. Falls back to the raw string on unparseable input. */
export function utcDate(iso: string): string {
  const d = parseUtc(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}

/** "08-17" — utcDate's compact MM-DD form, for the spine's tight event
 *  labels. */
export function utcShortDate(iso: string): string {
  const d = parseUtc(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(5, 10);
}
