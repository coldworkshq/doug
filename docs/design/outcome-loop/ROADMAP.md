# Roadmap: The Outcome Loop

**The tracking document.** Check boxes in the PR that completes them; a milestone closes only
when its exit gate is verifiably true (the gate is the definition of done, not the checklist).
Sequencing logic: clear the decks → land the reviewed ingest plan once → make spend/auth safe →
build the loop → prove it on ourselves → let outsiders in → gated tracks. Nothing outside
M0 starts before M0 closes; M1–M3 are strictly ordered; M4/M5 overlap M3's calendar time
(the 14-day clock runs while we work); M6 tracks fire on triggers, not dates.

Effort marks are engineer-days of focused work, not calendar days.

`[x]` done and merged · `[ ]` not started · `[~]` **partially** landed, with the remaining half
named in the item. `[~]` exists because items go half-true in a way that reads as done if you
only count boxes: a shipped primitive nothing calls is not a shipped capability. One of the
original pair remains open — **doug-web's dedicated service account** (code merged in #44; the
ops cutover has not run). Bot-author skip closed in #106. Two closed the way this mark is
meant to close: Task 7's reconcile, once Task 7b called it from the lifespan, and M2's spend
cap, whose primitive landed in #25 and sat wired to nothing until #37 put `_charge(scope)` in
front of both paid entry points.

---

## M0 — Clear the decks *(mostly decisions; ~1d)*

The items that make every later step messier the longer they wait.

- [x] **Merge PR #15** (`fix/reliability-review`) — lands the gated-traffic deploy + web timeout fix; merging FIRST avoids the known collision with step-2 Tasks 9/10 (else: deliberate rebase, its `/v1/review` idempotency work dies with the endpoint). Merged `0d95884`.
- [x] **Commit the design docs + landing-page section** as a PR (Doug reviews it, ADR-0008) — merged `240caf5` (#16).
- [x] **Decide** `workflow-summary-test-fidelity` branch: merge or drop (~49 test lines) — dropped; its only real content was already on main byte-identical, branch deleted.
- [x] **Rotate + delete** the local key at `api/.backtest-cache/llm-probe/api-key` (long-standing) — confirmed NOT in the public repo (full-history pickaxe search across all branches, file never tracked, covered by `.gitignore`), so no public exposure. Done at the Task 10 cutover, and checked rather than taken on trust: the plaintext file is gone (the whole `api/.backtest-cache/llm-probe/` directory with it), and `gcloud secrets versions list doug-anthropic-key --project doug-prod0` shows a version 2 created 2026-08-02. One loose end for whoever closes the rotation out, deliberately not ticked away here: version 1 is still `enabled` in Secret Manager, so the superseded material is still readable from it — disabling that version is a separate step from revoking the key at Anthropic, and neither is what this item was about.
- [x] **Confirm intent-stream posture** (design already assumes it): per-installation flag, default OFF for tenants, ON for dogfood, labeled experimental — confirmed in `design-lock.md:62`.
- [x] Fix stale `.env.example` (`MAGPIE_*` → current names) — trivial, stops onboarding confusion. Shipped in PR #16.

**Exit gate:** main contains #15 + the design docs; no undecided branches; no live credentials on disk.

---

## M1 — App ingest: execute step 2 with the amendments *(~10–14d)*

The reviewed 10-task TDD plan (`docs/superpowers/plans/2026-07-31-step-2-github-app-webhook-ingest.md`)
executed as written — amendments folded in at their task, never as a second pass.

- [x] Tasks 1–2: app_auth + migration runner — **with migration 002 in the same sitting**:
  `outcome_jobs` (+ UNIQUE(inst, repo, pr, merge_sha, window)), `verdicts.source` (String(64)) + `verdicts.prompt_hash`,
  `outcomes` identity columns (github_repo_id, installation_id, window_days, detail JSON),
  `installations.token_hash`. Note: the Task 6 `installation.created` token mint is superseded —
  hash-only storage makes an install-time mint unrecoverable; M2's dispense endpoint mints.
- [x] Task 3: durable job queue (`ingest.py`) — **plus** `reclaim_stalled()`, a lease-based sweep
  for claims stranded `'running'` by an instance that died mid-review. Without it such a row is
  never revivable, so `enqueue` collides forever and that SHA is silently never reviewed; adding
  `'running'` to the revivable set instead would buy a second paid read on a job still in flight.
- [x] Task 4: check run (`check_run.py`) — deviations render `unvalidated` (ADR-0007 + the
  2026-07-31 derangement FAIL); fallback tier visible in the **title**, never a footnote.
  Merged #20. Its review also fixed a live bug outside the brief: `verdict_from_reader` dropped
  every finding's severity, so the check run — Doug's only PR surface — showed none of them.
- [x] Task 5: worker drain — **calls `reclaim_stalled()` once per pass before the first claim**
  (the other half of Task 3's fix; a young claim is left strictly alone — that test is the
  anti-double-spend guarantee). Merged #23. The amendment that added reclaim also opened a
  double-spend hole (a crash after `save_review` re-ran the whole job), closed with an
  idempotency pre-read, `store.find_verdict_by_identity`.
- [x] Task 6: webhook dispatch — **plus** the clock-start branch (`closed && merged` → outcome_jobs,
  never through review-enqueue; closed-unmerged-writes-nothing test), **plus** `pull_request_review`
  ingest → third-party verdict rows (`source='review:<login>'`, no score, no model call). The
  `installation.created` token mint that used to sit here is superseded (see Tasks 1–2); note the
  GitHub App needs its "Pull request review" event subscription enabled at the Task 10 cutover.
  Merged #27.
- [x] Task 7: reconcile-on-startup by head sha — **calls `reclaim_stalled()` before the enqueue
  sweep** (startup path only, never per-installation: the sweep is queue-wide, not per-tenant).
  Steps 1–3 merged #24. Step 4 — `reconcile_all` then `drain` in a daemon thread from the lifespan
  Task 6 created, behind `app_auth.enabled() and store.enabled()` — lands as Task 7b, which is what
  turns the primitive into a capability (the `[~]` above was there for exactly this gap). Its tests
  are new work, not the brief's: the brief shipped the wiring with none.
- [x] Task 8: ADR-0010 (neutral check run) supersedes ADR-0003 in the same commit. Merged #22.
- [x] Task 10: deploy + cutover — **resequenced ahead of Task 9** (Andrew, 2026-08-01), the reverse
  of the plan's order; the reasoning lives on the Task 9 line below, since Task 9 is the item the
  reversal constrains. Code merged `f3fcee8` (#32), operator cutover run 2026-08-01. The App path is
  verified working in production on `drewjst/doug`: a neutral check run, "Cleared · risk 0.02 · diff
  read", rendered on PR #33 — with the tier in the **title**, which is the part ADR-0010 and Task 4
  both insist on, so a deterministic fallback could not have passed for a read. What the cutover
  changed, each verified on the serving revision: `doug-api` runs as its own `doug-api-sa` service
  account instead of the default compute SA; `DOUG_GITHUB_APP_ID` **and** `GITHUB_APP_PRIVATE_KEY`
  are both deployed, so `app_auth.enabled()` is true in production for the first time — before this
  it was false and nothing could mint an installation token; `--no-cpu-throttling` is set, without
  which a background drain is suspended the moment its request returns; and Task 7b's startup sweep
  actually runs at boot, which needs both of the preceding two to be true at once. `doug-web` still
  runs as the default compute SA — held back deliberately, so a misconfigured web SA could not
  confuse the cutover — and gets its own in a follow-on PR.
- [x] Task 9: retire the CI-token review path — deletes `.github/workflows/doug-review.yml` and the
  `/v1/review` endpoint it calls. **Sequenced after Task 10** (Andrew, 2026-08-01), and this is the
  whole reason for the reversal: `doug-review.yml` is the surface producing Doug's reviews on this
  repo today, so landing Task 9 first would have left every PR reviewed by nothing — including the
  PRs fixing whatever the cutover found. Now unblocked, because the line above is ticked. Note for
  whoever takes it: deleting that workflow also deletes the job summary that has been standing in
  as the "did a review run?" signal, which is why `worker.process_job` had to start logging its
  successful outcomes first — after Task 9 the check run is the only other observable.
  **Closed (Andrew, 2026-08-05):** soak concluded, dual runs stopped. Both copies of
  `doug-review.yml` are gone along with `/v1/review`, `ReviewRequest`/`ReviewResponse` and the
  idempotency machinery (`_inflight_review`/`_replay_or_none`/`_score_and_persist`) that lived only
  in that route — `worker.process_job`'s success logging, landed above for exactly this, is now the
  check run's only companion observable. `/v1/review`'s inline auth copy died with the route: every
  operator route goes through the shared `_operator_only` gate now (`api.py`). The stale
  "(Rebase vs. merged #15 still to be done deliberately.)" parenthetical this line used to carry is
  moot — Task 9 was implemented fresh from main, so there was no old branch to rebase.
- [x] Research-corpus quarantine — **resolved as a write-time convention, not a data migration**:
  no research rows exist in the app database, so there is nothing to `UPDATE`. The sentinel
  installation plus `source='research'` at insert is documented in the migration docstring.
  Ruling recorded rather than applied silently, per the plan-intent rule.
- [x] Doug's own review of #24 found a real spend leak the in-house review had only documented:
  reconcile revives `failed` rows on every cold start, so a permanently broken PR re-armed
  `max_attempts` paid reads per restart. The first fix over-corrected — it put the cooloff in the
  shared `_revive`, which would have made a reopened PR silently unreviewable for an hour once
  Task 6 added a webhook caller. Merged #26 charges the cooloff to the *caller* instead:
  `enqueue(..., trigger=)`, live by default, and a caller opts in to the sweep's terms.
  Two do, and both say so at the call site: `worker.reconcile_all` and the
  `installation.created` handler, which is a sweep over every open PR of an installation and
  is replayable by the Redeliver button. #29 briefly let that second one inherit the live
  default — Doug caught it on its own review of #29, which is the same leak class it found on
  #24, one call site further out.

**Exit gate:** webhook-driven review live on `drewjst/doug` — deliveries 202 with dedup proven
(same delivery twice → one job), check run rendering, full suite green, CI token path gone.

---

## M2 — Safe to point at strangers *(~3–4d; blocks ANY outside install)*

- [x] Spend caps wrapping **both** model calls — the primitive landed in #25
  (`store.record_deep_read`) and sat wired to nothing until this item closed it. `_charge(scope)`
  now runs at the top of `read_diff` **and** `read_with_decisions`, before the client is even
  constructed, so the previously uncapped-and-unmetered intent read is covered on the same terms.
  `scope` is **required** on both and on `score_one`/`read_intent` — no default anywhere on the
  path, so a new caller is a `TypeError` rather than an unmetered read. Un-tenanted callers (the
  CI path, the credential probe, the CLI, the intent probe script) charge a sentinel scope, which
  kept the CI dual-run and the probe alive without letting either touch a tenant's ceiling — the CI
  path itself is retired (Task 9), so only the probe and the CLI still draw on that sentinel today.
  At the cap: `SpendCapExceeded(ReaderError)` → deterministic fallback under its own rule name,
  and the check run renders the **deterministic** tier honestly (pinned end-to-end, ADR-0010).
  **Caps are runaway guards, not plan limits** (4,000/installation/month ≈ 2,000 PRs, 1,000
  sentinel), and they are guesses until the cost lines below produce real numbers — M4 sets
  plan-shaped figures.
  **Honest limit, deliberately not papered over:** `record_deep_read` returns `True` when there
  is no ledger, so the cap is a property of deployments that have one. Production does; local
  dogfooding and the open-source path do not, and reads there are uncapped. A test asserts that
  rather than a comment claiming otherwise.
- [x] Per-read cost capture — `response.usage` was previously discarded at the one moment it was
  knowable. Each read now logs `kind` (risk vs intent), `scope`, `model`, `in=`, `out=`, emitted
  from `reader.py` so it covers **every** read including the CI path the worker never sees, and
  **before** the `stop_reason` check so a `max_tokens` truncation — billed in full, then thrown
  away — reports what it cost. No schema change: logs answer "what does a PR cost" without
  touching an existing prod table. Promoting it to the ledger is a deliberate later step.
- [x] `/v1/score/read`: **authed**, not deleted — nothing in the product calls it, but the step-2
  plan's Task 10 Step 6 uses it as the post-deploy probe that a rotated Anthropic key works on a
  live revision, which is a recurring operational need and the only check that needs no PR. It
  now carries `/v1/queue`'s `DOUG_API_TOKEN` gate; the probe command was updated to send the
  header in the same commit, since a gated endpoint plus a tokenless documented `curl` is the
  same defect moved into a doc.
- [x] Coverage integrity: paginate `list_files`, carry `changed_files` + `files_dropped`,
  `complete` ⇔ every changed file seen (a partial read can no longer render as a clean one).
  Merged #25.
- [x] `fetch_pr` fetches review state (approvals no longer hardcoded 0 — live scorer matches the
  backtested one), with graceful degradation when the reviews call fails. Merged #25.
- [x] ADR-0002 made real: cross-pin test (reader constants ≡ `llm_probe.py`), `prompt_hash` written
  per verdict. Merged #25. The previous test compared `reader.py` to itself and could not fail.
- [x] Fork-PR + bot-author exclusion from deep reads — the **fork** half merged
  #27, on both entrances to the paid path: the webhook gate never enqueues one,
  and `worker._skip_reason` refuses one that reached the queue another way.
  Both treat non-integer repo ids as a fork. **Bot-author skip shipped in #106:**
  webhook + worker refuse to enqueue/charge when `user.type == "Bot"` or the
  login ends with `[bot]`. A missing user is not a bot (proceed). Merges still
  clock (prereg §2.4). The deterministic `agent-authored` rule stays on the
  fallback tier for human-authored PRs that touch bot-shaped diffs; Dependabot
  does not buy a deep read.
- [x] Per-installation gate on the **experimental intent tier**. **This item did not exist on
  this list until 2026-08-02** — it was found by reading the cost lines #37 had just added,
  which is the first time anyone could see that the intent read is the *larger* of the two paid
  reads (`in=16601/out=1305` vs `in=14031/out=925` on #38). `design-lock.md:62` had committed
  the tier to "a per-installation flag, default OFF, ON for the dogfood install" as a red-team
  mitigation; the code had a process-wide `DOUG_INTENT` env var, and `gcp.sh` deployed it as
  `DOUG_INTENT=1`, i.e. on for every installation the service reviews. One installation exists,
  so nothing was ever mischarged — but M2's exit gate is *safe to point at strangers*, and this
  would have charged stranger #1 for an experiment whose findings are still unbelieved.
  Now `intent.enabled_for(installation_id)` over a `DOUG_INTENT_INSTALLATIONS` allowlist, with
  the installation derived from the **same scope string the spend cap charges** — so the payer
  and the opted-in party are one value and cannot drift. Un-tenanted callers (CI path, credential
  probe, CLI, intent probe) resolve to `None` and buy no intent read at all, which also halves
  the soak's intent spend. Default OFF is real: an unset allowlist enables nobody.
  The deploy config is pinned by a test, because a flag that exists only in the source is not a
  flag — and the failure mode here is *silent-off*, the safe direction and therefore the easy
  one to ship by mistake.
  **Chosen shape (Andrew, 2026-08-02): env allowlist, not an `installations` column** — no
  migration, no collision with 005 below, right-sized for one install. It becomes a column when
  the token-dispense item opens that table anyway.
- [x] Migration **005** — **UNIQUE** index on `verdicts` (installation_id, github_repo_id,
  pr_number, head_sha), partial
  `WHERE installation_id IS NOT NULL AND tier <> 'external'` so pre-App/CI rows and Task 6
  external grader rows stay able to share the four columns with Doug's scored row.
  **Renumbered 2026-08-02: 003 and 004 are taken** (#30 shipped 003, the partial
  queue indexes, and 004, `review_jobs.claim_generation`). Two jobs in one: the idempotency
  pre-read runs on every job over unindexed columns (seq scan on a table that only grows —
  harmless at dogfood volume, a cliff at tenant volume), and that pre-read is still *advisory
  only* — `save_review` converts the unique violation into an idempotent return of the
  existing id so the race floor under the pre-read does not 500 the worker.
  **Rationale rewritten 2026-08-02, because #30 changed what is left to close.** The old
  wording — "the lease bounds that window; the index closes it" — is stale: #30's
  `claim_generation` fence is stronger than a lease and now bounds it, so a late `complete`/
  `fail` from a superseded holder can neither finish the job, burn attempts, nor post a second
  check run. What the fence does **not** do is stop both holders writing: `store.save_review`
  takes no generation, so worker A can still insert a duplicate verdict after worker B
  completed, and both had already paid before either could be fenced. So this item is now
  about **ledger integrity — an honest published denominator — rather than double-spend**,
  which the fence and the spend cap between them already bound.
  Must be a migration, never a bare index (the constraint that governs columns governs indexes).
  **Shape amendment 2026-08-03:** a four-column UNIQUE with only
  `installation_id IS NOT NULL` would collide with `tier='external'` rows that share the
  same identity (`find_verdict_by_identity` already filters them out). External exclusion
  belongs in the index predicate. Migration also **dedupes** existing App-identity groups
  (keep lowest id, re-point `review_jobs`, drop dependents) before `CREATE UNIQUE INDEX`,
  so advisory-era duplicates cannot brick `apply()` on boot. Race losers enter the
  identity-replay path so they do not hang local deviations / a locally rendered check
  run on the peer's row.
- [~] **doug-web dedicated service account** — code merged #44 (`5b06214`):
  `setup()` creates `doug-web-sa` (token-only accessor); `web()` deploys with
  `--service-account`. Held back from Task 10 so a misconfigured web SA could
  not confuse the api cutover. **Ops still open:** this PR only touches `api/` +
  docs, so merge does not run `gcp.sh web` — first web deploy must use the new
  SA, then revoke the default compute SA's leftover accessor on `doug-api-token`.
- [x] Per-installation token dispense endpoint (GitHub-token-verified); scoped
  `/v1/queue`; cross-tenant read attempt → 404 (test pinned). **Two token
  classes, not one replaced:** `DOUG_API_TOKEN` survives as an unscoped
  *operator* credential — scoping everything would have deleted the CI half of
  `/v1/comparisons` mid-soak, and `doug-web` has no login to carry a tenant
  token (its dashboard is M6's gated track). Dispensed tokens resolve to one
  `installation_id` and reach `/v1/queue` alone.
  **`/v1/patterns` is operator-only permanently**, on licensing rather than
  scoping grounds: `design-lock.md:71` — nothing derived from the research
  corpus is servable across tenants, because the rationales quote
  getsentry/grafana source verbatim.
  Dispense verifies PAT-first, app-JWT-second, because the app call spends
  Doug's shared 5,000/hr REST quota on a public endpoint and the reverse order
  is an anonymous drain loop. Receipt reads are **not** in this item — they are
  M3's endpoint and inherit the same `tenancy.resolve`.
  **Honest limit:** the operator token remains superuser. M2's gate is "no
  cross-tenant read" and an operator is not a tenant, but "scoped reads" should
  not be read as more than shipped. One token per installation, too — the
  garden and a tenant's CI would share it; `installation_tokens` when that bites.
  **Second honest limit, found by the Task 5 review:** the 404 on operator-only
  endpoints does *not* hide their existence, because FastAPI serves
  `/openapi.json` and `/docs` unauthenticated and they enumerate every route on
  an `--allow-unauthenticated` service. 404 is still the right code (403 would
  be worse) and the **cross-tenant `repo` 404 is unaffected** — repo names are
  not in the OpenAPI schema — so the gate clause stands. Closing it for real is
  `FastAPI(openapi_url=None, docs_url=None)` in prod: **follow-up task, not
  done here.**

**Exit gate:** the attacker math closes — no unauthenticated paid endpoint, no uncapped spend
path, no cross-tenant read, no silent partial reads.

---

## M3 — The loop itself *(~5–7d build + 14d calendar)*

- [x] `doug/adjudicate.py` as a pure function over (job rows, revert map) + fixtures that run
  `git_labels` cases through the **live** path (live label ≡ backtest label, pinned by test).
  The pure core landed first; the Cloud Run Job that drains it is now live in the item below.
  Building it found a defect three review rounds of the pre-registration had missed: the
  window predicate had no **lower** bound, so a revert dated *before* a PR merged counted as
  a miss against it. `scripts/label_precision_delta.py` had already measured that at 6/67 on
  sentry and 6/54 on grafana, and `screen_features.py`/`rf_kamei.py` already filtered it while
  the adjudicator would not — so "live labels and backtest labels are the same event"
  (`design-lock.md:29`), the whole reason `git_labels.py` is the only detector, was false.
  `TOLERANCE_DAYS` now lives once in `git_labels.py` and both sides import it.
- [x] Cloud Run Job (2Gi) + Cloud Scheduler; repository-batched claims use
  `due_at <= now()` + `FOR UPDATE SKIP LOCKED`, a two-hour crash lease and a
  generation fence. Daily 03:00 UTC, one task, zero platform retries, so the
  pre-registered ten attempts buy ten scheduled days. Shipped in #64, deploy
  boundary corrected in #65, and verified in production on 2026-08-07:
  `doug-adjudicator-nvwqn` succeeded with an all-zero no-op summary before the
  first due clock; both session-independent SQL audits returned zero rows.
- [~] `base_ref` censoring: merge to non-default branch → `censored`, never `clean`.
  Pure fixtures and the scheduled worker path are built; production execution
  remains the live gate.
- [~] **Receipts:** `GET /v1/prs/{n}/receipt` (verdict + threshold-at-scoring +
  findings + read coverage + adjudication block + hashes) — the endpoint
  ships, reachable by the operator token (unscoped, no `receipt:read` check
  on that path) or by a dispensed token carrying the new `receipt:read`
  scope, and so does every honesty state the design named: absent read
  configuration renders as "not recorded" rather than a number, a merged PR
  with no governing verdict says so instead of silently falling back to
  `latest_verdict`, a PR merged more than once names which merge is
  `publication_governing`, a fallback-tier merge is labelled rather than
  scored as if it were a reader read, and a stamped-vs-in-force
  pre-registration hash mismatch shows both hashes rather than one.
  **Narrower than the design spec:** no top-level `url`, no per-merge
  `governing_rule` string, and "read coverage" shipped as the pre-existing
  5-field `RunCoverage` (`diff_chars`, `sent_chars`, `files_sent`,
  `files_unseen`, `file_cut`) rather than the spec's `inputs_seen` shape
  (`changed_files`, `files_dropped`, `complete` among them) — see the spec's
  "Response shape" section, now marked aspirational there. Follow-up, not
  done here.
  **What's not landed:** zero adjudications exist anywhere before the first
  due clock (2026-08-16), so the adjudicated half of the exit gate's "one
  receipt correct end-to-end" — a real adjudication block on a real merge —
  is carried today by `governing_verdict()`'s fixture pin against §2.2's SQL
  and by the honesty-state tests, not by a production receipt. Nothing
  further needs to ship for that gap to close: it closes itself the first
  time a real merge clears its 60-day window.
  Migration **8** is consumed by this slice (`verdicts.diff_budget`,
  `verdicts.read_order`, `outcome_jobs.merged_head_sha`, plus a one-time
  `verdicts.prompt_hash` backfill over historical reader rows) —
  ~~**MT3's `installations.reconciled_at` is migration 9.**~~ **Superseded
  2026-08-17:** 9 went to Front Door Phase 1a and 10 to `review_jobs.base_sha`,
  so MT3 takes **11**. MT3 also does not use `installations.reconciled_at`: a
  per-*installation* timestamp cannot say *which* repos were swept, and the
  defect it must close is a per-repo coverage hole. See
  `docs/superpowers/specs/2026-08-17-reconcile-sweep-scheduling-design.md` §4.5.
  `merged_head_sha`, captured at merge, closes pre-registration §11 item 7
  ("PR head sha at merge — not stored") **forward only**: rows written before
  this slice stay NULL, and it does not touch the locked §2.1 timestamp-match
  rule.
- [x] Check-run footer: `adjudicated N · pending M · as of <date>` + `deep reads x/200`
  this cycle. Empty is the product (`adjudicated 0` still renders). Shipped in #106.
- [x] Public Doug-on-Doug scoreboard page (dogfood proof, no auth) — `/scoreboard`
  consumes `GET /v1/showcase/scoreboard`, same `instrument_snapshot` as the footer.
  Prospective panel only; miss rate is `null` / `not yet decidable — a count, not a rate`.
  Shipped in #106.
- [~] **Pre-registration document published + hashed** (metrics, denominator, both windows,
  right-censoring, cadence). `LOCKED v8`, the atomic dual-write, guarded catch-up CLI,
  deploy lock, and production runbook are built on `m3-60-day-backfill`; production is
  unchanged until the branch merges and Task 7 runs.
  - [x] **Task 7 production catch-up: COMPLETE 2026-08-11.** Deploy pinned the v9
    lock hash (`c8e30da3…60f2`) into the Job env; dry-run reported 44 missing
    (42 `drewjst/doug`, 2 `lemahq/lema-verify`); apply inserted exactly 44 and the
    manifest verified untouched; pre- and post-Job SQL audits returned zero rows on
    all four invariants; manual execution `doug-adjudicator-srj97` completed with an
    all-zero DrainSummary (nothing due before 2026-08-16 — so the first adjudicated
    rows ever stamped will carry v9); final dry-run 0 missing / 0 mismatches /
    0 orphans with eligible_14 = existing_60 = 66; Scheduler resumed ENABLED.
    Receipt: `/tmp/doug-60-day-backfill-20260811T224751Z`, durable copy at
    `workspace/research/task7-receipt-20260811T224751Z` (outside the repo).

**Exit gate = Phase 0 dogfood gate:** drewjst/doug's own history backfilled and adjudicated with
**100% agreement vs. a manual `git log` audit** (any disagreement = detector bug = stop); one real
receipt correct end-to-end; scoreboard rendering live counts; then one full webhook-started
14-day cycle observed in prod.

---

## M4 — Onboarding + the kill-criterion interviews *(~3d + calendar; overlaps M3's clock)*

- [ ] 90-day replay productized: harvest/replay against an installation, `source='replay'`,
  structurally excluded from prospective counters; replay panel on the scoreboard, visually distinct
- [ ] Install/welcome: the dated IOU + first-adjudication date + projection of when the
  preregistered two-sided interval may first become decidable; scheduled publications
  continue on schedule at any N and may remain "not yet decidable — a count, not a rate"
- [ ] **The 3 prospect interviews**, pitched off the live dogfood scoreboard + a replay of *their*
  public repo where possible — THESIS.md standing kill criterion: **2 of 3 "that's not right" halts productization**; outcome recorded either way

**Exit gate:** three interviews done, verdict written down.

---

## MT — Multi-tenant readiness *(blocks M5's first outside install)*

The data model is already tenant-shaped and that half is done: `verdicts`
carries `installation_id` + `github_repo_id` as real keys, migration 005's
uniqueness is installation-scoped, `latest_reviews` filters inside the grouped
subquery, spend caps charge per installation, the intent tier is
per-installation, and PR #48's tokens resolve to exactly one installation.
**What is not ready is the edges** — the places where "one honest operator on a
User install" is baked in. Every item below was found by a review or a
production check on 2026-08-04, not predicted; the ordering is by when each
would bite a real tenant.

- [ ] **MT0 — Populate `installations` for the existing install.** Production
  holds **zero** rows in `installations` and `installation_repos` while
  `verdicts` holds 33 rows for installation 150424894. Its only writer is the
  `installation` webhook handler (`api.py:730`), which never fired for an App
  installed before it existed. Consequences: `insert_installation_token`
  refuses when the `installations` row is absent, so dispense still 404s for
  our own install; `reconcile_all` loops over
  `active_installations()` and is therefore a **structural no-op**, which is the
  real reason the startup sweep never enqueues (M1's soak criterion 2 recorded a
  different explanation and it was wrong). **Fix is operational** — redeliver
  the `installation` event; do **not** uninstall/reinstall, which mints a new
  `installation_id` and orphans every existing verdict.
- [x] **MT1 — Repo-admin must not mint an installation-wide token.**
  `verify_admin` proves admin on **one repo**; `mint` issues a token scoped to
  the **whole installation**. Identical on a User install, which is why it was
  invisible. On an org install covering all repositories, admin on any single
  repo reads every repo's PR titles, authors and reader rationales across the
  org — data GitHub itself would not show that person — and the same call
  silently rotates the org's live token. **Closed** —
  `docs/superpowers/specs/2026-08-04-tenant-api-keys-design.md`: mint authority
  now covers the selection (proof covers selection), so a repo-admin proof
  mints only a `selected`-repo token and org-admin proof is required for `all`.
- [x] **MT2 — Uninstall must revoke.** `tenancy.resolve` matches on
  `token_hash` and never reads `installations.state`; the uninstall webhook
  clears the repo list and leaves the hash. Uninstalling is the tenant-facing
  revocation gesture and today it does nothing. Acceptable while the tenant is
  us; not acceptable when it is someone else. **Closed** —
  `docs/superpowers/specs/2026-08-04-tenant-api-keys-design.md`: resolve
  intersects every call against the live ledger, and the uninstall webhook
  now bulk-revokes the installation's keys outright.
- [ ] **MT3 — the reconcile sweeps must not scale by repo count.** No cap on
  repos per installation and no call budget (the existing
  `_MAX_OPEN_PRS_PER_REPO` bounds PRs *per repo*, not repos). A 10k-repo
  installation is ≥10k REST calls per cold start, on a scale-to-zero service
  where cold starts are frequent — and the loop is **serial across
  installations**, so one large tenant delays every tenant behind it. Fixing
  MT0 exposes this rather than causing it.
  **Scope corrected 2026-08-17:** this item said `reconcile_all`, but
  `reconcile_outcomes` has the identical uncapped `active_repos` loop and is
  the more expensive lane (a `pulls.get` per merge in the window, per repo,
  per installation). Both are in scope; the scheduling primitive is built once.
  **And the item is a correctness item, not a scaling one:** `active_repos`
  has no `ORDER BY` and `reconcile_all`'s only caller is a daemon thread
  (`api.py:188`) that scale-to-zero reaps, so on a large installation the
  repos past the reaping point are never swept on *any* cold start. A silent,
  permanent coverage hole, not slowness.
  Design: `docs/superpowers/specs/2026-08-17-reconcile-sweep-scheduling-design.md`.
  (Next free migration: **11** — 9 is Front Door Phase 1a and 10 is
  `review_jobs.base_sha`; the earlier "next free: 9" note here was stale.)
- [x] **MT4 — One source of truth for repo authorization.** The `?repo=` scope
  check reads `installation_repos.full_name` (annotated *display only* in
  `store.py`) while row filtering reads `verdicts.installation_id`. Traced as
  failing closed in every direction by two independent reviewers, so no leak —
  but it means the unfiltered queue can return rows for a repo that `?repo=`
  404s. **Closed** — `docs/superpowers/specs/2026-08-04-tenant-api-keys-design.md`:
  authorization and row filtering both key on `github_repo_id` via the active
  `installation_repos` ledger, id-unifying `?repo=` with the queue.
- [x] **MT5 — Rate-limit dispense.** `POST /v1/installations/token` is public
  by design and unthrottled. A caller who administers *any* repo passes check
  one, so check two spends Doug's app-JWT quota on a 404; repeated calls also
  rotate a live token, denying the tenant's own integration. The obvious
  mitigation (consult the ledger first) collides with MT4 — decide them
  together. **Closed** — `docs/superpowers/specs/2026-08-04-tenant-api-keys-design.md`:
  mint is append-only (no more rotate-by-remint DoS) behind PAT-first proof,
  plus a fail-open daily mint cap per installation.

**Open design question — the credential model itself.** Andrew (2026-08-04):
*lema has an API key system worth borrowing.* Doug's current model is one
opaque token per installation, hash-only, rotate-by-remint, with no scopes, no
expiry, no per-consumer attribution, and no record that a mint happened
(`mint` writes no `updated_at`). MT1, MT2 and MT5 are all symptoms of that
shape rather than independent bugs, so **evaluate lema's design before fixing
them one at a time** — a keys-with-scopes model may close all three at once and
would also answer the garden/CI sharing problem PR #48 recorded as a stated
limit. Doug and lema stay separate products; this is borrowing a pattern, not
coupling them. **Decided** (2026-08-04): adopt a keys-with-scopes model —
the repo-selection design in
`docs/superpowers/specs/2026-08-04-tenant-api-keys-design.md`, built on this
branch, which closes MT1, MT2, MT4 and MT5 above.

**Exit gate:** MT0 and MT1 closed, and a second installation on a different
account reads only its own rows — proven against the real ledger, not fixtures.

**PROVEN 2026-08-05.** `api/deploy/prove-isolation.sh` ran 16/16 against prod:
installations 150424894 (drewjst) and 151500529 (lemahq, `lema-verify`), each
`all`-key seeing only its own rows, cross-account `?repo=` 404ing both ways,
key lists tenant-scoped, cross-tenant revocation refused, same-tenant
revocation dead next request. MT0 was closed operationally the same day
(suspend/unsuspend + repo re-add fired fresh webhooks; the original deliveries
had aged out — the redeliver-don't-reinstall rule held). The run also caught
two live defects on its way in: the pepper secret's trailing newline (45
bytes; `b64decode(validate=True)` refuses `\n`) and githubkit clients being
GC'd mid-call-chain (#52) — an executable gate earns its keep.

---

## M5 — First design partners *(calendar-gated)*

- [ ] App visibility → "Any account" *(gated on MT above)*
- [ ] Onboard 2–3 design partners: $99/installation hand-invoiced, allowance rows, meter visible day 1
- [ ] 30 days of fill: prospective counters ticking on a real tenant, zero cross-tenant reads
- [ ] 60-day clocks mature; **first pre-committed publication ships on its date, good or bad**

**Exit gate:** the first published number exists with N + CI + censoring rate, on schedule.

---

## M6 — Gated tracks *(each fires on its trigger — no dates)*

| Track | Trigger | Ref |
|---|---|---|
| MCP garden service (`doug.check`, AGENTS.md fragment export) | adjudicated rows ≥ min-n on ≥1 tenant | design-lock T4, addendum A3 |
| Tenant dashboard (WorkOS, tenancy steps 3–4) | **PULLED FORWARD 2026-08-08 ahead of its trigger** — see note below | `2026-08-08-front-door-design.md` |
| Evidence refinery (offline council) | enough adjudicated data to mine; becomes the panel-experiment harness | addendum A1 |
| Live specialist panel — **pre-registered experiment** | refinery harness ready; paired shadow PR-level review-quality gate beats a compute-matched grounded reader; separate surfaced canary required before downstream causal claims | addendum G1 |
| Champion–challenger shadow models | model price/retirement event, or matured outcome set | addendum A2 |
| Staging GCP project | tenant #2 or first deploy-caused incident | design-lock open risk 1 |
| Derangement **positive control** (decision records) | pre-registered before any further intent investment; passes → deviations believed, fails → pull the stream | HANDOFF 2026-07-31 |
| Underwriter shadow probe (loss-ratio SQL) | ≥2 quarters adjudicated data on real tenants | IDEAS.md 2026-07-31 |
| Public cross-repo garden | its own design pass; never before the private garden earns "pattern" | design-lock non-goals |

**The tenant-dashboard track started early, deliberately (Andrew, 2026-08-08).**
Neither trigger had fired — there are two tenants, and no tenant has asked —
and this reverses the 2026-08-06 ruling that "WorkOS auth is a detour from the
dogfooding pain." Recorded as an override rather than drifted into. What
changed: the existing dogfood installation *cannot* test self-serve onboarding,
because installation 150424894 was populated operationally (MT0, by redelivering
a webhook) and carries no WorkOS identity, so the bind step is precisely the
thing it cannot exercise. The first real tenant is `coldworkshq/coldworks` — an
**org** install on a **private** repo, which also exercises what a User install
structurally cannot (MT1 hid for a year because repo-admin and installation-wide
scope are indistinguishable on a User install).

Design: `docs/superpowers/specs/2026-08-08-front-door-design.md`. Three phases.

- [x] **Phase 0 — take the operator credential off `doug-web`.** Plan:
  `docs/superpowers/plans/2026-08-08-front-door-phase-0.md`. Public
  `GET /v1/showcase/queue` pinned by `DOUG_SHOWCASE_REPO`; both public pages
  repointed; `DOUG_API_TOKEN` removed from the deploy flag *and* the Secret
  Manager binding; `web/`'s first tests plus a guard against reporting zero
  tests as a pass, wired into CI.
- [ ] **Phase 1 — auth, install, bind, tenant surface.** HARD GATE FIRST: no
  documentation states end-to-end that the token a WorkOS GitHub-**App**
  connection returns is a *user-to-server* token that `GET /user/installations`
  answers for. The entire entitlement model rests on that inference. Prove it
  with one live call before writing a line.
- [ ] **Phase 2 — marketing and custom domain.** Deliberately last; everything
  before it is built against `*.run.app`.

Two corrections this design already forced on prior thinking, both load-bearing:
`GET /user/installations` answers on **`:read`**, not admin, so it reports what a
user may *see*, never what they may *control* — a session must carry per-user
`repo_ids`, never installation-wide. And GitHub does **not** document propagating
`state` to a GitHub App's Setup URL, so the bind flow uses a signed HttpOnly
cookie instead.

---

## PC — Public-corpus track *(parallel; touches scripts and spend, never the product path)*

Leverages the built-and-tested backtest machinery (`harvest`/`git_labels`/`replay`) and the
existing 653-PR corpus. Inherits the standing discipline without exception: **bars pre-registered
before any spend, failures recorded, spent holdouts stay spent, frozen prompt only** (reads stay
comparable), permissive-license filter + citations for anything served onward, and public-corpus
rows live in their own store — quarantined from every tenant counter and every published tenant rate.

- [ ] **PC1 — Repo #3–#5 replication** (~$40 in batch reads; can start now): pre-register AUC
  bars, harvest three diverse permissively-licensed repos (incl. one non-Python, one monorepo),
  read newer slices, publish the replication table. Each survivor strengthens the core claim;
  a failure is recorded and caps the transfer story honestly.
- [ ] **PC2 — Garden evidence base** (~$250–500; **gated on PC1 showing transfer**): scale to
  10–20k read PRs across 10–15 permissive repos filtered to the observable entry domain (schema
  migrations first), then run the three pre-registered garden probes from IDEAS.md — survival-signal
  separation, variant separation, migration-episode reconstruction. Pass → the public garden tier
  has its evidence basis and the private garden's cold start gets a day-1 fallback; fail → the
  word "pattern" stays locked and we say so.
- [ ] **PC3 — Prospect replays** (≈ free; lands with M4): replay each interview prospect's public
  repo beforehand; walk in with their own 90 days adjudicated.
- [ ] **PC4 — Bureau seed** (research; no bar yet): harvest bot-authored PRs at scale across
  popular public repos; measure per-author-type revert rates with stratified base-rate controls;
  pre-register before any claim. Feeds the bureau → underwriter staircase (IDEAS.md 2026-07-31).

**Existing-asset conversions (no new spend):** the 653-corpus becomes the refinery dry-run fixture
set and the champion–challenger evaluation set; the hand-audit files seed receipt content; the
replication table is the honest sales one-pager.

---

*Sequencing rationale in one line: every milestone makes the next one's failure mode impossible —
#15 before ingest (collision), migration before columns (no second mechanism), caps before
strangers (spend), dogfood before partners (the gate), publication before scale (the promise) —
and the PC track runs beside it all, spending only against pre-registered bars.*
