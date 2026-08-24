---
title: The needs-you line is a per-repository setting, forward-only, one number for both scorers
status: accepted
date: 2026-08-18
amended_by: ADR-0019
---

## Context

The line above which Doug says "needs you" was process-wide: DOUG_THRESHOLD
(0.62, deterministic scorer) and DOUG_READER_THRESHOLD (30/100, reader).
Production runs the reader, so most verdicts were scored against 0.30 and
only fallbacks against 0.62. A docs-only repo and a Terraform repo have very
different costs for a false "needs you" and shared one line. The dashboard's
threshold lens argued the line "is not a setting because it cannot be" —
true of the wiring, not a constraint. Spec:
docs/superpowers/specs/2026-08-18-per-repo-needs-you-threshold-design.md.

## Decision

- Per-repository: `installation_repos.needs_you_threshold` (0..1, NULL =
  inherit), set via `PATCH /v1/sessions/repositories/{id}` behind the
  `settings:write` session scope, edited on the Repositories view.
  **Amended by ADR-0019:** also edited on `/dashboard/settings`. The
  Repositories view keeps its control — the adjacency argument below is
  unchanged — and both surfaces render one component against this same PATCH.
- Forward-only: read at scoring time and stamped on the verdict; existing
  verdicts keep their line; open PRs keep their check until a new commit.
- One number for both scorers; the reader receives round(t*100).
- The unset state is displayed as both defaults (0.30 deep read / 0.62
  fallback), never one.
- Authority: any member of the bound WorkOS org whose live entitlement
  reaches the repo. Weaker than key minting (repo admin) and bind
  (installer); accepted because org membership is operator-curated and
  the setting is reversible and audited by the verdicts it produces.
- Two-PR deploy: web response guards tolerate the new fields first, because
  the API is promoted before web.

## Rejected

- Retroactive re-banding of the ledger — the ledger would stop matching
  the check runs posted to GitHub.
- An in-repo config file (`.doug.yml`), or both — a file fetch per review;
  two sources of truth. Can be layered later without moving the column.
- Two knobs (reader / deterministic) — two settings for one question.
- Displaying a single "default" of 0.62 — false in production, and the
  lie `_banding_threshold` was built to end.
- Installer-only writes via `_prove_installer` — a WorkOS read per write
  and policy locked to one person.

## Consequences

- The lens survives as a preview; the gear is "preview at…", the setting is
  the "flag line", and a contract test keeps the names apart.
- Setting one number moves the two scorers in opposite directions from
  their defaults; the control's copy says so.
- `/v1/queue` `summary.threshold` is a mode and can mislead once an
  installation's repos differ; deferred (`?repo=` is exact).
- Uninstall + reinstall yields a new installation and the setting does not
  carry; remove + re-add of a repo under the same installation keeps it.
- A global `RequestValidationError` handler was added to the FastAPI
  application so a NaN/Infinity threshold body 422s instead of 500 (the
  stock handler, with non-finite floats stringified before the response
  is serialised).
- **Amended by ADR-0019**, which adds `/dashboard/settings` as a second home
  for these controls and a third setting (`installation_repos.deep_read`)
  beside them. Nothing in this record is retired: the line is still one number
  for both scorers, still forward-only, still authorised the same way, and
  still sits beside the "needs you" count on the Repositories view for the
  reason stated above.
- Reader-fed: this record is `accepted`, so the reader will flag PRs that
  reintroduce a process-wide-only line, or make the settings PATCH advance
  `installation_repos.updated_at` (webhook reconciliation legitimately does;
  the settings write must not).
