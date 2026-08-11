# Hosted Example Pack Workbench Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` to execute this plan task by task. Use `superpowers:test-driven-development` for every behavior change and `superpowers:verification-before-completion` before any completion claim.

**Goal:** Add an automatic, risk-only Doug dogfood capture lane backed by private Cloud Storage, expose evidence-complete cohort reads and append-only adjudication through purpose-token API routes, and render the workbench in the existing IAM-gated `doug-console` without changing WorkOS, login, tenant, scoring, or verdict behavior.

**Architecture:** Keep Example Pack canonical models independent of storage SDKs. Add immutable cohort contracts and a generic hosted repository, a thin GCS object adapter, a read/adjudication service that joins validated objects to completed review jobs, purpose-token FastAPI routes, and server-only console pages/actions. Capture remains advisory and bounded; scorecards fail closed when their evidence set is incomplete. Production resource creation and capture enablement are scripted/documented but are not executed by this implementation session.

**Tech stack:** Python 3.14, Pydantic 2, FastAPI, SQLAlchemy, `google-cloud-storage`, pytest, Ruff; Next.js 16 App Router, React 19 Server Components/Server Actions, TypeScript, Tailwind 4, Node test runner; Bash/gcloud source-contract tests.

**Approved design:** `docs/superpowers/specs/2026-08-10-hosted-example-pack-workbench-design.md`

**Base:** `origin/main` at `dd433712ed468d1ce9bf4c050cc1b1055ec0ff28`; the branch already contains the WorkOS issuer fix from PR #85.

## Assumptions and non-negotiable boundaries

- The hosted lane captures only `attempt_kind="risk"` for exact numeric installation and GitHub repository allowlists.
- Existing local `DOUG_EXAMPLE_PACK_DIR` behavior remains supported and is mutually exclusive with hosted bucket configuration.
- `review_jobs.enqueued_at` is not a stable admission timestamp. Completeness uses the design's corrected union of terminal `started_at` rows and completed membership-linked job IDs. No database migration is added.
- The existing `DOUG_API_TOKEN` cannot authorize Example Pack routes. Only `DOUG_EXAMPLE_PACK_TOKEN` can.
- The console has no Cloud Storage role and never sends a token to the browser.
- No WorkOS module, session route, tenant dashboard, public route, scoring path, verdict contract, or database schema changes.
- No GCP, IAM, Secret Manager, audit-log, Cloud Run, or capture mutation is run in this session.

## Success loop

1. A non-allowlisted or malformed configuration produces zero object-store calls and cannot alter a review result.
2. An allowlisted risk attempt creates canonical blobs, pack, and first-writer membership using create-only writes within one five-second budget.
3. Cohort reads validate every object and reference, compare against durable completed jobs, and publish per-instrument metrics only when complete.
4. The console lists cohorts, drills into exact evidence, and appends/supersedes adjudications through a same-origin server action.
5. Focused tests, full API/web/console suites, both builds, deployment source tests, and a synthetic browser smoke all pass with no skipped checks.

---

### Task 1: Define immutable cohort contracts and generic hosted repository

**Files:**

- Create: `api/doug/example_pack_hosted.py`
- Modify: `api/doug/example_pack.py`
- Modify: `api/doug/example_pack_eval.py`
- Create: `api/tests/test_example_pack_hosted.py`
- Modify: `api/tests/test_example_pack_eval.py`

**Step 1: Write failing domain tests**

Add tests that pin the reason for each contract:

- `CohortManifestV0` accepts only schema `example-pack-cohort-v0`, a safe slug, ordered unique positive IDs, `attempt_kinds=("risk",)`, UTC timestamps with `started < until`, finding cap `3`, retention `90`, and a clean 40-character lowercase git SHA.
- `EvaluationIdentityV0.from_pack(pack)` hashes exactly `instrument_id`, installation ID, repository ID, PR number, admitted base SHA, and admitted head SHA.
- `CohortMembershipV0.build(pack, review_job_id)` self-hashes the identity, carries the immutable job ID, pack hash, run ID, and captured timestamp, and rejects a mismatched pack/identity/hash.
- `HostedExamplePackRepository` writes only these keys:

  ```text
  cohorts/<cohort>/cohort.json
  cohorts/<cohort>/blobs/sha256/<sha256>
  cohorts/<cohort>/packs/sha256/<pack_hash>.json
  cohorts/<cohort>/members/sha256/<eligibility_hash>.json
  cohorts/<cohort>/adjudications/sha256/<adjudication_id>.json
  ```

- The first membership create wins; a later retry is stored as a pack but cannot replace the member.
- Repository reads reject missing references, wrong hashes/sizes, duplicate membership identities, foreign cohort prefixes, more than 500 packs, and two live adjudication heads.
- `score_packs_by_instrument(...)` returns one ordered scorecard per `instrument_id` and never mixes revisions.

Use a test-local `MemoryObjectStore` that records `(key, bytes, content_type)` and implements create/read/list. Do not use filesystem or GCP credentials in these tests.

**Step 2: Run the focused tests and confirm RED**

Run:

```bash
cd api
uv run pytest tests/test_example_pack_hosted.py tests/test_example_pack_eval.py -q
```

Expected: collection/import failures for the new hosted contracts and failing partition assertions.

**Step 3: Implement the minimum domain layer**

In `example_pack_hosted.py`, add:

```python
class HostedObjectStore(Protocol):
    def create(self, key: str, data: bytes, *, content_type: str) -> None: ...
    def read(self, key: str) -> bytes: ...
    def list(self, prefix: str) -> tuple[str, ...]: ...

class CohortManifestV0(FrozenModel): ...
class EvaluationIdentityV0(FrozenModel): ...
class CohortMembershipV0(FrozenModel): ...
class MembershipClaimV0(FrozenModel):
    member: bool
    membership: CohortMembershipV0
class ValidatedCohortV0(FrozenModel): ...

class HostedExamplePackRepository:
    def ensure_manifest(self, manifest: CohortManifestV0) -> None: ...
    def put_blob(self, data: bytes, *, media_type: str) -> ContentRefV0: ...
    def put_pack(self, pack: ExamplePackV0) -> str: ...
    def put_membership(self, pack: ExamplePackV0, *, review_job_id: int) -> MembershipClaimV0: ...
    def put_adjudication(self, adjudication: ExampleAdjudicationV0) -> str: ...
    def validate(self) -> ValidatedCohortV0: ...
```

Keep canonical serialization in `example_pack.py`; only widen `ExamplePackStore.put_pack` and `put_adjudication` return types from `Path` to `Path | str` so the reader orchestration stays storage-agnostic. Every hosted repository create passes canonical bytes to `HostedObjectStore.create`; collisions are handled only by the adapter.

In `example_pack_eval.py`, add:

```python
def score_packs_by_instrument(
    packs: Sequence[ExamplePackV0],
    overlays: Sequence[ExampleAdjudicationV0],
    *,
    finding_cap: int,
) -> tuple[InstrumentScorecardV0, ...]: ...
```

Partition before calling `score_packs`, order by `instrument_id`, and filter overlays to the partition's pack hashes. Preserve the existing single-instrument evaluator API.

**Step 4: Run focused tests and static checks**

```bash
cd api
uv run pytest tests/test_example_pack.py tests/test_example_pack_eval.py tests/test_example_pack_hosted.py -q
uv run ruff check doug/example_pack.py doug/example_pack_eval.py doug/example_pack_hosted.py tests/test_example_pack_hosted.py
```

Expected: all pass, no skipped tests.

**Step 5: Commit**

```bash
git add api/doug/example_pack.py api/doug/example_pack_eval.py api/doug/example_pack_hosted.py api/tests/test_example_pack_eval.py api/tests/test_example_pack_hosted.py
git commit -m "feat(api): define hosted Example Pack cohorts"
```

---

### Task 2: Add the create-only Cloud Storage adapter and five-second budget

**Files:**

- Create: `api/doug/example_pack_gcs.py`
- Create: `api/tests/test_example_pack_gcs.py`
- Modify: `api/pyproject.toml`
- Modify: `api/uv.lock`

**Step 1: Add the dependency deterministically**

```bash
cd api
uv add google-cloud-storage
```

Review both `pyproject.toml` and `uv.lock`; do not accept unrelated dependency changes.

**Step 2: Write failing adapter tests**

With fake client/bucket/blob objects, assert:

- every upload uses `if_generation_match=0`;
- uploads use a conditional retry policy and a timeout no greater than the remaining total budget;
- `PreconditionFailed` reads the existing object and treats byte equality as idempotent success;
- different existing bytes raise `ContentCollisionError`;
- reads verify the object exists and return bytes without exposing bucket/object URLs;
- lists are sorted, scoped to the supplied prefix, and fail over 500 results;
- a monotonic clock crossing five seconds prevents another storage call and raises `CaptureBudgetExceeded`;
- exceptions expose only bounded exception class names to callers.

**Step 3: Run the focused test and confirm RED**

```bash
cd api
uv run pytest tests/test_example_pack_gcs.py -q
```

Expected: import failure for `doug.example_pack_gcs`.

**Step 4: Implement the adapter**

Add:

```python
class CaptureBudgetExceeded(TimeoutError): ...

class StorageBudget:
    def __init__(self, *, seconds: float = 5.0, monotonic: Callable[[], float] = time.monotonic): ...
    def remaining(self) -> float: ...

class GcsObjectStore:
    def __init__(self, bucket_name: str, *, client: storage.Client | None = None, budget: StorageBudget | None = None): ...
    def create(self, key: str, data: bytes, *, content_type: str) -> None: ...
    def read(self, key: str) -> bytes: ...
    def list(self, prefix: str) -> tuple[str, ...]: ...
```

Use `google.cloud.storage.retry.DEFAULT_RETRY_IF_GENERATION_SPECIFIED` with the remaining budget and `if_generation_match=0`. Never use overwrite, delete, signed URL, ACL, or public helpers.

**Step 5: Verify and commit**

```bash
cd api
uv run pytest tests/test_example_pack_gcs.py tests/test_example_pack_hosted.py -q
uv run ruff check doug/example_pack_gcs.py tests/test_example_pack_gcs.py
git diff --check
cd ..
git add api/pyproject.toml api/uv.lock api/doug/example_pack_gcs.py api/tests/test_example_pack_gcs.py
git commit -m "feat(api): add immutable GCS evidence store"
```

---

### Task 3: Gate automatic hosted capture before canonicalization

**Files:**

- Modify: `api/doug/example_pack_capture.py`
- Modify: `api/doug/example_pack.py`
- Modify: `api/doug/worker.py`
- Modify: `api/doug/reader.py`
- Modify: `api/tests/test_example_pack_capture.py`
- Modify: `api/tests/test_reader.py`
- Modify: `api/tests/test_worker.py`

**Step 1: Write failing eligibility and isolation tests**

Pin these cases:

- local directory capture still behaves exactly as before;
- local directory plus bucket is a named configuration error contained by the best-effort boundary;
- hosted capture requires flag, bucket, cohort, explicit UTC start/end, exact positive numeric installation/repository allowlists, clean application revision, and fixed adjudicator;
- malformed, pre-window, expired, intent, non-allowlisted installation/repository, or missing base/head configuration creates no client, scope, request bytes, or storage calls;
- allowlisted risk capture creates/validates the manifest, stores the pack, and claims membership with `review_job_id`;
- a failed, partial, zero-finding, and ordinary finding pack can each win membership;
- a retry collision leaves the first membership unchanged and returns the later pack as captured/non-member;
- GCS construction/blob/pack/membership/budget errors produce one bounded diagnostic and do not change `review.score_one`, `review.read_intent`, worker completion, verdict ID, or check-run behavior;
- the intent read inside the same worker context never reaches the hosted store;
- `DOUG_APPLICATION_REVISION` must equal a clean SHA while `K_REVISION` remains only runtime evidence.

**Step 2: Run focused tests and confirm RED**

```bash
cd api
uv run pytest tests/test_example_pack_capture.py tests/test_reader.py tests/test_worker.py -q
```

Expected: hosted-configuration and membership tests fail while existing local tests remain green.

**Step 3: Implement explicit configuration and lazy eligibility**

Add frozen `HostedCaptureConfigV0` parsing in `example_pack_capture.py`. Keep `capture_requested()` cheap: it may inspect environment strings but must not instantiate GCS. Pass `installation_id` and `github_repository_id` explicitly from the worker into `capture_scope_if_enabled`; hosted configuration must reject foreign IDs and a closed window before invoking `scope_factory`. Do not extract either ID from a repository display name.

Add optional `review_job_id` to `CaptureScopeV0`; the worker sets it from the claimed row and hosted capture requires it, while existing local callers remain compatible. Add `attempt_kind` to `prepare_request_bytes`: local capture continues to canonicalize both kinds, but hosted capture returns `(None, None)` for intent before constructing storage. Hosted `record_attempt` repeats the risk-only guard, creates one `StorageBudget`, and uses it for manifest, blobs, pack, and membership. Preserve `CaptureResultV0` but add `member: bool | None` and keep `path` local-only so no bucket or object name enters logs/API responses.

Do not move capture into scoring and do not catch or rewrite reader outcomes. The only new worker logic is identity/config gating; `ingest.complete`, check-run order, and replay behavior remain unchanged.

**Step 4: Verify and commit**

```bash
cd api
uv run pytest tests/test_example_pack_capture.py tests/test_reader.py tests/test_worker.py -q
uv run ruff check doug/example_pack_capture.py doug/reader.py doug/worker.py tests/test_example_pack_capture.py
git diff --check
cd ..
git add api/doug/example_pack.py api/doug/example_pack_capture.py api/doug/reader.py api/doug/worker.py api/tests/test_example_pack_capture.py api/tests/test_reader.py api/tests/test_worker.py
git commit -m "feat(api): capture allowlisted risk packs automatically"
```

---

### Task 4: Join validated cohorts to durable review-job coverage

**Files:**

- Create: `api/doug/example_pack_service.py`
- Modify: `api/doug/store.py`
- Create: `api/tests/test_example_pack_service.py`
- Modify: `api/tests/test_store.py`

**Step 1: Write failing store and service tests**

For `store.completed_example_pack_jobs(...)`, assert the query returns only allowlisted `status="done"`, non-null `verdict_id`, non-null base/head rows in the union of:

- terminal `started_at` in `[capture_started_at, capture_until)`; or
- exact membership-linked job IDs.

Assert it excludes failed, pending, superseded, skipped/no-verdict, foreign installation/repository, null-base, and unlinked post-window rows. Add the regression that `enqueued_at` can move across the window without changing inclusion.

For `ExamplePackService`, assert:

- complete identity sets produce member inventory and per-instrument scorecards;
- a completed job without membership blocks every scorecard and returns the exact missing identity;
- a membership-linked completed retry stays in-scope after the window;
- a member with no durable completed job is labeled extra and is excluded from scorecard denominators;
- empty, expired-by-retention, invalid-reference, duplicate-member, duplicate-live-head, and over-500-pack cohorts return named unavailable states, never empty metrics;
- adjudication coverage counts every finding, including unadjudicated findings as unsupported;
- list/detail/results ordering is deterministic.

**Step 2: Run focused tests and confirm RED**

```bash
cd api
uv run pytest tests/test_store.py tests/test_example_pack_service.py -q
```

Expected: missing query/service failures.

**Step 3: Implement the read service**

Add a read-only store query returning `CompletedExamplePackJobV0` values. Use SQLAlchemy predicates over the existing table only; no metadata/table/migration edits.

In `example_pack_service.py`, add explicit response-domain models:

```python
class CaptureCompletenessV0(FrozenModel): ...
class CohortAvailabilityV0(FrozenModel): ...
class CohortSummaryV0(FrozenModel): ...
class CohortDetailV0(FrozenModel): ...
class PackDetailV0(FrozenModel): ...
class CohortResultsV0(FrozenModel): ...

class ExamplePackService:
    def list_cohorts(self) -> tuple[CohortSummaryV0, ...]: ...
    def cohort_detail(self, cohort_id: str) -> CohortDetailV0: ...
    def pack_detail(self, cohort_id: str, pack_hash: str) -> PackDetailV0: ...
    def results(self, cohort_id: str) -> CohortResultsV0: ...
```

Only matched completed members enter scorecards. Keep non-member retries and extra members in separately labeled inventories. Return structured bounded reasons that the API can map without forwarding exception text.

**Step 4: Verify and commit**

```bash
cd api
uv run pytest tests/test_store.py tests/test_example_pack_service.py -q
uv run ruff check doug/store.py doug/example_pack_service.py tests/test_example_pack_service.py
git diff --check
cd ..
git add api/doug/store.py api/doug/example_pack_service.py api/tests/test_store.py api/tests/test_example_pack_service.py
git commit -m "feat(api): validate cohort completeness against review jobs"
```

---

### Task 5: Add purpose-token API routes and serialized adjudication

**Files:**

- Modify: `api/doug/api.py`
- Modify: `api/doug/store.py`
- Modify: `api/tests/test_api.py`
- Modify: `api/tests/test_store.py`
- Modify: `api/tests/test_prove_session_isolation_script.py`

**Step 1: Write failing API/auth/concurrency tests**

Add caller-level tests for all five routes. Prove:

- missing and wrong `X-Doug-Example-Pack-Token` are 403;
- correct `DOUG_API_TOKEN` alone is still 403;
- unset `DOUG_EXAMPLE_PACK_TOKEN` is 503;
- correct purpose token reaches list/detail/pack/results and returns deterministic JSON;
- 404 unknown cohort/pack/finding, 409 invalid/incomplete/stale, 413 pack cap, and 503 store misconfiguration are exact;
- no response/error contains token, bucket, object key, storage exception body, or signed URL;
- conclusive dispositions require evidence/verifier receipts while `unknown` may be receipt-free;
- the API ignores browser adjudicator input and stamps configured `DOUG_EXAMPLE_PACK_ADJUDICATOR`;
- the POST requires the observed current adjudication ID; a stale value returns 409;
- two concurrent corrections serialize and cannot create two live heads;
- existing `/v1/*` routes remain on their prior auth classes and Example Pack routes are excluded from tenant-session proofs.

**Step 2: Run focused tests and confirm RED**

```bash
cd api
uv run pytest tests/test_api.py tests/test_store.py tests/test_prove_session_isolation_script.py -q
```

Expected: missing routes/helper/lock failures.

**Step 3: Implement the separate gate and advisory lock**

Add `_example_pack_only(x_doug_example_pack_token)` using `hmac.compare_digest`. Keep it separate from `_operator_only`; never accept either token as a fallback for the other.

Add a session-level Postgres advisory-lock context manager in `store.py` keyed by the first signed 64 bits of SHA-256 over canonical `(cohort_id, pack_hash, finding_id)`. Hold it across service re-read, expected-head comparison, adjudication build, and create-only GCS write. Use a process lock only for SQLite tests; production must execute `pg_advisory_lock`/`pg_advisory_unlock` on the same connection.

Mount exactly:

```text
GET  /v1/example-pack-cohorts
GET  /v1/example-pack-cohorts/{cohort_id}
GET  /v1/example-pack-cohorts/{cohort_id}/packs/{pack_hash}
POST /v1/example-pack-cohorts/{cohort_id}/packs/{pack_hash}/findings/{finding_id}/adjudications
GET  /v1/example-pack-cohorts/{cohort_id}/results
```

Build the service from configured bucket/adjudicator on each request or a safe cached client; closed capture windows remain readable. Do not expose storage configuration in response models.

**Step 4: Verify and commit**

```bash
cd api
uv run pytest tests/test_api.py tests/test_store.py tests/test_prove_session_isolation_script.py -q
uv run ruff check doug/api.py doug/store.py tests/test_api.py
git diff --check
cd ..
git add api/doug/api.py api/doug/store.py api/tests/test_api.py api/tests/test_store.py api/tests/test_prove_session_isolation_script.py
git commit -m "feat(api): expose Example Pack adjudication API"
```

---

### Task 6: Add explicit, non-executed GCP rollout wiring and receipts

**Files:**

- Modify: `api/deploy/gcp.sh`
- Modify: `api/tests/test_deploy_gcp.py`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/EXAMPLE_PACK.md`

**Step 1: Write failing shell-source tests**

Pin that:

- `example-pack-setup` enables Storage API, creates one regional Standard bucket, enables uniform bucket-level access, enforces public-access prevention, and installs a 90-day delete lifecycle;
- it creates `doug-example-pack-token`, binds secret access only to API and console service accounts, grants only bucket-level `roles/storage.objectCreator` and `roles/storage.objectViewer` to API, and grants console no storage role;
- ordinary `deploy` and `console` perform no bucket/IAM/audit-log mutation;
- API and console receive `DOUG_EXAMPLE_PACK_TOKEN`; web and adjudicator do not;
- hosted capture stays disabled unless every explicit cohort variable is supplied;
- a capture-enabled deploy refuses a dirty/non-commit source and stamps the exact clean git SHA;
- existing WorkOS secret allowlists and console's absence of WorkOS identity secrets remain exact.

**Step 2: Run the focused test and confirm RED**

```bash
cd api
uv run pytest tests/test_deploy_gcp.py -q
```

Expected: missing setup command, token, bucket, and env wiring assertions.

**Step 3: Implement commands without running them**

Add explicit `example-pack-setup`, `example-pack-enable`, and `example-pack-disable` subcommands. `example-pack-enable` must require bucket, cohort, exact UTC start/end, numeric allowlists, adjudicator, and clean application revision; it may update only `doug-api`. `example-pack-disable` must set only `DOUG_EXAMPLE_PACK_CAPTURE=0`. Keep both outside CI.

Document commands as operator runbooks with placeholders represented as required shell variables, not guessed production IDs. Include read-only preflight commands for bucket location/UBLA/PAP/lifecycle/IAM, project Data Read/Data Write audit configuration, secret bindings, Cloud Run revision env, one synthetic object write/read audit-log query, console proxy smoke, queue drain, and disable/incident steps. State that Data Access audit-log configuration is project-wide and must be reviewed/applied separately; the script must not overwrite the project's audit policy.

**Step 4: Verify and commit**

```bash
cd api
uv run pytest tests/test_deploy_gcp.py -q
bash -n deploy/gcp.sh
git diff --check
cd ..
git add api/deploy/gcp.sh api/tests/test_deploy_gcp.py docs/OPERATIONS.md docs/EXAMPLE_PACK.md
git commit -m "ops: wire bounded Example Pack rollout"
```

Do not invoke any new gcloud command.

---

### Task 7: Add strict server-only console API contracts

**Files:**

- Create: `console/lib/example-packs.ts`
- Create: `console/lib/example-packs.test.mjs`
- Modify: `console/lib/api.ts`
- Modify: `console/lib/api.test.mjs`

**Step 1: Write failing TypeScript behavior tests**

Test strict guards/formatters for cohort summaries, completeness, per-instrument scorecards, member/non-member rows, pack detail, evidence receipts, and adjudication action input. Malformed nested payloads must become an unavailable/error result rather than a partial cast. Rates must always format with `N`; null/empty/unavailable remain distinct.

Test the server API wrapper with mocked `fetch`:

- reads and POST use only `X-Doug-Example-Pack-Token` from `DOUG_EXAMPLE_PACK_TOKEN`;
- `DOUG_API_TOKEN` is absent from Example Pack requests;
- credentials never appear in returned error strings;
- all requests are `cache: "no-store"` and bounded by the existing timeout;
- POST sends only validated disposition/receipt/current-head fields.

**Step 2: Run and confirm RED**

```bash
cd console
npm test -- --test-name-pattern="Example Pack"
```

Expected: missing module/export failures.

**Step 3: Implement the strict boundary**

Add exact TypeScript interfaces plus `unknown`-to-contract validators in `example-packs.ts`. In `api.ts`, keep the existing operator `get` unchanged and add a private purpose-token request helper plus:

```typescript
getExamplePackCohorts()
getExamplePackCohort(cohortId)
getExamplePackDetail(cohortId, packHash)
getExamplePackResults(cohortId)
postExamplePackAdjudication(cohortId, packHash, findingId, input)
```

Use `encodeURIComponent` for every path segment. Do not export either token or API request headers.

**Step 4: Verify and commit**

```bash
cd console
npm test
npm run lint
cd ..
git diff --check
git add console/lib/api.ts console/lib/api.test.mjs console/lib/example-packs.ts console/lib/example-packs.test.mjs
git commit -m "feat(console): add strict Example Pack API client"
```

---

### Task 8: Build the evidence-ledger workbench and adjudication action

**Files:**

- Modify: `console/components/shell.tsx`
- Create: `console/components/example-pack-summary.tsx`
- Create: `console/components/example-pack-table.tsx`
- Create: `console/components/example-pack-detail.tsx`
- Create: `console/components/adjudication-form.tsx`
- Create: `console/app/example-packs/page.tsx`
- Create: `console/app/example-packs/[packHash]/page.tsx`
- Create: `console/app/example-packs/actions.ts`
- Modify: `console/app/globals.css`
- Create: `console/scripts/example-pack-fixture-api.mjs`
- Create: `console/scripts/example-pack-smoke.mjs`
- Modify: `console/package.json`

**Design brief applied from `frontend-design`:**

- **Subject / audience / job:** a private operator evidence docket for Andrew; decide whether each captured finding is supported and preserve a correction receipt.
- **Palette:** reuse Doug's existing Paper `#fcfcfa`, Ink `#111311`, Field Grey `#545852`, Signal Orange `#d1571e`, Flag Red `#c93a2b`, and Verify Green `#177a50`. Add no third semantic data color.
- **Type:** existing Bricolage for restrained headings, Geist Sans for explanation, Geist Mono for hashes, status, metrics, and receipts. No remote font or new dependency.
- **Layout:** cohort page is a horizontal coverage docket above an instrument-partitioned ledger; pack page is a responsive case file with evidence in the main column and the finding/adjudication docket beside it.
- **Signature:** one vertical “evidence seam” joins request → evidence → output → finding → adjudication, using the existing orange chrome color only for navigation/focus. It encodes provenance order rather than decorating the page.
- **Self-critique:** avoid generic metric cards and dashboard gradients. Four top facts render as a ruled receipt with explicit numerator/denominator and blocked states. Keep motion out; this is an audit surface where stability helps reading.

Wire `Shell.active` to include `"example-packs"` and replace the disabled Evidence phase marker with a real `Example Packs` link. Leave Runs, Jobs, Repos, scope chips, health strip, and auth behavior unchanged.

The list route is `force-dynamic`, selects a requested cohort or the newest valid summary deterministically, and renders unavailable/empty/complete states without fallback. The detail route validates both `cohort` and `packHash`, displays captured content only through React text nodes, and uses `<details>` for exact request/diff/raw output.

Implement the server action with `'use server'`, strict `FormData` validation, fixed path identities passed with `bind`, the observed current adjudication ID, `postExamplePackAdjudication`, and `revalidatePath` for both detail and list. It must never accept adjudicator identity or token fields from the browser. Use `useActionState` and `useFormStatus` for exact stale/validation/API error states and pending submission. Do not use `dangerouslySetInnerHTML`.

**Step 1: Add failing pure/render contract tests**

Before components, extend `example-packs.test.mjs` to pin presentation decisions: blocked results return no rate, member/non-member labels are distinct, every rate includes N, exact captured `<script>` text remains plain text data, and stale adjudication maps to a correction-needed message.

**Step 2: Implement pages/components/action**

Build in this order: shell navigation, server pages, pure summary/table/detail components, then the small client adjudication form. Use semantic table/dl/details/form elements, visible focus, mobile single-column fallback, and `aria-live` for action results.

**Step 3: Add a checked-in synthetic HTTP fixture and smoke script**

The fixture server exposes only the five Example Pack endpoints on localhost and mutates only an in-memory adjudication array. Include cohorts for complete, blocked-missing, partial/failed/zero-finding, retry, and two-instrument states. The smoke script starts the fixture plus `next dev` on unused localhost ports, verifies list/detail HTML and adjudication/correction responses, and exits cleanly. It is local test support only; production code has no fixture fallback.

Add `npm run smoke:example-packs`.

**Step 4: Verify, inspect, and commit**

```bash
cd console
npm test
npm run lint
npm run build
npm run smoke:example-packs
cd ..
git diff --check
git add console
git commit -m "feat(console): add Example Pack adjudication workbench"
```

Start the local fixture and console, inspect `/example-packs` and one detail route in the in-app browser at desktop and mobile widths, and capture screenshots outside the repository. Check focus, overflow, escaped source text, blocked metrics, first-load errors, pending action, stale correction, and post-adjudication refresh. Apply any visual corrections before the commit.

---

### Task 9: Full regression verification, documentation reconciliation, and PR

**Files:**

- Modify if needed: `docs/superpowers/specs/2026-08-10-hosted-example-pack-workbench-design.md`
- Modify if needed: `docs/superpowers/plans/2026-08-10-hosted-example-pack-workbench.md`
- Modify if needed: `docs/EXAMPLE_PACK.md`
- Modify if needed: `docs/OPERATIONS.md`

**Step 1: Run the complete verification matrix from a clean state**

```bash
cd api
uv sync --locked --dev
uv run pytest -q
uv run ruff check .
bash -n deploy/gcp.sh
cd ../web
npm test
npm run lint
npm run build
cd ../console
npm test
npm run lint
npm run build
npm run smoke:example-packs
cd ..
git diff --check
git status --short
```

No test may be skipped silently. Record the exact counts, warnings, and build outcomes. The pre-existing npm audit report is not a passing security receipt; report it separately if still present.

**Step 2: Run targeted boundary searches**

```bash
rg -n "DOUG_EXAMPLE_PACK_TOKEN|X-Doug-Example-Pack-Token" api console web
rg -n "google\.cloud|storage\.Client|roles/storage" console web
rg -n "WorkOS|workos|session_auth|DOUG_API_TOKEN" api/doug/example_pack* console/app/example-packs console/lib/example-packs.ts
rg -n "dangerouslySetInnerHTML|signed_url|make_public|allUsers|allAuthenticatedUsers" api/doug/example_pack* console/app/example-packs console/components/example-pack*
git diff origin/main -- api/doug/session_auth.py api/doug/workos_client.py web console/app/api
```

Expected: purpose token appears only in API/console server/deploy/test/docs wiring; no console/web storage client; no Example Pack WorkOS/session dependency; no captured-content HTML injection/public URL helper; no auth/login diff.

**Step 3: Reconcile implementation to design**

Walk every success criterion and named failure in the approved design. If implementation differs, either fix code/tests or update the design with a specific verified reason. Do not average contradictory behavior. Confirm production mutation remains unexecuted.

**Step 4: Request a code-review pass and address findings**

Use `superpowers:requesting-code-review` locally, inspect the full `origin/main...HEAD` diff, independently reproduce every material finding, and apply only verified corrections with focused regression tests.

**Step 5: Final clean verification and commit**

Rerun the complete matrix after review fixes. If documentation changed:

```bash
git add docs api console web
git commit -m "docs: reconcile hosted Example Pack delivery"
```

Confirm `git status --short` is empty.

**Step 6: Push and open the PR**

```bash
git push -u origin feat/example-pack-hosted-workbench
gh pr create --base main --head feat/example-pack-hosted-workbench --title "Add hosted Example Pack adjudication workbench" --body-file /tmp/doug-example-pack-pr.md
```

The PR body must include scope, exact verification receipts, evidence limitations, the corrected `started_at`/membership completeness boundary, the npm audit status, and a conspicuous “not performed” list for bucket creation, IAM, audit logging, secret creation/binding, deploy, proxy smoke against hosted production, capture enablement, and production adjudication.

Stop at the PR. Do not merge or run the production rollout.
