# Phase 0(b) results — 2026-08-20

The $0 offline re-run per build-plan.md Phase 0(b), on the immutable 43-unit
sample, with the frozen attributions from `span-verification/` joined as
inputs. Recorded pass-or-fail per the pre-registered discipline; a fail is a
result, not a redo.

## The split (reproduced exactly)

| Classifier | resolved | persisted | unknown |
|---|---|---|---|
| Pure file-delta table | 6 (`hunk-edited`) | 26 (`by-construction`) | 11 (10 `not-reconfirmed`, 1 `left-diff`) |
| Attribution-refined | 11 (6 + 5 `attributed-edited`) | 30 (26 + 4 `attributed-surviving`) | 2 |

Coverage covariate: 0 `path_form_suspects` in the sample pairs.

## Bar A(B) — FAIL, both classifiers

Every `resolved` unit was adversarially hand-checked against git history (15
checkers, one per unit, quoted-evidence protocol; verdicts and evidence in
`span-verification/phase0_handcheck_verdicts.json`; two decisive claims
re-verified by hand on raw git).

| Class | False | The false units |
|---|---|---|
| `resolved(hunk-edited)` | **4 of 6** | #43 `data-loss` and `lock-contention` (the pair's only edit is a **5-line comment block**; the DELETE block and the `CREATE UNIQUE INDEX` are byte-identical at to_head); #56 `tier-classification-edge-case` (an adjacent guard line in the same hunk changed; the flagged line is unchanged and the defect replays live at to_head); #69 `unsafe-migration` (the file's single edit is the `due_at` expression; the flagged SHARE ROW EXCLUSIVE sequence is verbatim at to_head, and the pair's own docs commit *accepts* the stall) |
| `resolved(attributed-edited)` | **2 of 5** | #50 `error-handling-gap` and `partial-write` (the attributed hunks were edited — by the `revoke_token` owner-guard fix — but neither defect was touched) |
| `persisted(attributed-surviving)` | **0 of 4** | — |

True resolves confirmed: #50 `authz-scope-gap` and `logic-error`, #69
`config-path-fragility` and `dialect-specific-logic`, #90
`tooling-resolution-fallback`. Zero checkers uncertain.

## Root cause

The same epistemic error as the original rule 5, one level down. Old rule 5:
*the reader's silence is evidence of a fix*. This design: *a byte change in
the hunk is evidence of a fix*. Neither is. A comment insertion re-hashes a
hunk; an adjacent-line edit re-hashes a hunk; any edit to a file that entered
as one hunk (every new file) re-hashes its only hunk. In each case every
finding riding that hunk "resolves" while its defect survives verbatim.

The attribution layer is not the failure: it placed findings correctly
(0 contradictions in the span pass; 0/4 false on its carry-forward direction
here) and its two false resolves are inherited from the same edit-inference.

## What stands validated

- **Carry-forward by construction**: all five of the original evaluation's
  confirmed false-`resolved` disasters (including #50 `input-validation`, the
  defect-verbatim killer) now correctly carry forward. 0 false persisted among
  the 4 checked attributed-surviving units. **Bar B: PASS, 1/26** — all 21
  blank units evidence-checked adversarially (21/21 `addressed: no`, 0
  uncertain, quoted git evidence in `span-verification/barb_evidence.json`),
  4 carry-overs, 1 pre-declared `yes` (#75 deploy-ordering); Andrew signed
  2026-08-20 (`phase0_labeling_sheet.md`).
- **The silence count and the abstentions**: unaffected — they never claimed
  edit evidence.
- **Attribution stability and placement** (span-verification bars): unaffected.

## Consequence (pre-registered)

Bar A(B) is recorded FAIL for both classifiers. Phase 1 does not start with
any state that stops carrying a finding on edit evidence alone. The v1
response is Andrew's ruling; the recommendation on the table:

1. Demote `resolved(hunk-edited)` and `resolved(attributed-edited)` to
   `unknown(edited-not-verified)` in v1 — Doug keeps listing the finding
   under "can't say: the code changed and this read did not confirm or clear
   it". The wedge that ships in v1 is the validated half: by-construction
   carry-forward plus the published silence count.
2. Pre-register a **verify-at-resolve** pass for v1.1: before Doug ever stops
   carrying a finding, an adversarial model check against the actual repo
   state must fail to find the defect at to_head — the exact task shape that
   just went 15/15 with documented git evidence and caught all six false
   resolves. Own bars, own prereg, model-in-the-loop disclosed.
