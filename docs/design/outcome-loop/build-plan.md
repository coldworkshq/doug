# Build Plan: The Outcome Loop

**Companion to:** `design-lock.md` (decisions — read first), `product-spec.md` (claims). Architect + PE voice. All anchors are `api/` paths unless noted; "the plan" = `docs/superpowers/plans/2026-07-31-step-2-github-app-webhook-ingest.md`.

## Architecture on the real seams

The loop is four attachments to code that exists (or that step 2 creates), one new Job, and zero new frameworks.

**Seam 1 — the webhook handler (plan Task 6; today `doug/api.py:348-373` verifies and discards).** The clock-start amendment: `closed` joins the `handled` table (plan:3111-3115) with its own dispatch branch — it must never enter `PR_ACTIONS`/review-enqueue (plan:2980-2982: closed must not buy a read). `closed && merged` writes `outcome_jobs` rows (windows 14 now, 60 via backfill); `closed && !merged` writes nothing (new test). `pull_request_review` events (new subscription) insert third-party verdict rows: `source='review:<login>'`, state approved/changes_requested, no score, no model call — adjudicable but never metered.

**Seam 2 — the schema (plan Task 2, `migrations.py`).** Migration 002, same runner:
- `outcome_jobs(installation_id, github_repo_id, pr_number, merge_commit_sha, merged_at, base_ref, window_days DEFAULT 14, due_at, status, attempts)` + `UNIQUE(installation_id, github_repo_id, pr_number, merge_commit_sha, window_days)`. The unique key is the dedup against GitHub redelivery — same mechanism as `review_jobs` (plan:720-743).
- `outcomes` += `github_repo_id, installation_id, window_days, detail JSON` (`store.py:77-86` today has none — the join re-keys on ids; `repo` string becomes display-only, closing the caller-controlled-string hole at `store.py:332-334`).
- `verdicts` += `source, prompt_hash` (`store.py:42-61`).
- Research rows: sentinel installation + `source='research'` (one UPDATE post-migration).

**Seam 3 — the adjudicator (new: `doug/adjudicate.py` + a Cloud Run Job).** Scheduler → Job (2Gi) → claim `due_at <= now() AND status='pending'` `FOR UPDATE SKIP LOCKED` (drain shape identical to plan Task 3's `ingest.py`). Revert map from `backtest/git_labels.py:236-294` — reused verbatim, treeless clone (`:48-101`); it is the same detector the backtest validated, so live and historical labels are the same event. Core is a pure function `adjudicate(jobs, revert_map) -> list[Outcome]`: `revert` (with anchor+revert shas in `detail`), `clean` only when `base_ref` == cloned default branch (else `censored` — the `--single-branch` blindness guard), append-only, no UPDATEs. **Denominator = `count(outcome_jobs WHERE status='done')`**, never `count(outcomes)` (`store.py:335-337` multi-rows).

**Seam 4 — surfaces.** Check-run summary (plan Task 7 / ADR-0010) gains: receipt content, monotone counters ("N adjudicated · M pending, as of <date>"), meter line ("deep reads: 143/200"). Receipts: `GET /v1/prs/{number}/receipt` beside `/v1/queue` (`api.py:207-284`), scoped by per-installation token (minted in Task 6's `installation.created` handler, hash in `installations` — plan:701; dispensed via a GitHub-token-verified endpoint reusing `api.py:92-94`). Public Doug-on-Doug scoreboard: extend `web/app/queue/page.tsx` + one aggregate endpoint, no auth (it's our data, deliberately public). Tenant dashboards: NOT here (tenancy spec steps 3-4).

**Blast radius:** `api.py` (handler branches, receipt route), `store.py` (identity columns, scoped reads — `pattern_join`/`latest_reviews` take required scope; ~3 prod call sites), `review.py` (paginated `list_files`, review-state fetch, coverage args), `reader.py` (Coverage fields; spend caps around BOTH calls incl. the uncapped `:372`), new `adjudicate.py`, migrations, one Job + one Scheduler entry in `deploy/gcp.sh`. Untouched: `scoring.py` rules, the frozen prompt bytes, `backtest/` (consumed, not modified), `features.py`.

## Phased plan

**Phase 0 — dogfood gate (nothing proceeds until green).** Run the loop on Doug itself (ADR-0008) end to end: backfill `outcome_jobs` from drewjst/doug's merge history, adjudicate, verify against `git log` by hand. **Passed means:** every merged PR since ADR-0008 has exactly one 14-day job row; adjudications match a manual audit 100% (any disagreement is a detector bug — stop); the public scoreboard renders real counts; one receipt for a real Doug PR reads correctly end to end; and the pre-registration document (metrics, denominator, windows, censoring, cadence) is published with its hash landing in receipts. This is also the first credible artifact for the 3-prospect kill-criterion conversations — which are themselves Phase 0's exit interview: pitch three prospects with the dogfood scoreboard; 2+ "that's not right" halts productization (THESIS.md standing criterion).

**Phase 1 — step 2 + amendments (~10-14 eng-days).** Execute the step-2 plan Tasks 1-10 as reviewed, plus: migration 002 (above) in Task 2; clock-start + review-ingest branches in Task 6; prompt-hash write + the ADR-0002 cross-pin test (constants vs `scripts/llm_probe.py` — today's `test_reader.py:62-64` is self-referential); coverage integrity in Task 5's orbit (paginate `list_files` at `review.py:54-56,88-90`; drop-tracking for `patch=None` at `:77-81,110-114`; `complete` requires `files_sent == changed_files`); intent per-installation flag default OFF (dogfood ON); spend caps (timeout, retry cap, per-installation monthly cap) wrapping both model calls — `reader.py:313-319` AND the uncapped `:372`; `/v1/score/read` authed or deleted. Mind the known collisions: branch `fix/reliability-review` vs Tasks 9/10 (rebase deliberately; its `/v1/review` idempotency work dies with the endpoint), and ship ADR-0010 in the check-run commit.

**Phase 2 — the loop (~5-7 eng-days).** `adjudicate.py` + Job + Scheduler; receipts endpoint + per-installation tokens; check-run counters + meter; public scoreboard page. Gate: Phase 0 re-run green on the *live* path (webhook-started clocks, not backfill), one full 14-day cycle observed in prod.

**Phase 3 — first tenants (~5 eng-days + calendar time).** App visibility to "Any account"; fork-PR/bot deep-read exclusion verified; onboard 2-3 design partners at $99 hand-invoiced (allowance rows); install-time projection copy; 60-day backfill runbook staged (hard gate before first publication). Gate: a paying tenant's scoreboard fills for 30 days with zero cross-tenant reads (test it: token A must 404 on tenant B's receipt).

**Phase 4 — v1.5 garden (gated, not scheduled).** Triggers in `product-spec.md`. Separate Cloud Run service, same image; `doug.check` serving adjudicated history with n+provenance inline; AGENTS.md fragment export (customer commits it). Blocked behind: min-n adjudicated rows on a real tenant + the three IDEAS.md probes for the word "pattern."

## Test-for-intent strategy

Tests pin *why*, on real rows, not mocks of the world:
- **Dedup is the denominator:** deliver the same `closed` webhook twice → exactly one `outcome_jobs` row; two windows → two rows, one adjudication each. (Kills the double-timer redelivery bug by construction.)
- **A merge never buys a read:** `closed && merged` produces outcome_jobs and zero review_jobs / zero model-call attempts.
- **Censoring is honest:** merge with `base_ref='release-2.4'` → `censored`, never `clean` (the false-clean survivorship guard); non-default-branch adjudication can only tighten, never relax.
- **Same detector both sides:** adjudicator fixtures are `git_labels` cases (nested `#N`, body-sha with ambiguous-prefix refusal, "Reland" non-revert) run through the *live* path — if live and backtest ever classify a commit differently, a test fails, because published rates are only comparable to the validated evidence if the label is the same event.
- **Coverage can't lie:** a fixture PR with 150 files + one binary → `complete=False`, `files_dropped` populated, receipt and meter show it.
- **Counters are monotone:** adjudicated count never decreases; backfilled research rows never enter any tenant counter (sentinel-installation exclusion pinned).
- **Tenancy fails closed:** every read helper without a valid installation scope errors; token A on tenant B's receipt → 404.
- **Spend is bounded:** cap exhausted → deterministic verdict labeled fallback, no model call, loud reason — mirroring the existing `reader-unavailable` contract (`api.py:162-167`).
- Adjudication logic tests are pure-function tests over row fixtures — no GitHub, no Anthropic, no scheduler fakes. If a loop test needs all three mocked at once, the seam is wrong (PE red-line upheld).

## Build from here

1. `git checkout -b step-2-execution` and execute the step-2 plan's Task 1 (fixtures) and Task 2 — **write migration 002 into Task 2's runner in the same sitting** (the schema above, verbatim). First commit: migrations + models + tests.
2. Task 6 lands the clock-start branch + `closed`-unmerged test + `installation.created` token mint; Task 5/7 orbit picks up coverage integrity, prompt-hash, cross-pin test, spend caps.
3. `doug/adjudicate.py` next to `doug/review.py`, first as pure function + fixtures; wire the Job in `deploy/gcp.sh` after Tasks 9/10 land.
4. Backfill Doug's own history; run Phase 0; publish the pre-registration; book the three prospect calls.
5. Everything goes through PRs — Doug reviews each one (ADR-0008), and every one of those verdicts is itself a row the loop will grade. The instrument dogfoods its own construction.
