# Example Pack v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add disabled-by-default exact reader-attempt capture, immutable adjudication overlays, honest all-run scorecards, deterministic adversarial controls, and the reconstructed PR #78 verifier regression without changing Doug's live review behavior.

**Architecture:** New `example_pack` modules own canonical schemas, storage, capture orchestration, evaluation, and deterministic verifiers. `reader.py` canonicalizes the same request dictionary it passes to Anthropic and reports terminal attempt state to a best-effort capture sink; `worker.py` supplies tenant/repository/PR/base/head identity through a task-local capture scope. Packs and adjudications are content-addressed files for tests and explicit local dogfood only.

**Tech Stack:** Python 3.14, Pydantic v2, standard-library JSON/hash/path/tempfile/AST/contextvars, pytest, Ruff, existing Anthropic SDK and SQLAlchemy migration helper.

## Global Constraints

- Preserve `docs/findings-log.jsonl` bytes, schema, validation, and prospective rates.
- Do not change reader constants, prompts, schemas, output, routing, score, band, risk threshold, check-run text, production verdict uniqueness, or publication calculations.
- Do not add a production database table, GCS bucket, deployment setting, retention default, challenger runtime, LangGraph, Vertex dependency, fine-tuning, or Coldworks integration.
- Capture requires both `DOUG_EXAMPLE_PACK_CAPTURE=1` and an absolute `DOUG_EXAMPLE_PACK_DIR`; otherwise it performs no I/O.
- Every pack write is content-addressed, atomic, idempotent for identical bytes, and collision-loud for mismatched bytes.
- Capture failures are visible on stderr and never change the successful review result or replace the original reader failure.
- PR #78 remains `exact_replay: false`; no historical request or output bytes are invented.
- Every production-code change follows a witnessed failing test, minimal passing implementation, and focused rerun before commit.

---

### Task 1: Immutable schemas, canonical identity, and file storage

**Files:**

- Create: `api/doug/example_pack.py`
- Create: `api/tests/test_example_pack.py`

**Interfaces:**

- Produces: `canonical_json_bytes(value) -> bytes`, `sha256_hex(data) -> str`, frozen `ContentRefV0`, `CaptureScopeV0`, `CoverageV0`, `UsageV0`, `FailureV0`, `WholeInstrumentManifestV0`, `CapturedFindingV0`, `ExamplePackV0`, `EvidenceReceiptV0`, `VerifierReceiptV0`, and `ExampleAdjudicationV0`.
- Produces: `ExamplePackStore` protocol and `FileExamplePackStore(root: Path)` with `put_blob`, `put_pack`, `put_adjudication`, and `validate`.
- Consumes: no Doug review modules; this file must remain free of reader/worker imports.

- [ ] **Step 1: Write failing canonical/hash/model tests**

Add tests that hand-derive literal canonical bytes and construct a minimal pack through a wished-for builder:

```python
def test_canonical_json_is_stable_and_rejects_non_finite_numbers():
    assert canonical_json_bytes({"z": "é", "a": [2, 1]}) == b'{"a":[2,1],"z":"\xc3\xa9"}'
    with pytest.raises(ValueError):
        canonical_json_bytes({"latency": float("nan")})

def test_request_or_evidence_byte_changes_pack_hash():
    first = _pack(request=b'{"model":"a"}', evidence=b"+x")
    request_changed = _pack(request=b'{"model":"b"}', evidence=b"+x")
    evidence_changed = _pack(request=b'{"model":"a"}', evidence=b"+y")
    assert len({first.pack_hash, request_changed.pack_hash, evidence_changed.pack_hash}) == 3
```

Add a parameterized test that changes each whole-instrument component independently and asserts a new `instrument_id`: pinned model, inference parameter, system hash, schema hash, max output tokens, effort, diff budget, read ordering, input policy, coverage policy, verifier version, tool version, failure policy, publication policy, application revision, and runtime revision.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
cd api
uv run pytest tests/test_example_pack.py -q
```

Expected: collection fails because `doug.example_pack` does not exist.

- [ ] **Step 3: Implement frozen models and canonical builders**

Use Pydantic frozen/forbid-extra models and class builders that hash the payload without its self-hash field:

```python
class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

def canonical_json_bytes(value: object) -> bytes:
    reject_secret_fields(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

class ExamplePackV0(FrozenModel):
    schema_version: Literal["example-pack-v0"] = "example-pack-v0"
    pack_hash: str
    # exact fields from the focused design

    @classmethod
    def build(cls, **values) -> "ExamplePackV0":
        payload = {"schema_version": "example-pack-v0", **values}
        digest = sha256_hex(canonical_json_bytes(payload))
        return cls.model_validate({**payload, "pack_hash": digest})
```

`WholeInstrumentManifestV0.instrument_id()` and `CapturedFindingV0.build(...)` use the same canonical-hash rule. Add model validation that request is mandatory when `model_call_made=True`, successful packs have parsed output, and latency is non-negative.

- [ ] **Step 4: Run focused identity tests and verify GREEN**

Run:

```bash
cd api
uv run pytest tests/test_example_pack.py -q
```

Expected: canonical, hash, manifest, finding-identity, frozen-model, and validation tests pass.

- [ ] **Step 5: Write failing storage, secret, and collision tests**

Cover observable filesystem behavior:

```python
def test_content_addressed_write_is_idempotent_and_collision_loud(tmp_path):
    store = FileExamplePackStore(tmp_path)
    ref = store.put_blob(b"exact", media_type="application/octet-stream")
    assert store.put_blob(b"exact", media_type="application/octet-stream") == ref
    target = tmp_path / "blobs" / "sha256" / ref.sha256
    target.write_bytes(b"different")
    with pytest.raises(ContentCollisionError):
        store.put_blob(b"exact", media_type="application/octet-stream")

def test_secret_shaped_structural_fields_are_rejected():
    with pytest.raises(SecretFieldError, match="authorization"):
        canonical_json_bytes({"authorization": "Bearer secret"})
```

Also assert pack/adjudication filenames are their self-hashes, existing identical bytes are not rewritten, temporary files do not remain, missing/mismatched references fail validation, and an SDK-client-shaped object cannot enter canonical data.

- [ ] **Step 6: Run storage tests and verify RED**

Run the new storage test names. Expected: missing `FileExamplePackStore` methods/errors.

- [ ] **Step 7: Implement atomic storage and validation**

Write the complete bytes to a same-directory temporary file, flush and `os.fsync`, then use `os.link(temp, target)` as the atomic create-if-absent operation. On `FileExistsError`, compare exact bytes: identical is idempotent; different raises `ContentCollisionError`. Always unlink the temporary file. Validate blob filename hashes, pack/adjudication self-hashes, canonical file bytes, and every referenced blob.

- [ ] **Step 8: Run Task 1 tests and commit**

Run:

```bash
cd api
uv run pytest tests/test_example_pack.py -q
uv run ruff check doug/example_pack.py tests/test_example_pack.py
git diff --check
```

Commit:

```bash
git add api/doug/example_pack.py api/tests/test_example_pack.py
git commit -m "feat: add immutable Example Pack storage"
```

### Task 2: Append-only adjudication, scorecards, and adversarial controls

**Files:**

- Create: `api/doug/example_pack_eval.py`
- Create: `api/tests/test_example_pack_eval.py`
- Modify: `api/doug/example_pack.py`
- Modify: `api/tests/test_example_pack.py`

**Interfaces:**

- Consumes: `ExamplePackV0`, `ExampleAdjudicationV0`, and finding IDs from Task 1.
- Produces: `resolve_adjudications(overlays)`, `score_packs(packs, overlays, finding_cap) -> ScorecardV0`, `null_control_scorecard(packs)`, `spam_control_scorecard(packs, finding_cap)`, and `evaluate_control_gates(...) -> ControlGateV0`.

- [ ] **Step 1: Write failing adjudication and scorecard tests**

Tests must prove:

```python
def test_adjudication_never_mutates_the_pack_and_supersession_is_explicit():
    pack = _pack_with_findings(1)
    before = canonical_json_bytes(pack.model_dump(mode="json"))
    first = _adjudication(pack, "unknown")
    second = _adjudication(pack, "verified_actionable", supersedes=first.adjudication_id)
    assert resolve_adjudications([first, second])[pack.findings[0].finding_id] == second
    assert canonical_json_bytes(pack.model_dump(mode="json")) == before

def test_zero_partial_and_failed_runs_enter_both_denominators():
    score = score_packs(
        [_zero_pack("captured"), _zero_pack("partial"), _zero_pack("failed")],
        [],
        finding_cap=3,
    )
    assert score.eligible_prs == 3
    assert score.yield_denominator == 3
    assert score.burden_denominator == 3
```

Add failures for missing supersession target, cross-finding supersession, cycle, two live heads, duplicate eligible PR identity, non-risk pack evaluation, and non-positive cap. Add a literal disposition table proving `verified_actionable` increments yield, `disproved`/`unknown`/unadjudicated increment burden, and `verified_accepted_nonactionable` increments its separate count only.

- [ ] **Step 2: Run evaluation tests and verify RED**

Run:

```bash
cd api
uv run pytest tests/test_example_pack_eval.py -q
```

Expected: collection fails because `doug.example_pack_eval` does not exist.

- [ ] **Step 3: Implement explicit overlay resolution and all-pack scorecards**

Resolve the supersession graph by IDs, reject invalid edges/cycles/ambiguous live heads, then index one effective record per finding. Enforce one pack per `(instrument_id, tenant, repo, PR, base, head)`. Iterate every pack before any finding count so empty/partial/failed packs cannot disappear from either denominator.

Use count fields plus derived properties:

```python
validated_actionable_yield = validated_actionable / eligible_prs
unsupported_finding_burden = unsupported / eligible_prs
```

Do not name either property precision or recall.

- [ ] **Step 4: Write failing null/spam control tests**

```python
def test_null_and_spam_controls_cannot_pass():
    packs = [_zero_pack("captured"), _zero_pack("partial"), _zero_pack("failed")]
    gates = evaluate_control_gates(packs, finding_cap=4, required_yield=0.01,
                                   reference_burden=0.0, burden_margin=0.0)
    assert gates.null.validated_actionable_yield == 0
    assert not gates.null_passes_yield
    assert gates.spam.unsupported_finding_burden == 4
    assert not gates.spam_passes_burden
```

- [ ] **Step 5: Implement controls through the same denominator contract**

The null scorecard has the input pack count and zero findings. The spam scorecard has `eligible_prs * finding_cap` unsupported findings. Gate functions compare literal yield and burden constraints; no model or random data is involved.

- [ ] **Step 6: Run Task 2 tests and commit**

Run focused Task 1/2 tests, Ruff, and diff check. Commit:

```bash
git add api/doug/example_pack.py api/doug/example_pack_eval.py \
  api/tests/test_example_pack.py api/tests/test_example_pack_eval.py
git commit -m "feat: add Example Pack evaluation controls"
```

### Task 3: Deterministic PR #78 reconstructed verifier regression

**Files:**

- Create: `api/doug/example_pack_verifiers.py`
- Create: `api/tests/fixtures/example_pack_v0/pr78-reconstructed.json`
- Create: `api/tests/test_example_pack_verifiers.py`
- Modify: `api/doug/migrations.py`
- Modify: `api/tests/test_migrations.py`

**Interfaces:**

- Produces: `production_ingest_enqueue_callers(repo_root) -> list[CallerReceiptV0]`, `migrations.unapplied_migrations(plan, applied)`, and `verify_pr78_fixture(repo_root, fixture) -> list[ReconstructedDispositionV0]`.
- Consumes: the checked-in fixture and the exact migration membership helper used by `migrations.apply`.

- [ ] **Step 1: Add the explicit non-replay fixture**

The JSON contains:

```json
{
  "schema_version": "reconstructed-verifier-regression-v0",
  "source_pr": 78,
  "exact_replay": false,
  "findings": [
    {"rule": "reader:api-contract-change"},
    {"rule": "reader:migration-version-conflict"},
    {"rule": "reader:silent-work-drop"},
    {"rule": "reader:retry-exhaustion"}
  ]
}
```

Add stable accepted-contract references for the latter two without copying them into Example Pack desired outputs.

- [ ] **Step 2: Write failing caller-inventory and migration-membership tests**

The caller test asserts the real repository inventory contains exactly three production calls—one in `api.py`, two in `worker.py`—and every call supplies `base_sha`. It must fail if a fourth production caller omits the keyword. Build a temporary Python file to prove detection of `ingest.enqueue`, aliased module imports, and direct imported `enqueue` calls while excluding `api/tests`.

The migration test uses a plan whose available versions are `[1,2,3,4,5,6,7,8,10,9]` and an applied set `{1,2,3,4,5,6,7,8,10}`; the shared helper must return `[9]`.

- [ ] **Step 3: Run verifier tests and verify RED**

Run:

```bash
cd api
uv run pytest tests/test_example_pack_verifiers.py tests/test_migrations.py -q
```

Expected: missing verifier module/helper failures.

- [ ] **Step 4: Implement AST inventory and shared migration membership**

The AST inventory tracks module aliases from `from doug import ingest`, `from . import ingest`, and `import doug.ingest as ...`, plus direct function aliases from `from ...ingest import enqueue as ...`. It walks `api/doug` and `api/scripts`, excludes tests/cache/virtualenv directories, and records relative path, line, and whether the call has a `base_sha` keyword.

Extract the exact membership rule in `migrations.py`:

```python
def unapplied_migrations(plan, applied_versions):
    done = set(applied_versions)
    return [(version, statements) for version, statements in plan if version not in done]
```

Change `apply` only from `for version, statements in MIGRATIONS` plus an inline membership branch to `for version, statements in unapplied_migrations(MIGRATIONS, done)`. No migration DDL, ordering, or runtime result changes.

- [ ] **Step 5: Write failing exact PR #78 disposition test**

Assert this literal ordered dictionary and aggregate counts:

```python
assert {d.rule: d.disposition for d in dispositions} == {
    "reader:api-contract-change": "disproved",
    "reader:migration-version-conflict": "disproved",
    "reader:silent-work-drop": "verified_accepted_nonactionable",
    "reader:retry-exhaustion": "verified_accepted_nonactionable",
}
assert Counter(d.disposition for d in dispositions) == {
    "disproved": 2,
    "verified_accepted_nonactionable": 2,
}
```

- [ ] **Step 6: Implement fixture verification and receipts**

Reject any fixture with `exact_replay` other than false or an unexpected/missing rule. The two disprovals call the code verifiers and include their full deterministic receipts. The two accepted/nonactionable results use the fixture's explicit accepted-contract references. No LLM or findings-log verdict conversion is allowed.

- [ ] **Step 7: Run Task 3 tests and commit**

Run focused verifier/migration tests, Ruff, and diff check. Commit:

```bash
git add api/doug/example_pack_verifiers.py api/doug/migrations.py \
  api/tests/test_example_pack_verifiers.py api/tests/test_migrations.py \
  api/tests/fixtures/example_pack_v0/pr78-reconstructed.json
git commit -m "test: add deterministic PR 78 verifier regression"
```

### Task 4: Best-effort capture orchestration and exact reader envelopes

**Files:**

- Create: `api/doug/example_pack_capture.py`
- Create: `api/tests/test_example_pack_capture.py`
- Modify: `api/doug/reader.py`
- Modify: `api/tests/test_reader.py`

**Interfaces:**

- Consumes: Task 1 schemas/store and the current task-local `CaptureScopeV0`.
- Produces: `capture_scope(scope)` context manager, `current_scope()`, `configured_store(environ)`, `record_attempt(...)`, and a validation-safe terminal capture path.
- Preserves: `read_diff` and `read_with_decisions` public signatures and returned Pydantic types.

- [ ] **Step 1: Write failing configuration and context-isolation tests**

Assert default disabled, one-setting-only disabled, relative directory rejected visibly, both settings create a file store, and two copied async/thread contexts cannot read one another's scope. The disabled path must leave a sentinel directory absent.

- [ ] **Step 2: Run capture-module tests and verify RED**

Expected: `doug.example_pack_capture` missing.

- [ ] **Step 3: Implement configuration and task-local scope**

Use `ContextVar[CaptureScopeV0 | None]`, a resetting context manager, and exact enablement:

```python
if environ.get("DOUG_EXAMPLE_PACK_CAPTURE") != "1":
    return None
root = Path(environ.get("DOUG_EXAMPLE_PACK_DIR", ""))
if not root.is_absolute():
    raise CaptureConfigurationError("DOUG_EXAMPLE_PACK_DIR must be absolute")
```

`record_attempt` catches all construction/storage errors, prints one bounded `doug: example-pack capture failed ...` line, and returns a result object rather than raising.

- [ ] **Step 4: Write failing exact-envelope and terminal-state reader tests**

Extend the existing real fake client. Tests assert:

- the request blob bytes equal the hand-canonicalized `client.messages.last_kwargs` exactly;
- success with findings and success with zero findings write `captured` packs;
- truncated diff writes `partial` and exact coverage;
- transport, stop-reason, and parse failure write `failed`, with raw output retained whenever available;
- a spend-cap failure writes a preflight failure with `model_call_made=False` and no request reference;
- usage and latency are present;
- parsed finding IDs are stable;
- SDK client, authorization/header state, and credentials are absent;
- risk and intent requests have distinct instrument IDs;
- capture disabled writes nothing and preserves the exact existing SDK kwargs.

- [ ] **Step 5: Run the new reader capture tests and verify RED**

Run only the new test names. Expected: no pack files because reader has no capture hook.

- [ ] **Step 6: Refactor each reader call to one request dictionary**

For risk and intent independently:

```python
request = {
    "model": MODEL,
    "max_tokens": MAX_TOKENS,
    "output_config": {...},
    "system": SYSTEM,
    "messages": [{"role": "user", "content": _user_text(pr, diff)}],
}
request_bytes = canonical_json_bytes(request)
response = client.messages.create(**request)
```

Do not change any value or ordering-sensitive input construction. Record transport, stop-reason, parse, and success terminals with the exact request/evidence/raw bytes and `coverage(...)`. Capture the parsed reader object before settlement in `review.score_one` can remove findings.

- [ ] **Step 7: Prove capture failure cannot change live behavior**

Add two tests with a store whose `put_pack` raises:

1. A successful reader call returns the same `ReaderVerdict` and SDK kwargs while stderr names the capture failure.
2. A transport failure still raises the original `ReaderError`; the store failure is logged but does not replace its type/message.

- [ ] **Step 8: Run Task 4 tests and commit**

Run:

```bash
cd api
uv run pytest tests/test_example_pack.py tests/test_example_pack_capture.py tests/test_reader.py -q
uv run ruff check doug/example_pack.py doug/example_pack_capture.py doug/reader.py \
  tests/test_example_pack.py tests/test_example_pack_capture.py tests/test_reader.py
git diff --check
```

Commit:

```bash
git add api/doug/example_pack_capture.py api/doug/reader.py \
  api/tests/test_example_pack_capture.py api/tests/test_reader.py
git commit -m "feat: capture exact reader attempts"
```

### Task 5: Worker tenant/run identity and live-path isolation

**Files:**

- Modify: `api/doug/worker.py`
- Modify: `api/tests/test_worker.py`

**Interfaces:**

- Consumes: `example_pack_capture.capture_scope` and `CaptureScopeV0`.
- Produces: one scoped risk run and, when enabled, one scoped intent run per claimed worker attempt.
- Preserves: worker verdict persistence, job terminal state, check-run rendering/posting, and pre-read replay behavior.

- [ ] **Step 1: Write failing worker-scope integration tests**

Use the real reader with the existing fake GitHub/network seams. Enable a temporary pack directory and assert a stored pack contains exact values from the claimed `review_jobs` row:

```python
assert pack.run_id == f"review-job:{job_id}:claim:1:risk"
assert pack.scope.installation_id == JOB["installation_id"]
assert pack.scope.github_repository_id == JOB["github_repo_id"]
assert pack.scope.pull_number == JOB["pr_number"]
assert pack.scope.admitted_base_sha == JOB["base_sha"]
assert pack.scope.admitted_head_sha == JOB["head_sha"]
```

Add a retry test proving claim generation 2 creates a distinct stable run ID, and a replay-existing-verdict test proving no pack is created because no reader attempt occurs.

- [ ] **Step 2: Run worker capture tests and verify RED**

Expected: reader reports no admitted worker capture scope or writes no pack.

- [ ] **Step 3: Install capture scope only around paid reader paths**

After `fetch_pr` and before `score_one`, construct the scope from the claimed job. Source `application_revision` only from `DOUG_APPLICATION_REVISION` and `runtime_revision` only from `DOUG_RUNTIME_REVISION` or Cloud Run's `K_REVISION`; leave absent values null. Include `review.READ_ORDER`, the exact input/coverage policy version constants, and stable verifier/tool policy versions. Wrap the existing `score_one` plus `read_intent` calls in one resetting `capture_scope` block.

- [ ] **Step 4: Write failing process-job capture-failure test**

Enable a store that always raises and run a successful real reader response through `worker.process_job`. Assert the verdict row exists, job is `done`, check run posts, returned verdict ID is unchanged, and stderr contains the capture failure.

- [ ] **Step 5: Implement only the isolation needed for the failing test**

Capture code must remain best-effort inside the reader/capture module. Worker must not catch or reinterpret capture errors because none may escape. Do not alter `save_review`, `ingest.complete`, or `check_run.post` ordering.

- [ ] **Step 6: Run affected live-path suites and commit**

Run:

```bash
cd api
uv run pytest tests/test_worker.py tests/test_reader.py tests/test_review.py \
  tests/test_store.py tests/test_ingest.py -q
uv run ruff check doug/worker.py tests/test_worker.py
git diff --check
```

Commit:

```bash
git add api/doug/worker.py api/tests/test_worker.py
git commit -m "feat: scope Example Packs to worker attempts"
```

### Task 6: Operator validation documentation and unchanged-denominator receipts

**Files:**

- Create: `docs/EXAMPLE_PACK.md`
- Modify: `api/doug/example_pack.py`
- Modify: `api/tests/test_example_pack.py`

**Interfaces:**

- Produces: `python -m doug.example_pack validate <absolute-root>`.
- Documents: local opt-in, emitted object layout, exact-request claim boundary, validation, failure visibility, deletion, and the production-storage prerequisite.

- [ ] **Step 1: Write failing validator CLI tests**

Build a valid temporary store and assert `main(["validate", root]) == 0` with pack/blob/adjudication counts. Corrupt one referenced blob and assert exit 1 with a bounded integrity error. Assert a relative root is refused.

- [ ] **Step 2: Run CLI tests and verify RED**

Expected: missing CLI/parser behavior.

- [ ] **Step 3: Implement the validation CLI**

The command opens only the named directory, calls `FileExamplePackStore.validate`, prints deterministic counts, and returns nonzero on the first integrity/configuration error. It does not delete, repair, upload, or infer missing data.

- [ ] **Step 4: Write operator/developer documentation**

Document exact commands:

```bash
export DOUG_EXAMPLE_PACK_CAPTURE=1
export DOUG_EXAMPLE_PACK_DIR=/absolute/private/path
cd api
uv run python -m doug.example_pack validate "$DOUG_EXAMPLE_PACK_DIR"
```

State that the directory contains opt-in source diff/request/output evidence, must be access-controlled by the operator, and can be removed locally only under the operator's own retention decision. State explicitly that no production capture/deploy/storage is enabled and list the prerequisite production decisions from the spec.

- [ ] **Step 5: Record findings-log invariants without editing it**

Capture and compare these base receipts before and after implementation:

```text
sha256 b5d9cfa261783be54e036bb9f77fb7f430863bbfd2b340449ea078109c5f3b39
rows 102
prospective n 90
by_verdict adjacent=23 disproved=26 real=41
changed_true 28
```

Run `uv run python -m doug.findings_log check` and `rate`. Do not add an enduring literal-hash test that would block future intentional disposition appends; the PR diff and command receipts prove this PR did not change the denominator.

- [ ] **Step 6: Run focused documentation/CLI tests and commit**

Run focused Example Pack and findings-log tests, Ruff, and diff check. Commit:

```bash
git add api/doug/example_pack.py api/tests/test_example_pack.py docs/EXAMPLE_PACK.md
git commit -m "docs: add Example Pack dogfood runbook"
```

### Task 7: Independent reviews, full verification, and unmerged PR

**Files:**

- Modify only files required to resolve confirmed review findings.
- Create no production configuration or deployment files.

**Interfaces:**

- Consumes: the complete branch diff from `4db0cce` to branch HEAD and this plan/spec.
- Produces: two independent read-only review reports, resolved findings, fresh verification receipts, commits, and an open PR.

- [ ] **Step 1: Run contract/evaluation review in an independent agent**

Give the reviewer the base/head SHAs, focused spec, plan, and read-only instruction. Require checks for request/pack/instrument/finding identity, canonical bytes, all-run denominators, duplicate PR handling, adjudication supersession, leakage, null/spam controls, finding-level evidence, and separation from PR-level outcomes.

- [ ] **Step 2: Run security/operations review in a second independent agent**

Require checks for tenant/repository scope, secret/client/header exclusion, default-off behavior, explicit config, path safety, task-local context, atomic/collision-safe storage, retention/deletion prerequisite, capture-failure isolation, and absence of production capture/deployment changes.

- [ ] **Step 3: Reproduce every claimed issue and resolve confirmed findings with TDD**

For each confirmed bug, add a failing regression test, observe the expected failure, implement the minimum fix, and rerun focused tests. Record rejected findings with concrete code/test evidence. Ask each reviewer to re-check its confirmed fixes or run a fresh scoped review when the first reviewer is unavailable.

- [ ] **Step 4: Run required verification from a clean tree candidate**

Run and preserve exact output for:

```bash
cd api
uv run pytest tests/test_example_pack.py tests/test_example_pack_capture.py \
  tests/test_example_pack_eval.py tests/test_example_pack_verifiers.py -q
uv run pytest tests/test_worker.py tests/test_reader.py tests/test_store.py \
  tests/test_ingest.py tests/test_findings_log.py -q
uv run pytest
uv run ruff check .
uv run python -m doug.findings_log check
uv run python -m doug.findings_log rate
cd ..
git diff --check
git status --short
```

Also compare `docs/findings-log.jsonl` SHA-256 and rates to Task 6's base receipts.

- [ ] **Step 5: Commit review fixes and final receipts documentation**

Keep independent-review findings/dispositions in the PR body rather than creating generated receipt files unless a confirmed repository convention requires one. Commit any code/doc fixes with focused messages.

- [ ] **Step 6: Push and create the PR without merging**

Push `feat/example-pack-v0` and open a PR against current `main`. The body must contain:

- literal capture-only scope and explicit non-goals;
- `ExamplePackV0`/`ExampleAdjudicationV0` schema and hash decisions;
- exact-request-bytes boundary (Doug-controlled canonical envelope, not HTTP wire bytes);
- default-off/local-file-only security and retention boundary;
- PR #78 reconstructed-regression disclaimer and exact four dispositions;
- verification commands and exact pass counts;
- both independent-review reports and dispositions;
- explicit statement that no production capture, source retention, infrastructure mutation, or deployment was enabled;
- remaining limitations and the next smallest follow-up.

Do not merge. Preserve the worktree for PR feedback.
