# Example Pack v0 Design

**Date:** 2026-08-10  
**Status:** Approved for implementation by the task contract  
**Base:** `origin/main` at `4db0cce47424753288c5e102f3635f0278b064d0`  
**Scope:** Capture-only substrate, deterministic evaluation, and the reconstructed PR #78 verifier regression

## Goal

Build the smallest safe substrate that preserves future Doug reader attempts exactly enough to evaluate a later challenger without changing the live reviewer. Example Pack v0 records what Doug controlled and observed at one attempt: admitted identity, canonical SDK request envelope, evidence, output or failure, coverage, cost/latency receipts, and the complete instrument manifest.

Capture and judgment are separate. A pack is immutable evidence about an attempt. An adjudication is an append-only human or deterministic-verifier overlay that may supersede another adjudication but never rewrites the pack.

## Success criteria

The implementation is complete when:

- capture is off unless an operator explicitly enables a file-backed dogfood directory;
- every capture-eligible worker reader attempt records success, zero findings, partial input, transport/parse failure, pre-call fallback state, usage, and latency without changing the live review result;
- the exact canonical request envelope passed to `client.messages.create` is content-addressed immediately before that call;
- every pack and adjudication has deterministic canonical bytes, identities, and collision-safe storage;
- two scorecards include every eligible PR-run, including zero-finding, partial, and failed runs;
- null and cap-filling spam controls fail their required gates;
- the reconstructed PR #78 fixture produces exactly two `disproved` and two `verified_accepted_nonactionable` dispositions through deterministic code;
- `docs/findings-log.jsonl`, its schema, and its rates remain byte-for-byte and behaviorally unchanged;
- the existing worker result, score, band, check-run text, publication rules, and canonical verdict uniqueness remain unchanged.

## Hard boundaries

This PR does not:

- change `SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT`, `MAX_TOKENS`, `DIFF_BUDGET`, read ordering, coverage policy, reader threshold, score, band, findings, check-run output, or publication calculations;
- treat `docs/findings-log.jsonl` as an Example Pack corpus or map its `real` rows to desired model output;
- claim PR #78 is an exact replay case; its original request and response were not persisted;
- add production database tables, a GCS bucket, production retention, source-code retention, deployment configuration, a challenger, LangGraph, Vertex evaluation or optimization, batch inference, fine-tuning, or Coldworks integration;
- write challenger rows into the canonical production-verdict identity domain;
- deploy or mutate production infrastructure.

## Considered approaches

### Selected: reader-bound capture with worker-scoped identity

The worker installs an immutable `CaptureScopeV0` in a Python `ContextVar` while it runs the risk and intent reads. The reader constructs one request-envelope dictionary, canonicalizes that exact dictionary, and passes the same dictionary as SDK keyword arguments. It records the response or failure through a best-effort capture sink.

This is the smallest seam that can prove the request bytes without reconstructing them later. A context variable avoids widening `score_one`, `read_intent`, and their existing test doubles with identity arguments unrelated to scoring. Context is task-local rather than a mutable process global, so concurrent worker threads cannot exchange tenant or PR identity.

### Rejected: reconstruct packs from verdict, read, and findings tables

The ledger does not retain the exact request envelope, raw output bytes, transport/parsing failures, zero-output attempts that never committed a verdict, or the whole instrument identity. Reconstruction would create plausible records, not exact ones.

### Rejected: add a production pack table or blob bucket now

The retention, deletion, tenant-authorization, and production-runtime-revision contracts are not approved. A database or GCS write in this PR would enable a new production source-retention path before those decisions exist. The v0 file store is for tests and explicitly enabled local dogfood only.

## Capture eligibility and attempt identity

The v0 capture lane is the App worker because it is the current review path that has all required admitted facts. `worker.process_job` has:

- `installation_id` as tenant scope;
- `github_repo_id` and `repo_full_name` as stable and display repository scope;
- PR number;
- event-time `base_sha` and `head_sha` from `review_jobs`;
- stable job ID and `claim_generation`.

The worker installs this context before calling the existing scoring and intent functions. Within an enabled worker capture scope, every risk and intent reader invocation is eligible, including a call stopped before the SDK by the spend cap. Calls outside a worker scope, such as the credential probe and developer CLI, are not silently captured as if they had an admitted base SHA. If capture configuration is enabled there, Doug emits a visible `capture unavailable: no admitted worker scope` diagnostic and preserves the caller's existing result.

The stable run ID is:

```text
review-job:<job-id>:claim:<claim-generation>:<risk|intent>
```

Retries therefore produce separate attempt records. A replay that returns an already durable verdict before any reader call produces no pack because no reader attempt occurred.

## Canonical bytes and hashes

Canonical JSON uses UTF-8, sorted object keys, no insignificant whitespace, Unicode preserved, and non-finite numbers rejected:

```python
json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
```

The exact request envelope is the complete dictionary Doug passes to the Anthropic SDK:

```text
model
max_tokens
output_config.effort
output_config.format.type
output_config.format.schema
system
messages
```

Doug canonicalizes that dictionary immediately before `client.messages.create(**request)`. These are the exact canonical bytes of the request envelope Doug controls. They are not claimed to be Anthropic's serialized HTTP wire bytes and contain no client object, headers, credentials, retry state, or SDK internals.

Content references carry `sha256`, byte length, and media type. The request envelope, exact evidence diff bytes, and raw model text bytes are stored as content-addressed blobs. The pack contains their references, so changing any request, evidence, or raw-output byte changes the corresponding reference and therefore `pack_hash`.

`instrument_id` is SHA-256 over the canonical whole-instrument manifest. `pack_hash` is SHA-256 over the canonical pack payload with the `pack_hash` field omitted. `adjudication_id` is SHA-256 over the canonical adjudication payload with the `adjudication_id` field omitted.

Finding identity is independent of mutable judgment. Each `finding_id` is SHA-256 over canonical JSON containing the raw-output blob hash, attempt kind, zero-based output ordinal, and the exact parsed finding. Two byte-identical duplicate findings at different output positions remain separately identifiable. Pack validation requires contiguous ordinals, exact equality with the finding objects in `parsed_output`, and a recomputed ID for every finding; a caller cannot make a forged finding authoritative by merely recomputing `pack_hash`.

## Whole-instrument manifest

`WholeInstrumentManifestV0` covers at least:

```yaml
schema_version: whole-instrument-v0
provider: anthropic
pinned_model_id: claude-opus-5
inference_parameters:
  max_output_tokens: 6000
  effort: medium
system_prompt_sha256: <hash of exact UTF-8 bytes>
output_schema_sha256: <hash of canonical schema bytes>
input_policy:
  diff_budget: 100000
  read_order: tiered
  policy_version: reader-input-v0
  coverage_policy_version: reader-coverage-v0
verifier_versions: <sorted name/version mapping>
tool_versions: <sorted name/version mapping, including Anthropic SDK>
failure_policy_version: reader-fallback-v0
publication_policy_version: neutral-check-v0
application_revision: <explicit environment value or null>
runtime_revision: <explicit environment value or null>
attempt_kind: risk | intent
```

The risk and intent attempts have different system-prompt and output-schema hashes and therefore different instrument IDs. Application and runtime revision values come only from explicit deployment/runtime environment variables. If unavailable, they are `null`; Doug never hashes or labels a developer checkout as a production revision. Changing any model/inference parameter, prompt/schema byte, input/coverage policy version, verifier/tool version, application revision, runtime revision, failure policy, or publication policy changes `instrument_id`.

## `ExamplePackV0`

The immutable pack contains:

```yaml
schema_version: example-pack-v0
pack_hash: <content hash of this payload without pack_hash>
run_id: <stable attempt id>
attempt_kind: risk | intent
captured_at: <UTC timestamp>
scope:
  installation_id: <tenant>
  github_repository_id: <stable repository id>
  repository_full_name: <display only>
  pull_number: <number>
  admitted_base_sha: <event-time base>
  admitted_head_sha: <event-time head>
request: <content reference or null only when no SDK request was made>
evidence: <content reference to exact diff bytes>
model_call_made: <boolean>
raw_output: <content reference or null>
parsed_output: <typed JSON or null>
coverage:
  diff_chars: <integer>
  sent_chars: <integer>
  files_sent: <integer>
  files_unseen: <ordered paths>
  file_cut: <path or null>
  changed_files: <integer or null>
  files_dropped: <ordered paths>
usage:
  input_tokens: <integer or null>
  output_tokens: <integer or null>
latency_ms: <non-negative integer>
capture_status: captured | partial | failed
failure:
  phase: preflight | transport | stop_reason | parse | null
  error_type: <bounded class name or null>
  detail: <bounded diagnostic or null>
fallback_state: none | spend_capped | deterministic_expected | intent_unavailable
instrument_manifest: <whole manifest>
instrument_id: <manifest hash>
findings: <ordered finding identities and exact parsed finding values>
```

Rules:

- A successful response with zero findings is `captured` and carries an empty findings list.
- A successful response over incomplete coverage is `partial`.
- Transport, refusal/stop-reason, parse, and spend-cap failures are `failed`; coverage and any available request/raw output remain present.
- `request` is null only for a preflight failure that prevented creation of an SDK request. Whenever `model_call_made` is true, request and evidence references are mandatory.
- Failure diagnostics are bounded and contain no response/request headers.
- Parsed output is the typed model output before settlement mutates the list used for the live verdict. Example Pack records what the model returned, not a later settlement view.

## `ExampleAdjudicationV0`

The overlay contains:

```yaml
schema_version: example-adjudication-v0
adjudication_id: <content hash>
pack_hash: <referenced pack>
run_id: <referenced run>
finding_id: <referenced finding>
disposition: disproved | verified_actionable | verified_accepted_nonactionable | unknown
evidence: <ordered typed receipts>
verifier_receipts: <ordered verifier/version/result receipts>
adjudicator: <human or deterministic verifier identity>
adjudicated_at: <UTC timestamp>
supersedes: <prior adjudication_id or null>
```

The storage layer only appends adjudications. A correction creates a new record with `supersedes` naming the exact prior record. Scorecard resolution keys the target by `(pack_hash, run_id, finding_id)`, so identical outputs on independent PRs remain independent. It rejects missing supersession targets, cross-finding supersession, cycles, and two live unsuperseded records for one scoped finding. Timestamp order never silently chooses a winner.

## Storage and secret boundary

`ExamplePackStore` is a protocol with content, pack, and adjudication writes plus validation reads. `FileExamplePackStore` implements it below an operator-selected root:

```text
blobs/sha256/<sha256>
packs/sha256/<pack_hash>.json
adjudications/sha256/<adjudication_id>.json
```

Every write:

1. computes the address from the exact bytes;
2. writes a temporary file in the destination directory;
3. flushes and `fsync`s it;
4. atomically hard-links the complete temporary file into the absent content address;
5. treats identical existing bytes as an idempotent success;
6. raises a collision/integrity error when existing bytes differ from the bytes addressed by that name.

The store validator recomputes every filename hash, pack/adjudication self-hash, and referenced blob hash. A malformed, missing, or mismatched object fails loudly.

Only allowlisted typed fields enter a pack. Recursive validation rejects credential-shaped field names including authorization, cookie, API key, access token, installation token, private key, client, and SDK client. It intentionally does not scan arbitrary source text for words such as `authorization`: exact diff bytes are opt-in source evidence and substring scanning would both corrupt exactness and produce false security claims. The capture path never serializes an SDK client or request/response headers.

Production storage remains blocked on an explicit decision covering tenant authorization, encryption, region, retention period, deletion and legal-hold behavior, access audit, source-code classification, runtime revision injection, and incident response. This is a prerequisite to production capture, not hidden deferred work.

## Opt-in configuration and failure isolation

Capture requires both:

```text
DOUG_EXAMPLE_PACK_CAPTURE=1
DOUG_EXAMPLE_PACK_DIR=/absolute/operator-owned/path
```

No default directory exists. The path must be absolute. With either value absent, the capture sink is disabled and the reader performs no pack I/O.

Pack construction or storage is best-effort relative to the advisory review. A capture failure writes one bounded stderr diagnostic naming the run ID and exception class. It cannot:

- change the returned reader output;
- replace an existing `ReaderError` with a capture exception;
- change fallback selection;
- fail `worker.process_job` after an otherwise successful review;
- change the verdict row, check run, score, band, or job terminal state.

The operator validates a dogfood directory with:

```bash
cd api
uv run python -m doug.example_pack validate /absolute/path
```

## Scorecards and controls

The evaluator accepts one pack per eligible PR and the separate adjudication overlay. Duplicate pack entries for the same `(instrument_id, installation_id, github_repository_id, pull_number, admitted_base_sha, admitted_head_sha)` are rejected rather than double-counted.

Both scorecards use the exact same eligible pack list and declared finding cap:

```text
validated actionable yield
  = verified_actionable findings inside the cap / all eligible PR packs

unsupported-finding burden
  = disproved, unknown, or unadjudicated findings inside the cap
    / all eligible PR packs
```

`verified_accepted_nonactionable` is supported evidence but contributes no actionable yield. It is reported separately so accepted contracts cannot be mistaken for desired findings. Failed and partial packs contribute zero findings when none are parseable but remain in both denominators. Zero-finding packs remain in both denominators.

The finding cap is an evaluation parameter only. Applying it does not alter live model output or check-run rendering.

Adversarial controls use the same pack population and cap:

- The null challenger emits no findings. Its validated actionable yield is exactly zero, so it cannot pass a positive-yield gate.
- The spam challenger emits exactly the cap for every PR with no supporting adjudications. Its unsupported burden is exactly the cap per PR and fails non-inferiority against the null/reference burden at zero margin.

These are named yield and burden. They are not precision or recall. Git outcomes remain separate PR-level associations and never adjudicate an individual finding.

## Reconstructed PR #78 verifier regression

The fixture is explicitly labeled `reconstructed_verifier_regression` and `exact_replay: false`. It contains only the four finding records and stable evidence expectations, not invented request or response bytes.

Two deterministic verifiers establish the disputed claims:

1. An AST-based production caller inventory walks checked-in Python outside tests, records every `ingest.enqueue` call, and proves every current production call supplies keyword-only `base_sha`. The inventory receipt contains path, line, and keyword presence. This settles `reader:api-contract-change` as `disproved` on this revision.
2. A migration-membership probe exercises the same exact-version rule as `migrations.apply`: an applied ledger containing versions 1–8 and 10 still selects a newly available version 9. It records the before set, selected versions, and final set. This settles `reader:migration-version-conflict` as `disproved`.

The two remaining findings are resolved against accepted contracts, not desired model output:

- `reader:silent-work-drop` -> `verified_accepted_nonactionable` because refusing an incomplete base/head identity is the approved fail-closed admission behavior and is operator-visible.
- `reader:retry-exhaustion` -> `verified_accepted_nonactionable` because preserving the only durable job until a complete replacement exists is the approved fail-loud retry boundary.

No LLM judge participates. The regression asserts the exact ordered map and the aggregate result: two disproved, two verified accepted/nonactionable, zero actionable, zero unknown.

## Test strategy

Tests are written red-green and name the business break they catch. The required coverage is:

- canonical JSON is byte-stable and any request/evidence change changes `pack_hash`;
- every named whole-instrument component changes `instrument_id` when changed;
- finding identities are deterministic and duplicate-output positions remain distinct;
- frozen packs are unchanged by adjudication and supersession is explicit;
- zero-finding, partial, and failed runs enter both denominators;
- null and spam controls cannot pass;
- credential-shaped fields are rejected and SDK/client/header state is absent;
- capture is disabled by default and requires both explicit settings;
- atomic content-addressed writes are idempotent and mismatched existing content fails;
- reader success survives a capture write failure unchanged, while the failure is visible;
- reader transport/parse failures retain their original live fallback behavior;
- worker capture context carries tenant, repository, PR, admitted base, and admitted head identity;
- PR #78 returns the required four dispositions from deterministic evidence;
- findings-log file bytes, validation output, and prospective rates are unchanged.

Verification runs the focused pack tests, affected worker/reader/store/ingest/findings-log tests, the full API suite, findings-log validation, Ruff, and `git diff --check` before the branch is pushed.

## Known limitations and next boundary

Example Pack v0 proves local capture and deterministic evaluation mechanics. It does not provide an exact historical corpus, a production retention system, an adjudication UI, exhaustive gold labels, a challenger runner, or promotion authority. The first next step after this PR is an explicitly authorized local dogfood run that captures 20–30 consecutive future worker attempts and validates every object; production storage remains a separate decision.
