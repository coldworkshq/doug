# Cited head reads — let a finding cite bounded reads at head

**Date:** 2026-08-18
**Status:** design approved 2026-08-18 — all decisions locked (D1–D9), ready for an implementation plan
**Design:** `docs/design/competitor-imports/design-lock.md` (L1–L9), `product-spec.md`, `build-plan.md`
**Blocks:** nothing on the main lane. MT3 is unaffected; this lane holds no file MT3 holds.
**Blocked by:** P0.1 (publish the locked v9 pre-registration + deploy its hash) — **gates merge, not implementation.**
**Baseline:** worktree `managed-agent-pr-review-76fe26` @ `b8e3659`

---

## 1. The problem, measured

Doug's reader is handed `f.patch` and nothing else. `review.py:190` and `:267` both assemble the model input as `reader.diff_chunk(...)` over `read_order(files) if f.patch` — no whole files, ever.

Doug nonetheless *has* an outside-the-diff fetcher. `review.py:273 head_file_text` and `store.columns_of` are built, wired as `resolve_file` / `resolve_schema` (`review.py:307-337`, `worker.py:237-251`), and versioned by `verifier_versions` (`worker.py:31-34`). Every one of their entry points is `drop_disproved_*` / `is_disproved_by_*` in `settle.py`, whose module docstring states the licence explicitly at `settle.py:6`: *"The model still saw only the diff."*

**The system's one outside-the-diff capability is licensed to subtract findings and forbidden to raise them.**

Against the only rater-independent evidence in the repo — the 8 external findings on PR #106 (`docs/reviews/2026-08-12-pr-106-external-review.md`, answer key `067e8ff`):

| | count |
|---|---|
| Needed rendering the output as the only route | **0 / 8** |
| Fully inside the bytes Doug received | **1 / 8** |
| Required ≥1 byte Doug never received | **7 / 8** |
| Lived in files absent from the PR entirely | **4 / 8** |

Exhibit: finding #2, the footer meter rendering against `PLAN_DEEP_READ_CAP = 200` (`store.py:1260`) while spend is enforced at `INSTALLATION_MONTHLY_READ_CAP = 4000` (`reader.py:230`). `reader.py` was not in the PR. Rendering the check run would not have caught it — a footer reading `deep reads 37/200` looks correct.

## 2. Decisions

**D1 — Reverse the directional licence.** A finding may cite bounded reads at head to *ground* a claim. The fetcher, its threading, and its `verifier_versions` are reused unchanged.

**D2 — The model supplies evidence, never a conclusion.** The verify output is `{file, line_start, line_end, quoted_text, predicate}`. Code runs the predicate. **`refuted` does not appear in the schema and cannot be expressed.**
*Why (L1):* PR #107 `reader:serialization-contract` — a refuter quoting `models.py:133` byte-matches head, is grep-re-derivable, and is **factually true**; the refutation is still wrong, because `models.py:113-125` records that `exclude` is honored by `model_dump`/FastAPI *"and by nothing else."* `ReaderFinding` (`reader.py:330-334`) carries no line numbers, so a refuter picks its own target with nothing to check it against.

**D3 — Existence and value claims only.** Absence and universality claims ("nothing else reads this", "no other caller") render **unresolved**. They are never citation-certified.
*Why (L3):* the failure in D2 is direction-independent — the model chose which lines to read and the answer can live in the lines it didn't choose. `settle.py:1-7` already polices this: *"a claim about an absence cannot be settled by re-reading the diff; the check and the error are the same observation."*

**D4 — One predicate: `constant_value_is`.** The verify prompt is a **separate frozen prompt** (precedent: `DECISION_INTENT_SYSTEM` / `INTENT_SCHEMA`, `reader.py:135-138`), so every named predicate is permanent. `name_is_runtime_imported`, `column_exists_in_live_schema`, `path_does_not_exist` and `symbol_defined_in_file` each score **0/8** against the answer key and are **not** named. `symbol_referenced_at` (find-references — what #4/#6/#7 actually need) is added **only if built**, never speculatively.

**D5 — `evidence` discriminator on `ReaderFinding`:** `Literal["diff", "head-cited"]`, plus an optional citation list. It rides `verdicts.raw` (`store.py:81`, unvalidated JSON, absent from the run-detail key list) — **zero wire change, no TS edit.**
*Why:* `Reason` is validated with exact key-set equality at `web/lib/session-api.ts:289-292`, so a new key there is a rejected payload, not an ignored field. And without the discriminator, `REVIEWING.md:47`'s rule — *"A finding that depends on code outside the diff must say so… mark these ⚠️ rather than assert them"* — is unenforceable by construction, while a sha256 makes the weaker claim class look like the stronger one.

**D6 — Receipts are SHA-anchored:** `path@<head_sha>#Lstart-Lend` + sha256. `git show` needs a ref; a locator without one is unverifiable by anyone not sitting at that commit.

**D7 — Spend is isolated.** Own scope `verify:<id>`, third branch in `cap_for` (`reader.py:267`). **Never `installation:<id>`** — `instrument_snapshot` (`store.py:1314-1330`) reads that counter and renders `deep reads N/200` on the *customer's* check run, clamped at 200, so overspend would display as an allowance the customer never used. Hard per-PR read cap; timeout below the 120s read timeout (`api.py:2630` schedules `worker.drain`; `drain(max_jobs=20)` runs 20 jobs sequentially in one Starlette threadpool worker sharing the ~40-worker pool with `/healthz`).

**D8 — The coverage sentence ships with the increment.** `Coverage.complete` is `sent_chars >= diff_chars and not files_dropped` — diff-only — and `check_run.py:138,154` render the caveat *only when incomplete*, so today it usually doesn't render at all. The increment adds: *"Coverage below describes the diff Doug was sent. Files Doug opened at head are not part of that percentage and have no denominator."*
*Why (L9):* the vNext read-log gate proves citation honesty but supplies **no denominator** for what the model should have opened. The words are required either way; the gate is additive, not a substitute.

**D9 — ADR-0013 ships with this increment:** *"A model's citation may ground a published finding."* It must state that a citation does not move `risk_score` or `band` — only the finding's evidence class. ADR-shaped against the ADR-0007 precedent (new unvalidated signals get their own stream and never move the score).

## 3. Non-goals

Rendering the output surface. Deleting findings by model. Any absence claim certified by citation. Writing to `verdicts` from anything agentic. Touching the shipped `SYSTEM`/`SCHEMA`/`MODEL`/`EFFORT`/`MAX_TOKENS` or moving `PROMPT_HASH`. A per-finding confidence number. The per-source grading table. The Example Pack challenger arm (blocked on the `application_revision`-in-`instrument_id` ruling — partitions are n≈1 at 4.9 PRs/day with merge-to-main deploys).

## 4. Tests assert intent

- **Superset** — the finding set after head reads is a superset of the set before. This makes "the model never deletes" a property, not a promise, and replaces both round-1 suppression bars (an additive change cannot suppress).
- **Citation integrity** — a fabricated quote, an off-by-one range, and `resolve_file` returning `None` each yield an **ungrounded finding that still renders**. Never a wrong citation, never a drop.
- **Evidence class is honest** — every finding with a citation is `head-cited`; every finding without one is `diff`. Fails if the classes mix.
- **Absence refused** — a finding phrased as a universal gets `unresolved`, not a citation.
- **Spend isolation** — a run performing head reads leaves `instrument_snapshot`'s counter unchanged.
- **Smoke test, labeled** — replay PR #106 @ `616ff99` against `067e8ff`, report recoveries. **Not a bar:** the answers are committed in-repo, their "deltas worth encoding" specified this capability, and all 8 were scored before this spec was written.

## 5. Open risks carried into implementation

1. `read_budget_gate.py` will govern one channel of two. ADR-0012's freeze-replacement argument assumed it governed *the read*; after this it holds over the diff channel only. Disclosed in words (D8), not repaired by them.
2. Nondeterminism — Convergence Bar 1 already FAILed with reader nondeterminism as root cause. This adds a nondeterministic call that *adds* published findings. Measure over n replays; do not assume.
3. PR #106's 8 rows are load-bearing in two directions at once (they demote the disposition surface *and* justify this capability). n=1 PR.
4. `web/app/page.tsx:248-259` renders "0.69 / 0.67" under *"What's actually measured."* The correction sentence is a publishing precondition before this capability is announced.
