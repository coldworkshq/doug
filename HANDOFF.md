# HANDOFF — doug

State:    spec — residual spec WRITTEN and committed (8851571), 1 commit off
          main @ 37942c3. Another session is code-reviewing PR #106; this
          session deliberately did NOT duplicate that.

Next:     Andrew reviews docs/superpowers/specs/
          2026-08-12-outcome-surface-residual-design.md. On approval →
          writing-plans for the receipt screen ONLY (the 60-day join is
          sequenced behind #106's merge).

Blockers: #106 conflicts with two rulings Andrew gave THIS session (§0.1 of
          the new spec). Needs one governing answer before #106 merges. NOT
          discoverable by the running code review — the rulings exist in a
          session transcript, not in any file. Andrew was offered the handoff
          to that session and has not yet said yes.

Decisions this session:
- PR #106 OVERLAP (found only because Andrew asked): it ships check-run footer,
  public scoreboard (endpoint + page), landing copy honesty, and bot-author
  deep-read skip — 4 of the 6 ranked options, incl. both M3 gate items. It does
  NOT ship the 60-day join or the receipt screen. Its spec is
  docs/superpowers/specs/2026-08-13-unbeatable-doug-research.md ("Approach A",
  Andrew-approved in another session; this session had not seen it).
- CONFLICT 1 — scoreboard scope. Andrew ruled THIS session "full §3 table,
  always". #106 ships 10 fields, none of §3's disclosure columns (no
  censoring_rate / unverdicted_merges-by-bucket / remediated_clears /
  base_rate / Wilson CI / partial_read_share). Also under-delivers against its
  OWN spec §4.3, which says the query "emits the §3 table".
- CONFLICT 2 — venue. Andrew ruled THIS session "not a publication — proof,
  not venue" (rationale: a live page as venue makes every page load a
  publication, reintroducing the selective-disclosure problem §12's cadence
  rule solves). Approach A §4.3 says "Venue can be the scoreboard page in this
  increment". More recent ruling should govern; §4.3 needs amending — but that
  is Andrew's call to state, not this session's to assume.
- CONFLICT 3 — latent trap in #106, VERIFIED by reading the branch. The zero
  state is pinned in 3 coupled places: `miss_rate: None` (Pydantic,
  models.py:137), `miss_rate: null` as a TS literal (scoreboard-shape.ts), and
  isScoreboardResponse() rejecting `miss_rate !== null || decidable !== false`.
  On validation failure web/lib/api.ts fetchScoreboard() silently falls back to
  scoreboard-fixture.json, which reads adjudicated:0 pending:0. NOT a 08-16
  break — adjudicated/pending come from instrument_snapshot and tick correctly,
  and "not yet decidable" stays honest while no interval is computed. The trap
  fires on the NEXT change to this endpoint (the one that teaches it a rate —
  i.e. the surface's whole purpose): miss three files and the public page
  silently claims zero adjudications.
- Brainstorm rulings from Andrew, still valid and reusable for whatever ships:
  full §3 table always; scoreboard is proof not venue; two lanes (small three
  first, scoreboard separate).
- SIZING FACTS established: SESSION_SCOPES = ("queue:read","receipt:read")
  (session_auth.py:27) so the receipt screen needs NO auth work and NO new
  endpoint. Nothing computed §3 before #106; precision.py:21 wilson() is the
  only reusable piece; §4 base_rate must come from backtest/git_labels.py over
  12 months of squash merges. §9 noise estimates are NOT computable — one hand
  audit per (repo, window), every quarter, forever.
- LANE AUDIT, verified against code not plans: Lane 0 closed (all 4). Lane 1
  Phase A (#90) + Phase B (#95/#102/#103) shipped; **Phase C is 0 of 7** —
  `finding_counts` has zero hits in web/, no /receipt or /scoreboard route, no
  health strip, and web/lib/api.ts:23 still calls /v1/showcase/queue not the
  real tenant queue. Phase D untouched. Lane 2 halted at a FAILED bar 1.
- THE CLOCK REORDERS THE PLAN: 2026-08-16 is the first due clock (#92 receipt:
  eligible_14 = existing_60 = 66, first rows ever, stamped v9). Doug is about
  to produce its first real outcomes and NOTHING renders them: the receipt
  endpoint (api.py:916) has zero consumers, there is no scoreboard route, and
  check_run.py has no adjudicated/pending footer. The last two are M3 exit-gate
  items. So Phase C ships against the clock (60-day join → receipt → scoreboard
  → footer), NOT in the plan's effort-to-value order — rejected: starting with
  finding_counts/spend meter, which are the cheap tail.
- CONVERGENCE RULING (proposed, not yet Andrew's): bar 1 failed upstream of the
  classifier — the reader is nondeterministic, so absence ≠ fixed; 26 of 43
  sampled findings sat on byte-identical code. Proposed fourth abstention:
  file byte-identical between the two verdict heads ⇒ `unknown`, never
  `resolved`. Catches 4 of the 5 confirmed false-resolveds (#75 ×2, #48 ×2);
  does NOT catch #50 input-validation, which is slug drift — the
  finding-identity problem. MUST be re-pre-registered and re-evaluated, not
  patched into the existing bar: those units leave the ratio as `unknown`, the
  sample shrinks, and 0.90 is not guaranteed. Independently: unblock MCP v0 by
  shipping the receipt payload WITHOUT a convergence halt signal — the
  differentiation is band/threshold/coverage provenance, and the spend gate can
  be a per-PR read ceiling instead — rejected: holding MCP v0 hostage to a
  signal that may never pass its bar.
- Live defect found, unfixed: web/app/docs/rest-api/page.tsx:38 marks
  /v1/queue and /v1/prs/:number/receipt "planned — none of this is live"; both
  ship today (api.py:534, api.py:916). Under-claiming on a page that only
  became reachable at #105. Belongs with Phase D copy honesty.

Pointers: worktree .claude/worktrees/doug-next-improvement-546ca1 · branch
          claude/doug-next-improvement-546ca1 (no commits) · spec
          docs/superpowers/specs/2026-08-11-two-lane-plan-design.md §2 Phase C
          · eval docs/design/outcome-loop/convergence-eval-results.md (bar 1
          FAIL arithmetic at "The arithmetic") · gate items at
          ROADMAP.md:311-312 · first clock ROADMAP.md:297
