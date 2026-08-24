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
const gearUrl = new URL("../components/threshold-gear.tsx", import.meta.url);

/** A source file with its comments removed.
 *
 *  Every assertion below that says "this must NOT appear" needs it. The
 *  comments in these files EXPLAIN the rules — the deep-read copy's docblock
 *  quotes "default · 0.30 deep read / 0.62 fallback" as the string it is
 *  describing, and actions.ts spells out `revalidatePath(...paths)` as the
 *  call it refuses to make. Scanning the raw file, a negative pin fails on the
 *  prose that documents it, which trains the next person to delete the
 *  explanation rather than keep the rule. */
function code(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

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
  const [css, page, gear] = await Promise.all([
    readFile(globalsUrl, "utf8"),
    readFile(pageUrl, "utf8"),
    readFile(gearUrl, "utf8"),
  ]);

  const light = css.match(/(?:^|\n):root,\n\.dashboard-surface,\n\.paper-tokens\s*\{([\s\S]*?)\n\}/);
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

  // The block gained `.paper-tokens` (a third selector on the SAME
  // declarations, not a second copy) so that content Radix portals out of the
  // wrapper — the threshold gear's popover — still gets the paper palette.
  // Pinned as part of the shared block precisely so nobody "fixes" a dark
  // popover by pasting the values into a component.
  assert.match(gear, /className="paper-tokens/);

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

test("the 14-day and 60-day outcomes render as two independent cells, never one collapsed to the other", async () => {
  // RULING (plan D-outcome-surface, project owner): 14-day and 60-day are two
  // separate, always-shown, separately-labelled columns, each with its own
  // pending state — NOT one column resolving to the strongest signal. They
  // are different observations of different windows, and collapsing them
  // (`outcome_60 ?? outcome_14`) would let a row's rendered "clean" silently
  // mean either window depending on data the reader cannot see. A row where
  // 14d reads "clean" and 60d reads "pending" is the honest picture, and
  // showing both is what makes the clock visible.
  //
  // Mutation proof (brief Step 5): collapse the two cells into one resolving
  // to `outcome_60 ?? outcome_14` and this test fails — the independent
  // `outcomeLabel(run.outcome_14)` call the first assertion requires is gone,
  // replaced by a single call fed the fallback expression.
  const page = await readFile(pageUrl, "utf8");
  assert.match(
    page,
    /outcomeToneClass\(outcomeTone\(run\.outcome_14\)\)[\s\S]{0,40}outcomeLabel\(run\.outcome_14\)/,
    "the 14-day cell must render run.outcome_14 through the shared tone/label rule, on its own",
  );
  assert.match(
    page,
    /outcomeToneClass\(outcomeTone\(run\.outcome_60\)\)[\s\S]{0,40}outcomeLabel\(run\.outcome_60\)/,
    "the 60-day cell must render run.outcome_60 through the shared tone/label rule, on its own",
  );
  for (const collapsed of ["outcome_60 ?? run.outcome_14", "run.outcome_60 ?? run.outcome_14", "outcome_60 ?? outcome_14"]) {
    assert.equal(
      page.includes(collapsed),
      false,
      `the outcome columns must not collapse to one value (found "${collapsed}")`,
    );
  }
  // Both columns carry their own label — a row is never left to infer which
  // window a bare "outcome" header meant.
  assert.match(page, /label:\s*"14d outcome"/);
  assert.match(page, /label:\s*"60d outcome"/);
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
  // The two submit buttons own `threshold` between them. A hidden input
  // alongside them would submit BOTH — a named submit button does not replace
  // other fields — and page.tsx's `value()` helper takes the first of a
  // repeated key, so "Clear" would silently re-apply the current lens. That
  // shipped once; this is what stops it shipping again.
  assert.equal(
    /<input[^>]*type="hidden"[^>]*name="threshold"/.test(gear),
    false,
    "a hidden threshold field would collide with the submit buttons that carry it",
  );
  const thresholdFields = gear.match(/name="threshold"/g) ?? [];
  assert.equal(thresholdFields.length, 2, "threshold must be carried by exactly the two submit buttons");

  // The slider steps by 0.01 and binary floating point turns some of those
  // steps into 0.30000000000000004. String(draft) put that in the address bar
  // verbatim: a URL that disagrees with the 0.30 printed beside the slider, and
  // two links to the same view that do not look like the same view — the exact
  // confusion serializeSort's "a param that is always present carries no
  // information" note exists to prevent.
  assert.equal(gear.includes("value={String(draft)}"), false, "the lens param is not canonicalised");
  assert.match(gear, /value=\{draft\.toFixed\(2\)\}/);
  // The carried params are what stop the gear clearing every pill on submit,
  // the same defect carriedParams already prevents for the search box.
  assert.match(gear, /carried\.map\(/);
  // The page hands it the carried params rather than the gear reaching for the
  // URL itself — the gear has no access to searchParams, by construction.
  assert.match(page, /<ThresholdGear\b/);
  assert.match(page, /carried=\{carriedParams\(params, \["threshold", "page"\], \{ keepRun: true \}\)\}/);
  // The gear seeds its slider once per mount and is KEYED on the lens, rather
  // than resyncing from the prop inside an effect. setState in an effect is a
  // lint error here (react-hooks/set-state-in-effect) and would also stomp a
  // drag in progress if a navigation landed mid-gesture.
  assert.equal(gear.includes("useEffect"), false, "the gear resyncs state in an effect");
  // Loosened from a literal pin on the key expression's exact source text:
  // hoisting the key into a `const` is a legitimate refactor that preserves
  // this property and would otherwise fail a pin that only matched one
  // formatting of it. What is real is that ThresholdGear IS keyed, and the
  // key's expression references `lens` — that is what forces the remount when
  // the applied lens changes, which is the property under test.
  const gearTag = page.match(/<ThresholdGear\b[^>]*>/)?.[0] ?? "";
  assert.ok(gearTag, "the gear is no longer rendered");
  const keyExpr = gearTag.match(/\bkey=\{([^}]*)\}/)?.[1] ?? "";
  assert.ok(keyExpr, "<ThresholdGear> lost its key");
  assert.match(keyExpr, /\blens\b/, "the gear's key does not reference `lens`");
  // ...and the page file itself still has no client boundary. This is already
  // pinned globally; asserted here too because the gear is the change most
  // likely to break it.
  assert.equal(page.includes('"use client"'), false);
});

test("the preview gear and the per-repo flag line setting are never called the same thing", async () => {
  // Two controls, one view, opposite powers. The gear RE-BANDS what is already
  // on screen; the flag line CHANGES WHAT DOUG DOES NEXT. While the gear read
  // "needs-you line" they shared a name on the same table — and moving the gear
  // visibly changes the "needs you" count sitting one column left of the
  // setting, so the wrong one looks like it took effect. Different words are
  // the fix, and this is what stops them converging again.
  const gear = await readFile(new URL("../components/threshold-gear.tsx", import.meta.url), "utf8");
  const control = await readFile(new URL("../components/flag-line-control.tsx", import.meta.url), "utf8");
  assert.match(gear, />\s*preview at…\s*</);
  assert.equal(gear.includes("needs-you line"), false, "the gear no longer claims to be the line");
  assert.match(control, /flag line/);
  // FORWARD-ONLY, said where the change is made. The API writes the setting for
  // future scoring runs only: verdicts already recorded keep the line they were
  // scored against, and an open PR keeps its existing check until a new commit
  // triggers a re-review. A control that quietly implied it rewrote history
  // would be the dishonesty this whole surface exists to refuse.
  assert.match(control, /Applies to reviews from now on/);
  assert.match(control, /open PRs keep their check until a new commit/);
  // BOTH defaults are printed when the repository is unset, because production
  // scores with the reader and falls back to the deterministic line — one
  // number would be a claim that is false half the time. Pinned on the template
  // around the numbers rather than on "0.30"/"0.62": the control renders
  // `defaults.reader.toFixed(2)` from the API response, so pinning the digits
  // would pin this suite to one deployment's environment.
  assert.match(control, /on deep reads and/);
  assert.match(control, /when the reader didn/);
  assert.match(control, /defaults\.reader\.toFixed\(2\)/);
  assert.match(control, /defaults\.fallback\.toFixed\(2\)/);
});

test("setFlagLineAction is a server action wired to the repositories table", async () => {
  const actions = await readFile(actionsUrl, "utf8");
  const page = await readFile(pageUrl, "utf8");
  assert.match(actions, /^"use server";/);
  assert.match(actions, /export async function setFlagLineAction/);
  assert.equal(actions.includes("export async function GET"), false);
  assert.match(page, /FlagLineControl/);
});

test("the runs table does not spend a column on scoring tier", async () => {
  // Hosted production sets DOUG_READER=1, so most ledger rows read "reader".
  // A deterministic fallback still exists — the selected-run pane is the
  // surface for the grade, not an always-on table column.
  const page = await readFile(pageUrl, "utf8");
  const columns = page.match(/const COLUMNS[^=]*=\s*\[([\s\S]*?)\n\];/)?.[1];
  assert.ok(columns, "COLUMNS is gone");
  assert.equal(
    /label: "tier"/.test(columns),
    false,
    "COLUMNS still declares a tier column",
  );

  const cells = page.match(/function RunCells\([\s\S]*?\n\}\n/)?.[0] ?? "";
  assert.ok(cells, "RunCells is gone");
  assert.equal(/\{\s*run\.tier\s*\}/.test(cells), false, "RunCells still prints run.tier");

  const headerCount = [...columns.matchAll(/label: "/g)].length;
  const cellCount = [...cells.matchAll(/<TableCell\b/g)].length;
  assert.equal(
    cellCount,
    headerCount,
    `RunCells has ${cellCount} cells against COLUMNS' ${headerCount} headers`,
  );

  assert.match(page, /<dt className="uppercase text-muted-foreground">tier<\/dt>/);

  // 154px was the slack 940 carried above fixed+160 with the tier column
  // still in COLUMNS. Deleting the column and leaving min-w at 940 would
  // leave the floor above the content — which the header-pin test's comment
  // forbids and does not enforce.
  const runTable = page.match(/function RunTable\([\s\S]*?\n\}\n/)?.[0] ?? "";
  const widths = [...columns.matchAll(/cls: "w-\[(\d+)px\]/g)].map((m) => Number(m[1]));
  const fixed = widths.reduce((total, width) => total + width, 0);
  const declared = Number(runTable.match(/min-w-\[(\d+)px\]/)?.[1] ?? 0);
  assert.ok(
    declared <= fixed + 160 + 154,
    `min-w-[${declared}px] is ${declared - fixed - 160}px above the columns; deleting tier left the floor behind`,
  );
});

test("the ledger is bounded and its header stays put", async () => {
  const page = await readFile(pageUrl, "utf8");
  const runTable = page.match(/function RunTable\([\s\S]*?\n\}\n/)?.[0] ?? "";
  assert.ok(runTable, "RunTable is gone");

  // The bound goes on the container <Table> ALREADY renders. A max-h wrapper
  // placed around <Table> would nest a second scroll container inside the
  // first, and a sticky <th> in the inner one scrolls away with the rows it
  // exists to pin. lib/ui-primitives.test.mjs pins the prop; this pins the use.
  assert.match(runTable, /containerClassName/);
  assert.match(runTable, /max-h-\[/);
  // Asserted against TH, where `sticky` actually lives, NOT against RunTable's
  // body — the brief originally pinned it on the function text, which a doc
  // comment mentioning the word satisfies just as well as the real class. A
  // pin a comment can pass is not a pin.
  const th = page.match(/const TH =[\s\S]*?;\n/)?.[0] ?? "";
  assert.ok(th, "the TH constant is gone");
  assert.match(th, /\bsticky\b/);
  assert.match(th, /\btop-0\b/);
  // An opaque background is not decoration: without it the rows scroll
  // visibly underneath the pinned header.
  assert.match(th, /\bbg-background\b/);

  // Collapsed borders are painted by the table, not the cell, and vanish from
  // a sticky header. The separated model is what keeps the header's rule
  // visible while it is pinned — without it the bound "works" and the header
  // silently loses its underline against the scrolling rows.
  assert.match(runTable, /border-separate/);
  assert.match(runTable, /border-spacing-0/);

  // Horizontal scrolling was already there and is NOT replaced by the vertical
  // bound — eight columns still need it in any column narrower than they are.
  //
  // Was a hardcoded `min-w-[980px]`, which measured the ledger when it owned
  // the full 1440 canvas. The split shell put a 400px dock beside it and every
  // fixed column gave up what it could, so 980 became a number no layout used;
  // the pin is now DERIVED from COLUMNS rather than restated, because the
  // property that matters is not "980" but "the table refuses to shrink past
  // what its own columns need". A future width change moves both together, and
  // deleting a column cannot silently leave the floor above the content.
  //
  // SLICE TO ONE ARRAY BEFORE MATCHING. A bare /cls: "w-\[(\d+)px\]/g over the
  // whole file was correct only while COLUMNS was the only column table on the
  // page; REPO_COLUMNS arrived and the scan summed all fourteen widths, failing
  // the runs table for the repositories table's arithmetic. Same defect class
  // as PR #109's cross-row regexes, caught the same way: name the record first.
  const floorFor = (arrayName, tableSource, flexible) => {
    const array = page.match(new RegExp(`const ${arrayName}[^=]*=\\s*\\[([\\s\\S]*?)\\n\\];`))?.[1];
    assert.ok(array, `${arrayName} is gone — its table has no pinned column widths`);
    const widths = [...array.matchAll(/cls: "w-\[(\d+)px\]/g)].map((m) => Number(m[1]));
    assert.ok(widths.length >= 5, `${arrayName} lost its fixed widths; found ${widths.length}`);
    const fixed = widths.reduce((total, width) => total + width, 0);
    const declared = Number(tableSource.match(/min-w-\[(\d+)px\]/)?.[1] ?? 0);
    assert.ok(declared > 0, `the ${arrayName} table lost its horizontal minimum — narrow columns will crush`);
    assert.ok(
      declared >= fixed + flexible,
      `min-w-[${declared}px] is under the ${fixed}px ${arrayName} claims plus ${flexible}px for its flexible column`,
    );
  };

  // The pull request column is the ledger's one flexible column and holds a repo
  // name, a PR number and a title. Below ~160px the title truncates to nothing
  // and the row stops identifying the thing it is a row about.
  floorFor("COLUMNS", runTable, 160);

  // The repositories table's flexible column holds a repo full_name and, on a
  // row the installation no longer lists, a "not connected" marker beside it.
  const repoTable = page.match(/function RepositoryTable\([\s\S]*?\n\}\n/)?.[0] ?? "";
  assert.ok(repoTable, "RepositoryTable is gone");
  assert.match(repoTable, /containerClassName/);
  assert.match(repoTable, /max-h-\[/);
  assert.match(repoTable, /border-separate/);
  floorFor("REPO_COLUMNS", repoTable, 160);
});

test("the per-PR disclosure survives the table swap", async () => {
  // The disclosure is a checkbox and a CSS :has() rule, deliberately — it is
  // the one control that is not URL state, which is exactly why it must not be
  // what drags a client boundary in. Swapping the table markup is the change
  // most likely to lose the <tbody>-per-group structure the selector needs.
  const page = await readFile(pageUrl, "utf8");
  assert.match(page, /className="pr-group"/);
  assert.match(page, /className="pr-toggle sr-only"/);
  assert.match(page, /pr-history/);
  assert.match(page, /type="checkbox"/);
});

test("choosing a space opens it, and still works without JavaScript", async () => {
  // Two clicks to change whose data you are looking at, the second of which was
  // a button labelled "open" beside a select that had already changed, read as
  // a control that had not taken effect. Selection now navigates.
  //
  // The submit control is not deleted. It is rendered server-side and removed
  // once hydration succeeds — NOT wrapped in <noscript>, which covers strictly
  // less: noscript renders only when scripting is DISABLED, so it did nothing
  // in the two cases that actually happen, the seconds before hydration and a
  // bundle that loaded and threw. In both, scripting is on, the noscript
  // content is absent, and the select's handlers are not attached: the form has
  // no working control and the operator cannot switch spaces at all.
  const [page, select, noJs] = await Promise.all([
    readFile(pageUrl, "utf8"),
    readFile(new URL("../components/auto-submit-select.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/no-js-submit.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(select, /^"use client"/);
  assert.match(select, /requestSubmit\(\)/);
  // Arrowing through a native select fires `change` on every keypress, and
  // this form navigates. Committing on each one walks a keyboard user off the
  // page before they reach the option they were aiming for (WCAG 3.2.2). The
  // keyboard path is therefore deferred to an explicit commit — Enter, Tab or
  // blur — while pointer input still commits immediately. Pinned because the
  // naive version is the obvious "simplification" someone will reach for.
  assert.match(select, /BROWSING_KEYS/);
  assert.match(select, /onKeyDown/);
  assert.match(select, /onBlur/);
  assert.match(select, /ArrowDown/);
  // `pending` is armed by a real change, never by a keystroke: a browsing key
  // that moves nothing (ArrowUp on the first option, a type-ahead letter
  // matching nothing) produces no change, so blurring afterwards must not
  // navigate. Arming from the keystroke shipped once and did exactly that.
  assert.match(select, /onPointerDown/);

  // Not merely that the handlers exist: that `pending` is armed where a real
  // change is KNOWN to have happened. Arming it from the keystroke shipped
  // once, and a no-op ArrowUp followed by Tab navigated with nothing chosen.
  const onKeyDownSlice = select.match(/onKeyDown=\{\(event\)[\s\S]*?\n      \}\}/)?.[0] ?? "";
  const onChangeSlice = select.match(/onChange=\{\(event\)[\s\S]*?\n      \}\}/)?.[0] ?? "";
  assert.ok(onKeyDownSlice && onChangeSlice, "the select's handlers could not be located");
  assert.match(onChangeSlice, /pending\.current = true/);
  assert.equal(
    onKeyDownSlice.includes("pending.current = true"),
    false,
    "pending is armed from a keystroke again — a key that moves nothing would commit on blur",
  );

  // Escape means cancel, and it needs handling because the browser does not do
  // it for us here: on a CLOSED select — where arrowing leaves you — Escape
  // reverts nothing, so the selection stays visibly moved and the blur commit
  // would then switch the operator's space after they backed out. "I cancelled"
  // and "the page navigated" is the worst pair on the control that decides
  // whose data you are looking at.
  assert.match(select, /"Escape"/);
  assert.match(select, /entryValue/);
  const onKeyDownEscape = select.match(/if \(event\.key === "Escape"\) \{[\s\S]*?\n {8}\}/)?.[0] ?? "";
  assert.ok(onKeyDownEscape, "the Escape branch is gone");
  assert.match(onKeyDownEscape, /pending\.current = false/);
  assert.match(onKeyDownEscape, /value = entryValue\.current/);

  // The no-JS fallback must not be a <noscript>. Pinned as an ABSENCE too,
  // because <noscript> is the obvious-looking thing to reach for and it is
  // precisely what did not work.
  assert.match(noJs, /^"use client"/);
  assert.match(noJs, /useSyncExternalStore/);
  assert.equal(noJs.includes("useEffect"), false, "the fallback resyncs state in an effect");

  const scopePicker = page.match(/function ScopePicker\([\s\S]*?\n\}\n/)?.[0] ?? "";
  assert.ok(scopePicker, "the scope picker is gone");
  assert.match(scopePicker, /<AutoSubmitSelect/);
  assert.match(scopePicker, /<NoJsSubmit/);
  assert.equal(
    scopePicker.includes("<noscript>"),
    false,
    "the fallback is a <noscript> again — it renders for nobody whose JS is merely broken",
  );
  // The server action is untouched — this changes WHEN the form submits, never
  // what happens when it does.
  assert.match(scopePicker, /action=\{switchConnectionAction\}/);

  // The repo filter is deliberately NOT given the same treatment: it is a GET
  // form on the same page rather than an org switch, and its submit button is
  // a normal, expected control. Pinned so the two are not "made consistent"
  // later without a reason.
  assert.match(page, /<select name="repo"/);
});

test("the PR comment toggle is its own form and cannot carry the flag line with it", async () => {
  // THE WHOLE POINT OF A THIRD FORM. This control is deliberately JS-free, and
  // `formData.get` returns the FIRST entry for a name — so a toggle sharing a
  // <form> with the flag-line input would submit `needs_you_threshold` too, and
  // every "PR comment · off" click would silently re-save (or clear) the line
  // beside it. The assertion is on the toggle form's own slice, not the file:
  // the file obviously contains that field name three lines up.
  const control = await readFile(new URL("../components/flag-line-control.tsx", import.meta.url), "utf8");
  assert.match(control, /PR comment/);
  assert.match(control, /setFlagLineCommentAction/);
  const toggleForm = control.match(/<form action=\{setFlagLineCommentAction\}[\s\S]*?<\/form>/)?.[0] ?? "";
  assert.ok(toggleForm, "the toggle form is gone");
  assert.equal(
    toggleForm.includes('name="needs_you_threshold"'),
    false,
    "the toggle form carries the flag line field — every toggle would rewrite the line",
  );
  assert.match(toggleForm, /name="pr_comment"/);
  assert.match(toggleForm, /name="github_repo_id"/);
  // The button READS the current state and SUBMITS the opposite; a label that
  // read the pending value would tell every operator the wrong thing about the
  // repository in front of them.
  assert.match(toggleForm, /PR comment · (\{|on|off)/);
  // BOTH DIRECTIONS. Off is a STOP, not an undo (D3): the updates end and the
  // last comment stays. Copy that described only the on-state left the one
  // fact an operator needs at the moment of deciding unsaid, and a switch whose
  // off-state you have to guess at is guessed at wrong.
  assert.match(control, /Off, Doug stops updating the comment/);
  assert.match(control, /the last one it posted stays where it is/);
  // AND NOTHING HEDGES IT ANY MORE (#144). The staged-rollout sentence was
  // true only while `DOUG_PR_COMMENT_INSTALLATIONS` could hold a space dark
  // with this toggle reading "on". The allowlist is gone, so the sentence
  // would now describe a gate that does not exist — copy narrating a finished
  // rollout is its own kind of wrong, and the absence is what needs pinning
  // because nothing else fails when stale copy survives a deletion.
  assert.equal(control.includes("Rolling out to Doug"), false);
  assert.equal(control.includes("first wave"), false);
});

test("the deep read toggle is its own form and states BOTH of its consequences", async () => {
  const control = await readFile(
    new URL("../components/flag-line-control.tsx", import.meta.url),
    "utf8",
  );
  // A FOURTH FORM, for the reason the third one exists: `formData.get` returns
  // the first entry for a name, so a toggle sharing a <form> with the
  // flag-line input would re-save (or clear) that box on every click.
  const toggleForm = control.match(/<form action=\{setDeepReadAction\}[\s\S]*?<\/form>/)?.[0] ?? "";
  assert.ok(toggleForm, "the deep read form is gone");
  assert.equal(
    toggleForm.includes('name="needs_you_threshold"'),
    false,
    "the deep read form carries the flag line field — every toggle would rewrite the line",
  );
  assert.equal(
    toggleForm.includes('name="pr_comment"'),
    false,
    "the deep read form carries the PR comment field",
  );
  assert.match(toggleForm, /name="deep_read"/);
  assert.match(toggleForm, /name="github_repo_id"/);
  // Reads the current state, submits the opposite — same as the toggle above
  // it, and for the same reason: a label showing the pending value tells the
  // reader the wrong thing about the repository in front of them.
  assert.match(toggleForm, /Deep read · (\{|on|off)/);
  assert.match(toggleForm, /value=\{deepRead \? "false" : "true"\}/);

  // TWO CONSEQUENCES, and this is the pin that matters. Turning the read off
  // drops the repository to the deterministic scorer AND — with no flag line
  // of its own — moves the band from the reader default to the deterministic
  // one. Copy that named only the first would let someone switch off "the AI
  // bit" and silently halve how often Doug asks for a human.
  assert.match(control, /Doug scores on\s*\n?\s*structural signals alone/);
  assert.match(control, /moves the line Doug bands against/);
  // Conditional on the repository actually being unset, because a repo that
  // has set 0.75 keeps 0.75 through this toggle. Promising a move there would
  // be the same lie pointing the other way.
  assert.match(control, /\{value === null &&/);
  // Read from the API's own defaults, never hardcoded — same rule the flag
  // line's copy follows, so this suite is not pinned to one deployment's
  // environment. Asserted on the paragraph, not the file: the docblock above
  // legitimately quotes the numbers while explaining them.
  const consequence = code(control).match(/On, Doug sends the diff[\s\S]*?<\/p>/)?.[0] ?? "";
  assert.ok(consequence, "the deep read consequence paragraph is gone");
  assert.match(consequence, /defaults\.reader\.toFixed\(2\)/);
  assert.match(consequence, /defaults\.fallback\.toFixed\(2\)/);
  // AND IN THE RIGHT TENSE. On a repository where the read is already off the
  // line has already moved, so copy describing what turning it off "would" do
  // is a warning about a future the reader is standing in — and it invites
  // them to believe the band is still the reader's. One sentence per state.
  assert.match(consequence, /deepRead\s*\n?\s*\?/);
  assert.match(consequence, /turning the read off also moves the line/);
  assert.match(consequence, /the line Doug bands against moved with the read/);
  for (const literal of ["0.30", "0.62"]) {
    assert.equal(
      consequence.includes(literal),
      false,
      `${literal} is hardcoded in the deep read copy`,
    );
  }
});


test("every settings write revalidates BOTH surfaces, not just the ledger", async () => {
  // THE BUG THIS PINS. Until /dashboard/settings there was one surface, so
  // `revalidatePath("/dashboard")` was the complete answer. The settings page
  // renders the same component over the same row, so a write from it that
  // revalidated only the ledger left the page the click happened on showing
  // the state before the click — on controls whose entire job is to be
  // believed. Doug caught it on PR #194
  // (reader:server-action-revalidation-mismatch).
  const actions = await readFile(actionsUrl, "utf8");
  assert.match(actions, /const DASHBOARD_SURFACES = \["\/dashboard", "\/dashboard\/settings"\]/);
  // A loop, not a spread: revalidatePath's second parameter is
  // `'page' | 'layout'`, so `revalidatePath(...paths)` would hand it a path as
  // a type — silently the wrong call rather than an error worth reading.
  assert.match(actions, /for \(const path of DASHBOARD_SURFACES\) revalidatePath\(path\);/);
  assert.equal(
    /revalidatePath\(\.\.\./.test(code(actions)),
    false,
    "revalidatePath is being spread — its second argument is a type, not a path",
  );
  // EVERY write, counted, so adding a fourth action that revalidates one
  // surface fails here rather than shipping. There is no bare
  // revalidatePath("/dashboard") left outside the helper.
  const calls = actions.match(/revalidateDashboard\(\);/g) ?? [];
  assert.ok(calls.length >= 2, "a settings write stopped revalidating both surfaces");
  assert.equal(
    code(actions).includes('revalidatePath("/dashboard");'),
    false,
    "a write still revalidates only the ledger",
  );
});

test("setDeepReadAction is a server action like the two beside it", async () => {
  // Its revalidation is covered by the shared pin above, which counts EVERY
  // write rather than this one — a third action that revalidated only the
  // ledger has to fail there, not here. What is left is what is specific to
  // this action.
  const actions = await readFile(actionsUrl, "utf8");
  assert.match(actions, /^"use server";/);
  assert.match(actions, /export async function setDeepReadAction/);
  assert.equal(actions.includes("export async function GET"), false);
  assert.match(actions, /setRepositoryDeepRead\(auth\.accessToken, repoId, value\)/);
});

test("setFlagLineCommentAction is a server action, and the denial is stated on the page", async () => {
  const actions = await readFile(actionsUrl, "utf8");
  const page = await readFile(pageUrl, "utf8");
  assert.match(actions, /^"use server";/);
  assert.match(actions, /export async function setFlagLineCommentAction/);
  assert.equal(actions.includes("export async function GET"), false);
  // D8: a toggle that reads "on" while nothing ever posts, with the only trace
  // a stderr line in a project with no alerting, is the failure this banner
  // exists to refuse. It names the USUAL cause without claiming it is the only
  // one — a locked conversation, an archived repository and secondary rate
  // limiting all return the same 403.
  //
  // THE COPY MOVED, THE PIN FOLLOWED IT. The banner is its own component now
  // because the PR-comment toggle has two homes — this table and
  // /dashboard/settings — and a denial stated on only one of them recreates
  // the silence D8 exists to break. Four assertions that used to read
  // `page` read the component instead; none was dropped, and the two that
  // are genuinely about THIS page (that it renders the banner, and that it
  // renders it only on evidence) still read `page`.
  const banner = await readFile(
    new URL("../components/pr-comment-denial-banner.tsx", import.meta.url),
    "utf8",
  );
  assert.match(banner, /PR comments are not posting/);
  assert.match(banner, /refused \(403\)/);
  assert.match(banner, /re-accepted in GitHub/);
  assert.match(banner, /secondary rate limiting/);
  assert.match(page, /<PrCommentDenialBanner deniedAt=\{door\.current\.pr_comment_denied_at\}/);
  // Rendered only when the API says a denial happened, never unconditionally.
  assert.match(page, /pr_comment_denied_at &&/);
});

test("a failed connections read never reaches the generic error boundary", async () => {
  const page = await readFile(pageUrl, "utf8");

  // THE BUG. `getConnections` was awaited unguarded, and `sessionJson` throws
  // on every non-ok status, so any 401 or 503 fell through to app/error.tsx —
  // "This page failed to render." over a Try again button. The page rendered
  // fine, and re-running a 401 cannot clear a 401.
  assert.equal(page.includes("await getConnections(accessToken);"), false);
  assert.match(page, /try \{\s*session = \{ data: await getConnections\(accessToken\), failure: null \}/);

  // The decision is delegated, not re-derived here — same reason #99 moved the
  // four front-door states into dashboard-model.ts, where node --test can
  // reach them. An inline ternary would put the claim back out of reach.
  assert.match(page, /ledgerFailure\(status\)/);
  assert.equal(page.includes('failure = "declined"'), false);

  // And the arm renders instead of the page, not beside it: everything below
  // the read is built from connections the page does not have.
  assert.match(page, /if \(session\.data === null\) return <LedgerUnreachable failure=\{session\.failure\} \/>;/);
});

test("only the arm a new session can fix offers sign-out", async () => {
  const page = await readFile(pageUrl, "utf8");

  // Sign-out is advice, and advice is a claim. On a 503 the fault is a missing
  // ledger or a missing operator secret — signing out cannot touch either, and
  // offering it there tells the reader their credentials are the problem when
  // the API deliberately checked for the deployment fault FIRST so that exact
  // confusion could not happen.
  assert.match(page, /\{copy\.signOut && \(/);
  const gate = page.indexOf("{copy.signOut && (");
  const control = page.indexOf("action={signOutAction}", gate);
  assert.ok(gate >= 0 && control > gate, "the sign-out form must sit inside the signOut branch");

  // Pinned as data, so flipping a flag is what it takes to move it — not
  // editing JSX that a regex over the whole file would still match.
  //
  // `(?:(?!signOut:)[\s\S])*?` rather than a bare lazy `[\s\S]*?`, and the
  // difference is the whole test. A lazy gap still crosses arm boundaries, so
  // it keeps scanning past this arm's flag to the NEXT arm's — flipping
  // `unavailable` to true left `/unavailable: \{[\s\S]*?signOut: false,/`
  // matching `unreachable`'s flag, and the mutation survived. Refusing to step
  // over an intervening `signOut:` confines each match to its own arm.
  const arm = (name, flag) =>
    new RegExp(`${name}: \\{(?:(?!signOut:)[\\s\\S])*?signOut: ${flag},`);
  assert.match(page, arm("declined", "true"));
  assert.match(page, arm("unavailable", "false"));
  assert.match(page, arm("unreachable", "false"));
});
