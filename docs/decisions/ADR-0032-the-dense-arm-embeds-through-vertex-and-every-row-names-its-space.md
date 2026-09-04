---
title: The dense arm embeds through Vertex at 768 unit-length dimensions, and every row names its embedding space
status: proposed
date: 2026-09-02
---

> **DRAFT FOR FOUNDER SIGNATURE. Not accepted, not fed to the reader.**
>
> This record decides the embedder for the memory store's dense search arm.
> It is the first of the three Stage-0 follow-on papers the integration plan
> lists after ADR-0022/0023/0024 ("embedding ADR, free-tier keying,
> lema-prod0 decommission checklist"). Two numbers in it are the founder's
> to set under R11 and are marked as such: the monthly spend cap and the
> pre-registered margin in **The known-wrong check**. Every other number was
> read from a source named beside it on 2026-09-02.

## Context

### What ADR-0022 already fixed, and what it left open

ADR-0022 ruled that the store holds no model client: embedding and synthesis
are `doug-api` endpoints, `/internal/embed` and `/internal/synthesize`, called
from Go over the internal wire under the store's service identity. It ruled
that Stage 1 ships lexical search only, and that every search response
carries `degraded: true` until the hybrid path exists, "so the search contract
does not change when the ranking does." ADR-0024 ruled one datastore, and
ADR-0001 had already noted that "pgvector is available later without a second
datastore."

What none of them decided is which model produces the vector, how wide it
is, whether it is unit-length, who pays, who re-embeds, and how the store
keeps a vector produced under one model from being compared against a vector
produced under another. Those are this record's questions. The Stage-2 build
item that ships `/internal/embed` cannot start until they have an answer,
because the column width is a migration and the migration is a claimed
number (ADR-0024).

### How this repository already reaches a model

ADR-0029 moved the reader's transport to Vertex. ADR-0030 removed the
Anthropic API key from the service and left `doug-api-sa` authenticating by
workload identity on one transport and by application default credentials on
the other. The posture that survives both records is: **no static key in the
service, one cloud relationship, the region is a value that is probed before
a deploy, and quota is a founder grant that the preflight refuses to assume.**
An embedder that needs a new vendor account, a new key class, or a second
cloud relationship contradicts three signed records at once.

Anthropic does not serve an embedding model. That was checked against the
API reference this record was drafted with, which lists no embeddings
endpoint; Anthropic's own guidance points at third-party providers. So "the
embedder routes the way ADR-0028 routes" cannot mean a Claude model. It means
the Google embedding model that Vertex serves in the same project, under the
same credentials, in the same region the reader already probes.

### The facts this record stands on

Read from Google's Vertex documentation on 2026-09-02 (the text-embeddings
guide, the text-embeddings API reference, the model-versions page, and the
generative-AI pricing page). A later reader should re-check the retirement
and pricing rows; the dimension and normalization facts are properties of the
model and will not drift.

| Fact | Value |
|---|---|
| Models in the supported table | `gemini-embedding-001`, `text-embedding-005`, `text-multilingual-embedding-002` |
| `gemini-embedding-001` output | 3072 dimensions by default; `outputDimensionality` truncates to a smaller size ("output embeddings will be truncated to the size specified") |
| `gemini-embedding-001` input | 2048 tokens per text, silently truncated unless `autoTruncate` is false; **one input text per request** |
| Normalization | "The vectors are normalized, so you can use cosine similarity, dot product, or Euclidean distance to provide the same similarity rankings." Stated for the model's output; a truncated prefix of a unit vector is not itself unit-length, which is arithmetic, not a claim about the API |
| Retirement, `gemini-embedding-001` | "No sooner than May 20, 2028" |
| Retirement, `text-embedding-005` (lema's model) | April 1, 2027 |
| `gemini-embedding-2` | Listed on the model-versions page with a release date of April 22, 2026 and no retirement date; **absent** from the supported-models table in the embeddings guide as fetched |
| Price, "Gemini Embedding", global | Input: $0.00015 per 1,000 count online, $0.00012 batch. Output: no charge. The page's unit is "1,000 count"; the row does not say whether count is characters or tokens |
| Price, "Embeddings for Text (Excluding Gemini Embedding)" | Input: $0.000025 per 1,000 count online, $0.00002 batch |

pgvector, from its README on the same date: the `vector` type holds up to
16,000 dimensions but HNSW and IVFFlat index it only "up to 2,000
dimensions"; `halfvec` indexes up to 4,000; `<#>` is negative inner product
because Postgres index scans are ascending; and "if vectors are normalized to
length 1, use inner product for best performance."

What lema did, on disk: `apps/api/migrations/0005_atom_layer_storage.sql:11`
declares "Embeddings: VECTOR(768), Vertex text-embedding-005", the
`claim_embeddings` table is `VECTOR(768) NOT NULL` hash-partitioned by org,
and `config.go:234` defaults `VERTEX_EMBED_MODEL` to `text-embedding-005`.
The cosine retrieval guard that MS-7 ports as an ingest fixture was written
against 768-wide vectors. lema kept the lexical half beside the dense half as
a stored `tsvector` column (`claim_tsv ... GENERATED ALWAYS AS
(to_tsvector('english', claim_text)) STORED`), "never to_tsvector() in the
query path."

### The load

The corpus is small and will stay small for the period this record governs.
ADR-0024 measured 5.6 merged pull requests per day on this repository with
two founder-owned tenants. A record is a title plus a body the reader clips
at 4,000 characters (`intent.BODY_BUDGET`), so a full re-embed of ten
thousand records is on the order of forty million characters. At the fetched
list price that is a few dollars whether the unit is characters or tokens.
Embedding is not where this system's money goes; the deriver's model reads
are (ADR-0023). The cap below exists so that a runaway backfill loop is
bounded by a number and not by someone noticing an invoice, not because the
expected spend is material.

## Decision

Everything here is a contract for Stage-2 code that does not exist. Where
the text says the store *refuses* or `doug-api` *asserts*, that names a
deliverable, not a mechanism on disk today.

### 1. The embedder is `gemini-embedding-001` on Vertex, called only by `doug-api`

`/internal/embed` is a `doug-api` endpoint (Python, by the language law: the
thing that calls a model is the thing that is graded) that calls
`gemini-embedding-001` through Vertex in the same project, under
`doug-api-sa`'s application default credentials, in the region
`VERTEX_REGION` names. No key, no new vendor, no new cloud relationship,
which is ADR-0029's and ADR-0030's posture carried to a second model.

The Go store never constructs a model client (ADR-0022, Rejected: "A model
client inside the Go store"). It sends text and receives vectors over the
internal wire, and it treats the vector as opaque bytes plus a space name.

ADR-0029 item 5's deploy preflight extends to this model: a Vertex deploy
probes `gemini-embedding-001` in `VERTEX_REGION` with an empty body and
allowlists only 200 and 400, for the same reason it probes the reader's
model. Model access and quota are separate grants and both are founder
actions; a region that serves the reader is not evidence that it serves the
embedder.

The model id is a constant in `doug-api`, `EMBED_MODEL`, and reaches the wire
verbatim with no mapping layer, for the reason ADR-0029 item 6 gives. It is
not part of ADR-0012's freeze: the embedder is not the reader's instrument
and its output never reaches the model that produces findings.

### 2. The dimension is 768, by `outputDimensionality`

Not the model's 3072 default. Three reasons, in order of weight:

- **The index.** pgvector's HNSW indexes `vector` up to 2,000 dimensions.
  3072 forces either `halfvec` (a second type on a column that the open
  conformance artifact must describe) or no index, and an unindexed
  nearest-neighbour scan on the tenant view is the "Postgres is measurably
  the bottleneck" case ADR-0024 says to measure, not to ship.
- **The fixtures.** lema's retrieval guards, which MS-7 ports as ingest
  enforcement, were written at 768. Porting them at 3072 changes what they
  measure while claiming to be the same test.
- **Storage and the wire.** A quarter of the bytes on every row, every
  backup, and every `/internal/embed` response, at a quality cost Google
  describes as "sacrificing little" and that **The known-wrong check** below
  measures rather than assumes.

`EMBED_DIM = 768` is a `doug-api` constant, the column is `vector(768)`, and
a vector of any other width is refused at write.

### 3. Vectors are unit-length, normalized by `doug-api`, asserted by the store

`/internal/embed` L2-normalizes every vector after truncation and before it
returns. The store asserts `abs(norm(v) - 1) < 1e-3` at write and refuses
otherwise. The column's index is `hnsw (embedding vector_ip_ops)` and the
query operator is `<#>`.

Why unit-length rather than storing what the model returns: the model's
normalization claim is for its output, and a 768-wide prefix of a normalized
3072-wide vector is not a unit vector. Normalizing on our side makes the
property true by construction instead of by trust, makes cosine and inner
product the same number so the cheaper operator is also the correct one, and
gives the store one arithmetic fact to check at write instead of a promise to
remember at read. A write-side assertion also catches the failure mode where
someone changes the model or the dimension in `doug-api` without registering
a new space (item 5): the vectors would still arrive normalized, so the
assertion is not the guard against that, and item 5 says what is.

### 4. What gets embedded, and how much of it

One vector per record, over the title, a newline, and the head of the body,
clipped by `doug-api` to a fixed character budget, `EMBED_CHARS`, chosen so
that English text under it stays inside 2048 tokens with margin. The call
sets `autoTruncate: false`, so if the budget is ever wrong the request fails
loudly instead of the model silently embedding a prefix we did not choose.
The row records `embedded_chars`, the length of what was actually sent.

Evidence spans (capped at 240 runes, ADR-0022) are not embedded separately
in v1. If a later record wants span-level retrieval, that is a second
embedding kind and a registry row, not a change to this one.

Because `gemini-embedding-001` accepts one input text per request,
`/internal/embed` accepts a batch on the internal wire and fans out serially
behind it. At the measured merge rate that is not a throughput question, and
if it becomes one the answer is Vertex batch requests (priced lower), not a
different model.

### 5. Every row records its `embedding_space`, and spaces are registry rows

`embedding_space` is a mandatory text column on every embedding row, and a
mandatory field on every `/internal/embed` request and response and on every
dense search request. Its value is a fixed-format string:

```
vertex:gemini-embedding-001:768:l2
```

provider, model id as it reaches the wire, dimension, normalization. The
store holds a registry table of admitted spaces, one row per string, with
`state` in `{active, backfilling, retired}` and exactly one `active` row at
a time. The task types the space pairs are recorded on that row
(`RETRIEVAL_DOCUMENT` for records, `RETRIEVAL_QUERY` for queries); they are
two views of one space, which is why the task type is not part of the string.

The rules the string enforces:

- **A search compares only within one space.** The query is embedded under
  the active space, and the nearest-neighbour scan is filtered to rows whose
  `embedding_space` equals the query's. A query that arrives naming a
  non-active space, or a row whose space is `retired`, is not compared. The
  search falls back to lexical and the response carries `degraded: true`
  with a reason. There is no code path that compares two spaces, and the
  open conformance artifact carries a fixture that submits a mixed pair and
  must see the refusal.
- **A space string is derived, never typed.** `doug-api` computes it from
  `EMBED_MODEL`, `EMBED_DIM`, and its normalization constant on every call.
  Changing any of the three changes the string, and a string the registry
  has not admitted is refused at write. That is the guard item 3 said it is
  not: a model or dimension change that nobody registered cannot land a row.
- **Spaces are additive.** Registering one is a registry row, not a contract
  change, on the same footing as an event type or a provenance variant in
  ADR-0024. Changing the *format* of the string or the *fields* of the
  embedding row is a contract change and reopens Stage 0.

### 6. Re-embedding: the store's drain owns it, three triggers, founder-approved spend

**Owner.** The store's own drain (Go) runs a re-embed as batch-stamped
`lema.jobs` work under a `batch_id` (ADR-0024), calling `/internal/embed`
per record, writing rows under the new space, and never touching rows under
the old one. `doug-api` owns the constants that define the space; the store
owns the work of moving the corpus into it. Neither owns the other's half.

**Triggers.** A re-embed happens when, and only when, the active space
string changes, which means one of:

1. **Model change.** Forced when Google retires `gemini-embedding-001` (no
   sooner than 2028-05-20 per the model-versions page as fetched) and
   voluntary otherwise. A voluntary swap must clear **The known-wrong
   check** against the *current* space as the baseline, not against
   lexical; a forced one clears it against lexical, because the current
   space stops existing. That is A2's superiority-versus-non-inferiority
   distinction from ADR-0028, applied to a model whose output never reaches
   the reader.
2. **Dimension change.** Any change to `EMBED_DIM`. Same bars.
3. **Normalization change.** Any change to the normalization rule, which
   in practice means "we stopped normalizing," and which this record
   expects never to happen.

**Sequence.** Register the new space as `backfilling`; run the batch; run
the known-wrong check over the new rows; on pass, flip the new space to
`active` and the old to `retired` in one transaction; retired rows are
deleted by a later registered `embedding.retired` event that carries the
space string and the batch id, so the append-only law has a receipt for the
deletion. Until the flip, search runs against the old space and nothing a
tenant sees changes. A backfill is a replay and produces zero new rows on a
second run (ADR-0024, Consequences).

**Spend.** The re-embed is a batch and is subject to the cap in item 7. A
re-embed that would exceed the cap does not start; the founder raises the
cap or the batch waits for the next period.

### 7. The spend cap is a number the founder sets, enforced in `doug-api`

`/internal/embed` keeps a per-calendar-month counter of input units sent to
Vertex and refuses with a named error, `embed_cap_exceeded`, once the
projected cost of the next call would cross `EMBED_MONTHLY_CAP_USD`. The
store treats that error as a park (ADR-0024's `parked` status), not a
failure: the job is re-claimed at the next drain start and succeeds when the
month rolls or the cap moves. Lexical search is unaffected, because it never
calls the endpoint.

The cap's value is the founder's under R11 (spend approval). **Proposed:
$10.00 per calendar month**, which at the fetched list price covers a full
re-embed of a corpus an order of magnitude larger than today's several times
over. The founder may set a different number at signature; what this record
fixes is that there is a number, that it lives in one constant beside the
model id, and that exceeding it parks rather than fails.

A second receipt: a Cloud Billing budget alert on the project for the Vertex
SKU family, at the same figure, so a cap that is silently disabled in code
is still loud in the console. Creating a budget is a founder click.

### 8. What stays lexical-only and `degraded: true`

Until the dense arm has passed **The known-wrong check** for the active
space, every surface that could use a vector uses text instead, and says so:

- **Search on the tenant view.** Postgres full-text search over a stored
  `tsvector` column, lema's `claim_tsv` pattern ported, with the same rule
  that the query path never calls `to_tsvector()`. Every response carries
  `degraded: true`.
- **The correlator's session-to-commitment matching** (ADR-0022, the only
  path that promotes an `advisory` session record to `settled`). Lexical
  matching until dense passes. A match that promotes a record is the one
  place a bad embedding would launder intention into fact, so this surface
  is last to go dense, not first.
- **Candidate retrieval for the check run's contradiction section**
  (ADR-0022, "Who may read"). Lexical, and the section stays advisory under
  Gate B regardless of this record.
- **The public `check_approach` corpus.** Lexical. Its dense arm, if it ever
  has one, is a separate space over a separate corpus and is not decided
  here.

`degraded` flips to `false` per space, only by the registry flip in item 6,
never by a deploy and never by a constant. A reader that sees `degraded:
false` may rely on the ranking having passed the check; a reader that sees
`degraded: true` may not, and the field exists so that the distinction is
on the wire rather than in someone's memory.

### The known-wrong check

Pre-registered here, run before the first `active` flip and before every
later one, results recorded in the pull request that performs the flip. The
check has two halves: the bar, and the control that shows the bar can fail.

**Corpus.** The retrieval goldset is the union of (a) lema's ported labeled
corpora, the same fixtures MS-7 runs as ingest enforcement, including the
ADR-0095 set of 22 non-goal false positives and 19 retained rulings, and
(b) this directory's own records, where every `amends`, `amended_by`,
`supersedes`, and `superseded_by` link is a labeled relevant pair and every
other pair is labeled irrelevant. Both are on disk today; neither is
tenant data. The goldset is hashed and the hash is recorded before the run.

**Arms.** Three rankings over the identical query set: lexical-only,
dense-only, and hybrid (reciprocal rank fusion of the two, the same fusion
the shipped ranking will use). Metric: recall at 10, per query, then
averaged, with the query as the unit.

**Bar.** Hybrid must exceed lexical-only by a margin the founder
pre-registers at signature (R11: it is a pre-registered bar). **Proposed:
5.0 percentage points absolute**, the same figure ADR-0028 chose for the
reader's non-inferiority margin and for the same reason: small enough to
matter, large enough that the goldset can resolve it. If dense-only is
*below* lexical-only, the dense arm is worse than what we have, the space
does not flip, and the result is recorded as a result and not as a reason
to change the goldset.

**The control, which is the point.** The same three arms run again with the
stored vectors **shuffled**: each record is assigned another record's
vector, chosen by a seeded permutation. Under that input the dense and
hybrid arms must score at or below lexical-only, within noise. If shuffled
dense scores near real dense, the metric is not measuring the vectors, and
the real number is an artifact of the goldset construction (most likely,
the lexical arm leaking through the fusion). A bar that passes on shuffled
input is not evidence, and a check that cannot fail on a known-wrong input
is not a check. This is the cheapest way the first number could be wrong,
named in advance.

**A second control, cross-space.** The conformance fixture from item 5: a
query vector under a string that is not the active space must produce a
refusal and `degraded: true`, never a ranking. It is a correctness fixture,
not a quality one, and it runs in CI on every build rather than at the
flip.

## Rejected

**An Anthropic-hosted embedder.** There is none. The API reference this
record was drafted against has no embeddings endpoint, and Anthropic points
at third parties. Recorded so nobody re-derives it.

**Voyage, OpenAI, or any first-party embedding vendor.** A new vendor
account, a new static key class, and a second billing relationship, three
days after ADR-0030 removed the last static key from the service. The
quality argument for a specialist embedder may be real; the known-wrong
check is where it would be measured, and it can be measured later under a
new space string without reopening this record's contract.

**`text-embedding-005`, lema's model.** The closest thing to a port. Google
retires it on 2027-04-01, which would force the first re-embed inside the
store's first year, and Google's own description says `gemini-embedding-001`
"unifies the previously specialized models like text-embedding-005" at
better quality. Choosing the retiring model to avoid a re-embed buys a
re-embed with a deadline.

**`gemini-embedding-2`.** Newer, released 2026-04-22 per the model-versions
page, but absent from the supported-models table in the embeddings guide as
fetched on 2026-09-02, with no dimension, token limit, or normalization
contract this record could cite. Item 5 makes moving to it a registry row
and a batch, not a contract change, so refusing it today costs nothing but
a later backfill. A record that names a model it cannot describe is a note,
not a decision.

**3072 dimensions, the model's default.** Over pgvector's 2,000-dimension
HNSW limit for `vector`; needs `halfvec` or no index; four times the bytes;
and the ported fixtures were written at 768. The quality difference is what
the known-wrong check measures. If it turns out to be material, that is a
dimension-change re-embed under item 6, measured rather than assumed.

**Storing raw model output and using the cosine operator.** Works, and is
what most tutorials do. It cannot be asserted at write, so a non-normalized
vector from a truncated call would be silently wrong by a scale factor that
depends on the input. The inner-product index over unit vectors is also the
path pgvector's own README names as fastest.

**A dedicated vector database.** ADR-0024: no second datastore until a
Postgres table is measurably the bottleneck. At 5.6 merges a day nothing is
measured, and pgvector on the existing Cloud SQL instance is the ADR-0001
plan.

**Embedding inside the Go store.** ADR-0022 rejected it by name: the
language law exists "so that the thing that calls a model is the thing that
is graded," and a store that calls a model turns every embedding-model swap
into a store release.

**Embedding at merge time, in the webhook.** ADR-0023's law: a merge must
never buy a model read. The drain buys it, batch-stamped, bounded by the
tenant's own merge rate and now by the cap.

**No spend cap, because the expected spend is small.** The expected spend
is small. A backfill loop with a bug is not bounded by expectations, and
spend approval is R11. A cap that is never hit costs nothing.

**One `embedding_space` for the whole store, as a config value.** It is
the same fact as the per-row column until the day a backfill is half done,
at which point it is a lie for every row on the wrong side of the batch.
The per-row column is what makes "never compare mixed spaces" a query
predicate instead of a deployment promise.

## Consequences

- **Stage 2 gains a migration and a registry table.** `lema.record_embeddings
  (record_id, embedding_space, embedding vector(768), embedded_chars,
  batch_id, recorded_at)` under RLS like every `lema.*` table (ADR-0022),
  and `lema.embedding_spaces`. The migration number is claimed, not raced
  (R5). It is a Stage-2 item and does not move the Stage-1 exit.
- **The `pgvector` extension is enabled on the shared Cloud SQL instance.**
  That is an instance-level flag on `doug-ledger`, visible to the `doug`
  schema as well as `lema`. It is additive and Python never has to use it,
  but it is an instance change on the production ledger and is recorded here
  so it is not a surprise in a migration review.
- **`doug-api` gains three constants and one counter.** `EMBED_MODEL`,
  `EMBED_DIM`, `EMBED_CHARS`, and `EMBED_MONTHLY_CAP_USD`, with the space
  string derived from the first two. None is in ADR-0012's freeze. A test
  pins that the derived string equals the registry's active row in the
  deployed environment, so a constant edit that nobody registered fails
  before it deploys.
- **Two founder actions before the first vector is written**, both R11:
  grant model access and quota for `gemini-embedding-001` in
  `VERTEX_REGION` (the reader's own grant, #274, is a separate line), and
  set `EMBED_MONTHLY_CAP_USD` with the matching billing budget. The
  preflight in item 1 refuses to deploy a Vertex build until the first is
  true.
- **A third founder action before the first flip:** the pre-registered
  margin in the known-wrong check, set at signature. Until it is set, the
  check has no bar and `degraded` cannot flip.
- **The open conformance artifact gains three things:** the space-string
  format, the mixed-space refusal fixture, and the write-side norm
  assertion. All three are public, which is the intended half of the
  2026-08-25 ruling.
- **The reader is untouched.** No vector reaches the model that produces
  findings; `instrument_id` does not move; `tool_versions` does not move.
  This record changes what the store can rank, not what the reader is
  shown, and Gate B still governs whether anything ranked reaches a check
  run.
- **A forced re-embed is on the calendar.** `gemini-embedding-001` retires
  no sooner than 2028-05-20. That is a known future batch with a known
  trigger and a known bar, which is the difference between a planned
  migration and an incident.
- **The pricing rows in Context will drift.** They are quoted so the cap's
  derivation can be checked, not so they can be relied on. The cap is a
  dollar figure precisely so that a price change moves the number of
  records it covers and not the promise.
- **This record is `proposed` and reaches no reader.** On acceptance it
  becomes the second record after ADR-0022 to describe `/internal/embed`,
  and ADR-0022's one sentence about that endpoint stands unchanged; this
  record fills it in and does not amend it.
