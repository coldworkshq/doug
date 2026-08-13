# Outcome surfaces — the residual after PR #106

Date: 2026-08-12 · Status: **PROPOSED** (awaiting Andrew) · Baseline: `origin/main` @ `37942c3`

**Relationship to work already in flight.** PR #106 (`cursor/unbeatable-doug-research-584a`,
open, under review in another session) implements Approach A of
`2026-08-13-unbeatable-doug-research.md`: check-run footer, public scoreboard, landing
copy honesty, bot-author deep-read skip. This spec covers only what #106 does **not**
touch, plus two rulings that conflict with it and need a governing answer.

Lane C of the two-lane plan (`2026-08-11-two-lane-plan-design.md` §2 Phase C) is the
parent charter. Phase C was written "specified, not stepped"; this is its just-in-time
expansion for the two surviving items.

---

## 0. Decisions (ruled by Andrew 2026-08-12, do not re-litigate)

Decisions 1–3 govern the **scoreboard** spec, which is out of scope here (§1); they are
recorded in this document because they were ruled in a session transcript and would
otherwise survive nowhere. Decisions 4–5 govern this spec.

1. **The scoreboard publishes the full §3 table, always** — every column in
   `publication-preregistration.md` §3's "Published together, never separately" list,
   with §3's zero rules honoured verbatim. Rejected: a headline with the table behind
   it (the headline is a selection, and §12's off-cycle condition exists precisely
   because choosing what to surface first is choosing what to show); counts-only until
   decidable (the shape §8 forbids — "publish at any N regardless").
2. **The scoreboard is NOT a §12 publication.** It is the dogfood proof; the venue
   (`drewjst.github.io/doug/publication/`) carries the claim. The §9 noise slot renders
   as a permanent pointer to the venue, showing the last hand audit's figures once one
   exists. Rationale: making a live page the venue means every page load is a
   publication, which reintroduces the selective-disclosure problem §12's cadence rule
   exists to solve. Rejected: promoting the page to venue; deferring the ruling.
3. **Two lanes, not one.** The tenant-facing surfaces ship separately from the public
   prereg-governed page: a mistake on the latter is a published honesty failure, not a
   dashboard bug, and bundling them dilutes review attention where errors are expensive.
4. **The receipt gets its own route**, `/dashboard/pr/[number]` — not an inline panel
   and not an extension of the `?run=` evidence panel. Rationale: the receipt is a trust
   document meant to be read end-to-end and shown to someone else, a dedicated URL is
   what gets pasted into a thread or linked from a check run, and the `?run=` panel is
   per-**verdict** while the receipt is per-**PR**. Rejected: extending the run panel
   (conflates two granularities — the exact category error #93 and Phase A item 3 each
   had to correct).
5. **14-day and 60-day outcomes render as two separate always-shown columns**, each with
   its own pending state. Rejected: one column resolving to the strongest signal (the
   row stops saying which window it reports, so "clean" means two different things
   depending on data the reader cannot see); burying 60d in the panel.

## 0.1 Two conflicts with PR #106 that need a governing answer

Decisions 1 and 2 were ruled after #106 was opened, and #106 contradicts both. Neither
is discoverable by a code review — they exist in a session transcript, not in any file.

- **§3 scope.** #106 ships ten fields (`repo, adjudicated, pending, as_of, first_due,
  deep_reads, deep_read_cap, miss_rate, decidable, label`). None of §3's disclosure
  columns are present: no `censoring_rate`, `unverdicted_merges` by bucket,
  `remediated_clears`, `base_rate`, Wilson CI, `partial_read_share`, `repos_withheld`.
  This also under-delivers against **its own approved spec** §4.3, which says the query
  "emits the §3 table … (cleared-band miss, N, censoring, `remediated_clears`,
  decidability)".
- **Venue.** Approach A §4.3: "Venue can be the scoreboard page in this increment."
  Decision 2 rules the opposite. The later ruling should govern and §4.3 should be
  amended, but that is Andrew's call to state rather than this spec's to assume.

**Not a conflict, but a verified defect worth carrying into #106's review** (found by
reading the branch, not by running a review): the zero state is pinned in three coupled
places — `miss_rate: None` in the Pydantic model, `miss_rate: null` as a TypeScript
*literal* type, and `isScoreboardResponse()` rejecting any payload where
`miss_rate !== null || decidable !== false`. On validation failure
`web/lib/api.ts` `fetchScoreboard()` falls back to `scoreboard-fixture.json`, which
reads `adjudicated: 0, pending: 0`, and the `catch` is silent. Nothing breaks on
2026-08-16 — `adjudicated`/`pending` come from `instrument_snapshot` and tick correctly,
and "not yet decidable" stays honest while no interval is computed. The trap fires on
the *next* change to that endpoint: the one that teaches it to report a rate, which is
the surface's entire purpose. Whoever makes it must update three files or the public
page silently reverts to claiming zero adjudications.

---

## 1. Scope

**In:** the receipt screen; the 60-day join.
**Out:** everything #106 ships; the full §3 scoreboard (its own spec, gated on the #106
review's outcome); `finding_counts` rendering, tenant queue swap, health strip, spend
meter (the Phase C tail, no gate depends on them); anything in Lane 2.

**Ordering, and why it is not one PR.** The two items have opposite collision profiles
against #106:

| | files it touches | overlaps #106 |
|---|---|---|
| Receipt screen | new route `web/app/dashboard/pr/[number]/page.tsx`, new fetch in `web/lib/session-api.ts`, new components | **none** — #106 touches `web/lib/api.ts` (the public/showcase client), not `session-api.ts`, and does not touch the dashboard page |
| 60-day join | `api/doug/store.py` (`run_history`), `api/doug/models.py`, both clients' row types, `facets.ts` | **yes** — #106 edits `store.py` (+161) and `models.py` (+21) |

So the receipt screen proceeds now and is unaffected by the review's outcome. The
60-day join was sequenced **after #106 merges**, per the two-lane plan's own execution
loop: "The one shared file is `store.py` — changes to it ship as small separate PRs,
coordinated by the controller."

**Amended 2026-08-12 after #106 merged as `da8bf97`.** The sequencing constraint is
discharged; both items may proceed. Re-verified against merged main: `session-api.ts`
and `web/app/dashboard/page.tsx` are untouched by #106, so the receipt screen's
zero-overlap claim holds; `RunSummaryItem` survives at `models.py:184`; the
`window_days == 14` filter moved from `store.py:2245` to **`store.py:2407`**.

Also re-verified: **none of §0.1 was addressed by the merge.** The external review
(`docs/reviews/2026-08-12-pr-106-external-review.md`) found and fixed eight findings,
none of them the fixture-fallback trap. Its finding #3 is adjacent — a `review_jobs`
fallback that could publish a 0/0 scoreboard for a repo *with* adjudications — but that
is a server-side resolution path; the trap below is the client-side validator path and
survives on main. Review finding #7 refactored both fetches into a shared
`cachedShowcaseFetch(path, validator, fallback)`; the behaviour is unchanged, so the
defect is now shared uniformly by the queue and scoreboard rather than duplicated. Both
conflicts remain open, as expected: a code review structurally cannot find a ruling that
exists only in a session transcript.

---

## 2. Surface 1 — the receipt screen

### 2.1 Route and data

`web/app/dashboard/pr/[number]/page.tsx`, a server component, matching the dashboard's
existing grammar (server-rendered, URL state, no client fetching).

`GET /v1/prs/{pr_number}/receipt?repo=…` already exists (`api/doug/api.py:916`) and
needs **no** new endpoint, **no** new scope, and **no** migration:
`session_auth.SESSION_SCOPES` is `("queue:read", "receipt:read")`
(`api/doug/session_auth.py:27`), so a signed-in dashboard session already holds exactly
the scope the endpoint checks.

`repo` comes from the same place the dashboard's run list gets it — the selected
connection — and travels in the query string, not the path: a PR number alone is
ambiguous across repositories, which is why the API requires it.

Entry point: the PR-group rows already rendered by `PrGroup` in
`web/app/dashboard/page.tsx` link to this route.

### 2.2 The honesty states — the whole job

The API layer already names every state in its docstrings. The screen's only real work
is rendering them **without collapsing any**. Each row below is a required behaviour,
and each gets a test (§4).

| State | Source | Must render as | Must never render as |
|---|---|---|---|
| `ReceiptRead.recorded == false` | either of `diff_budget`/`read_order` NULL | "not recorded" | a budget or ordering number |
| `ReceiptVerdict.prompt_hash == null` | row predates prompt-hash stamping | "not stamped" | a match against the frozen prompt |
| `ReceiptWindow.kind == null` | window open, or job never completed | the job's `status` (pending/running/failed) | `clean`, or any adjudication word |
| `ReceiptWindow.prereg_hash == null` | pending window, nothing stamped yet | the top-level `preregistration` block, labelled as what *will* govern | today's env hash presented as what governed |
| `ReceiptPreregistration.in_force == false` | `DOUG_PREREG_HASH` unset | "no pre-registration in force" | a fabricated or omitted hash |
| `ReceiptMerge.governing_verdict == null` | merged with no governing verdict | says so explicitly | a fallback to `latest_verdict` |
| `ReceiptMerge.merged_head_sha == null` | pre-migration-008, or deleted fork branch | "not recorded" | an inferred sha |
| `publication_governing == false` | one of several merges | the `publication_note` verbatim | silently showing one merge |
| `latest_verdict` ≠ a merge's `governing_verdict` | rescored after merge, or work landed | **both**, side by side, with the gap named | either one alone |

Two further rules carried from the parent charter and the store:

- `latest_verdict` **excludes `tier='external'`** deliberately
  (`store.py:1786-1798`), and the reason is sharper than "external rows are noise":
  `api.py`'s webhook handler calls `save_external_review` on every
  `pull_request_review` event, writing a row with `scored_at` set to the human
  reviewer's `submitted_at` and **0.0/0.0 score/threshold placeholders** because no
  model ran and no diff was read. On a PR a human approved after Doug's last score, that
  row is newest and would win `ORDER BY scored_at DESC`. So the screen must not describe
  `latest_verdict` as "the newest verdict on this PR" — a human approval is newer and is
  deliberately not it.
- A PR carries a **list** of merges — `uq_outcome_job` includes `merge_commit_sha`, and
  revert-and-reland is the ordinary case, not an edge case. The screen renders all of
  them, in order, not just the first.

### 2.3 Visual grammar

Reuse, do not reinvent: `BandChip` (colour always accompanied by its word),
`CoverageRuler`, `RunSpine`, `.panel`, `.mono` with tabular-nums — all ported in Phase B
and already in `web/components/`. `console/app/runs/[verdictId]/page.tsx` is the nearest
precedent for a document-shaped detail view; follow its section-label-with-hairline
rhythm. No third data colour (the CVD rule at `console/app/globals.css:160-196`).

### 2.4 Error and empty states

- **404** — out-of-scope repo and absent PR share a code *and* a body by design, so the
  screen must render one indistinguishable "no receipt for this PR" state. It must not
  say "you don't have access", which would re-leak the existence signal the API's 404
  exists to suppress.
- **401** — session expired. Reuse the existing `reauthorize_required` treatment shipped
  in #99/#100 rather than inventing a second expiry story. **401 only** — see below.
- **Anything else, including no status at all** — an honest "could not load", with no
  instruction to sign in. `sessionJson` throws `status: null` on a transport failure
  (timeout, DNS, connection refused) *and* on a body the validator rejects, and neither is
  an expired session. A 500 or a 502 is not one either. **Amended 2026-08-12** — this arm
  did not exist in the first draft of this section, which routed every non-404, non-503
  case to the expiry copy. That told a reader to sign out and back in for a network blip
  or a malformed payload, which is a confident false claim on the one surface built to
  make confident false claims impossible. Four arms, not three.
- **503** — deployment fault (no ledger, no operator secret). Render as "the ledger is
  not answering", never as a credential problem: the API checks 503 *before* the token
  precisely so a misconfiguration is not reported as a bad credential.
- **A PR with verdicts but no merges** — the ordinary open-PR case. Renders
  `latest_verdict` and an explicit "not merged — no window has started".

---

## 3. Surface 2 — the 60-day join

**Unblocked** — #106 merged as `da8bf97`.

`store.run_history` currently filters `outcomes.c.window_days == 14` and keys its
reduction by `(repo, pr_number)` (`api/doug/store.py:2407`, post-merge). The change:

- drop the `window_days == 14` filter; key the dict by `(repo, pr_number, window_days)`;
- emit **two** scalar columns, `outcome_14` and `outcome_60`, preserving the existing
  last-observation-wins reduction *per window* — the comment at that site explains why a
  list column would fan one run into two rows, and that reasoning is unchanged;
- add `outcome_60` to `RunSummaryItem` (`models.py`), both clients' row types
  (`web/lib/session-api.ts`, `console/lib/api.ts`), and `search.ts`'s searchable fields;
- two separate table columns per Decision 5, each with its own pending state; a second
  facet in `facets.ts` mirroring the `outcome_14 ?? "pending"` treatment.

No migration. The 60-day rows already exist — `enqueue` writes both windows
(`store.py:1115`), and Task 7's backfill reported `eligible_14 = existing_60 = 66`.

---

## 4. Testing

Repo discipline applies unchanged: logic in `lib/` where `node --test` reaches it, no
render tests, and **every honesty test proven to discriminate** by reintroducing the bug
and watching it fail (clear `__pycache__` between weaken and restore).

Mutation proofs required, one per honesty state in §2.2 — the table is the test list.
The three that matter most, because each is a confident false claim rather than a
cosmetic slip:

1. Substituting `clean` for a null `kind` must fail a test.
2. Rendering the top-level prereg hash over an already-adjudicated window must fail a
   test.
3. Falling back to `latest_verdict` when `governing_verdict` is null must fail a test.

For §3: a test that reintroduces the `window_days == 14` filter must fail, and a test
that keys the reduction by `(repo, pr_number)` — dropping one window — must fail.

---

## 5. Exit gate

- `/dashboard/pr/[number]` renders a real receipt from the live ledger for a PR on
  `drewjst/doug`, with every §2.2 state exercised by a fixture and each proven to
  discriminate.
- Both outcome columns render, and a row where 14d is `clean` and 60d is `pending` shows
  exactly that.
- Zero contradictions against the console on identical data.
- `make test` + `make lint` + `npm run build` green in both workspaces.
- Doug's own review of the PR comes back clean or is adjudicated into
  `docs/findings-log.jsonl`.

## 6. Planned follow-on

- **Adversarial pass over all of it** (Andrew, 2026-08-12), once the #106 review lands —
  this spec, #106 as merged, and the scoreboard ruling together, rather than piecemeal.
- **Full §3 scoreboard**, its own spec, shaped by the #106 review's outcome. Sizing
  facts established while writing this: nothing computed §3 before #106;
  `precision.py:21` `wilson()` is the only reusable piece; §4's `base_rate` must come
  from `backtest/git_labels.py`'s squash-merge enumeration over 12 months; and §9's
  noise estimates are **not computable at all** — the basis is one hand audit per
  published `(repo, window)`, every quarter, forever, which is why the §9 slot on a live
  page can only ever be a pointer to the venue.
