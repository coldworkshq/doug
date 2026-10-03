import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// The door at / is public/landing.html (ADR-0034).
const landing = await readFile(new URL("../public/landing.html", import.meta.url), "utf8");

test("the door invites no App install while Reviews is closed to new installs", () => {
  // Reviews is not open to new installs. Re-adding an install link is the
  // decision to open it, so change this test in the same pull request.
  assert.equal(/github\.com\/apps\//.test(landing), false, "the door links to a GitHub App install page");
  assert.match(landing, /not open to new installs yet/);
});

test("the door promises no tier without model reads while the deep read defaults on", () => {
  // New repositories default to the deep read (api/doug/store.py, deep_read
  // server_default true) and production runs DOUG_READER=1. No customer model
  // key exists in api/doug. A visitor who read any of these would get
  // something else on install.
  for (const claim of [/no model reads/i, /no model at all/i, /your own model keys/i]) {
    assert.equal(claim.test(landing), false, `the door still claims ${claim}`);
  }
});
