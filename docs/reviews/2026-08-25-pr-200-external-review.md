# External review vs Doug — PR #200 @ 6293571

A calibration record for Doug's self-improvement loop: what an external
low-effort review found on this PR, next to what Doug's own check run
flagged on the same diff. Machine-readable table first; the narrative
deltas below are the training signal.

PR #200 closes #176 — `/install/callback`'s refused-authority `403` offered
`/install/callback?reauth=github` as its only action, and that action
provably changed nothing. Web only, no API change. Three files: the route,
its test file, and the Node test loader.

Doug read the diff (`validated diff reader`, risk 0.22, **Cleared**, four
low findings plus one unvalidated deviation). Unlike #114 the read was not
truncated, and the disposition below turns on judgment rather than on files
Doug never received.

**This round is unusual and worth the note: the external review found
nothing Doug missed.** Both of its findings are the same two defects Doug
ranked low. The delta is entirely in the other direction — three of Doug's
four findings do not survive contact with the code they describe.

## External findings (both verified, both fixed in this branch)

| # | file:line | category | finding | doug caught it? |
|---|-----------|----------|---------|-----------------|
| 1 | web/lib/node-next-loader.mjs:55 | correctness | The new `@/lib/*` rule appends `.ts` unconditionally, contradicting the extensionless-ONLY rule the same function states twenty lines later. `@/lib/queue-fixture.json` resolves to `queue-fixture.json.ts`, reporting a file nobody wrote as missing and masking the one that is | **yes** (`reader:over-broad-pattern-match`, low) |
| 2 | web/app/install/callback/route.ts:186 | correctness | The `403` gives the sign-out remedy as an unconditional instruction, while the block comment directly above it states the page cannot tell which of three causes produced the `404` and that the remedy helps in only one | **yes** (`reader:misleading-user-facing-copy`, low) |

### How each was fixed

1. A specifier that names its extension resolves exactly as written; only
   an extensionless one gets `.ts`. This is the rule the loader's own
   fallback already stated, now applied in both places instead of one.
   `lib/node-next-loader.test.mjs` is new and holds both halves — the flat
   `.ts` sibling and the `.json` that must not grow a second extension —
   and it pins resolution against the LOADER rather than the importer,
   which is the other half of the bug the single rule replaced.
2. The goal precedes the instruction. One instruction covers both causes a
   reader can act on, because signing in to GitHub as the installing
   account repairs the wrong-account case and the no-GitHub-identity case
   alike. The third cause is named by a trigger the **reader** can check —
   "if you do that and this page comes back" — rather than by a claim about
   who they are, which this page is in no position to make. The test pins
   the ordering, the trigger sentence, and the operator escape hatch.

Both defects are the same species: a comment or a sibling rule stating a
constraint correctly, and the code beside it not honouring the constraint.
Doug found both by reading the constraint and the code together, which is
the behaviour worth reinforcing.

## Doug's findings, dispositioned

- `reader:over-broad-pattern-match` (low) — **CONFIRMED**, row 1 above,
  with one half refuted. The unconditional `.ts` append is real. The `.tsx`
  / nested-index / `.js` half is not reachable: every `@/lib/*` import in
  the tree resolves to a flat `.ts` sibling. And the claim that "the
  default resolver fallback might have worked" is backwards — `@/` is not a
  real package specifier, so `nextResolve` always threw on it. That is
  precisely how this PR's own `@/lib/links` import failed, and why the
  loader had to change at all.
- `reader:misleading-user-facing-copy` (low) — **CONFIRMED**, row 2 above,
  with its premise corrected. The copy did not "assert that the current
  sign-in is not the installing account"; it said *not confirmed as* that
  account, which is true in all three cases. The real defect is the
  unconditioned instruction that followed, and Doug's remedy — condition it
  — is the right one whatever the premise.
- `reader:removed-route-branch` (low) — **REFUTED.** The finding says a
  stale `?reauth=github` with an absent or expired flow cookie now yields
  the generic invalid-flow response "rather than a re-auth". The deleted
  branch returned `invalidFlow()` on exactly that condition — it verified
  the cookie first and bailed to the same `400` when there was none. The
  behaviour under an absent or expired cookie is identical before and
  after. Separately, a repo-wide grep finds no link, doc, or email template
  pointing at the path; its only reference was the `403` body this PR
  rewrites, and the comments describing its removal.
- `reader:missing-import-verification` (low) — **REFUTED as a defect.**
  "If either export is missing or renamed" describes how imports work, and
  `tsc --noEmit` is green, which is what proves both exports exist; a
  rename fails the typecheck before it reaches a reader. The half worth
  acting on was that no test rendered the link, so the `403` test now
  imports `GITHUB_REPO_URL` from `lib/links.ts` and pins the rendered
  `href` against it. Mutation-verified: pointing the link at another repo
  fails the test.

### Decision deviation

- `beyond-ticket` on the loader rewrite (unvalidated section, so it
  contributes nothing to the band) — **ACCEPTED as stated.** Rewriting
  three entries into one is wider than adding a fourth. The ticket forced a
  loader change either way, the file is test-only, and two of the three
  entries resolved against the importer in a way a fourth line would have
  copied. Recorded here rather than as an ADR: a decision record for a
  test-runner resolve hook would be the first of its kind in
  `docs/decisions`, and this note is the durable trace the deviation asked
  for.

## Scoreboard

| | count |
|---|---|
| External findings | 2 |
| Doug caught | 2 of 2 |
| Doug missed | 0 |
| Doug's findings confirmed | 2 of 4 (both with a corrected premise) |
| Doug's findings refuted | 2 of 4 |
| Deviations accepted | 1 of 1 |

Nine mutations verified across both rounds of this PR, each failing exactly
one pin.
