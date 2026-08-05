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

Doug's development goes through pull requests. The GitHub App is installed
on this repo, and this repo's installation is opted in to the deviation
tier via `DOUG_INTENT_INSTALLATIONS`.

**Surface correction, 2026-08-02 — the decision stands.** The line above
named `DOUG_INTENT=1`. That switch was process-wide, so it covered every
tenant rather than this repo alone, which is not what this record says.
Superseded by the `DOUG_INTENT_INSTALLATIONS` allowlist.

**Mechanism correction, 2026-08-05 (Task 9) — the decision stands.** The
line above named `doug-review.yml` installed with `DOUG_API_URL` and
`DOUG_API_TOKEN`. That was the CI-token path, retired in the same commit
that corrects this record: every GitHub call now goes through an
installation token the service mints itself, and the dual CI/App run this
decision originally described has stopped. The webhook → queue → worker
pipeline is the only ingest path; the check run is the only surface.

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
  reader, not by itself, so the circularity is mild. Combined with the
  always-`neutral` check-run conclusion (ADR-0010), a broken reader cannot
  block its own fix.
- Doug's repo has no revert history, so these verdicts carry no outcome
  labels for a long time. This is a qualitative dogfood — do the findings
  look right — and not a source of precision numbers.
