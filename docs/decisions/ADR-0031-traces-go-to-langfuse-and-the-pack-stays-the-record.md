---
title: Model calls are traced to Langfuse, and the example pack stays the record
status: accepted
date: 2026-09-03
---

> **A viewing surface, not a second record.** The Example Pack lane
> (ADR-0026, ADR-0027) remains the only evidence this repository reasons from.
> Nothing decided here may be cited from a trace.

## Context

### What forced it

There was no way to watch a review happen. A read that goes wrong is visible
in three places, none of which answers "what did Doug just do on this PR":

- One stderr line per paid call from `_report_cost`, giving tokens and a model
  and nothing about the prompt or the answer.
- The example pack, which is hashed, cohort-scoped and adjudicated — the right
  shape for evidence and the wrong shape for looking at one PR right now. It
  also covers two of the four paid passes: `verify_finding` and
  `attribute_findings` are deliberately outside it (`reader.verify_finding`
  says why), so half the paid calls are invisible to it by design.
- The verdict itself, which is the conclusion, not the working.

Four paid model calls now run per review across two tiers and two models. The
question "which pass cost that, and what did it see" had no surface at all.

### What is being sent, stated plainly

With tracing on, a span carries the exact bytes the model was sent — the
system prompt and the diff slice under `DIFF_BUDGET` — and the exact text it
sent back. That is tenant source code from private repositories, held by a
third party.

That is a real cost and it is the decision, not a side effect of it. It was
put to the founder as a choice between full payloads and a metadata-only mode
carrying tokens, latency and stop reasons but no content. Full payloads won,
because a trace without the prompt and the response answers "what did this
cost" and cannot answer "why did the reader say that" — and the second
question is the one worth a subprocessor for.

## Decision

1. **The four paid calls are traced to Langfuse Cloud, US host.** US rather
   than EU because `doug-api`, its ledger and its evidence bucket are already
   in `us-central1`, and `VERTEX_REGION: us` keeps reads there too. Sending
   traces to the EU host would put tenant source code under a jurisdiction
   nothing else in this deployment uses. `LANGFUSE_HOST` overrides it.

2. **The seam is the request dict, not the client.** `tracing.create` takes
   the request the caller already built, forwards it to the SDK unchanged, and
   reads `model`, `system` and `messages` out of that same dict. ADR-0002 and
   ADR-0012 make what reaches the wire evidence; a wrapper that assembled its
   own kwargs would be one refactor away from disagreeing with the frozen
   constants, silently, because the read would still succeed and the pack
   would still hash. Pinned by
   `test_the_request_reaches_the_sdk_unchanged_when_tracing_is_on` and by
   `test_the_request_is_identical_whether_tracing_is_on_or_off`.

3. **Tracing may never change, slow or break a read.** Every entry point in
   `tracing.py` swallows its own exceptions and every one of them has a test
   that goes red when the guard is removed. The reader falls back soft on any
   exception, so a tracing fault would not surface as a tracing fault: it
   would read as "the model is down" on every PR at once. That
   misdiagnosis has already cost this project once, on the Vertex transport,
   and adding a second cause of it would be a poor trade for a dashboard.

4. **Existence of the two secrets is the switch.** `deploy/gcp.sh` adds
   `DOUG_TRACING=1`, the host and both mounts only when
   `doug-langfuse-public-key` and `doug-langfuse-secret-key` both exist. A
   separate `TRACING=1` variable alongside them would give two ways to be
   half-configured, and both are quiet: a flag with no keys constructs a
   client that fails every export at a log level nobody reads, and keys with
   no flag look configured and trace nothing.

5. **The trace root is the review job, and the session is the head SHA.**
   `worker.drain` wraps `process_job`, so one review is one trace and its two
   to five model calls nest inside it. A second push to the same PR opens a
   new session rather than appending to the old one, because it is a review of
   different bytes and grouping the two makes "what did the reader see"
   unanswerable for either.

6. **The example pack stays the record.** Where the two disagree the pack is
   right. No finding, no measurement and no ADR may cite a trace: a span that
   a network hiccup can drop is not something to reason from, and this
   repository has spent enough on the difference between a receipt and a
   record.

## Consequences

### What this does not do

It does not measure anything. Traces are for looking at, and a number read off
one is a number with no denominator — the first thing anyone will want to do
with this surface is exactly what item 6 forbids.

It does not cover `scripts/llm_probe.py`, which must go on reporting what it
measured under its own configuration and gains nothing from a dashboard.

It does not flush per read. `worker.drain` flushes once at the end of a pass;
the synchronous `POST /v1/score/read` route flushes not at all, because that
request already spends its whole Cloud Run `--timeout 300` budget on a 240s
read bound plus backoff, and a blocking flush is the tail latency that turns
the `reader-unavailable` fallback into a platform 504.

### Open

Langfuse is now a subprocessor holding tenant source code, and Doug's published
privacy surface does not say so. That is decision debt with a named owner and
it blocks no code — tracing is off in production until the secrets exist.
Tracked in #289, which is also where the residency and retention answers land.
Creating the two secrets is founder-only under R11.

### Alternatives rejected

**Wrapping `_build_client`.** The obvious seam, and the one the reader's own
docstring points at as "the one construction site". Rejected on two counts: a
proxy around `messages.create` sees the exception but not `stop_reason`, not
the parsed output and not the spend cap, so the most interesting failures
arrive as successes; and every reader test injects `client=`, which would make
the proxy the one part of this that never ran under test.

**Emitting from `_record_attempt`.** Tempting, because it is already called at
every exit of the risk and intent reads with the request, the response, the
usage, the latency and the failure phase in hand. Rejected: it is gated on
`example_pack_capture.capture_requested()`, so tracing would inherit the
cohort gate; it hardcodes `model=MODEL`, so it would misreport the mechanical
tier the way `_report_cost` did before ADR-0027; and it carries no `scope`, so
nothing could be attributed to who paid for it.

**Metadata-only spans.** Offered and declined — see Context.

**Self-hosting Langfuse.** Keeps tenant source code on infrastructure Coldworks
controls and removes the subprocessor question entirely. Rejected for now on
cost of ownership: it is a container, a Postgres and a ClickHouse to run and
patch before anything is visible, which is a large standing obligation for a
viewing surface. It stays the answer if the subprocessor question resolves
against Langfuse Cloud.

**One trace per model call, with no root span.** Simpler, and it is what
happens on the synchronous read route where no job exists. Rejected as the
default because a review that ran a risk read, an intent read and three verify
calls would arrive as five unrelated rows, and reassembling them by hand is
the work this was supposed to remove.
