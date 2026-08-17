# HANDOFF — doug

State:    review — **PR #110 IS OPEN.** https://github.com/drewjst/doug/pull/110
          Branch `fix/pr109-review-findings` @ d597b98, 4 commits off main
          @ 2e6a69c. #109's 3 findings fixed + MT3 design. All D1–D5 locked.
          Verified cold at d597b98: api 1402/1402 · web 282/282 · ruff ·
          eslint · next build (23 routes).

Next:     1. Andrew reviews/merges #110.
          2. **MT0** — redeliver the `installation` webhook in GitHub.
             Operational, Andrew's hands, and still the real critical path.
          3. writing-plans for MT3 implementation (spec is approved and
             needs no further decisions).

Blockers: MT0 blocks every prospective clock. Not a code blocker for MT3 —
          fixing MT0 exposes MT3 rather than causing it.

## #109's 3 findings — ALL FIXED (commit da404c8)

#109 was merged before the fixes landed, so they went onto main afterward.
Each fix is proven by re-running the mutation that previously passed:
- `public-surface.test.mjs` cross-row regexes → `fieldOf()` slices to one
  record first. Receipt-row mutation now FAILS (it passed before). Both
  showcase rows newly pinned — they were named but never checked.
- `check_run.py` `only_settled` → gated on `partial is None`.
- per-author-type ban → pinned to the disclaimer sentence, not a spelling
  neither file uses.
Verified: api 1402/1402 · web 282/282 · ruff · eslint · next build.

## MT3 — decisions locked (do not re-litigate)

- D1 Design for the org-install case (10k repos), not design-partner scale.
- D2 Full sweep moves to its own scheduled Cloud Run Job, mirroring
     doug-outcome-reconciler. Startup thread drops the full sweep.
- D3 Job ENQUEUES ONLY; drain stays in the API. Keeps the Job SA narrow —
     no model creds, no spend-cap surface, no paid reads on a second path.
- D4 One shared primitive applied to BOTH lanes.
- D5 Startup thread keeps a BOUNDED stalest-N pass — not nothing. Moving the
     full sweep out would trade away the healing latency the system has today
     (lost delivery heals next cold start vs. waiting 6h for the Job).
     Cheap because interruption-safety is structural, so a reapable thread is
     a legitimate caller by construction. Rejected: accept the regression;
     shorten the Job cadence.
- CONSEQUENCE: THREE entry points, three different bounds — unbounded
  (installation.created), budgeted (Job), bounded (startup). Collapsing any
  two is a regression that looks like correct behaviour. One test per site.
- Design: staleness within a tenant, round-robin across tenants.
- REJECTED: global staleness ordering. It does not deliver fairness — a
  10k-repo tenant joining degrades every other tenant's interval 200x, which
  is MT3's own complaint with the blocking spread evenly. The per-tenant cap
  is structural, not a refinement.
- REFUTED (recorded so it is not re-argued): the claim that global
  interleaving re-mints an installation token per repo. githubkit's
  DEFAULT_CACHE_STRATEGY is a module-level singleton shared across clients —
  verified empirically. Interleaving costs connection churn, not REST calls.

## MT3 — what the spec work corrected in the ROADMAP

- "Next free migration: 9" was STALE. 9 = Front Door Phase 1a, 10 =
  review_jobs.base_sha. **MT3 takes 11.**
- The reserved `installations.reconciled_at` CANNOT close the defect: a
  per-installation timestamp says a sweep ran, never which repos it reached.
  Sweep state must be per repo.
- Scope corrected to both lanes; reconcile_outcomes has the identical loop
  and is the more expensive one.
- MT3 is a CORRECTNESS item, not a scaling one: active_repos has no ORDER BY
  and reconcile_all's only caller is a reaped daemon thread, so the tail is
  never swept on any cold start. Silent permanent coverage hole.

## PR #109 review — original findings (now fixed, kept for calibration)

All three are the same defect class: **a check that passes for the wrong
reason** — the same family the last branch's review loop kept catching.

1. `web/lib/public-surface.test.mjs:94` — lazy `[\s\S]*?` spans table rows.
   PROVEN by mutation: flipping the receipt row to `meta: "planned"` leaves the
   suite green; the regex matches the NEXT row's `meta: "live"`. Line 93 only
   fails because `/v1/queue` is the last `live` row — reorder and it goes quiet.
   Fix: anchor to the row object, or parse instead of match.
2. `api/doug/check_run.py:156` — `only_settled` is computed from `risks`, which
   has already had `read-truncated` filtered out. PROVEN by repro: a truncated
   read renders "a clear is not evidence about the rest" and then, directly
   beneath, "Every finding the read produced was disproved."
   Fix: add `partial is None` to the condition at :158.
3. `web/lib/public-surface.test.mjs:86,121` — bans `"per author type"` while
   both guarded files write `"Per-author-type"`. Pins the old string's removal;
   does not guard reintroduction in the spelling the files now use.

## Doug's own verdict on #109 — 2 of 4 right

- `css-class-regression` — **REFUTED.** `--sheen` (globals.css:87) and
  `--accent`/`--accent-foreground` (:108-109) are all in the light `:root,`
  block at :55 and exported via `@theme inline`. Two greps away.
- `logic-edge-case` — **CONFIRMED** (= finding 2 above).
- `duplicated-constant` — **REFUTED as stated.** The load-bearing word is
  "silently"; it isn't. Added a third code to `SETTLED_REASON_CODES` and
  `test_settlement_rules_match_the_producer` failed loudly, naming the item.
  Doug flagged a mitigated design as if the mitigation weren't there.
- `brittle-source-text-test` — **CONFIRMED** (= finding 1), body was truncated
  in the paste, mechanism derived independently.

Calibration note: severity ordering was inverted — the one finding that lets a
defect through CI was ranked last.

## The critical path — MT0, and why it dominates

Verified in code, not taken from the doc:
- `worker.py:710` and `:923` both loop `store.active_installations()`.
- `store.py:2706` returns rows where `installations.state == 'active'`.
- Production holds **zero** `installations` rows against 33 `verdicts` rows for
  installation 150424894 (ROADMAP MT0). So `reconcile_all` is a **structural
  no-op** and token dispense 404s for our own install.
- The code already knows: `api.py:123` prints a DRIFT line naming ROADMAP MT0
  on cold start. Nobody has read that stderr.

Consequence: **the 14-day clocks are not ticking in production.** Everything
downstream is gated on data that is not being produced —
- M3 exit gate wants "one full webhook-started 14-day cycle observed in prod"
- M4 pitches the interviews "off the live dogfood scoreboard"
- M5's first pre-committed publication needs matured clocks

Fix is operational: **redeliver the `installation` event.** Do NOT
uninstall/reinstall — that mints a new `installation_id` and orphans all 33
existing verdicts.

MT3 (`reconcile_all` has no repo cap or call budget, and is serial across
installations) is the code follow-on. Fixing MT0 *exposes* it rather than
causing it. Next free migration: **9**.

## Recommended order after #109

1. MT0 (operational, ~5 min, Andrew's hands) → clocks start.
2. Watch one cycle; confirm the drift line stops printing.
3. MT3 before any outside install.
4. M4's 3 prospect interviews — highest information per hour in the whole plan,
   and they carry a STANDING KILL CRITERION (2 of 3 "that's not right" halts
   productization). Everything in MT/M5 builds infrastructure for a product
   these three conversations could kill. Do them as early as the live
   scoreboard allows.

## Decision debt — Andrew's call, blocks the scoreboard spec

Carried forward from the #108 session, still unresolved:
- #106 ships ten fields (`api.py:718-727`) and **none** of prereg §3's
  disclosure columns — no `censoring_rate`, `N_at_risk`, `misses`,
  `unverdicted_merges`, `partial_read_share`, `repos_withheld`. §3 says
  "Published together, never separately." Under-delivers against its OWN
  approved spec §4.3 ("emits the §3 table").
- Approach A §4.3 says the venue "can be the scoreboard page"; the later
  ruling ("the scoreboard is proof, not venue — a live page as venue makes
  every page load a publication") says the opposite. Later ruling should
  govern and §4.3 should be amended. Neither is written down outside a
  session transcript, so no code review can see it.
- Latent trap live on main: the zero state is pinned in three coupled places
  (`miss_rate: None` in Pydantic, `miss_rate: null` as a TS literal, and
  `isScoreboardResponse` rejecting anything else), and on validation failure
  `cachedShowcaseFetch` silently serves a fixture reading `adjudicated: 0`.
  Fires on the next change to that endpoint — the one that teaches it a rate.

Pointers: worktree .claude/worktrees/pr-106-code-review-cb48f9 · branch `pr109`
          @ 44781d2 (PR #109, base main) · findings in
          web/lib/public-surface.test.mjs + api/doug/check_run.py:156 ·
          roadmap docs/design/outcome-loop/ROADMAP.md (MT0 :369, MT3 :399,
          M4 :341) · prereg §3 docs/design/outcome-loop/publication-preregistration.md:337
