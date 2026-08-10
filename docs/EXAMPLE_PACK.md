# Example Pack v0

Example Pack v0 is a local, opt-in evidence path for Doug's existing reader. It
records what an admitted worker attempt read, the exact request dictionary it
gave the Anthropic SDK, the selected text output, the parsed output, coverage,
usage, terminal state, and the complete instrument identity. It does not change
the live verdict or authorize a new model, challenger, or promotion path.

No production capture, database table, object bucket, deployment setting, or
retention system is enabled by this work.

## Local dogfood setup

Choose an absolute, operator-owned directory on an access-controlled local
volume. The directory will contain source diffs and model request/output
evidence, so treat it as private source code rather than ordinary application
logs.

```bash
export DOUG_EXAMPLE_PACK_CAPTURE=1
export DOUG_EXAMPLE_PACK_DIR=/absolute/private/path
cd api
uv run python -m doug.example_pack validate "$DOUG_EXAMPLE_PACK_DIR"
```

Both settings are required. Capture is disabled when the enable flag is not
exactly `1` or when either setting is absent. A configured path must be
absolute; there is no default directory.

Only risk or intent reader calls made inside an admitted worker scope are
captured. Credential probes, developer CLI reads, and other unscoped calls are
not given invented tenant, base, or head identity. If capture is enabled for an
unscoped call, Doug prints `capture unavailable: no admitted worker scope` and
preserves the call's existing result.

## What is written

Objects are immutable and content-addressed:

```text
blobs/sha256/<sha256>
packs/sha256/<pack_hash>.json
adjudications/sha256/<adjudication_id>.json
```

Each write is completed to a temporary file, flushed and `fsync`ed, then
hard-linked into an absent content address. Rewriting identical bytes is an
idempotent success. Different bytes at an existing address are an integrity
failure.

`ExamplePackV0` includes:

- job ID, claim generation, attempt kind, tenant, stable repository ID, PR,
  admitted base SHA, and admitted head SHA;
- exact request, source evidence, and selected raw-output content references;
- parsed output before live settlement can remove disproved findings;
- complete, partial, or failed terminal state, coverage, usage, and latency;
- provider, pinned model, output limit, effort, inference defaults, separate
  prompt and schema hashes, diff budget, read order, policy versions, verifier
  versions, tool versions, and explicitly injected application/runtime
  revisions;
- deterministic finding identities and the pack's own content hash.

Application revision comes only from `DOUG_APPLICATION_REVISION`. Runtime
revision comes from `DOUG_RUNTIME_REVISION`, falling back to Cloud Run's
`K_REVISION`. Missing values remain `null`; a developer checkout is never
hashed and mislabeled as a served production revision.

## Exactness boundary

The request blob is canonical JSON made from the same Python dictionary passed
as `client.messages.create(**request)`. It proves Doug's SDK call arguments. It
does not claim to be the provider's HTTP wire encoding or to contain transport
headers.

The evidence blob is the reader's input diff encoded as UTF-8. The raw-output
blob is the exact first text block selected by the existing reader before
Pydantic parsing. Parsed output is stored separately. Request/response headers,
SDK clients, API keys, installation tokens, cookies, and other client state are
not captured. Credential-shaped keys in Doug-controlled structured data are
rejected. Arbitrary source text is not substring-scanned, because a diff may
legitimately contain words such as `authorization` and must remain byte-exact.

A spend-cap failure occurs before an SDK request exists. Its failed pack has
`model_call_made=false` and a null request reference. Transport, stop-reason,
and parse failures retain the request and any selected raw output that exists.
Successful incomplete reads are `partial`; successful zero-finding reads are
`captured`, not omitted.

## Failure isolation

Capture is best-effort relative to the advisory review. Construction or storage
failure prints one bounded line containing the run ID and exception class. It
cannot replace the reader's return value or error, select a different fallback,
change score or band, fail an otherwise successful worker job, or alter check
run publication.

Existing-verdict replay performs no reader call and therefore writes no pack.
Retries use a distinct run ID such as
`review-job:<job-id>:claim:<generation>:risk`.

## Validation

Run validation after a dogfood session:

```bash
cd api
uv run python -m doug.example_pack validate /absolute/private/path
```

Success prints deterministic object counts:

```text
blobs=<n> packs=<n> adjudications=<n>
```

Validation recomputes blob filename hashes, pack and adjudication self-hashes,
all referenced blob hashes and sizes, and adjudication pack/run/finding links.
It stops nonzero on the first malformed, missing, non-canonical, or mismatched
object. The command does not repair, delete, upload, or infer data.

## Adjudication and evaluation

Judgment is an append-only `ExampleAdjudicationV0` overlay. A correction names
the exact prior `adjudication_id` in `supersedes`; timestamps never pick a
winner. Resolution rejects a missing target, cross-finding edge, cycle, or two
live heads.

Offline scorecards accept one risk pack for each eligible PR identity. Every
captured, zero-finding, partial, and failed pack remains in both PR
denominators. Within the declared evaluation-only finding cap:

```text
validated actionable yield = verified_actionable findings / eligible PR packs
unsupported-finding burden = disproved + unknown + unadjudicated findings
                             / eligible PR packs
```

`verified_accepted_nonactionable` is reported separately and contributes to
neither numerator. These metrics are yield and burden, not precision or recall.
The deterministic null and spam controls use the same pack population and cap.

The checked-in PR #78 fixture is a reconstructed verifier regression with
`exact_replay: false`. It does not invent historical request or response bytes.
Its AST caller inventory and exact migration-membership probe deterministically
produce two disproved findings; two explicit accepted-contract references
produce two verified accepted-nonactionable findings.

## Retention and deletion

The operator owns the local directory and its retention decision. Doug has no
background cleanup, upload, repair, or legal-hold behavior. Remove a local pack
directory only under the operator's own retention and incident-response policy;
validation never deletes it.

Production storage remains blocked until an explicit design and approval cover
all of the following:

- tenant authorization and repository isolation;
- encryption and key management;
- storage region;
- retention periods;
- deletion and legal-hold behavior;
- access audit;
- source-code data classification;
- trusted application/runtime revision injection; and
- incident response.

The next permitted step is a separately authorized local dogfood run over
20–30 consecutive future worker attempts, followed by validation of every
object. That run is evidence collection, not model validation or promotion.
