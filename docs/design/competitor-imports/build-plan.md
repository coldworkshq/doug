# Build plan — cited head reads

**Date:** 2026-08-18 · **Status:** LOCKED 2026-08-18 · **Design:** [`design-lock.md`](design-lock.md) · **Baseline:** `b8e3659`

House convention is one spec + one plan per shipped increment (`docs/superpowers/specs/`, `docs/superpowers/plans/` — 40 files, no exceptions), so this plan names increments, not a mega-doc. Next free migration is **11**; nothing here uses one. **MT3 is the main-lane critical path — this lane stays in its worktree and touches nothing MT3 holds.**

---

## Phase 0 — dogfood gate (ADR-0008), and it ships before the code

**P0.1 — Publish the locked v9 pre-registration, §7 included.**
Zero code, zero rows, zero model calls. `publication-preregistration.md:5-8` records that neither the catch-up nor the v9 hash deployment has happened in production; `web/lib/receipt-shape.ts` already carries `prereg_hash` and the receipt consumer shipped in #108. This is the only artifact in the lane whose value strictly decreases in calendar time, and it is written, locked, and undeployed. **It is the gate: nothing else in this lane merges until the hash is live and the document is public.**

**P0.2 — The AUC panel correction** (`web/app/page.tsx:248-259`). One sentence. Publishing precondition per `design-lock.md` open risk #4.

**P0.3 — Retrigger Part 3** in `product-spec.md:30` and `design-lock.md:60`: from *"a design partner running Bugbot/CodeRabbit asks"* to *"the first installation accumulating a `tier='external'` row from a second reviewer of any kind."* One line of text; `save_external_review` already writes those rows.

**Pass condition:** the pre-registration is public with its hash in a live receipt, and Doug's own next PR renders a check run that is still `neutral`, still routed, and unchanged in shape.

## Phase 1 — the increment

**Goal.** Reverse the directional license on the outside-the-diff fetcher: let a finding cite bounded reads at head to *ground* an existence-or-value claim.

### Real seams

| Seam | Anchor | Change |
|---|---|---|
| Reader input assembly | `review.py:190`, `:267` — `diff_chunk` over `read_order(files) if f.patch` | unchanged; head reads are a second channel, not a bigger diff |
| The fetcher, already built and wired | `review.py:273 head_file_text`, threaded as `resolve_file` (`review.py:307-337`, `worker.py:237-251`), versioned by `verifier_versions` (`worker.py:31-34`) | reused as-is; this is the whole point |
| Finding shape | `ReaderFinding` (`reader.py:330-334`) | add `evidence: Literal["diff","head-cited"]` and an optional citation list. Rides `verdicts.raw` (`store.py:81`, unvalidated JSON, absent from the run-detail key list) — **zero wire change, no TS edit** |
| Frozen prompt | precedent at `reader.py:135-138` (`DECISION_INTENT_SYSTEM` / `INTENT_SCHEMA`) | a **separate** frozen prompt. Do-not-reopen #3 — the shipped `SYSTEM`/`SCHEMA` are untouched and `PROMPT_HASH` does not move |
| Spend | `_charge` → `record_deep_read` (`reader.py:271-297`, `store.py:1215-1254`); `cap_for` (`reader.py:267`) | third branch, own scope `verify:<id>`. **Never `installation:<id>`** — `instrument_snapshot` (`store.py:1314-1330`) renders that counter as `deep reads N/200` on the customer's check run and clamps at 200 |
| Render | `check_run.py:184-190` | citation rides `label` via `_oneline`; the `evidence` class drives whether the "outside the diff" sentence prints |
| Notice grammar | `convergence.py:38`, `:246-270` | **moves in the same commit** or convergence silently degrades to `unknown` |

### Hard constraints

- Existence and value claims only. An absence or universality claim renders **unresolved**, never citation-certified.
- The model supplies `{file, line_start, line_end, quoted_text, predicate}`; code runs the predicate. **`refuted` is not in the schema.**
- Predicate names are permanent (frozen prompt). Ship `constant_value_is`. Add `symbol_referenced_at` only if the find-references class is actually built — do not name it speculatively.
- Receipts are `path@<head_sha>#Lstart-Lend` + sha256.
- Hard per-PR read cap, and a timeout below the 120s read timeout. `api.py:2630` schedules `worker.drain`; `drain(max_jobs=20)` runs 20 jobs sequentially in one Starlette threadpool worker sharing the ~40-worker pool with `/healthz`.

### Test for intent, not shape

- **Superset assertion** — the finding set after head reads is a superset of the finding set before. This is what makes "the model never deletes" a property rather than a promise, and it replaces both suppression bars.
- **Citation integrity** — a fabricated quote, an off-by-one range, and a `resolve_file` returning `None` each yield an **ungrounded finding that still renders**, never a wrong citation and never a drop. `test_settle.py`'s 16 pure tests are the shape to copy (`lambda p: FILE` is the entire mock).
- **Evidence class is honest** — every finding carrying a citation is `head-cited`; every finding without one is `diff`. Fails if the classes are ever mixed.
- **Absence claims are refused** — a finding phrased as a universal gets `unresolved`, not a citation.
- **Spend isolation** — a run that performs head reads leaves `instrument_snapshot`'s counter unchanged. This one fails loudly if anyone reroutes the scope.
- **Smoke test, labeled as one** — replay PR #106 @ `616ff99` against `067e8ff` and report how many of the 8 are recovered. **Not a bar.** The answers are committed in-repo and shaped this design; report the number, claim nothing from it.

### ADR-0013

Owed with this increment: *"A model's citation may ground a published finding."* It is ADR-shaped against do-not-reopen #5 (new unvalidated signals get their own stream and never move the score) — and it must state that the citation does not move `risk_score` or `band`, only the finding's evidence class.

## Phase 2 — deferred, with named blockers

- **The agentic instrument** as G1's compute-matched comparator — blocked on the `application_revision`-in-`instrument_id` ruling (partitions are n≈1 at 4.9 PRs/day with merge-to-main deploys).
- **The per-source grading table** — blocked on P0.3's trigger firing.
- **A zero-call gate over the read log** — *every file cited in a finding appears in the read log*. This is open risk #1's second option and the most interesting unclaimed piece in the lane.

## Build from here

1. ~~Decide open risk #1.~~ **Settled — design-lock L9.** The scoped coverage sentence ships with the increment; the read-log gate is vNext and additive, not a substitute.
2. Ship **P0.1**. It gates every merge in this lane and needs no code. Andrew's hands.
3. Write `docs/superpowers/specs/2026-08-18-cited-head-reads-design.md` (D1–Dn against this lock), then the matching plan.
4. First code move — **unblocked by P0.1, safe to start now**: add `evidence` to `ReaderFinding` and prove it round-trips through `verdicts.raw` to the receipt API without touching `Reason` or the TS validators.
