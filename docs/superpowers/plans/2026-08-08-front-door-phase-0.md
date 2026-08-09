# Front Door Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the operator credential from `doug-web` by giving the public pages their own unauthenticated, deployment-pinned endpoint — and put a test job behind the web app that actually asserts something.

**Architecture:** A new `GET /v1/showcase/queue` on `doug-api` serves one repo named by `DOUG_SHOWCASE_REPO`, with no token gate at all. Both public pages fetch it instead of the token-gated `/v1/queue`. `doug-web` then loses `DOUG_API_TOKEN` from its deploy and its Secret Manager binding. The queue-response assembly is extracted first so the two endpoints share it rather than drifting.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (`api/`), Next.js 16.2.12 + node:test (`web/`), bash + pytest-pinned deploy script (`api/deploy/gcp.sh`, `api/tests/test_deploy_gcp.py`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-08-front-door-design.md` (commit `62c461a`). Branch `front-door-design`, worktree `repo/.worktrees/front-door`, off `origin/main` `7fa5869`.
- **This repo has NO `conftest.py` and NO pytest fixtures.** The idiom is `tmp_path` + `monkeypatch` + the module's own `_db()` helper (`api/tests/test_api.py:2467`) + `TestClient(app)` constructed inside the test.
- **`DOUG_SHOWCASE_REPO` lives on `doug-api`, not `doug-web`.** The endpoint reads it; the web app must never send a repo selector.
- The showcase endpoint **must not** read or require `DOUG_API_TOKEN`. That dependency is the entire reason it exists (`api/doug/api.py:317-322` shows the pattern being avoided).
- Run API tests from `api/`: `uv run pytest`. Lint: `uv run ruff check .`.
- Run web checks from `web/`: `npm test`, `npm run lint`, `npm run build`.
- Do not touch `docs/design/outcome-loop/publication-preregistration.md` — it is LOCKED.
- Commit after every task. Never amend a commit from a previous task.

---

### Task 1: Extract the queue-response assembly

Pure refactor. `queue()` currently inlines row→item mapping, re-banding, sorting and summary counting. Two endpoints are about to need all of it, and a second copy would drift. **For a pure refactor the existing tests ARE the test** — they must pass unchanged, before and after, with no new assertions about behavior.

**Files:**
- Modify: `api/doug/api.py:355-420` (inside `queue()`)
- Test: `api/tests/test_api.py` (existing tests only; no new test file)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_rows_to_items(rows: list[dict]) -> list[QueueItem]` and `_queue_response(items: list[QueueItem], threshold: float | None) -> QueueResponse`, both module-level in `api/doug/api.py`. Task 2 calls both.

- [ ] **Step 1: Record the current green baseline**

Run from `api/`:

```bash
uv run pytest -q 2>&1 | tail -3
```

Write the exact test count down. It must be identical at Step 5.

- [ ] **Step 2: Add the two helpers above `queue()`**

Insert immediately before the `@app.get("/v1/queue")` decorator in `api/doug/api.py`:

```python
def _rows_to_items(rows: list[dict]) -> list[QueueItem]:
    """Ledger rows -> queue items. Rows without pr_meta are dropped: the
    queue renders PR titles and authors, and a row that has none would
    render as a blank card rather than a missing one."""
    return [
        QueueItem(
            pr=_with_url(row),
            verdict=Verdict(
                score=row["score"],
                band=Band(row["band"]),
                threshold=row["threshold"],
                reasons=[
                    Reason(
                        rule=f["rule"],
                        label=f["label"],
                        weight=f["weight"],
                        severity=f["severity"],
                    )
                    for f in row["findings"]
                ],
            ),
        )
        for row in rows
        if row["pr_meta"]
    ]


def _queue_response(
    items: list[QueueItem], threshold: float | None
) -> QueueResponse:
    """Band, sort and summarise. Shared by /v1/queue and
    /v1/showcase/queue so the two cannot drift on the banding rule —
    which is the one place this surface has already been wrong once
    (reporting 0.62 while showing rows flagged at 0.30)."""
    thr = default_threshold() if threshold is None else threshold
    if threshold is None:
        # Report the line the rows were actually banded at, not the
        # deterministic default.
        thr = _banding_threshold(items, thr)
    else:
        # An explicit threshold has to re-band, or the parameter changes
        # the summary while the rows keep contradicting it.
        items = [
            QueueItem(
                pr=i.pr,
                verdict=i.verdict.model_copy(
                    update={
                        "threshold": thr,
                        "band": Band.FLAGGED if i.verdict.score >= thr else Band.CLEARED,
                    }
                ),
            )
            for i in items
        ]

    items.sort(key=lambda i: i.verdict.score, reverse=True)
    flagged = sum(1 for i in items if i.verdict.band is Band.FLAGGED)
    return QueueResponse(
        summary=QueueSummary(
            open=len(items),
            flagged=flagged,
            cleared=len(items) - flagged,
            threshold=thr,
        ),
        items=items,
    )
```

- [ ] **Step 3: Rewrite `queue()`'s tail to call them**

Replace everything in `queue()` from `thr = default_threshold() if threshold is None else threshold` through the final `return QueueResponse(...)` with:

```python
    thr = default_threshold() if threshold is None else threshold
    if store.enabled():
        items = _rows_to_items(
            store.latest_reviews(
                repo=repo if ctx is None else None,  # operator keeps the display filter
                installation_id=installation_id,
                repo_ids=repo_ids,
            )
        )
    else:
        # No ledger configured — the fixture keeps the demo path alive.
        items = [QueueItem(pr=pr, verdict=score(pr, thr)) for pr in _load_fixture()]

    return _queue_response(items, threshold)
```

Leave everything above `thr = ...` (the token gate, `tenancy.resolve`, the scope check, the `?repo=` 404) exactly as it is.

- [ ] **Step 4: Lint**

```bash
uv run ruff check .
```

Expected: clean.

- [ ] **Step 5: Run the full suite and compare to the baseline**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: **the identical count from Step 1, all passing.** A refactor that changes the count changed behavior — revert and redo.

- [ ] **Step 6: Commit**

```bash
git add api/doug/api.py
git commit -m "refactor: extract the queue-response assembly for reuse"
```

---

### Task 2: `GET /v1/showcase/queue`

The public, unauthenticated, deployment-pinned queue. Already designed at `docs/superpowers/specs/2026-08-06-doug-console-design.md:57-61` and `:188-189`, including the 404-when-unset behavior — this executes that item.

**Files:**
- Modify: `api/doug/api.py` (new route, after `queue()`)
- Test: `api/tests/test_api.py` (append)

**Interfaces:**
- Consumes: `_rows_to_items`, `_queue_response` from Task 1.
- Produces: `GET /v1/showcase/queue?threshold=<float|omitted>` returning the same `QueueResponse` model as `/v1/queue`. Task 3 fetches it.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_api.py`:

```python
def test_showcase_queue_404s_when_the_repo_is_unset(tmp_path, monkeypatch):
    """Unset means 'this deployment has no showcase', not 'show everything'."""
    _db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_SHOWCASE_REPO", raising=False)
    client = TestClient(app)
    assert client.get("/v1/showcase/queue").status_code == 404


def test_showcase_queue_serves_without_any_token(tmp_path, monkeypatch):
    """The whole point: doug-web must be able to call this holding no
    credential at all."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    client = TestClient(app)
    assert client.get("/v1/showcase/queue").status_code == 200


def test_showcase_queue_does_not_depend_on_the_operator_token(tmp_path, monkeypatch):
    """/v1/queue 503s when DOUG_API_TOKEN is unset (api.py:317-322). If this
    endpoint inherited that, removing the secret from doug-web would take the
    public pages down — the exact failure this endpoint exists to prevent."""
    _db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    client = TestClient(app)
    assert client.get("/v1/showcase/queue").status_code == 200


def test_showcase_queue_ignores_a_caller_supplied_repo(tmp_path, monkeypatch):
    """It is pinned by deployment, never selected by the caller. A ?repo=
    that changed the answer would make a public endpoint a cross-tenant
    selector."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    client = TestClient(app)
    pinned = client.get("/v1/showcase/queue").json()
    attempted = client.get("/v1/showcase/queue?repo=someone/private").json()
    assert pinned == attempted


def test_showcase_queue_serves_only_the_pinned_repos_rows(tmp_path, monkeypatch):
    """Two repos in the ledger, one pinned: the other must not appear."""
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_SHOWCASE_REPO", "drewjst/doug")
    calls: list[dict] = []
    real = store.latest_reviews

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(store, "latest_reviews", spy)
    client = TestClient(app)
    assert client.get("/v1/showcase/queue").status_code == 200
    assert calls == [{"repo": "drewjst/doug"}]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/test_api.py -k showcase -v
```

Expected: all five FAIL with 404 (no such route).

- [ ] **Step 3: Implement the route**

Add to `api/doug/api.py`, immediately after the `queue()` function:

```python
@app.get("/v1/showcase/queue")
def showcase_queue(threshold: float | None = None) -> QueueResponse:
    """The public Doug-on-Doug queue, pinned to one repo by deployment.

    Unauthenticated by design (ADR-0008) and therefore NOT a selector: the
    repo comes from DOUG_SHOWCASE_REPO and never from the caller, so no
    request can widen it. It deliberately does NOT read DOUG_API_TOKEN —
    that independence is the whole reason this route exists, so doug-web
    can serve the public pages while holding no operator credential.

    Unset variable and no ledger both 404 rather than falling back to the
    bundled fixture: serving invented PRs from a PUBLIC url would be a
    confident false claim, and web/ already has its own labelled fixture
    fallback for the unreachable-API case.
    """
    showcase = os.environ.get("DOUG_SHOWCASE_REPO")
    if not showcase or not store.enabled():
        raise _not_found()
    return _queue_response(
        _rows_to_items(store.latest_reviews(repo=showcase)), threshold
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_api.py -k showcase -v
```

Expected: 5 passed.

- [ ] **Step 5: Run the full suite and lint**

```bash
uv run pytest -q 2>&1 | tail -3 && uv run ruff check .
```

Expected: baseline + 5, all passing; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "feat: serve a public showcase queue pinned by deployment"
```

---

### Task 3: Point the public pages at the showcase endpoint

Both public pages fetch through `web/lib/api.ts`. **`web/app/page.tsx:73` calls `getQueue()` too** — repointing only `/queue` would leave the landing page silently serving the bundled fixture once the token is removed, and `promote_if_healthy` smokes `/` (`gcp.sh:466`) which returns 200 either way, so the deploy gate would not catch it.

The shape guard moves to its own module. `api.ts` imports `queue-fixture.json`, and importing that module from a node test trips ESM's JSON import attributes — extracting the guard sidesteps it entirely and gives the file one responsibility. **Do not merge it back into `api.ts`.**

**Files:**
- Create: `web/lib/queue-shape.ts`
- Create: `web/lib/queue-shape.test.mjs`
- Modify: `web/lib/api.ts` (types + `isQueueResponse` move out; `fetchQueue` repointed; `QUEUE_REPO` deleted)
- Modify: `web/package.json:10` (test runner)

**Interfaces:**
- Consumes: `GET /v1/showcase/queue` from Task 2.
- Produces: `web/lib/queue-shape.ts` exporting `isQueueResponse(data: unknown): data is QueueResponse` plus the types `Band`, `PRMetadata`, `Reason`, `Verdict`, `QueueItem`, `QueueResponse`. `web/lib/api.ts` keeps exporting `API_URL`, `getQueue`, and re-exports the types so the pages' imports are unchanged.

- [ ] **Step 1: Fix the test runner**

`web/package.json:10` currently globs `lib/*.test.mjs`. When nothing matches, the shell passes the literal pattern through and node's `--test` treats it as a no-op — **exit 0 with zero tests**, a green check asserting nothing. Point it at the directory instead, which cannot silently match nothing:

```json
    "test": "node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test --experimental-strip-types lib/"
```

- [ ] **Step 2: Write the failing test**

Create `web/lib/queue-shape.test.mjs`, following the recovered idiom of the deleted `comparison.test.mjs` (direct `.ts` import):

```js
import assert from "node:assert/strict";
import test from "node:test";

import { isQueueResponse } from "./queue-shape.ts";

function body(overrides = {}) {
  return {
    summary: { open: 1, flagged: 1, cleared: 0, threshold: 0.3 },
    items: [
      {
        pr: { number: 7, files: ["a.py"] },
        verdict: { score: 0.9, reasons: [] },
      },
    ],
    ...overrides,
  };
}

test("accepts a body carrying every field the pages dereference", () => {
  assert.equal(isQueueResponse(body()), true);
});

test("rejects a summary missing a counter", () => {
  assert.equal(
    isQueueResponse(body({ summary: { open: 1, flagged: 1, cleared: 0 } })),
    false,
  );
});

test("rejects an item whose verdict lost its reasons array", () => {
  assert.equal(
    isQueueResponse(
      body({ items: [{ pr: { number: 7, files: [] }, verdict: { score: 0.1 } }] }),
    ),
    false,
  );
});

test("rejects null, which JSON.parse produces for a bare null body", () => {
  assert.equal(isQueueResponse(null), false);
});
```

- [ ] **Step 3: Run it to verify it fails**

From `web/`:

```bash
npm test
```

Expected: FAIL — `./queue-shape.ts` cannot be resolved, because the module does not exist yet. If it reports `tests 0` and exits 0, the runner fix in Step 1 did not take — stop and fix it before continuing.

- [ ] **Step 4: Create the shape module**

Create `web/lib/queue-shape.ts` by moving lines 3–42 and 52–82 of `web/lib/api.ts` verbatim, adding `export` to the guard:

```ts
export type Band = "cleared" | "flagged";

export interface PRMetadata {
  number: number;
  title: string;
  author: string;
  author_type: "human" | "agent";
  additions: number;
  deletions: number;
  files: string[];
  approvals: number;
  approval_latency_s: number | null;
  days_since_last_human_commit: number | null;
  url: string | null;
}

export interface Reason {
  rule: string;
  label: string;
  weight: number;
  /** Reader findings only; deterministic rules carry a weight instead. */
  severity?: string | null;
}

export interface Verdict {
  score: number;
  band: Band;
  threshold: number;
  reasons: Reason[];
}

export interface QueueItem {
  pr: PRMetadata;
  verdict: Verdict;
}

export interface QueueResponse {
  summary: { open: number; flagged: number; cleared: number; threshold: number };
  items: QueueItem[];
}

/** Structural check on exactly the fields the pages dereference. A 200
 *  with a drifted body used to be cast straight through and threw deep in
 *  server rendering — with no boundary to catch it, one renamed backend
 *  field took both routes down to Next's unstyled default error page. A
 *  body that fails this check is treated like an unreachable API.
 *
 *  This lives apart from api.ts on purpose: api.ts imports a JSON fixture,
 *  and a node test importing that module trips ESM's JSON import
 *  attributes. Keep it standalone so it stays directly testable. */
export function isQueueResponse(data: unknown): data is QueueResponse {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  const s = d.summary as Record<string, unknown> | null | undefined;
  if (
    typeof s !== "object" || s === null ||
    typeof s.open !== "number" || typeof s.flagged !== "number" ||
    typeof s.cleared !== "number" || typeof s.threshold !== "number"
  )
    return false;
  if (!Array.isArray(d.items)) return false;
  return (d.items as unknown[]).every((it) => {
    if (typeof it !== "object" || it === null) return false;
    const { pr, verdict } = it as { pr?: unknown; verdict?: unknown };
    if (typeof pr !== "object" || pr === null) return false;
    if (typeof verdict !== "object" || verdict === null) return false;
    const p = pr as Record<string, unknown>;
    const v = verdict as Record<string, unknown>;
    return (
      typeof p.number === "number" &&
      Array.isArray(p.files) &&
      typeof v.score === "number" &&
      Array.isArray(v.reasons)
    );
  });
}
```

- [ ] **Step 5: Run the test to verify it passes**

From `web/`:

```bash
npm test
```

Expected: 4 passing.

- [ ] **Step 6: Repoint `api.ts` and delete the token header**

In `web/lib/api.ts`: delete the type declarations and `isQueueResponse` (now in `queue-shape.ts`), delete the `QUEUE_REPO` constant, and replace `fetchQueue`'s request. The file's top becomes:

```ts
import fixture from "./queue-fixture.json";
import { isQueueResponse } from "./queue-shape";

export type {
  Band,
  PRMetadata,
  Reason,
  Verdict,
  QueueItem,
  QueueResponse,
} from "./queue-shape";
import type { QueueResponse } from "./queue-shape";

export const API_URL = process.env.DOUG_API_URL ?? "http://localhost:8000";

type QueueResult = { queue: QueueResponse; source: "live" | "fixture" };
```

and `fetchQueue`'s call becomes:

```ts
    // The public showcase queue: unauthenticated, and pinned to one repo by
    // the API's own DOUG_SHOWCASE_REPO. doug-web sends no credential and no
    // repo selector, which is what lets this service hold no operator token.
    const res = await fetch(`${API_URL}/v1/showcase/queue`, {
      cache: "no-store",
      // 5s, up from 2s: a cold doug-web calling a cold doug-api overran 2s
      // and served the fixture to the first visitor after every
      // scale-to-zero. A rare slow first paint beats invented PRs.
      signal: AbortSignal.timeout(5000),
    });
```

Leave the fixture fallback, the micro-cache, and `getQueue`'s signature untouched — both pages call `getQueue()` and must keep working unchanged.

- [ ] **Step 7: Verify no token or repo selector survives in web/**

```bash
grep -rn "DOUG_API_TOKEN\|DOUG_QUEUE_REPO\|X-Doug-Token\|v1/queue" web/lib web/app
```

Expected: **no output.** Any hit is a missed call site.

- [ ] **Step 8: Run web checks**

```bash
npm test && npm run lint && npm run build
```

Expected: 4 tests passing, lint clean, build succeeds.

- [ ] **Step 9: Commit**

```bash
git add web/lib/queue-shape.ts web/lib/queue-shape.test.mjs web/lib/api.ts web/package.json
git commit -m "feat: serve both public pages from the unauthenticated showcase queue"
```

---

### Task 4: Put the web tests in CI, and prove the job is not vacuous

The `web` job already exists at `.github/workflows/ci.yml:31-45` — it runs `npm ci`, `npm run lint`, `npm run build`. **The missing line is `npm test`, not the job.** Console got exactly this treatment because it holds the operator credential (`ci.yml:66`).

**Files:**
- Modify: `.github/workflows/ci.yml:43-45`

**Interfaces:**
- Consumes: the working `npm test` from Task 3.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the step**

In `.github/workflows/ci.yml`, in the `web` job, after `- run: npm run lint`:

```yaml
      - run: npm test
```

Keep `- run: npm run build` last.

- [ ] **Step 2: Prove the job would actually fail**

A green check that cannot go red is worse than no check. Temporarily break one assertion in `web/lib/queue-shape.test.mjs` — change `assert.equal(isQueueResponse(body()), true);` to `false` — then from `web/`:

```bash
npm test; echo "exit=$?"
```

Expected: a failing test and **`exit=1`**. If it prints `exit=0`, the runner is still vacuous — go back to Task 3 Step 1.

- [ ] **Step 3: Restore the assertion and confirm green**

Change it back to `true`, then:

```bash
npm test; echo "exit=$?"
```

Expected: 4 passing, `exit=0`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run the web tests, verified non-vacuous"
```

---

### Task 5: Drop the operator credential from doug-web

`api/tests/test_deploy_gcp.py:49` currently **pins the binding this task removes** — it asserts `doug-api-token` appears after the `doug-web-sa` create. That test must be inverted, not deleted: the pin is what stops a future edit quietly reintroducing the credential.

**Files:**
- Modify: `api/deploy/gcp.sh:48` (`QUEUE_REPO` → `SHOWCASE_REPO`), `:165-171` (binding), `:378` (api env), `:450` (stale comment), `:458-459` (web env + secrets)
- Modify: `api/tests/test_deploy_gcp.py:49-63`

**Interfaces:**
- Consumes: `DOUG_SHOWCASE_REPO` from Task 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

Replace `test_setup_creates_doug_web_sa_and_binds_the_api_token` in `api/tests/test_deploy_gcp.py` with:

```python
def test_setup_creates_doug_web_sa_and_binds_it_no_secrets():
    """doug-web serves only the unauthenticated showcase queue, so it needs
    NO secret at all. This pin is what stops the operator token being
    quietly reintroduced to a --allow-unauthenticated service."""
    setup = _function_body("setup")
    assert "service-accounts create doug-web-sa" in setup
    after_web = setup.split("service-accounts create doug-web-sa", 1)[1].split(
        "service-accounts create doug-console-sa", 1
    )[0]
    assert "doug-api-token" not in after_web
    assert "secretAccessor" not in after_web
    assert "doug-database-url" not in after_web
    assert "doug-github-app-key" not in after_web
    assert "doug-anthropic-key" not in after_web
    assert "roles/cloudsql.client" not in after_web


def test_web_deploy_carries_no_secrets():
    """The deploy flag is a second, independent way the credential could
    return — setup()'s binding and web()'s --set-secrets must BOTH stay
    clean or the service holds a token again."""
    body = _function_body("web")
    assert "--set-secrets" not in body
    assert "DOUG_API_TOKEN" not in body


def test_api_deploy_carries_the_showcase_repo():
    """The public pages 404 without it, so it belongs on doug-api and
    nowhere else."""
    assert "DOUG_SHOWCASE_REPO=" in _function_body("api")
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/test_deploy_gcp.py -v -k "doug_web_sa or carries_no_secrets or showcase_repo"
```

Expected: all three FAIL.

- [ ] **Step 3: Edit `gcp.sh`**

Four edits:

1. Line 48 — rename the variable:

```bash
SHOWCASE_REPO=${SHOWCASE_REPO:-drewjst/doug}
```

2. Lines 165-171 — delete the whole `if gcloud secrets describe doug-api-token ... fi` block that binds `secretAccessor` to `$WEB_SA`, and replace it with:

```bash
  # doug-web binds NO secret. It serves only /v1/showcase/queue, which is
  # unauthenticated and pinned by the API's own DOUG_SHOWCASE_REPO. A
  # --allow-unauthenticated service holding an operator credential was the
  # hole this closed; test_deploy_gcp.py pins it shut.
```

3. Line 378 — add `DOUG_SHOWCASE_REPO` to the api deploy's `--set-env-vars`, appending `,DOUG_SHOWCASE_REPO=$SHOWCASE_REPO` to the existing value.

4. Lines 450, 458-459 — fix the stale comment (there is no dashboard; `web/app/` holds only `page.tsx`, `queue/page.tsx`, `error.tsx`, `loading.tsx`, `layout.tsx`), drop `DOUG_QUEUE_REPO`, and delete the `--set-secrets` line entirely:

```bash
  # DOUG_API_URL is read at request time by the public pages' server
  # components. No secrets: see setup()'s doug-web-sa block.
  # --service-account: deploying without it silently falls back to the
  # default compute SA (roles/editor).
  gcloud run deploy "$WEB_SERVICE" \
    --source ../web \
    --project "$PROJECT" --region "$REGION" \
    --allow-unauthenticated \
    --service-account "doug-web-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-env-vars "DOUG_API_URL=$(api_url)" \
    --memory 512Mi --cpu 1 --max-instances 2 --timeout 60 \
    $traffic_flags
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_deploy_gcp.py -v
```

Expected: all pass, including the untouched `test_web_deploy_runs_as_doug_web_sa` and `test_web_deploy_is_still_the_only_public_service`.

- [ ] **Step 5: Check the script still parses, then run everything**

```bash
bash -n deploy/gcp.sh && uv run pytest -q 2>&1 | tail -3 && uv run ruff check .
```

Expected: no syntax error; full suite green; ruff clean.

- [ ] **Step 6: Verify no stale references survive**

```bash
grep -n "QUEUE_REPO" deploy/gcp.sh ../web -r
```

Expected: **no output.**

- [ ] **Step 7: Commit**

```bash
git add api/deploy/gcp.sh api/tests/test_deploy_gcp.py
git commit -m "fix: doug-web holds no operator credential"
```

---

### Task 6: Record the compute-SA revocation as a real runbook step

`gcp.sh:172-178` carries a comment telling a human to remove the default compute SA's leftover `secretAccessor` on `doug-api-token`. **It has never been executed**, and a comment inside a script nobody reads on deploy is not a task anyone will do. It also cannot be run from here — it needs `gcloud` against prod.

Removing the token from `doug-web` does not close this: the default compute SA may still be able to read the secret.

**Files:**
- Modify: `api/deploy/gcp.sh:172-178` (remove the orphaned comment)
- Modify: `docs/OPERATIONS.md` (add the step)

**Interfaces:**
- Consumes: nothing. Produces: nothing.

- [ ] **Step 1: Add the runbook entry**

`docs/OPERATIONS.md` today has exactly one top-level section, `## Tenant API keys` (line 3), with `###` subsections. This is not about tenant keys, so it gets a **new `##` section appended at the end of the file**, matching the surrounding prose style (imperative, commands indented as code blocks, explicit about what has and has not been run):

```markdown
## Service identities

### Revoke the default compute SA's access to `doug-api-token` (one-off, NOT YET RUN)

Legacy from the Task-10 era: the default compute service account may still
hold `secretmanager.secretAccessor` on `doug-api-token`. `doug-api` and
`doug-console` run as their own service accounts and `doug-web` now holds no
secret at all, so nothing should depend on this binding — but it has never
been verified or removed.

Check first, and only remove if it is present:

    PROJECT=doug-prod0
    PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
    gcloud secrets get-iam-policy doug-api-token --project "$PROJECT" \
      --format=json | grep -A3 "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

If it appears:

    gcloud secrets remove-iam-policy-binding doug-api-token --project "$PROJECT" \
      --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
      --role=roles/secretmanager.secretAccessor

Then redeploy nothing — no service uses that identity. Confirm `doug-api`
and `doug-console` still serve, since they are the only readers left.
```

- [ ] **Step 2: Remove the orphaned comment from `gcp.sh`**

Delete the `# setup does not revoke the default compute SA's leftover accessor…` comment block and its four commented command lines at `gcp.sh:172-178`, replacing them with a pointer:

```bash
  # The default compute SA may still hold a leftover accessor on
  # doug-api-token. It is a one-off operator action, not a setup step —
  # see docs/OPERATIONS.md, "Revoke the default compute SA's access".
```

- [ ] **Step 3: Verify the script and suite**

```bash
bash -n deploy/gcp.sh && uv run pytest -q 2>&1 | tail -3
```

Expected: no syntax error; full suite green.

- [ ] **Step 4: Commit**

```bash
git add api/deploy/gcp.sh docs/OPERATIONS.md
git commit -m "docs: make the compute-SA revocation a runbook step, not a comment"
```

---

## Phase exit criteria

Verify all of these before calling Phase 0 done:

- [ ] `uv run pytest` green from `api/`; `uv run ruff check .` clean.
- [ ] `npm test`, `npm run lint`, `npm run build` all pass from `web/`, and `npm test` reports **more than zero tests**.
- [ ] `grep -rn "DOUG_API_TOKEN\|X-Doug-Token" web/` returns nothing.
- [ ] `_function_body("web")` in `gcp.sh` contains no `--set-secrets`.
- [ ] `bash -n deploy/gcp.sh` clean.
- [ ] Locally, with `DOUG_SHOWCASE_REPO` set and no `DOUG_API_TOKEN` in the web environment, **both `/` and `/queue` render live data** — not the "bundled fixture" badge. This is the check `promote_if_healthy` cannot make for you, because `/` returns 200 either way.

## Known follow-ups, deliberately out of scope

- **`doug-console` still holds `DOUG_API_TOKEN`** (`gcp.sh:484`). It is IAM-gated and not public, so it is a different risk. Phase 0's exit means "the *public* service holds no operator credential," not "the token is gone from the fleet."
- **`console/package.json:10` has the same silently-vacuous test glob** as web's did. Console's tests do currently match, so it is green for real today — but the same trap is armed there. Not fixed here; recorded so it is not rediscovered as a surprise.
- Phase 0's "holds no credential" is momentary by design: Phase 1 adds `WORKOS_API_KEY`, `WORKOS_CLIENT_ID` and `WORKOS_COOKIE_PASSWORD` to `doug-web`, with new Secret Manager entries and new bindings.
