# Hosted Example Pack Workbench Design

**Date:** 2026-08-10  
**Status:** Approved direction, corrected by verification pass  
**Base:** `origin/main` at `bc287501466d89da5b7f0d8e591bd4b0157e5e1d`  
**Scope:** Automatic dogfood-only risk capture, private hosted evidence storage,
operator adjudication, and scorecards in the existing IAM-gated `doug-console`

## Goal

Turn Example Pack v0 from a local capture substrate into a bounded hosted
dogfood loop:

```text
production Doug risk attempt
  -> immutable evidence pack
  -> deterministic cohort membership
  -> operator adjudication in doug-console
  -> evidence-complete scorecard by instrument revision
```

The first cohort covers only Doug's own installation and stable GitHub
repository ID. It must make unsupported findings, missing captures, partial
reads, failed reads, retries, and instrument changes visible rather than
selecting around them.

## Success criteria

The work is complete when:

- automatic production capture is impossible without an exact installation
  allowlist, repository allowlist, cohort ID, bucket, and expiration timestamp;
- only risk attempts are captured in the hosted cohort;
- every stored blob, pack, membership record, and adjudication is immutable and
  written with a create-only generation precondition;
- the first successfully persisted pack for one evaluation identity becomes the
  cohort member, while retry packs remain inspectable but cannot silently replace
  it;
- the API compares cohort members with completed production review jobs and
  refuses to publish a scorecard when a completed eligible job has no member;
- scorecards are partitioned by whole-instrument ID and never aggregate two
  application/model/prompt/runtime revisions;
- `doug-console` can inspect exact captured evidence, append or explicitly
  supersede adjudications, and render the cohort metrics and controls;
- zero-finding, partial, and failed member packs remain in the denominators;
- invalid, incomplete, expired, oversized, or unreachable evidence renders as
  unavailable, never as an empty or partial cohort;
- no WorkOS code, session route, tenant dashboard, public route, or database
  schema changes;
- the PR makes no production mutation. Bucket creation, IAM changes, audit-log
  configuration, capture enablement, and deployment require a separate explicit
  operator confirmation.

## Verification-pass corrections

The first approved sketch was directionally correct but incomplete. The
verification pass made these changes load-bearing:

1. **Retries need a selection receipt.** Example Pack correctly records each
   claimed attempt, but `score_packs` rejects duplicate eligible identities. A
   content-addressed pack directory alone cannot say which retry enters the
   scorecard. The hosted design adds an immutable, create-only membership record;
   first successfully persisted attempt wins.
2. **Stored packs do not prove complete capture.** Capture is best-effort by
   design. A storage outage could omit a difficult review and flatter the
   scorecard. The API must compare member identities with completed review jobs
   in PostgreSQL. Any missing completed job blocks the scorecard.
3. **Instrument revisions cannot share a headline.** The existing evaluator's
   identity includes `instrument_id`, but one scorecard call can still receive
   packs from different instruments. The service partitions member packs by
   `instrument_id`; the UI prints a separate N and metrics for each partition.
4. **Retention deletion is not atomic.** Cloud Storage lifecycle deletion can
   remove related objects at different times. The service validates the whole
   cohort and every content reference before rendering. Once lifecycle deletion
   makes it incomplete, the entire cohort becomes unavailable.
5. **Raw evidence deserves a purpose-scoped API secret.** The existing operator
   token remains unchanged. Example Pack endpoints use a separate
   `DOUG_EXAMPLE_PACK_TOKEN`, present only on `doug-api` and `doug-console`.

## Non-goals

- No tenant or WorkOS authorization for Example Packs.
- No capture for any installation or repository outside the exact dogfood
  allowlists.
- No intent-pack scorecard.
- No model, prompt, read-budget, score, band, check-run, or settlement change.
- No challenger, training, fine-tuning, promotion, or production model switch.
- No precision, recall, model-quality, or generalization claim from 20-30 dogfood
  examples.
- No public download, signed URL, email, Slack, or external report delivery.
- No editable pack, adjudication deletion, or timestamp-based conflict winner.
- No legal-hold workflow for tenant data. Capture remains prohibited for data
  subject to a hold.

## Decision 1: hosted architecture uses the existing console/API seam

The existing console is already a separate Cloud Run service deployed with
`--no-allow-unauthenticated`, reached through `gcloud run services proxy`, and
run as `doug-console-sa`. The browser never receives an API credential; the
Next server calls `doug-api` with a server-side token.

Example Packs follow that same shape:

```text
Doug worker on doug-api
  -> GcsExamplePackStore
  -> private Cloud Storage bucket

Andrew -> gcloud run services proxy -> doug-console
  -> server-side X-Doug-Example-Pack-Token
  -> operator-only Example Pack API
  -> validated bucket reads / append-only adjudication writes
```

`doug-console-sa` receives no Cloud Storage role. `doug-api-sa` owns the
storage adapter and the Pydantic integrity checks. This avoids duplicating
canonical JSON, hash validation, adjudication resolution, and scorecard rules in
TypeScript.

## Decision 2: explicit cohort contract

Hosted capture requires all of these settings:

```text
DOUG_EXAMPLE_PACK_CAPTURE=1
DOUG_EXAMPLE_PACK_BUCKET=<private bucket name>
DOUG_EXAMPLE_PACK_COHORT=<immutable cohort slug>
DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT=<UTC RFC3339 timestamp>
DOUG_EXAMPLE_PACK_INSTALLATION_IDS=<comma-separated numeric IDs>
DOUG_EXAMPLE_PACK_REPOSITORY_IDS=<comma-separated numeric GitHub repository IDs>
DOUG_EXAMPLE_PACK_CAPTURE_UNTIL=<UTC RFC3339 timestamp>
DOUG_APPLICATION_REVISION=<verified git commit SHA>
DOUG_EXAMPLE_PACK_ADJUDICATOR=andrew
```

Missing, malformed, ambiguous, or closed-window configuration disables hosted
capture and emits one bounded diagnostic. A closed capture window does not hide
or disable the stored cohort: adjudication and results remain available until
retention removes required evidence. Local `DOUG_EXAMPLE_PACK_DIR` capture remains
supported. Local-directory and bucket configuration are mutually exclusive;
setting both is a named configuration error contained by the existing
best-effort boundary.

The first production configuration contains exactly Doug's dogfood installation
and `drewjst/doug`'s stable numeric repository ID. Matching only a repository
display name is forbidden. A second installation or repository requires a new
reviewed configuration change; it cannot arrive through a request.

The explicit start and end timestamps make every API instance construct the
same cohort manifest; server clocks never race to define cohort identity. The
cohort manifest is immutable:

```yaml
schema_version: example-pack-cohort-v0
cohort_id: <slug>
capture_started_at: <UTC>
capture_until: <UTC>
installation_ids: [<dogfood installation>]
github_repository_ids: [<stable drewjst/doug id>]
attempt_kinds: [risk]
finding_cap: 3
raw_retention_days: 90
application_revision: <verified commit SHA>
```

Capture eligibility is checked before scope construction and request
canonicalization. A non-allowlisted tenant pays no capture CPU, memory, storage,
or latency.

## Decision 3: storage and immutability

One regional Standard Cloud Storage bucket in `us-central1` stores private
dogfood evidence. It uses:

- uniform bucket-level access;
- enforced public-access prevention;
- Google-managed default encryption at rest;
- a 90-day delete lifecycle for the cohort prefix;
- Cloud Audit Logs Data Read and Data Write logging enabled before capture;
- no object versioning, public ACL, signed URL, or browser-direct access.

Google documents that public-access prevention blocks `allUsers` and
`allAuthenticatedUsers`, that uniform access removes per-object ACLs, and that
default Cloud Storage encryption protects content at rest. Data Access audit
logs are disabled by default and therefore are an explicit rollout prerequisite,
not an inferred property.

Bucket object names are:

```text
cohorts/<cohort>/cohort.json
cohorts/<cohort>/blobs/sha256/<sha256>
cohorts/<cohort>/packs/sha256/<pack_hash>.json
cohorts/<cohort>/members/sha256/<eligibility_hash>.json
cohorts/<cohort>/adjudications/sha256/<adjudication_id>.json
```

Every write uses `if_generation_match=0`. Cloud Storage defines generation
match zero as create-only. On a precondition failure, the adapter reads the
existing object: identical canonical bytes are an idempotent success; different
bytes at the content address are an integrity failure. No runtime identity gets
overwrite or delete permission.

`doug-api-sa` receives `roles/storage.objectCreator` plus
`roles/storage.objectViewer` on this bucket only. Creation and IAM binding live
in privileged setup, not ordinary API or console deploys. Lifecycle deletion is
the only automatic deletion path. Manual purge is a destructive operator action
outside this implementation.

The service validates all canonical bytes, self-hashes, referenced blob hashes
and sizes, membership links, and adjudication links before serving a cohort.
Object listing is strongly consistent, so a successful create followed by a
list cannot legitimately omit the new object. More than 500 pack objects fails
the cohort as too large; no endpoint returns a fabricated first page.

## Decision 4: capture remains advisory and bounded

The existing worker context and reader request seam remain the capture point.
The hosted adapter changes storage, not scoring.

For each eligible risk attempt:

1. construct the same exact pack and blob bytes v0 already defines;
2. write blobs with create-only preconditions;
3. write the immutable pack only after every referenced blob succeeds;
4. attempt the immutable cohort-membership claim;
5. return the existing reader result regardless of capture outcome.

The total hosted-storage budget is five monotonic seconds per attempt, including
safe conditional retries. When the budget expires, capture stops, prints one
bounded diagnostic with run ID and error class, and leaves any already-created
content-addressed blobs as harmless unreferenced objects for lifecycle cleanup.
It never changes score, band, findings, fallback selection, check-run output,
worker job status, or retry behavior.

`DOUG_APPLICATION_REVISION` is set only when the deploy source is a verified
clean commit. Cloud Run's `K_REVISION` remains the runtime revision. A dirty
manual deploy records a null application revision and is ineligible for the
hosted cohort; it cannot masquerade as the named commit.

## Decision 5: deterministic membership and completeness

The evaluation identity is canonical JSON over:

```text
instrument_id
installation_id
github_repository_id
pull_number
admitted_base_sha
admitted_head_sha
```

Its SHA-256 is the membership object name. The first successfully stored pack
creates that object with `if_generation_match=0`; the record contains the exact
pack hash and run ID. A retry that loses the precondition remains inspectable as
a non-member attempt and cannot replace the denominator row.

First-persisted means failed, partial, captured-with-zero-findings, or captured
with findings. It never means first successful model answer.

Membership does not prove capture completeness. `review_jobs.enqueued_at` cannot
be the cohort boundary: Doug deliberately rewrites it when a failed job returns
to the back of the queue. The API instead forms the durable completed-job set as
the union of:

- completed allowlisted jobs whose terminal attempt's `started_at` falls in
  `[capture_started_at, capture_until)`; and
- completed allowlisted jobs whose immutable job ID is named by a cohort
  membership record, even when their terminal retry completed after the window.

Membership records therefore carry `review_job_id` as well as the exact pack
hash and run ID. The API compares the completed-job set's
`(installation_id, github_repo_id, pr_number, base_sha, head_sha)` identities with
stored members. This preserves a job first captured inside the window even when
its terminal retry starts later, without changing queue ordering or adding a
database column. The response carries:

- completed eligible job count;
- member count;
- exact missing completed-job identities;
- extra member identities with no durable completed job;
- invalid or duplicate membership records.

Any missing completed job, invalid record, missing reference, or duplicate live
adjudication head makes every scorecard unavailable. Extra members remain in the
attempt inventory and are labeled; they do not erase a successfully captured
reader attempt.

This is a completed-job coverage receipt, not proof that every pre-reader worker
failure was captured. One narrower limitation also remains explicit: without an
attempt-history table, an earlier failed attempt whose evidence write also failed
cannot be reconstructed if its terminal retry starts after the capture window.
The rollout drains the allowlisted review queue before cohort closure to prevent
that boundary from silently selecting a row out. The console states both limits
literally.

## Decision 6: API surface

All routes require `X-Doug-Example-Pack-Token` checked against the separate
`DOUG_EXAMPLE_PACK_TOKEN`. `DOUG_API_TOKEN` does not authorize them. The API
writes the fixed configured adjudicator value (`andrew` in the first cohort);
the browser cannot claim a different human identity. This is a capability-backed
operator assertion, not proof that Cloud Run authenticated a named end user.

```text
GET  /v1/example-pack-cohorts
GET  /v1/example-pack-cohorts/{cohort_id}
GET  /v1/example-pack-cohorts/{cohort_id}/packs/{pack_hash}
POST /v1/example-pack-cohorts/{cohort_id}/packs/{pack_hash}/findings/{finding_id}/adjudications
GET  /v1/example-pack-cohorts/{cohort_id}/results
```

The list endpoint returns manifest and availability only. Cohort detail returns
member/non-member attempt summaries, capture-completeness receipt, adjudication
coverage, and scorecards partitioned by `instrument_id`. Pack detail returns the
validated pack, exact evidence diff, exact selected raw output, canonical request
dictionary, and effective adjudication for each finding.

The results endpoint returns deterministic JSON containing cohort manifest,
completeness receipt, per-instrument scorecards, raw null/spam controls, and the
ordered member inventory. It reports yield and unsupported burden, never
precision or recall. It has no pass/fail model-quality verdict.

Adjudication POST accepts a disposition, evidence receipts, verifier receipts,
and the exact current adjudication ID the browser observed. Conclusive
dispositions (`verified_actionable`, `verified_accepted_nonactionable`, and
`disproved`) require at least one evidence or verifier receipt. `unknown` may be
recorded without one.

Corrections are serialized under a PostgreSQL advisory lock derived from
`(cohort_id, pack_hash, finding_id)`. Inside that lock the server re-reads the
current live head, rejects a stale expected ID with HTTP 409, builds one new
append-only adjudication with `supersedes=<current>`, and writes it create-only.
No table or migration is added. Timestamp order never resolves a fork.

Named failures map as follows:

- unknown cohort: 404;
- capture window closed: reads and adjudication remain available, capture stops;
- evidence service misconfigured: 503;
- invalid, incomplete, or retention-expired cohort: 409 with a bounded reason;
- more than 500 packs: 413;
- stale adjudication form: 409;
- token missing or wrong: 403;
- unknown cohort, pack, or finding: 404.

No response includes a credential, GCS URL, signed URL, bucket name, exception
body, or storage-client detail.

## Decision 7: doug-console workbench

The console adds an `Example Packs` navigation item and two force-dynamic,
server-rendered routes:

```text
/example-packs
/example-packs/[packHash]?cohort=<cohort-id>
```

The cohort page leads with four facts:

1. capture status and expiration;
2. completed-job capture coverage;
3. adjudication coverage;
4. one scorecard per instrument revision.

It then lists member attempts, followed by explicitly labeled non-member
retries. Zero-finding, partial, and failed rows remain visible. A scorecard that
is blocked by missing evidence renders the missing identities and no metric.

The pack page shows:

- repository, PR, admitted base/head, run ID, capture time and status;
- whole-instrument ID and manifest;
- coverage, usage, latency and failure/fallback receipts;
- parsed findings and their effective dispositions;
- collapsed exact request, evidence diff, and raw selected output;
- an adjudication form with disposition, evidence kind, locator, detail, optional
  SHA-256, and the observed current adjudication ID.

The browser never gets either server token. Reads and writes use the existing
server-only console API module. The adjudication form is a Next server action;
same-origin checks and the server-held token prevent a cross-origin browser POST
from becoming an evidence write. React text rendering escapes captured source
and model output. There is no `dangerouslySetInnerHTML`, external script, remote
font, blob download, or outbound link built from captured content.

The console preserves its standing honesty rules: no fixture fallback, no rate
without N, empty distinct from unavailable, and no partial results after an API
error.

## Decision 8: retention, deletion, audit, and incident response

Example Pack evidence contains source diffs, exact model request dictionaries,
and model output. It is classified as private source evidence even though the
first allowlisted repository is public.

- **Region:** `us-central1`, matching the services.
- **Encryption:** Google-managed default encryption at rest and TLS in transit.
- **Retention:** object lifecycle deletion at age 90 days for the cohort prefix.
- **Deletion:** neither runtime service account can delete. Lifecycle performs
  ordinary expiry. Manual early purge requires a separately approved privileged
  operator action.
- **Legal hold:** the dogfood cohort asserts no legal hold. If a hold becomes
  applicable before lifecycle eligibility, capture stops and a privileged
  operator places temporary holds on every cohort object before suspending the
  lifecycle rule. Suspending a lifecycle rule alone is insufficient because a
  previously eligible delete can still execute later. Capture is prohibited for
  any corpus that needs a product-grade legal-hold workflow.
- **Audit:** Cloud Storage Data Read and Data Write audit logs are enabled before
  capture. The rollout records the IAM policy receipt and a read/write log query.
- **Incident response:** disable the capture flag, redeploy the API, revoke the
  bucket roles from `doug-api-sa`, preserve logs and objects, and only then decide
  whether a separately approved purge is warranted.

Lifecycle deletion is asynchronous and not cohort-atomic. Once any required
object disappears, validation makes the whole cohort unavailable. The UI never
continues with surviving rows and calls them the cohort.

## Test strategy

Tests encode the reasons these boundaries exist:

1. **Eligibility:** non-allowlisted installation/repository, intent attempt,
   malformed expiry, expired cohort, dirty application revision, and ambiguous
   local/bucket configuration perform zero storage calls.
2. **Storage:** create-only generation preconditions, canonical-byte idempotency,
   collision refusal, checksum verification, bounded retries, and whole-capture
   time budget.
3. **Failure isolation:** storage construction, blob, pack, and membership
   failures cannot change the reader return, worker result, verdict, or check run.
4. **Membership:** first persisted failed/partial/zero/finding pack wins; later
   retries remain non-members; no success-only selection is possible.
5. **Completeness:** a terminal attempt started in-window without a member blocks
   all scorecards; a completed membership-linked retry remains in-scope after the
   window; an extra member is labeled; invalid references and duplicate
   identities fail the cohort.
6. **Instrument partition:** two instrument IDs produce two scorecards with
   separate N and can never appear in one aggregate.
7. **API authorization:** the existing operator token cannot reach Example Pack
   routes; only the purpose-scoped token can. Wrong/missing tokens are constant
   403 responses.
8. **Adjudication:** conclusive writes require receipts; stale expected heads
   409; correction names the exact superseded ID; concurrent requests cannot
   create two live heads.
9. **Console honesty:** malformed nested data, API failures, missing evidence,
   pack caps, empty cohorts, partial/failed/zero rows, and multiple instruments
   render their exact states with no fallback.
10. **Output safety:** captured HTML/script text renders as text; no secret or
    bucket location enters errors or page source.
11. **Deploy contract:** bucket privacy settings, exact bucket-level roles,
    distinct secret distribution, allowlist, capture expiry, application
    revision, and absence of WorkOS changes are pinned by shell-source tests.

The delivery gate is the full API suite, Ruff, web and console tests, both
linters, both Next production builds, deploy-script syntax check, and a local
browser smoke over a checked-in synthetic cohort. The smoke proves list,
drilldown, adjudication, correction, blocked scorecard, and complete scorecard
states without GCP credentials.

## Rollout boundary

The implementation PR may add code, tests, documentation, dependency locks, and
deployment/runbook wiring. It must not create a bucket, modify IAM, enable Data
Access logs, create or bind a secret, deploy a revision, or enable capture.

After merge, a separate production run requires explicit confirmation and these
receipts in order:

1. private bucket location, uniform-access, public-prevention, lifecycle, and
   encryption configuration;
2. exact bucket IAM policy showing only the approved runtime roles;
3. Data Read/Data Write audit-log configuration;
4. purpose-scoped secret creation and service bindings;
5. dogfood numeric installation/repository allowlist, fixed adjudicator, and
   explicit capture start/expiration;
6. clean application revision and candidate deployment;
7. one synthetic or controlled automatic pack, immutable-object verification,
   and audit-log write receipt;
8. console proxy smoke showing that pack and one append-only adjudication;
9. capture enabled for the bounded cohort window;
10. the allowlisted review queue observed drained before the capture window is
    closed, so no failed in-window attempt can become an unknowable post-window
    terminal retry.

The initial target is 20-30 unique member identities. Reaching the target does
not validate the model. It produces a reviewable dogfood cohort and a measured
actionable-yield/unsupported-burden result for the captured instrument revisions.

## Rejected alternatives

- **Local-only workbench:** preserves the old storage boundary but does not make
  automatic production dogfood capture or the hosted console useful.
- **Browser upload:** makes the operator transport source data manually and can
  select around failed attempts; it cannot prove denominator completeness.
- **Console reads GCS directly:** duplicates Python's canonical hash and
  adjudication rules in TypeScript and gives `doug-console-sa` raw bucket access.
- **Store packs in PostgreSQL:** puts large source/request/output blobs in the
  operational ledger and couples review availability to evaluation retention.
- **Pick latest or successful retry:** flatters the scorecard and contradicts the
  existing append-only attempt identity.
- **Aggregate instruments:** turns deployment/model/prompt changes into an
  uninterpretable average.
- **Serve surviving objects after lifecycle deletion:** exposes a partial cohort
  without saying which evidence disappeared.

## Primary platform references

- [Cloud Storage request preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions)
- [Cloud Storage consistency](https://docs.cloud.google.com/storage/docs/consistency)
- [Uniform bucket-level access](https://docs.cloud.google.com/storage/docs/uniform-bucket-level-access)
- [Public access prevention](https://docs.cloud.google.com/storage/docs/public-access-prevention)
- [Cloud Storage object lifecycle management](https://docs.cloud.google.com/storage/docs/lifecycle)
- [Cloud Storage audit logging](https://docs.cloud.google.com/storage/docs/audit-logging)
- [Enable Data Access audit logs](https://docs.cloud.google.com/logging/docs/audit/configure-data-access)
- [Standard Cloud Storage encryption](https://docs.cloud.google.com/storage/docs/encryption/default-keys)
