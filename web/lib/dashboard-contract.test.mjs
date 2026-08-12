import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const pageUrl = new URL("../app/dashboard/page.tsx", import.meta.url);
const actionsUrl = new URL("../app/dashboard/actions.ts", import.meta.url);
// Was ../app/dashboard/dashboard.module.css until Phase B PR 2 deleted it. The
// four pins that read the module are rewritten below against the mechanisms
// that replaced it — none was dropped. See each test's own note for where its
// intent now lives.
const globalsUrl = new URL("../app/globals.css", import.meta.url);

test("dashboard source keeps the forensic ledger copy and provider-neutral empty state", async () => {
  const page = await readFile(pageUrl, "utf8");
  assert.match(page, /You're in\. Connect GitHub only when you want Doug to review repositories\./);
  assert.match(page, /Lema — separate product/);
  assert.match(page, /What the reader was given/);
  // Intent: A COVERAGE RULER EXISTS ON THIS PAGE. Until Phase B PR 2 this was
  // `/coverageRuler/`, satisfied only by the CSS module's class name — after
  // the port the source literal is `CoverageRuler`, capital C, so the old
  // regex would have failed. It is NOT repaired by loosening to a
  // case-insensitive match, which would pass on any passing mention of the
  // words: the component's import and its use are pinned separately, so
  // importing it without rendering it fails, and rendering something else
  // fails too.
  assert.match(page, /import \{ CoverageRuler \} from "@\/components\/coverage-ruler";/);
  assert.match(page, /<CoverageRuler\b/);
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
  // The deleted dashboard.module.css hardcoded a whole light palette on
  // `.console`, including `--card: #fff`, which shadowed the global `--card`
  // for the entire subtree. THAT is why the dashboard rendered light no matter
  // what web's theme toggle said, and deleting the module without a
  // replacement would have silently retired the property along with the pin.
  //
  // The replacement (RULING 1) is `.dashboard-surface`, which shares ONE
  // declaration block with `:root` — not a second copy of the light values,
  // which would drift. Because those custom properties are declared ON the
  // dashboard's own wrapper, they beat anything `.dark` sets further up the
  // tree: inheritance is the weakest source a custom property can have.
  const [css, page] = await Promise.all([
    readFile(globalsUrl, "utf8"),
    readFile(pageUrl, "utf8"),
  ]);

  const light = css.match(/(?:^|\n):root,\n\.dashboard-surface\s*\{([\s\S]*?)\n\}/);
  assert.ok(
    light,
    "the dashboard scope no longer shares :root's light palette block — it now follows the dark toggle",
  );
  // The exact reference background, not an approximation.
  assert.match(light[1], /--background:\s*#fcfcfa/);
  // The token whose shadowing is what actually forced light before.
  assert.match(light[1], /--card:\s*#ffffff/);

  // ...and the dark palette must never claim the dashboard scope, which is the
  // one edit that would defeat the mechanism above while leaving it in place.
  const dark = css.match(/(?:^|\n)\.dark[^{]*\{/);
  assert.ok(dark, "globals.css lost its .dark block");
  assert.equal(dark[0].includes("dashboard-surface"), false);

  // The mechanism is only real if the page actually mounts it.
  assert.match(page, /className="dashboard-surface/);

  // The 1440px canvas — the reference layout width the design was measured at.
  // It moved from the module's six `max-width: 1440px` rules onto the page's
  // own wrappers.
  assert.match(page, /max-w-\[1440px\]/);
});

test("coverage, outcomes, and select focus use honest visual semantics", async () => {
  const page = await readFile(pageUrl, "utf8");

  // COVERAGE IS A MAGNITUDE, NOT A JUDGEMENT. The forensic ruler's own
  // cut-marker rule is pinned on the component (design-system.test.mjs, "the
  // coverage ruler never spends a judgement colour on a magnitude"); what this
  // page must not do is paint its own table-row coverage cell with a verdict
  // colour. It uses the neutral sequential ramp from globals and nothing else.
  const readCell = page.match(/function CoverageCell\([\s\S]*?\n\}\n/)?.[0] ?? "";
  assert.ok(readCell, "CoverageCell is gone — the read column has no pinned renderer");
  assert.match(readCell, /cov-track/);
  assert.match(readCell, /cov-fill/);
  assert.equal(
    /data-(flag|clear)|var\(--(flag|clear)\)/.test(readCell),
    false,
    "the read column borrows a verdict colour for a measurement",
  );

  // THE THREE-WAY TONE RULE. Was three pins on the module's
  // .outcomeClear/.outcomeFlag/.outcomeNeutral rules; the rule itself now
  // lives in `outcomeToneClass` (runs-time.test.mjs pins that neutral is the
  // ABSENCE of a data colour, never the miss colour). What is pinned here is
  // that BOTH render sites go through it rather than branching inline — an
  // inline ternary written from memory is what dropped the neutral branch in
  // two components at once, the bug that rule exists to prevent.
  const toneCalls = page.match(/outcomeToneClass\(outcomeTone\(/g) ?? [];
  assert.ok(
    toneCalls.length >= 2,
    `every outcome render site must use the shared rule; found ${toneCalls.length}`,
  );
  assert.equal(page.includes('=== "clean"'), false, "outcome tone is branched inline");
  assert.equal(page.includes('=== "censored"'), false, "outcome tone is branched inline");

  // THE ORG SWITCHER'S FOCUS RING. This is the control that changes whose data
  // you are looking at, so it must be visibly focusable. It had no counterpart
  // in the ported component library, which is why the inventory called it the
  // pin most likely to be dropped rather than migrated — and why it is pinned
  // on the CONTROL rather than on a class string. One level of indirection is
  // resolved deliberately: hoisting a long utility string into a const is a
  // normal edit, and it must not be able to drop the ring silently.
  const scopePicker = page.match(/function ScopePicker\([\s\S]*?\n\}\n/)?.[0] ?? "";
  assert.ok(scopePicker, "the scope picker is gone");
  assert.match(scopePicker, /aria-label="Connected space"/);
  const hoisted = scopePicker.match(/<label className=\{(\w+)\}/)?.[1];
  const controlClasses = hoisted
    ? page.match(new RegExp(`const ${hoisted}\\s*=[\\s\\S]*?;\\n`))?.[0] ?? ""
    : scopePicker.match(/<label className="([^"]*)"/)?.[1] ?? "";
  assert.match(
    controlClasses,
    /focus-within:(outline|ring|border)/,
    "the control that switches which org's data you see has no visible focus indicator",
  );
});

test("repository connection and every pending setup remain reachable in all dashboard states", async () => {
  const page = await readFile(pageUrl, "utf8");
  // Reachability is an ORDERING property: both affordances are rendered ABOVE
  // the three-way state branch, so they exist in every state — including the
  // states where the user has nothing yet, and the one where a half-finished
  // install is the only thing to act on.
  //
  // Pinned on the link's href and its label, NEVER on its className. The old
  // pin hardcoded the full markup including `className={styles.connectRepositories}`
  // and derived all three assertions from `indexOf` on it, so restyling the
  // link would have failed the reachability guarantee for a styling reason
  // while the invariant itself was untouched. Pasting the new class string
  // back in here would silently re-couple them.
  const connectLink = page.match(/<Link\b[\s\S]{0,400}?>\s*Connect repositories\s*<\/Link>/);
  assert.ok(connectLink, "the header's 'Connect repositories' link is gone");
  assert.match(connectLink[0], /href="\/install\/start"/);
  // The branch anchor moved with #99: three states became four, dispatched on
  // `door.state` rather than on a connections-length check.
  const stateBranches = page.indexOf('door.state === "welcome"');
  const pendingStrip = page.indexOf("<PendingConnections connections={connections}");
  assert.ok(stateBranches > 0, "the three-way state branch is gone");
  assert.ok(connectLink.index < stateBranches, "connect repositories fell inside a state branch");
  assert.ok(
    pendingStrip >= 0 && pendingStrip < stateBranches,
    "the pending-setup strip fell inside a state branch",
  );
  // `prefetch={false}` on this link is pinned by the next test, over BOTH
  // install links at once — deliberately separate, so a prefetch regression
  // and a reachability regression cannot be confused for one another.
  assert.match(page, /action=\{finishSetupAction\}/);
  assert.match(page, /name="installation_id"/);
  assert.match(page, />finish setup<\/button>/);
});

test("every filter the dashboard offers lives in the URL, not in client memory", async () => {
  // RULING 2. The page's own count line claims "filters live in the URL", and
  // that claim is only true while the page has no client island: console's
  // FacetBar and RunsTable are `"use client"` and keep selection, sort, search
  // and paging in React state, so copying them here would have retired a
  // shareable-URL property the page advertises in shipped prose.
  //
  // Adapted instead: pills and pager are <Link>s, search is a GET <form>, and
  // every target is computed by the pure rewrites in lib/dashboard-view.ts.
  const page = await readFile(pageUrl, "utf8");
  assert.equal(page.includes('"use client"'), false, "the dashboard grew a client boundary");
  assert.equal(page.includes("'use client'"), false, "the dashboard grew a client boundary");
  // The hooks that would only appear if filter state had moved off the URL.
  for (const hook of ["useState", "useEffect", "useSearchParams", "useRouter", "usePathname"]) {
    assert.equal(page.includes(hook), false, `the dashboard reads ${hook} — filter state left the URL`);
  }
  assert.match(page, /filters live in the URL/);
  // …and the claim is backed by a real read of the URL on the server.
  assert.match(page, /const params = await searchParams;/);

  // The per-PR history disclosure is the one control that is NOT URL state,
  // deliberately — which is exactly why it must not be the thing that drags a
  // client boundary in. It is a checkbox and a CSS `:has()` rule, so it stays
  // a real labelled control that keyboard users can operate.
  assert.match(page, /type="checkbox"/);
  assert.match(page, /aria-label=\{`Show the \$\{count\.title\}/);
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

test("the threshold lens never reaches the evidence pane", async () => {
  // The lens is a view over the ledger. The evidence pane is a RECORD of one
  // run, and `detail.threshold` is the line Doug actually scored against —
  // re-banding it would destroy the only place on the page where the real
  // verdict can still be read.
  //
  // Pinned as an ORDERING property, the way the reachability test is: the
  // selected summary must be resolved from the unlensed set, so the lens
  // cannot reach it no matter how the pane is later restyled.
  const page = await readFile(pageUrl, "utf8");
  const selection = page.indexOf("selectedSummary = Number.isInteger(selectedId)");
  const lensApplied = page.indexOf("applyLens(");
  assert.ok(selection > 0, "the selected-run lookup is gone");
  assert.ok(lensApplied > 0, "the lens is never applied");
  assert.match(
    page.slice(selection, selection + 260),
    /fetched\.find\(/,
    "the selected run is no longer resolved from the unlensed fetched set",
  );
  // The pane still prints the recorded line, not the lens.
  assert.match(page, /threshold \{detail\.threshold\.toFixed\(2\)\}/);
  assert.equal(page.includes("threshold {lens"), false);
});

test("an active lens is announced on the page, not just applied to it", async () => {
  // A ledger showing bands that no verdict asserts, with nothing on screen
  // saying so, is the exact failure this surface exists to refuse. The banner
  // is the thing that makes the lens a lens.
  //
  // GATED ON THE SIGNAL, not merely present in the file — the same rule the
  // scopeUnconfirmed note follows. A banner rendered unconditionally would
  // caveat a ledger that has nothing to caveat, and would still satisfy a test
  // that only looked for the words.
  const page = await readFile(pageUrl, "utf8");
  const gate = page.indexOf("{lens !== null && <LensBanner");
  assert.ok(gate > 0, "the lens banner is not gated on there being a lens");
  assert.match(page, /function LensBanner\(/);
  assert.match(page, /re-banded by this view/);
  // It must offer the way out. A caveat you cannot act on is decoration.
  const banner = page.match(/function LensBanner\([\s\S]*?\n\}\n/)?.[0] ?? "";
  assert.match(banner, /thresholdChanges\(null\)/, "the banner has no reset control");
  // ...and it must not spend a data colour on a view state. --flag and --clear
  // are verdicts; the lens is chrome.
  assert.equal(
    /data-(flag|clear)|var\(--(flag|clear)\)/.test(banner),
    false,
    "the lens banner paints a view state in a verdict colour",
  );
});

test("the gear writes the lens to the URL, and the page file stays server-side", async () => {
  // RULING 2 survives the gear. The control is a client leaf because Radix's
  // popover and slider need to be; the STATE it produces is still a query
  // param the server reads, so a shared link reproduces the view exactly and
  // the page's own "filters live in the URL" claim stays true.
  const [page, gear] = await Promise.all([
    readFile(pageUrl, "utf8"),
    readFile(new URL("../components/threshold-gear.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(gear, /^"use client"/);
  // A GET form, not a router push: the lens must land in the address bar.
  assert.match(gear, /method="GET"/);
  assert.match(gear, /action="\/dashboard"/);
  assert.match(gear, /name="threshold"/);
  // The carried params are what stop the gear clearing every pill on submit,
  // the same defect carriedParams already prevents for the search box.
  assert.match(gear, /carried\.map\(/);
  // The page hands it the carried params rather than the gear reaching for the
  // URL itself — the gear has no access to searchParams, by construction.
  assert.match(page, /<ThresholdGear\b/);
  assert.match(page, /carried=\{carriedParams\(params, \["threshold", "page"\]\)\}/);
  // ...and the page file itself still has no client boundary. This is already
  // pinned globally; asserted here too because the gear is the change most
  // likely to break it.
  assert.equal(page.includes('"use client"'), false);
});
