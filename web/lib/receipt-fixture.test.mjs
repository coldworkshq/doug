// The fixtures are the every-state artifact the receipt screen was built
// against, and nothing imports them at runtime — deliberately: a receipt that
// cannot be loaded renders an honest error state, never invented evidence.
// That leaves them with no consumer at all, so this file is their consumer.
//
// Two things it pins, and the second is the reason it exists. Conformance:
// `isReceiptResponse` must still accept them, so a rename in receipt-shape.ts
// cannot leave the artifact silently stale. And coverage: the honesty states
// §2.2 enumerates must still each be REACHED by one of these payloads, so a
// fixture edited for some other purpose cannot quietly stop exercising the
// branch it was written to exercise. Both were hand-verified once when the
// fixtures landed; a hand-verified fact is not a pinned one.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  governingLine,
  mergeCaption,
  mergedHeadLine,
  windowOutcome,
  windowPreregLine,
} from "./receipt-merge-view.ts";
import { isReceiptResponse } from "./receipt-shape.ts";
import { promptHashLine, readLine, verdictGap } from "./receipt-verdict-view.ts";

async function load(name) {
  return JSON.parse(await readFile(new URL(`./${name}`, import.meta.url), "utf8"));
}

const STAMPED = "sha256:1c9f8b0d4e72a3516c8fd2b90a4e7c15d36f8021b9ae4c7d05f31682ba9c40de";

test("both fixtures are payloads the validator accepts", async () => {
  assert.equal(isReceiptResponse(await load("receipt-fixture.json")), true);
  assert.equal(isReceiptResponse(await load("receipt-fixture-no-prereg.json")), true);
});

test("the fixture still carries the two merges its every-state claim rests on", async () => {
  const receipt = await load("receipt-fixture.json");
  assert.equal(receipt.merges.length, 2);
  // Exactly one governing merge — the receipt's whole publication story is
  // that a PR has several merges and one of them is the published record.
  assert.equal(receipt.merges.filter((m) => m.publication_governing).length, 1);
  assert.equal(receipt.merges[0].governing_verdict, null);
  assert.equal(receipt.merges[0].merged_head_sha, null);
});

test("the fixture reaches the absent-read and unstamped-prompt states", async () => {
  const receipt = await load("receipt-fixture.json");
  assert.equal(receipt.latest_verdict.read.recorded, false);
  assert.equal(readLine(receipt.latest_verdict.read), "not recorded");
  assert.equal(promptHashLine(receipt.latest_verdict), "not stamped");
});

test("the fixture also reaches the recorded-read and stamped-prompt states", async () => {
  const receipt = await load("receipt-fixture.json");
  const governing = receipt.merges[1].governing_verdict;
  assert.equal(readLine(governing.read), "60000 chars · risk order");
  assert.equal(promptHashLine(governing), governing.prompt_hash);
  // The point of pairing them: the same two functions, on the same payload,
  // must be able to say a number AND say there is none.
  assert.notEqual(readLine(governing.read), readLine(receipt.latest_verdict.read));
});

test("the fixture's latest verdict is not the one that governed publication", async () => {
  const receipt = await load("receipt-fixture.json");
  assert.deepEqual(verdictGap(receipt), {
    latestId: 9112,
    governingId: 9088,
    mergeSha: "a2d70b6e1f4c8395d0b7e2a1c6f39d84b05e7c21",
  });
  // …and the gap is read off the PUBLICATION-GOVERNING merge, not the first
  // one in the list, which here carries no governing verdict at all.
  assert.equal(receipt.merges[1].publication_governing, true);
});

test("the fixture reaches all four window outcomes in one payload", async () => {
  const receipt = await load("receipt-fixture.json");
  const seen = receipt.merges.flatMap((m) => m.adjudication).map(windowOutcome);
  assert.deepEqual(seen, [
    // censored is NEUTRAL, not flag: an unobserved outcome is not a miss (#93).
    { text: "censored", tone: "neutral" },
    { text: "clean", tone: "clear" },
    { text: "revert", tone: "flag" },
    // A null kind reports the JOB's status, never an adjudication word.
    { text: "pending", tone: "neutral" },
  ]);
});

test("the fixture's stamped windows quote their own hash, not the one in force", async () => {
  const receipt = await load("receipt-fixture.json");
  const inForce = receipt.preregistration;
  const stamped = receipt.merges[0].adjudication[0];
  const pending = receipt.merges[1].adjudication[1];

  // The fixture is built so these two differ. If they were ever made equal,
  // the assertion below would pass for the wrong reason: a page reprinting
  // today's env hash over an adjudicated window would look correct.
  assert.notEqual(stamped.prereg_hash, inForce.hash);
  assert.equal(windowPreregLine(stamped, inForce), `${STAMPED} · stamped at adjudication`);
  assert.equal(windowPreregLine(pending, inForce), `${inForce.hash} · will govern this window`);
});

test("the fixture's merge identity and captions render the multi-merge states", async () => {
  const receipt = await load("receipt-fixture.json");
  const [older, governing] = receipt.merges;
  assert.equal(mergedHeadLine(older), "not recorded");
  assert.equal(mergedHeadLine(governing), governing.merged_head_sha);
  assert.equal(mergeCaption(older, receipt.merges.length), "not the governing merge");
  assert.equal(mergeCaption(governing, receipt.merges.length), "governs the published record");
  // The note lives in exactly one place on the page, and this is it.
  assert.equal(governingLine(older), older.publication_note);
  assert.equal(mergeCaption(older, receipt.merges.length).includes(older.publication_note), false);
});

test("the no-prereg fixture reaches the states the main one cannot", async () => {
  // §2.2's `in_force: false` row and its "will govern this window" row are
  // mutually exclusive in one payload — hence a second fixture rather than a
  // state left uncovered. It also carries the single-merge and
  // latest-IS-governing cases, which the two-merge fixture cannot show.
  const receipt = await load("receipt-fixture-no-prereg.json");
  assert.equal(receipt.preregistration.in_force, false);
  assert.equal(receipt.preregistration.hash, null);

  const pending = receipt.merges[0].adjudication[0];
  assert.equal(
    windowPreregLine(pending, receipt.preregistration),
    "no pre-registration in force",
  );
  assert.equal(mergeCaption(receipt.merges[0], receipt.merges.length), "");
  assert.equal(verdictGap(receipt), null);
});
