# doug-console Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an IAM-gated operator console whose run-forensics page answers "what did Doug actually do with this PR?" end to end, backed by two new operator-only API endpoints.

**Architecture:** Two new read-only store queries (`run_history`, `run_detail`) feed two new FastAPI routes behind the existing `_operator_only` gate. A new Next application at `repo/console/` — separate from `repo/web/`, never sharing a build — renders a dense Runs table and a forensic detail page, and deploys as its own Cloud Run service with `--no-allow-unauthenticated`.

**Tech Stack:** FastAPI + SQLAlchemy Core + Pydantic (api), Next 16.2.12 + React 19 + Tailwind 4 (console), pytest, `node --test`, Cloud Run.

**Spec:** `docs/superpowers/specs/2026-08-06-doug-console-design.md`
**Design reference:** `workspace/mockups/console.html` (rendered mockup — match its layout and colour rules)

## Global Constraints

Every task's requirements implicitly include this section.

- **Python lint:** ruff, `line-length = 100`, `select = ["E", "F", "I", "UP", "B"]`. Run `cd api && uv run ruff check .` before every commit.
- **Python tests:** `cd api && uv run pytest`. There is no `conftest.py`; tests build their own sqlite ledger via a local `_db(tmp_path, monkeypatch)` helper.
- **Console tests:** `cd console && npm test` → `node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test --experimental-strip-types lib/*.test.mjs`.
- **Next 16.2.12 is NOT the Next.js you know.** Per `web/AGENTS.md`: read the relevant guide in `node_modules/next/dist/docs/` before writing any Next code. APIs, conventions and file structure differ from training data.
- **The console never falls back to a fixture.** An unreachable or malformed API renders an explicit failure state. Inventing data on an operator console defeats its purpose.
- **Coverage denominator is `pr_meta.changed_files`, never `len(files)`.** `files` is the paginated list actually fetched and can be short of the true count. `changed_files is None` renders "denominator unknown", never a percentage.
- **Exactly two data colours:** `--flag #c93a2b` and `--clear #177a50`, each always accompanied by its word. `--iridescent #d1571e` is chrome only — it fails CVD separation against `--flag` at ΔE 6.1 in normal vision. Low coverage is alarmed by the ruler's emptiness, never by hue.
- **No rate without its denominator; empty is not zero.**
- **Work happens on branch `console-design`**, worktree `.claude/worktrees/console-design`.

---

### Task 1: `store.run_history()` — verdict history, correctly scoped

**Files:**
- Modify: `api/doug/store.py` (add after `latest_reviews`, which ends at line 1312)
- Test: `api/tests/test_store.py`

**Interfaces:**
- Consumes: `verdicts` table, `EXTERNAL_TIER` (`store.py:347`)
- Produces: `store.run_history(limit: int = 100, offset: int = 0, repo: str | None = None, installation_id: int | None = None, include_untenanted: bool = False) -> list[dict]` — returns raw `verdicts` column dicts, newest `scored_at` first. Task 2 extends the same function; Task 3 consumes it.

**Why this is not `latest_reviews`:** `latest_reviews` groups by `(repo, pr_number)` and keeps `max(id)` — one row per PR. A PR pushed three times is three runs and the console must show all three. `latest_reviews` also drops `repo` from its wire model, which is the specific reason the current UI cannot group per repo.

**Why `installation_id IS NOT NULL` is the default filter:** `migrations.py:211-217` states the research-corpus quarantine convention — research rows carry a reserved sentinel installation id, and *"every tenant-facing counter therefore stays correct by filtering on real installation ids rather than by excluding a label after the fact."* Backfilled probe corpora and CLI rows also carry no installation. `DOUG_QUEUE_REPO` exists on doug-web solely to keep those out of the queue; the console filters structurally instead.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_store.py`:

```python
def test_run_history_returns_every_run_for_a_pr_not_just_the_latest(tmp_path, monkeypatch):
    """The defining difference from latest_reviews. A PR pushed three times
    is three runs; a console that collapses them cannot answer "what did
    Doug do on this push" — which is the whole point of the page."""
    _db(tmp_path, monkeypatch)
    for sha in ("a" * 40, "b" * 40, "c" * 40):
        store.save_review(
            "o/r", 7, "reader", VERDICT,
            github_repo_id=1, installation_id=99, head_sha=sha, source="app",
        )
    rows = store.run_history()
    assert len(rows) == 3
    assert {r["head_sha"] for r in rows} == {"a" * 40, "b" * 40, "c" * 40}
    assert store.latest_reviews() and len(store.latest_reviews()) == 1


def test_run_history_carries_repo_and_installation(tmp_path, monkeypatch):
    """The field latest_reviews drops. Without it the console cannot group
    per repo, which is the reported gap."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    row = store.run_history()[0]
    assert row["repo"] == "o/r"
    assert row["installation_id"] == 99
    assert row["github_repo_id"] == 1


def test_run_history_excludes_untenanted_rows_by_default(tmp_path, monkeypatch):
    """Backfilled probe corpora, CLI rows and the research quarantine all
    carry no installation_id. Including them would flood the console with
    thousands of rows that are not tenant traffic — the exact failure
    DOUG_QUEUE_REPO exists to paper over on doug-web."""
    _db(tmp_path, monkeypatch)
    store.save_review("o/r", 1, "reader", VERDICT)  # no installation — CLI/backfill
    store.save_review(
        "o/r", 2, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    assert [r["pr_number"] for r in store.run_history()] == [2]
    assert {r["pr_number"] for r in store.run_history(include_untenanted=True)} == {1, 2}


def test_run_history_excludes_external_tier(tmp_path, monkeypatch):
    """External rows are other reviewers' verdicts, not Doug's runs."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 1, store.EXTERNAL_TIER, VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40,
    )
    assert store.run_history() == []


def test_run_history_scopes_by_repo_and_installation(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/one", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=11, head_sha="a" * 40, source="app",
    )
    store.save_review(
        "o/two", 2, "reader", VERDICT,
        github_repo_id=2, installation_id=22, head_sha="b" * 40, source="app",
    )
    assert [r["repo"] for r in store.run_history(repo="o/one")] == ["o/one"]
    assert [r["installation_id"] for r in store.run_history(installation_id=22)] == [22]


def test_run_history_paginates_newest_first(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    base = datetime(2026, 8, 1, tzinfo=UTC)
    for n in range(5):
        vid = store.save_review(
            "o/r", n, "reader", VERDICT,
            github_repo_id=1, installation_id=99, head_sha=str(n) * 40, source="app",
        )
        engine = store._get_engine()
        with engine.begin() as conn:
            conn.execute(
                store.verdicts.update()
                .where(store.verdicts.c.id == vid)
                .values(scored_at=base + timedelta(hours=n))
            )
    assert [r["pr_number"] for r in store.run_history(limit=2)] == [4, 3]
    assert [r["pr_number"] for r in store.run_history(limit=2, offset=2)] == [2, 1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && uv run pytest tests/test_store.py -k run_history -v`
Expected: 6 FAILs with `AttributeError: module 'doug.store' has no attribute 'run_history'`

- [ ] **Step 3: Write the implementation**

Add to `api/doug/store.py`, immediately after `latest_reviews`:

```python
def run_history(
    limit: int = 100,
    offset: int = 0,
    repo: str | None = None,
    installation_id: int | None = None,
    include_untenanted: bool = False,
) -> list[dict]:
    """Verdict HISTORY, newest first — every run, not one row per PR.

    `latest_reviews` answers "what is the current state of the queue".
    This answers "what has Doug done", which is a different question: a PR
    pushed three times is three runs, and collapsing them hides exactly the
    comparison an operator opens the console to make.

    Untenanted rows (installation_id IS NULL) are excluded by default. That
    is the filter migrations.py:211 names as the correct one — real
    installation ids rather than a label — and it is what keeps backfilled
    probe corpora, CLI rows and the research quarantine out of a console
    that is meant to show tenant traffic.
    """
    engine = _get_engine()
    if engine is None or limit < 1 or offset < 0:
        return []
    from sqlalchemy import desc, select

    query = select(verdicts).where(verdicts.c.tier != EXTERNAL_TIER)
    if not include_untenanted:
        query = query.where(verdicts.c.installation_id.is_not(None))
    if repo:
        query = query.where(verdicts.c.repo == repo)
    if installation_id is not None:
        query = query.where(verdicts.c.installation_id == installation_id)
    query = (
        query.order_by(desc(verdicts.c.scored_at), desc(verdicts.c.id))
        .limit(limit)
        .offset(offset)
    )
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(query).mappings()]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && uv run pytest tests/test_store.py -k run_history -v`
Expected: 6 PASS

- [ ] **Step 5: Run the full suite and lint**

Run: `cd api && uv run pytest && uv run ruff check .`
Expected: all pass (657 tests + the 6 new), ruff clean

- [ ] **Step 6: Commit**

```bash
git add api/doug/store.py api/tests/test_store.py
git commit -m "store: run_history — verdict history, not latest-per-PR

latest_reviews keeps max(id) per (repo, pr_number), so a PR pushed three
times renders as one row and the console cannot show what changed between
pushes. It also drops repo, which is why per-repo grouping is impossible
today. Untenanted rows are excluded structurally, per the filter rule
migrations.py:211 already states."
```

---

### Task 2: `run_history` enrichment — coverage, findings, job, outcome

**Files:**
- Modify: `api/doug/store.py` (`run_history`, added in Task 1)
- Test: `api/tests/test_store.py`

**Interfaces:**
- Consumes: `store.run_history` (Task 1), `reads`, `findings`, `review_jobs`, `outcomes` tables
- Produces: each `run_history` dict gains four keys — `coverage: dict | None` (`{diff_chars, sent_chars, files_sent, files_unseen, file_cut}`), `finding_counts: dict` (`{total, high, medium, low}`), `job: dict | None` (`{status, attempts, error, enqueued_at, started_at, finished_at}`), `outcome_14: str | None` (the `kind`). Task 3 serialises these.

**The fan-out hazard:** a plain `outerjoin` to `reads` or `outcomes` duplicates a verdict row whenever two child rows match, and a duplicated run in the list is a silent correctness bug. Use the id-picking subquery pattern `comparison_reviews` already establishes (`store.py:1697-1712`): aggregate to one id per parent, then join the aliased table on that id.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_store.py`:

```python
def test_run_history_attaches_coverage_without_duplicating_runs(tmp_path, monkeypatch):
    """Two reads on one verdict must not become two runs. A plain outerjoin
    fans out here, and a duplicated run reads as a real second review."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
        coverage=store.Coverage(
            diff_chars=1000, sent_chars=170, files_sent=4,
            files_unseen=["tenancy.py"], file_cut="api.py",
        ),
    )
    store.save_read(vid, store.Coverage(
        diff_chars=1000, sent_chars=900, files_sent=20,
        files_unseen=[], file_cut=None,
    ))
    rows = store.run_history()
    assert len(rows) == 1
    assert rows[0]["coverage"]["files_sent"] in (4, 20)
    assert rows[0]["coverage"]["diff_chars"] == 1000


def test_run_history_coverage_is_none_for_the_deterministic_tier(tmp_path, monkeypatch):
    """No read happened, so there is no coverage. This must be None and
    render as "no read" — never as 0%, which would read as a total miss."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 1, "deterministic", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    assert store.run_history()[0]["coverage"] is None


def test_run_history_counts_findings_by_severity(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    verdict = Verdict(
        score=0.8, band=Band.FLAGGED, threshold=0.62,
        reasons=[
            Reason(rule="reader:a", label="a", weight=0.0, severity="high"),
            Reason(rule="reader:b", label="b", weight=0.0, severity="low"),
            Reason(rule="reader:c", label="c", weight=0.0, severity="low"),
        ],
    )
    store.save_review(
        "o/r", 1, "reader", verdict,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    counts = store.run_history()[0]["finding_counts"]
    assert counts == {"total": 3, "high": 1, "medium": 0, "low": 2}


def test_run_history_attaches_the_review_job(tmp_path, monkeypatch):
    """The job row is the "what did Doug do" record: attempts and error are
    the only place a failed run explains itself."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.review_jobs.insert().values(
            installation_id=99, github_repo_id=1, repo_full_name="o/r",
            pr_number=1, head_sha="a" * 40, status="done", attempts=2,
            enqueued_at=datetime(2026, 8, 1, tzinfo=UTC),
            finished_at=datetime(2026, 8, 1, 0, 0, 41, tzinfo=UTC),
            verdict_id=vid,
        ))
    job = store.run_history()[0]["job"]
    assert job["status"] == "done"
    assert job["attempts"] == 2


def test_run_history_reports_only_the_14_day_outcome(tmp_path, monkeypatch):
    """Both windows exist for a merged PR. The list column is the 14d one;
    joining both would fan the run out into two rows."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        for window, kind in ((14, "clean"), (60, "revert")):
            conn.execute(store.outcomes.insert().values(
                repo="o/r", pr_number=1, kind=kind, window_days=window,
                observed_at=datetime(2026, 8, 15, tzinfo=UTC), source="git-labels",
                github_repo_id=1, installation_id=99,
            ))
    rows = store.run_history()
    assert len(rows) == 1
    assert rows[0]["outcome_14"] == "clean"


def test_run_history_outcome_is_none_before_the_window_closes(tmp_path, monkeypatch):
    """Ungraded is not clean. The console must render these differently."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    assert store.run_history()[0]["outcome_14"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && uv run pytest tests/test_store.py -k run_history -v`
Expected: the 6 new tests FAIL with `KeyError: 'coverage'` / `KeyError: 'finding_counts'` / `KeyError: 'job'` / `KeyError: 'outcome_14'`

- [ ] **Step 3: Write the implementation**

Replace the body of `run_history` in `api/doug/store.py` (keep the docstring, append this paragraph to it):

```
    Each row carries `coverage`, `finding_counts`, `job` and `outcome_14`.
    Every child join goes through an id-picking subquery — the pattern
    comparison_reviews uses — because a plain outerjoin duplicates the
    verdict row whenever two children match, and a duplicated run reads as
    a real second review rather than as a bug.
```

```python
    engine = _get_engine()
    if engine is None or limit < 1 or offset < 0:
        return []
    from sqlalchemy import case, desc, func, select

    query = select(verdicts).where(verdicts.c.tier != EXTERNAL_TIER)
    if not include_untenanted:
        query = query.where(verdicts.c.installation_id.is_not(None))
    if repo:
        query = query.where(verdicts.c.repo == repo)
    if installation_id is not None:
        query = query.where(verdicts.c.installation_id == installation_id)
    query = (
        query.order_by(desc(verdicts.c.scored_at), desc(verdicts.c.id))
        .limit(limit)
        .offset(offset)
    )

    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(query).mappings()]
        if not rows:
            return rows
        ids = [r["id"] for r in rows]

        # One read per verdict: newest by id. A verdict can carry more than
        # one (a retried read writes a second row), and both are real.
        read_ids = (
            select(reads.c.verdict_id, func.max(reads.c.id).label("read_id"))
            .where(reads.c.verdict_id.in_(ids))
            .group_by(reads.c.verdict_id)
            .subquery()
        )
        cov_by_verdict = {
            row["verdict_id"]: {
                "diff_chars": row["diff_chars"],
                "sent_chars": row["sent_chars"],
                "files_sent": row["files_sent"],
                "files_unseen": row["files_unseen"],
                "file_cut": row["file_cut"],
            }
            for row in conn.execute(
                select(reads).join(read_ids, read_ids.c.read_id == reads.c.id)
            ).mappings()
        }

        counts_by_verdict = {
            row["verdict_id"]: {
                "total": row["total"],
                "high": row["high"],
                "medium": row["medium"],
                "low": row["low"],
            }
            for row in conn.execute(
                select(
                    findings.c.verdict_id,
                    func.count().label("total"),
                    func.sum(case((findings.c.severity == "high", 1), else_=0)).label("high"),
                    func.sum(case((findings.c.severity == "medium", 1), else_=0)).label("medium"),
                    func.sum(case((findings.c.severity == "low", 1), else_=0)).label("low"),
                )
                .where(findings.c.verdict_id.in_(ids))
                .group_by(findings.c.verdict_id)
            ).mappings()
        }

        job_by_verdict = {
            row["verdict_id"]: {
                "status": row["status"],
                "attempts": row["attempts"],
                "error": row["error"],
                "enqueued_at": row["enqueued_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
            for row in conn.execute(
                select(review_jobs).where(review_jobs.c.verdict_id.in_(ids))
            ).mappings()
        }

        # 14-day only. Both windows exist for a merged PR, and carrying both
        # into a list column is what fans one run out into two.
        keys = {(r["repo"], r["pr_number"]) for r in rows}
        outcome_by_pr = {
            (row["repo"], row["pr_number"]): row["kind"]
            for row in conn.execute(
                select(outcomes)
                .where(outcomes.c.window_days == 14)
                .where(outcomes.c.repo.in_({k[0] for k in keys}))
                .order_by(outcomes.c.id)
            ).mappings()
        }

    zero = {"total": 0, "high": 0, "medium": 0, "low": 0}
    for row in rows:
        row["coverage"] = cov_by_verdict.get(row["id"])
        row["finding_counts"] = counts_by_verdict.get(row["id"], dict(zero))
        row["job"] = job_by_verdict.get(row["id"])
        row["outcome_14"] = outcome_by_pr.get((row["repo"], row["pr_number"]))
    return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && uv run pytest tests/test_store.py -k run_history -v`
Expected: 12 PASS

- [ ] **Step 5: Run the full suite and lint**

Run: `cd api && uv run pytest && uv run ruff check .`
Expected: all pass, ruff clean

- [ ] **Step 6: Commit**

```bash
git add api/doug/store.py api/tests/test_store.py
git commit -m "store: attach coverage, findings, job and outcome to run_history

Every child is fetched through an id-picking subquery or an in_() lookup
rather than an outerjoin: two reads on one verdict, or the 14d and 60d
outcomes on one PR, would otherwise fan the run out into two rows, which
reads as a real second review rather than as a bug."
```

---

### Task 3: `GET /v1/runs` — the list endpoint

**Files:**
- Modify: `api/doug/models.py` (append after `QueueResponse`, line ~120)
- Modify: `api/doug/api.py` (add route after `/v1/queue`, which ends at line ~410)
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: `store.run_history` (Tasks 1–2), `_operator_only` (`api.py:246`)
- Produces: `GET /v1/runs?limit&offset&repo&installation_id` → `RunListResponse`. Wire models `RunCoverage`, `RunFindingCounts`, `RunJob`, `RunSummaryItem`, `RunListResponse` in `models.py`; the console's `lib/api.ts` mirrors these types in Task 7.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_api.py`:

```python
def test_runs_refuses_without_the_operator_token(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/runs").status_code == 401


def test_runs_404s_a_tenant_key(tmp_path, monkeypatch):
    """A resolving tenant key is a real credential at the wrong door, so it
    gets the same no-existence-leak 404 _operator_only gives everywhere."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setattr(tenancy, "resolve", lambda t: tenancy.TokenContext(
        installation_id=99, token_id=1, repo_ids=None, scopes=("queue:read",),
    ))
    client = TestClient(app)
    assert client.get("/v1/runs", headers={"X-Doug-Token": "dg_tenant"}).status_code == 404


def test_runs_returns_repo_and_installation_on_every_item(tmp_path, monkeypatch):
    """The fields /v1/queue drops. Without them the console cannot group
    per repo, which is the gap this endpoint exists to close."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    client = TestClient(app)
    item = client.get("/v1/runs", headers=AUTH).json()["items"][0]
    assert item["repo"] == "o/r"
    assert item["installation_id"] == 99
    assert item["verdict_id"] > 0


def test_runs_serialises_a_missing_read_as_null_not_zero(tmp_path, monkeypatch):
    """A deterministic run had no read. Zero coverage would claim Doug read
    nothing of a diff it never opened — empty is not zero."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "deterministic", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    client = TestClient(app)
    assert client.get("/v1/runs", headers=AUTH).json()["items"][0]["coverage"] is None


def test_runs_rejects_an_out_of_range_limit(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/runs?limit=0", headers=AUTH).status_code == 422
    assert client.get("/v1/runs?limit=501", headers=AUTH).status_code == 422


def test_runs_503s_without_a_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    client = TestClient(app)
    assert client.get("/v1/runs", headers=AUTH).status_code == 503
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && uv run pytest tests/test_api.py -k "test_runs_" -v`
Expected: 6 FAILs, mostly 404 from FastAPI (no such route)

- [ ] **Step 3: Add the wire models**

Append to `api/doug/models.py`:

```python
class RunCoverage(BaseModel):
    """What the reader was actually given. None on the whole object means no
    read happened — never zeros, which would claim Doug read nothing of a
    diff it never opened."""

    diff_chars: int
    sent_chars: int
    files_sent: int
    files_unseen: list[str]
    file_cut: str | None


class RunFindingCounts(BaseModel):
    total: int
    high: int
    medium: int
    low: int


class RunJob(BaseModel):
    status: str
    attempts: int
    error: str | None
    enqueued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class RunSummaryItem(BaseModel):
    verdict_id: int
    repo: str
    installation_id: int | None
    github_repo_id: int | None
    pr_number: int
    title: str
    url: str | None
    scored_at: datetime
    tier: str
    source: str | None
    score: float
    band: Band
    threshold: float
    coverage: RunCoverage | None
    changed_files: int | None
    finding_counts: RunFindingCounts
    job: RunJob | None
    outcome_14: str | None


class RunListResponse(BaseModel):
    items: list[RunSummaryItem]
    limit: int
    offset: int
```

Add `from datetime import datetime` to the imports at the top of `models.py`.

- [ ] **Step 4: Add the route**

Add to `api/doug/api.py` after the `/v1/queue` handler, and extend the `.models` import block with `RunCoverage, RunFindingCounts, RunJob, RunListResponse, RunSummaryItem`:

```python
def _run_item(row: dict) -> RunSummaryItem:
    """One ledger row as a list item.

    `changed_files` travels separately from `coverage` because it is GitHub's
    own count on pr_meta, and it is the ONLY correct denominator for a
    coverage percentage — `len(files)` is the paginated list actually
    fetched and can be short on exactly the large PRs where coverage matters
    most. None here means the console renders "denominator unknown".
    """
    meta = _with_url(row)
    return RunSummaryItem(
        verdict_id=row["id"],
        repo=row["repo"],
        installation_id=row["installation_id"],
        github_repo_id=row["github_repo_id"],
        pr_number=row["pr_number"],
        title=meta.title,
        url=meta.url,
        scored_at=row["scored_at"],
        tier=row["tier"],
        source=row["source"],
        score=row["score"],
        band=Band(row["band"]),
        threshold=row["threshold"],
        coverage=RunCoverage(**row["coverage"]) if row["coverage"] else None,
        changed_files=meta.changed_files,
        finding_counts=RunFindingCounts(**row["finding_counts"]),
        job=RunJob(**row["job"]) if row["job"] else None,
        outcome_14=row["outcome_14"],
    )


@app.get("/v1/runs")
def runs(
    limit: int = 100,
    offset: int = 0,
    repo: str | None = None,
    installation_id: int | None = None,
    include_untenanted: bool = False,
    x_doug_token: str = Header(""),
) -> RunListResponse:
    """Verdict history for the operator console. Operator-only, permanently:
    this crosses every installation by design, which is exactly what no
    tenant credential may ever do."""
    _operator_only(x_doug_token)
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must not be negative")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    rows = store.run_history(
        limit=limit,
        offset=offset,
        repo=repo,
        installation_id=installation_id,
        include_untenanted=include_untenanted,
    )
    return RunListResponse(
        items=[_run_item(row) for row in rows], limit=limit, offset=offset
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd api && uv run pytest tests/test_api.py -k "test_runs_" -v`
Expected: 6 PASS

- [ ] **Step 6: Run the full suite and lint**

Run: `cd api && uv run pytest && uv run ruff check .`
Expected: all pass, ruff clean

- [ ] **Step 7: Commit**

```bash
git add api/doug/models.py api/doug/api.py api/tests/test_api.py
git commit -m "api: GET /v1/runs — operator-only verdict history

Carries repo and installation_id, which /v1/queue's QueueItem drops, and
changed_files alongside coverage because it is the only correct denominator
for a coverage percentage. Operator-only permanently: the endpoint crosses
installations by design."
```

---

### Task 4: `store.run_detail()` — the forensic bundle

**Files:**
- Modify: `api/doug/store.py` (add after `find_verdict_by_id`, line 1186)
- Test: `api/tests/test_store.py`

**Interfaces:**
- Consumes: `_verdict_bundle` (`store.py:1054`), `verdicts`, `review_jobs`, `outcome_jobs`, `outcomes`
- Produces: `store.run_detail(verdict_id: int) -> dict | None` — `_verdict_bundle`'s keys (`id`, `tier`, `score`, `band`, `threshold`, `reasons`, `deviations`, `intent_alignment`, `intent_refs`, `coverage`) plus `repo`, `pr_number`, `scored_at`, `model`, `prompt_hash`, `risk_score`, `rationale`, `head_sha`, `source`, `installation_id`, `github_repo_id`, `pr_meta`, `job`, `outcome_jobs`, `outcomes`. Task 5 serialises it.

**Why not `find_verdict_by_id`:** it returns `_verdict_bundle` alone, which deliberately drops `model`, `prompt_hash`, `risk_score`, `rationale`, `scored_at`, `source`, `head_sha`, `repo` and `pr_number` — everything the forensic page exists to show. It is the check-run render path, not an inspection path. Leave it untouched; four tests still drive it.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_store.py`:

```python
def test_run_detail_carries_the_fields_the_check_run_bundle_drops(tmp_path, monkeypatch):
    """_verdict_bundle serves the check run and omits provenance on purpose.
    The forensic page is the opposite need: model, prompt hash and rationale
    ARE the answer to "what did Doug do"."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, reader_verdict=RV, model="claude-opus-5",
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
        prompt_hash="a3f9e2c1",
    )
    detail = store.run_detail(vid)
    assert detail["repo"] == "o/r"
    assert detail["pr_number"] == 7
    assert detail["model"] == "claude-opus-5"
    assert detail["prompt_hash"] == "a3f9e2c1"
    assert detail["risk_score"] == 62
    assert detail["rationale"] == "Unlocked cache write."
    assert detail["source"] == "app"
    assert detail["head_sha"] == "a" * 40
    # and still everything the bundle already gave
    assert detail["reasons"][0]["rule"] == "reader:race-condition"


def test_run_detail_returns_none_for_an_unknown_id(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert store.run_detail(4242) is None


def test_run_detail_attaches_the_job_including_its_error(tmp_path, monkeypatch):
    """A failed run explains itself nowhere else."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.review_jobs.insert().values(
            installation_id=99, github_repo_id=1, repo_full_name="o/r",
            pr_number=7, head_sha="a" * 40, status="failed", attempts=3,
            claim_generation=3, error="reader timeout after 60s",
            enqueued_at=datetime(2026, 8, 1, tzinfo=UTC), verdict_id=vid,
        ))
    job = store.run_detail(vid)["job"]
    assert job["status"] == "failed"
    assert job["attempts"] == 3
    assert job["claim_generation"] == 3
    assert job["error"] == "reader timeout after 60s"


def test_run_detail_returns_both_outcome_windows_separately(tmp_path, monkeypatch):
    """The 14d and 60d clocks are different claims with different dates, and
    the page shows them side by side. Collapsing them loses the censoring
    story."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.outcomes.insert().values(
            repo="o/r", pr_number=7, kind="clean", window_days=14,
            observed_at=datetime(2026, 8, 17, tzinfo=UTC), source="git-labels",
            github_repo_id=1, installation_id=99,
        ))
        conn.execute(store.outcome_jobs.insert().values(
            installation_id=99, github_repo_id=1, pr_number=7,
            merge_commit_sha="b" * 40, merged_at=datetime(2026, 8, 3, tzinfo=UTC),
            base_ref="main", window_days=60,
            due_at=datetime(2026, 10, 2, tzinfo=UTC), status="pending",
            created_at=datetime(2026, 8, 3, tzinfo=UTC),
        ))
    detail = store.run_detail(vid)
    assert [o["window_days"] for o in detail["outcomes"]] == [14]
    assert detail["outcomes"][0]["kind"] == "clean"
    assert [j["window_days"] for j in detail["outcome_jobs"]] == [60]
    assert detail["outcome_jobs"][0]["status"] == "pending"


def test_run_detail_never_surfaces_the_no_deviations_marker(tmp_path, monkeypatch):
    """save_deviations writes a kind="none" row to record "the read ran and
    found nothing". It is a storage marker, never a finding. If it reached
    the page it would render as a deviation named "none" — Doug reporting a
    problem it explicitly did not find."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    # signature: (verdict_id, findings, intent_refs, intent_alignment)
    store.save_deviations(vid, [], intent_refs=[], intent_alignment=100)
    detail = store.run_detail(vid)
    assert detail["deviations"] == []
    # The row exists — "read happened, found nothing" stays distinguishable
    # from "no read happened", which is why the marker is written at all.
    assert detail["intent_alignment"] == 100


def test_run_detail_exposes_pr_meta_for_the_coverage_denominator(tmp_path, monkeypatch):
    """changed_files lives on pr_meta and is the only correct denominator.
    Without it on the detail payload the page would fall back to
    len(files_unseen) + files_sent, which is not the true file count."""
    _db(tmp_path, monkeypatch)
    meta = PRMetadata(
        number=7, title="t", author="a", files=["one.py"], changed_files=23,
        files_dropped=["uv.lock"],
    )
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, pr_meta=meta.model_dump(),
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    detail = store.run_detail(vid)
    assert detail["pr_meta"]["changed_files"] == 23
    assert detail["pr_meta"]["files_dropped"] == ["uv.lock"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && uv run pytest tests/test_store.py -k run_detail -v`
Expected: 5 FAILs with `AttributeError: module 'doug.store' has no attribute 'run_detail'`

- [ ] **Step 3: Write the implementation**

Add to `api/doug/store.py` immediately after `find_verdict_by_id`:

```python
def run_detail(verdict_id: int) -> dict | None:
    """Everything the console's forensic page shows for one run.

    _verdict_bundle deliberately omits provenance — it renders a check run,
    where model and prompt hash are noise. This page has the opposite need:
    those fields ARE the answer to "what did Doug do with this PR". Rather
    than widen the bundle and change what every check run carries, this
    composes it with the columns it drops.
    """
    engine = _get_engine()
    if engine is None:
        return None
    from sqlalchemy import select

    with engine.connect() as conn:
        v = conn.execute(
            select(verdicts).where(verdicts.c.id == verdict_id).limit(1)
        ).mappings().first()
        if v is None:
            return None
        detail = _verdict_bundle(conn, v)
        detail.update(
            {
                "repo": v["repo"],
                "pr_number": v["pr_number"],
                "scored_at": v["scored_at"],
                "model": v["model"],
                "prompt_hash": v["prompt_hash"],
                "risk_score": v["risk_score"],
                "rationale": v["rationale"],
                "head_sha": v["head_sha"],
                "source": v["source"],
                "installation_id": v["installation_id"],
                "github_repo_id": v["github_repo_id"],
                "pr_meta": v["pr_meta"],
            }
        )
        job = conn.execute(
            select(review_jobs).where(review_jobs.c.verdict_id == verdict_id).limit(1)
        ).mappings().first()
        detail["job"] = (
            {
                "status": job["status"],
                "attempts": job["attempts"],
                "claim_generation": job["claim_generation"],
                "error": job["error"],
                "enqueued_at": job["enqueued_at"],
                "started_at": job["started_at"],
                "finished_at": job["finished_at"],
            }
            if job
            else None
        )
        # Outcomes key on (repo, pr_number), not on the verdict: a PR scored
        # three times has one merge and one set of clocks, shared by all
        # three runs. Both windows travel separately — they are different
        # claims with different dates, and the page shows them side by side.
        detail["outcomes"] = [
            {
                "kind": row["kind"],
                "window_days": row["window_days"],
                "observed_at": row["observed_at"],
                "source": row["source"],
                "detail": row["detail"],
            }
            for row in conn.execute(
                select(outcomes)
                .where(outcomes.c.repo == v["repo"])
                .where(outcomes.c.pr_number == v["pr_number"])
                .order_by(outcomes.c.window_days)
            ).mappings()
        ]
        detail["outcome_jobs"] = [
            {
                "window_days": row["window_days"],
                "status": row["status"],
                "due_at": row["due_at"],
                "merged_at": row["merged_at"],
            }
            for row in conn.execute(
                select(outcome_jobs)
                .where(outcome_jobs.c.github_repo_id == v["github_repo_id"])
                .where(outcome_jobs.c.pr_number == v["pr_number"])
                .order_by(outcome_jobs.c.window_days)
            ).mappings()
        ]
    return detail
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && uv run pytest tests/test_store.py -k run_detail -v`
Expected: 5 PASS

- [ ] **Step 5: Run the full suite and lint**

Run: `cd api && uv run pytest && uv run ruff check .`
Expected: all pass, ruff clean

- [ ] **Step 6: Commit**

```bash
git add api/doug/store.py api/tests/test_store.py
git commit -m "store: run_detail — the forensic bundle for one run

_verdict_bundle omits model, prompt_hash, rationale and provenance because
a check run does not want them. The console's forensic page wants exactly
those, so this composes the bundle with the columns it drops rather than
widening what every check run carries."
```

---

### Task 5: `GET /v1/runs/{verdict_id}` — the forensic endpoint

**Files:**
- Modify: `api/doug/models.py`
- Modify: `api/doug/api.py`
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: `store.run_detail` (Task 4), `_operator_only`
- Produces: `GET /v1/runs/{verdict_id}` → `RunDetailResponse`. Console types mirror it in Task 7.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_api.py`:

```python
def test_run_detail_404s_an_unknown_verdict(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/runs/4242", headers=AUTH).status_code == 404


def test_run_detail_refuses_without_the_operator_token(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.get("/v1/runs/1").status_code == 401


def test_run_detail_reports_a_null_prompt_hash_as_unstamped(tmp_path, monkeypatch):
    """Historical App-path reader verdicts carry NULL because the worker
    never stamped it (the CI endpoint did, masking the bug). Serialising
    that as a match would assert the frozen prompt ran when nobody knows."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, reader_verdict=RV, model="claude-opus-5",
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    body = client_get_detail(vid, monkeypatch)
    assert body["prompt_hash"] is None


def test_run_detail_returns_findings_deviations_and_coverage(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, reader_verdict=RV, model="claude-opus-5",
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
        coverage=store.Coverage(
            diff_chars=108200, sent_chars=18400, files_sent=4,
            files_unseen=["api/doug/tenancy.py"], file_cut="api/doug/api.py",
        ),
    )
    body = client_get_detail(vid, monkeypatch)
    assert body["coverage"]["files_unseen"] == ["api/doug/tenancy.py"]
    assert body["coverage"]["file_cut"] == "api/doug/api.py"
    assert body["reasons"][0]["rule"] == "reader:race-condition"
    assert body["deviations"] == []
```

Add this helper next to the other helpers in `test_api.py`:

```python
def client_get_detail(verdict_id: int, monkeypatch) -> dict:
    res = TestClient(app).get(f"/v1/runs/{verdict_id}", headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && uv run pytest tests/test_api.py -k "test_run_detail_" -v`
Expected: 4 FAILs (404 from FastAPI — no such route)

- [ ] **Step 3: Add the wire models**

Append to `api/doug/models.py`:

```python
class RunOutcome(BaseModel):
    kind: str
    window_days: int | None
    observed_at: datetime
    source: str
    detail: str | None


class RunOutcomeJob(BaseModel):
    window_days: int
    status: str
    due_at: datetime
    merged_at: datetime


class RunDetailJob(BaseModel):
    status: str
    attempts: int
    claim_generation: int
    error: str | None
    enqueued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class RunDeviation(BaseModel):
    type: str
    description: str
    severity: str


class RunDetailResponse(BaseModel):
    verdict_id: int
    repo: str
    pr_number: int
    installation_id: int | None
    github_repo_id: int | None
    pr: PRMetadata
    scored_at: datetime
    tier: str
    # None means the row predates prompt-hash stamping on the worker path.
    # It is NOT a match against the frozen prompt and must never render as one.
    prompt_hash: str | None
    model: str | None
    source: str | None
    head_sha: str | None
    risk_score: int | None
    rationale: str | None
    score: float
    band: Band
    threshold: float
    coverage: RunCoverage | None
    reasons: list[Reason]
    deviations: list[RunDeviation]
    intent_alignment: int | None
    intent_refs: list[str]
    job: RunDetailJob | None
    outcomes: list[RunOutcome]
    outcome_jobs: list[RunOutcomeJob]
```

- [ ] **Step 4: Add the route**

Add to `api/doug/api.py` after the `/v1/runs` handler, extending the `.models` import with `RunDetailJob, RunDetailResponse, RunDeviation, RunOutcome, RunOutcomeJob`:

```python
@app.get("/v1/runs/{verdict_id}")
def run_detail(verdict_id: int, x_doug_token: str = Header("")) -> RunDetailResponse:
    """One run, end to end. Operator-only for the same reason /v1/runs is."""
    _operator_only(x_doug_token)
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    row = store.run_detail(verdict_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return RunDetailResponse(
        verdict_id=row["id"],
        repo=row["repo"],
        pr_number=row["pr_number"],
        installation_id=row["installation_id"],
        github_repo_id=row["github_repo_id"],
        pr=_with_url({"pr_meta": row["pr_meta"], "repo": row["repo"], "pr_number": row["pr_number"]}),
        scored_at=row["scored_at"],
        tier=row["tier"],
        prompt_hash=row["prompt_hash"],
        model=row["model"],
        source=row["source"],
        head_sha=row["head_sha"],
        risk_score=row["risk_score"],
        rationale=row["rationale"],
        score=row["score"],
        band=Band(row["band"]),
        threshold=row["threshold"],
        coverage=RunCoverage(**row["coverage"]) if row["coverage"] else None,
        reasons=[Reason(**r) for r in row["reasons"]],
        deviations=[RunDeviation(**d) for d in row["deviations"]],
        intent_alignment=row["intent_alignment"],
        intent_refs=row["intent_refs"],
        job=RunDetailJob(**row["job"]) if row["job"] else None,
        outcomes=[RunOutcome(**o) for o in row["outcomes"]],
        outcome_jobs=[RunOutcomeJob(**j) for j in row["outcome_jobs"]],
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd api && uv run pytest tests/test_api.py -k "test_run_detail_" -v`
Expected: 4 PASS

- [ ] **Step 6: Run the full suite and lint**

Run: `cd api && uv run pytest && uv run ruff check .`
Expected: all pass, ruff clean

- [ ] **Step 7: Commit**

```bash
git add api/doug/models.py api/doug/api.py api/tests/test_api.py
git commit -m "api: GET /v1/runs/{verdict_id} — one run, end to end

prompt_hash is serialised as-is including NULL. Historical App-path reader
verdicts carry NULL because the worker never stamped it; rendering that as
a match would assert the frozen prompt ran when nobody can know."
```

---

### Task 6: Console application scaffold and shell

**Files:**
- Create: `console/package.json`, `console/tsconfig.json`, `console/next.config.ts`, `console/postcss.config.mjs`, `console/eslint.config.mjs`, `console/Dockerfile`, `console/AGENTS.md`, `console/CLAUDE.md`, `console/.gitignore`
- Create: `console/app/globals.css`, `console/app/layout.tsx`, `console/app/error.tsx`
- Create: `console/components/shell.tsx`, `console/components/doug-logo.tsx`
- Modify: `Makefile` (add `console-dev`)

**Interfaces:**
- Produces: `<Shell tenant={…} repo={…} health={…}>{children}</Shell>` from `console/components/shell.tsx` — the top bar, scope switchers, health strip and nav tabs. Tasks 8 and 9 wrap their pages in it.

**Why a separate app:** serving a public marketing surface and a gated operator surface from one Next build means a single environment variable separates them. That is the exact failure mode this console exists to close.

- [ ] **Step 1: Scaffold the app**

```bash
cd /Users/andrew/Projects/doughq/repo
cp web/tsconfig.json web/next.config.ts web/postcss.config.mjs web/eslint.config.mjs console/ 2>/dev/null || mkdir -p console && cp web/tsconfig.json web/next.config.ts web/postcss.config.mjs web/eslint.config.mjs console/
cp web/Dockerfile web/AGENTS.md web/CLAUDE.md console/
mkdir -p console/app console/components console/lib
cd console && npm install next@16.2.12 react@19.2.4 react-dom@19.2.4 clsx tailwind-merge && npm install -D tailwindcss@^4 @tailwindcss/postcss@^4 typescript@^5 @types/node@^20 @types/react@^19 @types/react-dom@^19 eslint@^9 eslint-config-next@16.2.12
```

Set `console/package.json`'s `name` to `"console"` and its scripts to match `web/package.json`:

```json
"scripts": {
  "dev": "next dev --port 3001",
  "build": "next build",
  "start": "next start",
  "lint": "eslint",
  "test": "node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test --experimental-strip-types lib/*.test.mjs"
}
```

- [ ] **Step 2: Read the Next docs before writing any Next code**

Per `console/AGENTS.md` (copied from `web/`): this is not the Next.js you know. Read `console/node_modules/next/dist/docs/` for the App Router, server components, `searchParams`, and `error.tsx` conventions before Step 3. Heed deprecation notices.

- [ ] **Step 3: Write the theme**

Create `console/app/globals.css`. Copy the `:root` and `.dark` blocks verbatim from `web/app/globals.css:54-164` so the brand tokens stay identical, then append the console's own layer:

```css
@layer utilities {
  /* Denser than the marketing site: this is a working surface. */
  .panel { background: var(--card); border: 1px solid var(--border); }

  /* Tabular numerals are mandatory on every column of numbers — a score
     column that does not align is unreadable at 34px rows. */
  .mono { font-family: var(--font-geist-mono); font-variant-numeric: tabular-nums; }

  /* The two data colours. NEVER add a third, and never use --iridescent
     here: it fails CVD separation against --flag at ΔE 6.1 in NORMAL
     vision, so the two are indistinguishable side by side. --iridescent is
     chrome only (nav, focus, hover rules). */
  .data-flag  { color: var(--flag); }
  .data-clear { color: var(--clear); }

  /* Coverage is a magnitude, not a judgement — a neutral sequential ramp,
     never the flag/clear pair. Low coverage is alarmed by how empty the
     track looks, not by hue. */
  .cov-track { background: #eceae3; }
  .cov-fill  { background: #3d403c; }
}
```

`console/app/layout.tsx` is `web/app/layout.tsx` with the metadata changed to `title: "doug-console"` and `defaultTheme="light"` retained. Keep the same three `next/font/google` fonts.

- [ ] **Step 4: Write the shell**

Create `console/components/shell.tsx`. Match `workspace/mockups/console.html`'s top bar, scope switchers, health strip and tabs. Scope switchers are links that set `?tenant=` / `?repo=` on the current route — filter state lives in the URL so any view is bookmarkable.

```tsx
import Link from "next/link";

import { DougLogo } from "@/components/doug-logo";

export interface ShellScope {
  tenant: string | null;
  repo: string | null;
}

export function Shell({
  scope,
  active,
  children,
}: {
  scope: ShellScope;
  active: "runs";
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-20 flex h-[52px] items-center gap-[18px] border-b border-border bg-background/[.86] px-5 backdrop-blur-[10px]">
        <span className="font-heading flex items-center gap-2 text-base font-bold tracking-tight">
          <DougLogo size={19} /> doug
          <span className="mono rounded-[3px] bg-accent px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[.12em] text-accent-foreground">
            console
          </span>
        </span>
        <div className="flex items-center gap-1.5">
          <ScopeSwitch label="tenant" value={scope.tenant ?? "all"} />
          <ScopeSwitch label="repo" value={scope.repo ?? "all"} />
        </div>
      </header>
      <nav className="flex items-end gap-0.5 border-b border-border px-5">
        <Link
          href="/"
          aria-current={active === "runs" ? "page" : undefined}
          className="mono -mb-px border-b-2 border-transparent px-3 pt-2 pb-2 text-xs uppercase tracking-[.06em] text-muted-foreground aria-[current]:border-b-[var(--iridescent)] aria-[current]:font-semibold aria-[current]:text-foreground"
        >
          Runs
        </Link>
        <span className="mono -mb-px cursor-not-allowed px-3 pt-2 pb-2 text-xs uppercase tracking-[.06em] text-muted-foreground/50">
          Repos <span className="text-[9px]">phase 2</span>
        </span>
        <span className="mono -mb-px cursor-not-allowed px-3 pt-2 pb-2 text-xs uppercase tracking-[.06em] text-muted-foreground/50">
          Evidence <span className="text-[9px]">phase 3</span>
        </span>
      </nav>
      <main className="mx-auto max-w-[1440px] px-5">{children}</main>
    </div>
  );
}

function ScopeSwitch({ label, value }: { label: string; value: string }) {
  return (
    <span className="mono inline-flex items-center gap-[7px] rounded-[5px] border border-border bg-card px-[9px] py-[5px] text-xs">
      <span className="text-[10px] uppercase tracking-[.1em] text-muted-foreground">
        {label}
      </span>
      {value}
    </span>
  );
}
```

Copy `web/components/doug-logo.tsx` to `console/components/doug-logo.tsx` unchanged.

- [ ] **Step 5: Verify it builds and renders**

```bash
cd console && npm run build && npm run lint
```
Expected: build succeeds, lint clean.

- [ ] **Step 6: Add the Makefile target**

Add to the repo-root `Makefile`, and add `console-dev` to the `.PHONY` line:

```make
console-dev:
	cd console && npm run dev
```

- [ ] **Step 7: Commit**

```bash
git add console Makefile
git commit -m "console: scaffold a separate Next app for the operator surface

Not new routes in web/: serving a public marketing surface and a gated
operator surface from one build means a single env var separates them,
which is the failure mode the console exists to close. Brand tokens are
copied verbatim from web/app/globals.css so the two read as one product."
```

---

### Task 7: Console data layer — types, client, and the coverage math

**Files:**
- Create: `console/lib/api.ts`, `console/lib/runs.ts`, `console/lib/runs.test.mjs`

**Interfaces:**
- Consumes: `GET /v1/runs` (Task 3), `GET /v1/runs/{id}` (Task 5)
- Produces:
  - `getRuns(params): Promise<{ runs: RunSummary[] } | { error: string }>` and `getRunDetail(id): Promise<RunDetail | { error: string }>` from `lib/api.ts`
  - `coveragePercent(coverage, changedFiles): { kind: "known"; pct: number; low: boolean } | { kind: "no-read" } | { kind: "unknown-denominator" }` from `lib/runs.ts`
  - `relativeAge(iso, now): string` from `lib/runs.ts`

- [ ] **Step 1: Write the failing tests**

Create `console/lib/runs.test.mjs`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import { coveragePercent, relativeAge } from "./runs.ts";

const coverage = {
  diff_chars: 108200,
  sent_chars: 18400,
  files_sent: 4,
  files_unseen: ["api/doug/tenancy.py"],
  file_cut: "api/doug/api.py",
};

test("coveragePercent divides files_sent by changed_files, not by the fetched file list", () => {
  // The live defect this page exists to make visible: 4 of 23 files.
  // files_unseen holds 1 entry, so a naive files_sent/(sent+unseen) would
  // report 80% on a run that read 17% — and would be MOST wrong on the
  // large PRs where coverage matters most, because `files` is paginated
  // and can be short of the true count.
  const result = coveragePercent(coverage, 23);
  assert.equal(result.kind, "known");
  assert.equal(Math.round(result.pct), 17);
});

test("coveragePercent reports no-read rather than zero when there was no read", () => {
  // A deterministic run never opened the diff. Zero would claim Doug read
  // none of it, which is a different and false statement.
  assert.deepEqual(coveragePercent(null, 23), { kind: "no-read" });
});

test("coveragePercent refuses to invent a denominator", () => {
  // changed_files is null on rows predating its capture. 100% would be a
  // fabricated claim about how much Doug saw.
  assert.deepEqual(coveragePercent(coverage, null), { kind: "unknown-denominator" });
});

test("coveragePercent flags a run below the low-coverage line", () => {
  assert.equal(coveragePercent(coverage, 23).low, true);
  assert.equal(coveragePercent({ ...coverage, files_sent: 20 }, 23).low, false);
});

test("coveragePercent never exceeds 100 even if files_sent overruns", () => {
  const result = coveragePercent({ ...coverage, files_sent: 30 }, 23);
  assert.equal(result.kind, "known");
  assert.equal(result.pct, 100);
});

test("relativeAge renders hours, days and weeks distinctly", () => {
  const now = new Date("2026-08-06T12:00:00Z");
  assert.equal(relativeAge("2026-08-06T10:00:00Z", now), "2h");
  assert.equal(relativeAge("2026-08-04T12:00:00Z", now), "2d");
  assert.equal(relativeAge("2026-07-16T12:00:00Z", now), "3w");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd console && npm test`
Expected: FAIL — `Cannot find module './runs.ts'`

- [ ] **Step 3: Write `lib/runs.ts`**

```typescript
export interface RunCoverage {
  diff_chars: number;
  sent_chars: number;
  files_sent: number;
  files_unseen: string[];
  file_cut: string | null;
}

/** Below this, the run is marked. Not a hue — the ruler's emptiness is the
 *  alarm, and hue stays reserved for Doug's routing decision. */
export const LOW_COVERAGE = 0.5;

export type CoverageResult =
  | { kind: "known"; pct: number; low: boolean }
  | { kind: "no-read" }
  | { kind: "unknown-denominator" };

/** Read coverage as a percentage of the PR's true file count.
 *
 *  `changedFiles` is GitHub's own count, carried on pr_meta. It is the only
 *  correct denominator: `files` is the paginated list actually fetched and
 *  can be short of the true count, so deriving the denominator from it
 *  inflates coverage on exactly the large PRs where coverage matters most.
 *  When it is absent the honest answer is "unknown", never 100%.
 */
export function coveragePercent(
  coverage: RunCoverage | null,
  changedFiles: number | null,
): CoverageResult {
  if (coverage === null) return { kind: "no-read" };
  if (changedFiles === null || changedFiles <= 0) {
    return { kind: "unknown-denominator" };
  }
  const ratio = Math.min(1, coverage.files_sent / changedFiles);
  return { kind: "known", pct: ratio * 100, low: ratio < LOW_COVERAGE };
}

export function relativeAge(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h`;
  if (seconds < 604_800) return `${Math.round(seconds / 86_400)}d`;
  return `${Math.round(seconds / 604_800)}w`;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd console && npm test`
Expected: 6 PASS

- [ ] **Step 5: Write `lib/api.ts`**

```typescript
import type { RunCoverage } from "./runs";

export type Band = "cleared" | "flagged";

export interface RunFindingCounts {
  total: number;
  high: number;
  medium: number;
  low: number;
}

export interface RunJob {
  status: string;
  attempts: number;
  error: string | null;
  enqueued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunSummary {
  verdict_id: number;
  repo: string;
  installation_id: number | null;
  pr_number: number;
  title: string;
  url: string | null;
  scored_at: string;
  tier: string;
  source: string | null;
  score: number;
  band: Band;
  threshold: number;
  coverage: RunCoverage | null;
  changed_files: number | null;
  finding_counts: RunFindingCounts;
  job: RunJob | null;
  outcome_14: string | null;
}

export const API_URL = process.env.DOUG_API_URL ?? "http://localhost:8000";

/** There is deliberately NO fixture fallback here.
 *
 *  doug-web falls back to a bundled fixture because a marketing page must
 *  survive an API outage. On an operator console that behaviour is strictly
 *  worse than an error: the page exists to answer "what did Doug do", and a
 *  plausible wrong answer defeats the entire purpose. Callers render the
 *  error string. */
async function get<T>(path: string): Promise<T | { error: string }> {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
      headers: { "X-Doug-Token": process.env.DOUG_API_TOKEN ?? "" },
    });
    if (!res.ok) return { error: `${path} → HTTP ${res.status}` };
    return (await res.json()) as T;
  } catch (e) {
    return { error: `${path} → ${e instanceof Error ? e.message : "unreachable"}` };
  }
}

export function isError<T>(v: T | { error: string }): v is { error: string } {
  return typeof v === "object" && v !== null && "error" in v;
}

export async function getRuns(params: {
  repo?: string;
  installationId?: number;
  limit?: number;
}): Promise<{ items: RunSummary[] } | { error: string }> {
  const q = new URLSearchParams();
  if (params.repo) q.set("repo", params.repo);
  if (params.installationId) q.set("installation_id", String(params.installationId));
  q.set("limit", String(params.limit ?? 100));
  return get<{ items: RunSummary[] }>(`/v1/runs?${q}`);
}
```

- [ ] **Step 6: Add the no-fabrication test**

Append to `console/lib/runs.test.mjs`:

```javascript
import { isError } from "./api.ts";

test("isError treats an API failure as an error, never as empty data", () => {
  // The console must never render a number when the API is unreachable.
  // An empty items array and a failed fetch are different facts and the
  // page states them differently.
  assert.equal(isError({ error: "/v1/runs → HTTP 503" }), true);
  assert.equal(isError({ items: [] }), false);
});
```

- [ ] **Step 7: Run the tests and lint**

Run: `cd console && npm test && npm run lint`
Expected: 7 PASS, lint clean

- [ ] **Step 8: Commit**

```bash
git add console/lib
git commit -m "console: typed client and coverage math, with no fixture fallback

coveragePercent divides by pr_meta.changed_files. Deriving the denominator
from files_sent + files_unseen would report 80% on the run that actually
read 17%, and would be most wrong on the large PRs where coverage matters
most. A missing denominator is reported as unknown, never as 100%."
```

---

### Task 8: Runs list page

**Files:**
- Create: `console/app/page.tsx`, `console/components/coverage-bar.tsx`, `console/components/band-chip.tsx`

**Interfaces:**
- Consumes: `Shell` (Task 6), `getRuns` / `isError` / `RunSummary` (Task 7), `coveragePercent` / `relativeAge` (Task 7)
- Produces: `<CoverageBar coverage changedFiles />` and `<BandChip band />` — both reused by Task 9.

**Layout reference:** `workspace/mockups/console.html`, the `table.runs` section. 34px rows, hairline row rules, mono tabular numerals, score right-aligned in the first column.

- [ ] **Step 1: Write `components/band-chip.tsx`**

```tsx
import type { Band } from "@/lib/api";

/** The colour is ALWAYS accompanied by its word.
 *
 *  --flag and --clear sit in the 6-8 CVD floor band, where secondary
 *  encoding is not optional — the word IS that encoding. Never render this
 *  as a bare dot or a colour swatch. */
export function BandChip({ band }: { band: Band | null }) {
  if (band === null) {
    return <span className="mono text-xs text-muted-foreground">—</span>;
  }
  const flagged = band === "flagged";
  return (
    <span
      className={
        "mono inline-flex items-center rounded-[3px] px-[7px] py-0.5 text-[10.5px] uppercase tracking-[.06em] " +
        (flagged
          ? "bg-[color-mix(in_srgb,var(--flag)_9%,transparent)] text-[var(--flag)]"
          : "bg-[color-mix(in_srgb,var(--clear)_9%,transparent)] text-[var(--clear)]")
      }
    >
      {flagged ? "needs you" : "cleared"}
    </span>
  );
}
```

- [ ] **Step 2: Write `components/coverage-bar.tsx`**

```tsx
import { coveragePercent, type RunCoverage } from "@/lib/runs";

/** Coverage gets no hue. A low read is alarmed by how empty the track
 *  looks plus a dotted underline — magnitude problems are shown with
 *  magnitude, which keeps hue reserved for Doug's routing decision. */
export function CoverageBar({
  coverage,
  changedFiles,
}: {
  coverage: RunCoverage | null;
  changedFiles: number | null;
}) {
  const result = coveragePercent(coverage, changedFiles);

  if (result.kind === "no-read") {
    return <span className="mono text-xs text-muted-foreground">no read</span>;
  }
  if (result.kind === "unknown-denominator") {
    return (
      <span className="mono text-xs text-muted-foreground" title="pr_meta.changed_files is absent on this row">
        denominator unknown
      </span>
    );
  }
  return (
    <span className="flex items-center gap-2">
      <span className="cov-track h-[7px] w-[62px] flex-none overflow-hidden rounded-[2px]">
        <span className="cov-fill block h-full" style={{ width: `${result.pct}%` }} />
      </span>
      <span
        className={
          "mono min-w-[34px] text-xs " +
          (result.low ? "font-semibold underline decoration-dotted underline-offset-[3px]" : "")
        }
      >
        {Math.round(result.pct)}%
      </span>
      {result.low && <span className="text-[11px]" aria-label="low coverage">⚠</span>}
    </span>
  );
}
```

- [ ] **Step 3: Write `app/page.tsx`**

```tsx
import Link from "next/link";

import { BandChip } from "@/components/band-chip";
import { CoverageBar } from "@/components/coverage-bar";
import { Shell } from "@/components/shell";
import { getRuns, isError } from "@/lib/api";
import { relativeAge } from "@/lib/runs";

export const dynamic = "force-dynamic";

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<{ repo?: string; tenant?: string }>;
}) {
  const params = await searchParams;
  const scope = { tenant: params.tenant ?? null, repo: params.repo ?? null };
  const result = await getRuns({
    repo: params.repo,
    installationId: params.tenant ? Number(params.tenant) : undefined,
  });

  return (
    <Shell scope={scope} active="runs">
      {isError(result) ? (
        // Never a number, never an empty table. An unreachable API and a
        // ledger with no runs are different facts.
        <div className="mono mt-10 rounded-[6px] border border-[var(--flag)]/40 bg-[color-mix(in_srgb,var(--flag)_6%,transparent)] p-4 text-xs">
          <p className="font-semibold text-[var(--flag)]">The API did not answer.</p>
          <p className="mt-1 text-muted-foreground">{result.error}</p>
          <p className="mt-2 text-muted-foreground">
            Nothing is rendered below because nothing is known. This console has no
            fixture fallback by design.
          </p>
        </div>
      ) : (
        <>
          <p className="mono flex items-center gap-3 py-5 text-[10.5px] uppercase tracking-[.16em] text-muted-foreground">
            Runs — verdict history across every installation
            <span className="h-px flex-1 bg-border" />
            <b className="text-foreground">{result.items.length}</b> runs
          </p>
          <table className="w-full table-fixed border-collapse">
            <thead>
              <tr>
                {[
                  ["score", "w-[66px] text-right"],
                  ["pull request", ""],
                  ["band", "w-[96px]"],
                  ["tier", "w-[88px]"],
                  ["read", "w-[150px]"],
                  ["outcome", "w-[104px]"],
                  ["job", "w-[118px]"],
                  ["age", "w-[46px] text-right"],
                ].map(([label, cls]) => (
                  <th
                    key={label}
                    className={`mono border-b border-border pb-[7px] text-left text-[10px] font-medium uppercase tracking-[.13em] text-muted-foreground ${cls}`}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.items.map((run) => {
                const failed = run.job?.status === "failed";
                return (
                  <tr key={run.verdict_id} className="border-b border-border/50 hover:bg-muted/40">
                    <td className="h-[34px] px-2.5 text-right">
                      {failed ? (
                        // A failed job produced no verdict, so "failed" and a
                        // band are mutually exclusive states of this cell —
                        // which is what lets one red serve both meanings.
                        <span className="mono whitespace-nowrap text-[11px] text-[var(--flag)]">⚠ failed</span>
                      ) : (
                        <span
                          className={
                            "mono text-[14.5px] font-semibold " +
                            (run.band === "flagged" ? "data-flag" : "data-clear")
                          }
                        >
                          {run.score.toFixed(2)}
                        </span>
                      )}
                    </td>
                    <td className="h-[34px] min-w-0 px-2.5">
                      <Link href={`/runs/${run.verdict_id}`} className="flex items-baseline gap-2">
                        <span className="mono flex-none text-[11px] text-muted-foreground">
                          {run.repo} <b className="font-medium text-foreground">#{run.pr_number}</b>
                        </span>
                        <span className="min-w-0 flex-1 truncate text-[12.5px]">{run.title}</span>
                      </Link>
                    </td>
                    <td className="h-[34px] px-2.5">
                      <BandChip band={failed ? null : run.band} />
                    </td>
                    <td className="mono h-[34px] px-2.5 text-[11px] text-muted-foreground">
                      {failed ? "—" : run.tier}
                    </td>
                    <td className="h-[34px] px-2.5">
                      <CoverageBar coverage={run.coverage} changedFiles={run.changed_files} />
                    </td>
                    <td className="mono h-[34px] px-2.5 text-xs">
                      {run.outcome_14 === null ? (
                        <span className="text-muted-foreground">◷ pending</span>
                      ) : run.outcome_14 === "clean" ? (
                        <span className="data-clear">✓ clean</span>
                      ) : (
                        <span className="data-flag font-semibold">↩ {run.outcome_14}</span>
                      )}
                    </td>
                    <td className="mono h-[34px] px-2.5 text-[11px] text-muted-foreground">
                      {run.job
                        ? failed
                          ? `${run.job.attempts}/3 · failed`
                          : run.job.status
                        : "—"}
                    </td>
                    <td className="mono h-[34px] px-2.5 text-right text-[11px] text-muted-foreground">
                      {relativeAge(run.scored_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </Shell>
  );
}
```

- [ ] **Step 4: Verify against a live API**

```bash
cd api && DOUG_API_TOKEN=t0ken uv run uvicorn doug.api:app --port 8000 &
cd console && DOUG_API_URL=http://localhost:8000 DOUG_API_TOKEN=t0ken npm run dev
```
Open `http://localhost:3001`. Expected: the table renders, or — with the API stopped — the explicit "The API did not answer" panel with no table beneath it.

- [ ] **Step 5: Build and lint**

Run: `cd console && npm run build && npm run lint && npm test`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add console/app/page.tsx console/components/band-chip.tsx console/components/coverage-bar.tsx
git commit -m "console: Runs list

A failed job produced no verdict, so 'failed' and a band are mutually
exclusive states of the score cell — that is what lets one red carry both
meanings without ambiguity. An unreachable API renders an explicit panel
and no table: empty and unknown are different facts."
```

---

### Task 9: Run forensics page

**Files:**
- Create: `console/app/runs/[verdictId]/page.tsx`, `console/components/coverage-ruler.tsx`, `console/components/run-spine.tsx`
- Modify: `console/lib/api.ts` (add `getRunDetail` and the `RunDetail` types)

**Interfaces:**
- Consumes: `GET /v1/runs/{verdict_id}` (Task 5), `Shell`, `BandChip`, `coveragePercent`
- Produces: the page. Nothing consumes it.

**Layout reference:** `workspace/mockups/console.html`, the `.forensic` section — a 232px timeline spine on the left, wide evidence column on the right, eight blocks in the order the spec fixes.

- [ ] **Step 1: Extend `lib/api.ts`**

```typescript
export interface RunDetail {
  verdict_id: number;
  repo: string;
  pr_number: number;
  installation_id: number | null;
  pr: {
    number: number;
    title: string;
    url: string | null;
    changed_files: number | null;
    files: string[];
    files_dropped: string[];
  };
  scored_at: string;
  tier: string;
  prompt_hash: string | null;
  model: string | null;
  source: string | null;
  head_sha: string | null;
  risk_score: number | null;
  rationale: string | null;
  score: number;
  band: Band;
  threshold: number;
  coverage: RunCoverage | null;
  reasons: { rule: string; label: string; weight: number; severity: string | null }[];
  deviations: { type: string; description: string; severity: string }[];
  job: {
    status: string;
    attempts: number;
    claim_generation: number;
    error: string | null;
    enqueued_at: string | null;
    started_at: string | null;
    finished_at: string | null;
  } | null;
  outcomes: { kind: string; window_days: number | null; observed_at: string; detail: string | null }[];
  outcome_jobs: { window_days: number; status: string; due_at: string; merged_at: string }[];
}

export async function getRunDetail(id: number): Promise<RunDetail | { error: string }> {
  return get<RunDetail>(`/v1/runs/${id}`);
}
```

- [ ] **Step 2: Write `components/coverage-ruler.tsx`**

```tsx
import { coveragePercent, type RunCoverage } from "@/lib/runs";

/** The console's signature element: every file the reader was given, in
 *  budget-consumption order, sized by share of the diff. Read is solid;
 *  never-read is hatched. The emptiness of the right-hand side IS the
 *  alarm — no hue is spent here.
 *
 *  Segments use flex-grow with a zero basis so the 2px gaps are subtracted
 *  from the track rather than added to it; percentage bases plus gaps
 *  overflow by exactly the sum of the gaps. The cut marker is an in-flow
 *  flex item, so it lands between the last read file and the first unread
 *  one by construction rather than by a hand-computed offset. */
export function CoverageRuler({
  coverage,
  changedFiles,
}: {
  coverage: RunCoverage;
  changedFiles: number | null;
}) {
  const result = coveragePercent(coverage, changedFiles);
  const seenShare = coverage.sent_chars;
  const unseenShare = Math.max(0, coverage.diff_chars - coverage.sent_chars);
  const perUnseen = coverage.files_unseen.length
    ? unseenShare / coverage.files_unseen.length
    : 0;

  return (
    <div className="panel rounded-[6px] p-4">
      <div className="mono mb-3 flex items-baseline gap-2.5 text-xs text-muted-foreground">
        <span className="text-[19px] font-semibold text-foreground">
          {result.kind === "known" ? `${Math.round(result.pct)}%` : "—"}
        </span>
        <span>
          of the diff · {coverage.files_sent} of {changedFiles ?? "?"} files ·{" "}
          {coverage.sent_chars.toLocaleString()} of {coverage.diff_chars.toLocaleString()} chars
        </span>
        {coverage.file_cut && (
          <span className="ml-auto">
            cut at <code>{coverage.file_cut}</code>
          </span>
        )}
      </div>

      <div className="mb-6 flex h-[26px] items-stretch gap-0.5">
        <div className="cov-fill min-w-0.5 rounded-[2px]" style={{ flex: `${seenShare} 1 0` }} />
        <div className="relative -my-[7px] mx-[3px] w-px flex-none bg-foreground">
          <span className="mono absolute left-[-2px] top-[calc(100%+4px)] whitespace-nowrap text-[9px] uppercase tracking-[.08em]">
            budget cut ↑
          </span>
        </div>
        {coverage.files_unseen.map((path) => (
          <div
            key={path}
            title={`${path} — never read`}
            className="min-w-0.5 rounded-[2px] border border-dashed border-[#c9c6bd] bg-[repeating-linear-gradient(135deg,#c9c6bd_0_1.5px,transparent_1.5px_5px)]"
            style={{ flex: `${perUnseen} 1 0` }}
          />
        ))}
      </div>

      <div className="mono border-t border-border pt-3 text-[10px] uppercase tracking-[.12em] text-muted-foreground">
        Unseen — {coverage.files_unseen.length} files
      </div>
      <ul>
        {coverage.files_unseen.map((path) => (
          <li key={path} className="mono flex items-center gap-2.5 py-[3px] text-xs">
            <span className="text-muted-foreground">{path}</span>
            <span className="ml-auto text-[10.5px] text-muted-foreground/60">cut by file order</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: Do NOT add a sensitive-path predicate**

There is no `isSensitivePath` in this plan, and the ruler takes no `sensitive` prop. This is deliberate and it overrides the `workspace/mockups/console.html` mockup, which still renders `SENSITIVE` tags from before the measurement below.

The obvious design is to mark `files_unseen` entries that `features._is_sensitive` classifies as sensitive. The approved read-budget-routing spec (`docs/superpowers/specs/2026-08-06-read-budget-routing-design.md:39-44`) measured that predicate against the exact PRs that motivated this work:

```
api/doug/tenancy.py      sensitive=False  test=False  migration=False
api/doug/keyformat.py    sensitive=False  test=False  migration=False
api/doug/migrations.py   sensitive=False  test=False  migration=False
```

`_SENSITIVE_NAME_RE` matches `secret|auth|authn|authz|rbac|oauth|credential|token`, and none of those filenames contain one. The predicate fires on **zero** of the motivating files. Marking the ruler with it would decorate the page with a signal that is inert exactly when it matters, and would make `tenancy.py` — the whole reason this page exists — render as an ordinary unread file while some unrelated `auth`-named file lit up.

Unseen files are therefore listed plainly, sized by their share of the diff. When `read_order()` lands on the `read-budget-routing` branch and `/v1/runs/{id}` can report the tier it assigned each file (code / tests / prose), the ruler marks by that instead — a classification the routing actually consumes. That is a Phase 2 follow-up, not a Phase 1 gap.

- [ ] **Step 4: Write `components/run-spine.tsx`**

```tsx
import type { RunDetail } from "@/lib/api";

function Event({
  title,
  stamp,
  sub,
  state,
}: {
  title: string;
  stamp: string;
  sub: string;
  state: "done" | "now" | "wait";
}) {
  const node =
    state === "now"
      ? "bg-[var(--clear)] border-[var(--clear)]"
      : state === "done"
        ? "bg-[#3d403c] border-[#3d403c]"
        : "bg-background border-[#c9c6bd]";
  return (
    <li className="relative pb-5 pl-5 last:pb-0 [&:not(:last-child)]:before:absolute [&:not(:last-child)]:before:left-[3.5px] [&:not(:last-child)]:before:top-[11px] [&:not(:last-child)]:before:bottom-[-3px] [&:not(:last-child)]:before:w-px [&:not(:last-child)]:before:bg-border">
      <span className={`absolute left-0 top-[5px] size-2 rounded-full border-[1.5px] ${node}`} />
      <div className="mono flex items-baseline gap-[7px] text-xs font-medium">
        {title}
        <span className="ml-auto text-[10.5px] font-normal text-muted-foreground">{stamp}</span>
      </div>
      <div className="mono mt-0.5 text-[10.5px] text-muted-foreground">{sub}</div>
    </li>
  );
}

/** The literal answer to "what did Doug do": webhook through outcome clock,
 *  with the real timestamps and durations from review_jobs. */
export function RunSpine({ run }: { run: RunDetail }) {
  const t = (iso: string | null) => (iso ? iso.slice(11, 19) : "—");
  const seconds =
    run.job?.started_at && run.job?.finished_at
      ? Math.round(
          (new Date(run.job.finished_at).getTime() - new Date(run.job.started_at).getTime()) / 1000,
        )
      : null;
  return (
    <aside className="border-r border-border pr-6 pt-5">
      <h2 className="mono mb-4 text-[10px] font-medium uppercase tracking-[.16em] text-muted-foreground">
        The run
      </h2>
      <ol>
        <Event title="job enqueued" stamp={t(run.job?.enqueued_at ?? null)} sub={`attempt ${run.job?.attempts ?? "?"} · gen ${run.job?.claim_generation ?? "?"}`} state="done" />
        <Event title="claimed" stamp={t(run.job?.started_at ?? null)} sub={run.job?.status ?? "no job row"} state="done" />
        <Event
          title="read"
          stamp={seconds === null ? "—" : `${seconds}s`}
          sub={run.coverage ? `${run.coverage.files_sent} of ${run.pr.changed_files ?? "?"} files sent` : "no read — deterministic tier"}
          state="done"
        />
        <Event title={`verdict ${run.verdict_id}`} stamp={t(run.scored_at)} sub={`${run.tier} · ${run.score.toFixed(2)} ${run.band}`} state="done" />
        {run.outcomes.map((o) => (
          <Event key={o.window_days} title={`${o.window_days}d outcome`} stamp={o.observed_at.slice(5, 10)} sub={`graded ${o.kind}`} state="now" />
        ))}
        {run.outcome_jobs
          .filter((j) => !run.outcomes.some((o) => o.window_days === j.window_days))
          .map((j) => (
            <Event key={j.window_days} title={`${j.window_days}d outcome`} stamp={j.due_at.slice(5, 10)} sub={j.status} state="wait" />
          ))}
      </ol>
    </aside>
  );
}
```

- [ ] **Step 5: Write `app/runs/[verdictId]/page.tsx`**

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";

import { BandChip } from "@/components/band-chip";
import { CoverageRuler } from "@/components/coverage-ruler";
import { RunSpine } from "@/components/run-spine";
import { Shell } from "@/components/shell";
import { getRunDetail, isError } from "@/lib/api";

export const dynamic = "force-dynamic";

function Block({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mono mb-3 flex items-center gap-2.5 text-[10px] font-medium uppercase tracking-[.16em] text-muted-foreground">
        {title}
        {note && <span className="text-[10.5px] normal-case tracking-normal text-foreground">{note}</span>}
        <span className="h-px flex-1 bg-border/60" />
      </h2>
      {children}
    </section>
  );
}

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ verdictId: string }>;
}) {
  const { verdictId } = await params;
  const id = Number(verdictId);
  if (!Number.isInteger(id) || id < 1) notFound();

  const run = await getRunDetail(id);
  const scope = { tenant: null, repo: null };

  if (isError(run)) {
    return (
      <Shell scope={scope} active="runs">
        <div className="mono mt-10 rounded-[6px] border border-[var(--flag)]/40 bg-[color-mix(in_srgb,var(--flag)_6%,transparent)] p-4 text-xs">
          <p className="font-semibold text-[var(--flag)]">The API did not answer.</p>
          <p className="mt-1 text-muted-foreground">{run.error}</p>
          <p className="mt-2 text-muted-foreground">
            Nothing is rendered below because nothing is known.
          </p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell scope={scope} active="runs">
      <header className="flex items-start gap-5 border-b border-border py-5">
        <div className="min-w-0 flex-1">
          <div className="mono flex items-center gap-[7px] text-xs text-muted-foreground">
            <Link href="/" className="text-foreground hover:text-[var(--iridescent)]">← runs</Link>
            <span>·</span>
            <span>{run.repo}</span>
            <span>·</span>
            {run.pr.url && (
              <a href={run.pr.url} target="_blank" rel="noreferrer" className="text-foreground hover:text-[var(--iridescent)]">
                #{run.pr_number} ↗
              </a>
            )}
            {run.source && (
              <span className="rounded-[3px] border border-border px-1.5 text-[9.5px] uppercase tracking-[.12em]">
                {run.source}
              </span>
            )}
          </div>
          <h1 className="font-heading mt-1.5 text-[21px] font-semibold leading-tight tracking-tight">
            {run.pr.title}
          </h1>
        </div>
        <div className="flex-none text-right">
          <div className={"mono text-[34px] font-semibold leading-none " + (run.band === "flagged" ? "data-flag" : "data-clear")}>
            {run.score.toFixed(2)}
          </div>
          <div className="mono mt-1.5 text-[10.5px] text-muted-foreground">
            <BandChip band={run.band} /> · threshold {run.threshold.toFixed(2)}
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-0 pb-16 lg:grid-cols-[232px_1fr]">
        <RunSpine run={run} />

        <div className="flex flex-col gap-6 pt-5 lg:pl-6">
          <Block title="What the reader was given">
            {run.coverage ? (
              <CoverageRuler coverage={run.coverage} changedFiles={run.pr.changed_files} />
            ) : (
              <p className="mono rounded-[5px] bg-muted px-3 py-2.5 text-xs text-muted-foreground">
                No read. This run was scored by the deterministic tier, so the diff was
                never opened — not a 0% read of a diff Doug saw.
              </p>
            )}
          </Block>

          <Block title="The read">
            <dl className="grid grid-cols-[132px_1fr] items-baseline gap-x-4 gap-y-[7px]">
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">tier</dt>
              <dd className="mono text-xs">{run.tier}</dd>
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">model</dt>
              <dd className="mono text-xs">{run.model ?? "—"}</dd>
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">prompt hash</dt>
              {/* NULL is "unstamped", never a match. Historical App-path reader
                  verdicts carry NULL because the worker never stamped it — the
                  CI endpoint did, which masked the gap. Rendering that as a
                  match asserts the frozen prompt ran when nobody can know. */}
              {run.prompt_hash === null ? (
                <dd className="mono text-xs">
                  <span className="underline decoration-dotted underline-offset-[3px]">unstamped</span>{" "}
                  <span className="text-muted-foreground">— predates prompt-hash stamping on the worker path</span>
                </dd>
              ) : (
                <dd className="mono text-xs">
                  {run.prompt_hash} <span className="data-clear">✓</span>{" "}
                  <span className="text-muted-foreground">matches the ADR-0002 frozen prompt</span>
                </dd>
              )}
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">risk score</dt>
              <dd className="mono text-xs">{run.risk_score ?? "—"} <span className="text-muted-foreground">/ 100</span></dd>
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">scored at</dt>
              <dd className="mono text-xs">{run.scored_at}</dd>
              <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">head sha</dt>
              <dd className="mono text-xs">{run.head_sha?.slice(0, 7) ?? "—"}</dd>
              {run.rationale && (
                <>
                  <dt className="mono text-[10.5px] uppercase tracking-[.06em] text-muted-foreground">rationale</dt>
                  <dd className="border-l-2 border-border pl-3 text-[12.5px] leading-relaxed text-muted-foreground">
                    {run.rationale}
                  </dd>
                </>
              )}
            </dl>
          </Block>

          <Block title="Findings" note={`${run.reasons.length} · ${run.tier} tier`}>
            {run.reasons.length === 0 ? (
              <p className="mono rounded-[5px] bg-muted px-3 py-2.5 text-xs text-muted-foreground">
                No findings.
              </p>
            ) : (
              run.reasons.map((r, i) => (
                <div key={`${r.rule}-${i}`} className="grid grid-cols-[62px_1fr] items-baseline gap-3 border-b border-border/50 py-2.5 last:border-0">
                  {/* Reader findings carry a severity and weight 0; deterministic
                      rules carry a weight and no severity. Showing "+0.00" beside
                      every reader finding prints a number that is constant by
                      construction. */}
                  <span className="mono rounded-[3px] bg-muted px-1.5 text-center text-[9.5px] uppercase tracking-[.1em] text-muted-foreground">
                    {r.severity ?? (r.weight ? `+${r.weight.toFixed(2)}` : "·")}
                  </span>
                  <div>
                    <div className="mono text-xs">{r.rule}</div>
                    <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{r.label}</div>
                  </div>
                </div>
              ))
            )}
          </Block>

          <Block title="Deviations" note="ADR-0007 · separate stream">
            {/* An empty list is a STORED result, not a missing one. The
                kind="none" marker row records "the read ran and found
                nothing", and _verdict_bundle filters it out server-side. */}
            {run.deviations.length === 0 ? (
              <p className="mono rounded-[5px] bg-muted px-3 py-2.5 text-xs text-muted-foreground">
                No deviations recorded. The read completed and found none — this is a
                stored result, not a missing one.
              </p>
            ) : (
              run.deviations.map((d, i) => (
                <div key={i} className="border-b border-border/50 py-2.5 last:border-0">
                  <div className="mono text-xs">{d.type}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{d.description}</div>
                </div>
              ))
            )}
          </Block>

          <Block title="Outcome">
            <div className="flex gap-2.5">
              {run.outcomes.map((o) => (
                <div key={o.window_days} className="panel flex-1 rounded-[6px] px-3.5 py-3">
                  <div className="mono text-[10px] uppercase tracking-[.12em] text-muted-foreground">
                    {o.window_days}-day window
                  </div>
                  <div className={"mono mt-1.5 text-[17px] font-semibold " + (o.kind === "clean" ? "data-clear" : "data-flag")}>
                    {o.kind === "clean" ? "✓ clean" : `↩ ${o.kind}`}
                  </div>
                  <div className="mono mt-1 text-[10.5px] text-muted-foreground">
                    graded {o.observed_at.slice(0, 10)}
                  </div>
                </div>
              ))}
              {run.outcome_jobs
                .filter((j) => !run.outcomes.some((o) => o.window_days === j.window_days))
                .map((j) => (
                  <div key={j.window_days} className="panel flex-1 rounded-[6px] px-3.5 py-3">
                    <div className="mono text-[10px] uppercase tracking-[.12em] text-muted-foreground">
                      {j.window_days}-day window
                    </div>
                    {/* Ungraded is not clean. */}
                    <div className="mono mt-1.5 text-sm font-medium text-muted-foreground">◷ {j.status}</div>
                    <div className="mono mt-1 text-[10.5px] text-muted-foreground">
                      grades {j.due_at.slice(0, 10)}
                    </div>
                  </div>
                ))}
              {run.outcomes.length === 0 && run.outcome_jobs.length === 0 && (
                <p className="mono rounded-[5px] bg-muted px-3 py-2.5 text-xs text-muted-foreground">
                  No outcome clock. This PR has not merged, so no window has started.
                </p>
              )}
            </div>
          </Block>
        </div>
      </div>
    </Shell>
  );
}
```

The eighth block from the spec — **Disposition**, joined from `findings-log.jsonl` — is deliberately absent. It needs `/v1/evidence/findings-log`, which is Phase 3. See "Not in Phase 1".

- [ ] **Step 6: Verify against a live API**

Run the API and console as in Task 8 Step 4, then open a real verdict id at `http://localhost:3001/runs/<id>`.
Expected: the spine, ruler, findings and outcome blocks render; a deterministic-tier run shows "no read — deterministic tier" and no ruler.

- [ ] **Step 7: Build, lint, test**

Run: `cd console && npm run build && npm run lint && npm test`
Expected: all pass (7 console tests — Task 7's six plus the `isError` test; there is no sensitive-path test, see Step 3)

- [ ] **Step 8: Commit**

```bash
git add console/app/runs console/components/coverage-ruler.tsx console/components/run-spine.tsx console/lib
git commit -m "console: run forensics

The ruler's segments use flex-grow with a zero basis so the 2px gaps are
subtracted from the track rather than added to it, and the cut marker is an
in-flow item so it lands between the last read file and the first unread
one by construction. Unseen files carry no sensitive marking: the
read-budget spec measured _is_sensitive firing on zero of the files that
motivated this page, so marking on it would decorate the page with a
signal that is inert exactly when it matters."
```

---

### Task 10: Deploy `doug-console` as its own gated service

**Files:**
- Modify: `api/deploy/gcp.sh` (`setup()` at line 27, new `console()` after `web()` at line 256)
- Test: `api/tests/test_deploy_gcp.py`

**Interfaces:**
- Consumes: nothing from earlier tasks at runtime; deploys `console/` from Task 6.
- Produces: `./deploy/gcp.sh console` — a Cloud Run service `doug-console`, `--no-allow-unauthenticated`, running as `doug-console-sa`.

**Why tests on a shell script:** `test_deploy_gcp.py` already pins that `web()` passes `--service-account`, because a comment claiming an identity is not a capability. The same reasoning applies with more force here: a console deployed `--allow-unauthenticated` by accident publishes both tenants' PR titles, job errors and coverage gaps to the internet. That must fail a test, not a code review.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_deploy_gcp.py`:

```python
def test_console_is_never_deployed_unauthenticated():
    """The console spans every installation. Deploying it open publishes
    both tenants' PR titles, job errors and coverage gaps. A comment is not
    a control — this is the control."""
    body = _function_body("console")
    assert "--no-allow-unauthenticated" in body
    assert "--allow-unauthenticated" not in body.replace("--no-allow-unauthenticated", "")


def test_console_runs_as_its_own_service_account():
    body = _function_body("console")
    assert "--service-account" in body
    assert "doug-console-sa@$PROJECT.iam.gserviceaccount.com" in body
    assert "compute@developer.gserviceaccount.com" not in body


def test_setup_creates_doug_console_sa_and_binds_only_the_api_token():
    """The console talks to doug-api over HTTP. It needs no Cloud SQL
    client, no App key, no Anthropic key."""
    setup = _function_body("setup")
    assert "service-accounts create doug-console-sa" in setup
    after = setup.split("service-accounts create doug-console-sa", 1)[1]
    assert "doug-api-token" in after
    assert "doug-database-url" not in after
    assert "doug-github-app-key" not in after
    assert "doug-anthropic-key" not in after
    assert "roles/cloudsql.client" not in after


def test_web_deploy_is_still_the_only_public_service():
    """Guard against the console being folded back into web()."""
    assert "--allow-unauthenticated" in _function_body("web")
    assert "--source ../console" not in _function_body("web")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && uv run pytest tests/test_deploy_gcp.py -v`
Expected: 3 FAILs (the `console` function body is empty), 1 PASS

- [ ] **Step 3: Add `CONSOLE_SERVICE` and the SA to `setup()`**

Add near the other service names at the top of `api/deploy/gcp.sh` (after `WEB_SERVICE=doug-web`):

```bash
CONSOLE_SERVICE=doug-console
```

Add to `setup()`, immediately after the `doug-web-sa` block ends (after line 153):

```bash
  # doug-console is the operator surface. It crosses every installation, so
  # it is IAM-gated rather than token-gated, and it gets its own identity
  # for the same reason doug-web did: a service must not inherit the
  # default compute SA's roles/editor.
  gcloud iam service-accounts create doug-console-sa \
    --display-name "doug-console runtime" --project "$PROJECT" 2>/dev/null \
    || echo "doug-console-sa exists; leaving it"
  CONSOLE_SA="doug-console-sa@$PROJECT.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$CONSOLE_SA" --project "$PROJECT" >/dev/null 2>&1; then
    echo "ERROR: service account $CONSOLE_SA is not visible after create." >&2
    exit 1
  fi
  if gcloud secrets describe doug-api-token --project "$PROJECT" >/dev/null 2>&1; then
    gcloud secrets add-iam-policy-binding doug-api-token --project "$PROJECT" \
      --member="serviceAccount:$CONSOLE_SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null
  else
    echo "WARN: secret doug-api-token does not exist yet — create it and re-run setup." >&2
  fi
  # Grant yourself the ability to invoke the gated console:
  #   gcloud run services add-iam-policy-binding doug-console --project "$PROJECT" \
  #     --region "$REGION" --member="user:YOUR@EMAIL" --role=roles/run.invoker
```

- [ ] **Step 4: Add the `console()` deploy function**

Add to `api/deploy/gcp.sh` after `web()`:

```bash
console() {
  # NO staged-traffic dance and NO smoke test: the service is
  # --no-allow-unauthenticated, so an unauthenticated curl from this script
  # gets 403 no matter how healthy the revision is. A failing console is an
  # operator inconvenience, not an outage — the tradeoff web() cannot make.
  gcloud run deploy "$CONSOLE_SERVICE" \
    --source ../console \
    --project "$PROJECT" --region "$REGION" \
    --no-allow-unauthenticated \
    --service-account "doug-console-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-env-vars "DOUG_API_URL=$(api_url)" \
    --set-secrets "DOUG_API_TOKEN=doug-api-token:latest" \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 60
  echo "console deployed. Reach it with:"
  echo "  gcloud run services proxy $CONSOLE_SERVICE --project $PROJECT --region $REGION"
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd api && uv run pytest tests/test_deploy_gcp.py -v`
Expected: 7 PASS (3 existing + 4 new)

- [ ] **Step 6: Run the full suite and lint**

Run: `cd api && uv run pytest && uv run ruff check .`
Expected: all pass, ruff clean

- [ ] **Step 7: Verify the script parses**

Run: `cd api && bash -n deploy/gcp.sh`
Expected: no output (syntax OK)

- [ ] **Step 8: Commit**

```bash
git add api/deploy/gcp.sh api/tests/test_deploy_gcp.py
git commit -m "deploy: doug-console as its own IAM-gated service

--no-allow-unauthenticated is pinned by a test, not by a comment: a console
deployed open publishes both tenants' PR titles, job errors and coverage
gaps. No staged-traffic smoke test, because an unauthenticated probe gets
403 from a healthy revision by design."
```

---

## Phase 1 exit criteria

Phase 1 is done when all of these hold:

1. `cd api && uv run pytest` passes with the ~21 new tests, and `uv run ruff check .` is clean.
2. `cd console && npm test && npm run lint && npm run build` all pass.
3. `./deploy/gcp.sh console` deploys, and an unauthenticated `curl` of the console URL returns 403.
4. `gcloud run services proxy doug-console` reaches the Runs list, showing runs from **both** installations with `repo` visible on every row.
5. Clicking a run opens the forensic page, which shows the job timeline, the coverage ruler with unseen files, the tier/model/prompt-hash block, findings, deviations and both outcome clocks.
6. Stopping doug-api and reloading renders the explicit failure panel and **no numbers**.

## Not in Phase 1

Phases 2–4 from the spec, each with its own plan. Three items are called out because a reader of the spec would expect them here:

- **The forensic page's eighth block, Disposition** (real / disproved / adjacent, `changed`, `settled_by`). The spec lists it among the eight blocks, but its only source is `docs/findings-log.jsonl` and its only route is `/v1/evidence/findings-log` — Phase 3. Phase 1 ships seven blocks.
- **Marking unseen files by read tier** (code / tests / prose). Blocked on `read_order()` landing from the `read-budget-routing` branch and on `/v1/runs/{id}` reporting the tier it assigned. See Task 9 Step 3 for why the obvious `_is_sensitive` marking is not a substitute.
- **Badging `replay` / `research` rows.** `run_history` excludes untenanted rows by default, so they cannot appear unless `include_untenanted=true` is passed, which nothing in Phase 1's UI does. The badge belongs with the Phase 3 rates, where the quarantine actually changes a number.

- **Phase 2** — `/v1/repos`, the Repos page, and a live health strip. Task 6's shell renders the health strip's markup; Phase 2 gives it real data.
- **Phase 3** — `/v1/evidence/*` and the Evidence page.
- **Phase 4** — `/v1/showcase/queue`, removing `DOUG_API_TOKEN` from doug-web, light-theming the public `/queue`, and deleting `/compare`. The `/compare` deletion should ride with PR #54's CI-path retirement.
