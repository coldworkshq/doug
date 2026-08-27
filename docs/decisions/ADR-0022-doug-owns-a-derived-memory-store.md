---
title: Doug owns a derived memory store, and the store fills the provider slot ADR-0006 left empty
status: proposed
date: 2026-08-26
amends: ADR-0006
---

## Context

ADR-0006 gave Doug its own provider interface for recorded decisions —
`IntentDoc {id, title, body, status, date}` at `api/doug/intent.py:61` — and
one provider, `intent_providers.fetch`, that parses ADR-format markdown from
the repository under review. It left a second slot deliberately empty: a
lema-backed provider, "unimplemented, until lema exposes decisions with status
and repo scoping." The reason was a measured failure mode, not taste: lema's
hosted search had no status filter, so `d_81e789` ("LLM-assisted scoring —
rejected") would have reached the reader after ADR-0004 overturned it, and the
reader would have flagged Doug's own shipped reader as a deviation.

Three things changed between 2026-07-30 and today:

1. **lema is retired as a product.** The 2026-08-19 design pass (Doug Product
   Map, workflow `wf_cf0e0ae0`, 43 red-team findings adjudicated, 7 fatal all
   cured) merged lema into Doug as schema and ledger semantics only. The brand,
   the standalone apps, `lema verify`, the human write verbs, and the BIND tier
   are dropped. No lema data row ever migrates; backfill comes from repositories.
2. **The judgment queue is dead by ruling.** Andrew clicked lema's accept
   buttons without reading and the queue died as ceremony; lema's own ADR-0135
   had already removed it. The law that replaces it: **commitment is the
   decision.** A merged pull request or a committed document is the record of
   having decided; nobody enters a decision, and no queue adjudicates one.
3. **Prose-derived records have a measured precision problem.** The red team
   put lema's prose-only extraction at 0.463 precision (finding 22) and named
   session text an attacker-writable surface (finding 28). A store that treats
   every source as equal feeds the reader what it should never see.

Andrew signed the store's license and home on 2026-08-25: the store is
**private**, its conformance fixtures are **open**, and by the language law
(Go = store and spine, Python = anything that calls a model, TypeScript = web
only) it is its own Go repository, `coldworkshq/memory-store`, extracted from
lema's Go backend (`apps/api`: chi, pgx, goose; 782 files, 75 migrations). The
DB-free third of that extraction — ADR frontmatter parsing, verdict types,
source citation, `check_decided` — already exists as the standalone
`lemahq/lema-mcp` module with zero pgx imports. Stage 1 is a port, not a build.

This record is one of three that Stage 0 of the integration plan requires
before any of that code may exist (rule R2, paper gates code). The other two
are ADR-0023 (how a merge feeds the store) and ADR-0024 (what the store rides
on). The plan itself lives at `coldworkshq/coldworks` `docs/integration-plan.md`.

## Decision

### The store

Doug runs a memory store in a second Postgres schema, `memory`, on the same
Cloud SQL instance as the outcome ledger. The `doug` schema stays Python-owned
and single-writer under ADR-0011; the `memory` schema is Go-owned and
single-writer, with row-level security keyed on a per-request tenant GUC. **No
foreign key ever crosses the schema boundary.** The two join on frozen natural
keys — `(installation_id, github_repo_id, pr_number, merge_commit_sha)` — the
same five facts `_record_merge` already refuses a merge without.

Tenancy goes through `memory.tenants`: an internal id every memory row keys
on, a UNIQUE *current* `installation_id`, and the GitHub account id as the
durable anchor. A reinstall or an organization transfer is one `UPDATE` on
that table. Migration 17 is the precedent: the move to `coldworkshq/doug` had
to backfill name strings across `verdicts` and `outcomes` because those rows
key history on the repository's full name. The memory schema never does; series
identity keys on `github_repo_id` (issue #218).

The store holds no model client. Embedding and synthesis are `doug-api`
endpoints, `/internal/embed` and `/internal/synthesize`, called from Go over
the internal wire. Stage 1 ships lexical search only and every response carries
`degraded: true` until the hybrid path exists, so the search contract does not
change when the ranking does.

### The wire, frozen

The provider slot is filled by an internal provider that reads the store over a
wire whose shape is this record's contract:

- **Reads take a status set in and return live status out.** A list or get
  call names the statuses it will accept; a record whose live status is not in
  the set is absent from the response, not present with a warning. The
  vocabulary is the ADR frontmatter's: `proposed | accepted | superseded |
  deprecated | rejected`.
- **The record shape is `IntentDoc` exactly** — `{id, title, body, status,
  date}` — plus one additive field, `force`, described next. The Python side
  changes nothing about how it consumes a record.
- **Every record carries provenance** as a closed sum type, mandatory and
  repository-stamped: `pr {pr_number, merge_sha}`, `commit {sha}`, or `doc
  {path, sha}`. A record with no provenance is refused at write.
- **`occurred_at` is the commitment time**, mandatory, and every display,
  recency, ranking, and supersedence decision keys on it. `recorded_at` is
  bookkeeping and never orders anything. lema's `agent_sessions` migration
  states the rule this generalizes: the store is a consumer of identity and
  time, never their authority.
- **One source per record.** A record is derived from exactly one source in
  exactly one channel — merged code, a committed document, or (advisory only)
  a session. A second channel that reaches the same subject *links* to the
  existing record; it never merges into it. A record's provenance is therefore
  always a single citation.

The wire contract, the event envelope (ADR-0024), and the status-predicate
fixtures ported from lema are published as an **open conformance artifact**.
That is the public half of the 2026-08-25 ruling. The store's code is the
private half.

### Force tiers

Lifecycle status says whether a decision is in effect. Force says how much the
record's *source* entitles it to be believed. lema kept the two axes separate
on purpose (`internal/knowledge/tier.go:3`: "Lifecycle state is intentionally
not part of tier derivation"), and that separation ports verbatim. Four tiers:

| Force | Source | Reaches the reader as intent |
|---|---|---|
| `settled` | A commitment: a merged pull request, or a document at HEAD under the repository's own merge governance. Settlement *is* the accept. | Yes, when status is `accepted`. |
| `advisory` | A non-commitment: an agent session, a pull-request thread, an issue, a discussion. Cited, labeled, never promoted on its own. | No. Surfaced to humans and agents with its citations. |
| `historical` | A settled record a later commitment on the same subject superseded. Recency supersedes; nothing is deleted. | No. |
| `contested` | A settled record whose outcome verdict demoted it — the merge that settled it was reverted or hotfixed within the ledger's window. Machine-demoted, never hand-demoted. | No. Surfaced as "settled on DATE, reverted since — worth reopening." |

The governing record on a subject is the most recent `settled` record by
`occurred_at`. `historical` and `contested` records never govern.
`advisory` records never govern and are always cited.

**Session-provenance records cap at `advisory`.** An agent may record a
decision mid-session; that is capture, not force. The record surfaces at once,
labeled "recorded, not settled." The only path to `settled` is the correlator
matching the session to a merged commitment, at which point the derived record
cites both. A record born `settled` from session text is forbidden — the
session records intention, and the ledger records outcome. A session that ends
without a commitment leaves its captures `advisory` forever, which is the
correct weight for "tried and abandoned in session S."

### What may write, and what it must carry

- **A self-declaring file is parsed, never judged.** ADR frontmatter goes
  through the mechanical parser (lema `internal/adr`, ported). No model
  assigns a status to a document that states its own.
- **Every derived record carries verbatim evidence spans** into its source.
  A `ruled_out` verdict requires a quote anchor; a record without one is
  refused at write, not flagged at read.
- **Authority is sanctioned-versus-drive-by, not human-versus-bot.** A
  commitment counts when it landed under the repository's own merge
  governance, whoever the merging principal was. The tenant's own sanctioned
  agents mint settled records; a drive-by does not. `actor_kind` and the
  on-behalf-of field port from lema's events table for that purpose.
- **The deriver is an instrument, not a service.** It holds a row in the
  graded-reviewer roster from its first write, its eval is pre-registered
  (60–100 hand-graded derivations against frozen fabrication, faithfulness,
  and yield bars), and no tenant-visible record exists until that eval
  passes. Backfill is batch-stamped and runs only afterward. That is Stage 2's
  gate, recorded here so Stage 1 cannot ship a deriver by accident.

### Who may read

Tenant reads are allowlist-first. A public tier — the static, read-only
corpus the `check_approach` door already serves — is admitted only after the
ported precision goldset clears the bar lema's ADR-0095 family set for
extraction precision, and `check_decided` is never sold before that. A
dedicated free-tier instance is bought by a measured funnel signal, never
assumed. The GTM fork this rides on was deferred on 2026-08-25 and is not
reopened by this record.

The neutral check run (ADR-0010) gains a contradiction section that cites the
governing record. It informs; it never changes the conclusion and never blocks.

### What coldworks reads

The coldworks M6 normalizer ingests decisions from this store as `recovered`
provenance. It reads a **versioned read view** — `memory.v1_decisions` or its
successor, bumped never mutated — and never the raw tables or the event
envelope. The envelope's provenance block alone is not a recovery surface
(red-team finding 34); the view is.

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
failure mode — and the session lane's own design (`docs/design/session-lane/
design.md:157`) says asserted material "decays unless corroborated by observed
commitment."

**A model client inside the Go store.** lema's `go.mod` imports
`anthropic-sdk-go` and `genai`; they stay behind. A store that calls a model
turns every embedding-model swap into a store release, and the language law
exists so that the thing that calls a model is the thing that is graded.

**Cross-schema foreign keys.** They couple two writers, make an organization
transfer a cascade instead of one `UPDATE`, and put the memory schema's
integrity in the hands of a migration framework it does not run under.

**Keying tenancy on `installation_id`.** GitHub reissues it on reinstall, and
the App transfer in flight as this is written (#226) is exactly the event that
would have orphaned every row.

## Consequences

- ADR-0006's "lema-backed provider ... unimplemented" clause is retired. Its
  other rulings stand unchanged: Doug owns the provider interface and the
  contract; Doug's own decisions live in this directory, which is now one
  channel into the store rather than the only source; repositories without an
  ADR directory get an inert feature, not an error.
- The wire contract is frozen at Stage 1's first migration. Changing it is not
  a refactor; it reopens Stage 0 and needs a new signature (integration plan
  rule R9).
- The reader's feed narrows: only records with status `accepted` and force
  `settled` reach the model. That is the ADR-0006 gap, closed by construction
  rather than by a filter someone must remember to apply. Until Stage 2's eval
  passes, the only settled records are the ones this directory's parser
  produces today, so the reader's behavior does not change at Stage 1.
- Stage 1 exits when the intent provider reads from the store with correct
  status filtering **and** a dual-run parity oracle against
  frontmatter-at-HEAD shows zero drift. Both bars are pre-registered here.
- A second writer joins the production ledger. Gate A of the integration plan
  — alert policies, one observed outcome cycle, one reconciler execution —
  must be green first. As of 2026-08-26 all three are still red.
- Every read pays for a tenant GUC and an RLS check. That is the price of
  putting tenant isolation in the database rather than in every caller.
- This record is `proposed` until Andrew signs it. Under this directory's own
  rule, a `proposed` record never reaches the reader, so an unsigned draft
  cannot produce a finding.
- The open conformance artifact is a public commitment that outlives any
  private implementation. Publishing the fixtures means a second
  implementation could pass them; that is intended.
