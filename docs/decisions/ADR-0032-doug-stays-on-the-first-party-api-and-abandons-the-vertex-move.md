---
title: Doug stays on the first-party Anthropic API, and the Vertex move is abandoned
status: accepted
date: 2026-09-03
supersedes: ADR-0028, ADR-0029
---

> **This reverses a direction, it does not report a failure.** Vertex works.
> The move is abandoned because it is no longer worth its cost, not because
> anything about it broke.

## Context

### What forced it

ADR-0028 moved the risk read to Vertex and declared a non-inferiority bar.
ADR-0029 shipped the move without running that bar, by direction, because the
Anthropic console balance funded the paired study or the cutover and not both.
Neither record's destination was ever reached: throughput quota for the Claude
5 lineage is zero in every servable location, the grant needs a Google account
team, and `.github/workflows/deploy.yml` has pinned `READER_TRANSPORT:
anthropic` throughout. Production has never taken a Vertex read.

Two things changed underneath those records.

**The cost pressure that forced ADR-0029 is gone.** ADR-0030 moved the
first-party transport to Workload Identity Federation, so the reader holds no
key and there is no credential to rotate, leak, or let expire. The
first-party API is not the fragile option ADR-0028 was routing around.

**The Vertex path acquired an open-ended dependency.** Quota is not
self-service for Anthropic models: it is issued only to projects with an
assigned Google sales representative (#274, Google Support, 2026-08-29). That
made the migration's completion date a function of somebody else's sales
process, and the whole apparatus — a deploy-time preflight, a required region,
a host table mirroring the SDK's — sat waiting on it.

### What this is not

It is not a measurement. No bar was run, on either transport, and this record
claims nothing about which serves better. ADR-0028's bar table is defective on
its own terms (#268) and is not resurrected here. If a transport question is
reopened, it starts from #268 and a new pre-registration, not from anything in
the superseded records.

## Decision

1. **The transport is the first-party Anthropic API, and that is the
   destination rather than a waypoint.** `deploy/gcp.sh` defaults
   `READER_TRANSPORT` to `anthropic`, matching `reader.DEFAULT_TRANSPORT`,
   which has read `anthropic` throughout. The workflow's value is pinned to
   `anthropic` by test rather than merely asserted to be one of two.

2. **The Vertex code path stays, unpromoted.** `_build_client`'s branch,
   `vertex_host` and the preflight in `deploy/gcp.sh`, and the
   `anthropic[vertex]` extra all remain. Deleting them is a separate,
   mechanical change and not a condition of this decision — a reversal and a
   large deletion in one diff makes the reversal harder to review, and the
   dead code is inert while nothing selects it. Tracked in #291.

3. **ADR-0028 item 1 survives.** `provider` names the API surface actually
   called, not the vendor of the weights. That ruling is why
   `WholeInstrumentManifestV0.provider` exists and it is unaffected by which
   surface is chosen. `PROVIDER_BY_TRANSPORT["anthropic"]` is `"anthropic"`
   and does not move, so no stored pack's `instrument_id` changes and the
   labelled corpus does not repartition.

4. **ADR-0030 stands in full.** It amended ADR-0029, but its subject is the
   CREDENTIAL on the first-party transport, not the choice of transport.
   Superseding ADR-0029 does not touch it, and this decision makes it more
   load-bearing rather than less: federation is now the only way the reader
   authenticates.

5. **#274 is closed.** Its premise — that a Vertex deploy would silently take
   the reader offline without quota — no longer describes anything that is
   going to happen.

## Consequences

### Why superseding matters more than the code

Only `accepted` records are fed to Doug's own intent tier. ADR-0028 and
ADR-0029 both said `accepted` while asserting a destination the project had
abandoned, and a record that is wrong does not merely mislead a human — it
produces a confident false deviation finding against any change that touches
the reader's transport. Both are now `superseded`, so they stay on disk for
their history and never reach the model.
`test_superseded_records_never_reach_the_model` is the mechanism.

### What this costs

The first-party API is a single provider with a single balance. ADR-0028's
Consequences called that out and the point is not retired by this record: an
exhausted balance fails every read soft into the deterministic score. What has
changed is that the second source was never actually available, so the choice
was between one transport and one transport plus an unfinished migration.

### Rejected

**Deleting the Vertex code in this change.** It is about 140 references across
eight files, most of them tests that pin real behaviour. Landing it with the
reversal would bury a four-line decision in a large deletion and make both
harder to review. Filed as #291 instead, so the deletion happens against a settled
decision rather than as part of settling it.

**Keeping ADR-0028 and ADR-0029 `accepted` with an amendment banner.** This is
the pattern ADR-0030 used, and it is right for a record that changes PART of
another. It is wrong here: the destination those two records exist to
establish is abandoned wholesale, and an `accepted` record keeps reaching the
intent tier no matter what its banner says.

**Marking them `deprecated` rather than `superseded`.** Both are excluded from
the reader identically, so nothing operational turns on it, but `superseded`
carries a pointer to the record that replaced it and `deprecated` does not.
The pointer is the part a later reader needs.

**Leaving `deploy/gcp.sh` defaulting to `vertex` and relying on the
workflow's pin.** The workflow is one caller. A hand-run deploy during an
incident — which is when `gcp.sh` is run directly — would take the Vertex
branch, hit the region refusal, and fail for a reason that has nothing to do
with the incident.
