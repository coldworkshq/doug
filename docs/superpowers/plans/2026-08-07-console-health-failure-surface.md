# Console Health Strip and Failure Surface (Phase 2a) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a failing Doug job visible in the operator console, in both the
review lane and the M3 outcome lane, without ever claiming a health state the
ledger does not support.

**Architecture:** Two read-only operator endpoints split by what each claims —
`GET /v1/health` returns fixed-size aggregates and no rows so the always-on
strip stays cheap; `GET /v1/jobs` returns rows in the same
`{items, limit, offset}` envelope `/v1/runs` already uses. The query layer
(`store.py`) stays pure SQL and receives the lane constants as arguments,
because `ingest` and `outcome_queue` both import `store` and the reverse
would be an import cycle. All console classification lives in one pure
`lib/health.ts` module so the existing `node --test` tooling can pin it.

**Tech Stack:** FastAPI + SQLAlchemy Core + Pydantic (api), pytest (api
tests), Next 16 App Router + React 19 + Tailwind 4 (console), `node --test`
with `--experimental-strip-types` (console tests).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-07-console-health-failure-surface-design.md`. Every decision below traces to it.
- **Read-only.** No endpoint in this plan mutates any row. No requeue, no retry, no clearing.
- **`superseded` is counted nowhere** — not as a failure, not as unhealthy, not in any strip cell.
- **Lane constants are never hardcoded in the console.** They travel in the `/v1/health` payload, per lane.
- **`as_of` is the database clock**, never the API process's wall clock and never the browser's.
- **No fixture fallback in the console, ever.** An unreachable API renders an explicit failure state.
- **Empty is not zero, and unknown is not clear.** These are three distinct renderings.
- **Colour is never the only carrier.** Every strip cell renders icon + word + count.
- **New API routes are operator-only** behind the existing `_operator_only(x_doug_token)` gate.
- Run api tests from `api/`: `uv run pytest`, and `uv run ruff check .`
- Run console tests from `console/`: `npm test`, and `npm run lint`

---

## File Structure

**API**
- `api/doug/ingest.py` — modify: promote the review attempt cap to a module constant.
- `api/doug/store.py` — modify: add `_db_now`, `job_health()`, `job_rows()`.
- `api/doug/models.py` — modify: add the health and job response models.
- `api/doug/api.py` — modify: add `GET /v1/health` and `GET /v1/jobs`.
- `api/tests/test_store.py` — modify: query-layer tests.
- `api/tests/test_api.py` — modify: endpoint and gate tests.

**Console**
- `console/lib/health.ts` — create: the pure classifier, the two console-owned constants, and the derived display types.
- `console/lib/health.test.mjs` — create: its tests.
- `console/lib/api.ts` — modify: `getHealth()`, `getJobs()`, and their response types.
- `console/components/health-strip.tsx` — create: the strip, replacing the ghosted placeholder.
- `console/components/shell.tsx` — modify: render the real strip, widen `active`, add the Jobs nav tab.
- `console/components/jobs-table.tsx` — create: the two-lane table.
- `console/app/jobs/page.tsx` — create: the `/jobs` route.
- `docs/superpowers/specs/2026-08-06-doug-console-design.md` — modify: the two corrections.

---

### Task 1: Promote the review attempt cap and add the health query

The review lane's cap of 3 currently exists **only** as a default parameter on
`ingest.fail(..., max_attempts: int = 3)`. There is no constant to read, so
the health endpoint would have to hardcode a literal `3` that could silently
drift from the value the queue actually enforces. Promoting it is a
behaviour-preserving one-line change that gives both callers one source of
truth, matching `outcome_queue.MAX_ATTEMPTS = 10`, which already is one.

`store.py` also has no database-clock helper, and it needs one.
`_db_now`/`_as_utc` are currently defined **three times** — `ingest.py:102`,
`outcome_queue.py:57`, `outcome_backfill.py:118` — with identical bodies. A
fourth copy in `store.py` is the wrong fix. All three of those modules
already import `store`, so `store` is the natural single home and no cycle
exists in that direction. This task consolidates them (Andrew's call,
2026-08-07, before execution).

**Files:**
- Modify: `api/doug/ingest.py` (add `MAX_ATTEMPTS`, change `fail()`'s default, drop the local clock helpers)
- Modify: `api/doug/outcome_queue.py` (drop the local clock helpers)
- Modify: `api/doug/outcome_backfill.py` (drop the local clock helpers)
- Modify: `api/doug/store.py` (add `_as_utc`, `_db_now`, `job_health`)
- Test: `api/tests/test_store.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `ingest.MAX_ATTEMPTS: int` (= 3)
  - `store._db_now(conn) -> datetime` and `store._as_utc(value) -> datetime`, now the single definitions; `ingest`, `outcome_queue` and `outcome_backfill` import them from `store`.
  - `store.job_health(*, review_lease_seconds: int, review_max_attempts: int, outcome_lease_seconds: int, outcome_max_attempts: int, repo: str | None = None, installation_id: int | None = None) -> dict | None` — returns `None` when no ledger is configured, otherwise a dict with keys `review`, `outcome`, `as_of`. `review` holds `pending, oldest_pending_at, retrying, oldest_retry_at, running, stalled, failed, failed_24h, stall_lease_seconds, max_attempts`. `outcome` holds `pending, overdue, next_due_at, oldest_overdue_due_at, running, stalled, failed, stall_lease_seconds, max_attempts`. All counts are `int`; all `*_at` values are `datetime | None`.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_store.py`:

```python
# store.job_health — the console strip's only data source. Every test here
# pins a way the aggregate could claim something the ledger does not say.

import datetime as _dt

from doug import ingest, outcome_queue


def _health(url, **kw):
    """Call job_health with the real lane constants, the way api.py does."""
    return store.job_health(
        review_lease_seconds=ingest.STALL_LEASE_SECONDS,
        review_max_attempts=ingest.MAX_ATTEMPTS,
        outcome_lease_seconds=outcome_queue.STALL_LEASE_SECONDS,
        outcome_max_attempts=outcome_queue.MAX_ATTEMPTS,
        **kw,
    )


def test_job_health_excludes_superseded_from_every_count(tmp_path, monkeypatch):
    """A superseded job is neither done nor failed and nothing went wrong —
    ingest.supersede() lands it revivable on purpose. Counting it is the
    single easiest way to make the strip cry wolf, so it must appear in no
    count at all."""
    _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.supersede(job_id, claim_generation=claimed["claim_generation"])

    health = _health(None)

    assert health["review"]["pending"] == 0
    assert health["review"]["running"] == 0
    assert health["review"]["failed"] == 0
    assert health["review"]["retrying"] == 0


def test_job_health_does_not_report_a_retried_job_as_freshly_pending(
    tmp_path, monkeypatch
):
    """ingest.fail() below the cap sets enqueued_at = now, deliberately, so
    the retry goes to the BACK of the queue instead of burning every attempt
    in one pass. A naive MIN(enqueued_at) over all pending rows therefore
    reports a twice-failed job as brand new — blind to exactly the jobs most
    likely to be in trouble. oldest_pending_at must see attempts = 0 only."""
    _db(tmp_path, monkeypatch)
    ingest.enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.fail(claimed["id"], "boom", claim_generation=claimed["claim_generation"])

    health = _health(None)

    # It is pending, and it is retrying, and those are different facts.
    assert health["review"]["pending"] == 1
    assert health["review"]["retrying"] == 1
    # No fresh-pending row exists, so there is no fresh-pending age to report.
    assert health["review"]["oldest_pending_at"] is None
    # The retry has its own age, which means "when the last attempt gave up".
    assert health["review"]["oldest_retry_at"] is not None


def test_job_health_measures_each_lane_against_its_own_lease(
    tmp_path, monkeypatch
):
    """ingest's lease is 900s; outcome_queue's is 7200s. A claim 20 minutes
    old is stalled in the review lane and perfectly healthy in the outcome
    lane. One shared lease constant would alarm on the healthy one."""
    _db(tmp_path, monkeypatch)
    twenty_min_ago = _dt.datetime.now(_dt.UTC) - _dt.timedelta(minutes=20)

    ingest.enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    _force_started_at(store.review_jobs, claimed["id"], twenty_min_ago)

    outcome_id = store.enqueue_outcome_jobs(
        99, 1, 7, "b" * 40, twenty_min_ago, "main", window_days=(14,)
    )[14]
    _force_running(store.outcome_jobs, outcome_id, twenty_min_ago)

    health = _health(None)

    assert health["review"]["stalled"] == 1
    assert health["outcome"]["stalled"] == 0


def test_job_health_reports_the_lane_constants_it_measured_with(
    tmp_path, monkeypatch
):
    """The console renders 'attempts 4/10' and computes nothing against a
    lease it holds locally. If a constant moves, the UI must follow rather
    than silently disagree with the sweep that enforces it."""
    _db(tmp_path, monkeypatch)

    health = _health(None)

    assert health["review"]["stall_lease_seconds"] == ingest.STALL_LEASE_SECONDS
    assert health["review"]["max_attempts"] == ingest.MAX_ATTEMPTS
    assert health["outcome"]["stall_lease_seconds"] == outcome_queue.STALL_LEASE_SECONDS
    assert health["outcome"]["max_attempts"] == outcome_queue.MAX_ATTEMPTS


def test_job_health_separates_overdue_from_next_due(tmp_path, monkeypatch):
    """next_due_at is the earliest clock still in the future;
    oldest_overdue_due_at is the earliest already past. Blending them would
    make 'the next clock' read as an alarm or an alarm read as a schedule."""
    _db(tmp_path, monkeypatch)
    now = _dt.datetime.now(_dt.UTC)
    # Merged 20 days ago: its 14-day clock is 6 days overdue, its 60-day
    # clock is still 40 days out.
    store.enqueue_outcome_jobs(
        99, 1, 7, "c" * 40, now - _dt.timedelta(days=20), "main"
    )

    health = _health(None)

    assert health["outcome"]["overdue"] == 1
    assert health["outcome"]["oldest_overdue_due_at"] is not None
    assert health["outcome"]["next_due_at"] is not None
    assert health["outcome"]["next_due_at"] > health["outcome"]["oldest_overdue_due_at"]


def test_job_health_returns_none_without_a_ledger(tmp_path, monkeypatch):
    """None, never a dict of zeros. A zeroed health payload would render as
    'nothing is wrong' on a deployment that cannot answer the question.

    store._get_engine() re-reads DATABASE_URL on every call and returns None
    when it is unset, so unsetting the variable is the whole fixture — there
    is no engine-reset helper in this codebase and none is needed."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _health(None) is None
```

`_db(tmp_path, monkeypatch)` is the existing sqlite fixture at the top of
`test_store.py` (it sets both `DATABASE_URL` and `DOUG_API_TOKEN`); use it
rather than adding a second fixture convention. `INSTALL = 150424894` is
already defined in that module if you prefer it over a literal `99`.

Add these two helpers next to the tests (both write columns no public helper
sets, which is the point — they simulate a crashed holder):

```python
def _force_started_at(table, job_id, when):
    """Age a claim's lease without waiting for one. reclaim_stalled compares
    started_at to the DB clock, so this is the only way to test the stalled
    branch in under 900 seconds."""
    from sqlalchemy import update as _update

    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(
            _update(table).where(table.c.id == job_id).values(started_at=when)
        )


def _force_running(table, job_id, when):
    from sqlalchemy import update as _update

    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(
            _update(table)
            .where(table.c.id == job_id)
            .values(status="running", started_at=when)
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `api/`: `uv run pytest tests/test_store.py -k job_health -v`
Expected: FAIL — `AttributeError: module 'doug.store' has no attribute 'job_health'`, and `AttributeError: module 'doug.ingest' has no attribute 'MAX_ATTEMPTS'`.

- [ ] **Step 3: Promote the review attempt cap**

In `api/doug/ingest.py`, next to `STALL_LEASE_SECONDS = 900`:

```python
# The review lane's attempt cap. A module constant rather than only fail()'s
# default because the health endpoint reports it to the console, which must
# render "attempts 2/3" against the value the queue actually enforces —
# outcome_queue.MAX_ATTEMPTS is the same contract for the other lane.
MAX_ATTEMPTS = 3
```

Then change `fail()`'s signature so the default reads from it:

```python
def fail(
    job_id: int, error: str, *, claim_generation: int, max_attempts: int = MAX_ATTEMPTS
) -> bool:
```

- [ ] **Step 4: Consolidate the DB clock helpers into store.py**

Add to `api/doug/store.py` (the docstrings are `ingest`'s, which are the
fullest of the three copies — keep them, they explain the sqlite/Postgres
split that the bodies alone do not):

```python
def _as_utc(value: datetime) -> datetime:
    """Normalise a DB timestamp to aware UTC.

    sqlite's CURRENT_TIMESTAMP is naive; Postgres timestamptz is aware.
    Claim holders compare the started_at they were handed against the row,
    so both sides of that equality have to share a timezone convention.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _db_now(conn) -> datetime:
    """The database's clock, not the caller's wall clock.

    Claim started_at and reclaim cutoffs must share one clock across Cloud
    Run instances; comparing one instance's datetime.now() to another's
    written started_at is how a skewed host reclaims a live worker.

    sqlite is the test path only and CURRENT_TIMESTAMP is second-precision —
    wall clock keeps microsecond resolution there. Postgres uses
    clock_timestamp() (statement time), not now()/transaction_timestamp(),
    so two claims in quick succession cannot collapse onto one tx start time.

    This is the single definition. ingest, outcome_queue and outcome_backfill
    each carried an identical private copy; they now import from here. It
    lives in store rather than in one of them because all three already
    import store, so this is the only direction with no cycle.
    """
    if conn.dialect.name == "sqlite":
        return datetime.now(UTC)
    value = conn.execute(select(func.clock_timestamp())).scalar_one()
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return _as_utc(value)
```

`store.py` already imports `select` and `func` from sqlalchemy at module
level and `UTC, datetime` from `datetime` — confirm both before adding, and
do not add a redundant local import.

Then, in each of `api/doug/ingest.py`, `api/doug/outcome_queue.py` and
`api/doug/outcome_backfill.py`: **delete** the local `_as_utc` and `_db_now`
definitions and import them from store instead. Each file already has
`from . import store`, so add alongside it:

```python
from .store import _as_utc, _db_now
```

Leave every call site untouched — the names are unchanged, so this is a pure
move. Do not "improve" any of the three modules while you are in them; this
task's diff outside `store.py` and `ingest.MAX_ATTEMPTS` should be deletions
and one import line per file, nothing else.

If `outcome_backfill.py` annotates its parameter as `Connection` and that
import becomes unused after the deletion, remove the now-unused import —
ruff will flag it otherwise.

- [ ] **Step 5: Implement `job_health`**

```python
def job_health(
    *,
    review_lease_seconds: int,
    review_max_attempts: int,
    outcome_lease_seconds: int,
    outcome_max_attempts: int,
    repo: str | None = None,
    installation_id: int | None = None,
) -> dict | None:
    """Fixed-size health aggregates for both job lanes.

    Returns None when no ledger is configured — never a dict of zeros, which
    would render as "nothing is wrong" on a deployment that cannot answer.

    The lane constants are arguments rather than imports because both ingest
    and outcome_queue import this module; taking them in keeps one source of
    truth without a cycle, and lets the response report the values actually
    measured with.

    'superseded' appears in no count. It is neither done (no verdict) nor
    failed (nothing went wrong), and counting it is the fastest way to make
    the strip cry wolf.
    """
    engine = _get_engine()
    if engine is None:
        return None
    from sqlalchemy import func, select

    rj, oj = review_jobs, outcome_jobs

    def _scope_review(q):
        if repo:
            q = q.where(rj.c.repo_full_name == repo)
        if installation_id is not None:
            q = q.where(rj.c.installation_id == installation_id)
        return q

    def _scope_outcome(q):
        # outcome_jobs carries no repo name — only github_repo_id — so a repo
        # filter has to go through the ledger that maps the two.
        if repo:
            q = q.where(
                oj.c.github_repo_id.in_(
                    select(installation_repos.c.github_repo_id).where(
                        installation_repos.c.full_name == repo
                    )
                )
            )
        if installation_id is not None:
            q = q.where(oj.c.installation_id == installation_id)
        return q

    with engine.connect() as conn:
        now = _db_now(conn)
        review_cutoff = now - timedelta(seconds=review_lease_seconds)
        outcome_cutoff = now - timedelta(seconds=outcome_lease_seconds)
        day_ago = now - timedelta(hours=24)

        def _one(q):
            return conn.execute(q).scalar()

        def _count_review(*where):
            return _one(_scope_review(select(func.count()).select_from(rj).where(*where))) or 0

        def _count_outcome(*where):
            return _one(_scope_outcome(select(func.count()).select_from(oj).where(*where))) or 0

        review = {
            "pending": _count_review(rj.c.status == "pending"),
            # attempts = 0 ONLY. ingest.fail() resets enqueued_at on every
            # retry, so a MIN over all pending rows reports a twice-failed
            # job as freshly enqueued. These are two different quantities and
            # must never be blended back into one MIN.
            "oldest_pending_at": _one(
                _scope_review(
                    select(func.min(rj.c.enqueued_at)).where(
                        rj.c.status == "pending", rj.c.attempts == 0
                    )
                )
            ),
            "retrying": _count_review(rj.c.status == "pending", rj.c.attempts > 0),
            "oldest_retry_at": _one(
                _scope_review(
                    select(func.min(rj.c.enqueued_at)).where(
                        rj.c.status == "pending", rj.c.attempts > 0
                    )
                )
            ),
            "running": _count_review(rj.c.status == "running"),
            "stalled": _count_review(
                rj.c.status == "running", rj.c.started_at < review_cutoff
            ),
            "failed": _count_review(rj.c.status == "failed"),
            "failed_24h": _count_review(
                rj.c.status == "failed", rj.c.finished_at >= day_ago
            ),
            "stall_lease_seconds": review_lease_seconds,
            "max_attempts": review_max_attempts,
        }

        outcome = {
            "pending": _count_outcome(oj.c.status == "pending"),
            "overdue": _count_outcome(oj.c.status == "pending", oj.c.due_at < now),
            # The earliest clock still in the FUTURE — a schedule, not an
            # alarm. oldest_overdue_due_at is the earliest already past.
            # They never overlap.
            "next_due_at": _one(
                _scope_outcome(
                    select(func.min(oj.c.due_at)).where(
                        oj.c.status == "pending", oj.c.due_at >= now
                    )
                )
            ),
            "oldest_overdue_due_at": _one(
                _scope_outcome(
                    select(func.min(oj.c.due_at)).where(
                        oj.c.status == "pending", oj.c.due_at < now
                    )
                )
            ),
            "running": _count_outcome(oj.c.status == "running"),
            "stalled": _count_outcome(
                oj.c.status == "running", oj.c.started_at < outcome_cutoff
            ),
            "failed": _count_outcome(oj.c.status == "failed"),
            "stall_lease_seconds": outcome_lease_seconds,
            "max_attempts": outcome_max_attempts,
        }

        return {"review": review, "outcome": outcome, "as_of": now}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run from `api/`: `uv run pytest tests/test_store.py -k job_health -v`
Expected: PASS, 6 tests.

Then prove the consolidation was a pure move and the promoted constant
changed no behaviour — these three suites cover the modules whose helpers
moved, and they must pass with **unchanged counts**:

```bash
uv run pytest tests/test_ingest.py tests/test_outcome_queue.py tests/test_outcome_backfill.py -v
```

Then the whole suite: `uv run pytest`. If any of these fail, the move was not
pure — fix the move, do not adjust the tests.

- [ ] **Step 7: Lint and commit**

```bash
cd api && uv run ruff check .
git add api/doug/ingest.py api/doug/outcome_queue.py api/doug/outcome_backfill.py api/doug/store.py api/tests/test_store.py
git commit -m "Add job_health aggregates, consolidate the DB clock, promote the review cap

The review lane's cap of 3 existed only as fail()'s default parameter, so
the health endpoint would have had to hardcode a literal that could drift
from what the queue enforces. It is now ingest.MAX_ATTEMPTS, matching
outcome_queue.MAX_ATTEMPTS.

_db_now and _as_utc were defined three times with identical bodies, in
ingest, outcome_queue and outcome_backfill. store.py needed one too, and a
fourth copy is the wrong fix: all three already import store, so store is
the only home with no cycle. They now import from there. Pure move -- no
call site changed, and the three suites pass with unchanged counts.

job_health takes the lane constants as arguments rather than importing
them: ingest and outcome_queue both import store, so the reverse IS a
cycle for those. Taking them in keeps one source of truth and lets the
response report the values it actually measured with -- the two lanes
differ (900s/3 vs 7200s/10) and one shared constant would report a healthy
twenty-minute-old outcome claim as stalled.

oldest_pending_at counts attempts = 0 only, because ingest.fail() resets
enqueued_at on retry and a naive MIN would report a twice-failed job as
freshly enqueued."
```

---

### Task 2: `GET /v1/health`

**Files:**
- Modify: `api/doug/models.py`
- Modify: `api/doug/api.py`
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: `store.job_health(...)`, `ingest.MAX_ATTEMPTS`, `outcome_queue.MAX_ATTEMPTS` from Task 1.
- Produces: `GET /v1/health` returning `HealthResponse`. Consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_api.py`, after the `/v1/runs` block:

```python
# /v1/health — the strip's only data source. Same _db/AUTH shape as /v1/runs.


def test_health_refuses_without_the_operator_token(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert TestClient(app).get("/v1/health").status_code == 401


def test_health_404s_a_tenant_key(tmp_path, monkeypatch):
    """Health crosses every installation by design, which is exactly what no
    tenant credential may ever do."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setattr(tenancy, "resolve", lambda t: tenancy.TokenContext(
        installation_id=99, token_id=1, repo_ids=None, scopes=("queue:read",),
    ))
    res = TestClient(app).get("/v1/health", headers={"X-Doug-Token": "dg_tenant"})
    assert res.status_code == 404


def test_health_503s_without_a_ledger(tmp_path, monkeypatch):
    """503, never a zeroed payload. Zeros would render as 'nothing is wrong'
    on a deployment that cannot answer the question at all."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    assert TestClient(app).get("/v1/health", headers=AUTH).status_code == 503


def test_health_reports_both_lanes_constants(tmp_path, monkeypatch):
    """The console must never hardcode 900, 7200, 3 or 10."""
    _db(tmp_path, monkeypatch)
    body = TestClient(app).get("/v1/health", headers=AUTH).json()
    assert body["review"]["stall_lease_seconds"] == ingest.STALL_LEASE_SECONDS
    assert body["review"]["max_attempts"] == ingest.MAX_ATTEMPTS
    assert body["outcome"]["stall_lease_seconds"] == outcome_queue.STALL_LEASE_SECONDS
    assert body["outcome"]["max_attempts"] == outcome_queue.MAX_ATTEMPTS


def test_health_carries_the_server_clock_as_of(tmp_path, monkeypatch):
    """Every age the console renders is as_of minus a timestamp. Without it
    the UI would subtract a server-written timestamp from a browser clock,
    which is the timestamp defect Phase 1 already paid for, with an alarm
    attached."""
    _db(tmp_path, monkeypatch)
    body = TestClient(app).get("/v1/health", headers=AUTH).json()
    assert body["as_of"] is not None
```

Ensure `from doug import ingest, outcome_queue` is available in the test
module's imports; add it to the existing import block if absent.

- [ ] **Step 2: Run the tests to verify they fail**

Run from `api/`: `uv run pytest tests/test_api.py -k health -v`
Expected: FAIL — 404 on every route call, because `/v1/health` does not exist.

- [ ] **Step 3: Add the response models**

In `api/doug/models.py`, next to `RunListResponse`:

```python
class ReviewLaneHealth(BaseModel):
    pending: int
    oldest_pending_at: datetime | None
    retrying: int
    oldest_retry_at: datetime | None
    running: int
    stalled: int
    failed: int
    failed_24h: int
    stall_lease_seconds: int
    max_attempts: int


class OutcomeLaneHealth(BaseModel):
    pending: int
    overdue: int
    next_due_at: datetime | None
    oldest_overdue_due_at: datetime | None
    running: int
    stalled: int
    failed: int
    stall_lease_seconds: int
    max_attempts: int


class HealthResponse(BaseModel):
    """Fixed-size aggregates, no rows. The strip renders on every page, so
    this response's cost must not grow with the queue."""

    review: ReviewLaneHealth
    outcome: OutcomeLaneHealth
    as_of: datetime
```

If `datetime` is not already imported in `models.py`, add
`from datetime import datetime` to its import block.

- [ ] **Step 4: Add the route**

In `api/doug/api.py`, after the `/v1/runs/{verdict_id}` handler:

```python
@app.get("/v1/health")
def health(
    repo: str | None = None,
    installation_id: int | None = None,
    x_doug_token: str = Header(""),
) -> HealthResponse:
    """Both job lanes' health. Operator-only for the same reason /v1/runs is:
    it crosses every installation by design.

    The lane constants are passed in from the modules that enforce them, so
    the response reports what was actually measured with rather than a
    literal duplicated here.
    """
    _operator_only(x_doug_token)
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    data = store.job_health(
        review_lease_seconds=ingest.STALL_LEASE_SECONDS,
        review_max_attempts=ingest.MAX_ATTEMPTS,
        outcome_lease_seconds=outcome_queue.STALL_LEASE_SECONDS,
        outcome_max_attempts=outcome_queue.MAX_ATTEMPTS,
        repo=repo,
        installation_id=installation_id,
    )
    if data is None:
        raise HTTPException(status_code=503, detail="no ledger configured")
    return HealthResponse(**data)
```

Add `HealthResponse` to the `from .models import (...)` block, and ensure
`outcome_queue` is imported alongside the existing `ingest` import.

- [ ] **Step 5: Run the tests to verify they pass**

Run from `api/`: `uv run pytest tests/test_api.py -k health -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Confirm the fails-closed pin is not vacuous**

Temporarily delete the `_operator_only(x_doug_token)` line from the new
handler and re-run `uv run pytest tests/test_api.py -k health -v`.
Expected: `test_health_refuses_without_the_operator_token` and
`test_health_404s_a_tenant_key` both FAIL. **Restore the line** and re-run to
confirm PASS. This is the same non-vacuity check Phase 1 applied to
`/v1/runs`; a gate test that cannot fail is not a gate test.

- [ ] **Step 7: Lint and commit**

```bash
cd api && uv run ruff check .
git add api/doug/models.py api/doug/api.py api/tests/test_api.py
git commit -m "Add GET /v1/health for the console strip

Aggregates only, no rows: the strip renders on every page, so this
response's cost must not grow with the queue. 503 rather than a zeroed
payload when no ledger is configured -- zeros would render as 'nothing is
wrong' on a deployment that cannot answer at all.

The operator gate is pinned by two tests verified non-vacuous by removing
the gate and watching them fail."
```

---

### Task 3: `store.job_rows()`

**Files:**
- Modify: `api/doug/store.py`
- Test: `api/tests/test_store.py`

**Interfaces:**
- Consumes: `store._db_now` from Task 1.
- Produces: `store.job_rows(*, lane: str, lease_seconds: int, unhealthy_only: bool = True, status: str | None = None, repo: str | None = None, installation_id: int | None = None, limit: int = 100, offset: int = 0) -> list[dict]`. Review rows carry `id, lane, repo, pr_number, head_sha, status, attempts, claim_generation, enqueued_at, started_at, finished_at, error, verdict_id, installation_id, github_repo_id, stalled, retrying`. Outcome rows carry `id, lane, repo, pr_number, merge_commit_sha, window_days, due_at, merged_at, status, attempts, started_at, finished_at, error, installation_id, github_repo_id, stalled, overdue`. `repo` is `str | None` on outcome rows. Consumed by Task 4.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_store.py`:

```python
def test_job_rows_defaults_to_unhealthy_only(tmp_path, monkeypatch):
    """The page exists to answer 'what is wrong'. A raw job list is
    overwhelmingly done and superseded, so the default filter is the RED and
    AMBER states and nothing else."""
    _db(tmp_path, monkeypatch)
    # One healthy done job.
    done_id = ingest.enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.complete(done_id, None, claim_generation=claimed["claim_generation"])
    # One failed job: three attempts exhausts ingest.MAX_ATTEMPTS.
    ingest.enqueue(99, 1, "o/r", 8, "b" * 40)
    for _ in range(ingest.MAX_ATTEMPTS):
        c = ingest.claim()
        ingest.fail(c["id"], "boom", claim_generation=c["claim_generation"])

    rows = store.job_rows(lane="review", lease_seconds=ingest.STALL_LEASE_SECONDS)

    assert [r["pr_number"] for r in rows] == [8]
    assert rows[0]["status"] == "failed"


def test_job_rows_never_returns_superseded_as_unhealthy(tmp_path, monkeypatch):
    """Same reason job_health excludes it: nothing went wrong."""
    _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.supersede(job_id, claim_generation=claimed["claim_generation"])

    rows = store.job_rows(lane="review", lease_seconds=ingest.STALL_LEASE_SECONDS)

    assert rows == []


def test_job_rows_shows_everything_when_unhealthy_only_is_off(
    tmp_path, monkeypatch
):
    """'The job I expected does not exist at all' is a real diagnosis, and
    only a complete list reaches it."""
    _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.supersede(job_id, claim_generation=claimed["claim_generation"])

    rows = store.job_rows(
        lane="review",
        lease_seconds=ingest.STALL_LEASE_SECONDS,
        unhealthy_only=False,
    )

    assert [r["status"] for r in rows] == ["superseded"]


def test_job_rows_carries_the_derived_flag_it_was_selected_by(
    tmp_path, monkeypatch
):
    """The page renders the REASON a row is unhealthy without recomputing it
    against a lease constant it would have to hold locally — which is how the
    list and the strip drift apart."""
    _db(tmp_path, monkeypatch)
    ingest.enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    _force_started_at(
        store.review_jobs,
        claimed["id"],
        _dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=1000),
    )

    rows = store.job_rows(lane="review", lease_seconds=ingest.STALL_LEASE_SECONDS)

    assert rows[0]["stalled"] is True
    assert rows[0]["retrying"] is False


def test_job_rows_renders_no_repo_name_when_the_ledger_has_none(
    tmp_path, monkeypatch
):
    """outcome_jobs carries only github_repo_id. The display name comes from
    installation_repos, which worker.py documents as able to go stale and
    which count_verdict_repos_missing_from_ledger proves can be absent. A
    miss must return None so the caller renders the bare id — never a guess,
    never a blank."""
    _db(tmp_path, monkeypatch)
    now = _dt.datetime.now(_dt.UTC)
    store.enqueue_outcome_jobs(
        99, 4242, 7, "c" * 40, now - _dt.timedelta(days=20), "main",
        window_days=(14,),
    )

    rows = store.job_rows(
        lane="outcome", lease_seconds=outcome_queue.STALL_LEASE_SECONDS
    )

    assert rows[0]["repo"] is None
    assert rows[0]["github_repo_id"] == 4242
    assert rows[0]["overdue"] is True


def test_job_rows_resolves_the_outcome_repo_name_when_the_ledger_has_it(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    now = _dt.datetime.now(_dt.UTC)
    # set_installation_repos takes (github_repo_id, full_name) tuples — the
    # same call the installation_repositories webhook tests already use.
    store.set_installation_repos(99, [(4242, "o/r")], replace=True)
    store.enqueue_outcome_jobs(
        99, 4242, 7, "c" * 40, now - _dt.timedelta(days=20), "main",
        window_days=(14,),
    )

    rows = store.job_rows(
        lane="outcome", lease_seconds=outcome_queue.STALL_LEASE_SECONDS
    )

    assert rows[0]["repo"] == "o/r"


def test_job_rows_does_not_treat_a_skipped_done_job_as_unhealthy(
    tmp_path, monkeypatch
):
    """ingest.complete() takes verdict_id: int | None — 'a skipped PR is
    finished, not failed'. A healthy done job can carry a NULL verdict, so
    unlinkable does not mean unhealthy. Surfacing it as a failure would
    invent an incident out of Doug correctly declining to review."""
    _db(tmp_path, monkeypatch)
    job_id = ingest.enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.complete(job_id, None, claim_generation=claimed["claim_generation"])

    unhealthy = store.job_rows(
        lane="review", lease_seconds=ingest.STALL_LEASE_SECONDS
    )
    everything = store.job_rows(
        lane="review",
        lease_seconds=ingest.STALL_LEASE_SECONDS,
        unhealthy_only=False,
    )

    assert unhealthy == []
    assert everything[0]["status"] == "done"
    assert everything[0]["verdict_id"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `api/`: `uv run pytest tests/test_store.py -k job_rows -v`
Expected: FAIL — `AttributeError: module 'doug.store' has no attribute 'job_rows'`.

- [ ] **Step 3: Implement `job_rows`**

```python
def job_rows(
    *,
    lane: str,
    lease_seconds: int,
    unhealthy_only: bool = True,
    status: str | None = None,
    repo: str | None = None,
    installation_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Job rows for one lane, newest first.

    `status` accepts STORED statuses only. 'stalled', 'retrying' and
    'overdue' are derived from started_at / attempts / due_at and are not
    stored anywhere; they are reachable through unhealthy_only, and each
    returned row carries the flags it was selected by so the caller renders
    the reason without recomputing it against a lease it holds locally. That
    is what keeps this list and the health strip from drifting apart.

    'superseded' is never unhealthy — nothing went wrong — so it appears only
    when unhealthy_only is False.
    """
    engine = _get_engine()
    if engine is None or limit < 1 or offset < 0 or lane not in ("review", "outcome"):
        return []
    from sqlalchemy import desc, or_, select

    with engine.connect() as conn:
        now = _db_now(conn)
        cutoff = now - timedelta(seconds=lease_seconds)

        if lane == "review":
            t = review_jobs
            query = select(t)
            if repo:
                query = query.where(t.c.repo_full_name == repo)
            if unhealthy_only:
                query = query.where(
                    or_(
                        t.c.status == "failed",
                        (t.c.status == "pending") & (t.c.attempts > 0),
                        (t.c.status == "running") & (t.c.started_at < cutoff),
                        (t.c.status == "pending") & (t.c.attempts == 0),
                    )
                )
        else:
            t = outcome_jobs
            query = select(t)
            if repo:
                query = query.where(
                    t.c.github_repo_id.in_(
                        select(installation_repos.c.github_repo_id).where(
                            installation_repos.c.full_name == repo
                        )
                    )
                )
            if unhealthy_only:
                query = query.where(
                    or_(
                        t.c.status == "failed",
                        (t.c.status == "pending") & (t.c.due_at < now),
                        (t.c.status == "running") & (t.c.started_at < cutoff),
                    )
                )

        if status:
            query = query.where(t.c.status == status)
        if installation_id is not None:
            query = query.where(t.c.installation_id == installation_id)
        query = query.order_by(desc(t.c.id)).limit(limit).offset(offset)

        rows = [dict(r) for r in conn.execute(query).mappings()]
        if not rows:
            return rows

        names = {}
        if lane == "outcome":
            # Display only, and genuinely nullable: a repo can be absent from
            # installation_repos entirely. A miss stays None so the caller
            # renders the bare github_repo_id rather than a guess.
            ids = {r["github_repo_id"] for r in rows}
            names = {
                row["github_repo_id"]: row["full_name"]
                for row in conn.execute(
                    select(
                        installation_repos.c.github_repo_id,
                        installation_repos.c.full_name,
                    ).where(installation_repos.c.github_repo_id.in_(ids))
                ).mappings()
            }

        for r in rows:
            r["lane"] = lane
            started = r.get("started_at")
            r["stalled"] = bool(
                r["status"] == "running" and started is not None and started < cutoff
            )
            if lane == "review":
                r["repo"] = r.pop("repo_full_name")
                r["retrying"] = bool(r["status"] == "pending" and r["attempts"] > 0)
            else:
                r["repo"] = names.get(r["github_repo_id"])
                r["overdue"] = bool(r["status"] == "pending" and r["due_at"] < now)
        return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run from `api/`: `uv run pytest tests/test_store.py -k job_rows -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Lint and commit**

```bash
cd api && uv run ruff check .
git add api/doug/store.py api/tests/test_store.py
git commit -m "Add store.job_rows for the console failure list

Each row carries the derived flag it was selected by (stalled, retrying,
overdue) so the page renders the reason without recomputing it against a
lease constant it holds locally -- which is how a list and a strip drift
apart.

The outcome lane's repo name is genuinely nullable: outcome_jobs carries
only github_repo_id, and installation_repos can be stale or absent. A miss
returns None so the caller renders the bare id rather than a guess."
```

---

### Task 4: `GET /v1/jobs`

**Files:**
- Modify: `api/doug/models.py`
- Modify: `api/doug/api.py`
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: `store.job_rows(...)` from Task 3.
- Produces: `GET /v1/jobs` returning `JobListResponse` with `{items, limit, offset}`. Consumed by Task 7.

- [ ] **Step 1: Write the failing tests**

```python
# /v1/jobs — the failure list. Same gate and envelope as /v1/runs.


def test_jobs_refuses_without_the_operator_token(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert TestClient(app).get("/v1/jobs?lane=review").status_code == 401


def test_jobs_rejects_a_derived_state_as_a_status(tmp_path, monkeypatch):
    """'stalled' and 'retrying' are derived from started_at and attempts,
    not stored. Accepting them here would put the derivation somewhere the
    strip cannot see, and the two surfaces would drift."""
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/jobs?lane=review&status=stalled", headers=AUTH).status_code == 422
    assert client.get("/v1/jobs?lane=review&status=retrying", headers=AUTH).status_code == 422
    assert client.get("/v1/jobs?lane=outcome&status=overdue", headers=AUTH).status_code == 422


def test_jobs_accepts_a_stored_status(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    res = TestClient(app).get("/v1/jobs?lane=review&status=failed", headers=AUTH)
    assert res.status_code == 200


def test_jobs_rejects_an_unknown_lane(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert TestClient(app).get("/v1/jobs?lane=nope", headers=AUTH).status_code == 422


def test_jobs_rejects_an_out_of_range_limit(tmp_path, monkeypatch):
    """Same 1..500 bound as /v1/runs, so the console's atCap logic carries
    over unchanged."""
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/jobs?lane=review&limit=0", headers=AUTH).status_code == 422
    assert client.get("/v1/jobs?lane=review&limit=501", headers=AUTH).status_code == 422


def test_jobs_round_trips_limit_and_offset(tmp_path, monkeypatch):
    """The only way a caller can tell 'this IS every unhealthy job' from
    'this is the first page of more'."""
    _db(tmp_path, monkeypatch)
    body = TestClient(app).get("/v1/jobs?lane=review&limit=7", headers=AUTH).json()
    assert body["limit"] == 7
    assert body["offset"] == 0


def test_jobs_503s_without_a_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    assert TestClient(app).get("/v1/jobs?lane=review", headers=AUTH).status_code == 503
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `api/`: `uv run pytest tests/test_api.py -k jobs -v`
Expected: FAIL — 404, `/v1/jobs` does not exist.

- [ ] **Step 3: Add the response models**

In `api/doug/models.py`:

```python
class JobItem(BaseModel):
    """One job from either lane. Lane-specific fields are None on the other
    lane rather than absent, so the console has one row type to render.

    `repo` is nullable because outcome_jobs carries only github_repo_id and
    installation_repos can be stale or missing entirely — the console renders
    the bare id in that case rather than guessing a name.
    """

    id: int
    lane: str
    repo: str | None
    github_repo_id: int
    installation_id: int
    pr_number: int
    status: str
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    stalled: bool
    # Review lane only.
    head_sha: str | None = None
    enqueued_at: datetime | None = None
    verdict_id: int | None = None
    retrying: bool = False
    # Outcome lane only.
    merge_commit_sha: str | None = None
    window_days: int | None = None
    due_at: datetime | None = None
    merged_at: datetime | None = None
    overdue: bool = False


class JobListResponse(BaseModel):
    items: list[JobItem]
    limit: int
    offset: int
```

- [ ] **Step 4: Add the route**

```python
# The stored statuses each lane's queue actually writes. 'stalled',
# 'retrying' and 'overdue' are deliberately absent: they are derived from
# started_at / attempts / due_at, and accepting them as a status would put
# the derivation somewhere /v1/health cannot see.
_REVIEW_STATUSES = frozenset({"pending", "running", "done", "failed", "superseded"})
_OUTCOME_STATUSES = frozenset({"pending", "running", "done", "failed"})


@app.get("/v1/jobs")
def jobs(
    lane: str = "review",
    view: str = "unhealthy",
    status: str | None = None,
    repo: str | None = None,
    installation_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    x_doug_token: str = Header(""),
) -> JobListResponse:
    """Job rows for one lane. Operator-only for the same reason /v1/runs is.

    Read-only: nothing here requeues, retries or clears a job.
    """
    _operator_only(x_doug_token)
    if lane not in ("review", "outcome"):
        raise HTTPException(status_code=422, detail="lane must be review or outcome")
    if view not in ("unhealthy", "all"):
        raise HTTPException(status_code=422, detail="view must be unhealthy or all")
    allowed = _REVIEW_STATUSES if lane == "review" else _OUTCOME_STATUSES
    if status is not None and status not in allowed:
        raise HTTPException(
            status_code=422, detail=f"status must be one of {sorted(allowed)}"
        )
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must not be negative")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    lease = (
        ingest.STALL_LEASE_SECONDS
        if lane == "review"
        else outcome_queue.STALL_LEASE_SECONDS
    )
    rows = store.job_rows(
        lane=lane,
        lease_seconds=lease,
        unhealthy_only=view == "unhealthy",
        status=status,
        repo=repo,
        installation_id=installation_id,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        items=[JobItem(**row) for row in rows], limit=limit, offset=offset
    )
```

Add `JobItem` and `JobListResponse` to the `from .models import (...)` block.

- [ ] **Step 5: Run the tests to verify they pass**

Run from `api/`: `uv run pytest tests/test_api.py -k jobs -v`
Expected: PASS, 7 tests.

Then run the whole api suite to confirm no regression:
`uv run pytest` — expected PASS, count is Phase 1's 691 plus the tests added in Tasks 1–4.

- [ ] **Step 6: Lint and commit**

```bash
cd api && uv run ruff check .
git add api/doug/models.py api/doug/api.py api/tests/test_api.py
git commit -m "Add GET /v1/jobs for the console failure list

Read-only, operator-only, and the same {items, limit, offset} envelope as
/v1/runs so the console's atCap logic carries over unchanged.

status accepts stored statuses only. stalled, retrying and overdue are
derived from started_at, attempts and due_at, and accepting them here
would put the derivation somewhere /v1/health cannot see -- the list and
the strip would then disagree about the same job."
```

---

### Task 5: `console/lib/health.ts`

The pure classifier. Nearly all of this feature's lying-risk lives here by
construction, which is what lets existing tooling pin it without the
render-test infrastructure that is still its own Phase 2 item.

**Files:**
- Create: `console/lib/health.ts`
- Create: `console/lib/health.test.mjs`

**Interfaces:**
- Consumes: the `/v1/health` payload shape from Task 2.
- Produces: `HealthPayload` type; `PENDING_THRESHOLD_MINUTES = 15`; `ADJUDICATOR_GRACE_HOURS = 26`; `classify(payload: HealthPayload | { error: string }): HealthVerdict` where `HealthVerdict = { level: "failing" | "degraded" | "clear" | "unknown"; cells: HealthCell[] }` and `HealthCell = { key: string; word: string; count: number | null; detail: string | null; level: "failing" | "degraded" | "clear" | "unknown" }`. Consumed by Tasks 6 and 7.

- [ ] **Step 1: Write the failing tests**

Create `console/lib/health.test.mjs`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import {
  ADJUDICATOR_GRACE_HOURS,
  PENDING_THRESHOLD_MINUTES,
  classify,
} from "./health.ts";

const AS_OF = "2026-08-07T12:00:00Z";

function payload(overrides = {}) {
  return {
    review: {
      pending: 0,
      oldest_pending_at: null,
      retrying: 0,
      oldest_retry_at: null,
      running: 0,
      stalled: 0,
      failed: 0,
      failed_24h: 0,
      stall_lease_seconds: 900,
      max_attempts: 3,
      ...(overrides.review ?? {}),
    },
    outcome: {
      pending: 0,
      overdue: 0,
      next_due_at: null,
      oldest_overdue_due_at: null,
      running: 0,
      stalled: 0,
      failed: 0,
      stall_lease_seconds: 7200,
      max_attempts: 10,
      ...(overrides.outcome ?? {}),
    },
    as_of: overrides.as_of ?? AS_OF,
  };
}

/** Minutes before as_of, as an ISO string. */
function ago(minutes) {
  return new Date(Date.parse(AS_OF) - minutes * 60_000).toISOString();
}

test("an unreachable API is unknown, never clear", () => {
  // The worst possible outcome for this surface: converting "I do not know"
  // into "everything is fine" on the one page built to prevent exactly that.
  const verdict = classify({ error: "/v1/health → HTTP 503" });
  assert.equal(verdict.level, "unknown");
  assert.notEqual(verdict.level, "clear");
  // No cell may claim a count it does not have.
  assert.ok(verdict.cells.every((c) => c.count === null));
});

test("a quiet ledger is clear, and clear is not unknown", () => {
  const verdict = classify(payload());
  assert.equal(verdict.level, "clear");
  // Zero is a real measurement and renders as one.
  assert.equal(verdict.cells.find((c) => c.key === "failed").count, 0);
});

test("a terminal failure is failing, not degraded", () => {
  // attempts >= max: Doug gave up, and nothing in the system retries it.
  assert.equal(classify(payload({ review: { failed: 2 } })).level, "failing");
});

test("a stalled claim is degraded, because reclaim_stalled heals it", () => {
  // worker.drain calls ingest.reclaim_stalled() before its first claim, so
  // the next webhook or cold start re-pends this row without spending an
  // attempt. Real, but not the same alarm as a terminal failure.
  assert.equal(classify(payload({ review: { running: 1, stalled: 1 } })).level, "degraded");
});

test("a job pending past the threshold is degraded; one under it is clear", () => {
  // The threshold has to bite in BOTH directions or it is decoration.
  const over = payload({
    review: { pending: 1, oldest_pending_at: ago(PENDING_THRESHOLD_MINUTES + 1) },
  });
  const under = payload({
    review: { pending: 1, oldest_pending_at: ago(PENDING_THRESHOLD_MINUTES - 1) },
  });
  assert.equal(classify(over).level, "degraded");
  assert.equal(classify(under).level, "clear");
});

test("ages are measured against as_of, never the client clock", () => {
  // A skewed browser must not invent or suppress an alarm. Same payload,
  // same relative age, as_of moved a year forward: the verdict cannot move.
  const shifted = payload({
    as_of: "2027-08-07T12:00:00Z",
    review: {
      pending: 1,
      oldest_pending_at: new Date(
        Date.parse("2027-08-07T12:00:00Z") - (PENDING_THRESHOLD_MINUTES + 1) * 60_000,
      ).toISOString(),
    },
  });
  assert.equal(classify(shifted).level, "degraded");
});

test("an outcome clock overdue inside the grace is not an alarm", () => {
  // The adjudicator fires daily, so any clock can be legitimately overdue
  // for most of a day. Without grace this is red every single day and is
  // ignored inside a week.
  const inside = payload({
    outcome: {
      pending: 1,
      overdue: 1,
      oldest_overdue_due_at: new Date(
        Date.parse(AS_OF) - (ADJUDICATOR_GRACE_HOURS - 1) * 3_600_000,
      ).toISOString(),
    },
  });
  assert.equal(classify(inside).level, "clear");
});

test("an outcome clock overdue past the grace is failing", () => {
  // Past this, a scheduled fire was genuinely missed.
  const outside = payload({
    outcome: {
      pending: 1,
      overdue: 1,
      oldest_overdue_due_at: new Date(
        Date.parse(AS_OF) - (ADJUDICATOR_GRACE_HOURS + 1) * 3_600_000,
      ).toISOString(),
    },
  });
  assert.equal(classify(outside).level, "failing");
});

test("each lane's stall is measured against its own lease", () => {
  // ingest is 900s, outcome_queue is 7200s. The server already applied both
  // when it set the stalled counts; classify must not re-derive them against
  // one shared number.
  const verdict = classify(
    payload({ outcome: { running: 1, stalled: 0 }, review: { running: 1, stalled: 1 } }),
  );
  assert.equal(verdict.level, "degraded");
  assert.equal(verdict.cells.find((c) => c.key === "stalled").count, 1);
});

test("every cell carries a word, so colour is never the only carrier", () => {
  // Red already means "this PR needs a human" in the band column. A
  // greyscale or colour-blind read of this strip must lose nothing.
  for (const cell of classify(payload()).cells) {
    assert.ok(cell.word.length > 0, `cell ${cell.key} has no word`);
  }
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `console/`: `npm test`
Expected: FAIL — cannot resolve `./health.ts`.

- [ ] **Step 3: Implement `lib/health.ts`**

```typescript
export type HealthLevel = "failing" | "degraded" | "clear" | "unknown";

export interface ReviewLaneHealth {
  pending: number;
  oldest_pending_at: string | null;
  retrying: number;
  oldest_retry_at: string | null;
  running: number;
  stalled: number;
  failed: number;
  failed_24h: number;
  stall_lease_seconds: number;
  max_attempts: number;
}

export interface OutcomeLaneHealth {
  pending: number;
  overdue: number;
  next_due_at: string | null;
  oldest_overdue_due_at: string | null;
  running: number;
  stalled: number;
  failed: number;
  stall_lease_seconds: number;
  max_attempts: number;
}

export interface HealthPayload {
  review: ReviewLaneHealth;
  outcome: OutcomeLaneHealth;
  as_of: string;
}

export interface HealthCell {
  key: string;
  word: string;
  count: number | null;
  detail: string | null;
  level: HealthLevel;
}

export interface HealthVerdict {
  level: HealthLevel;
  cells: HealthCell[];
}

/** A fresh-pending job older than this means the drain that should have
 *  claimed it did not. The drain is kicked by every webhook delivery and
 *  every container start, and a job's own delivery kicks one in the same
 *  request — so several opportunities have passed by this point.
 *
 *  This number cannot come from the API: it is a statement about how often
 *  drains are kicked, not about any stored value. The strip states the
 *  quantity in words so the reader sees the age, not only the verdict. */
export const PENDING_THRESHOLD_MINUTES = 15;

/** The adjudicator Cloud Run Job fires daily at 03:00 UTC, so a clock due at
 *  00:00 is legitimately overdue for three hours and any clock can be
 *  legitimately overdue for most of a day. 24-hour cycle plus two hours of
 *  slack. Without this the alarm is red every single day and is ignored
 *  inside a week.
 *
 *  Like the threshold above, this cannot come from the ledger honestly — the
 *  schedule lives in Cloud Scheduler, not in Python. The strip names the
 *  assumption ("no adjudicator pass in over 26h") so that when the schedule
 *  changes the console says something falsifiable rather than something
 *  quietly wrong. */
export const ADJUDICATOR_GRACE_HOURS = 26;

function isError(v: unknown): v is { error: string } {
  return typeof v === "object" && v !== null && "error" in v;
}

/** Age in milliseconds against the SERVER's clock, never the browser's.
 *  Returns null when there is no timestamp — absent is not zero. */
function ageMs(at: string | null, asOf: string): number | null {
  if (at === null) return null;
  return Date.parse(asOf) - Date.parse(at);
}

const UNKNOWN_CELLS = ["verdict", "failed", "stalled", "waiting", "retrying", "clocks"];

function worst(levels: HealthLevel[]): HealthLevel {
  if (levels.includes("failing")) return "failing";
  if (levels.includes("degraded")) return "degraded";
  return "clear";
}

export function classify(input: HealthPayload | { error: string }): HealthVerdict {
  // An unreachable API is UNKNOWN, and unknown renders no counts at all.
  // Rendering "clear" here would convert "I do not know" into "everything is
  // fine" on the one surface built to prevent exactly that.
  if (isError(input)) {
    return {
      level: "unknown",
      cells: UNKNOWN_CELLS.map((key) => ({
        key,
        word: key === "verdict" ? "unknown" : key,
        count: null,
        detail: "the API did not answer",
        level: "unknown" as HealthLevel,
      })),
    };
  }

  const { review, outcome, as_of: asOf } = input;

  const failed = review.failed + outcome.failed;
  const stalled = review.stalled + outcome.stalled;

  const pendingAge = ageMs(review.oldest_pending_at, asOf);
  const pendingStale =
    pendingAge !== null && pendingAge > PENDING_THRESHOLD_MINUTES * 60_000;

  const overdueAge = ageMs(outcome.oldest_overdue_due_at, asOf);
  const overduePastGrace =
    overdueAge !== null && overdueAge > ADJUDICATOR_GRACE_HOURS * 3_600_000;

  const cells: HealthCell[] = [
    {
      key: "failed",
      word: "failed",
      count: failed,
      detail: review.failed_24h > 0 ? `${review.failed_24h} in 24h` : null,
      level: failed > 0 ? "failing" : "clear",
    },
    {
      key: "stalled",
      word: "stalled",
      count: stalled,
      detail: null,
      level: stalled > 0 ? "degraded" : "clear",
    },
    {
      key: "waiting",
      word: "waiting",
      count: review.pending - review.retrying,
      detail: review.oldest_pending_at,
      level: pendingStale ? "degraded" : "clear",
    },
    {
      key: "retrying",
      word: "retrying",
      count: review.retrying,
      detail: review.oldest_retry_at,
      level: review.retrying > 0 ? "degraded" : "clear",
    },
    {
      key: "clocks",
      word: "clocks",
      count: outcome.pending,
      detail: overduePastGrace
        ? `no adjudicator pass in over ${ADJUDICATOR_GRACE_HOURS}h`
        : outcome.next_due_at,
      level: overduePastGrace ? "failing" : "clear",
    },
  ];

  const level = worst(cells.map((c) => c.level));
  return {
    level,
    cells: [
      { key: "verdict", word: level, count: null, detail: null, level },
      ...cells,
    ],
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run from `console/`: `npm test`
Expected: PASS — 58 existing plus 10 new = 68.

- [ ] **Step 5: Lint and commit**

```bash
cd console && npm run lint
git add console/lib/health.ts console/lib/health.test.mjs
git commit -m "Add the pure console health classifier

Nearly all of this feature's lying-risk lives in this one module by
construction, which is what lets the existing node --test tooling pin it
without the render-test infrastructure that is still its own Phase 2 item.

Two constants live here rather than in the API because neither is a
statement about a stored value: the 15-minute pending threshold describes
how often drains are kicked, and the 26-hour adjudicator grace describes a
Cloud Scheduler cron. The strip states each in words so a changed schedule
makes the console say something falsifiable rather than something quietly
wrong.

An unreachable API classifies as unknown and renders no counts. Clear and
unknown are different states and can never be confused."
```

---

### Task 6: Wire the real health strip

**Files:**
- Modify: `console/lib/api.ts`
- Create: `console/components/health-strip.tsx`
- Modify: `console/components/shell.tsx`

**Interfaces:**
- Consumes: `classify`, `HealthPayload`, `HealthVerdict` from Task 5; `GET /v1/health` from Task 2.
- Produces: `getHealth(): Promise<HealthPayload | { error: string }>` in `lib/api.ts`; `<HealthStrip health={payload} />` in `components/health-strip.tsx`, taking the raw payload-or-error and calling `classify` itself. `Shell` becomes `async` and fetches health itself, and its `active` prop widens to `"runs" | "jobs"`.

- [ ] **Step 1: Add `getHealth` to `lib/api.ts`**

```typescript
import type { HealthPayload } from "./health";

/** Global, never scoped. "Is Doug failing on anything" is a global question,
 *  and a scope filter that can hide a fire in another tenant is an
 *  anti-feature on this surface specifically — so this deliberately takes no
 *  repo or installation argument even though /v1/health accepts them. */
export async function getHealth(): Promise<HealthPayload | { error: string }> {
  return get<HealthPayload>("/v1/health");
}
```

- [ ] **Step 2: Create `components/health-strip.tsx`**

```tsx
import { classify, type HealthPayload } from "@/lib/health";

const LEVEL_CLASS: Record<string, string> = {
  // Colour is never the only carrier — every cell renders its word too.
  failing: "text-[var(--flag)]",
  degraded: "text-[var(--iridescent)]",
  clear: "text-muted-foreground",
  unknown: "text-muted-foreground/60",
};

/** Ages are rendered against the server's as_of, never the browser clock. */
function age(at: string | null, asOf: string): string | null {
  if (at === null) return null;
  const ms = Date.parse(asOf) - Date.parse(at);
  if (!Number.isFinite(ms) || ms < 0) return null;
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  return hours < 48 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
}

export function HealthStrip({
  health,
}: {
  health: HealthPayload | { error: string };
}) {
  const verdict = classify(health);
  const asOf = "as_of" in health ? health.as_of : null;

  return (
    <div
      role="group"
      aria-label="Fleet health across every installation"
      className="mono ml-auto flex items-stretch overflow-hidden rounded-[5px] border border-border bg-card text-[11.5px]"
    >
      {verdict.cells.map((cell) => {
        // A detail that parses as a timestamp renders as an age against
        // as_of; anything else is already prose from the classifier.
        const detail =
          cell.detail && asOf && !Number.isNaN(Date.parse(cell.detail))
            ? age(cell.detail, asOf)
            : cell.detail;
        return (
          <span
            key={cell.key}
            className={`flex items-center gap-1.5 border-r border-border/70 px-[11px] py-[5px] last:border-r-0 ${LEVEL_CLASS[cell.level]}`}
            aria-label={
              cell.count === null
                ? `${cell.word}: not available`
                : `${cell.word}: ${cell.count}${detail ? `, ${detail}` : ""}`
            }
          >
            {/* Unknown renders neither a count nor a zero: those are
                different facts and must never be confused. */}
            <span aria-hidden="true" className="font-semibold tabular-nums">
              {cell.count === null ? "—" : cell.count}
            </span>
            <span className="text-[10.5px]">{cell.word}</span>
            {detail ? (
              <span className="text-[10px] text-muted-foreground/70">{detail}</span>
            ) : null}
          </span>
        );
      })}
      <span className="flex items-center border-l border-border px-[9px] text-[9px] uppercase tracking-[.04em] text-muted-foreground/60">
        all tenants
      </span>
    </div>
  );
}
```

- [ ] **Step 3: Render it from `Shell`**

In `console/components/shell.tsx`: delete the local `HealthStrip` and
`HealthCell` placeholder functions entirely (lines 60–97 in the current
file, including the comment block that reserved the layout), add the import,
make `Shell` async, and fetch health:

```tsx
import { getHealth } from "@/lib/api";
import { HealthStrip } from "@/components/health-strip";

export async function Shell({
  scope,
  active,
  children,
}: {
  scope: ShellScope;
  active: "runs" | "jobs";
  children: React.ReactNode;
}) {
  // Server-rendered per page load. No polling: the pages are already
  // force-dynamic so a refresh is a fresh read, and a polling client
  // component would need its own stale and error states — one more thing
  // that can render "clear" while being wrong.
  const health = await getHealth();
```

Then replace `<HealthStrip />` with `<HealthStrip health={health} />`.

- [ ] **Step 4: Verify the build and tests**

Run from `console/`:
```bash
npm test        # expect 68 passing, unchanged from Task 5
npm run lint
npm run build
```
Expected: all three succeed. `npm run build` is the step that catches the
`Shell` signature change breaking `app/page.tsx`, since `Shell` is now async.

- [ ] **Step 5: Commit**

```bash
git add console/lib/api.ts console/components/health-strip.tsx console/components/shell.tsx
git commit -m "Wire the real health strip into the console chrome

Replaces the Phase 1 ghosted placeholder, whose four cells (running,
pending, failed 24h, clocks due) had nowhere to put terminal-failed as
distinct from failed-in-24h, retrying as distinct from pending, stalled at
all, or the unknown state. The visual treatment is kept.

The strip is global, never scoped: a scope filter that can hide a fire in
another tenant is an anti-feature on this surface, and a global strip
above a filtered table needs no disagreement rule because it never claims
to describe that table. It says 'all tenants' in words.

Server-rendered per page load rather than polled -- a polling client
component would need its own stale and error states, which is one more
thing that can render clear while being wrong."
```

---

### Task 7: The `/jobs` page, the nav, and the Phase 1 spec corrections

**Files:**
- Modify: `console/lib/api.ts`
- Create: `console/components/jobs-table.tsx`
- Create: `console/app/jobs/page.tsx`
- Modify: `console/components/shell.tsx` (nav tab)
- Modify: `docs/superpowers/specs/2026-08-06-doug-console-design.md`

**Interfaces:**
- Consumes: `GET /v1/jobs` from Task 4; `Shell`'s widened `active` prop from Task 6.
- Produces: the `/jobs` route. Nothing later depends on it.

- [ ] **Step 1: Add `getJobs` and the row type to `lib/api.ts`**

```typescript
/** Mirrors JobItem in api/doug/models.py field-by-field.
 *
 *  `repo` is nullable because outcome_jobs carries only github_repo_id and
 *  installation_repos can be stale or absent entirely — the page renders the
 *  bare id in that case rather than guessing a name.
 *
 *  `stalled`, `retrying` and `overdue` are computed by the API against each
 *  lane's own lease and travel on the row, so this client never re-derives
 *  them against a constant it holds locally. */
export interface JobItem {
  id: number;
  lane: string;
  repo: string | null;
  github_repo_id: number;
  installation_id: number;
  pr_number: number;
  status: string;
  attempts: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  stalled: boolean;
  head_sha: string | null;
  enqueued_at: string | null;
  verdict_id: number | null;
  retrying: boolean;
  merge_commit_sha: string | null;
  window_days: number | null;
  due_at: string | null;
  merged_at: string | null;
  overdue: boolean;
}

export async function getJobs(params: {
  lane: "review" | "outcome";
  view: "unhealthy" | "all";
  repo?: string;
  installationId?: number;
  limit?: number;
}): Promise<{ items: JobItem[]; limit: number; offset: number } | { error: string }> {
  const q = new URLSearchParams();
  q.set("lane", params.lane);
  q.set("view", params.view);
  if (params.repo) q.set("repo", params.repo);
  // Explicit presence, not truthiness: installation id 0 is falsy but is a
  // value the caller passed, not an absent one — the same trap parseTenantId
  // exists to close on the Runs page.
  if (params.installationId !== undefined) {
    q.set("installation_id", String(params.installationId));
  }
  q.set("limit", String(params.limit ?? 100));
  return get<{ items: JobItem[]; limit: number; offset: number }>(`/v1/jobs?${q}`);
}
```

- [ ] **Step 2: Create `components/jobs-table.tsx`**

```tsx
import Link from "next/link";

import type { JobItem } from "@/lib/api";

/** The reason a row is here, in words. Derived server-side against each
 *  lane's own lease and carried on the row, so this component never
 *  recomputes it — that is what keeps this page and the strip agreeing. */
function reason(job: JobItem): string {
  if (job.status === "failed") return `failed after ${job.attempts}`;
  if (job.stalled) return "lease expired";
  if (job.overdue) return "clock overdue";
  if (job.retrying) return `retrying, attempt ${job.attempts}`;
  if (job.status === "done" && job.verdict_id === null) return "skipped, no verdict";
  return job.status;
}

export function JobsTable({
  title,
  jobs,
  atCap,
  limit,
  maxAttempts,
}: {
  title: string;
  jobs: JobItem[];
  atCap: boolean;
  limit: number;
  maxAttempts: number;
}) {
  return (
    <section className="mt-8">
      <h2 className="mono text-xs uppercase tracking-[.08em] text-muted-foreground">
        {title}{" "}
        <span className="text-muted-foreground/70">
          {atCap ? `newest ${limit} fetched` : `${jobs.length} in scope`}
        </span>
      </h2>

      {jobs.length === 0 ? (
        // Empty is not zero, and this says which one it is.
        <p className="mono mt-3 text-xs text-muted-foreground">
          No jobs in this lane match the current filter.
        </p>
      ) : (
        <table className="mono mt-3 w-full text-left text-xs">
          <thead className="text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">
            <tr>
              <th className="py-1.5 pr-3 font-medium">id</th>
              <th className="py-1.5 pr-3 font-medium">repo / PR</th>
              <th className="py-1.5 pr-3 font-medium">state</th>
              <th className="py-1.5 pr-3 font-medium">attempts</th>
              <th className="py-1.5 font-medium">error</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={`${job.lane}-${job.id}`} className="border-t border-border/60 align-top">
                <td className="py-2 pr-3 tabular-nums text-muted-foreground">{job.id}</td>
                <td className="py-2 pr-3">
                  {/* A missing repo name renders the bare id. installation_repos
                      can be stale or absent, and a guessed name would be the
                      console claiming something it does not know. */}
                  {job.repo ?? (
                    <span className="text-muted-foreground">
                      repo id {job.github_repo_id}
                    </span>
                  )}{" "}
                  <span className="text-muted-foreground">#{job.pr_number}</span>
                  {job.verdict_id !== null ? (
                    <Link
                      href={`/runs/${job.verdict_id}`}
                      className="ml-2 underline underline-offset-2"
                    >
                      forensics
                    </Link>
                  ) : null}
                </td>
                <td className="py-2 pr-3">{reason(job)}</td>
                <td className="py-2 pr-3 tabular-nums">
                  {job.attempts}/{maxAttempts}
                </td>
                <td className="py-2 whitespace-pre-wrap break-all text-muted-foreground">
                  {/* Rendered in full, untruncated: an operator needs the whole
                      exception string, and this console is IAM-gated. */}
                  {job.error ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Create `app/jobs/page.tsx`**

```tsx
import { JobsTable } from "@/components/jobs-table";
import { Shell } from "@/components/shell";
import { getHealth, getJobs, isError } from "@/lib/api";
import { parseTenantId } from "@/lib/runs";

export const dynamic = "force-dynamic";

const PAGE_LIMIT = 500;

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<{ repo?: string; tenant?: string; view?: string }>;
}) {
  const params = await searchParams;
  const scope = { tenant: params.tenant ?? null, repo: params.repo ?? null };
  const view = params.view === "all" ? "all" : "unhealthy";

  // Same contract as the Runs page: a tenant that does not parse to a real
  // installation id must not silently fall back to "no filter".
  const tenant = parseTenantId(params.tenant);
  const installationId = tenant.kind === "present" ? tenant.id : undefined;

  const [review, outcome, health] =
    tenant.kind === "invalid"
      ? [
          { error: `tenant=${params.tenant} is not a valid installation id` },
          { error: `tenant=${params.tenant} is not a valid installation id` },
          await getHealth(),
        ]
      : await Promise.all([
          getJobs({ lane: "review", view, repo: params.repo, installationId, limit: PAGE_LIMIT }),
          getJobs({ lane: "outcome", view, repo: params.repo, installationId, limit: PAGE_LIMIT }),
          getHealth(),
        ]);

  // The caps come from the health payload, not from a literal here: the two
  // lanes differ (3 vs 10) and the console must never hardcode either.
  const caps = isError(health)
    ? { review: 0, outcome: 0 }
    : { review: health.review.max_attempts, outcome: health.outcome.max_attempts };

  return (
    <Shell scope={scope} active="jobs">
      <div className="mono mt-6 flex items-center gap-3 text-xs">
        <span className="text-muted-foreground">showing</span>
        <a
          href={`?${new URLSearchParams({ ...params, view: "unhealthy" })}`}
          aria-current={view === "unhealthy" ? "true" : undefined}
          className="rounded-[4px] border border-border px-2 py-1 aria-[current]:border-[var(--iridescent)] aria-[current]:font-semibold"
        >
          unhealthy only
        </a>
        <a
          href={`?${new URLSearchParams({ ...params, view: "all" })}`}
          aria-current={view === "all" ? "true" : undefined}
          className="rounded-[4px] border border-border px-2 py-1 aria-[current]:border-[var(--iridescent)] aria-[current]:font-semibold"
        >
          every job
        </a>
      </div>

      {[
        { key: "review", title: "Review lane", result: review, cap: caps.review },
        { key: "outcome", title: "Outcome lane (adjudicator)", result: outcome, cap: caps.outcome },
      ].map(({ key, title, result, cap }) =>
        isError(result) ? (
          // Never a number, never an empty table. An unreachable API and a
          // lane with no unhealthy jobs are different facts.
          <div
            key={key}
            className="mono mt-8 rounded-[6px] border border-[var(--flag)]/40 bg-[color-mix(in_srgb,var(--flag)_6%,transparent)] p-4 text-xs"
          >
            <p className="font-semibold text-[var(--flag)]">
              {title}: the API did not answer.
            </p>
            <p className="mt-1 text-muted-foreground">{result.error}</p>
          </div>
        ) : (
          <JobsTable
            key={key}
            title={title}
            jobs={result.items}
            atCap={result.items.length >= result.limit}
            limit={result.limit}
            maxAttempts={cap}
          />
        ),
      )}
    </Shell>
  );
}
```

- [ ] **Step 4: Add the Jobs nav tab**

In `console/components/shell.tsx`, immediately after the existing `Runs`
`<Link>` and before the ghosted `Repos` span:

```tsx
        <Link
          href="/jobs"
          aria-current={active === "jobs" ? "page" : undefined}
          className="mono -mb-px border-b-2 border-transparent px-3 pt-2 pb-2 text-xs uppercase tracking-[.06em] text-muted-foreground aria-[current]:border-b-[var(--iridescent)] aria-[current]:font-semibold aria-[current]:text-foreground"
        >
          Jobs
        </Link>
```

- [ ] **Step 5: Correct the Phase 1 design doc**

In `docs/superpowers/specs/2026-08-06-doug-console-design.md`:

Replace the `/v1/health` row of the Decision 3 table with:

```
| `GET /v1/health` | Job counts by status, oldest pending age, 24-hour failures, outcome clocks due. (AMENDED 2026-08-07: the original row also listed per-installation `reconciled_at`. That column does not exist — it is MT3 / migration 8, unstarted — so it was never buildable as written. See `2026-08-07-console-health-failure-surface-design.md`.) |
```

Replace the Phase 2 row of the Decision 6 table with these two rows:

```
| 2a | `/v1/health`, `/v1/jobs`, health strip, Jobs page | "is it healthy", "is Doug failing on anything" |
| 2b | `/v1/repos`, Repos page | "per repos" |
```

- [ ] **Step 6: Verify**

Run from `console/`:
```bash
npm test        # expect 68 passing
npm run lint
npm run build
```
Expected: all three succeed. The build is what proves `active="jobs"` type-checks
against the widened union and that the new route compiles.

- [ ] **Step 7: Commit**

```bash
git add console/lib/api.ts console/components/jobs-table.tsx console/app/jobs/page.tsx console/components/shell.tsx docs/superpowers/specs/2026-08-06-doug-console-design.md
git commit -m "Add the /jobs failure page and correct the Phase 1 design

Two labelled lane sections rather than one blended table: the review lane
is keyed on head SHA with a 900s lease and a cap of 3, the outcome lane on
merge SHA with a due date, a 7200s lease and a cap of 10. Blending them
produces columns empty for half the rows -- the same objection that kept
the spine verdict-keyed, one level down.

Default filter is unhealthy only, with a toggle to show every job,
because 'the job I expected does not exist at all' is a real diagnosis
only a complete list reaches.

The attempt caps are read from the health payload rather than written as
literals, so the page can never render 4/3 on a lane whose cap is ten.

Corrects the Phase 1 design on two points: its /v1/health listed
installations.reconciled_at, which does not exist, and its Phase 2 row
bundled the health strip with /v1/repos."
```

---

## Verification Before Completion

After Task 7, before opening a PR:

- [ ] From `api/`: `uv run pytest` — full suite passes; note the count against Phase 1's 691.
- [ ] From `api/`: `uv run ruff check .` — clean.
- [ ] From `console/`: `npm test` — 68 passing.
- [ ] From `console/`: `npm run lint` and `npm run build` — both clean.
- [ ] Confirm the operator gate is non-vacuous on **both** new routes by removing `_operator_only` from each in turn and watching the paired tests fail, then restoring. Phase 1's gate test on the console's Cloud Run binding was verified this way and it is the convention here.
- [ ] Reread the honesty rules in the spec's Decision 4 against the running UI: `superseded` appears in no count; unknown and clear render differently; every strip cell carries its word; no attempt count renders against the wrong lane's cap.

### Known test-coverage gap, stated rather than hidden

The spec's testing section lists *"attempts rendered against the wrong
lane's cap fails a test"*. **This plan does not deliver that test.** It is a
rendering assertion about `JobsTable`, and no page- or component-level test
infrastructure exists in `console/` — that is still its own Phase 2 item.

What this plan does instead is remove the opportunity for the bug: the caps
are never written as literals in the console, `app/jobs/page.tsx` reads
`max_attempts` per lane from the `/v1/health` payload, and Task 1 pins that
the payload reports the values the queues actually enforce. The failure mode
survives only as "the page passes the wrong lane's cap to the right table",
which is one line, visible in review, and impossible to get wrong silently
once each lane's section is constructed from its own entry.

Do not mark the spec's testing section fully satisfied. When render-test
infrastructure lands, this is the first assertion to add.

**Deploy note, not a task:** `doug-console` does not redeploy on merge. It
needs `PROJECT=doug-prod0 REGION=us-central1 bash deploy/gcp.sh console`,
and `doug-api` must be deployed first or the console will render its
explicit failure state against a 404 on both new routes.
