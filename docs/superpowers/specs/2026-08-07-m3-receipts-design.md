# M3 receipts design

**Status:** Approved by Andrew on 2026-08-07
**Branch:** `m3-receipts`
**Governing contract:** `docs/design/outcome-loop/publication-preregistration.md`
(LOCKED v8) §2.1/§2.2/§2.5/§11, `docs/design/outcome-loop/build-plan.md:19`,
`docs/design/outcome-loop/product-spec.md` §Week 3+, ADR-0002, ADR-0012

## Goal

Serve `GET /v1/prs/{pr_number}/receipt` — the artifact a staff engineer pastes
into an incident review. A receipt states what Doug said about one pull request,
which instrument said it, how much of the change that instrument actually saw,
and what the repository subsequently did about it.

The slice is complete when a receipt for a real merged Doug PR reads correctly
end to end, a cross-tenant token cannot obtain one, and every claim the document
makes is one the ledger can support.

## Why this is not a re-skin of `/v1/runs/{id}`

`store.run_detail` already assembles verdict, threshold, reasons, coverage,
`prompt_hash`, model, `head_sha`, deviations, outcomes and outcome jobs. The
temptation is to scope that query and ship.

The two endpoints do not share a contract. `run_detail` answers *"this verdict,
by id"* — the console already knows which row it wants. A receipt answers *"the
governing verdict for this PR"*, and which verdict governs is not a display
choice. Pre-registration §2.1 defines it, and §2.2 holds the SQL the published
quarterly number will run. If receipts implements that rule in its own query, one
locked definition acquires two implementations, and the day they diverge a
customer's receipt contradicts the published table. That is the most expensive
failure available to this product: the entire claim is that the receipt and the
number come from the same ledger.

**Therefore the rule is extracted once.** A single `governing_verdict()` selector
in `store.py` implements §2.1. Receipts calls it. The future publication query
calls it. `run_detail` is not touched and keeps serving the console by verdict id.
Response projection reuses the existing shapes where they genuinely match;
selection logic exists in exactly one place, with a comment saying that editing it
changes a published metric.

### Selection is not qualification, and the spec must not blur them

Reading §2.2's SQL rather than §2.1's prose settles three details that a
paraphrase gets wrong:

- **`tier = 'reader'` is inside the ranking CTE**, so it filters *before*
  `row_number()`. The governing verdict is the latest **reader** verdict at or
  before `merged_at`; a later deterministic-fallback verdict does not displace it.
- **`band = 'cleared'` is in the outer query, not the CTE.** Band is a
  *denominator qualification*, not part of selection. A flagged PR has a governing
  verdict and deserves a receipt; the receipt reports the band rather than
  filtering on it. `governing_verdict()` therefore does not take band as an
  argument.
- **The CTE requires the installation to still exist** (`EXISTS (SELECT 1 FROM
  installations …)`). The selector carries that check so a receipt cannot outlive
  the ledger row that scopes it.

`row_number()`, never `DISTINCT ON` — §2.2 says so explicitly, because
`DISTINCT ON` is Postgres-only and every test in this project runs sqlite
(`REVIEWING.md:141-143` records that exact trap).

### One PR can have more than one merge identity

`uq_outcome_job` includes `merge_commit_sha`, so §2.2 counts with
`count(DISTINCT j.pr_number)` precisely because two rows for one PR at one window
are schema-permitted. A receipt keyed on `(repo, pr_number)` therefore cannot
assume a single merge.

**Correction, 2026-08-07 — this section previously claimed §2.2's CTE "resolves
strictly per merge identity". That was false**, caught by Task 4's implementer
and verified against the document. §2.2's window is:

```sql
PARTITION BY v.installation_id, v.github_repo_id, v.pr_number
```

There is **no job term in the partition**. So §2.2 designates exactly **one**
governing verdict per PR per window: the latest reader verdict scored at or
before the **latest** `merged_at`. It does not resolve per merge.

The per-merge signature is kept anyway, because a receipt that could not show
what Doug had said at an earlier merge would be less truthful, not more. But it
creates a hazard the false justification had hidden: an earlier merge's standing
verdict is *not* the verdict §2.2 designates, and a reader looking only at that
line could believe it governed.

**Resolution (Andrew, 2026-08-07):** `governing_verdict()` takes `merged_at` and
is called once per merge identity, and the merge with the greatest `merged_at`
is flagged `publication_governing: true` — exactly one per receipt, and it is by
construction the verdict §2.2 selects. Every other merge is labelled historical
context and the receipt says in words that it did not govern publication. In the
ordinary single-merge case there is one merge, flagged true.

Rejected: resolving once per PR to mirror §2.2 one-to-one (loses the earlier
merge's verdict, which is real evidence); rejected: leaving the code as built and
correcting only this prose (the hazard survives, undistinguished on the page).

Rejected alternatives:

- **Extend `run_detail`.** Puts a pre-registered metric rule inside a console
  helper, where nothing signals what editing it costs.
- **A separate receipts query.** Ships marginally faster and creates the second
  implementation described above.

## The instrument-identity problem this slice also fixes

`reader._compute_prompt_hash` covers `SYSTEM + repr(SCHEMA)` and nothing else.
Its docstring calls the result "the 'these numbers are about the same instrument'
anchor". It is not one today.

`DIFF_BUDGET` moved 30,000 → 100,000 and `read_order()` tiering shipped, both in
#56. Neither is in the hash. `Coverage` records `diff_chars` and `sent_chars` but
never the budget or the ordering, so **for any diff under 30,000 characters the
two configurations are indistinguishable in the row.** Two verdicts can carry an
identical `prompt_hash` and have been produced by materially different reads.

A receipt whose purpose is evidentiary cannot ship on top of that silently.

### What is provable, and what is not

Verified 2026-08-07: `git log -L 45,92:api/doug/reader.py` returns exactly one
commit — `293c19d`, 2026-07-29, the commit that created `SYSTEM` and `SCHEMA`.
They have never changed. There is **one prompt era**, so writing today's
`PROMPT_HASH` onto historical reader verdicts asserts nothing that git history
does not already establish.

Read configuration is the opposite. Merge time is not serving time: #56 merged
2026-08-06 21:48Z, its revision began serving later, and Cloud Run shifts traffic
gradually. A dated `UPDATE` would mislabel every verdict scored inside that
window, and nothing anywhere records how wide the window was.

So the two halves are treated differently, and the receipt says which is which:

1. **Backfill `prompt_hash`** — provable, therefore recorded.
2. **Stamp read configuration forward only** — not provable for history,
   therefore not invented.
3. **No read-configuration backfill.** `NULL` renders as its own state.

The precedent is already in this schema and it runs the same direction:
`outcome_jobs.due_at` is stored rather than derived because "a derived value
would drift if `window_days` ever changed after the row was written."

Rejected: a `read_config_hash`. A hash tells a reader that two verdicts differ;
the integer tells them *what* differed, which is a receipt's whole job. Also
rejected: prose-only per ADR-0012, which leaves the gap open for the next time
`DIFF_BUDGET` moves. Also rejected: shipping the columns as their own PR — the
ROADMAP's own `[~]` rule is that "a shipped primitive nothing calls is not a
shipped capability", and receipts is the only consumer.

## Migration 8

`MIGRATIONS` in `api/doug/migrations.py` ends at 7. Check that list before
writing a number; this repository has hit the renumbering trap at 003/004 and
again at 007. **This slice consumes 8, so MT3's `installations.reconciled_at`
becomes migration 9.**

| Column | Type | Written at |
| --- | --- | --- |
| `verdicts.diff_budget` | `Integer`, nullable | `worker.py:191` |
| `verdicts.read_order` | `String(16)`, nullable | `worker.py:191` |
| `outcome_jobs.merged_head_sha` | `String(64)`, nullable | `_record_merge` |

`read_order` is written from a named constant in `review.py`, never a literal at
the call site, so the recorded value cannot drift from the ordering actually
applied. Both verdict columns are written only when `tier == 'reader'`, matching
how `model` and `prompt_hash` are already conditioned on the same line.

`merged_head_sha` closes pre-registration §11 item 7 ("PR head sha at merge — not
stored") **forward only**. It does not change the locked §2.1 rule, which stays
timestamp-matched; it makes a future amendment possible without a second
migration. It is captured from `pull_request.head.sha`.

**It must not join the required-facts set in `_record_merge`.** That function
today drops the whole row if any of five facts is missing, because "a half-row is
worse than a missing one" when `base_ref` drives censoring and `github_repo_id`
drives tenancy. `merged_head_sha` carries neither weight. A missing `head.sha`
must never suppress an outcome clock — best-effort, nullable, and silent.

### The backfill statement

```sql
UPDATE verdicts
SET prompt_hash = '8bd26c677a0e087a0b8c14933203cc85e15b65e32b432c10a3ae78009a951cdf'
WHERE tier = 'reader' AND prompt_hash IS NULL
```

That literal was verified two ways on 2026-08-07: recomputed from the `SYSTEM`
and `SCHEMA` source text, and read back from `reader.PROMPT_HASH` at runtime.
They agree.

**The hash is a literal, not `reader.PROMPT_HASH`.** A runtime reference would,
if the prompt ever changed, stamp historical rows with the *new* hash on any
fresh replay — silently relabelling verdicts as the product of a prompt they
never saw. A literal pins that era permanently and correctly. The `IS NULL`
predicate makes it idempotent and a no-op on fresh databases.

Only `tier='reader'` rows are touched. Deterministic and `external` verdicts have
no prompt, so `NULL` is their correct value. CI-path rows already carry a hash and
are excluded by the same predicate.

## Endpoint and authorization

`GET /v1/prs/{pr_number}/receipt?repo=owner/name`

`repo` is required — a PR number alone is ambiguous across repositories. This
matches `/v1/queue`'s existing `?repo=` shape rather than inventing a nested path.

Two token classes reach it, structured exactly as `/v1/queue` already does:

- operator `DOUG_API_TOKEN` — unscoped, any repository
- a dispensed tenant token — must carry `receipt:read`, and the repository must
  be in its live-intersected effective selection

**`receipt:read` is a new scope**, and `tenancy.py:342` starts minting it
alongside `queue:read`. Existing keys carry only `queue:read` and will `401` on
receipts until re-minted. That is deliberate: `/v1/queue`'s own comment says the
scopes column exists "so a future receipts/MCP-only key does not silently inherit
queue access it was never granted", and the same discipline runs both ways.
Production has two installations, both Andrew's, and minting appends rather than
rotates, so the blast radius is nil. Fixing the vocabulary before M5's outside
tenants is far cheaper than after.

Status codes follow the established convention:

| Code | Condition |
| --- | --- |
| `503` | `DOUG_API_TOKEN` unset, or no ledger configured |
| `401` | token resolves to nothing, or lacks `receipt:read` |
| `404` | token resolves but the repo is outside its scope — **and** repo, PR or verdict genuinely absent |
| `422` | malformed typed params (pre-existing posture, `_operator_only` docstring) |

The shared `404` is the point: a caller must not be able to distinguish "not
yours" from "does not exist".

## Response shape

**This block is the original design intent, not the shipped contract.** What
actually shipped (`ReceiptResponse` in `api/doug/api.py:543`) diverges from it
in three ways, each deliberately deferred rather than silently dropped:

- `inputs_seen` (with `changed_files`, `files_dropped`, `complete`) does not
  exist. What shipped is a `coverage` field on the verdict — the
  pre-existing 5-field `RunCoverage` (`diff_chars`, `sent_chars`,
  `files_sent`, `files_unseen`, `file_cut`) — which carries none of those
  three.
- There is no top-level `url`.
- There is no per-merge `governing_rule` string naming §2.1. `publication_note`
  shipped instead, and answers a different question — whether this merge's
  governing verdict is the one the published quarterly number uses, not which
  rule governed it.

The block below is kept as the record of what was intended; treat the three
points above as the current, accurate delta against it. Closing that delta is
a follow-up, not done in this slice.

Adjudication nests **under a merge identity**, and both are lists, because the
schema permits several merges per PR and `outcome_jobs` carries one row per
`(merge identity, window_days)`. Nesting is what lets the receipt produce
product-spec's sentence — *"no revert observed in 14 days (60-day window
pending)"* — while still naming which merge it is talking about.

```
repo, pr_number, url
latest_verdict:                            # always present
                                           # (merges[] entries carry
                                           #  publication_governing: bool —
                                           #  exactly one true, the greatest
                                           #  merged_at; see the correction above)
  verdict_id, scored_at, tier, band, score, threshold
  head_sha, model, prompt_hash, rationale, findings[]
  read: { diff_budget, read_order }        # nulls mean "not recorded"
  inputs_seen: { changed_files, files_sent, files_unseen, files_dropped,
                 file_cut, sent_chars, diff_chars, complete }
merges: [                                  # empty when the PR has not merged
  merged_at, merge_commit_sha, base_ref, merged_head_sha
  governing_verdict: { ...same shape as latest_verdict... } | null
  governing_rule: str                      # names §2.1 in a sentence
  adjudication: [ { window_days, status, due_at,
                    kind, observed_at, evidence_sha, source,
                    prereg_hash } ]
]
preregistration: { hash, in_force: bool }
```

`latest_verdict` and `governing_verdict` are separate fields rather than one
field with a flag. They are usually the same row, and when they are not, that
difference is exactly what a reader of an incident review needs to see: work
pushed after the advice a human actually merged on. Collapsing them into one
field with `governing: bool` would make the interesting case invisible.

`governing_verdict` is `null` when no reader verdict was scored at or before that
merge — a real case for PRs that merged before Doug was installed, or where only
a deterministic fallback ran.

### The pre-registration hash

`gcp.sh:401` sets `DOUG_PREREG_HASH` on the adjudicator Job only. **This slice
also sets it on the `doug-api` service**, where the value is already computed a
few lines earlier in the same script.

An adjudicated entry prints the hash stamped in `outcomes.detail` at adjudication
time. A pending entry prints the hash currently in force, labelled as such,
because that is the document that will govern it. When the two differ, both are
shown — a receipt that silently reprinted the current hash over an older
adjudication would be manufacturing the exact confident-derived claim this design
exists to avoid.

Note for whoever runs Task 7: the v8 hash
(`be69db86eab91b569716f112a77f73993263a9650a7e55a33b1f6fafc57b86e8`) went live at
2026-08-08 00:52Z via #69's ordinary deploy, because `gcp.sh` calls `adjudicator`
before `api_url`. Pre-registration §11 item 10 and `repo/HANDOFF.md` both still
say it is not live; they are stale on that point. The production **catch-up** has
genuinely not run.

### The ten states a receipt renders rather than smooths over

This is the section reviewers should be hardest on. Each one is a way the
document could imply more than the ledger knows.

1. **Open PR** — `merges: []`. No governing verdict exists, because §2.1's rule
   needs a `merged_at` that does not exist yet. The receipt shows
   `latest_verdict` and says plainly that nothing governs yet. Rendering the
   latest verdict as though it counted would be the "partial rendered as whole"
   failure `check_run.py` exists to prevent.
2. **`governing_verdict: null` on a merged PR** — no reader verdict at or before
   that merge. Stated as its own fact, never backfilled with the latest verdict.
3. **`latest_verdict` differs from `governing_verdict`** — pushes landed after
   the advice the merge was made on. Both shown, with the distinction named.
4. **More than one merge identity** — every merge listed, and exactly one
   carries `publication_governing: true` (the greatest `merged_at`, which is the
   verdict §2.2 designates). The others are labelled historical context, in
   words, so no reader can mistake an earlier merge's standing verdict for the
   one the published table used. The receipt never silently picks one, and never
   lets two of them look equally authoritative.
5. **Read configuration absent** — "not recorded", never a number.
6. **`prompt_hash` present without read configuration** — the receipt does not
   claim instrument identity on the strength of the hash alone.
7. **Incomplete coverage** — surfaced through the existing
   `reader.truncation_reason`, not a second phrasing of the same caveat.
8. **`tier != 'reader'`** — labelled fallback-grade. Pre-registration §2.5
   governs these, not §2.1, and `design-lock.md:77` calls deterministic ranking
   "the loud, labeled fallback".
9. **Adjudication pending, or censored** — pending reads "no revert observed yet,
   window closes ⟨date⟩"; a merge to a non-default `base_ref` reads `censored`.
   Neither ever reads "clean".
10. **Stamped and in-force pre-registration hashes differ** — both shown.

## Testing

The load-bearing test is `governing_verdict()` pinned against §2.2's SQL
**verbatim as a fixture**: a PR pushed several times whose verdicts straddle the
threshold, plus a tie on `scored_at` that must resolve to the greatest
`verdicts.id`. A test that cannot fail when the rule changes is worthless here,
so the fixture asserts the selector and the raw SQL agree row for row. Because
§2.2 runs under sqlite in the suite, that comparison is executable rather than
argued.

Three cases in that test exist specifically to catch a paraphrase of §2.1 that
reads correctly but ranks wrongly:

- a later **deterministic** verdict must not displace an earlier reader one
- a **flagged** PR must still resolve a governing verdict (band qualifies the
  denominator, not the selection)
- a verdict scored **after** `merged_at` must be excluded

Then, one test per claim the design makes:

- cross-tenant token on another installation's PR → `404`
- a token holding only `queue:read` → `401`
- open PR → `merges: []`, latest verdict present and labelled
- merged PR with no reader verdict → `governing_verdict: null`, not substituted
- two merge identities on one PR → both listed
- the `prompt_hash` backfill is idempotent — second run touches zero rows
- a verdict with `diff_budget IS NULL` renders "not recorded" and never a number
- a non-default `base_ref` renders `censored`, never `clean`
- incomplete coverage reaches the response
- `merged_head_sha` missing from a merge payload does not suppress the clock
- a receipt for a real merged Doug PR, end to end

## Known limit at ship time

Zero adjudications exist and the first due clock is 2026-08-16. Every receipt
written before then is empty on the adjudication side, so states 6 and 7 are
carried by tests rather than production observation. The M3 exit gate's "one
receipt correct end to end" is therefore only **partly** satisfiable this week —
the verdict, inputs-seen and pending-adjudication halves can be proven now; the
adjudicated half cannot. This is a sequencing fact, not a defect, and it should
not be ticked off as complete until a real adjudication has been rendered.
