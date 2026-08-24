// Pins for /dashboard/settings — the named place where Doug is turned down.
//
// The page exists because the controls were unreachable, not because they were
// missing: the flag line and the PR-comment toggle shipped inside a <details>
// in one cell of ?view=repositories, nothing on the public site linked to
// /dashboard at all, and the only control on the screen wearing the word
// "Settings" was a gear holding sign-out. Every assertion here is about one of
// those three, so a regression to any of them fails loudly rather than quietly
// hiding a setting again.
//
// Source-text pins, not render tests (house rule).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [settings, dashboard, header, control] = await Promise.all([
  readFile(new URL("../app/dashboard/settings/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../app/dashboard/page.tsx", import.meta.url), "utf8"),
  readFile(new URL("../components/site-header.tsx", import.meta.url), "utf8"),
  readFile(new URL("../components/flag-line-control.tsx", import.meta.url), "utf8"),
]);

test("the settings page is reachable from the signed-in shell in two places", () => {
  // The rail, for someone browsing the sections, and the account gear, for
  // someone who went looking. Two doors to one room is not a duplicate: the
  // bug being fixed is that neither door existed.
  const railEntry = dashboard.match(
    /<Link href="\/dashboard\/settings" className=\{RAIL_ITEM\}>Settings<\/Link>/,
  );
  const menuEntry = dashboard.match(
    /<Link href="\/dashboard\/settings" className=\{MENU_ITEM\}>Settings<\/Link>/,
  );
  assert.ok(railEntry, "the rail's Settings entry is gone");
  assert.ok(menuEntry, "the account menu's Settings entry is gone");
});

test("the gear is not also called Settings", () => {
  // Two different things sharing one word on one screen is the confusion the
  // gear/flag-line naming pin already exists to refuse — and this is the same
  // failure in a new place. The gear opens sign-out and Connect repositories;
  // it is an account menu, and calling it Settings while a section by that
  // name sits six rows above it would send every reader to the wrong control.
  assert.match(dashboard, /aria-label="Account"/);
  assert.equal(
    dashboard.includes('aria-label="Settings"'),
    false,
    "the account gear still claims the word the settings section uses",
  );
});

test("the marketing header links to the dashboard, without reading the session", () => {
  // The root cause. Nothing on /, /docs/*, /queue, /scoreboard or /about
  // linked to /dashboard, and the header's only signed-in affordance was a
  // Sign in button that says Sign in whether or not you are signed in.
  assert.match(header, /\{ href: "\/dashboard", label: "Dashboard" \}/);
  // And it stays a PLAIN link. `withAuth` here would make /about and every
  // /docs page render per request to choose between two words — the cost is
  // real and the link is not a dead end without it, because proxy.ts hands an
  // unauthenticated /dashboard request to AuthKit and returns to it after.
  assert.equal(
    header.includes("withAuth"),
    false,
    "the header reads the session — every static public page just went dynamic",
  );
});

test("the settings page stays a server component with no client boundary", () => {
  // Same ethic as the ledger (RULING 2) and for a sharper reason: these are
  // the controls that turn Doug down. A setting that stops working when a
  // bundle fails to load is worse than one that never needed the bundle, and
  // the control it renders is deliberately three plain <form>s.
  assert.equal(settings.includes('"use client"'), false);
  assert.equal(settings.includes("'use client'"), false);
  for (const hook of ["useState", "useEffect", "useRouter", "useSearchParams"]) {
    assert.equal(settings.includes(hook), false, `the settings page reads ${hook}`);
  }
});

test("the settings page delegates every not-ready state to the ledger", () => {
  // A failed connections read, a never-connected account, an expired scope and
  // "choose a space" are four screens with four different next actions, all
  // four already worded once on /dashboard and pinned in
  // dashboard-contract.test.mjs. A second copy here would be a second thing to
  // keep true, and the two would drift on the first edit. There is nothing to
  // set until one of them is resolved, so this page hands the reader back.
  assert.match(settings, /if \(connections === null\) redirect\("\/dashboard"\);/);
  assert.match(settings, /if \(door\.state !== "runs"\) redirect\("\/dashboard"\);/);
  // …and it does not grow its own copy for them.
  assert.equal(settings.includes("LEDGER_UNREACHABLE"), false);
  assert.equal(settings.includes("Doug could not load your connected spaces"), false);

  // `redirect` works by throwing, so it must not sit inside the catch that
  // swallowed the read failure — there it would be caught and the page would
  // render on data it does not have.
  const catchBlock = settings.match(/\} catch \{([\s\S]*?)\n  \}/)?.[1] ?? "";
  assert.ok(catchBlock, "the guarded connections read is gone");
  assert.equal(
    catchBlock.includes("redirect("),
    false,
    "redirect() is inside the catch — it throws, so the catch would eat it",
  );
});

test("both surfaces render ONE control, so the copy cannot drift", () => {
  // ADR-0013 put the flag line on the repositories table for adjacency: it
  // sits one column from the "needs you" count it decides. That argument is
  // about the LINE and is still true, so the table keeps its control. It says
  // nothing about someone who has not opened the ledger and does not know the
  // words — which is what this page is for. The amendment is "both places, one
  // API", and the way that stays honest is one component.
  assert.match(settings, /import \{ FlagLineControl \} from "@\/components\/flag-line-control";/);
  assert.match(settings, /layout="page"/);
  assert.match(dashboard, /<FlagLineControl/);
  assert.match(control, /layout\?: "cell" \| "page";/);
  // The forward-only promise is written once, inside the shared panel, so both
  // surfaces make it. A copy of this sentence on the settings page would be
  // the drift this test exists to prevent.
  assert.equal(
    settings.includes("past verdicts keep the line they were scored against"),
    false,
    "the settings page grew its own copy of the flag line's forward-only promise",
  );
  assert.match(control, /Applies to reviews from now on/);
});

test("a PR-comment denial is stated on the settings page, not only on the table", () => {
  // D8, on the surface that now carries the toggle. A page showing
  // "PR comment · on" while every post is being refused is exactly the
  // dishonesty the banner was built to end, and it would be a NEW instance of
  // it — the ledger's banner cannot speak for a screen the reader is not on.
  assert.match(settings, /import \{ PrCommentDenialBanner \}/);
  assert.match(settings, /connection\.pr_comment_denied_at &&/);
  assert.match(settings, /<PrCommentDenialBanner deniedAt=\{connection\.pr_comment_denied_at\}/);
});

test("the settings list is the installation's, not a rollup over the ledger", () => {
  // A repository Doug has never reviewed still has settings worth changing,
  // and it is the likeliest reason someone opened this page — "why has Doug
  // never said anything about this repo". Building the list from runs would
  // hide exactly that row.
  assert.match(settings, /connection\.repositories/);
  assert.equal(
    settings.includes("getSessionRuns"),
    false,
    "the settings page reads the run ledger — a never-reviewed repo would vanish",
  );
});
