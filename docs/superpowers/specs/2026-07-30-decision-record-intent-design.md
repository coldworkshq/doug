# Decision records as intent input for the reader

**Date:** 2026-07-30
**Status:** approved, not yet built
**Depends on:** Experiment B v2 (intent-grounded deviation detection, PASSED)

## Why

The reader is validated as a *ranker* of defect risk (AUC 0.687 sentry /
0.668 grafana, pre-registered, two repos). Experiment B v2 validated a
second, different capability: given the PR's diff **and** the intent it
claims to serve, the reader reports deviations between them — 4% of
matched PRs produced a HIGH-severity deviation against 100% of mismatched
ones, with intent-alignment scores of 80 vs 2.

B v2 used the linked GitHub issue as the intent surface. This spec adds a
second source in the same slot: the team's own recorded architecture
decisions. The failure mode it targets is the one no incumbent reviewer
sees — *competent code implementing the wrong thing*, deviating from a
decision the team already made and wrote down.

## Scope

In scope: an intent-provider interface, an in-repo ADR provider, the
frozen intent prompt in the product path, a separate deviation stream in
the ledger, a CI surface, and the integrity experiment that gates trust.

Out of scope: a lema-backed provider (see Boundary), suggested fixes,
letting deviation influence the risk score, and any change to the
diff-reader's own prompt or schema.

## Decisions

### Records come from the repo under review, not from lema

Doug's CI-facing `/v1/review` already receives a per-request
`x-github-token` from the caller's workflow, which is how it reaches
private repos without holding credentials of its own. Decision records
are markdown in that repo. Reading them therefore needs no new
credential, no Cloud Run egress to a private service, and no dependency
on another product's uptime.

It also enforces the status rule. Records carry `status:` in frontmatter,
so "feed only accepted decisions" is checkable at parse time. The hosted
lema MCP is search-only in its current form and cannot filter by status,
which would mean feeding superseded decisions to the reader and getting
confident, wrong deviation findings.

Rejected: lema's hosted search as the source of record.

### Doug does not depend on lema

Doug owns the provider interface and the contract it needs:
`{id, title, body, status, date}`. Whether lema exposes decisions for
outside consumption — with status and repo scoping — is lema's product
decision and lema's roadmap, not Doug's to assume.

The reason is commercial as much as architectural: if intent-reading only
works for lema customers, Doug's addressable market becomes lema's
customer list. In-repo ADRs keep Doug standalone; a lema provider, if it
ever arrives, is an enrichment behind the same interface.

This also settles the open question of overlap with `lemahq/lema-verify`:
lema-verify is lema checking its own decisions; Doug is a reviewer that
accepts decisions as one input among several. Different products, one
shared insight.

Rejected: building a lema provider now; making this a lema-integrated
feature only.

### Doug must first record its own decisions

`drewjst/doug` has no `docs/decisions/`. Doug cannot read its own intent
because Doug never wrote any down in its own repo — the decisions live in
`HANDOFF.md` prose and in lema's store (`lema:d_81e789`, `d_48b302ae`),
recorded there in July 2026 when Doug had nowhere else to put them, and
before Doug and lema were treated as separate products. Doug was never
ingested into lema as a repo. Seeding `docs/decisions/` is
therefore a prerequisite for dogfooding, not a side quest. The material
already exists: every "Decisions this session" entry is ADR-shaped —
choice, rationale, rejected alternative.

One of those records supersedes thesis-v2's rejection of LLM-assisted
scoring, which Phase 1 overturned and which the shipped reader already
violates.

### Selection is deterministic

Which records go in front of the model is chosen by lexical relevance
between (PR title + changed paths) and (record title + body), top-k
within a character budget (chars, matching the reader's existing
`DIFF_BUDGET` convention). No model participates in selection.

Two reasons. Routing is not a judgement call, so it belongs in code. And
a model-selected record set would make the derangement check
uninterpretable — a null result could mean either "the reader ignores
intent" or "selection fed it the wrong records".

Rejected: LLM-scored or embedding-ranked selection. (Embeddings may be
worth revisiting once there is a reason to believe lexical overlap is the
binding constraint; pgvector is already anticipated in the ledger's
design notes.)

### The schema is reused verbatim; the system prompt is a frozen sibling

`INTENT_SCHEMA` moves verbatim from `scripts/intent_probe.py` into
`doug/reader.py` — same `intent_alignment`, same `deviation_findings`
with the same three `type` values. Storage and analysis therefore work
identically across both intent sources.

The system prompt cannot be reused verbatim, and pretending otherwise
would be the dishonest version of this design. `INTENT_SYSTEM` says "you
are ALSO given the issue/ticket this PR claims to resolve" and defines
`missing-from-pr` as "things the ticket asks for that the PR does not
do". A recorded decision does not ask a PR to do anything, so that
sentence is false and that deviation type barely maps. The two types
that *do* map — a change the decision does not sanction, a change that
contradicts it — are the interesting ones anyway.

So `DECISION_INTENT_SYSTEM` is a sibling prompt: same task shape, same
deviation vocabulary, framing adapted to decision records. It is frozen
from creation and pinned by test, exactly like its siblings (ADR-0002).

What this costs, stated plainly: B v2 does **not** transfer as
validation. It transfers as prior evidence that the capability exists —
that a reader given a diff and an intent document can detect real
divergence rather than hallucinate it. Whether *this* prompt on *these*
documents does the same is unproven, and the derangement check is what
answers it.

### Deviation is a separate stream

Deviation findings and `intent_alignment` are written to a new
`deviations` table and are **never** folded into `risk_score` or `band`.

Deviation has no outcome-precision evaluation yet. Blending it into the
score would silently change what every score on the dashboard means and
would invalidate the AUC evidence the reader is trusted on. Note that
lema reached the same conclusion independently for decision-bound
verdicts, keeping them a distinct stream gated by their own precision
eval.

Rejected: deviation raising the risk score.

## Architecture

```
review.score_one(meta, diff)
  ├─ reader.read_diff(...)                    unchanged, frozen
  └─ if DOUG_INTENT=1:
       intent.gather(repo, meta, gh)          deterministic
         └─ providers.InRepoADR               fetch + parse + filter + rank
       reader.read_intent(meta, diff, docs)   frozen INTENT_SYSTEM/SCHEMA
       store.save_deviations(verdict_id, ...) separate table
```

### `doug/intent.py`

Owns the contract and the selection, and nothing else.

```python
class IntentDoc(BaseModel):
    id: str        # "ADR-0007"
    title: str
    body: str
    status: str    # accepted | proposed | superseded | deprecated | rejected
    date: str | None
    ref: str       # provenance carried into every deviation finding
```

- `gather(repo, meta, gh, budget) -> list[IntentDoc]` — fetch via the
  provider, drop anything not `accepted`, rank by lexical relevance,
  return top-k within the character budget.
- `relevance(meta, doc) -> float` — pure function, no I/O, directly
  testable.

### `doug/intent_providers.py`

- `InRepoADR(gh, repo)` — lists candidate directories (`docs/decisions/`,
  `docs/adr/`, `doc/adr/`; overridable by `DOUG_ADR_PATH`), fetches
  markdown, parses YAML frontmatter for `status`/`date`/`title`. A repo
  with no such directory yields `[]` and the feature is simply inert —
  that is the common case and must not be an error.

### `doug/reader.py` additions

- `INTENT_SYSTEM`, `INTENT_SCHEMA` — verbatim from the probe, byte-pinned.
- `IntentReaderVerdict` — the diff-reader's fields plus `intent_alignment`
  and `deviation_findings`.
- `read_with_intent(pr, diff, docs) -> IntentReaderVerdict`.

### `doug/store.py` additions

```python
deviations = Table(
    "deviations", metadata,
    Column("id", Integer, primary_key=True),
    Column("verdict_id", Integer, ForeignKey("verdicts.id"), nullable=False, index=True),
    Column("kind", String(24), nullable=False),   # missing-from-pr | beyond-ticket | contradicts-ticket
    Column("description", Text, nullable=False),
    Column("severity", String(10), nullable=False),
    Column("intent_ref", Text),                   # which record, for provenance
    Column("intent_alignment", Integer),
)
```

`metadata.create_all` creates it on first use; no migration framework.

## Data flow and failure handling

Every failure is inert, never fatal — this path is advisory and must
never redden a PR or corrupt a risk verdict:

| Failure | Behaviour |
|---|---|
| No ADR directory | `gather` returns `[]`; intent read skipped entirely |
| All records superseded | same as above |
| GitHub fetch fails | log, skip the intent read, risk verdict unaffected |
| Intent read raises `ReaderError` | skip; deviations absent, not empty-but-recorded |
| Ledger write fails | already handled — a down ledger must not fail CI |

The distinction in row 4 matters for the eventual precision numbers: "no
deviations found" and "the read did not happen" must not be recorded the
same way.

## CI surface

Job summary only, consistent with the existing rule that Doug never
comments and never blocks. Deviations render under the risk verdict as a
separate block, each line carrying its decision ref so a reader can check
the claim against the record. The risk verdict's own rendering is
unchanged.

## Testing

Unit, with no network:

- `relevance` ranks a record sharing PR paths above one that does not.
- `gather` drops `superseded`, `proposed`, `rejected`; keeps `accepted`.
- `gather` honours the character budget and returns records in rank order.
- Frontmatter parsing survives missing `status`, missing `date`, CRLF, and
  a file that is not an ADR at all.
- A repo with no ADR directory yields `[]` and logs nothing alarming.
- `INTENT_SYSTEM`/`INTENT_SCHEMA` byte-pinned against the probe's values.
- `save_deviations` writes rows against the verdict and does not touch
  `verdicts.score` or `verdicts.band`.
- A failed intent read leaves the risk verdict byte-identical to the same
  PR scored with `DOUG_INTENT=0`.

The last one is the load-bearing test: it encodes the separate-stream
decision as an executable guarantee rather than a convention.

## Shipping and the integrity check

**It ships on.** `DOUG_INTENT=1` wherever Doug runs, from the first
merge. Deviations render in the CI job summary immediately. There is no
staged rollout, because there is nothing to stage: Doug never blocks, so
every verdict it emits is already advisory, and a deviation in a job
summary cannot hurt anyone. The only thing withheld is deviation moving
the risk score, and that is the separate-stream decision above, not a
rollout phase.

The **derangement integrity check** —
`scripts/decision_intent_probe.py` — decides whether to *believe*
deviations, not whether to ship them. Matched arm: each PR with its own
top-k records. Deranged arm: each PR with another PR's records.
Deviation findings must fire on the deranged arm and stay quiet on the
matched arm, mirroring B v2's 4% / 100%. Bar pre-registered in
`workspace/research/phase1-entry-preregistration.md` before the run.

If the arms come out identical, the reader is pattern-matching the diff
and ignoring the records. That is worth knowing whether or not the
feature is live, which is exactly why the check is not a gate.

Runs on `drewjst/doug` once Doug's own PRs exist — a repo the assistant
can read, unlike private lema.

**Power, stated honestly:** Doug's and lema's own PR history is the
entire corpus. Enough to catch theater; nowhere near enough to estimate
deviation precision. No precision claim comes out of this experiment.

## Open items

- Whether the deviation stream ever earns its way into routing is a
  separate decision, and needs outcome-joined evidence that does not exist
  yet. Deliberately not designed here.
- The lema provider stays an unimplemented stub with a documented
  contract until lema exposes decisions with status and repo scoping.
