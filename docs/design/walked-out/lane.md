---
lane: walked-out
vertical: Outcome loop
status: parked
opened: 2026-08-19
closed:
next: Andrew confirms the Bar B sheet (phase0_labeling_sheet.md — evidence prefilled, review-and-sign), then Bar B is recorded and Phase 1 starts (7 commits, no resolved state in v1 per the 2026-08-20 demote ruling). Verify-at-resolve prereg is the v1.1 gate for any resolved state. PR #163 is open (ADR-0008).
branches: [design/walked-out]
prs: []
supersedes:
---

# Lane: Walked Out — evidence-gated `resolved` in the convergence lane

Doug's convergence lane marks an earlier finding `resolved` when the reader does not mention it again. Bar 1 of the convergence evaluation failed because the reader is nondeterministic: 26 of 43 sampled findings were "resolved" on files nobody touched. This lane replaces rule 5 so that Doug stops carrying a finding only with deterministic evidence (the cited file's diff changed in the PR and the reader did not report it again), carries it forward by construction when the cited file's diff is byte-unchanged, and abstains everywhere else. It adds one column (`reads.hunks`), no model calls, and no reader schema change, and it prints on every check run how many of Doug's own earlier findings on unchanged code the reader did not mention again. The name: a Saint Bernard leaves when it sees the traveler walk out, not when the snow shifts and it loses sight of them.

**Status: locked; Phase 0 run; resolved direction demoted by ruling (v1 ships carry-forward + silence count; no resolved state).** Span-verification passed (attribution is stable and places findings correctly); Phase 0's hand-check then proved edit-evidence is not fix-evidence — Bar A(B) FAIL, carry-forward direction fully validated. See [span-verification.md](span-verification.md) then [phase0-results.md](phase0-results.md).

## Read in this order

1. **[ground-truth.md](ground-truth.md)** — the grounding brief: real seams on `origin/main @ 7905735`, settled decisions, do-not-reopen, and the constraints the concept had not accounted for.
2. **[debate-record.md](debate-record.md)** — round-1 rulings, the hunk-multiplicity measurement that decided the span question (option B answers 195/265 findings and abstains on 70), the challenger's attacks, and the three convergence amendments.
3. **[span-verification.md](span-verification.md)** — the pre-registered measurement that settled ruling 1: frozen bars, 28-agent run, verdict (A-prime in v1).
4. **[phase0-results.md](phase0-results.md)** — Phase 0's recorded split, the failed Bar A(B) with per-unit evidence, root cause, and the pending ruling.
5. **[design-lock.md](design-lock.md)** — the locked design: converged design, resolved tensions, supersessions, red-team mitigations applied, non-goals.
6. **[product-spec.md](product-spec.md)** — what each user sees, the journeys and their cliffs, v1 versus vNext, and the honesty contract with the exact check-run sentences.
7. **[build-plan.md](build-plan.md)** — the architecture on the real seams, Phase 0 dogfood gate (amend the design note, then the $0 offline re-run), the ordered Phase 1 commits, and the test-for-intent strategy.
8. **[hunk_multiplicity.py](hunk_multiplicity.py)** and **[span_verification_run.py](span_verification_run.py)** / **[span_verification_grade.py](span_verification_grade.py)** — the measurement script; reproduces the 160/265 and 7/26/10 figures from `workspace/research/two-lane-2026-08-11/convergence-eval-run1.json` and the local clone.

## What a resumer most needs to know

- The ruling on bar 1 is this redesign. Bar 1 stays FAILED as recorded; Bar A(B) and Bar B are new bars on the same immutable sample.
- Identity is `(pattern, file, hunk-hash multiset)` computed from the patch Doug already fetches. Doug does not know which hunk a finding is about. ADR-0014 is the attribution pass (span-verification verdict); generative model-emitted spans are vNext under ADR-0015+.
- `store.py` is the only module allowed to import `convergence`. The worker and `score()` never do.
- The per-PR silence count ships on the check run in v1; the silence rate ships on the scoreboard in v1.1 after its sibling pre-registration; the honest denominator is earlier findings on unchanged files (160/213 = 75% on Doug's own history, file grain), not 160/265.
- The reland-labeler bug (`git_labels._attribute_reverts`) is backlogged and out of this lane; it gates defect-labelled publications, not the certificate.
