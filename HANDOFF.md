# HANDOFF — doug

State:    building — design-lock.md AND build-plan.md both LOCKED
          2026-08-18. Side lane, isolated in worktree
          `managed-agent-pr-review-76fe26` (branch
          `claude/managed-agent-pr-review-76fe26`, base b8e3659). Main lane
          untouched. Design artifacts in docs/design/competitor-imports/:
          ground-truth · positions · decisions · design-lock · product-spec ·
          build-plan.

Next:     Task 4 — the constant_value_is predicate runner (new module
          api/doug/verify.py). Pure, resolvers injected, settle.py's shape.
          MUST abstain on ambiguity per settle.py:239 ("we settle neither
          rather than guess"). Tasks 1-3 DONE.
          ONE BLOCKER, Andrew's hands, gates MERGE not work: P0.1 — publish
          the LOCKED v9 pre-registration + deploy its hash. Zero code, zero
          rows; the one artifact whose value decreases with calendar time.
          Main lane unchanged: MT3 is still the critical path.

Blockers: MT0 blocks every prospective clock (main lane). This lane's only
          blocker is P0.1, and it gates merge, not the spec/plan/first commit.

Decisions this session:
- Reject managed-agent-in-reader.py — why: the addendum already rejects Agent
  Engine for the live verdict path, and A2 makes toolset/graph/runtime part of
  instrument identity while PROMPT_HASH would not notice — rejected: the
  advisor roster entry (an Opus-5 primary can only pair with redacted
  advisors, so advice can never enter a published receipt).
- LOCKED: cited head reads. Reverse the directional license on the
  outside-the-diff fetcher — review.py:273 head_file_text is wired only into
  settle.py's drop_disproved_* — so a finding may CITE bounded head reads to
  ground an existence-or-value claim. Why: 7 of PR #106's 8 external findings
  needed ≥1 byte Doug never received (reader gets f.patch only,
  review.py:190/267) — rejected: rendering the output surface (0/8 needed it
  as the only route), and the disposition surface (already ships at
  check_run.py:176-186).
- Model gets ZERO delete authority; closed vocabulary of deterministic
  predicates, `refuted` absent from the schema. Why: PR #107
  serialization-contract — a byte-matching, grep-derivable, factually TRUE
  quote carrying a FALSE refutation (models.py:113-125) — rejected: the
  citation gate with {refuted: bool}, and model-authored Narrowed prose.
- Existence-and-value claims only; absence/universality claims render
  unresolved, never citation-certified. Why (red-team's sharpest hit): the
  failure is direction-independent — the model chose which lines to look at
  and the answer lived in the lines it didn't choose.
- CUT after red-team: the citation-receipt PR. Why: settle.py has fired ZERO
  times since it landed (code 7b222c4 2026-08-03, schema class f065f0d
  2026-08-04; all 6 settle-eligible rows predate both; zero rows across 113
  prospective dispositions on #49-#107), and its dominant class resolves
  through a live DB query git show cannot reproduce.
- Predicate vocabulary cut to `constant_value_is` (the only one of five
  scoring >0/8). Why: the verify prompt is a separate FROZEN prompt, so every
  named predicate is permanent — vocabulary is not free.
- Part 3's table stays dead; its LOCKED §7 RULE ships first. Why: 461
  Co-authored-by / zero Reviewed-by, and publishing a rule needs zero rows —
  rejected: "empty and dated" (no clock can produce a first row) and the old
  trigger (a partner cannot ask for a capability with no surface).
- Corrected my own round-1 doc: it claimed the PM's red-lines were "retained
  in full" — four of seven were, and tension T-E was recorded resolved when it
  had been lost. Reinstated, then settled as L9.
- L9 (settles former open risk #1): the scoped coverage sentence and the
  zero-call read-log gate are NOT alternatives. Words ship with the increment;
  gate is vNext. Why: the gate proves citation honesty but supplies no
  denominator for what the model should have opened — shipping it instead of
  the words leaves a false completeness claim looking rigorous — rejected:
  round 1's either/or framing.

Tasks 1-3 DONE (verified 2026-08-18; committed afcb77c, a1411d3):
- reader.py — added Citation model + `evidence: Literal["diff","head-cited"]
  = "diff"` and `citations` (default_factory) to ReaderFinding. SCHEMA and
  PROMPT_HASH untouched (8bd26c67...), freeze tests green.
- tests/test_store.py +2, tests/test_api.py +1 (and `reader` added to its
  doug import block — ruff F821 caught the omission).
- api: 1405/1405 passed (was 1402), ruff clean.
- Mutation-checked BOTH new store tests: flipping the default to
  "head-cited" kills one; adding exclude=True to citations kills the other.
- Task 2: reader.cite() — pure, returns Citation|None, NEVER raises (a bad
  line number must be a no-op leaving the finding ungrounded, not a failed
  review). Deliberately NOT shared with example_pack_verifiers.
  _accepted_contract_receipt: that one resolves a Path under a repo root and
  its ref-less locator is an Example Pack contract.
- Task 2 tests: the load-bearing one re-derives the same bytes via
  `git show <sha>:<path> | sed -n 'a,bp'` and compares hashes — a different
  tool, no shared code. Confirmed it RUNS (not skipped). Mutation-checked:
  exclusive-end and splitlines()-without-keepends each kill both tests.
- Task 3: VERIFY_SYSTEM / VERIFY_SCHEMA / VERIFY_PROMPT_HASH + VerifyCheck,
  VerifyResponse (both extra="forbid"). `checks` is a LIST so declining is
  the natural answer — empty means diff-only, or an absence claim, or no
  nameable location; all three leave the finding published and ungrounded.
  NO `refuted` field and no boolean anywhere: the model cannot express a
  conclusion at the type level. PROMPT_HASH unmoved (8bd26c67...).
  VERIFY_PROMPT_HASH added because the intent tier is frozen by prose with
  no test behind it — a hash only anchors identity if edits move it.
- Task 3 mutation-checked: adding `refuted`, loosening extra=forbid, and
  adding a second predicate each kill a test.
- api: 1413/1413 passed, ruff clean across the whole package.

Pointers: docs/design/competitor-imports/ (six artifacts) ·
          docs/superpowers/specs/2026-08-18-cited-head-reads-design.md (D1-D9) ·
          docs/superpowers/plans/2026-08-18-cited-head-reads.md (Tasks 1-9) ·
          docs/reviews/2026-08-12-pr-106-external-review.md (the answer key —
          SPENT, it shaped this design; the replay is a smoke test not a bar) ·
          api/doug/{review,reader,settle,check_run,convergence}.py ·
          publication-preregistration.md §7 (locked, written, undeployed)
