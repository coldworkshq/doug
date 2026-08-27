---
title: Doug owns a derived memory store, and the store fills the provider slot ADR-0006 left empty
status: proposed
date: 2026-08-26
amends: ADR-0006
---

## Context

ADR-0006 gave Doug its own provider interface for recorded decisions —
`IntentDoc` at `api/doug/intent.py:61` — and one provider,
`intent_providers.fetch`, that parses ADR-format markdown from the repository
under review. It left a second slot deliberately empty: a lema-backed
provider, "unimplemented, until lema exposes decisions with status and repo
scoping." The reason was a measured failure mode, not taste: lema's hosted
search had no status filter, so `d_81e789` ("LLM-assisted scoring — rejected")
would have reached the reader after ADR-0004 overturned it, and the reader
would have flagged Doug's own shipped reader as a deviation.

Three things changed between 2026-07-30 and today:

1. **lema is retired as a product.** The 2026-08-19 design pass (Doug Product
   Map, workflow `wf_cf0e0ae0`, 43 red-team findings adjudicated, 7 fatal all
   cured) merged lema into Doug as schema and ledger semantics only. The brand,
   the standalone apps, `lema verify`, the human write verbs, and the BIND tier
   are dropped. No lema data row ever migrates; backfill comes from repositories.
2. **The judgment queue is dead by ruling.** Andrew clicked lema's accept
   buttons without reading and the queue died as ceremony; lema's own ADR-0135
   (proposed 2026-06-29, never signed) had already proposed removing the inbox.
   The law that replaces it: **commitment is the decision.** A merged pull
   request or a committed document is the record of having decided; nobody
   enters a decision, and no queue adjudicates one.
3. **Prose-derived records have a measured precision problem.** The red team
   put lema's prose-only extraction at 0.463 precision (finding 22) and named
   session text an attacker-writable surface (finding 28). A store that treats
   every source as equal feeds the reader what it should never see.

Andrew signed the store's license and home on 2026-08-25: the store is
**private**, its conformance fixtures are **open**, and by the language law
(Go = store and spine, Python = anything that calls a model, TypeScript = web
only) it is its own Go repository, `coldworkshq/memory-store`, extracted from
lema's Go backend (`apps/api`: chi, pgx, goose; 782 Go files, 73 SQL
migrations). The DB-free third of that extraction — ADR frontmatter parsing,
verdict types, source citation, `check_decided` — already exists as the
standalone `lemahq/lema-mcp` module with zero pgx imports. Stage 1 is a port,
not a build.

This record is one of three that Stage 0 of the integration plan requires
before any of that code may exist (rule R2, paper gates code). The other two
are ADR-0023 (how a merge feeds the store) and ADR-0024 (what the store rides
on). The plan itself lives at `coldworkshq/coldworks` `docs/integration-plan.md`;
its per-item build order is `docs/build-orders/memory-store.md` there. This
record was red-teamed on 2026-08-26 (six lenses, 60 findings filed, 38
adjudicated by independent refuters, 11 standing); the cures are in the text
below, and the funnel is recorded in the pull request.

## Decision

Everything in this section is a contract for code that does not yet exist.
Where the text says the store *refuses*, *pins*, or *fails CI*, that names a
Stage-1 deliverable in the build order (MS-2 through MS-9), not a mechanism on
disk today. The Decision is what those deliverables must satisfy.

### The store

Doug runs a memory store in a second Postgres schema, `memory`, on the same
Cloud SQL instance as the outcome ledger. The `doug` schema stays Python-owned
and single-writer; the `memory` schema is Go-owned and single-writer, with
row-level security keyed on a per-request tenant setting. **No foreign key
ever crosses the schema boundary.** The two join on frozen natural keys —
`(github_repo_id, pr_number, merge_commit_sha)`, the three-column identity
migration 17 already calls stable and issue #218 rules is the only series key.
`installation_id` is stored on every row as operational plumbing and is never
part of a key: the doug schema is never rewritten for tenancy, and after the
organization move its ledger holds the same repository's history under two
installation ids (150424894 and 153075663, per the ADR-0017 amendment). A join
that keyed on the current installation id would silently miss every pre-move
merge.

Tenancy is three tables, all Go-owned:

- `memory.tenants(id, account_id)` — the internal id every memory row keys on,
  anchored on the GitHub account id (user or organization).
- `memory.tenant_installations(tenant_id, installation_id UNIQUE, valid_from,
  valid_to)` — every installation id a tenant has ever held. A reinstall is
  one new row; nothing is rewritten and every historical id still resolves.
- `memory.tenant_repos(tenant_id, github_repo_id, valid_from, valid_to)` — the
  mutable link that mirrors doug's own `installation_repos`
  (`store.py:242-250`). A repository transfer between accounts is one row
  change on this table; the memory rows keep the tenant they were written
  under, and the read view and the RLS policy resolve the *current* tenant
  through the link.

The move to `coldworkshq/doug` (#227, migration 17) is the executed precedent:
an App ownership transfer preserves installation ids (#226 step 2), and it was
the *repository* transfer that re-homed the repo under a different installation
and account. Both cases are one row on this schema.

**Tenants have a producer.** `doug-api` is the only party that sees
installation webhooks. It emits `tenant.installed` and `tenant.uninstalled`
events keyed on `installation.account.id` (from the signed payload, or from
`GET /app/installations/{id}` through the App JWT) carrying the installation
id and the repository ids it covers. The store refuses any event whose
installation has no tenant rather than creating an anchorless row. These
provisioning events are part of the frozen wire, so MS-3 lands with or before
MS-2's first migration, not after it.

**Isolation follows coldworks invariant 4**, which this codebase family has
already proven live and regressed twice (`coldworks/db/001_init.sql:259-264`,
`002`, `004`, `005`): the tenant setting is transaction-scoped
(`set_config(..., true)`, never a session `SET`); every `memory.*` table is
`ENABLE` **and `FORCE` `ROW LEVEL SECURITY`**, because the table owner bypasses
RLS otherwise; the runtime role is separate from the migrator and has no
`BYPASSRLS`; any `memory.v*_` read view is created `WITH (security_invoker =
true, security_barrier = true)`; and a catalog test (ported from coldworks'
`test_current_views_respect_rls`) fails CI on any table or view that breaks
those rules. The store's own drains read across tenants under a named policy,
never by unsetting the tenant.

The store holds no model client. Embedding and synthesis are `doug-api`
endpoints, `/internal/embed` and `/internal/synthesize`, called from Go over
the internal wire and accepting only the store's service identity — never the
operator header `DOUG_API_TOKEN`. Stage 1 ships lexical search only and every
response carries `degraded: true` until the hybrid path exists, so the search
contract does not change when the ranking does.

### The wire, frozen

The provider slot is filled by an internal provider that reads the store over a
wire whose shape is this record's contract. The wire is an authenticated IAM
surface (mechanism in the build order, not here), and the registry binds each
producer identity to the event types it may emit.

- **Reads take a status set and a force set, and return live values of both.**
  A list or get call names the statuses and the forces it will accept; a
  record outside either set is absent from the response, not present with a
  warning. The status vocabulary is the ADR frontmatter's: `proposed |
  accepted | superseded | deprecated | rejected`. The intent provider reads
  `{accepted} × {settled}`, and the open conformance fixtures pin that an
  `accepted` + `advisory` record is absent from that read. That server-side
  filter, not a Python convention, is what makes "by construction" true.
- **The record shape is `IntentDoc`'s six fields** — `{id, title, body,
  status, date, ref}` — plus `force`. `ref` is provider-derived from
  provenance (`pr#N@sha`, `commit:sha`, `path@sha`), the same way the file
  provider derives it from a path today. `select` and the reader are
  unchanged; the store provider maps provenance to `ref` and passes the force
  set explicitly, because pydantic drops an unknown key silently and an
  implicit filter is no filter.
- **Every record carries exactly one provenance**, a closed sum type, mandatory,
  and every variant carries `github_repo_id`:
  `pr {github_repo_id, pr_number, merge_sha}` ·
  `commit {github_repo_id, sha}` ·
  `doc {github_repo_id, path, sha}` ·
  `session {harness, external_session_id, seq}` (keyed as lema's
  `agent_sessions` is, `UNIQUE (harness, external_session_id)`).
  A record with no provenance is refused at write. Force is a pure function of
  the variant: `pr`, `commit`, and `doc` are settled-eligible; `session` caps
  at `advisory` by construction. Pull-request threads, issues, and discussions
  have **no producer in v1**; admitting one registers a new variant. Variants
  are registry rows and adding one is additive; the envelope's *fields* are
  what is frozen (ADR-0024).
- **`occurred_at` is GitHub-clocked, never git-clocked.** For `pr` it is
  `pull_request.merged_at` from the signed webhook. For `doc` and `commit` it
  is the `merged_at` of the pull request that brought the sha to the default
  branch, else the push delivery's `repository.pushed_at` — never
  `head_commit.timestamp`, which is the committer's own clock. For `session` it
  is the capture time, labeled as such. Every display, recency, ranking, and
  supersedence decision keys on `occurred_at`; `recorded_at` is bookkeeping
  and orders nothing. The store refuses `occurred_at` later than `recorded_at`
  plus a small skew allowance, and the conformance artifact carries a
  future-dated fixture that must be rejected.
- **One source per record, links between records.** A record is derived from
  exactly one source in exactly one channel. A second channel that reaches the
  same subject writes a *link fact* on the existing record; it never mints a
  second settled record and never merges into the first. The wire carries
  `links[]`, so "the derived record cites both" (below) means one provenance
  plus one link. In particular, a diff-derived commitment whose subject a
  document at HEAD already declares is written as a link on the doc record.

The wire contract, the event envelope (ADR-0024), and the status-predicate
fixtures ported from lema are published as an **open conformance artifact**.
That is the public half of the 2026-08-25 ruling. The store's code is the
private half. The artifact's venue and case format are chosen at Stage 1
(MS-1), when the fixtures are transcribed from lema
`apps/api/internal/retrieval/decision_status_db_test.go`; the source text of
lema's status predicate (its ADR-0083) is at lema git
`b2a9ffed:docs/adr/0083-decision-status-on-the-retrieval-wire.md` and
`.lema/decisions.jsonl.retired-2026-07-20:77`. Publication is a done-item of
coldworkshq/coldworks#20.

### Force tiers

Lifecycle status says whether a decision is in effect. Force says how much the
record's *source* entitles it to be believed. lema kept the two axes separate
on purpose (`internal/knowledge/tier.go:3`: "Lifecycle state is intentionally
not part of tier derivation"), and that separation ports. The tiers themselves
do **not** port verbatim: lema's five (`inferred < captured < settled-by-merge
< adjudicated < authored`) rank interactive humans at the top, which is the
judgment queue by another name. The mapping is `settled-by-merge → settled`,
`captured` and `inferred → advisory`, `adjudicated` and `authored → dropped`;
`historical` and `contested` are new pure functions with table-driven tests
(Stage 1 and Stage 3 respectively). Four tiers:

| Force | Source | Reaches the reader as intent |
|---|---|---|
| `settled` | A commitment: a merged pull request, or a document at HEAD under the repository's own merge governance. Settlement *is* the accept. | Yes, when status is `accepted`. |
| `advisory` | A non-commitment: an agent session. Cited, labeled, never promoted on its own. | No. Surfaced to humans and agents with its citations. |
| `historical` | A settled record a later commitment on the same subject superseded. Recency supersedes; nothing is deleted by supersedence. | No. |
| `contested` | A settled record whose outcome verdict demoted it — the merge that settled it was reverted or hotfixed within the ledger's window. Machine-demoted, never hand-demoted. | No. Surfaced as "settled on DATE, reverted since — worth reopening." |

The governing record on a subject is the most recent `settled` record by
`occurred_at`. At equal `occurred_at`, `doc` beats `pr` beats `commit`, then
the lower `idempotency_key`. `historical` and `contested` records never
govern. `advisory` records never govern and are always cited.

**Session-provenance records cap at `advisory`.** An agent may record a
decision mid-session; that is capture, not force. The record surfaces at once,
labeled "recorded, not settled." The only path to `settled` is the correlator
matching the session to a merged commitment, at which point the derived record
carries the commitment as provenance and the session as a link. A record born
`settled` from session text is forbidden — the session records intention, and
the ledger records outcome. A session that ends without a commitment leaves its
captures `advisory` forever, which is the correct weight for "tried and
abandoned in session S."

### What may write, and what it must carry

- **A self-declaring file is parsed, never judged.** ADR frontmatter goes
  through the mechanical parser (lema `internal/adr`, ported). No model
  assigns a status to a document that states its own.
- **Every derived record carries verbatim evidence spans** into its source,
  each capped in length (lema's precedent is 240 runes). A `ruled_out` verdict
  requires a quote anchor; a record without one is refused at write, not
  flagged at read. A settled record's spans lie in the commitment, never in a
  linked session.
- **Authority is the repository's own merge governance.** A commitment counts
  when it landed under that governance, whoever authored or merged it — a
  maintainer-merged contributor pull request is sanctioned by definition, as
  lema's settlement record already ruled (`0056:31-34`). "Drive-by" means a
  non-commitment source or an unregistered producer, which caps at advisory or
  is refused. `actor_kind` and the on-behalf-of field port from lema's events
  table to classify the store's *producer*, never the GitHub principal.
  Retraction is a later commitment: a status flip or deletion at HEAD makes the
  record `historical`; a revert in-window makes it `contested`; an in-context
  dismissal is a `decision.dismissed` event (schema in ADR-0024) that records a
  `settled → historical` transition with its actor and surface.
- **The deriver is an instrument, not a service.** The graded-reviewer roster
  is the `verdicts.source` namespace the neutral-grader lane grades
  (pre-registration §7, unit `(reviewer, PR)`); the deriver writes under
  `source = 'deriver'` with the external-tier shape `save_external_review`
  already uses for score-less reviewers. Its ledger grade is the share of its
  settled records demoted to `contested`, reported per source and per
  `batch_id` — that aggregation is Stage 3. Until then its only grade is the
  derivation eval, which **will be pre-registered in a named file** under
  `docs/design/`, bars locked and Andrew-signed before the first graded
  derivation (60–100 hand-graded derivations against fabrication,
  faithfulness, and yield bars, plus an injection goldset of planted
  `DECISION:` text in merged diffs). A run that does not cite that file's hash
  does not count toward the Stage 2 gate, and no tenant-visible record exists
  until it passes. Backfill is batch-stamped and runs only afterward.

### Who may read

Tenant reads are allowlist-first. A public tier — the static, read-only
corpus the `check_approach` door already serves, built from public
repositories only and never from the tenant view — is admitted only after
the ported ADR-0095 labeled fixtures pass (22 non-goal false positives muted,
19 rulings retained), and `check_decided` is never sold before that. A
dedicated free-tier instance is bought by a measured funnel signal, never
assumed. The GTM fork this rides on was deferred on 2026-08-25 and is not
reopened by this record.

The neutral check run (ADR-0010) gains a contradiction section that cites the
governing record, on the existing surface — which since ADR-0014 includes the
sticky-comment mirror; the section's spans pass through the same
neutralization as the ADR-0007 deviation section. It informs; it never changes
the conclusion and never blocks. It rides the deviation instrument ADR-0010
records as failing its positive control, so it stays advisory until that
control passes (Gate B).

### What coldworks reads

The coldworks M6 normalizer's input is a span dump (`normalizer.py:1-5`, "it
reads spans, never IR"; `SOURCE_FORMAT = 'otel.span'`), and what it normalizes
is Doug's *review judgments* — Andrew's 2026-08-08 ruling made Doug's receipts
the answer key, "the same judgments recorded both ways," with density measured
over findings. The recovery surface is therefore **a versioned read view over
the `doug` schema's verdicts and findings, Python-owned, or an additive
`review.judgment` event family emitted by Python** — never the memory envelope
and never a decision view. A decision-shaped view would fail M6 loudly
(`NormalizeError` on a non-span input), not vacuously. Whether coldworks should
*also* ingest decision records is a separate surface, not decided here, and is
marked new if anyone proposes it. The integration plan's §1 still says "memory
schema" and disagrees with its own build order §B3; that drift is filed as
coldworkshq/coldworks#22 rather than averaged.

## Rejected

**Reading from lema's hosted store.** ADR-0006's reason stands — no status
filter — and a second reason now joins it: the product is retired and
`lema-prod0` is on a decommission checklist.

**Migrating lema's rows.** Every record in the store must trace to a
commitment in a repository the tenant connected. lema's rows trace to a
workspace, an accept click, or a seed; the ceremony that produced them is the
one this design retires. Backfilling from the repositories reproduces every
record that was ever real and none that were not.

**A `store/` directory inside this repository.** One CI, one WIF binding, one
handoff — genuinely simpler. The license ruling forbids it: the store is
private and Doug is public, and a license boundary that runs through a
directory is not a boundary. The open conformance artifact keeps the contract
public without the code.

**A human review-and-accept queue.** It was tried, as lema, by the person who
would have to run it, and it died as ceremony. In-context dismissal survives as
an action — a `decision.dismissed` event — never as a queue.

**Letting a model assign status.** At 0.463 precision on prose, a model that
statuses records produces the exact confident false finding ADR-0006 exists to
prevent, at scale. Self-declaring files are parsed; derived records carry
evidence spans; force is derived from provenance by a pure function.

**Session records born `settled`.** A session is intention. Promoting it
without a correlated commitment launders assertion into fact — the mem0
failure mode — and the session lane's own design
(`docs/design/session-lane/design.md:157`) says asserted material "decays
unless corroborated by observed commitment."

**A model client inside the Go store.** lema's `go.mod` imports
`anthropic-sdk-go` and `genai`; they stay behind. A store that calls a model
turns every embedding-model swap into a store release, and the language law
exists so that the thing that calls a model is the thing that is graded.

**Cross-schema foreign keys.** They couple two writers, make an organization
transfer a cascade instead of one row, and put the memory schema's integrity
in the hands of a migration framework it does not run under.

**Keying rows or tenancy on `installation_id`.** GitHub reissues it on
reinstall, a repository transfer re-homes a repo under another one, and the
doug ledger already holds one repository under two of them. Issue #218 rules
that only `github_repo_id` defines a series; this record obeys it.

**A fork or bot gate on the derive path.** Merges are never gated on
author: `_record_merge` applies none by ruling (pre-registration §2.4), and a
merge under the repository's governance is the tenant's own commitment
whoever opened it. Spend is bounded by the tenant's own merge rate and the
reader's existing cap (ADR-0023), not by refusing to look.

## Consequences

- ADR-0006's "lema-backed provider ... unimplemented" clause is retired. Its
  other rulings stand unchanged: Doug owns the provider interface and the
  contract; Doug's own decisions live in this directory, which is now one
  channel into the store rather than the only source; repositories without an
  ADR directory get an inert feature, not an error. On signing, the same commit
  that flips this record to `accepted` rewrites ADR-0006's banner from the
  conditional form to an unconditional one.
- The wire contract is frozen at Stage 1's first migration. Changing a field is
  not a refactor; it reopens Stage 0 and needs a new signature (integration
  plan rule R9). Registering a new provenance variant or event type is
  additive and does not.
- The reader's feed narrows to `status = accepted` **and** `force = settled`,
  filtered server-side. Until Stage 2's eval passes, the only settled records
  are the ones this directory's parser produces today, so the reader's behavior
  does not change at Stage 1.
- Stage 1 exits when the intent provider reads from the store with correct
  status **and force** filtering, a dual-run parity oracle against
  frontmatter-at-HEAD shows zero drift, and the supersedence-freshness bar from
  the build order is met. All three are pre-registered here; the oracle's
  runner, population, and tolerance are named in the build order.
- A second writer joins the production ledger. Gate A of the integration plan
  — alert policies, one observed outcome cycle, one reconciler execution — and
  Gate B's positive-control and derivation-eval legs must be green first (the
  interview leg is deferred with its kill criterion not retired). As of
  2026-08-26 Gate A is entirely red, and the startup reconciler has enqueued
  zero windows in 102 runs because `pulls.get` returns no `merge_commit_sha`
  for this repository's merges — it has never healed anything.
- Every read pays for a transaction-scoped tenant setting and a forced RLS
  check. That is the price of putting tenant isolation in the database rather
  than in every caller, and it is only a price if `FORCE` is on.
- Evidence spans persist verbatim and capped. A registered `record.redacted`
  event nulls a payload while keeping its hash and idempotency key, and a
  tenant purge on uninstall follows lema's ADR-0081 precedent, so the
  append-only law has one lawful purge path with a receipt.
- This record is `proposed` until Andrew signs it. Under this directory's own
  rule a `proposed` record never reaches the reader; ADR-0006's banner does,
  and it says in its own text that it is not yet in effect.
- The open conformance artifact is a public commitment that outlives any
  private implementation. Publishing the fixtures means a second
  implementation could pass them; that is intended.
