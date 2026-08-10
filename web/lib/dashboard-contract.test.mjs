import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const pageUrl = new URL("../app/dashboard/page.tsx", import.meta.url);
const actionsUrl = new URL("../app/dashboard/actions.ts", import.meta.url);
const cssUrl = new URL("../app/dashboard/dashboard.module.css", import.meta.url);

test("dashboard source keeps the forensic ledger copy and provider-neutral empty state", async () => {
  const page = await readFile(pageUrl, "utf8");
  assert.match(page, /You're in\. Connect GitHub only when you want Doug to review repositories\./);
  assert.match(page, /Lema — separate product/);
  assert.match(page, /What the reader was given/);
  assert.match(page, /coverageRuler/);
  assert.equal(page.includes("tenant all"), false);
  assert.equal(page.includes("health"), false);
  assert.equal(page.includes("illustrative"), false);
});

test("organization switching and sign-out are POST server actions", async () => {
  const [page, actions] = await Promise.all([
    readFile(pageUrl, "utf8"),
    readFile(actionsUrl, "utf8"),
  ]);
  assert.match(actions, /^"use server";/);
  assert.match(actions, /getConnections/);
  assert.match(actions, /switchToOrganization/);
  assert.match(actions, /connections\.some/);
  assert.equal(actions.includes("ensureSignedIn"), false);
  assert.match(
    actions,
    /switchToOrganization\(organizationId, \{ returnTo: "\/dashboard" \}\)/,
  );
  assert.match(page, /action=\{switchConnectionAction\}/);
  assert.match(page, /action=\{signOutAction\}/);
  assert.equal(actions.includes("export async function GET"), false);
});

test("the signed-in console stays on the reference light paper surface", async () => {
  const css = await readFile(cssUrl, "utf8");
  assert.equal(css.includes(":global(.dark)"), false);
  assert.match(css, /--paper:\s*#fcfcfa/);
  assert.match(css, /max-width:\s*1440px/);
});
