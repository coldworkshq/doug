# HANDOFF — doug

State:    review — the outcome-surface residual is BUILT, reviewed, and green.
          8 code commits + docs off main @ da8bf97 (#106 merged). Final
          whole-branch review clean after one fix wave. Nothing pushed; no PR
          opened yet.

Next:     Open the PR (superpowers:finishing-a-development-branch was the next
          step). Then Andrew's two still-open rulings, both about the MERGED
          scoreboard and unrelated to this branch — see "Still open" below.

Blockers: none for this branch.

Verified cold by the controller, not taken from agent reports:
          web 270/270 · console 113/113 · api 1393/1393 · both Node builds
          green · both lints clean · ruff clean.

## What shipped

- **Receipt screen** at `/dashboard/pr/[number]` — the first consumer of
  `GET /v1/prs/{n}/receipt` (`api.py:916`), which had none. Needed no new
  endpoint, no new scope, no migration: SESSION_SCOPES already carries
  `receipt:read` (`session_auth.py:27`).
- **60-day outcome** joined beside the 14-day one in `store.run_history` and
  rendered as a second always-shown column on both the dashboard and the
  console. No migration — `enqueue` has always written both windows.
- All honesty logic lives in `web/lib/` because `npm test` runs
  `node --test 'lib/**/*.test.mjs'` and reaches nothing else. The page holds no
  conditional that decides a claim.

## Rulings made this session (do not re-litigate)

1. Scoreboard publishes the full prereg §3 table, always. (Governs the
   scoreboard spec, NOT this branch.)
2. The scoreboard is NOT a §12 publication — proof, not venue. A live page as
   venue makes every page load a publication, reintroducing the
   selective-disclosure problem the cadence rule exists to solve.
3. Two lanes: tenant surfaces separate from the public prereg-governed page.
4. The receipt is its own route, not a dashboard panel — it is per-PR while the
   `?run=` panel is per-verdict.
5. 14d and 60d are two separate always-shown columns, never collapsed into one
   "strongest signal" column.

## Follow-ups this branch deliberately did not do

- **`receiptBand()`** — `ReceiptVerdict.band` is a bare `string` on the wire, so
  `BandChip` could not be used honestly: the alternatives were a cast that could
  paint an unknown band CLEARED (the #93 error) or an untestable ternary. The
  page renders band as its word with no data colour, which is honest. This began
  as a Task-1 deferred minor and became load-bearing in Task 5 — the deferred
  list earning its keep.
- **PR-level `preregLine()`** — on an unmerged PR the page reads "… will govern
  this window" directly above "not merged — no window has started". Incoherent
  but not an overclaim. Weakest of the deferred set; fix when next in the file.
- Nested `.panel` (VerdictCard inside MergeCard); per-field reject tests for
  receipt nullable fields; `WindowTile` prints `due` rather than `observed_at`.

## Still open — Andrew's call, unrelated to this branch

Both concern the now-merged #106 scoreboard, and both are invisible to a code
review because they exist only in a session transcript:
- #106 ships ten fields, none of prereg §3's disclosure columns, which
  under-delivers against its OWN approved spec §4.3 ("emits the §3 table").
- Approach A §4.3 says the venue "can be the scoreboard page"; ruling 2 above
  says the opposite. The later ruling should govern and §4.3 should be amended.
- Plus a live latent trap on main: the zero state is pinned in three coupled
  places (`miss_rate: None` in Pydantic, `miss_rate: null` as a TS literal, and
  `isScoreboardResponse` rejecting anything else), and on validation failure
  `cachedShowcaseFetch` silently serves a fixture reading `adjudicated: 0`.
  Fires on the next change to that endpoint — the one that teaches it a rate.

## What the review loop actually caught (worth knowing)

Every defect found was in the PLAN, not in implementer work — implementers
transcribed faithfully throughout. All were the same shape: **a check that
passes for the wrong reason.**
- A `.ts` import extension legal in `.test.mjs` and illegal in `.ts`, so
  `npm test` stayed green while `next build` failed TS5097.
- A caption test asserting `/external/i`, which passed on the exact inversion.
- A fallback test whose fixture supplied its own expected answer.
- An inert mutation whose literal reading proved nothing.
- **And the one that matters most:** the fix for the third item introduced a
  fourth. Feeding `governingLine` an empty `publication_note` proved a branch
  production never reaches, because the API always sends a non-empty note — so a
  merge with `governing_verdict: null` rendered a note saying "The verdict shown
  here is historical context" while no verdict was rendered. Caught only by the
  whole-branch review, which is the one pass that asks whether the page does
  what its sentences claim.

Pointers: worktree .claude/worktrees/doug-next-improvement-546ca1 · branch
          claude/doug-next-improvement-546ca1 · spec
          docs/superpowers/specs/2026-08-12-outcome-surface-residual-design.md
          · plan docs/superpowers/plans/2026-08-12-outcome-surface-residual.md
          · page web/app/dashboard/pr/[number]/page.tsx · logic
          web/lib/receipt-{shape,verdict-view,merge-view}.ts · pins
          web/lib/receipt-page-contract.test.mjs + receipt-fixture.test.mjs ·
          join api/doug/store.py:2413
