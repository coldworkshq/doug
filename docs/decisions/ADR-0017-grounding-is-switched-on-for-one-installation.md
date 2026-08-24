---
title: Switch grounding on, for one named installation, behind an allowlist
status: accepted
date: 2026-08-23
---

## Context

`reader.ground_findings` and `verify.run_check` landed dark in #118 under the
cited-head-reads design lock. `reader.py`'s own docstring stated the posture:

> Landing the code dark means the PR that introduces it can be reviewed and
> merged without changing what Doug does to anyone, and the capability is
> switched on deliberately.

The deliberate act was never recorded. Doug flagged that on its own review of
`da5b3fb`: "no recorded decision covers switching grounding on." It was right —
the design lock covers *building* cited head reads and says nothing about
enabling them, and ADR-0014's precedent for a comparable live-surface change
(the sticky PR comment) carried a design doc, an allowlist, and a changelog row.
This ADR is the missing half.

Why now: the dominant miss class on the only rater-independent evidence in the
repo is findings whose disproof lives in a file absent from the PR — 4 of 8 on
PR #106 (`docs/superpowers/specs/2026-08-18-cited-head-reads-design.md`).
Grounding is the only shipped capability that reads outside the diff to *raise*
confidence rather than to subtract, which is the asymmetry design-lock.md:11
says produced those misses.

## Decision

Grounding is on for installation `150424894` (dogfood) and nobody else, through
`DOUG_VERIFY_INSTALLATIONS` in `api/deploy/gcp.sh`.

`reader.verify_enabled()` — a process-wide `DOUG_VERIFY == "1"` boolean —
becomes `reader.verify_enabled_for(installation_id)`, matching
`intent.enabled_for` and `pr_comment.allowed` in shape and in failure mode: an
unset or empty allowlist enables **nobody**. The installation is derived from
the same `scope` string the risk read charged, so who pays and who opted in
cannot drift apart.

## Rejected

**The `DOUG_VERIFY=1` boolean that was already there.** It would have enabled
paid grounding for every installation the service reviews, and kept doing so for
every installation added later, silently. This is the mistake
`docs/design/outcome-loop/design-lock.md:64` records one tier down: `DOUG_INTENT`
shipped as a process-wide switch and was "the opposite of 'default OFF' ...
harmless only because there has only ever been one installation." The lesson
recorded there is that a red-team mitigation written in a design file is not
evidence it exists in the code. Repeating the boolean would have made this ADR
that same kind of writing.

**Waiting for a wider predicate vocabulary.** `VERIFY_SCHEMA` names one
predicate, `constant_value_is`, and design-lock.md:37 cut the vocabulary to that
plus at most one more on measured grounds — the other four candidates scored
0/8. Waiting would mean holding the capability dark for work that is explicitly
gated on infrastructure that does not exist (`build-plan.md:40`: do not name
`symbol_referenced_at` speculatively). One predicate producing mostly
abstentions is the designed starting state, not a reason to defer.

## Consequences

- Up to `MAX_VERIFY_READS_PER_REVIEW` = 2 extra paid calls per review, on the
  dogfood installation only. On `claude-sonnet-5` (ADR-0016) that is about
  $0.019 per review against a ~$0.074 risk read.
- **Most findings will abstain.** One predicate, Python-only, existence-and-value
  claims only (ruling L3). A low grounding rate in the first weeks is the
  expected shape, not a defect. An abstention costs a call and stores nothing.
- The spend does **not** reach the customer's published `deep reads N/200` meter:
  `verify_scope` carries its own prefix, which is what design-lock Task 5
  isolated it for.
- Check-run output changes for that installation — findings can now carry an
  evidence class and a citation.
- **Reversal is one env var.** Removing the id from `DOUG_VERIFY_INSTALLATIONS`
  and redeploying turns it off with no code change and no migration.
- What would justify widening the allowlist: a period of real reviews where the
  grounded findings are checked by hand and the abstention reasons read as
  honest rather than as breakage. No date is set here, deliberately — ADR-0014's
  "one reversible week" was a guess, and this one has no comparable notification
  cost to bound it.

## What this ADR does not cover

Switching on `DOUG_ATTRIBUTION`, widening the predicate vocabulary, raising
`MAX_VERIFY_READS_PER_REVIEW` (design-lock: "going bigger is a repricing, not a
config knob"), or removing the allowlist. Each needs its own record.
