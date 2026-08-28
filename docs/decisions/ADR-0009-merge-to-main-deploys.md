---
title: Merging to main deploys to Cloud Run
status: accepted
date: 2026-07-30
amended_by: ADR-0021
---

> **Amendment, 2026-08-26 (ADR-0021), narrowed 2026-08-28 (ADR-0025): the
> federation provider is pinned to main, not just to this repository.**
>
> One clause of the Decision below is amended: "pinned by attribute condition
> to this repository" undersold the boundary, because any branch of this
> repository could mint the deployer credential. The condition now pins the
> ref as well, so only a run on `refs/heads/main` can exchange its token — and
> a rollback dispatch on a tag or any other branch is refused there.
>
> ADR-0021 also held every deploy for Andrew's approval. That half lasted 32
> hours and is retired: ADR-0025 found it cancelled one merge's deploy outright
> and held others up to 17 hours, so "push to main builds and deploys" below is
> current text, not history.

## Context

Deploys were manual: `bash deploy/gcp.sh deploy` from a laptop, from
whatever happened to be in the working tree. That produced a real
incident on the first day of PR-based development — production was
deployed from an unmerged branch, so `main` and the running revision
disagreed about which features existed.

This is a solo repository. There is no staging environment to promote
through and no second reviewer, so the pull request is the whole review
gate.

## Decision

Push to `main` builds and deploys. Path filters decide which of the two
Cloud Run services is touched, so a copy change does not rebuild the API.

Tests run again in the deploy workflow even though CI already ran them on
the pull request, because a direct push to `main` skips the PR entirely
and shipping a red build is the one failure this pipeline exists to
prevent. The API deploy ends with a smoke test against a real route —
`/healthz` is intercepted by the Google frontend and never reaches the
app, so it cannot serve as a probe.

Authentication is Workload Identity Federation, pinned by attribute
condition to this repository.

## Rejected

**A service-account JSON key in repo secrets.** Simpler, but a
long-lived credential to a project holding the ledger and the Anthropic
key, sitting in a public repository's settings. WIF costs one setup
script and removes the credential entirely.

**A staging environment.** Nothing to promote through with one developer
and no customers. Revisit when a deploy can break someone else's day.

**Deploy without re-running tests**, on the grounds that CI already
passed on the PR. It does not hold for direct pushes to `main`, which is
exactly when nobody is watching.

## Consequences

- A bad merge reaches production in a couple of minutes. Cloud Run keeps
  revisions, so rollback is `workflow_dispatch` on an earlier commit or a
  traffic split.
- `gcp.sh deploy` and `web` are now pure deploys — no IAM, no resource
  creation — so the CI principal needs no admin rights. Anything
  privileged lives in `setup`.
- Cloud Build runs on every merge that touches code. Small, but not free.
