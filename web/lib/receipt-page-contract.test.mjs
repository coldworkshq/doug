// THE RECEIPT SCREEN'S SOURCE PIN, in the style of lib/dashboard-contract.test.mjs.
//
// Nothing in this suite renders — the page's own docstring says so, and every
// SENTENCE it makes about the evidence comes back from a tested function in
// lib/receipt-merge-view.ts or lib/receipt-verdict-view.ts, which is why those
// have real behavioural tests. What is left in the .tsx is layout plus a
// handful of PRESENCE GATES, and a presence gate is precisely what a
// behavioural test cannot reach: `governingLine` can be word-perfect while the
// verdict it describes is not on the page at all.
//
// That is not hypothetical. `09ab52b` fixed exactly that — the governing
// verdict's note rendered with no verdict beside it — and shipped with no test,
// so deleting the gate again would have left the whole suite green while the
// gap banner's "Both are on this page" went back to being false. The four error
// arms and the `repo === "all"` guard were in the same position.
//
// This repo's answer to its own no-render-tests rule is the source-text pin,
// and this branch already added one for both tables. This is that, for the
// receipt.
//
// A source pin can assert a string is present and cannot execute a branch. So
// every assertion here is about PRESENCE, ORDERING or ABSENCE — never about
// what a function returns, which belongs in the function's own test.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { register } from "node:module";
import test from "node:test";

register("./node-next-loader.mjs", import.meta.url);

const pageUrl = new URL("../app/dashboard/pr/[number]/page.tsx", import.meta.url);

test("both verdicts are on the page — the latest one and the one that governed the merge", async () => {
  // THE REGRESSION `09ab52b` FIXED, PINNED AT LAST.
  //
  // §2.2's last row requires the latest verdict and a merge's governing
  // verdict rendered side by side and forbids either one alone, and GapBanner
  // says "Both are on this page" in shipped prose. Before the gate below
  // existed, a merge's governing verdict contributed only a SENTENCE — the
  // publication note — under a label reading `governing`, with no verdict card
  // anywhere near it.
  //
  // Mutation proof (required by the fix brief): delete the
  // `{merge.governing_verdict !== null && (…<VerdictCard …/>…)}` block and this
  // test fails on the second assertion, then on the count.
  const page = await readFile(pageUrl, "utf8");

  assert.match(
    page,
    /<VerdictCard verdict=\{receipt\.latest_verdict\} \/>/,
    "the latest verdict is no longer rendered",
  );
  assert.match(
    page,
    /<VerdictCard verdict=\{merge\.governing_verdict\} \/>/,
    "the governing verdict is described but not rendered — 09ab52b's defect, again",
  );

  // Exactly two render sites, so neither can be quietly dropped and neither
  // can be double-counted by a third that renders something else.
  const cards = page.match(/<VerdictCard\b/g) ?? [];
  assert.equal(cards.length, 2, `expected the latest and governing cards only; found ${cards.length}`);

  // ...and the governing card stays GATED on the verdict existing. Deleting
  // only the null check — keeping the render — would crash the page for the
  // very payload the null case exists for
  // (test_merged_pr_without_a_reader_verdict_reports_null_governing). Pinned as
  // an ORDERING property, the way dashboard-contract pins its scopeUnconfirmed
  // note, so restyling the block cannot silently retire the guard.
  const gate = page.indexOf("{merge.governing_verdict !== null && (");
  const card = page.indexOf("<VerdictCard verdict={merge.governing_verdict} />");
  assert.ok(gate > 0, "the governing verdict's presence gate is gone");
  assert.ok(gate < card, "the governing verdict renders outside the gate that proves it exists");
});

test("all five unloadable arms exist, and each one is actually reachable", async () => {
  // Five states, five sentences, no shared "something went wrong". The arms
  // are only worth having if each is REACHED: an arm present in the table but
  // never dispatched is copy nobody sees, and — worse — the case it was
  // written for silently falls into whichever arm the `else` names.
  const page = await readFile(pageUrl, "utf8");

  assert.match(
    page,
    /type Failure =\s*"missing" \| "unauthorized" \| "unavailable" \| "unreachable" \| "unscoped";/,
    "the Failure union changed shape — an arm was added or dropped",
  );

  // Each arm has copy, and no arm is an empty shell. Sliced to the object
  // LITERAL, not the declaration: the `Record<Failure, { … heading: string;
  // body: string }>` annotation carries both field names too, and counting
  // over it would report six of each and pass while an arm was empty.
  const table = page.match(/const UNLOADABLE: Record<Failure,[^=]*= \{([\s\S]*?)\n\};\n/)?.[1] ?? "";
  assert.ok(table, "the UNLOADABLE copy table is gone");
  for (const arm of ["missing", "unavailable", "unauthorized", "unreachable", "unscoped"]) {
    assert.match(table, new RegExp(`\\n  ${arm}: \\{`), `the ${arm} arm lost its copy`);
  }
  assert.equal((table.match(/heading:/g) ?? []).length, 5);
  assert.equal((table.match(/body:/g) ?? []).length, 5);

  // And each is dispatched from the one status it may be dispatched from.
  // 404 covers BOTH "no such PR" and "not your repo" deliberately; 503 is a
  // deployment fault checked BEFORE the token; 401 is the API declining the
  // session; anything else — including no status at all — claims nothing.
  assert.match(page, /if \(status === 404\) failure = "missing";/);
  assert.match(page, /else if \(status === 503\) failure = "unavailable";/);
  assert.match(page, /else if \(status === 401\) failure = "unauthorized";/);
  assert.match(page, /else failure = "unreachable";/);
});

test("a link that names no repository says so, instead of claiming the PR has no receipt", async () => {
  // "all" is the run ledger's every-repo sentinel, not a repository, and the
  // receipt endpoint has no every-repo branch — so a link that dropped its
  // query string would 404 and render "Doug has no verdict and no merge
  // recorded for it" about a pull request in a repository nobody named. The
  // guard is what keeps this page from asserting a fact about data it never
  // asked for.
  //
  // Pinned as an ORDERING property: the guard must sit BEFORE the fetch, or it
  // is a guard that runs after the damage.
  const page = await readFile(pageUrl, "utf8");
  const guard = page.indexOf('if (repo === "all")');
  const unscoped = page.indexOf('<Unloadable failure="unscoped" />');
  const fetched = page.indexOf("await getReceipt(");
  assert.ok(guard > 0, "the every-repo sentinel guard is gone — a scopeless link would 404 as 'missing'");
  assert.ok(unscoped > guard, "the guard no longer renders the unscoped arm");
  assert.ok(fetched > guard, "the guard fell below the fetch it exists to prevent");
});

test("the 401 arm claims a status, never one of the five causes behind it", async () => {
  // `resolve_session` returns None — 401 — for an invalid or expired JWT, NO
  // ORGANIZATION SELECTED (the normal first-sign-in state), no installation
  // bound to the org, a stale entitlement, and a `live_scope` that resolves to
  // nothing (api/doug/session_auth.py:164-195). The dashboard's #99/#100
  // expiry copy is licensed because the API states `reauthorize_required` in
  // the body; here the arm is inferred from a bare 401, which names no cause.
  //
  // Pinned as an ABSENCE, because the overclaim is a sentence and the honest
  // version is not one particular sentence.
  const page = await readFile(pageUrl, "utf8");
  const arm = page.match(/\n  unauthorized: \{[\s\S]*?\n  \},\n/)?.[0] ?? "";
  assert.ok(arm, "the unauthorized arm is gone");
  assert.equal(
    /still has your connection/.test(arm),
    false,
    "false whenever the 401 came from no org, no installation, or a dead scope",
  );
  assert.equal(
    /What expired is/.test(arm),
    false,
    "expiry is one of five causes; a bare 401 does not say which",
  );
  // It still offers the control that helps across the set, so the arm is
  // actionable rather than merely cautious.
  assert.match(arm, /[Ss]igning out|[Ss]ign out/);
});

test("the gap banner says which verdict the rule selects, not which the statistic counts", async () => {
  // SELECTION IS NOT INCLUSION. The published denominator is cleared-band only
  // (docs/design/outcome-loop/publication-preregistration.md:186,
  // `AND g.band = 'cleared'`), and band is deliberately no part of
  // governing-verdict selection — so "is the one the published statistic uses"
  // was false for every flagged governing verdict, including the one in this
  // repo's own receipt fixture.
  const page = await readFile(pageUrl, "utf8");
  const banner = page.match(/function GapBanner\([\s\S]*?\n\}\n/)?.[0] ?? "";
  assert.ok(banner, "GapBanner is gone");
  assert.equal(
    /the one the published statistic uses/.test(banner),
    false,
    "the banner claims inclusion in the published rate from a selection rule that ignores band",
  );
  // The claim it DOES make — both verdicts are here — is the one the test
  // above keeps true.
  assert.match(banner, /Both are on this page/);
});
