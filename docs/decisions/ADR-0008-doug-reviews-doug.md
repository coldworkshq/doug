---
title: Doug's development moves to pull requests so Doug reviews Doug
status: accepted
date: 2026-07-30
---

## Context

`drewjst/doug` had zero pull requests and zero merge commits — every
change went straight to main. Doug's dogfooding therefore meant Doug
reviewing `lemahq/lema`, not Doug.

Two things followed from that. The decision-record intent experiment
would have had to run against private lema, putting a human in the
critical path of every run. And Doug's own pull requests — heavily
agent-authored, which is precisely the population the thesis is about —
were entirely absent from the ledger.

## Decision

Doug's development goes through pull requests. `doug-review.yml` is
installed on this repo with `DOUG_API_URL` and `DOUG_API_TOKEN`, and this
repo's own install is opted in to the deviation tier.

**Surface correction, 2026-08-02 — the decision stands.** The line above
named `DOUG_INTENT=1`. That switch was process-wide, so it covered every
tenant rather than this repo alone, which is not what this record says.
Superseded by the `DOUG_INTENT_INSTALLATIONS` allowlist.

## Rejected

**Keeping push-to-main.** Cheaper day to day, but it leaves the
integrity experiment blocked on private-repo access and keeps the most
on-target PRs available out of the corpus.

**Pull requests for feature work only.** Less friction, but the ledger
would then hold a biased sample — exactly the changes most likely to
carry risk. Fine for qualitative review, misleading the moment it feeds
a number.

## Consequences

- Branch-and-PR friction on a solo repository. This is the whole cost.
- A pull request that changes `reader.py` is scored by the *deployed*
  reader, not by itself, so the circularity is mild. Combined with
  `continue-on-error` and job-summary-only output, a broken reader cannot
  block its own fix.
- Doug's repo has no revert history, so these verdicts carry no outcome
  labels for a long time. This is a qualitative dogfood — do the findings
  look right — and not a source of precision numbers.
