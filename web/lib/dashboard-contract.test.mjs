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

test("reader evidence never labels a verdict id as a read id", async () => {
  const page = await readFile(pageUrl, "utf8");
  assert.equal(page.includes("reads #{detail.verdict_id}"), false);
  assert.match(page, /What the reader was given <span>reader evidence<\/span>/);
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

test("coverage, outcomes, and select focus use honest visual semantics", async () => {
  const [page, css] = await Promise.all([
    readFile(pageUrl, "utf8"),
    readFile(cssUrl, "utf8"),
  ]);
  const cutMarker = css.match(/\.coverageRuler > i\s*\{[^}]+\}/)?.[0] ?? "";
  assert.equal(cutMarker.includes("var(--flag-data)"), false);
  assert.match(css, /\.outcomeClear\s*\{[^}]*var\(--clear-data\)/);
  assert.match(css, /\.outcomeFlag\s*\{[^}]*var\(--flag-data\)/);
  assert.match(css, /\.outcomeNeutral\s*\{[^}]*var\(--ink-muted\)/);
  assert.match(page, /outcomeTone\(outcome\.kind\)/);
  assert.match(css, /\.switchControl:focus-within\s*\{[^}]*(outline|box-shadow):/);
});

test("repository connection and every pending setup remain reachable in all dashboard states", async () => {
  const page = await readFile(pageUrl, "utf8");
  const connectMarkup = '<Link href="/install/start" prefetch={false} className={styles.connectRepositories}>Connect repositories</Link>';
  const connect = page.indexOf(connectMarkup);
  const stateBranches = page.indexOf('door.state === "welcome"');
  const pendingStrip = page.indexOf("<PendingConnections connections={connections}");
  assert.ok(connect >= 0 && connect < stateBranches);
  assert.ok(pendingStrip >= 0 && pendingStrip < stateBranches);
  assert.ok(page.includes(connectMarkup));
  assert.match(page, /action=\{finishSetupAction\}/);
  assert.match(page, /name="installation_id"/);
  assert.match(page, />finish setup<\/button>/);
});

test("an expired scope is named as expired, and never counted as never-connected", async () => {
  const page = await readFile(pageUrl, "utf8");

  // The claim the bug made: an operator with a bound installation whose derived
  // scope had aged past entitlements.TTL was shown the never-connected welcome.
  // The welcome may now be reached ONLY from the state that means it, and the
  // page must no longer decide it by counting connections — a stale connection
  // is still a connection.
  assert.match(page, /door\.state === "welcome" \? <NoConnection/);
  assert.equal(page.includes("connections.length === 0 ? <NoConnection"), false);

  // And the state it goes to instead says what happened and what fixes it.
  assert.match(page, /session scope expired — sign out and sign back in to refresh/);
  assert.match(page, /door\.state === "reauthorize" \? <ScopeExpired/);
  assert.match(page, /frontDoor\(connections, organizationId\)/);
});

test("a sign-in whose derivation failed says so instead of claiming nothing is connected", async () => {
  const page = await readFile(pageUrl, "utf8");

  // The welcome is a claim: "you have not connected anything". It is only true
  // when Doug actually asked. When the derivation POST at sign-in failed, Doug
  // never asked, and the honest version of the same screen says which one it is.
  assert.match(page, /const scopeUnconfirmed = \(await cookies\(\)\)\.has\(SCOPE_UNCONFIRMED_COOKIE\)/);
  assert.match(page, /<NoConnection userLabel=\{userLabel\} scopeUnconfirmed=\{scopeUnconfirmed\} \/>/);

  // The note must be GATED ON THE SIGNAL, not merely present in the file. A
  // caveat shown to every first-time visitor is its own small dishonesty — most
  // of them have simply not connected anything — and an ungated one would still
  // satisfy a test that only looked for the words.
  assert.match(page, /\{scopeUnconfirmed && \(/);
  const note = page.indexOf("Doug could not confirm your repositories");
  const gate = page.indexOf("{scopeUnconfirmed && (");
  assert.ok(gate >= 0 && gate < note, "the copy must sit inside the scopeUnconfirmed branch");
});

test("state-mutating install links disable Next prefetch", async () => {
  const page = await readFile(pageUrl, "utf8");
  const installLinks = [...page.matchAll(/<Link\b[^>]*>/g)]
    .map((match) => match[0])
    .filter((markup) => markup.includes('href="/install/start"'));

  assert.equal(installLinks.length, 2);
  for (const markup of installLinks) {
    assert.match(markup, /\bprefetch=\{false\}/);
  }
});

test("finish setup is a POST-only exact pre-bind and post-bind server action", async () => {
  const actions = await readFile(actionsUrl, "utf8");
  const start = actions.indexOf("export async function finishSetupAction");
  const end = actions.indexOf("export async function switchConnectionAction", start);
  const finish = actions.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.match(actions, /^"use server";/);
  assert.equal((finish.match(/getConnections\(/g) ?? []).length, 2);
  assert.match(finish, /formData\.get\("installation_id"\)/);
  assert.equal(finish.includes('formData.get("organization_id")'), false);
  assert.match(finish, /isFinishableSetupConnection/);
  assert.match(finish, /bindInstallation\(auth\.accessToken, installationId\)/);
  assert.match(finish, /readyOrganizationAfterSetup/);
  assert.match(finish, /switchToOrganization\(organizationId, \{ returnTo: "\/dashboard" \}\)/);
  assert.ok(finish.indexOf("isFinishableSetupConnection") < finish.indexOf("bindInstallation"));
  assert.ok(finish.lastIndexOf("getConnections") > finish.indexOf("bindInstallation"));
  assert.ok(finish.indexOf("readyOrganizationAfterSetup") > finish.indexOf("bindInstallation"));
  assert.equal(actions.includes("export async function GET"), false);
});
