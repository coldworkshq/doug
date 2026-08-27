---
title: Doug does not depend on lema
status: accepted
date: 2026-07-30
amended_by: ADR-0022
---

> **Amendment, 2026-08-26 (ADR-0022, proposed): the empty provider slot is
> filled by an internal store, not by lema.** The clause "a lema-backed
> provider sits behind the same interface, unimplemented, until lema exposes
> decisions with status and repo scoping" is retired: lema is retired as a
> product, and Doug's own `memory` schema supplies status-filtered records
> behind the unchanged `IntentDoc` contract. Everything else here stands —
> Doug owns the interface, Doug's decisions live in this directory, a
> repository with no ADRs gets an inert feature. The amendment takes effect
> when ADR-0022 is accepted.

## Context

Doug is adding recorded architecture decisions as an intent surface for
the reader. lema is a decision-record product, built by the same author,
already installed locally. The obvious move is to read decisions from
lema's store.

Two facts argue against it. Decisions about Doug were recorded in lema's
workspace in July 2026 — `lema:d_81e789`, `d_48b302ae` — even though
Doug was never ingested into lema as a repo. And lema's hosted interface
is search-only in its current form, with no status filter, so it cannot
distinguish an accepted decision from a superseded one. `d_81e789` still
records "LLM-assisted scoring — rejected: destroys the cost wedge",
which ADR-0004 overturned; feeding it to the reader would produce a
confident finding that Doug's own shipped reader is a deviation.

## Decision

Doug owns the provider interface and the contract it needs —
`{id, title, body, status, date}` — and implements one provider that
reads ADR-format markdown from the repo under review, using the
per-request GitHub token CI already supplies.

A lema-backed provider sits behind the same interface, unimplemented,
until lema exposes decisions with status and repo scoping. Whether it
ever does is lema's product decision, not Doug's to assume.

## Rejected

**Reading from lema's hosted search now.** No status filter means
feeding superseded decisions to the model, which is the one failure mode
this design exists to avoid.

**Making decision-record intent a lema-integrated feature.** It would
tie Doug's differentiating capability to lema's customer base. Doug's
addressable market must not be another product's user list.

## Consequences

- Doug's own decisions have to live in Doug's repo. This directory is
  that, and it is a prerequisite for dogfooding rather than a side quest.
- The overlap with `lemahq/lema-verify` resolves: lema-verify is lema
  checking its own decisions; Doug is a reviewer that accepts decisions
  as one input among several. One insight, two products, no shared code.
- Repos with no ADR directory get an inert feature, not an error. That is
  the common case.
