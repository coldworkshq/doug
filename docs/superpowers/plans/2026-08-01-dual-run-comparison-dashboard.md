# Dual-Run Comparison Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lossless App-versus-CI comparison read and a dashboard that exposes missing runs, duplicates, tier, coverage, and descriptive score gaps per PR head.

**Architecture:** The store returns every qualifying ledger event for the most recent PR groups; the API serializes those events without pairing them. A pure TypeScript module groups exact head revisions and computes metrics, and a server-rendered `/compare` route presents the evidence without fixtures.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, pytest, Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4, Node 22 built-in test runner.

## Global Constraints

- Work only in `/Users/andrew/Projects/doughq/repo/.claude/worktrees/dashboard` on `dashboard-dual-run`.
- Do not change `store.latest_reviews`, `/v1/queue`, the reader prompt, migration 003, authentication, spend controls, or safety-session-owned files.
- Append new code to `api/doug/store.py`, `api/doug/api.py`, `api/tests/test_store.py`, and `api/tests/test_api.py`; do not reorder or reformat unrelated regions.
- Preserve every qualifying verdict. App means all three identity columns set; CI means all three NULL; mixed identity and `tier='external'` are excluded.
- Never infer complete coverage from tier or a missing coverage row.
- The comparison UI has no fixture fallback.
- Run the full API suite and Ruff before every commit; run web tests, lint, and build before every web commit.
- Every commit includes `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Do not deploy or merge. Push the branch, open the PR, and stop.

---

## File map

- `api/doug/store.py`: lossless recent-PR comparison read and coverage attachment.
- `api/doug/api.py`: shared-token endpoint and ledger-to-wire serialization.
- `api/tests/test_store.py`: identity, duplicate, grouping-limit, scope, and coverage contracts.
- `api/tests/test_api.py`: auth, availability, validation, fallback metadata, and wire-shape contracts.
- `web/lib/api.ts`: comparison wire types, structural validator, and server-only fetch.
- `web/lib/comparison.ts`: comparison wire validation, pure head grouping, and descriptive statistics.
- `web/lib/comparison.test.mjs`: Node tests for validation, grouping, duplicates, missing paths, and metrics.
- `web/app/compare/page.tsx`: server-rendered comparison dashboard.
- `web/app/page.tsx`: landing navigation link.
- `web/app/queue/page.tsx`: queue navigation link.
- `web/package.json`: dependency-free `npm test` script.

---

### Task 1: Lossless comparison store read

**Files:**

- Modify: `api/tests/test_store.py:1310`
- Modify: `api/doug/store.py` at end of file

**Interfaces:**

- Consumes: `verdicts`, `reads`, `EXTERNAL_TIER`, `_get_engine()`.
- Produces: `comparison_reviews(limit: int = 50, repo: str | None = None) -> list[dict]`.
- Each returned row contains all verdict columns plus `coverage: dict | None`.

- [ ] **Step 1: Append failing store tests**

Add a helper that writes CI or App rows without hiding the identity contract:

```python
def _comparison_review(
    repo: str,
    pr_number: int,
    sha: str,
    *,
    app: bool,
    coverage: reader.Coverage | None = None,
) -> int:
    identity = (
        {"installation_id": 10, "github_repo_id": 20, "head_sha": sha, "source": "app"}
        if app else {}
    )
    verdict_id = store.save_review(
        repo,
        pr_number,
        "reader",
        VERDICT,
        RV,
        pr_meta={**_pr().model_dump(mode="json"), "number": pr_number, "head_sha": sha},
        coverage=coverage,
        **identity,
    )
    assert verdict_id is not None
    return verdict_id
```

Add these tests with behavioral docstrings:

```python
def test_comparison_reviews_keeps_both_paths_duplicates_and_coverage(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    coverage = reader.Coverage(
        diff_chars=20,
        sent_chars=10,
        files_sent=1,
        files_unseen=["second.py"],
        file_cut="first.py",
    )
    app_one = _comparison_review("o/r", 7, "a" * 40, app=True, coverage=coverage)
    app_two = _comparison_review("o/r", 7, "a" * 40, app=True)
    ci = _comparison_review("o/r", 7, "a" * 40, app=False)
    _external()
    mixed = store.save_review(
        "o/r",
        7,
        "reader",
        VERDICT,
        RV,
        pr_meta={**_pr().model_dump(mode="json"), "head_sha": "a" * 40},
        installation_id=10,
    )

    rows = store.comparison_reviews(repo="o/r")
    assert {row["id"] for row in rows} == {app_one, app_two, ci}
    assert mixed not in {row["id"] for row in rows}
    by_id = {row["id"]: row for row in rows}
    assert by_id[app_one]["coverage"]["sent_chars"] == 10
    assert by_id[app_one]["coverage"]["file_cut"] == "first.py"
    assert by_id[app_two]["coverage"] is None
    assert by_id[ci]["coverage"] is None


def test_comparison_reviews_limits_pr_groups_without_cutting_their_runs(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    _comparison_review("o/r", 1, "a" * 40, app=True)
    _comparison_review("o/r", 1, "a" * 40, app=False)
    newest_app = _comparison_review("o/r", 2, "b" * 40, app=True)
    newest_ci = _comparison_review("o/r", 2, "b" * 40, app=False)

    rows = store.comparison_reviews(limit=1)
    assert {row["id"] for row in rows} == {newest_app, newest_ci}
    assert {row["pr_number"] for row in rows} == {2}


def test_comparison_reviews_scopes_repo_and_is_empty_without_storage(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    wanted = _comparison_review("a/x", 1, "a" * 40, app=True)
    _comparison_review("b/y", 2, "b" * 40, app=True)
    assert [row["id"] for row in store.comparison_reviews(repo="a/x")] == [wanted]

    monkeypatch.delenv("DATABASE_URL")
    assert store.comparison_reviews() == []
```

- [ ] **Step 2: Run the focused tests and verify they fail for the missing function**

Run:

```bash
cd api
uv run pytest -q tests/test_store.py -k comparison_reviews
```

Expected: FAIL with `AttributeError: module 'doug.store' has no attribute 'comparison_reviews'`.

- [ ] **Step 3: Append the minimal store implementation**

Use one qualifying predicate in both the recent-group subquery and outer query:

```python
def comparison_reviews(limit: int = 50, repo: str | None = None) -> list[dict]:
    """All App and CI verdicts for the most recently scored PR groups.

    The limit counts PRs, not verdict rows, so one side of a pair and duplicate
    App writes cannot be cut away at the boundary.
    """
    engine = _get_engine()
    if engine is None or limit < 1:
        return []
    from sqlalchemy import and_, desc, func, or_, select

    app_identity = and_(
        verdicts.c.installation_id.is_not(None),
        verdicts.c.github_repo_id.is_not(None),
        verdicts.c.head_sha.is_not(None),
    )
    ci_identity = and_(
        verdicts.c.installation_id.is_(None),
        verdicts.c.github_repo_id.is_(None),
        verdicts.c.head_sha.is_(None),
    )
    qualifies = and_(
        verdicts.c.tier != EXTERNAL_TIER,
        or_(app_identity, ci_identity),
    )
    recent = select(
        verdicts.c.repo,
        verdicts.c.pr_number,
        func.max(verdicts.c.scored_at).label("latest_scored_at"),
    ).where(qualifies)
    if repo:
        recent = recent.where(verdicts.c.repo == repo)
    recent = (
        recent.group_by(verdicts.c.repo, verdicts.c.pr_number)
        .order_by(desc("latest_scored_at"))
        .limit(limit)
        .subquery()
    )
    query = (
        select(verdicts)
        .join(
            recent,
            (recent.c.repo == verdicts.c.repo)
            & (recent.c.pr_number == verdicts.c.pr_number),
        )
        .where(qualifies)
        .order_by(
            desc(recent.c.latest_scored_at),
            desc(verdicts.c.scored_at),
            desc(verdicts.c.id),
        )
    )
    out = []
    with engine.connect() as conn:
        for verdict in conn.execute(query).mappings():
            read = conn.execute(
                select(reads)
                .where(reads.c.verdict_id == verdict["id"])
                .order_by(desc(reads.c.id))
                .limit(1)
            ).mappings().first()
            out.append({**verdict, "coverage": dict(read) if read else None})
    return out
```

- [ ] **Step 4: Run focused and full API verification**

Run:

```bash
cd api
uv run pytest -q tests/test_store.py -k comparison_reviews
uv run pytest -q
uv run ruff check .
```

Expected: focused tests PASS; 457 baseline tests plus new tests PASS; Ruff prints `All checks passed!`.

- [ ] **Step 5: Mutation-check duplicate and identity behavior**

Temporarily change `or_(app_identity, ci_identity)` to `app_identity`; the both-path test must fail. Restore it. Temporarily add one-verdict-per-PR reduction; the duplicate test must fail. Restore it and rerun the focused tests.

- [ ] **Step 6: Commit the store read**

```bash
git add api/doug/store.py api/tests/test_store.py
git commit -m "feat: read dual-run comparison verdicts" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Token-gated comparison endpoint

**Files:**

- Modify: `api/tests/test_api.py:1567`
- Modify: `api/doug/api.py` at end of file

**Interfaces:**

- Consumes: `store.enabled()`, `store.comparison_reviews()`, existing `os`, `hmac`, `HTTPException`, and `Header` imports.
- Produces: `GET /v1/comparisons?repo=<owner/name>&limit=<1..200>` returning `{ "runs": ComparisonRun[] }`.
- `ComparisonRun.path` is `app | ci`; `coverage` is the store object without `id` or `verdict_id`.

- [ ] **Step 1: Append failing endpoint tests**

Add a local ledger helper and these tests:

```python
def _comparison_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/comparison.db")
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    assert store.enabled()


def _comparison_api_review(*, app: bool, coverage=None, pr_meta=None) -> int:
    sha = "a" * 40
    verdict = api.Verdict(
        score=0.2,
        band=api.Band.CLEARED,
        threshold=0.3,
        reasons=[],
    )
    identity = (
        {"installation_id": 10, "github_repo_id": 20, "head_sha": sha, "source": "app"}
        if app else {}
    )
    verdict_id = store.save_review(
        "o/r",
        33,
        "reader",
        verdict,
        pr_meta=(
            {"number": 33, "title": "Compare paths", "author": "dev", "files": [],
             "head_sha": sha}
            if pr_meta is None else pr_meta
        ),
        coverage=coverage,
        **identity,
    )
    assert verdict_id is not None
    return verdict_id


def test_comparisons_requires_the_shared_token(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    assert client.get("/v1/comparisons").status_code == 401


def test_comparisons_refuses_when_the_token_is_unconfigured(monkeypatch):
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    response = client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "anything"}
    )
    assert response.status_code == 503


def test_comparisons_refuses_when_the_ledger_is_unconfigured(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    )
    assert response.status_code == 503


def test_comparisons_rejects_a_limit_outside_one_through_two_hundred(
    tmp_path, monkeypatch
):
    _comparison_db(tmp_path, monkeypatch)
    for limit in (0, 201):
        response = client.get(
            "/v1/comparisons",
            params={"limit": limit},
            headers={"X-Doug-Token": "secret"},
        )
        assert response.status_code == 422


def test_comparisons_serializes_both_paths_duplicates_and_coverage(
    tmp_path, monkeypatch
):
    _comparison_db(tmp_path, monkeypatch)
    coverage = api.reader.Coverage(
        diff_chars=20,
        sent_chars=10,
        files_sent=1,
        files_unseen=["second.py"],
        file_cut="first.py",
    )
    app_one = _comparison_api_review(app=True, coverage=coverage)
    app_two = _comparison_api_review(app=True)
    ci = _comparison_api_review(app=False)

    response = client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    )
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert {run["id"] for run in runs} == {app_one, app_two, ci}
    assert [run["path"] for run in runs].count("app") == 2
    assert [run["path"] for run in runs].count("ci") == 1
    assert {run["head_sha"] for run in runs} == {"a" * 40}
    covered = next(run for run in runs if run["id"] == app_one)
    assert covered["coverage"]["sent_chars"] == 10
    assert covered["coverage"]["diff_chars"] == 20


def test_comparisons_keeps_a_run_whose_display_metadata_is_missing(
    tmp_path, monkeypatch
):
    _comparison_db(tmp_path, monkeypatch)
    verdict = api.Verdict(
        score=0.2,
        band=api.Band.CLEARED,
        threshold=0.3,
        reasons=[],
    )
    store.save_review("o/r", 9, "deterministic", verdict, pr_meta=None)

    run = client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    ).json()["runs"][0]
    assert run["title"] == "PR #9"
    assert run["url"] == "https://github.com/o/r/pull/9"
    assert run["head_sha"] is None
```

The serialization test must write two App rows and one CI row for one SHA, then assert all three ids are present; App uses the identity `head_sha`, CI uses `pr_meta.head_sha`, and coverage includes exact sent and diff character counts. The fallback test inserts a qualifying CI row with `pr_meta=None` and asserts `title == "PR #9"`, a repaired GitHub URL, and `head_sha is None`.

- [ ] **Step 2: Run the focused tests and verify the route is missing**

Run:

```bash
cd api
uv run pytest -q tests/test_api.py -k comparisons
```

Expected: FAIL because `/v1/comparisons` returns 404.

- [ ] **Step 3: Append path classification and serialization helpers**

Implement helpers with these exact contracts:

```python
def _comparison_path(row: dict) -> str:
    identity = (row["installation_id"], row["github_repo_id"], row["head_sha"])
    return "app" if all(value is not None for value in identity) else "ci"


def _comparison_run(row: dict) -> dict:
    path = _comparison_path(row)
    meta = row.get("pr_meta") if isinstance(row.get("pr_meta"), dict) else {}
    coverage = row.get("coverage")
    return {
        "id": row["id"],
        "repo": row["repo"],
        "pr_number": row["pr_number"],
        "title": meta.get("title") or f"PR #{row['pr_number']}",
        "url": meta.get("url") or f"https://github.com/{row['repo']}/pull/{row['pr_number']}",
        "head_sha": row["head_sha"] if path == "app" else meta.get("head_sha"),
        "path": path,
        "scored_at": row["scored_at"],
        "score": row["score"],
        "band": row["band"],
        "threshold": row["threshold"],
        "tier": row["tier"],
        "coverage": (
            {key: coverage[key] for key in (
                "diff_chars", "sent_chars", "files_sent", "files_unseen", "file_cut"
            )}
            if coverage else None
        ),
    }
```

- [ ] **Step 4: Append the route with the existing queue auth semantics**

```python
@app.get("/v1/comparisons")
def comparisons(
    repo: str | None = None,
    limit: int = 50,
    x_doug_token: str = Header(""),
) -> dict:
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if not hmac.compare_digest(x_doug_token, expected):
        raise HTTPException(status_code=401, detail="bad token")
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    return {"runs": [_comparison_run(row) for row in store.comparison_reviews(limit, repo)]}
```

- [ ] **Step 5: Run focused and full API verification**

Run:

```bash
cd api
uv run pytest -q tests/test_api.py -k comparisons
uv run pytest -q
uv run ruff check .
```

Expected: all tests PASS and Ruff is clean.

- [ ] **Step 6: Mutation-check wire preservation**

Temporarily derive both paths' SHA only from `row["head_sha"]`; the CI SHA assertion must fail. Restore it. Temporarily emit only the first store row; the duplicate serialization assertion must fail. Restore it and rerun focused tests.

- [ ] **Step 7: Commit the endpoint**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "feat: expose dual-run comparisons" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Web contract and comparison model

**Files:**

- Modify: `web/package.json:5-10`
- Modify: `web/lib/api.ts:154`
- Create: `web/lib/comparison.ts`
- Create: `web/lib/comparison.test.mjs`

**Interfaces:**

- Produces `ComparisonRun` and `ComparisonResponse` types plus `isComparisonResponse(data: unknown): data is ComparisonResponse` from `web/lib/comparison.ts`; `web/lib/api.ts` re-exports them.
- Produces `getComparisons(): Promise<ComparisonResult>` from `web/lib/api.ts`.
- Produces `summarizeComparisons(runs: ComparisonRun[]): ComparisonView`.
- `ComparisonView` contains ordered groups and summary fields `exactPairs`, `missingApp`, `missingCi`, `duplicateGroups`, `meanSignedGap`, `meanAbsoluteGap`, and `maxAbsoluteGap`.

- [ ] **Step 1: Add the dependency-free test script and failing tests**

Add:

```json
"test": "node --test --experimental-strip-types lib/*.test.mjs"
```

Create tests using `node:test` and `node:assert/strict`, importing the TypeScript module as `./comparison.ts`. Fixtures must cover two exact pairs on separate SHAs of the same PR, an App-only head, a CI-only head, two App duplicates on one head, and two null-SHA runs. Assert:

```typescript
assert.equal(view.summary.exactPairs, 2);
assert.equal(view.summary.missingApp, 1);
assert.equal(view.summary.missingCi, 1);
assert.equal(view.summary.duplicateGroups, 1);
assert.ok(Math.abs(view.summary.meanSignedGap - 0) < 1e-9);
assert.ok(Math.abs(view.summary.meanAbsoluteGap - 0.2) < 1e-9);
assert.ok(Math.abs(view.summary.maxAbsoluteGap - 0.2) < 1e-9);
assert.notEqual(unknownGroups[0].key, unknownGroups[1].key);
```

Add validator cases for a valid empty response, malformed `path`, malformed coverage, invalid timestamp, and a missing field the page dereferences.

- [ ] **Step 2: Run web tests and verify the source modules are missing**

Run:

```bash
cd web
npm test
```

Expected: FAIL with module/export-not-found errors.

- [ ] **Step 3: Implement comparison wire types and validation in `web/lib/comparison.ts`**

Define the coverage and run fields exactly as the API emits. The validator must check finite numeric fields, `app | ci`, `cleared | flagged`, a parseable timestamp, nullable string SHA, and every coverage field when coverage is non-null. Export the types and validator.

- [ ] **Step 4: Import the comparison contract and append the fetch to `web/lib/api.ts`**

Import `isComparisonResponse` and `ComparisonResponse` from `./comparison`, re-export the comparison contract from `web/lib/api.ts`, and fetch with:

Fetch with:

```typescript
export async function getComparisons(): Promise<ComparisonResult> {
  try {
    const repoParam = QUEUE_REPO ? `?repo=${encodeURIComponent(QUEUE_REPO)}` : "";
    const res = await fetch(`${API_URL}/v1/comparisons${repoParam}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
      headers: { "X-Doug-Token": process.env.DOUG_API_TOKEN ?? "" },
    });
    if (res.ok) {
      const body: unknown = await res.json();
      if (isComparisonResponse(body)) return { comparison: body, source: "live" };
    }
  } catch {
    // The caller renders unavailable; comparison evidence is never fabricated.
  }
  return { comparison: null, source: "unavailable" };
}
```

- [ ] **Step 5: Implement the pure grouping model**

Use the SHA-bearing key below and a run-specific fallback:

```typescript
const keyFor = (run: ComparisonRun) =>
  run.head_sha
    ? `${run.repo}:${run.pr_number}:${run.head_sha}`
    : `${run.repo}:${run.pr_number}:unknown:${run.id}`;
```

For each group, retain all path arrays, set presence from non-empty arrays, set `duplicate` when either array length exceeds one, and set `delta` only when both arrays have length one. Sort groups by newest `scored_at`. Calculate all gap metrics from non-null deltas only and return `null` metrics when there are no exact pairs.

- [ ] **Step 6: Run tests, then mutation-check the grouping contract**

Run:

```bash
cd web
npm test
```

Temporarily omit `head_sha` from `keyFor`; the multi-push fixture must fail. Restore it. Temporarily allow duplicate groups into deltas; the duplicate fixture must fail. Restore and rerun.

- [ ] **Step 7: Run all web verification**

```bash
cd web
npm test
npm run lint
npm run build
```

Expected: tests PASS, lint exits zero, and the existing routes still build.

- [ ] **Step 8: Commit the web data boundary**

```bash
git add web/package.json web/lib/api.ts web/lib/comparison.ts web/lib/comparison.test.mjs
git commit -m "feat: model dual-run comparison evidence" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Comparison dashboard and navigation

**Files:**

- Create: `web/app/compare/page.tsx`
- Modify: `web/app/page.tsx:82-95`
- Modify: `web/app/queue/page.tsx:51-67`

**Interfaces:**

- Consumes: `getComparisons()`, `summarizeComparisons()`, `DougLogo`, and existing global design tokens.
- Produces: server-rendered `/compare` route with unavailable, empty, and populated states.

- [ ] **Step 1: Read current framework and visual instructions before UI code**

Read `web/AGENTS.md`, the relevant Next 16 App Router server-component and data-fetching guides under `web/node_modules/next/dist/docs/`, and the `frontend-design` skill. Confirm the page stays a server component and uses no client-side state.

- [ ] **Step 2: Implement the route shell and source-honest states**

The page calls `getComparisons()` once. If `comparison` is null, render a branded unavailable panel saying no soak evidence is being shown. If `runs` is empty, render a configured-but-empty panel. Neither state renders summary zeroes as observations.

- [ ] **Step 3: Implement populated summary and revision evidence**

Render:

- Header: “Two paths. One head.” with live API badge.
- Cards: exact pairs, missing App, missing CI, duplicate groups, signed mean gap, mean absolute gap, and maximum absolute gap. Each gap card includes the exact-pair count.
- Revision cards sorted by the pure model. Each shows repo, PR link, short SHA or `head unknown`, presence badge, duplicate badge, and singleton delta.
- Side-by-side App and CI columns. Missing App uses the flag tone and literal `missing App run`; missing CI says `missing CI run` without the same alert priority.
- Every run shows score, band, tier, scored timestamp, and coverage. Coverage is `coverage unavailable` when null; otherwise show rounded percentage plus sent/total characters, cut file, and unseen files.
- A zero-to-one score rail for exact pairs, with separate labeled App and CI markers. Exact numeric scores remain visible.

Do not use color alone for status, do not say a small gap is noise, and do not imply the instruments were equivalent when tier or coverage differs.

- [ ] **Step 4: Add navigation links**

Add `Compare` beside `Queue` on the landing page. On `/queue`, add a compact `Compare` link without removing the live/fixture badge. On `/compare`, link back to Queue and GitHub.

- [ ] **Step 5: Run web tests, lint, and build**

```bash
cd web
npm test
npm run lint
npm run build
```

Expected route table includes dynamic `/compare`; all commands exit zero.

- [ ] **Step 6: Render and inspect the page locally**

Start the existing Next dev server, open `/compare` through the in-app browser, and inspect desktop and narrow viewport screenshots. Verify long PR titles, duplicate attempts, missing App, missing CI, null coverage, partial coverage, and empty/unavailable layouts do not overflow or imply false data. Stop the server after inspection.

- [ ] **Step 7: Commit the dashboard**

```bash
git add web/app/compare/page.tsx web/app/page.tsx web/app/queue/page.tsx
git commit -m "feat: show App and CI runs side by side" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Final verification, review, and PR

**Files:**

- Review: all branch changes relative to `origin/main`.
- Modify only files required by verified findings.

**Interfaces:**

- Produces: verified branch `dashboard-dual-run` and an open PR against `main`.

- [ ] **Step 1: Run the complete verification matrix from a clean state**

```bash
cd api
uv run pytest -q
uv run ruff check .
cd ../web
npm test
npm run lint
npm run build
cd ..
git diff --check origin/main...HEAD
git status --short
```

Expected: no skipped tests, all commands pass, no whitespace errors, and only intentional files differ.

- [ ] **Step 2: Review the complete diff against the approved spec**

Check each spec section explicitly: identity classification, external exclusion, recent-PR limit, duplicate preservation, coverage honesty, auth parity, no fixture, exact-head pairing, missing-path visibility, descriptive-only statistics, navigation, and no out-of-scope files.

- [ ] **Step 3: Request independent code review and verify every finding**

Use the `superpowers:requesting-code-review` skill. For every finding, reproduce it against the full repository before changing code. Record code outside the diff that disproves a finding. After fixes, rerun the relevant focused tests and a scoped re-review.

- [ ] **Step 4: Rerun the complete verification matrix after review fixes**

Repeat Step 1 with fresh output. Do not reuse pre-fix results.

- [ ] **Step 5: Push and open the PR**

```bash
git push -u origin dashboard-dual-run
gh pr create --base main --head dashboard-dual-run \
  --title "Show App and CI review runs side by side" \
  --body "## Summary

- add a lossless, token-gated App-versus-CI comparison read
- show missing paths, duplicates, tier, coverage, and exact-head score gaps at /compare
- keep /v1/queue and the review paths unchanged

## Verification

- API: full pytest suite and Ruff
- Web: Node tests, ESLint, and Next production build
- Mutation checks: identity predicate, duplicate preservation, CI SHA, coverage, and head grouping
- Browser QA: populated, missing-path, duplicate, partial-coverage, empty, and unavailable states

## Scope

This PR does not retire CI, deploy, change the frozen reader, add tenant auth, add spend controls, or implement migration 003. npm ci continues to report four pre-existing high-severity advisories."
```

The PR body must state the mechanism, exact verification counts, mutation checks, UI inspection, npm audit advisory, and that the work does not retire CI, deploy, alter the reader, or implement tenant auth. Do not merge.

- [ ] **Step 6: Inspect Doug's PR verdict and GitHub checks**

Wait for checks. Verify every Doug finding against the repository before fixing or dismissing it, following `docs/REVIEWING.md`. If fixes are needed, commit them with the required trailer, push, rerun the full matrix, and re-check. Stop with the PR open and unmerged.
