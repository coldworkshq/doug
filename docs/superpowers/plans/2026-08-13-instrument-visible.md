# Instrument Visible (Approach A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (tasks are sequential: snapshot → footer → scoreboard API → page → copy → bot skip). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Doug's outcome instrument visible: every check run shows `adjudicated N · pending M`, a public `/scoreboard` page shows the same numbers from the same query, landing copy stops overclaiming, and bot-authored PRs no longer buy deep reads.

**Architecture:** One ledger query (`store.instrument_snapshot`) is the only source of the counters. The check-run footer, `GET /v1/showcase/scoreboard`, and the public `/scoreboard` page all consume that snapshot. Denominator is `count(outcome_jobs)` split by `status='done'` vs not — never `count(outcomes)`. Deep-read meter is a read of `deep_read_counters` against the $99 plan cap of 200, not the 4000 runaway guard.

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy (api), Next.js 16 / Tailwind 4 (web). Tests: `uv run pytest` in `api/`, `node --test` on `web/lib/**/*.test.mjs`.

**Spec:** `docs/superpowers/specs/2026-08-13-unbeatable-doug-research.md` §4.

## Global Constraints

- Doug never writes code, never opens a PR, never blocks. Check conclusion stays `neutral`.
- Nothing outcome-derived enters `score()`.
- Publication denominator is `count(outcome_jobs WHERE status='done')` for the installation+repo. Never `count(outcomes)`.
- Footer empty state is the product: `adjudicated 0` still renders.
- No 90-day replay, no bot-comment parsing, no MCP, no convergence on receipt, no garden, no prompt v2.
- Landing copy: no "learns" as a marketing verb; no "repos like yours"; Rule 03 is future tense until first publication. Evidence panel `—` stays.
- Bot-author skip matches fork skip: webhook + worker refuse to enqueue/charge. Merges still clock.
- Plan deep-read cap shown on surfaces: **200**. Runaway cap in `reader.py` stays 4000.
- TDD: failing test first, watch it fail, then implement.
- Commands from repo root unless noted. API tests: `cd api && uv run pytest <file> -q`. Web: `cd web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test --experimental-strip-types lib/<file>.test.mjs`.

---

### Task 1: Instrument snapshot (publication query)

**Files:**
- Create: `api/tests/test_instrument.py`
- Modify: `api/doug/store.py` (add `PLAN_DEEP_READ_CAP`, `InstrumentSnapshot`, `instrument_snapshot`)

**Interfaces:**
- Produces:
  - `PLAN_DEEP_READ_CAP = 200`
  - `@dataclass(frozen=True) class InstrumentSnapshot` with fields: `adjudicated: int`, `pending: int`, `as_of: datetime`, `first_due: datetime | None`, `deep_reads: int | None`, `deep_read_cap: int`, `miss_rate: None`
  - `instrument_snapshot(installation_id: int, github_repo_id: int, *, now: datetime | None = None) -> InstrumentSnapshot | None` — `None` when no ledger (`DATABASE_URL` unset)

- [ ] **Step 1: Write failing tests** in `api/tests/test_instrument.py` covering: empty ledger → 0/0; done vs pending split; two windows of one PR count as two jobs; other installation/repo excluded; `first_due` is min pending `due_at`; deep_reads from `deep_read_counters` for `installation:{id}` current UTC month; no-row meter is 0 not None; source of `instrument_snapshot` must not mention `outcomes` as a table (inspect `store.py` function body); when DATABASE_URL unset, returns None.

- [ ] **Step 2: Run tests, confirm FAIL** (`function not defined` / import error).

- [ ] **Step 3: Implement `InstrumentSnapshot` + `instrument_snapshot` in store.py.** Query only `outcome_jobs` and `deep_read_counters`. `adjudicated = count(status=='done')`, `pending = count(status!='done')`. Use `reader.installation_scope` for the meter key.

- [ ] **Step 4: Tests pass.** Commit.

---

### Task 2: Check-run footer

**Files:**
- Modify: `api/tests/test_check_run.py`
- Modify: `api/doug/check_run.py` (`render` gains optional `instrument`)
- Modify: `api/doug/worker.py` (fetch snapshot, pass in)

**Interfaces:**
- Consumes: `store.instrument_snapshot`, `store.InstrumentSnapshot`
- Produces: `check_run.render(..., instrument: InstrumentSnapshot | None = None)` appends two footer lines when instrument is not None:
  - `adjudicated N · pending M · as of YYYY-MM-DD` and, when `adjudicated == 0` and `first_due` is set, ` · first due YYYY-MM-DD`
  - `deep reads x/200 this cycle` (omit the meter line when `deep_reads is None`)
- `check_run.FOOTER_EMPTY` / format helpers if needed so worker and tests share the string.

- [ ] **Step 1: Failing tests** — render with a zero snapshot still contains `adjudicated 0`; render without instrument does not invent a footer (existing tests stay green); footer uses `as of`; N=0 includes `first due`; never contains a live miss-rate number.

- [ ] **Step 2: Watch FAIL.**

- [ ] **Step 3: Implement footer in `render`; worker calls `store.instrument_snapshot(job['installation_id'], job['github_repo_id'])` at both render sites (`_replay_existing` and `process_job`).**

- [ ] **Step 4: Tests pass including existing check_run suite.** Commit.

---

### Task 3: Public scoreboard API

**Files:**
- Modify: `api/tests/test_api.py` (showcase scoreboard tests, next to showcase queue)
- Modify: `api/doug/api.py` (`GET /v1/showcase/scoreboard`)
- Modify: `api/doug/store.py` (`instrument_snapshot_for_repo(full_name, *, now)`)
- Modify: `api/tests/test_deploy_gcp.py` + `api/deploy/gcp.sh` to smoke the new route

**Interfaces:**
- `instrument_snapshot_for_repo(repo: str, *, now=None) -> InstrumentSnapshot | None` — resolve `github_repo_id` (+ installation_id) from `installation_repos` active rows matching `full_name`, else from `review_jobs`. If multiple installations, pick the one with any outcome_jobs, else the first. Showcase is one repo.
- `GET /v1/showcase/scoreboard` — unauthenticated, pinned to `DOUG_SHOWCASE_REPO`, 404 if unset or no ledger. Same Cache-Control as queue. Ignores `?repo=`. Body JSON of the snapshot (`as_of`/`first_due` ISO-8601, `miss_rate: null`, `decidable: false`, `label: "not yet decidable — a count, not a rate"`).
- Response model `ScoreboardResponse`.

- [ ] **Step 1: Failing tests** — 404 when unset; 200 without token; ignores `?repo=`; empty jobs → adjudicated 0; does not use `count(outcomes)`; deploy smokes `/v1/showcase/scoreboard`.

- [ ] **Step 2–4: Implement, pass, commit.**

---

### Task 4: Public `/scoreboard` page

**Files:**
- Create: `web/lib/scoreboard-shape.ts`, `web/lib/scoreboard-shape.test.mjs`, `web/lib/scoreboard-fixture.json`
- Modify: `web/lib/api.ts` (`getScoreboard`)
- Create: `web/app/scoreboard/page.tsx`
- Modify: `web/components/site-header.tsx` (add Scoreboard nav link)

**Interfaces:**
- `isScoreboardResponse(body)` — required fields: `adjudicated`, `pending`, `as_of`, `first_due` (null ok), `deep_reads` (null ok), `deep_read_cap`, `miss_rate` (must be null), `decidable` (must be false), `label`.
- Page shows prospective panel only (no replay). Copy includes `not yet decidable — a count, not a rate`. Distinct from `/queue`. Fixture fallback labelled sample, same honesty pill pattern as landing.

- [ ] **Step 1: Shape tests fail (module missing).** Implement shape + fixture + fetch + page + nav. Pin header href `/scoreboard` in a small source-read test if no existing header test.

- [ ] **Commit.**

---

### Task 5: Landing copy honesty

**Files:**
- Create: `web/lib/landing-copy.test.mjs`
- Modify: `web/app/page.tsx`

Banned in `web/app/page.tsx` (mutation proofs):
- `repos like yours`
- Layer title `Learns what production did` (body may keep clock language)
- Hero/h2 `Doug learns what production did`
- Rule 03 present-tense `is counted, dated, and published` without future/will

Keep: evidence panel `Published miss rate` / `—`.

- [ ] **Step 1: Write the pin test against current file — it FAIL on the banned strings.**
- [ ] **Step 2: Confirm FAIL.**
- [ ] **Step 3: Fix copy.** Hero scores *this repo's* reverts / research repos. Layers title → `Every merge starts a clock`. H2 → counts/dates. Rule 03 → will be published on the locked cadence.
- [ ] **Step 4: Pin test passes.** Commit.

---

### Task 6: Bot-author deep-read skip

**Files:**
- Modify: `api/tests/test_worker.py`, `api/tests/test_api.py`
- Modify: `api/doug/worker.py` (`_skip_reason` returns `"bot"`)
- Modify: `api/doug/api.py` (`_enqueue_pull_request` same gate)

Detection (same as `review.py`): `user.type == "Bot"` OR `login.endswith("[bot]")`. Missing user is not a bot (proceed). Merges still clock — `_record_merge` has no fork/bot gate.

- [ ] **Step 1: Failing tests** — webhook Dependabot PR 202s and writes no `review_jobs`; worker `_skip_reason` returns `"bot"` for Bot user; human still None; merge of a bot PR still writes `outcome_jobs`.
- [ ] **Step 2–4: Implement, pass, commit.**

---

### Task 7: Full verification

- `cd api && uv run pytest` — 0 failures
- `cd api && uv run ruff check .`
- `cd web && npm test`
- `cd web && npm run lint`
- `cd web && npm run build` (scoreboard route must compile)
- Mutation: temporarily make snapshot count `outcomes` rows — the inspect test must fail; restore.

---

## Spec coverage

| Spec §4 | Task |
|---|---|
| 4.1 Check-run footer | 2 |
| 4.2 Public scoreboard | 3, 4 |
| 4.3 Publication query | 1 |
| 4.4 Landing copy | 5 |
| 4.5 Bot-author skip | 6 |
| 4.6 Not in increment | no tasks |
| 4.7 Exit gate / mutation proofs | 1 inspect test, 2 empty footer, 5 copy pin, 7 suite |
