# Retire `/compare` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the dead App-vs-CI comparison surface (`/compare`, `/v1/comparisons`, store read, client helpers) and scrub operational docs so nothing still presents it as live.

**Architecture:** Leaf-to-root deletion. Pin that the API route is gone with one 404 test, remove the endpoint and its comparison-only tests, delete the store read next, then strip the web route/client/nav, then update operational docs and stamp the dual-run design/plan as retired. No schema changes; `/queue` and App-path review stay untouched.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, pytest, Next.js 16 App Router, TypeScript, Node built-in test runner, Ruff.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-07-retire-compare-path-design.md`
- Branch from `origin/main` as `retire-compare-path` (must include PR #54). Do not stack on `read-budget-routing`.
- Do not edit worker, webhook, scoring, queue serialization, migrations, or Cloud Run/IAM.
- Do not rewrite tenant-token historical specs/plans that mention `/v1/comparisons`.
- Dual-run design/plan files get a one-line retired banner only — bodies stay.
- Run API pytest (+ ruff if the repo’s usual pre-commit path expects it) after Python tasks; run `npm test` and `npm run lint` in `web/` after the web task.
- Do not deploy or merge unless the user asks.

---

## File map

| Action | Path | Responsibility |
|---|---|---|
| Delete | `web/app/compare/page.tsx` | `/compare` UI |
| Modify | `web/app/page.tsx` | Remove Compare nav link |
| Modify | `web/app/queue/page.tsx` | Remove Compare nav link |
| Delete | `web/lib/comparison.ts` | Comparison types + grouping |
| Delete | `web/lib/comparison.test.mjs` | Comparison unit tests |
| Modify | `web/lib/api.ts` | Remove comparison imports, types, `getComparisons` |
| Modify | `api/doug/api.py` | Remove `/v1/comparisons` + helpers |
| Modify | `api/doug/store.py` | Remove `comparison_reviews` + limit/error |
| Modify | `api/tests/test_api.py` | Replace comparison suite with 404 pin; shrink parametrize |
| Modify | `api/tests/test_store.py` | Delete comparison_reviews tests + helper |
| Modify | `docs/REVIEWING.md` | Strip live `/compare` claims; keep transferable lessons |
| Modify | `/Users/andrew/Projects/doughq/HANDOFF.md` | Mark `/compare` deletion done |
| Banner | `docs/superpowers/specs/2026-08-01-dual-run-comparison-dashboard-design.md` | Retired note |
| Banner | `docs/superpowers/plans/2026-08-01-dual-run-comparison-dashboard.md` | Retired note |

---

### Task 0: Branch setup

**Files:** none (git only)

- [ ] **Step 1: Create branch from origin/main**

```bash
cd /Users/andrew/Projects/doughq/repo
git fetch origin main
git checkout -b retire-compare-path origin/main
```

Expected: on `retire-compare-path`, tracking or based on `origin/main`. Confirm PR #54 is an ancestor:

```bash
git merge-base --is-ancestor e1aea0f HEAD && echo ok
```

Expected: `ok`

- [ ] **Step 2: No commit yet** — setup only.

---

### Task 1: Retire `GET /v1/comparisons`

**Files:**
- Modify: `api/doug/api.py` (remove `_comparison_path`, `_comparison_run`, `comparisons` endpoint at end of file)
- Modify: `api/tests/test_api.py` (delete comparison helpers/tests; add 404 pin; shrink parametrize lists)
- Test: `api/tests/test_api.py`

**Interfaces:**
- Consumes: none from later tasks
- Produces: FastAPI no longer registers `/v1/comparisons` (404). Operator-auth parametrize lists no longer include that path.

- [ ] **Step 1: Replace the comparison API tests with a 404 pin and shrink parametrize lists**

In `api/tests/test_api.py`, delete from `def _comparison_db` through the end of `test_comparisons_keeps_a_run_whose_display_metadata_is_missing` (everything before `def _api_db`). Insert this single replacement:

```python
def test_comparisons_route_is_gone(monkeypatch):
    """Dual-run soak instrument retired with the CI path (PR #54)."""
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    assert client.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    ).status_code == 404
```

Change the two parametrize lists:

```python
@pytest.mark.parametrize("path", ["/v1/patterns", "/v1/score/read"])
def test_tenant_token_404s_on_operator_only_endpoints(tmp_path, monkeypatch, path):
    ...


@pytest.mark.parametrize("path", ["/v1/patterns"])
def test_junk_token_is_still_401_on_operator_only_endpoints(tmp_path, monkeypatch, path):
    ...
```

- [ ] **Step 2: Run the 404 pin — expect FAIL while the route still exists**

```bash
cd /Users/andrew/Projects/doughq/repo/api
uv run pytest -q tests/test_api.py::test_comparisons_route_is_gone
```

Expected: FAIL — status is 401/503/200/422/413, not 404 (route still registered).

- [ ] **Step 3: Delete the API endpoint and helpers**

In `api/doug/api.py`, delete `_comparison_path`, `_comparison_run`, and the entire `@app.get("/v1/comparisons")` `comparisons` function (they are contiguous at the end of the file). Leave whatever function precedes them intact, with a single trailing newline at EOF.

- [ ] **Step 4: Verify the pin and the related auth tests**

```bash
cd /Users/andrew/Projects/doughq/repo/api
uv run pytest -q \
  tests/test_api.py::test_comparisons_route_is_gone \
  tests/test_api.py::test_tenant_token_404s_on_operator_only_endpoints \
  tests/test_api.py::test_junk_token_is_still_401_on_operator_only_endpoints
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/andrew/Projects/doughq/repo
git add api/doug/api.py api/tests/test_api.py
git commit -m "$(cat <<'EOF'
feat: retire GET /v1/comparisons

The App-vs-CI soak endpoint is meaningless after CI-path retirement.
EOF
)"
```

---

### Task 2: Delete `store.comparison_reviews`

**Files:**
- Modify: `api/doug/store.py` — remove `COMPARISON_RUN_LIMIT`, `ComparisonResultTooLarge`, and `comparison_reviews`
- Modify: `api/tests/test_store.py` — remove `_comparison_review` and all `test_comparison_reviews_*` / `test_current_ci_review_is_visible_in_comparisons_*` tests
- Test: `api/tests/test_store.py`, full API suite

**Interfaces:**
- Consumes: Task 1 removed the only production caller
- Produces: `doug.store` has no `comparison_reviews` attribute

- [ ] **Step 1: Delete the store tests and helper**

In `api/tests/test_store.py`, delete from `def _comparison_review` through the end of `test_comparison_reviews_scopes_repo_and_is_empty_without_storage` (stop before `def _scored`).

- [ ] **Step 2: Confirm nothing outside the deleted block still references comparison_reviews**

```bash
cd /Users/andrew/Projects/doughq/repo
rg -n 'comparison_reviews|COMPARISON_RUN_LIMIT|ComparisonResultTooLarge|_comparison_review' api/
```

Expected: hits only in `api/doug/store.py` (implementation still present).

- [ ] **Step 3: Delete the store implementation**

In `api/doug/store.py`:

1. Delete:

```python
COMPARISON_RUN_LIMIT = 500


class ComparisonResultTooLarge(RuntimeError):
    """The comparison cannot be returned without cutting ledger evidence."""

    def __init__(self, limit: int):
        super().__init__(
            f"comparison contains more than {limit} runs; narrow the repo or PR limit"
        )
```

Keep a single blank line between `metadata = MetaData()` and `verdicts = Table(` if that was the surrounding structure.

2. Delete the entire `comparison_reviews` function (from `def comparison_reviews(` through its final `return out`), including its docstring. Leave the preceding function intact with normal spacing.

- [ ] **Step 4: Run store + full API suite**

```bash
cd /Users/andrew/Projects/doughq/repo/api
uv run pytest -q
```

Expected: all green; no `comparison_reviews` / `COMPARISON_RUN_LIMIT` collection errors.

Also confirm orphans are gone:

```bash
rg -n 'comparison_reviews|COMPARISON_RUN_LIMIT|ComparisonResultTooLarge|/v1/comparisons' api/
```

Expected: no matches (the 404 pin string `/v1/comparisons` in `test_comparisons_route_is_gone` is allowed — that one path string must remain).

- [ ] **Step 5: Commit**

```bash
cd /Users/andrew/Projects/doughq/repo
git add api/doug/store.py api/tests/test_store.py
git commit -m "$(cat <<'EOF'
feat: remove comparison_reviews store read

No remaining caller after /v1/comparisons retirement.
EOF
)"
```

---

### Task 3: Delete the web `/compare` surface

**Files:**
- Delete: `web/app/compare/page.tsx`
- Delete: `web/lib/comparison.ts`
- Delete: `web/lib/comparison.test.mjs`
- Modify: `web/lib/api.ts`
- Modify: `web/app/page.tsx`
- Modify: `web/app/queue/page.tsx`
- Test: `web` `npm test`, `npm run lint`

**Interfaces:**
- Consumes: none (API already 404s)
- Produces: no `/compare` route; no Compare nav; `api.ts` queue helpers unchanged

- [ ] **Step 1: Strip comparison exports and `getComparisons` from `web/lib/api.ts`**

Replace the top of the file so it no longer imports or re-exports comparison types. The file must start:

```typescript
import fixture from "./queue-fixture.json";

export type Band = "cleared" | "flagged";
```

Delete the entire block:

```typescript
export type ComparisonResult = {
  comparison: ComparisonResponse | null;
  source: "live" | "unavailable";
};
```

and the entire `getComparisons` function. Leave `getQueue`, `applyThreshold`, and queue types untouched.

Also remove these imports/re-exports that currently sit at the top:

```typescript
import { isComparisonResponse, type ComparisonResponse } from "./comparison";

export { isComparisonResponse } from "./comparison";
export type {
  ComparisonCoverage,
  ComparisonGroup,
  ComparisonPresence,
  ComparisonResponse,
  ComparisonRun,
  ComparisonSummary,
  ComparisonView,
} from "./comparison";
```

- [ ] **Step 2: Remove Compare nav links**

In `web/app/page.tsx`, delete the Compare `Link` block so Queue is immediately followed by GitHub:

```tsx
          <Link
            href="/queue"
            className="rounded-full px-3 py-1 transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            Queue
          </Link>
          <a
            href="https://github.com/drewjst/doug"
            className="rounded-full px-3 py-1 transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            GitHub
          </a>
```

In `web/app/queue/page.tsx`, delete the Compare `Link` entirely. Keep the live/fixture badge. The nav `div` should look like:

```tsx
          <div className="flex items-center gap-2">
            <span className="glass flex items-center gap-2 rounded-full px-3 py-1.5 font-mono text-xs text-muted-foreground">
              <span
                className={
                  "size-1.5 rounded-full " +
                  (source === "live"
                    ? "animate-pulse bg-clear"
                    : "bg-muted-foreground")
                }
              />
              {source === "live" ? "live api" : "bundled fixture"}
            </span>
          </div>
```

- [ ] **Step 3: Delete the compare page and comparison client module**

```bash
cd /Users/andrew/Projects/doughq/repo
rm web/app/compare/page.tsx
rmdir web/app/compare
rm web/lib/comparison.ts web/lib/comparison.test.mjs
```

- [ ] **Step 4: Verify web tests and lint; grep for orphans**

```bash
cd /Users/andrew/Projects/doughq/repo/web
npm test
npm run lint
```

Expected: tests pass (queue tests only; comparison tests gone); lint clean.

```bash
cd /Users/andrew/Projects/doughq/repo
rg -n 'getComparisons|/compare|from \"@/lib/comparison\"|from \"./comparison\"' web/
```

Expected: no matches.

Optional build check (slower, recommended once):

```bash
cd /Users/andrew/Projects/doughq/repo/web
npm run build
```

Expected: success; route table has no `/compare`.

- [ ] **Step 5: Commit**

```bash
cd /Users/andrew/Projects/doughq/repo
git add -A web/
git commit -m "$(cat <<'EOF'
feat: remove /compare dashboard and client helpers

Nav, page, and comparison grouping existed only for App-vs-CI soak.
EOF
)"
```

---

### Task 4: Operational docs + retired banners

**Files:**
- Modify: `docs/REVIEWING.md`
- Modify: `/Users/andrew/Projects/doughq/HANDOFF.md` (workspace working note — **outside** the `repo` git root; edit in place, no commit). `repo/HANDOFF.md` has no `/compare` deletion note — leave it unless a present-tense live claim appears.
- Modify: `docs/superpowers/specs/2026-08-01-dual-run-comparison-dashboard-design.md`
- Modify: `docs/superpowers/plans/2026-08-01-dual-run-comparison-dashboard.md`
- Leave untouched: tenant-token design/plan docs; ROADMAP historical mid-soak sentences

**Interfaces:**
- Produces: operators reading REVIEWING/HANDOFF no longer see `/compare` as live

- [ ] **Step 1: Rewrite the live `/compare` section in `docs/REVIEWING.md`**

Replace the entire section starting at:

```markdown
## A shared commit SHA does not make App and CI the same idempotency domain
```

through the paragraph ending:

```markdown
establish a regression, and speculative query rewrites can reintroduce the N+1 or cut
duplicate evidence.
```

with:

```markdown
## A shared commit SHA does not make two delivery paths the same idempotency domain

During App-vs-CI dual-run soak (retired with PR #54), a shared head SHA did not
mean the two paths shared an idempotency domain. The CI `/v1/review` route
deduped with `find_review` (NULL App ids); App webhook deliveries enqueue a job
and `worker.py` deduplicates with
`find_verdict_by_identity(installation_id, github_repo_id, pr_number, head_sha)`.
Cross-instrument dedupe would have destroyed the soak evidence rather than
saving a duplicate read. The dual-run comparison dashboard (`/compare`,
`/v1/comparisons`) that measured that evidence is also gone.

Lasting lesson: before treating a dedupe helper as global, enumerate its
production callers and identify the event identity each caller owns. A
hypothetical route from one delivery mechanism through another is not a current
regression.

The same PR #38 review pass also taught coverage-read lessons that outlive the
dashboard: do not invent `.get()` fallbacks for column shapes the producer has
never emitted; prefer set-based joins over per-verdict SELECTs; and when a
safety bound would cut evidence, fail loud rather than return a partial slice
that a client could misread as a missing path. Trace an error through its
consumer before claiming the user sees a crash or fabricated state.
```

- [ ] **Step 2: Mark workspace HANDOFF deletion done (not in git)**

In `/Users/andrew/Projects/doughq/HANDOFF.md` (outside the doug git root), replace:

```markdown
- /compare gets DELETED, riding with PR #54's CI-path retirement (Task 9) —
  the page renders app-vs-CI dual runs and is meaningless once that path is gone
```

with:

```markdown
- /compare DELETED (with `/v1/comparisons` + `comparison_reviews`) after PR #54
  CI-path retirement — App-vs-CI dual-run soak instrument is gone
```

Leave other historical `/v1/comparisons` mid-soak rationale bullets as-is. Do not
`git add` this file from `repo/` — it is not tracked there.

- [ ] **Step 3: Add retired banners to the dual-run design and plan**

At the very top of `docs/superpowers/specs/2026-08-01-dual-run-comparison-dashboard-design.md`, insert:

```markdown
> **Retired (2026-08-07):** App-vs-CI dual-run soak ended with PR #54. `/compare` and `/v1/comparisons` are deleted. This document is historical.

```

At the very top of `docs/superpowers/plans/2026-08-01-dual-run-comparison-dashboard.md`, insert the same banner line (before the `# Dual-Run...` title).

Do not edit the bodies. Do not touch tenant-token docs.

- [ ] **Step 4: Grep operational surfaces for present-tense live claims**

```bash
cd /Users/andrew/Projects/doughq
rg -n '`/compare`|/compare |/v1/comparisons' HANDOFF.md repo/docs/REVIEWING.md repo/docs/design/outcome-loop/ROADMAP.md
```

Expected:
- HANDOFF: deletion-done note and any historical mid-soak rationale only
- REVIEWING: past-tense / retired framing only
- ROADMAP: historical mid-soak sentences only (no “still serves comparisons” claims). If a present-tense live claim remains, fix that sentence in the same commit; otherwise leave ROADMAP alone.

- [ ] **Step 5: Commit (repo docs only)**

```bash
cd /Users/andrew/Projects/doughq/repo
git add \
  docs/REVIEWING.md \
  docs/superpowers/specs/2026-08-01-dual-run-comparison-dashboard-design.md \
  docs/superpowers/plans/2026-08-01-dual-run-comparison-dashboard.md \
  docs/superpowers/specs/2026-08-07-retire-compare-path-design.md \
  docs/superpowers/plans/2026-08-07-retire-compare-path.md
git commit -m "$(cat <<'EOF'
docs: mark /compare retirement done

Operational docs no longer treat the dual-run soak dashboard as live.
EOF
)"
```

---

### Task 5: Final verification

**Files:** none (commands only)

- [ ] **Step 1: Full API suite**

```bash
cd /Users/andrew/Projects/doughq/repo/api
uv run pytest -q
```

Expected: all passed.

- [ ] **Step 2: Web test + lint**

```bash
cd /Users/andrew/Projects/doughq/repo/web
npm test && npm run lint
```

Expected: pass.

- [ ] **Step 3: Contract smoke (optional local servers)**

If API and web can be started locally:

```bash
# API: GET /v1/comparisons → 404; GET /v1/queue without token → 401
# Web: /compare → Next 404; / and /queue have no Compare link
```

- [ ] **Step 4: Non-impact diff check**

```bash
cd /Users/andrew/Projects/doughq/repo
git diff origin/main...HEAD --stat
git diff origin/main...HEAD --name-only | rg 'worker|webhook|migrations|check_run|scoring' || echo 'no impact files'
```

Expected: no matches on those impact files (or only incidental doc mentions).

- [ ] **Step 5: Stop** — do not open a PR unless the user asks.

---

## Spec coverage self-review

| Spec requirement | Task |
|---|---|
| Delete web route + nav | Task 3 |
| Delete comparison client + tests | Task 3 |
| Delete `/v1/comparisons` + helpers | Task 1 |
| Delete `comparison_reviews` + constants/errors | Task 2 |
| Delete comparison-only tests; shrink parametrize | Tasks 1–2 |
| Update REVIEWING.md | Task 4 |
| Update workspace HANDOFF deletion note (not in git) | Task 4 |
| ROADMAP only if present-tense live claim | Task 4 Step 4 |
| Dual-run design/plan retired banners | Task 4 |
| Leave tenant-token historical docs | Task 4 (explicit non-touch) |
| No schema/worker/queue changes | Global constraints + Task 5 |
| Branch from origin/main | Task 0 |
| Verify pytest / web / 404 / non-impact | Tasks 1–5 |
