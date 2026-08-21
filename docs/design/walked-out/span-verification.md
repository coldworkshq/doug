# Span verification: option A vs option B, decided by measurement

Ordered by Andrew 2026-08-20 ("lets run a verification pass here. we can override ADRs
if we are achieving our goal of accuracy"). This file is the pre-registration; the bars
in it were frozen before any model call ran. Results are appended below the line at the
bottom and never edited above it.

## Question

Option B (the lock) identifies a finding by the hunk-hash multiset of its cited file's
diff and abstains on multi-hunk partial edits — 84 of 126 touched-file findings on the
eval corpus sit in files with more than one hunk, and most of them come out
`unknown(not-reconfirmed)`. Option A gives each finding its own span so those cases get
answers. The question this pass decides: **is model hunk-attribution stable and correct
enough to put in the identity path, and is the yield big enough to matter?**

## Instrument, and what it ceilings

Post-hoc closed-choice attribution: an Opus-class model (the diff-reader's model family)
is shown the numbered hunks of one file's diff exactly as sent at the *from* read, plus
the finding text Doug already stored, and must name the hunk numbers the finding rests
on, or answer "cannot attribute". Two independent runs (R1, R2) use byte-identical
prompts.

This task is strictly easier than option A as designed (the reader emitting line spans
mid-read, schema change, PROMPT_HASH move): the choices are enumerated, the finding is
already written, and nothing else competes for attention. **So this measures a ceiling:
if post-hoc attribution fails a bar, generative spans fail it worse.** If it passes,
the cheapest honest implementation is attribution itself — a small separate pass after
the read ("A-prime") that leaves SCHEMA and PROMPT_HASH untouched and ADR-0012 closed,
layered on option B's hunk index as a refinement, under a new ADR-0014.

## Population (frozen)

From `convergence-eval-run1.json`, the 76 SHA pairs: prior-side findings with a non-null
`file` whose file has ≥1 hunk in diff `merge-base(origin/main, from)..from` and is
touched between the reads (`git diff --name-only from..to`). n = 126:

- **Control, n = 42**: files with exactly 1 hunk. The only defensible answers are hunk 1
  or abstain.
- **Test, n = 84**: files with ≥2 hunks (2–19; median 5). B abstains on most of these.
- **Mechanical ground truth, n = 51 of 84**: findings whose label names a code token
  (backticked span, dotted call, snake_case identifier, or quoted string ≥4 chars) that
  appears in the +/- lines of exactly one hunk. Computed before any model ran; stored in
  the run artifacts.

No exclusions. Lockfiles and generated files stay in if they met the criteria.

## Derived state per run

For a finding with nonempty attribution H: **persisted** if every hunk in H (by content
hash of its +/- lines) survives into the to-read's hunk multiset for that file;
**resolved-candidate** if none survives and the later read did not re-report the
finding; **unknown(mixed)** otherwise. Empty attribution = **abstain**. Hash and
survival logic identical to `hunk_multiplicity.py` (same diff command, same base
`merge-base(origin/main, from)`).

## Bars (frozen before results)

- **Bar S — stability.** The derived state differs between R1 and R2 on at most 2 of
  the 84 test findings. Raw hunk-set agreement is also reported but the bar is on
  states, because a flip between two surviving hunks changes nothing while a flip
  between a surviving and an edited hunk manufactures a false `resolved` — the exact
  disease this lane exists to cure. B's instability is zero; the tolerance is 2/84
  because that is the level at which A's expected false-state count on this corpus
  stays below one per ~40 findings, comparable to Bar B's ≤1/26 allowance.
- **Bar C — correctness.** (a) On the 51 mechanical-ground-truth findings, in each run,
  a nonempty attribution that omits the mechanically located hunk occurs at most once
  per run. (b) On the 42 single-hunk controls, at least 90% attribute to the hunk
  (persistent abstention on certain cases collapses A's yield claim).
- **Bar P — prize.** Measured on the *marginal set*: test findings where option B
  abstains (`unknown(not-reconfirmed)` — partial hunk survival and the later read did
  not re-report). Re-reported findings are persisted under both designs (rules 1-4) and
  all-hunks-edited findings are `resolved(hunk-edited)` under both, so neither counts as
  yield. Bar: at least 50% of the marginal set receives a determinate state (persisted
  or resolved-candidate) that both runs agree on. The marginal-set membership is frozen
  in the run manifest before any model call. (Sharpened from an absolute-yield wording
  before any run; the absolute rate is still reported.)

**Frozen counts** (from `span_verification_run.py`, run 2026-08-20 before any model
call): 126 findings; 84 test, 42 control; marginal set 59 (Bar P threshold: ≥30
both-runs-agreed determinate); mechanical ground truth 51; 14 payload batches; run
artifacts archived in this folder's `span-verification/` directory (`manifest.json`,
`batches.json`; `batch_NN.md` payloads are reproducible from `span_verification_run.py`). Instrument: Opus-class subagents (the reader's model
family), one per batch per run, byte-identical prompts across R1/R2.

## Verdict rule (frozen)

- **All three bars pass** → A-prime enters v1: an attribution pass refines option B's
  hunk-multiset identity to the attributed subset; ADR-0014 records it; ADR-0012 stays
  closed because the reader schema never moves. Bars A(B)/B in the build plan are
  re-derived for the refined classifier before Phase 0 runs.
- **Any bar fails** → option B stands exactly as locked; A (both forms) stays vNext;
  the measured numbers are recorded here and in the debate record.

Andrew's standing instruction is honored either way: ADRs bend to measured accuracy,
not the other way around — this pass is the measurement.

---

## Results

(appended after the runs; nothing above this line changes)

Run 2026-08-20, workflow `wf_2829c92a-742`: 28 agents (14 batches x R1/R2), model
`claude-opus-5[1m]`, 1,119,321 subagent tokens, 0 errors, all 126 findings answered
exactly once per run. Raw returns archived in this folder's `span-verification/` directory (`calls.json`,
`grades.json`); grading by
`span_verification_grade.py` against the frozen manifest.

| Bar | Frozen threshold | Measured | Result |
|---|---|---|---|
| S — stability | ≤2/84 state flips | **0/84** (raw hunk-set disagreement 2/84, neither state-changing) | PASS |
| C(a) — GT misses | ≤1 per run | **1/51 per run** (same finding both runs; see note) | PASS |
| C(b) — control | ≥90% attribute | **42/42 both runs (100%)** | PASS |
| P — prize | ≥30/59 marginal | **50/59 (85%)** | PASS |

Marginal-set outcomes, both runs agreeing: 36 `resolved-candidate`, 14 `persisted`,
9 `unknown` (all mixed survival — the finding straddles edited and surviving hunks;
the honest abstain).

**Danger-class audit (beyond the bars).** The 36 `resolved-candidate` conversions are
where a wrong attribution would manufacture a false `resolved`. 25 of 36 carry
mechanical ground truth; in **0 of 25** did the mechanically located hunk survive
while the model attributed to edited hunks. No manufactured false `resolved` was
detected anywhere in the run.

**Note on the single C(a) miss.** Finding 69 (PR #51, `api/doug/api.py`, 7 hunks):
both runs said hunks {3,4}; the mechanical token points at hunk 5. On inspection the
token is a deploy-detail mention (`latest` binding in `gcp.sh` context) while the
finding's subject is the `KeysNotConfigured` raise — the mechanical locator, not the
model, is the doubtful party. Either way all 7 hunks survive, so the derived state is
`persisted` under both answers; the disagreement cannot change a state.

**Caveats.** Two samples per prompt bound stability loosely; the 2/84 raw
disagreements show generation is not deterministic, but a prospective run with more
repeats should accompany the v1.1 receipt work. Mechanical GT covers 51/84; the
uncovered remainder is validated by stability and the control cohort only. The task
remains a ceiling for generative spans (option A as originally drawn), which stay
vNext.

## Verdict

**All three bars pass. Per the frozen rule, A-prime enters v1**: a post-read
attribution pass (model maps each carried finding to hunk numbers of its cited file's
sent diff; code validates the numbers and computes survival against the stored hunk
index) refines option B's file-delta identity. Reader SCHEMA and PROMPT_HASH are
untouched; ADR-0012 stays closed; ADR-0014 records the attribution pass. Mixed
survival, invalid numbers, and abstentions all remain `unknown(not-reconfirmed)`.
Bars A(B) and B in the build plan are re-derived for the refined classifier before
Phase 0 runs.
