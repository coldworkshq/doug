// Intents: every slot is a figure with its sentence or a chip with its
// reason; the two engine slots decide together and never show a number the
// mapping, the tenant, or a dispatch does not back; the decisions slot never
// renders a bare zero.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const { decisionsSlot, guardSlots, reviewedSlot } = await import("./overview-slots.ts");

const fixtureText = await readFile(
  new URL("./registry-contract/registry-snapshot.v1.fixture.json", import.meta.url),
  "utf8",
);
const snapshot = () => JSON.parse(fixtureText);
const TENANT = JSON.parse(fixtureText).tenant_id;

const run = (band) => ({ band });

test("reviewed counts the ledger and how many needed a reader", () => {
  const slot = reviewedSlot([run("cleared"), run("flagged"), run("cleared")]);
  assert.equal(slot.figure, "3");
  assert.match(slot.sentence, /1 needed a reader/);
  assert.equal(slot.chip, null);
  assert.match(reviewedSlot([]).sentence, /no reviews recorded/);
});

test("decisions is a count of the binding status, or a chip that says which zero", () => {
  const ok = { ok: true, decisions: { ...snapshotDecisions(), count_accepted: 7, binding_status: "accepted", matched_nothing: false } };
  const slot = decisionsSlot(ok, "acme/repo");
  assert.equal(slot.figure, "7");
  assert.match(slot.sentence, /accepted records in acme\/repo/);
  const none = decisionsSlot({ ok: true, decisions: { ...snapshotDecisions(), matched_nothing: true } }, "acme/repo");
  assert.equal(none.figure, null);
  assert.match(none.chip.detail, /usual locations/);
  const failed = decisionsSlot({ ok: false, failure: { status: 502, reason: "the read answered 502", reads_before_diff: null } }, "acme/repo");
  assert.match(failed.chip.detail, /502/);
  assert.equal(decisionsSlot(null, null).chip.kind, "unknown");
});

function snapshotDecisions() {
  return {
    github_repo_id: 1, full_name: "acme/repo", items: [], binding_status: "accepted", count_accepted: 0,
    matched_nothing: false, directory: "docs/decisions", directories_searched: ["docs/decisions"],
    files_seen: 0, files_unparseable: 0, files_unread: 0,
    reads_before_diff: { value: false, deep_read: true, allowlisted: false, reader_enabled: false },
    fetched_at: "2026-09-10T00:00:00Z", cached: false,
  };
}

test("unmapped is the Guards later chip on both engine slots, and nothing is read", () => {
  const { settled, t } = guardSlots(null, null);
  assert.equal(settled.figure, null);
  assert.equal(t.figure, null);
  assert.deepEqual(settled.chip, { kind: "later", subject: "guards" });
  assert.deepEqual(t.chip, settled.chip);
});

test("mapped but unread, or read as unknown, is the reason on both slots", () => {
  assert.match(guardSlots(TENANT, null).t.chip.detail, /was not read/);
  const unknown = guardSlots(TENANT, { kind: "unknown", reason: "the registry answered 404" });
  assert.match(unknown.settled.chip.detail, /404/);
  assert.match(unknown.t.chip.detail, /404/);
});

test("mutation: a payload for another tenant never becomes a figure", () => {
  const { settled } = guardSlots("some-other-tenant", { kind: "snapshot", snapshot: snapshot() });
  assert.equal(settled.figure, null);
  assert.match(settled.chip.detail, /mapped to some-other-tenant/);
});

test("mutation: no dispatch means no T, even with a measured metric", () => {
  const s = snapshot();
  s.landings = s.landings.map((l) => ({ ...l, compiledDecisions: 0 }));
  const { t } = guardSlots(TENANT, { kind: "snapshot", snapshot: s });
  assert.equal(t.figure, null);
  assert.match(t.chip.detail, /no guard has dispatched/);
});

test("a mapped, matching, dispatched snapshot renders both figures with the provenance sentence", () => {
  const { settled, t } = guardSlots(TENANT, { kind: "snapshot", snapshot: snapshot() });
  assert.equal(settled.figure, "38%");
  assert.equal(t.figure, "0.62");
  assert.match(settled.sentence, /measured on Coldworks wind tunnel corpus/);
  assert.match(settled.sentence, /not this repository's pull requests/);
  assert.equal(t.sentence, settled.sentence);
});

test("a metric the registry does not assert is a chip with its note, not a number", () => {
  const s = snapshot();
  s.metrics = s.metrics.map((m) => (m.key === "t" ? { ...m, status: "unknown", value: null, note: "stale mirror" } : m));
  const { settled, t } = guardSlots(TENANT, { kind: "snapshot", snapshot: s });
  assert.equal(settled.figure, "38%");
  assert.equal(t.figure, null);
  assert.match(t.chip.detail, /stale mirror/);
});
