# Phase 3 — Chief Architect rulings (converged, round 1)

Convergence test run: after C1–C7 no material tension remained that moves the design, the v1 cut, or the seams. Residual risks recorded in §Open, not laundered into resolutions.

---

## C1 — The model gets zero delete authority, and a closed predicate vocabulary instead of a boolean

**Decision.** The verify schema is `{file, line_start, line_end, quoted_text, predicate}`, where `predicate` is drawn from a **closed vocabulary of deterministic checks the code already owns** — `name_is_runtime_imported` (`settle.py:104-155`), `column_exists_in_live_schema` (`settle.py:249-264`), `symbol_defined_in_file`, `constant_value_is`, `path_does_not_exist`. `settle.py` runs **the predicate, not the model's conclusion**. `refuted` does not appear in the schema, so it cannot be honored.

**Kills.** (a) `{refuted: bool}` behind a byte-match — the PE's citation gate as proposed. (b) Model-authored `Narrowed` prose on the customer surface in v1.

**Why.** Byte-matching proves the model didn't hallucinate file contents. It does not prove the claim is false. Measured, zero adversarial effort: PR #107 `reader:serialization-contract` (`adjacent`, `changed: true`). A refuter quotes `file: str | None = Field(default=None, exclude=True)` at `models.py:133` — byte-matches head, grep-re-derivable, **factually true** — and the refutation is wrong, because `models.py:113-121` records that `exclude` is honored by `model_dump`/FastAPI *"and by nothing else."* That finding bought a behavioural pin. Compounding: `ReaderFinding` (`reader.py:330-334`) carries **no line numbers**, so the refuter picks its own target with nothing to check it against — weaker than `settle.py`'s regex, which at least extracted its target from the finding's own text and *still* produced the measured false settlement at `settle.py:227-243`.

**Why this is not splitting the difference.** It gives the model strictly less authority than the PE proposed (zero deletions) and strictly more reach than never-delete (five refuters aimable at any finding, versus two hardcoded slug-matchers). Both openings drew the seam at the wrong place. The joint is: **the model is good at deciding where to look and bad at concluding.**

## C2 — The gap is reading outside the diff. Not rendering, and not precision.

**Decision.** v1's capability target is making the **existing** outside-the-diff fetcher additive — bounded, cited symbol/constant resolution into head — under the same citation discipline that governs it subtractively today.

**Kills.** (a) "Render the output surface" as the v1 capability. (b) The disposition surface as the headline. (c) `settle.py` extension as the lead build.

**Why.** `review.py:190` and `:267` build the reader's input as `diff_chunk` over `read_order(files) if f.patch` — patches only, no whole files. Against PR #106's 8 external findings: render-as-only-route **0/8**; fully inside Doug's bytes **1/8**; required ≥1 byte Doug never received **7/8**; in files absent from the PR entirely **4/8**. Rendering would not have caught the Architect's own exhibit #2 (meter 200 vs enforced 4000) — a rendered footer reading `deep reads 37/200` looks correct; the bug is only visible from `reader.py:230`, a file not in the PR.

`review.py:273 head_file_text` and `store.columns_of` are built and wired — exclusively into `settle.py`, whose docstring at `settle.py:6` states *"The model still saw only the diff"* and whose entry points are all `drop_disproved_*` / `is_disproved_by_*`. **The system's one outside-the-diff capability is licensed to subtract and forbidden to raise.** That asymmetry produced 7 of 8 misses.

**Corollary for the founder's tension.** The LLM's ambiguity value is retained by letting it *aim* the checks and *cite* the evidence — not by letting it conclude, and not by confining it to being filtered afterward. Additive citation is the same gate run in the direction that carries the measured value.

## C3 — The disposition surface does not carry v1

**Decision.** Demoted from headline to copy riding along. Two states in v1: **Held** / **Refuted-with-citation**. The PM's red-lines are retained in full.

**Kills.** Three-state Held/Refuted/Narrowed as the v1 product.

**Why.** The 13-of-39 claim does not survive skeptical reading. `changed` does not mean "changed code" (`REVIEWING.md:275-277`); `reader:fragile-import` is `changed:true` with the note *"No import code changed."* Sorted by what shipped: 4 docs-only, 3 comment/docstring-only, 1 explicitly no-runtime-change, 1 test+docs — **8 of 13 changed nothing that executes**. Of the remaining 4, `deploy-workflow-gating`'s own note records that the finding *also stated the true clause*, and `global-state-mutation` had no concurrent caller. **~2 clean instances in 123 rows.** And the corpus structurally cannot contain the evidence under debate: all 135 rows are `layer=doug` and all three verdicts presuppose Doug emitted something, so it is the one dataset in the repo incapable of recording a miss — dispositioned by the findings' own author, against a schema that pre-declares `adjacent` "the valuable one." The 8-row external review is the only rater-independent evidence and it says the opposite.

**Retained regardless (free, and correct).** No finding disappears without a line. No `adjacent` is deletable — operationalized as: **the predicate must bear on the finding's own named subject, or it does not run** (`settle.py:239`'s existing *"we settle neither rather than guess"*, extended not diluted). No per-finding confidence number. No "verified"/"confirmed"/"validated" and no green check on a finding. No rate from `findings-log.jsonl`.

## C4 — Part 3 (per-source grading) is out of this design

**Kills.** The per-source cleared-band table in v1 *and* as "vNext, empty-and-dated."

**Why.** Plumbing is genuinely cheap (~2–3 days: a sibling to `governing_verdict` (`store.py:1743`) partitioned by `source`, the §7 duplicate-rate query, a response model and table; zero migrations) and the metric is already pre-registered at `publication-preregistration.md` §7 as LOCKED v9. But the data cannot exist: `drewjst/doug` has **461 `Co-authored-by` trailers and zero `Reviewed-by`**; only `approved`/`changes_requested` band (`api.py:2392`) while `commented` — the state review bots overwhelmingly emit — is dropped as stance-less; `issue_comment` is unsubscribed. The trigger is written and unfired (`product-spec.md:30`: *"trigger: a design partner running Bugbot/CodeRabbit asks"*). The repo's empty-state device works because it ships a **due date** off a clock already running; here no mechanism can produce a first row. "Empty and dated" without a date is a promise, not a disclosure. Stays deferred-with-trigger where `design-lock.md:60` already put it.

## C5 — Part 2's blocker is instrument identity, not capture

**Decision.** The P0 is a **ruling on whether `application_revision` belongs in `instrument_id`** — a design decision against a BUILT identity scheme, not an env var flip.

**Kills.** "Turn Example Pack capture on" as P0.

**Why.** `instrument_id()` hashes the whole manifest including `application_revision` (`example_pack.py:196-201`), pinned to a 40-hex commit SHA. Merge to main deploys. Measured cadence: **88 PRs merged 2026-08-01 → 2026-08-18 (#21 → #112) = 4.9/day**, so deploys/day ≈ PRs/day and `score_packs_by_instrument` partitions into buckets of **n ≈ 1** — not "halved by two arms," pulverized. Hosted capture is worse: `ApplicationRevisionMismatch` hard-skips (`example_pack_capture.py:369-372`). A paired n=100 comparison under one `instrument_id` needs the deploy SHA held constant across **~20 days of PR traffic** — freezing main for three weeks, directly across MT3.

## C6 — Ordering: PR 1 makes PR 2 safe

**Decision.**
- **PR 1 — citation receipts on the settlements that already ship.** No new model call, no new prompt, no migration, no wire change. Lift the byte-slice + sha256 primitive out of `example_pack_verifiers._accepted_contract_receipt` (`example_pack_verifiers.py:133-172`) into a shared helper; every `settle.py` drop carries `path#Lstart-Lend` + `sha256` so `git show` reproduces it. The locator rides **inside `label`** (`check_run.py:184` already renders it via `_oneline`), avoiding the `Reason` exact-key-set validator at `web/lib/session-api.ts:289-292`.
- **PR 2 — the additive direction:** bounded, cited symbol/constant resolution into head, under C1's predicate gate.
- **Third, and may not clear its own bar:** model-aimed *subtractive* refutation. Measured ceiling is low — only 12 of 123 prospective rows land in slug families today's settlers could even attempt, 8 already disproved, and `settle.py:241-242`'s bare-backtick veto kills a share of those.

**Why the order is the argument.** With the byte gate already shipped, a fabricated or off-by-one citation in PR 2 is a **no-op** rather than a wrong result. Reversed, PR 2 is the thing the PE correctly says should not be built at all: a second nondeterministic call acting on published findings, against a Convergence Bar 1 that already FAILed with reader nondeterminism named as root cause.

## C7 — Artifacts

One spec + one plan **per PR** — `docs/superpowers/specs/` and `plans/` are one-artifact-per-increment across all 40 files, never one per theme. `docs/design/competitor-imports/` holds the lane's shared record (`ground-truth.md`, `positions.md`, this file). **ADR-0013** is owed with the PR that first lets a model's citation affect a published finding — it is precisely ADR-shaped against do-not-reopen #5. Next free migration stays **11**; neither PR uses one.

---

## Pre-registered bars (declared before any run)

- **PR 1:** every existing settlement emits a locator + sha256 that `git show` reproduces; `test_settle.py`'s 18 pure tests stay green; the notice grammar change moves `convergence.py:38` and `:246-270` in the same commit.
- **PR 2:** the reconstructed 57-prospective-`real`-row fixture suppresses **zero**, **and** the 31 `adjacent` rows suppress **zero** (the class most likely to be killed and the one the PE's bar could not see); **and** the new capability recovers **≥3 of the 8** external findings on a replay of PR #106 @ `616ff99` against answer key `067e8ff`. Finding #3 is excluded — it needed in-diff rigor, not new capability.

## Open risks (residual — recorded, not resolved)

1. **Nondeterminism.** Convergence Bar 1 failed with reader nondeterminism as root cause. The citation gate makes a *bad* citation a no-op; it does not make the *choice of what to read* stable. PR 2 adds a nondeterministic call that **adds** findings. Unresolved; must be measured, not assumed.
2. **Instrument identity has no orchestration field.** `WholeInstrumentManifestV0` is `extra="forbid"` with no orchestration-graph/roles field, so two materially different read policies can share an `instrument_id`. Either a `whole-instrument-v1` schema change, or the collision is accepted and stated out loud.
3. **The AUC panel is a prerequisite, not part of the build.** `web/app/page.tsx:248-259` renders "0.69 / 0.67" under "What's actually measured." Ground truth #7 forbids any instrument inheriting it and the shipped reader has never been AUC-measured. The correction sentence ships before any new-reader work is announced.
4. **Corpus reconstruction is PR 2's long pole,** not capture: `findings_log.py:79` raises on extra keys and the schema carries no finding text, file, line, or head SHA. Rebuilding the 57 rows across 17 PRs (#48–#107) needs a one-time production read of `verdicts.raw` / `findings.label` / `head_sha` plus local `git show`, committed as a fixture. ≈1 day.
