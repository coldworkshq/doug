---
title: The deep read is a per-repository setting that narrows only, and the settings live on a page as well as the table
status: accepted
date: 2026-08-23
amends: ADR-0013
---

## Context

Two things were wrong at once, and only one of them was a missing feature.

**Unreachable.** Both per-repository settings shipped and worked — the flag
line (ADR-0013) and the sticky PR comment (ADR-0014) — and neither could be
found. They live in a `<details>` inside one cell of `/dashboard?view=repositories`,
under a column named "flag line". Nothing on the public site linked to
`/dashboard` at all: the `SiteHeader` component is static and renders
"Sign in" whether or not you are signed in, and `withAuth` is called only under
`/dashboard`, so after leaving that page the URL bar was the way back. The only
control on the screen wearing the word "Settings" was a gear holding sign-out
and Connect repositories.

**No way to decline the reader.** Production sets `DOUG_READER=1` (ADR-0004),
so every reviewed repository has its diff sent to the model. A repository whose
owner does not want that had no setting; the only lever was
`DOUG_READER` itself, which is process-wide and would have turned the reader
off for every tenant at once.

ADR-0013 placed the flag line on the repositories table for a stated reason:
the line sits one column from the "needs you" count it decides, and reading
them together is the point. That reason still holds. It is an argument about
the LINE and about the person already reading the ledger; it says nothing about
someone who has not opened the ledger, does not know the phrase "flag line",
and is looking for the place where Doug is turned down.

## Decision

- **`/dashboard/settings` exists**, listing every repository the installation
  covers with its three controls. The repositories table KEEPS its control:
  ADR-0013's adjacency argument is untouched. Both surfaces render one
  `FlagLineControl` (`layout="cell" | "page"`) against one API, so the
  forward-only promise is written once.
- **The marketing header carries a plain `Dashboard` link**, first in
  `NAV_LINKS`. Not session-aware: `withAuth` in `SiteHeader` would make
  `/about` and every `/docs` page render per request to choose between two
  words, and `proxy.ts` already hands an unauthenticated `/dashboard` request
  to AuthKit.
- **The rail gear is "Account", not "Settings".** Two different things sharing
  one word on one screen is the confusion the gear/flag-line naming test
  already refuses.
- **Per-repository deep read**: `installation_repos.deep_read`
  (`NOT NULL DEFAULT TRUE`), set through the existing
  `PATCH /v1/sessions/repositories/{id}` behind `settings:write`, read by the
  worker at scoring time beside the flag line.
- **It narrows only.** `reader.enabled()` (`DOUG_READER`) stays the master
  switch and the spend control; `review.score_one` requires both. A `true`
  here cannot turn a read on where the service has it off.
- **It gates the intent tier too** (`review.read_intent`). A repository whose
  owner turned the LLM read off turned off the LLM, not one of the two things
  Doug asks it.
- **Off is named on the verdict**, under the rule `deep-read-off`, distinct
  from `reader-unavailable` (a fault) and `reader-capped` (a budget).
- **A missing or removed row reads as ON**, the opposite of
  `repo_pr_comment`'s default and deliberately so — see Consequences.
- **Two-PR deploy**, the same sequence ADR-0013 used, and this record lands
  with the FIRST of them. `deploy.yml:162` gives the web job
  `needs: [changes, api]`, so the API is always promoted before web: PR 1
  ships the settings page, the header link and a response guard that TOLERATES
  `deep_read`; PR 2 adds the column, the API that emits it, the worker read
  and the toggle, and tightens the guard back. A reader at PR 1's commit will
  not find `installation_repos.deep_read` — the decision precedes its
  implementation on purpose, because PR 1's guard tolerance is otherwise a
  change with no recorded reason.

## Rejected

- **Moving the flag line off the repositories table.** ADR-0013's reason for
  putting it there was tested rather than assumed, and it still holds. Both
  places, one API, one component.
- **A session-aware header.** One word, paid for by turning `/about` and eleven
  `/docs` routes from static into per-request renders.
- **`DOUG_READER` per installation, through an allowlist env var**, the shape
  ADR-0017 used for grounding. It is an operator lever, and this is a tenant
  decision about their own repository; routing it through a deploy makes the
  operator the bottleneck for every opt-out.
- **A separate reader-model or effort setting per repository.** ADR-0018
  freezes `EFFORT` against an unrun pre-registration; exposing it would settle
  by product what that record says is unmeasured.
- **Folding a missing row into "off"**, matching `repo_pr_comment`. Rejected on
  the asymmetry in Consequences.
- **Retroactively re-scoring anything.** Forward-only, like the line.

## Consequences

- **Turning the read off MOVES THE BAND on an unset repository.** With no flag
  line of its own, Doug bands at `DOUG_READER_THRESHOLD` on a deep read and at
  `DOUG_THRESHOLD` when the reader did not run — so switching the read off also
  switches the line, and Doug asks for a human less often rather than merely
  differently. The control's copy states this, and states it only when the
  repository actually has no line of its own.
- **A missing or removed `installation_repos` row reads as deep-read ON**,
  where the same fault reads as PR-comment OFF. Both are reconciliation faults
  (the API's startup DRIFT line), and the costs of being wrong are not
  symmetric: resolving towards "off" for the sticky comment means silence on a
  PR nobody could have toggled, while resolving towards "off" here silently
  downgrades the verdict AND moves the band with it, with nothing on the check
  run saying why. Spending on a read for a repository whose row went missing is
  the cheaper way to be wrong.
- **A removed row is still readable and no longer writable**, like
  `repo_threshold` and unlike `repo_pr_comment`: a job already running keeps
  the setting it was configured with rather than changing scorer partway
  through.
- Verdicts on an opted-out repository record `tier="deterministic"` with null
  coverage, so the repositories table's "read" column shows an em dash. That is
  correct and must not be "fixed".
- **The toggle can read "on" while no read happens**, if the service has
  `DOUG_READER` off. The copy says the setting narrows rather than promises,
  and the ledger's tier and coverage columns are the evidence. A service-level
  indicator in the connections response is deferred to
  [#196](https://github.com/drewjst/doug/issues/196) — the issue is the
  tracker, not this line.
- All three settings writes now revalidate `/dashboard` and
  `/dashboard/settings`. Two surfaces disagreeing about a setting is worse than
  either being stale: it makes the reader doubt the write landed.
- Reader-fed: this record is `accepted`, so the reader will flag PRs that make
  the per-repo deep read able to turn a read ON where `DOUG_READER` is off,
  that leave `read_intent` running for an opted-out repository, that collapse
  `deep-read-off` into `reader-unavailable`, or that let a settings write
  advance `installation_repos.updated_at`.
