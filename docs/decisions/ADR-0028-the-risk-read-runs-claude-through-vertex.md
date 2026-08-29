---
title: The risk read runs Claude through Vertex, and clears a non-inferiority bar before it does
status: accepted
date: 2026-08-28
amends: ADR-0012
amended_by: ADR-0029
---

> **AMENDED BY ADR-0029, 2026-08-28. THE BAR BELOW WAS NEVER RUN, AND THE MOVE
> SHIPPED ANYWAY. This record's title is inaccurate from that date onward: the
> transport moved to Vertex WITHOUT clearing a non-inferiority bar.**
>
> Read **ADR-0029** before acting on anything in this file. Andrew directed the
> move the same day this record was signed, because the Anthropic console
> balance funds the paired study or the cutover and not both. ADR-0029 records
> the direction, the reason, and the fact that the resulting instrument era
> ships governed by nothing.
>
> **The bar table below is also defective and must not be reused.** Its baseline
> does not reproduce from the extraction this record names, and the corpus it
> names holds no finding dispositions and so cannot produce the quantity it
> measures. Both defects are recorded in **#268**, which is open and is a
> founder ruling. A bar declared against the Vertex transport later starts from
> #268, not from the table below.
>
> What survives unchanged: item 1, that `provider` names the API surface
> actually called, so the labelled corpus partitions at the cutover; and item 6,
> that the rollback is a value and not a redeploy. ADR-0029 implements both.
>
> ---
>
> *The original banner, kept because the history is the point:*
>
> > **SIGNED 2026-08-28. The bar was declared before the run, and the run has
> > not happened.**
> >
> > This record shipped on 2026-08-28 with its bar table blank and a note
> > saying it could not be signed as it stands. Andrew set the two governing
> > numbers the same day — a 5.0 pp absolute margin on validated yield, scored
> > on a 300-PR sample — and the two derived constraints follow from them and
> > from bounds already in the code. See **The bar**.
> >
> > **Nothing has run.** Signing this record declares the bar; it does not
> > report a result. No traffic has moved to Vertex, and none does until the
> > paired silent run clears the table below. If the run fails, the bar does
> > not widen — that is the failure this file is arranged to prevent, and it is
> > stated again in Consequences.
>
> Companion record: **ADR-0027** moves the *mechanical* tier's vendor boundary
> and is also `accepted`. They are separate on purpose: ADR-0027's tier is
> validated by code on every call, and this one's is not validated by anything
> downstream, which is the distinction ADR-0016 drew and neither record blurs.

## Context

### What actually changes, and what does not

Claude Opus 5 through Vertex is the same weights reached over a different API
surface. Verified on this commit, in the deployed environment:

| Fact | State |
|---|---|
| `anthropic` version | 0.120.2, already a declared dependency |
| `anthropic.AnthropicVertex` | present in the installed package |
| `google-auth` | 2.56.3, already installed transitively through `google-cloud-storage` |
| Client construction sites | two, `reader._client` and `reader._verify_client` |
| Other client construction anywhere in `reader.py` | none |

So the transport move adds **no new SDK and no new vendor**, and
`tool_versions` — which names `anthropic-sdk`, `pydantic`, and `python` — does
not move. That is the unusual part of this change and the reason it is worth
doing separately from anything else: the diff is two functions and a
dependency extra.

`MODEL` stays `"claude-opus-5"`. ADR-0012's freeze on `SYSTEM`, `SCHEMA`,
`MODEL`, and `MAX_TOKENS` is untouched, and
`test_reader_and_probe_share_the_validated_prompt_bytes` compares those four
constants against `scripts/llm_probe.py` — not clients, not transports — so it
stays green by construction. **This record `amends` ADR-0012, and the earlier draft that said it did not was
wrong.** Doug caught the inconsistency (`beyond-ticket`): this same PR marks
both sides of the ADR-0016/ADR-0027 amendment and then authorizes a vendor
boundary change to the frozen judgment tier with no banner on the freeze record
at all. Asserting "the freeze covers constants, not transports" IS a claim about
what ADR-0012 means, made by the record that benefits from it — the exact
self-authorized scope claim ADR-0016 was criticized for and ADR-0027 exists to
ratify. So it is declared as an amendment and marked on both sides.

What it amends is the freeze's SCOPE, not its list. `SYSTEM`, `SCHEMA`, `MODEL`
and `MAX_TOKENS` remain frozen, byte-identical to the probe, and the coverage
bar on `DIFF_BUDGET` is untouched. What this record settles is that the freeze
governs the request's constants and not the transport that carries them —
which, because the Vertex ID is the same string, is a distinction with no
observable difference today and a real one the moment a dated snapshot is
pinned.

### The frozen MODEL, and what happens to it on Vertex

Doug raised this as a `missing-from-pr` deviation and it was a real hole: ADR-0018
keeps ADR-0012's freeze on `MODEL` explicitly binding, byte-identical to
`scripts/llm_probe.py`, and an earlier draft of this record authorized Vertex
without saying how a Vertex model identifier reconciles with that constant or
which test would catch a divergence. Checked and answered:

- **Vertex model IDs carry no prefix.** A current-generation model uses the bare
  first-party ID, so the string is `claude-opus-5` on both transports. `MODEL`
  does not move, and `test_reader_and_probe_share_the_validated_prompt_bytes`
  — which compares `SYSTEM`, `SCHEMA`, `MODEL` and `MAX_TOKENS` against the
  probe, not clients or transports — stays green by construction rather than by
  anyone remembering to keep it green.
- **`effort` is generally available on Vertex.** `EFFORT = "high"` carries over
  unchanged, so ADR-0018's divergence from the probe is unaffected.
- **The construction is `AnthropicVertex(project_id=..., region=...)`** from the
  same `anthropic` package, authenticated by GCP application default
  credentials. No Anthropic API key, no second SDK.

**The guard, and the one case that breaks it.** Dated *snapshot* IDs on Vertex
use an `@` separator (`claude-opus-4-5@20251101`) where the first-party API uses
a hyphen. Doug's question — which test would catch the divergence — has this
answer: when the client change lands, the Vertex client is constructed with
`reader.MODEL` **verbatim**, with no transport-specific mapping, and that is
pinned by test. A mapping layer is the thing to refuse, because it is how
`MODEL` comes to say one thing while the wire says another, which is the exact
state ADR-0012's freeze exists to make impossible.

If Doug ever pins a dated snapshot, the two transports stop sharing a string and
this record is wrong. That reopens it; it does not get worked around.

### The thing that is not free

`WholeInstrumentManifestV0` carries a `provider` field, hardcoded `"anthropic"`
at the risk-read call site. What that field means has never been decided,
because until now there was only one answer.

A2 in `docs/design/outcome-loop/addendum-agentic-architecture.md` states the
governing rule: whole-instrument identity covers the model snapshot and
inference parameters, prompt and output schema, input budget and ordering,
tools, orchestration graph, runtime commit, fallback policy, and publication
policy — and "any change creates a new instrument era and cannot silently
inherit historical evidence."

Two serving stacks for the same weights can differ in defaults, in snapshot
pinning, in retry and error surfaces, and in when a version is retired. None of
those differences is visible in a verdict row. Pooling them is exactly the
silent inheritance A2 forbids.

### The bar this runs against

`design-lock.md:83` names open risk #2: a single frozen instrument, where
"model retirement or price change forces a new validation run." A2 sets two
bars and the distinction decides how expensive this is:

- **Superiority** for a voluntary swap.
- **Non-inferiority** when a price or retirement event forces the move.

This is the forced class. The instrument is not being changed because a better
one was found; it is being moved because the terms of reaching the current one
changed. Demanding superiority here is how a forced move ships unmeasured
instead of measured, because the bar nobody can clear is the bar nobody runs.

## Decision

**1. `provider` names the API surface actually called, not the vendor of the
weights.** Moving the risk and intent reads to Vertex changes that field,
therefore moves `instrument_id`, and therefore partitions the labelled corpus
at the cutover. Reads before and after are not pooled. This is a cost, it is
chosen deliberately, and the alternative is in Rejected.

**2. The move clears A2's non-inferiority bar first,** through a paired silent
run: both transports score the same frozen PR snapshots, PR is the primary
unit, findings are nested evidence within a PR and never counted as independent
samples, and nothing surfaces to a customer or touches a published number until
the bar is met.

**3. The bar is declared before the run and is founder-only.** Declared
2026-08-28; see **The bar**. Two numbers are Andrew's ruling and two are derived
from them and from bounds already in the code, and the derivation of each is
recorded so that a later reader cannot mistake a derived constraint for a
measured one.

**4. `anthropic[vertex]` is declared explicitly in `api/pyproject.toml`.**
`google-auth` arrives transitively through `google-cloud-storage` today. That is
an accident of the dependency graph, and a transport that depends on an
accident is a transport that breaks when an unrelated dependency is dropped.
Done 2026-08-28, and it added **no new package**: `uv.lock` gains no entry, and
`requests` — which Doug flagged as possibly arriving with the extra — was
already there three times over before the change. The declaration makes an
existing dependency explicit; it does not enlarge the runtime image.

**4a. Declaring the dependency is not permission to use it.**
`test_the_risk_read_has_not_moved_to_vertex_before_its_bar_is_run` fails the
suite if either client function builds a Vertex client. Doug turned this
record's own reasoning back on it: ADR-0027's C3 got a guard because a condition
that binds only in prose does not bind, and item 2 below is the same kind of
claim. The guard is symmetric, and the test names how to remove it — run the
study, record the result against the bar table, delete it in the PR that lands
the client. A failed run does not delete it either.

**5. Credentials follow the existing GCP path.** No new secret class, no new
key material in the service. If that turns out to be false in the build, this
record is wrong and gets amended rather than quietly worked around.

**6. Rollback is a constant, not a redeploy.** The transport is selected by
configuration read at client construction, so reverting is a value change and
not a release. A forced transition whose rollback needs a deploy is a forced
transition with an outage attached.

## The bar

**NEVER RUN. Defective. See the banner, ADR-0029, and #268. Nothing below was
measured, and the two thresholds are derived from a baseline that does not
reproduce from the command this section names.**

**Declared 2026-08-28, before any Vertex call. Frozen.**

The baseline is Doug's own reader corpus as ADR-0026 defines the extraction —
`rate --repo doug --rule-prefix reader:`, which is what "Doug's own review
history" was always meant to name:

| Disposition | n | share |
|---|---|---|
| `real` | 68 | 44.4% |
| `disproved` | 49 | 32.0% |
| `adjacent` | 36 | 23.5% |

| Quantity | Value |
|---|---|
| **Corpus** | A 300-PR sample drawn from the frozen 653-PR replay corpus. The sample is drawn, committed, and hash-recorded **before the first call**, and both arms score the identical set. |
| **Non-inferiority margin, PR-level validated yield** | The Vertex arm's `real` share is **≥ 39.4%** — 5.0 percentage points below the 44.4% baseline. |
| **False-positive burden ceiling** | The Vertex arm's `disproved` share is **≤ 37.0%** — 5.0 percentage points above the 32.0% baseline. |
| **Latency** | p95 whole-read **≤ 240s**, and no single read exceeds it. |
| **Reliability** | The Vertex arm's hard-failure rate is at most **1.0 pp above** the Anthropic arm's on the same 300 PRs. |

### Where each number comes from

The two governing numbers are Andrew's, set 2026-08-28. The two derived ones are
not independent judgments and are recorded here so that nobody later mistakes
them for measurements.

- **The 5.0 pp margin is the ruling.** It was chosen against the alternatives:
  3 pp needs roughly 800 PRs per arm to separate a true drop from sampling
  noise, which the 653-PR corpus cannot supply, so that bar would be
  underpowered and its PASS would not mean what it says. 10 pp passes at about
  100 per arm but certifies a visible product regression — roughly 30 lost real
  findings per 300 PRs — as acceptable.
- **300 PRs is the ruling**, and it is what powers 5 pp. A2 states that shadow
  doubles the deep-read bill and that sampling is a decision to make **before**
  switching it on, which is why the size is here and not in a later note.
- **The false-positive ceiling is the margin, mirrored.** A transition that
  holds `real` steady by producing more `disproved` has not held anything
  steady. Using a different figure on this side would need its own derivation,
  and there is none.
- **240s is already in the code, not a new choice.** `DEFAULT_READ_TIMEOUT_S`
  is 120s per HTTP attempt and `MAX_READ_RETRIES` is 1, so the whole read is
  bounded by 240s plus backoff. That bound exists because `POST /v1/score/read`
  buys its read inside the request and Cloud Run's `--timeout 300` kills it
  otherwise, pinned by
  `test_read_timeout_budget_fits_inside_the_cloud_run_timeout`. A transport
  that cannot hold it produces platform 504s instead of the reader-unavailable
  fallback this module contracts for.
- **Reliability is stated as a difference, not a level,** because no baseline
  transport-failure rate has ever been recorded. Both arms run the same 300 PRs
  in the same window, so the comparison is available even though the level is
  not. Recording the level for the first time is a side effect of this run and
  is reported, not barred.

### Provenance of the two ruled numbers

Doug reviewed the commit that filled this table and raised the right objection
(`contradicts-ticket`, high): the banner above said the numbers were
founder-only and that the record could not be signed as it stands, and then the
same commit supplied them, with the only evidence of authorization being prose
added by that commit. Left there, a protected pre-registration and a fabricated
one are indistinguishable in the record.

So the mechanism is written down rather than asserted:

- The two ruled numbers were **chosen by Andrew on 2026-08-28** from enumerated
  alternatives, each with its arithmetic stated before the choice: margins of
  3 pp, 5 pp, 10 pp, and a Wilson-lower-bound variant; corpora of 300 PRs, the
  full 653, and the 153-row findings-log set. 5 pp and 300 were selected. The
  rejected options and why they lose are in **Where each number comes from**,
  which is what makes this a choice on the record rather than a preference.
- The other two are **derived, and labelled derived**, from those two plus
  bounds already in the code. No third quantity was invented.
- **The founder act that ratifies this record is the merge**, not the prose. An
  agent can write a number into a file; it cannot merge a PR into `main`. If
  the numbers here are not Andrew's, the correct response is to reject the PR,
  and this paragraph is the instruction to do so.

That is weaker than a signature on a separate artifact and it is worth naming as
weaker. What it is not is self-certifying: the authorization is an act by a
different party, recorded in git, on a record that states in advance what the
act means.

### What this table does not do

It does not license surfacing. Clearing it establishes review quality,
calibration, cost, latency, and reliability against the current transport. It
cannot establish that surfacing the Vertex arm changes a merge decision, a code
change, or reviewer effort, because only a surfaced review can do that. A2
reserves that claim for a later opt-in randomized surfaced-policy stage, and
this record does not reach it.

## Rejected

**Keeping `provider = "anthropic"` so the corpus does not partition.** This is
the tempting option and it is the one that destroys the evidence quietly. It
buys corpus continuity by asserting that the serving stack is not part of the
instrument, which is a claim about the world that nobody has tested, made by the
party who benefits from it being true. A2 already ruled the other way.

**Moving the mechanical tier in the same change.** It has its own record,
ADR-0027, its own conditions, and a different safety argument: the mechanical
passes are validated in code on every call and the risk read is validated by
nothing downstream. One PR moving both would make a single review decide two
questions that deserve different evidence.

**Bedrock.** `anthropic.AnthropicBedrock` is equally present in the installed
SDK, so the same two-function change reaches it. Not chosen and not rejected on
merit: the service already runs on Cloud Run with GCP credentials in the image,
so Vertex is the transport that adds no new cloud relationship. If that stops
being true, this record is the wrong one to consult.

**Shipping the move and measuring afterward.** ADR-0004's Rejected section
already refuses this shape: "the bars were frozen before the run, which is the
only reason the result is worth anything." ADR-0018 shipped against that rule
once, by direction, and was candid that the value ships governed by nothing.
Doing it twice would make the exception the practice.

**Running both transports live and splitting traffic.** That is a surfaced-policy
experiment. A2 reserves it for a later opt-in randomized stage, because only a
surfaced review can change the code, the merge decision, or reviewer effort — so
a live split measures something other than the transport.

## Consequences

- **The published series partitions at the cutover.** `example_pack_eval.py`
  partitions by `instrument_id`, so this is mechanical rather than a matter of
  discipline. Every surface that reports a rate names which era it covers, and
  the pre-registered publication series states the partition rather than
  spanning it.
- **The paired run doubles the read bill for its duration** on the line item
  that sets margin. Sampling or a corpus-only run is a decision to make before
  switching it on, not after the invoice.
- **This record is not a licence to move anything else.** It moves a transport
  for two named calls. A new prompt, schema, budget, tool, orchestration graph,
  or fallback policy is a different instrument under A2 and needs its own
  record.
- **`scripts/llm_probe.py` stays on the current transport.** It reports what it
  measured, which is the same reason ADR-0018 left its `EFFORT` alone.
- **If the bar fails, the record stands and the move does not happen.** A failed
  non-inferiority run is a result, not a reason to widen the margin. Widening a
  declared margin after seeing the data is the failure this whole file is
  arranged to prevent.
