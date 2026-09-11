// Intents: every slot is a figure with its sentence or a chip with its
// reason; a full ledger page is said as "500+", never as a total; the two
// engine slots decide together and never show a number the mapping, the
// reader, or a dispatch does not back; a metric carried by several packs is
// not one number; the decisions slot tells a failed read from no repository.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const { decisionsSlot, guardSlots, pickMetric, reviewedSlot } = await import("./overview-slots.ts");

const fixtureText = await readFile(
  new URL("./registry-contract/registry-snapshot.v1.fixture.json", import.meta.url),
  "utf8",
);
const snapshot = () => JSON.parse(fixtureText);
const TENANT = JSON.parse(fixtureText).tenant_id;
const mapped = { tenant: TENANT, error: null };
const unmapped = { tenant: null, error: null };

const run = (band) => ({ band });

test("reviewed counts the ledger and how many needed a reader", () => {
  const slot = reviewedSlot([run("cleared"), run("flagged"), run("cleared")], 500);
  assert.equal(slot.figure, "3");
  assert.match(slot.sentence, /1 needed a reader/);
  assert.equal(slot.chip, null);
  assert.match(reviewedSlot([], 500).sentence, /no reviews recorded/);
});

test("mutation: a full page is 500+ over the most recent 500, never a total", () => {
  const runs = Array.from({ length: 500 }, (_, i) => run(i % 7 === 0 ? "flagged" : "cleared"));
  const slot = reviewedSlot(runs, 500);
  assert.equal(slot.figure, "500+");
  assert.match(slot.sentence, /over the most recent 500/);
  assert.equal(reviewedSlot(runs.slice(0, 499), 500).figure, "499");
});

test("a failed ledger read is a chip, decided by the slot and not by the page", () => {
  const slot = reviewedSlot(null, 500);
  assert.equal(slot.figure, null);
  assert.deepEqual(slot.chip, { kind: "unknown", subject: "reviews", detail: "the ledger did not answer" });
});

function decisions(over = {}) {
  return {
    github_repo_id: 1, full_name: "acme/repo", items: [], binding_status: "accepted", count_accepted: 0,
    matched_nothing: false, directory: "docs/decisions", directories_searched: ["docs/decisions"],
    files_seen: 0, files_unparseable: 0, files_unread: 0,
    reads_before_diff: { value: false, deep_read: true, allowlisted: false, reader_enabled: false },
    fetched_at: "2026-09-10T00:00:00Z", cached: false, ...over,
  };
}

test("decisions is a count of the binding status, or a chip that says which zero", () => {
  const slot = decisionsSlot({ ok: true, decisions: decisions({ count_accepted: 7 }) }, "acme/repo");
  assert.equal(slot.figure, "7");
  assert.match(slot.sentence, /accepted records in acme\/repo/);
  const none = decisionsSlot({ ok: true, decisions: decisions({ matched_nothing: true }) }, "acme/repo");
  assert.equal(none.figure, null);
  assert.match(none.chip.detail, /usual locations/);
  const failed = decisionsSlot({ ok: false, failure: { status: 502, reason: "the read answered 502", reads_before_diff: null } }, "acme/repo");
  assert.match(failed.chip.detail, /502/);
});

test("mutation: a thrown read names the repository; only a missing repository says none is connected", () => {
  assert.match(decisionsSlot(null, "acme/repo").chip.detail, /the read of acme\/repo did not answer/);
  assert.match(decisionsSlot(null, null).chip.detail, /no repository is connected/);
});

test("unmapped is the Guards later chip on both engine slots", () => {
  const { settled, t } = guardSlots(unmapped, null);
  assert.equal(settled.figure, null);
  assert.deepEqual(settled.chip, { kind: "later", subject: "guards" });
  assert.deepEqual(t.chip, settled.chip);
});

test("a malformed mapping env is the error on both slots, for every installation, never a throw", () => {
  const { settled, t } = guardSlots({ tenant: null, error: "DOUG_GUARDS_INSTALLATIONS entry \"x\" is not <installation id>:<engine tenant id>" }, null);
  assert.match(settled.chip.detail, /DOUG_GUARDS_INSTALLATIONS/);
  assert.equal(t.chip.detail, settled.chip.detail);
});

test("mapped but unread, or read as unknown, is the reason on both slots", () => {
  assert.match(guardSlots(mapped, null).t.chip.detail, /was not read/);
  const unknown = guardSlots(mapped, { kind: "unknown", reason: "the registry serves tenant x; this installation is mapped to y" });
  assert.match(unknown.settled.chip.detail, /mapped to y/);
});

test("mutation: no dispatch means no T, even with a measured metric", () => {
  const s = snapshot();
  s.landings = s.landings.map((l) => ({ ...l, compiledDecisions: 0 }));
  const { t } = guardSlots(mapped, { kind: "snapshot", snapshot: s });
  assert.equal(t.figure, null);
  assert.match(t.chip.detail, /no guard has dispatched/);
});

test("a mapped, dispatched snapshot renders both figures with the provenance sentence", () => {
  const { settled, t } = guardSlots(mapped, { kind: "snapshot", snapshot: snapshot() });
  assert.equal(settled.figure, "38%");
  assert.equal(t.figure, "0.62");
  assert.match(settled.sentence, /measured on Coldworks wind tunnel corpus/);
  assert.match(settled.sentence, /not this repository's pull requests/);
  assert.equal(t.sentence, settled.sentence);
});

test("a metric the registry does not assert is a chip with its note, not a number", () => {
  const s = snapshot();
  s.metrics = s.metrics.map((m) => (m.key === "t" ? { ...m, status: "unknown", value: null, note: "stale mirror" } : m));
  const { settled, t } = guardSlots(mapped, { kind: "snapshot", snapshot: s });
  assert.equal(settled.figure, "38%");
  assert.equal(t.figure, null);
  assert.match(t.chip.detail, /stale mirror/);
});

test("mutation: a key carried by several packs is not one number; a tenant-level figure wins", () => {
  const s = snapshot();
  s.metrics.push({ key: "coverage", pack: "other", status: "measured", value: 0.9, denominator: 10, note: null });
  assert.deepEqual(pickMetric(s, "coverage").ambiguous, ["docs", "other"]);
  const { settled } = guardSlots(mapped, { kind: "snapshot", snapshot: s });
  assert.equal(settled.figure, null);
  assert.match(settled.chip.detail, /several packs \(docs, other\)/);
  s.metrics.push({ key: "coverage", pack: null, status: "measured", value: 0.5, denominator: 20, note: null });
  assert.equal(guardSlots(mapped, { kind: "snapshot", snapshot: s }).settled.figure, "50%");
});
