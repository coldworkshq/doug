---
title: A post-read attribution pass refines convergence identity; edit-evidence never resolves
status: accepted
date: 2026-08-20
---

## Context

The convergence lane's rule 5 read the reader's silence as evidence of a fix
and failed its bar arithmetically (5 confirmed false-`resolved` in a 43-unit
sample; precision ≤ 0.884 < 0.90). The Walked Out redesign
(`docs/design/walked-out/`) replaced silence with hunk-set evidence: identity
is the multiset of the cited file's sent-hunk content hashes
(`reads.hunks`), and a byte-unchanged delta carries the finding forward by
construction. That leaves multi-hunk partial edits: file-delta identity
cannot say which hunk a finding rests on, so 59 of 84 such findings on the
evaluation corpus abstained.

Andrew ruled the identity question be settled by measurement. A
pre-registered pass (`docs/design/walked-out/span-verification.md`, bars
frozen before any model call) graded closed-choice hunk attribution — the
model picks hunk numbers from an enumerated list, code validates every
number — on 126 findings, double-run: 0/84 state flips, 42/42 single-hunk
controls, 50/59 yield on the abstention class, and 0/25 danger-class
contradictions against mechanical ground truth.

Phase 0 then hand-checked every `resolved` the refined classifier produced
on the 43-unit sample and falsified the edit inference itself: 6 of 11
`resolved` calls were false (`docs/design/walked-out/phase0-results.md`) — a
comment-only edit, an adjacent-line edit, and any edit to a new file's
single hunk re-hash a hunk without touching its defect. The carry-forward
direction was clean everywhere (0/4 false `attributed-surviving`; Bar B
signed at 1/26 with the one member pre-declared).

## Decision

- **Attribution is a separate post-read pass**, one batched charged call per
  reader-tier read (`reader.attribute_findings`): the model maps each
  finding to the numbered hunks of its cited file's sent diff; code converts
  validated numbers to content hashes from `Coverage.hunks` and stores them
  on the finding (`findings.hunks`, migration 014). The risk read's frozen
  `SYSTEM`/`SCHEMA`/`PROMPT_HASH` are untouched; the pass carries its own
  frozen pair and `ATTRIBUTION_PROMPT_HASH`. ADR-0012 stays closed.
- **Fail soft, land dark.** Any failure — spend cap, transport, stop
  reason, parse, out-of-range pick, index drift — stores nothing; the
  classifier reads a missing attribution as `unknown(not-reconfirmed)`.
  Enabled by `DOUG_ATTRIBUTION=1` (the `DOUG_VERIFY` posture); its scope
  prefix `attribution:` keeps the spend off the published meter.
- **Edit-evidence never resolves.** Per Andrew's 2026-08-20 ruling after
  Bar A(B) failed, v1 has NO `resolved` state: every-hash-gone outcomes are
  `unknown(edited-not-verified)` ("Doug has not verified a fix, so it stays
  listed"), whether file-grain or attributed. The only paths to a future
  `resolved` are pre-registered in `convergence-design.md`
  ("Verify-at-resolve — pre-registration hook"): an adversarial model check
  against the repo at `to_head` that fails to find the defect, with stored
  evidence and a zero-false hand-checked sample, or `settle.py`'s
  deterministic disproof (which stays `unknown(settled)` in v1).
- **Attribution refines only the carry-forward direction in v1**:
  `persisted(basis=attributed-surviving)` when every attributed hunk
  survives byte-identical; everything else abstains.

## Consequences

- The killer false-`resolved` (#50 `input-validation`, defect verbatim at
  the later head) classifies `persisted(attributed-surviving)` — carried,
  correctly — and all five originally-confirmed false-`resolved` disasters
  carry forward.
- Numbers derived from re-derived history carry the label `hunk-emulated`
  (`convergence_eval.py --emulate-hunks`); stored rows are `stored`.
- The design docs name "migration 12" and "ADR-0014"; both numbers were
  claimed on main between the lock and the build. The binding content is the
  column set (`reads.hunks`, `findings.hunks` — migration 014) and this
  decision (ADR-0015).
