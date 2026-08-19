# Per-repo "needs you" threshold — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a tenant set, per repository, the 0–1 line above which Doug says "needs you", applied to every future review by both scorers, stamped on the verdict, and shown honestly on the dashboard.

**Architecture:** A nullable `installation_repos.needs_you_threshold` column read by the worker at scoring time and threaded through `review.score_one()` to both scorers (reader gets `round(t*100)`); a session-authenticated `PATCH /v1/sessions/repositories/{github_repo_id}` behind a new `settings:write` scope; the connections read carries per-repo values plus both process defaults; the dashboard's Repositories view edits it. Forward-only — the ledger keeps each verdict's stamped line. Two PRs: web response-guard tolerance ships first because the API deploys before web.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy Core / pydantic v2 / pytest (`cd api && uv run pytest`); Next.js (App Router, server actions) / TypeScript / `node --test` (`npm test --workspace=web`).

**Spec:** `docs/superpowers/specs/2026-08-18-per-repo-needs-you-threshold-design.md`

## Global Constraints

- Range `0 ≤ x ≤ 1`, endpoints included; stored rounded to 2 decimals; strings/bools/NaN/Infinity rejected with 422; `{}` (key absent) is 422, `null` clears.
- Reader receives `round(t * 100)`, never `t * 100`.
- The write is keyed on `(installation_id, github_repo_id)` with `installation_id` from the session context, WHERE `state = 'active'`; **never** bumps `updated_at`.
- Unset displays as two numbers: `default · 0.30 deep read / 0.62 fallback` (`default_needs_you_threshold: {reader, fallback}`); never one.
- New session scope string is exactly `settings:write`.
- Gear button text becomes `preview at…`; the row setting is labelled `flag line`; a contract test asserts they differ.
- Check run risk line gains exactly: `The flag line is set per repository on the Doug dashboard.`
- Migration version = `migrations.MIGRATIONS[-1][0] + 1` at implementation time (11 today; MT3's spec also claims 11 — whoever lands second renumbers).
- Deploy order: **PR 1 = Task 1 only** (web guards tolerate the new keys). **PR 2 = Tasks 2–11.**
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Console (`console/`) is untouched; `lib/console-lockstep.test.mjs` must stay green.

---

## PR 1 — web tolerance (ships and deploys before anything else)

### Task 1: Connections response guards accept the two new keys as optional

**Files:**
- Modify: `web/lib/session-api.ts:192-232` (`repository`, `isConnectionsResponse`)
- Test: `web/lib/session-api.test.mjs`

**Interfaces:**
- Produces: `repository()` accepts `{id, full_name}` and `{id, full_name, needs_you_threshold: number|null}`; `isConnectionsResponse()` accepts `{connections}` and `{connections, default_needs_you_threshold: {reader:number, fallback:number}}`. Types unchanged in this PR (fields are not yet read).

- [ ] **Step 1: Write the failing test** — append to `web/lib/session-api.test.mjs`:

```js
test("the connections validator accepts bodies with and without the per-repo flag line fields", async () => {
  // DEPLOY-ORDER SAFETY, same reason as the reauthorize_required test above:
  // the API goes live first, so web must accept the new keys before the API
  // emits them, or every dashboard load fails between the two promotions.
  const { getConnections } = await import("./session-api.ts");
  const withFields = {
    connections: [{
      ...validConnections.connections[0],
      repositories: [
        { id: 11, full_name: "acme/one", needs_you_threshold: 0.9 },
        { id: 12, full_name: "acme/two", needs_you_threshold: null },
      ],
    }],
    default_needs_you_threshold: { reader: 0.3, fallback: 0.62 },
  };
  for (const [label, body] of [["old api", validConnections], ["new api", withFields]]) {
    const oldFetch = globalThis.fetch;
    globalThis.fetch = async () => new Response(JSON.stringify(body), { status: 200 });
    try {
      const result = await getConnections("token");
      assert.equal(result.connections.length, 1, label);
    } finally {
      globalThis.fetch = oldFetch;
    }
  }
  // Still exact on everything else: an unknown key is still rejected.
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ ...validConnections, surprise: 1 }), { status: 200 });
  try {
    await assert.rejects(() => getConnections("token"));
  } finally {
    globalThis.fetch = oldFetch;
  }
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test --experimental-strip-types lib/session-api.test.mjs`
Expected: FAIL — the "new api" body throws `Doug could not load your connected spaces.`

- [ ] **Step 3: Implement** — in `web/lib/session-api.ts` add a helper next to `exact()` and use it:

```ts
/** `exact` plus a set of keys that MAY be present. Used only where the API
 *  is about to start emitting a field and this build must not reject it
 *  before it learns to read it (deploy.yml promotes API before web). */
function exactWithOptional(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[],
): boolean {
  const actual = Object.keys(value);
  const allowed = new Set([...required, ...optional]);
  return required.every((key) => key in value) && actual.every((key) => allowed.has(key));
}

function repository(value: unknown): value is { id: number; full_name: string } {
  return (
    record(value) &&
    exactWithOptional(value, ["id", "full_name"], ["needs_you_threshold"]) &&
    Number.isInteger(value.id) &&
    typeof value.full_name === "string" &&
    (!("needs_you_threshold" in value) || nullableNumber(value.needs_you_threshold))
  );
}

function isConnectionsResponse(value: unknown): value is ConnectionsResponse {
  return (
    record(value) &&
    exactWithOptional(value, ["connections"], ["default_needs_you_threshold"]) &&
    Array.isArray(value.connections) &&
    value.connections.every(connection)
  );
}
```

(`nullableNumber` already exists in the file — it is used by `runSummary`.)

- [ ] **Step 4: Run web tests** — `cd web && npm test` → PASS (including `console-lockstep`).

- [ ] **Step 5: Commit and open PR 1**

```bash
git add web/lib/session-api.ts web/lib/session-api.test.mjs
git commit -m "fix(web): accept per-repo flag line fields in the connections body ahead of the API

Deploy order: API promotes before web (deploy.yml:162). The exact() guards
would reject the new keys and fail every dashboard load until web caught
up, so web learns to tolerate them first, in its own PR.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

PR title: `fix(web): tolerate per-repo flag line fields in the connections body`. **Merge and confirm deployed before PR 2 merges.**

---

## PR 2 — the feature

### Task 2: Column + migration (two homes)

**Files:**
- Modify: `api/doug/store.py:221-235` (`installation_repos` Table)
- Modify: `api/doug/migrations.py` (append version)
- Test: `api/tests/test_migrations.py`

**Interfaces:**
- Produces: column `installation_repos.needs_you_threshold` (Float, nullable).

- [ ] **Step 1: Failing test** — in `api/tests/test_migrations.py`, next to `M10_COLUMNS`:

```python
M11_COLUMNS = {"installation_repos": {"needs_you_threshold"}}


def test_migration_011_declares_the_same_columns_as_their_tables(tmp_path):
    """Two homes (migrations.py docstring): the Table gets a fresh database
    the column; the migration gets production the same column. A drift
    between them is a green suite and a broken production write."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl11.db")
    store.metadata.create_all(engine)
    assert _statements_by_table(dict(migrations.MIGRATIONS)[11]) == M11_COLUMNS
    for table, columns in M11_COLUMNS.items():
        assert columns <= _columns(engine, table)
```

If `migrations.MIGRATIONS[-1][0]` is no longer 10 when you get here (MT3 landed), use the next free number everywhere in this task and rename the test accordingly.

- [ ] **Step 2: Run** — `cd api && uv run pytest tests/test_migrations.py -q` → FAIL (`KeyError: 11`).

- [ ] **Step 3: Implement**

`api/doug/store.py`, inside the `installation_repos` Table after `updated_at`:

```python
    # The repo's own needs-you line, 0..1, or NULL to inherit the process
    # defaults (DOUG_THRESHOLD / DOUG_READER_THRESHOLD). Read by the worker
    # at scoring time and stamped on the verdict; forward-only by design
    # (spec 2026-08-18-per-repo-needs-you-threshold). Written ONLY by
    # set_repo_threshold — set_installation_repos must never touch it.
    Column("needs_you_threshold", Float, nullable=True),
```

`api/doug/migrations.py`, append to `MIGRATIONS`:

```python
    (
        11,
        (
            # Per-repo needs-you line (spec 2026-08-18). Nullable: NULL is
            # "inherit the defaults", which is every existing row.
            "ALTER TABLE installation_repos ADD COLUMN needs_you_threshold FLOAT",
        ),
    ),
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_migrations.py tests/test_store.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/doug/store.py api/doug/migrations.py api/tests/test_migrations.py
git commit -m "feat(store): installation_repos.needs_you_threshold, both homes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 3: `store.repo_threshold` / `store.set_repo_threshold`

**Files:**
- Modify: `api/doug/store.py` (after `set_installation_repos`, ~line 1105)
- Test: `api/tests/test_store.py`

**Interfaces:**
- Produces:
  - `repo_threshold(installation_id: int, github_repo_id: int) -> float | None`
  - `set_repo_threshold(installation_id: int, github_repo_id: int, value: float | None) -> bool` (True iff an active row was updated; stores `round(value, 2)`; never touches `updated_at`).

- [ ] **Step 1: Failing tests** — append to `api/tests/test_store.py` (use the module's existing sqlite fixture pattern; `_db(tmp_path, monkeypatch)` or the local equivalent that points `store` at a temp DB):

```python
def test_repo_threshold_round_trips_and_is_none_when_unset_or_unknown(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.upsert_installation(101, "acme", "Organization", "active")
    store.set_installation_repos(101, [(11, "acme/one")], replace=False)

    assert store.repo_threshold(101, 11) is None
    assert store.set_repo_threshold(101, 11, 0.9) is True
    assert store.repo_threshold(101, 11) == 0.9
    assert store.repo_threshold(101, 999) is None
    assert store.set_repo_threshold(101, 11, None) is True
    assert store.repo_threshold(101, 11) is None


def test_set_repo_threshold_rounds_to_two_decimals(tmp_path, monkeypatch):
    """Verdict.score is 2dp (scoring.py) and the reader conversion is
    round(t*100): a stored 0.6249 would compare in a way no surface shows."""
    _db(tmp_path, monkeypatch)
    store.upsert_installation(101, "acme", "Organization", "active")
    store.set_installation_repos(101, [(11, "acme/one")], replace=False)
    store.set_repo_threshold(101, 11, 0.6249)
    assert store.repo_threshold(101, 11) == 0.62


def test_set_repo_threshold_touches_only_the_callers_row_and_only_active_ones(tmp_path, monkeypatch):
    """A transferred repo legitimately has rows under two installations
    (repo_id_for). One tenant's PATCH must not reach the other's row, and a
    removed row is not writable (rowcount 0 -> 404 at the API)."""
    _db(tmp_path, monkeypatch)
    store.upsert_installation(101, "acme", "Organization", "active")
    store.upsert_installation(202, "other", "Organization", "active")
    store.set_installation_repos(101, [(11, "acme/one")], replace=False)
    store.set_installation_repos(202, [(11, "other/one")], replace=False)

    assert store.set_repo_threshold(101, 11, 0.9) is True
    assert store.repo_threshold(202, 11) is None

    store.set_installation_repos(101, [], replace=True)  # 11 -> removed
    assert store.set_repo_threshold(101, 11, 0.5) is False
    assert store.repo_threshold(101, 11) == 0.9  # still readable, unchanged


def test_webhook_resync_preserves_the_line_and_the_patch_never_bumps_updated_at(tmp_path, monkeypatch):
    """Webhooks must not erase tenant configuration; and updated_at is the
    tiebreaker repo_id_for uses to pick between duplicate registrations, so
    a settings write must not be a lever over it."""
    _db(tmp_path, monkeypatch)
    store.upsert_installation(101, "acme", "Organization", "active")
    store.set_installation_repos(101, [(11, "acme/one")], replace=False)
    with store._get_engine().connect() as conn:
        before = conn.execute(
            select(store.installation_repos.c.updated_at)
            .where(store.installation_repos.c.github_repo_id == 11)
        ).scalar_one()

    store.set_repo_threshold(101, 11, 0.9)
    with store._get_engine().connect() as conn:
        after = conn.execute(
            select(store.installation_repos.c.updated_at)
            .where(store.installation_repos.c.github_repo_id == 11)
        ).scalar_one()
    assert after == before

    store.set_installation_repos(101, [], replace=True)          # removed
    store.set_installation_repos(101, [(11, "acme/one")], replace=False)  # re-added
    assert store.repo_threshold(101, 11) == 0.9
```

(`select` is already imported in `test_store.py`; if not, `from sqlalchemy import select`.)

- [ ] **Step 2: Run** — `uv run pytest tests/test_store.py -k repo_threshold -q` → FAIL (`AttributeError`).

- [ ] **Step 3: Implement** — `api/doug/store.py`, after `set_installation_repos`:

```python
def repo_threshold(installation_id: int, github_repo_id: int) -> float | None:
    """The repo's own needs-you line, or None to inherit the process defaults.

    Read regardless of `state`: the worker calls this with the job's own
    installation_id at scoring time, and a repo removed mid-job still
    scores against the line it was configured with.
    """
    engine = _get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        value = conn.execute(
            select(installation_repos.c.needs_you_threshold).where(
                installation_repos.c.installation_id == installation_id,
                installation_repos.c.github_repo_id == github_repo_id,
            )
        ).scalar_one_or_none()
    return None if value is None else float(value)


def set_repo_threshold(
    installation_id: int, github_repo_id: int, value: float | None
) -> bool:
    """Write the line on the ACTIVE row for (installation_id, github_repo_id).

    Returns False when no such active row exists — the API turns that into
    404. Keyed on both columns, never github_repo_id alone: a transferred
    repo has rows under two installations. Writes ONLY this column —
    `updated_at` means "registration/state changed" and is repo_id_for's
    tiebreaker between duplicate registrations; a settings write must not
    move it. Rounds to 2dp to match Verdict.score and to make the reader's
    round(t*100) an exact integer.
    """
    engine = _get_engine()
    if engine is None:
        return False
    stored = None if value is None else round(float(value), 2)
    with engine.begin() as conn:
        result = conn.execute(
            update(installation_repos)
            .where(
                installation_repos.c.installation_id == installation_id,
                installation_repos.c.github_repo_id == github_repo_id,
                installation_repos.c.state == "active",
            )
            .values(needs_you_threshold=stored)
        )
    return result.rowcount == 1
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_store.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/doug/store.py api/tests/test_store.py
git commit -m "feat(store): repo_threshold / set_repo_threshold keyed on the installation row

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 4: Thread `threshold` through `review.score_one` to all four exits; reader gets `round(t*100)`

**Files:**
- Modify: `api/doug/review.py:303-390`
- Test: `api/tests/test_review.py`, `api/tests/test_reader.py`

**Interfaces:**
- Produces: `review.score_one(meta, diff, *, scope, threshold: float | None = None, resolve_file=None, resolve_schema=None)`. Unchanged return shape.
- Consumes: `reader.verdict_from_reader(rv, threshold: float | None)` (0–100 units), `scoring.score(pr, threshold: float | None)` (0–1 units) — both existing.

- [ ] **Step 1: Failing tests**

`api/tests/test_reader.py` (find an existing `ReaderVerdict` construction helper in the file and reuse it — e.g. whatever `verdict_from_reader` tests already build):

```python
def test_verdict_from_reader_on_the_line_needs_you_at_every_two_decimal_stop():
    """0.55*100 == 55.00000000000001; with an integer risk_score and >=, a PR
    sitting exactly on the line would clear while the check run printed
    'Risk 0.55 against a flag line of 0.55'. The caller passes round(t*100);
    this pins the two sides agree at the stops that would otherwise fail."""
    for line in (0.07, 0.14, 0.28, 0.55, 0.56):
        points = round(line * 100)
        on = reader.verdict_from_reader(_rv(risk_score=points), threshold=points)
        under = reader.verdict_from_reader(_rv(risk_score=points - 1), threshold=points)
        assert on.band is Band.FLAGGED, line
        assert under.band is Band.CLEARED, line
        assert on.threshold == line, line
```

`api/tests/test_review.py`:

```python
def test_score_one_threads_the_repo_line_to_every_exit(monkeypatch):
    """A capped or broken read on a 0.9 repo must not band at 0.62 because
    the fallback forgot the argument — that would make the tenant's line
    fiction on exactly the reviews they can't see happening."""
    meta = _pr_with_deterministic_score_0_71()  # migration + sensitive path etc.

    monkeypatch.setattr(reader, "enabled", lambda: False)
    tier, v, _, _ = review.score_one(meta, "+ x", scope=reader.SENTINEL_SCOPE, threshold=0.9)
    assert (tier, v.band, v.threshold) == ("deterministic", Band.CLEARED, 0.9)
    _, v0, _, _ = review.score_one(meta, "+ x", scope=reader.SENTINEL_SCOPE)
    assert v0.band is Band.FLAGGED  # unset: env default 0.62

    monkeypatch.setattr(reader, "enabled", lambda: True)
    monkeypatch.setattr(reader, "read_diff", lambda *a, **k: (_ for _ in ()).throw(reader.ReaderError("down")))
    tier, v, _, _ = review.score_one(meta, "+ x", scope=reader.SENTINEL_SCOPE, threshold=0.9)
    assert (tier, v.band, v.threshold) == ("deterministic", Band.CLEARED, 0.9)
    assert any(r.rule == "reader-unavailable" for r in v.reasons)

    monkeypatch.setattr(reader, "read_diff", lambda *a, **k: (_ for _ in ()).throw(reader.SpendCapExceeded("cap")))
    tier, v, _, _ = review.score_one(meta, "+ x", scope=reader.SENTINEL_SCOPE, threshold=0.9)
    assert (tier, v.band, v.threshold) == ("deterministic", Band.CLEARED, 0.9)

    monkeypatch.setattr(reader, "read_diff", lambda *a, **k: _rv(risk_score=55))
    tier, v, _, _ = review.score_one(meta, "+ x", scope=reader.SENTINEL_SCOPE, threshold=0.55)
    assert (tier, v.band, v.threshold) == ("reader", Band.FLAGGED, 0.55)
```

Build `_pr_with_deterministic_score_0_71()` from an existing `PRMetadata` fixture in `test_review.py`/`test_scoring.py` whose rules sum to 0.67 (e.g. `boundary-plus-migration` 0.35 + `dep-change-no-test-delta` 0.25 + base 0.04 = 0.64 — pick any combination from `scoring._rules` that lands between 0.62 and 0.90 and assert its exact `score` in the test so the intent is visible). `_rv` is whatever helper `test_reader.py` uses to build a `ReaderVerdict`; if `test_review.py` lacks one, import it or construct `reader.ReaderVerdict(risk_score=..., findings=[], ...)` per its model. Check `reader.SpendCapExceeded`/`ReaderError` constructor signatures before using them.

- [ ] **Step 2: Run** — `uv run pytest tests/test_review.py -k threads tests/test_reader.py -k on_the_line -q` → FAIL (`TypeError: unexpected keyword 'threshold'`).

- [ ] **Step 3: Implement** — `api/doug/review.py`:

```python
def score_one(
    meta: PRMetadata,
    diff: str,
    *,
    scope: str,
    threshold: float | None = None,
    resolve_file: settle.ResolveFile | None = None,
    resolve_schema: settle.ResolveSchema | None = None,
):
    """... (existing docstring) ...

    `threshold` is the repo's own needs-you line in 0..1 (store.repo_threshold),
    or None for the process defaults. It reaches EVERY exit below — the reader
    (as round(t*100): 0.55*100 is 55.00000000000001 and risk_score is an
    integer compared with >=) and all three deterministic fallbacks — because
    a capped read on a 0.9 repo must not quietly band at 0.62.
    """
    reader_line = None if threshold is None else round(threshold * 100)
    if reader.enabled():
        try:
            ...
            verdict = reader.verdict_from_reader(rv, threshold=reader_line)
            ...
        except reader.SpendCapExceeded as e:
            verdict = score(meta, threshold=threshold)
            ...
        except reader.ReaderError as e:
            verdict = score(meta, threshold=threshold)
            ...
    return "deterministic", score(meta, threshold=threshold), None, None
```

(Replace the three bare `score(meta)` calls and the one `verdict_from_reader(rv)` call; nothing else moves.)

- [ ] **Step 4: Run** — `uv run pytest tests/test_review.py tests/test_reader.py tests/test_scoring.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/doug/review.py api/tests/test_review.py api/tests/test_reader.py
git commit -m "feat(review): score_one takes the repo line and threads it to every exit

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 5: Worker reads the line at scoring time and logs `line`/`line_source`

**Files:**
- Modify: `api/doug/worker.py:250-255`, `:327-332`
- Test: `api/tests/test_worker.py` (fakes at `:144` and `:1012` need `threshold=None` in their signatures)

**Interfaces:**
- Consumes: `store.repo_threshold`, `review.score_one(..., threshold=...)`.

- [ ] **Step 1: Failing test** — in `api/tests/test_worker.py`, using the file's existing `_env`/`_gh`/job helpers (read the top of the file for how a job is seeded and how `score_one` is faked):

```python
def test_worker_passes_the_repos_line_into_scoring_and_logs_its_source(tmp_path, monkeypatch, capsys):
    """The setting must reach the scoring seam; and the log must say whether
    a stamped 0.62 was the repo's own line or the default, which the row
    alone cannot tell once the tenant clears it."""
    seen: list = []

    def _score_one(meta, diff, *, scope, threshold=None, resolve_file=None, resolve_schema=None):
        seen.append(threshold)
        v = VERDICT.model_copy(deep=True)
        if threshold is not None:
            v.threshold = threshold
        return ("deterministic", v, None, None)

    # ... seed installation 101 / repo 11 / one job exactly as the nearest
    # existing process_job test does, then:
    store.set_repo_threshold(101, 11, 0.9)
    monkeypatch.setattr(review, "score_one", _score_one)
    _run_one_job()  # the file's helper for draining/processing one job
    assert seen == [0.9]
    err = capsys.readouterr().err
    assert "line=0.90 line_source=repo" in err

    seen.clear()
    store.set_repo_threshold(101, 11, None)
    # re-seed a job for a new head_sha, run again
    assert seen == [None]
    assert "line_source=default" in capsys.readouterr().err
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_worker.py -q` → FAIL (new test), and possibly the two existing fakes fail with `TypeError` once Step 3 lands — fix their signatures to accept `threshold=None`.

- [ ] **Step 3: Implement** — `api/doug/worker.py`:

```python
    scope = reader.installation_scope(job["installation_id"])
    # The repo's own needs-you line, read INSIDE the job at scoring time (not
    # at admission) so the line in effect when Doug scores is the one stamped.
    threshold = store.repo_threshold(job["installation_id"], job["github_repo_id"])
    ...
        tier, verdict, rv, cov = review.score_one(
            meta,
            diff,
            scope=scope,
            threshold=threshold,
            resolve_file=resolve,
            resolve_schema=store.columns_of,
        )
```

and the success line:

```python
    print(
        f"doug: reviewed {job['repo_full_name']}#{job['pr_number']}"
        f"@{job['head_sha'][:12]} (paid read) "
        f"tier={tier} band={verdict.band.value} "
        f"risk={verdict.score:.2f} line={verdict.threshold:.2f} "
        f"line_source={'repo' if threshold is not None else 'default'} "
        f"verdict={verdict_id}",
        file=sys.stderr,
    )
```

Update the two `score_one` fakes in `test_worker.py` (`:144`, `:1012`) to accept `threshold=None`.

- [ ] **Step 4: Run** — `uv run pytest tests/test_worker.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/doug/worker.py api/tests/test_worker.py
git commit -m "feat(worker): score against the repo's own line and log its source

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 6: `settings:write` scope + `PATCH /v1/sessions/repositories/{github_repo_id}`

**Files:**
- Modify: `api/doug/session_auth.py:27` (`SESSION_SCOPES`)
- Modify: `api/doug/api.py` (after `_session_read_context` ~`:1181`; new endpoint after `session_run_detail`)
- Test: `api/tests/test_api.py`, `api/tests/test_session_auth.py`

**Interfaces:**
- Produces: `PATCH /v1/sessions/repositories/{github_repo_id}` body `{"needs_you_threshold": number|null}` → `200 {"needs_you_threshold": stored|null}`; `401` bad/unscoped session; `404` repo not in live scope or not active; `422` invalid body; `503` no ledger.
- Consumes: `store.set_repo_threshold`, `store.repo_threshold`.

- [ ] **Step 1: Failing tests** — `api/tests/test_api.py`, after the `/v1/sessions/runs` tests (reuse `_session_scope`):

```python
def _patch_line(headers, repo_id, body):
    return TestClient(app).patch(
        f"/v1/sessions/repositories/{repo_id}", headers=headers, json=body
    )


def test_session_can_set_and_clear_a_repos_flag_line_inside_its_live_scope(
    tmp_path, monkeypatch, capsys
):
    headers = _session_scope(tmp_path, monkeypatch, repos=(11, 12), claim=(11,))

    r = _patch_line(headers, 11, {"needs_you_threshold": 0.9})
    assert r.status_code == 200 and r.json() == {"needs_you_threshold": 0.9}
    assert store.repo_threshold(101, 11) == 0.9
    assert "needs_you_threshold installation=101 repo=11 None->0.9 by sub=user_01ABC" in capsys.readouterr().err

    r = _patch_line(headers, 11, {"needs_you_threshold": 0.6249})
    assert r.json() == {"needs_you_threshold": 0.62}  # the STORED value comes back

    r = _patch_line(headers, 11, {"needs_you_threshold": None})
    assert r.status_code == 200 and r.json() == {"needs_you_threshold": None}
    assert store.repo_threshold(101, 11) is None


def test_flag_line_write_fails_closed_outside_scope_and_on_bad_bodies(tmp_path, monkeypatch):
    """404 not 403 for a repo the session cannot see (do not confirm it
    exists); 422 for anything that is not a JSON number in 0..1 or null —
    '{}' would otherwise silently clear, and '62' is someone typing a
    percentage."""
    headers = _session_scope(tmp_path, monkeypatch, repos=(11, 12), claim=(11,))
    assert _patch_line(headers, 12, {"needs_you_threshold": 0.5}).status_code == 404  # live but not claimed
    assert _patch_line(headers, 999, {"needs_you_threshold": 0.5}).status_code == 404
    for bad in (1.5, -0.1, "0.9", "62", True, float("nan"), float("inf")):
        assert _patch_line(headers, 11, {"needs_you_threshold": bad}).status_code == 422, bad
    assert _patch_line(headers, 11, {}).status_code == 422
    assert store.repo_threshold(101, 11) is None
    # ints at the endpoints are numbers, not strings — accepted.
    assert _patch_line(headers, 11, {"needs_you_threshold": 1}).status_code == 200


def test_flag_line_write_refuses_tenant_api_keys_and_orgless_sessions(tmp_path, monkeypatch):
    _session_scope(tmp_path, monkeypatch)
    orgless = _session()  # no org_id → resolve_session is None
    assert _patch_line(orgless, 11, {"needs_you_threshold": 0.5}).status_code == 401
    # A minted tenant key is a TokenContext, never a SessionContext — this
    # route must not use the dual-context resolution shape.
    key_headers = {"Authorization": f"Bearer {_mint_key_for(101, [11])}"}  # use the file's existing minting helper
    assert _patch_line(key_headers, 11, {"needs_you_threshold": 0.5}).status_code == 401
```

(Use whichever helper `test_api.py` already has for minting a tenant key — grep `mint` in the file. `float("nan")` via `json=` will serialize as `NaN`, which the endpoint must reject; if `TestClient` refuses to serialize it, send `content='{"needs_you_threshold": NaN}'` with a JSON content-type instead.)

`api/tests/test_session_auth.py`:

```python
def test_session_scopes_include_the_settings_write_scope():
    """The PATCH on a repo's flag line is gated on this exact string; a
    session that resolves gets it, a minted tenant key never does."""
    assert "settings:write" in session_auth.SESSION_SCOPES
    assert "settings:write" not in tenancy.mint_key.__defaults__ if False else True  # replaced below
```

Replace that last line with a real assertion against however `mint_key`'s scopes are defined (`tenancy.py:389` — likely a module constant like `KEY_SCOPES`); assert `"settings:write"` is not in it.

- [ ] **Step 2: Run** — `uv run pytest tests/test_api.py -k flag_line tests/test_session_auth.py -k settings_write -q` → FAIL (405/404 and the scope assertion).

- [ ] **Step 3: Implement**

`api/doug/session_auth.py`:

```python
SESSION_SCOPES: tuple[str, ...] = ("queue:read", "receipt:read", "settings:write")
```

`api/doug/api.py`, after `_session_read_context`:

```python
def _session_write_context(authorization: str) -> tenancy.SessionContext:
    """A session allowed to change per-repo settings. Same resolver as reads
    (org-bound, live-scoped, fails closed on stale entitlement) — the scope
    string is what makes a write route greppable and keeps a read-only
    context from ever satisfying it."""
    return _session_read_context(authorization, "settings:write")


class RepositorySettingsPatch(BaseModel):
    # Required (no default): `{}` must be a 422, not a silent clear.
    # strict: "0.9", "62" and true are refused rather than coerced.
    needs_you_threshold: float | None = Field(
        ..., strict=True, allow_inf_nan=False, ge=0, le=1
    )


class RepositorySettings(BaseModel):
    needs_you_threshold: float | None


@app.patch("/v1/sessions/repositories/{github_repo_id}")
def set_repository_flag_line(
    github_repo_id: int,
    body: RepositorySettingsPatch,
    authorization: str = Header(""),
) -> RepositorySettings:
    """Set (or clear, with null) the repo's needs-you line. Forward-only:
    verdicts already scored keep the line they were scored against.

    installation_id comes from the session, never the request; the write is
    keyed on (installation_id, github_repo_id, state='active'), so another
    tenant's row under the same github_repo_id is unreachable and a removed
    repo is 404 like one that never existed.
    """
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")
    ctx = _session_write_context(authorization)
    if github_repo_id not in ctx.repo_ids:
        raise _not_found()
    before = store.repo_threshold(ctx.installation_id, github_repo_id)
    if not store.set_repo_threshold(ctx.installation_id, github_repo_id, body.needs_you_threshold):
        raise _not_found()
    after = store.repo_threshold(ctx.installation_id, github_repo_id)
    sub = session_auth.verify_session_claims(authorization).get("sub")
    print(
        f"doug: needs_you_threshold installation={ctx.installation_id} "
        f"repo={github_repo_id} {before}->{after} by sub={sub}",
        file=sys.stderr,
    )
    return RepositorySettings(needs_you_threshold=after)
```

(`_not_found()` exists — it is what `session_runs` raises. `verify_session_claims` is already used by bind; if calling it a second time is undesirable, have `_session_write_context` return `(ctx, sub)` — but keep the audit line.)

- [ ] **Step 4: Run** — `uv run pytest tests/test_api.py tests/test_session_auth.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/doug/session_auth.py api/doug/api.py api/tests/test_api.py api/tests/test_session_auth.py
git commit -m "feat(api): PATCH /v1/sessions/repositories/{id} sets a repo's flag line behind settings:write

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 7: Connections read carries per-repo lines and both defaults

**Files:**
- Modify: `api/doug/store.py:3189-3255` (`session_connections_for`)
- Modify: `api/doug/api.py:1877-1940` (`session_connections`)
- Test: `api/tests/test_api.py`

**Interfaces:**
- Produces: `repositories[]` entries are `{id, full_name, needs_you_threshold: float|null}`; response gains `default_needs_you_threshold: {"reader": reader.reader_threshold()/100, "fallback": default_threshold()}`.

- [ ] **Step 1: Failing test** — `api/tests/test_api.py`, near the existing connections tests:

```python
def test_connections_carry_each_repos_flag_line_and_both_process_defaults(tmp_path, monkeypatch):
    """Production runs the reader, so the unset line on most verdicts is
    0.30, not 0.62 — printing one 'default' number is the lie
    _banding_threshold was built to end. Both are sent; the web prints both."""
    headers = _session_scope(tmp_path, monkeypatch, repos=(11, 12), claim=(11, 12))
    monkeypatch.setenv("DOUG_THRESHOLD", "0.62")
    monkeypatch.setenv("DOUG_READER_THRESHOLD", "30")
    store.set_repo_threshold(101, 11, 0.9)

    body = TestClient(app).get("/v1/sessions/connections", headers=headers).json()

    assert body["default_needs_you_threshold"] == {"reader": 0.3, "fallback": 0.62}
    repos = {r["id"]: r for r in body["connections"][0]["repositories"]}
    assert repos[11] == {"id": 11, "full_name": "acme/repo11", "needs_you_threshold": 0.9}
    assert repos[12] == {"id": 12, "full_name": "acme/repo12", "needs_you_threshold": None}
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_api.py -k both_process_defaults -q` → FAIL.

- [ ] **Step 3: Implement**

`store.session_connections_for`: add `installation_repos.c.needs_you_threshold` to the `select(...)` and build

```python
            connection["repositories"].append(
                {
                    "id": int(repo_id),
                    "full_name": row["full_name"],
                    "needs_you_threshold": (
                        None if row["needs_you_threshold"] is None
                        else float(row["needs_you_threshold"])
                    ),
                }
            )
```

`api.session_connections`: `repositories: row["repositories"]` already passes the dicts through; add to the returned dict:

```python
    return {
        "connections": connections,
        # Both process defaults, per spec D4: the reader's line is what most
        # unset verdicts are actually scored against in production; the
        # deterministic one applies only on fallback. One number would lie.
        "default_needs_you_threshold": {
            "reader": reader.reader_threshold() / 100,
            "fallback": default_threshold(),
        },
    }
```

(`reader` and `default_threshold` are already imported in `api.py`.) Existing connections tests that assert the whole body with `==` need the new key added.

- [ ] **Step 4: Run** — `uv run pytest tests/test_api.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/doug/store.py api/doug/api.py api/tests/test_api.py
git commit -m "feat(api): connections carry per-repo flag lines and both defaults

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 8: Check-run risk line names where the line is set

**Files:**
- Modify: `api/doug/check_run.py:143`
- Test: `api/tests/test_check_run.py:335` and any byte-locked fixture that contains "against a flag line of"

- [ ] **Step 1: Failing test** — update the byte-locked expectation(s): the risk line becomes

```python
    risk_line = "Risk 0.62 against a flag line of 0.30. The flag line is set per repository on the Doug dashboard."
```

Run `rg -n "flag line of" api/tests` and update every occurrence, plus any fixture files under `api/tests/fixtures` that embed the summary.

- [ ] **Step 2: Run** — `uv run pytest tests/test_check_run.py -q` → FAIL.

- [ ] **Step 3: Implement** — `api/doug/check_run.py`:

```python
        f"Risk {verdict.score:.2f} against a flag line of {verdict.threshold:.2f}. "
        "The flag line is set per repository on the Doug dashboard.",
```

(Static, because provenance is not in `Verdict` and the sentence is always true once this ships.)

- [ ] **Step 4: Run** — `uv run pytest tests/test_check_run.py tests/test_worker.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add api/doug/check_run.py api/tests
git commit -m "feat(check-run): say the flag line is a per-repository setting

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 9: Web client — types + `setRepositoryThreshold`

**Files:**
- Modify: `web/lib/session-api.ts` (types at `:22-33`; new function after `bindInstallation`)
- Test: `web/lib/session-api.test.mjs`

**Interfaces:**
- Produces:
  - `RepositoryConnection.repositories: Array<{ id: number; full_name: string; needs_you_threshold: number | null }>`
  - `ConnectionsResponse = { connections: RepositoryConnection[]; default_needs_you_threshold: { reader: number; fallback: number } }`
  - `setRepositoryThreshold(accessToken: string, githubRepoId: number, value: number | null): Promise<number | null>` — PATCH, returns the stored value; throws `SessionApiError` on non-200 (message carries `status` so the action can map 401).

- [ ] **Step 1: Failing test** — append to `web/lib/session-api.test.mjs`:

```js
test("setRepositoryThreshold PATCHes a JSON number or null, never a string, and returns the stored value", async () => {
  const { setRepositoryThreshold } = await import("./session-api.ts");
  const calls = [];
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ needs_you_threshold: 0.62 }), { status: 200 });
  };
  try {
    const stored = await setRepositoryThreshold("token", 11, 0.6249);
    assert.equal(stored, 0.62);
    assert.equal(calls[0].url, `${process.env.DOUG_SESSION_API_URL ?? "http://localhost:8000"}/v1/sessions/repositories/11`);
    assert.equal(calls[0].options.method, "PATCH");
    assert.deepEqual(JSON.parse(calls[0].options.body), { needs_you_threshold: 0.6249 });
    await setRepositoryThreshold("token", 11, null);
    assert.deepEqual(JSON.parse(calls[1].options.body), { needs_you_threshold: null });
    // Out-of-range never leaves the client.
    await assert.rejects(() => setRepositoryThreshold("token", 11, 1.5));
    await assert.rejects(() => setRepositoryThreshold("token", 11, Number.NaN));
    assert.equal(calls.length, 2);
  } finally {
    globalThis.fetch = oldFetch;
  }
});
```

(Check how the file's first test derives the base URL — `SESSION_API_URL` — and mirror it rather than the env fallback above if it differs.)

- [ ] **Step 2: Run** — web tests → FAIL (`setRepositoryThreshold` not exported).

- [ ] **Step 3: Implement** — `web/lib/session-api.ts`:

```ts
export type RepositoryConnection = {
  ...
  repositories: Array<{ id: number; full_name: string; needs_you_threshold: number | null }>;
};

export type ConnectionsResponse = {
  connections: RepositoryConnection[];
  /** Both process defaults, because production scores most PRs with the
   *  reader (0.30) and only falls back to the deterministic line (0.62). An
   *  unset repo is shown as BOTH numbers, never one. */
  default_needs_you_threshold: { reader: number; fallback: number };
};
```

Tighten the Task-1 guards now that both sides emit: `repository()` requires `needs_you_threshold` (`exact(value, ["id","full_name","needs_you_threshold"])` + `nullableNumber`), and `isConnectionsResponse()` requires `default_needs_you_threshold` with two finite numbers. Update `validConnections` in the test file to the new shape (the "old api" tolerance test from Task 1 is now obsolete — replace it with one that asserts the *new* required shape and that an unknown key still rejects). Then:

```ts
export async function setRepositoryThreshold(
  accessToken: string,
  githubRepoId: number,
  value: number | null,
): Promise<number | null> {
  const message = "Doug could not save that flag line.";
  if (!Number.isSafeInteger(githubRepoId) || githubRepoId <= 0) throw new SessionApiError(message);
  if (value !== null && !(Number.isFinite(value) && value >= 0 && value <= 1)) {
    throw new SessionApiError(message);
  }
  let response: Response;
  try {
    response = await fetch(`${SESSION_API_URL}/v1/sessions/repositories/${githubRepoId}`, {
      method: "PATCH",
      cache: "no-store",
      headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({ needs_you_threshold: value }),
      signal: AbortSignal.timeout(SESSION_FETCH_TIMEOUT_MS),
    });
  } catch {
    throw new SessionApiError(message);
  }
  if (response.status !== 200) throw new SessionApiError(message, response.status);
  const body: unknown = await response.json().catch(() => null);
  if (!record(body) || !exact(body, ["needs_you_threshold"]) || !nullableNumber(body.needs_you_threshold)) {
    throw new SessionApiError(message);
  }
  return body.needs_you_threshold as number | null;
}
```

- [ ] **Step 4: Run** — `cd web && npm test && npx tsc --noEmit` → PASS.

- [ ] **Step 5: Commit**

```bash
git add web/lib/session-api.ts web/lib/session-api.test.mjs
git commit -m "feat(web): session client reads flag lines and PATCHes setRepositoryThreshold

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 10: Dashboard — rename the gear, add the "flag line" column + control + server action

**Files:**
- Modify: `web/components/threshold-gear.tsx:52` (button text)
- Create: `web/components/flag-line-control.tsx`
- Modify: `web/app/dashboard/actions.ts` (add `setFlagLineAction`)
- Modify: `web/app/dashboard/page.tsx` (`REPO_COLUMNS` `:838`, `RepositoryTable` `:861`, call site `:1229`/repositories view)
- Modify: `web/lib/dashboard-model.ts` (add `parseGithubRepoId`, `parseFlagLine`)
- Test: `web/lib/dashboard-contract.test.mjs`, `web/lib/dashboard-model.test.mjs`

**Interfaces:**
- Produces: `setFlagLineAction(formData: FormData): Promise<void>` reading `github_repo_id` and `needs_you_threshold` (empty string = clear); `parseGithubRepoId(v: FormDataEntryValue | null): number | null`; `parseFlagLine(v: FormDataEntryValue | null): number | null | undefined` (undefined = invalid, null = clear).
- Consumes: `setRepositoryThreshold`, `getConnections`, `frontDoor` (existing in `dashboard-model.ts`).

- [ ] **Step 1: Failing tests**

`web/lib/dashboard-model.test.mjs`:

```js
test("parseFlagLine: 0..1 numbers, '' clears, everything else is invalid", async () => {
  const { parseFlagLine } = await import("./dashboard-model.ts");
  assert.equal(parseFlagLine("0.9"), 0.9);
  assert.equal(parseFlagLine("0"), 0);
  assert.equal(parseFlagLine("1"), 1);
  assert.equal(parseFlagLine(""), null);
  for (const bad of ["62", "1.5", "-0.1", "abc", "0x1", " ", null]) {
    assert.equal(parseFlagLine(bad), undefined, String(bad));
  }
});
```

`web/lib/dashboard-contract.test.mjs` (follow the file's existing pattern of reading source with `readFile`):

```js
test("the preview gear and the per-repo flag line setting are never called the same thing", async () => {
  const gear = await readFile(new URL("../components/threshold-gear.tsx", import.meta.url), "utf8");
  const control = await readFile(new URL("../components/flag-line-control.tsx", import.meta.url), "utf8");
  assert.match(gear, />\s*preview at…\s*</);
  assert.equal(gear.includes("needs-you line"), false, "the gear no longer claims to be the line");
  assert.match(control, /flag line/);
  assert.match(control, /Applies to reviews from now on/);
  assert.match(control, /open PRs keep their check until a new commit/);
  assert.match(control, /0\.30 on deep reads and 0\.62 when the reader didn't run/);
});

test("setFlagLineAction is a server action wired to the repositories table", async () => {
  const actions = await readFile(new URL("../app/dashboard/actions.ts", import.meta.url), "utf8");
  const page = await readFile(new URL("../app/dashboard/page.tsx", import.meta.url), "utf8");
  assert.match(actions, /^"use server";/);
  assert.match(actions, /export async function setFlagLineAction/);
  assert.equal(actions.includes("export async function GET"), false);
  assert.match(page, /FlagLineControl/);
});
```

- [ ] **Step 2: Run** — web tests → FAIL.

- [ ] **Step 3: Implement**

`web/components/threshold-gear.tsx:52`: replace the text node `needs-you line` with `preview at…` and the `aria-label` with `"Preview the ledger at a different line"`. Nothing else in the component changes (its popover header already says "Show needs-you at").

`web/lib/dashboard-model.ts`:

```ts
export function parseGithubRepoId(value: FormDataEntryValue | null): number | null {
  if (typeof value !== "string" || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/** '' → null (clear). A 0..1 decimal → number. Anything else → undefined
 *  (invalid; the action refuses). Same grammar as parseThresholdLens so
 *  "62" (a percentage) fails closed instead of flagging nothing. */
export function parseFlagLine(value: FormDataEntryValue | null): number | null | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  if (trimmed === "") return null;
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return undefined;
  const n = Number(trimmed);
  return Number.isFinite(n) && n >= 0 && n <= 1 ? n : undefined;
}
```

`web/app/dashboard/actions.ts`:

```ts
import { revalidatePath } from "next/cache";
import { frontDoor, parseFlagLine, parseGithubRepoId, ... } from "@/lib/dashboard-model";
import { SessionApiError, getConnections, setRepositoryThreshold, ... } from "@/lib/session-api";

const FLAG_LINE_ERROR = "Doug could not save that flag line.";
const FLAG_LINE_REAUTH = "Your session's repository access has aged out — sign in again to change settings.";

export async function setFlagLineAction(formData: FormData): Promise<void> {
  const repoId = parseGithubRepoId(formData.get("github_repo_id"));
  const line = parseFlagLine(formData.get("needs_you_threshold"));
  if (repoId === null || line === undefined) throw new Error(FLAG_LINE_ERROR);

  const auth = await withAuth();
  if (!auth.user || !auth.accessToken) throw new Error(FLAG_LINE_ERROR);

  // The API is authoritative; this pre-check only makes the failure legible
  // when the id belongs to a connection other than the selected one.
  const { connections } = await getConnections(auth.accessToken);
  const door = frontDoor(connections, auth.organizationId ?? null);
  if (!door.current?.repositories.some((r) => r.id === repoId)) throw new Error(FLAG_LINE_ERROR);

  try {
    await setRepositoryThreshold(auth.accessToken, repoId, line);
  } catch (error) {
    if (error instanceof SessionApiError && error.status === 401) throw new Error(FLAG_LINE_REAUTH);
    throw new Error(FLAG_LINE_ERROR);
  }
  revalidatePath("/dashboard");
}
```

(Check `SessionApiError`'s field name for the status — read its class in `session-api.ts`; and how `frontDoor` is exported / what it takes, at `dashboard-model.ts:192`.)

`web/components/flag-line-control.tsx` (server-rendered form; no client JS needed):

```tsx
import { setFlagLineAction } from "@/app/dashboard/actions";

/** The per-repository FLAG LINE — Doug's setting, not the preview gear.
 *  Forward-only: verdicts already scored keep the line they were scored
 *  against, and the copy says so where the change is made. Unset prints
 *  BOTH defaults, because production scores with the reader (0.30) and
 *  falls back to the deterministic line (0.62); one number would lie. */
export function FlagLineControl({
  githubRepoId,
  value,
  defaults,
}: {
  githubRepoId: number;
  value: number | null;
  defaults: { reader: number; fallback: number };
}) {
  const shown =
    value === null
      ? `default · ${defaults.reader.toFixed(2)} deep read / ${defaults.fallback.toFixed(2)} fallback`
      : value.toFixed(2);
  return (
    <details className="group">
      <summary className="mono cursor-pointer list-none text-[12px] text-muted-foreground hover:text-foreground" aria-label="flag line">
        {shown}
      </summary>
      <form action={setFlagLineAction} className="mt-1 flex flex-col gap-1">
        <input type="hidden" name="github_repo_id" value={githubRepoId} />
        <label className="mono text-[10.5px] uppercase tracking-[.08em] text-muted-foreground">
          flag line
          <input
            name="needs_you_threshold"
            type="number"
            min={0}
            max={1}
            step={0.01}
            defaultValue={value ?? ""}
            list={`flag-line-marks-${githubRepoId}`}
            className="mono ml-2 h-[26px] w-[72px] rounded-[4px] border border-border bg-card px-1.5 text-[12px] text-foreground"
          />
          <datalist id={`flag-line-marks-${githubRepoId}`}>
            <option value={defaults.reader} label="deep read default" />
            <option value={defaults.fallback} label="fallback default" />
          </datalist>
        </label>
        <p className="text-[10.5px] text-muted-foreground">
          One line for both scorers. Unset, Doug uses {defaults.reader.toFixed(2)} on deep reads and {defaults.fallback.toFixed(2)} when the reader didn&apos;t run.
          Applies to reviews from now on — past verdicts keep the line they were scored against, and open PRs keep their check until a new commit.
          {value !== null && value >= 0.9 && " Close to flag-nothing on the fallback scorer."}
        </p>
        <p className="text-[10.5px] text-muted-foreground">
          This is Doug&apos;s line for new reviews — the preview gear above only re-bands what&apos;s on screen.
        </p>
        <div className="flex gap-2">
          <button type="submit" className="mono h-[26px] rounded-[4px] border border-border px-2 text-[11px]">save</button>
          <button type="submit" name="needs_you_threshold" value="" className="mono h-[26px] rounded-[4px] border border-border px-2 text-[11px] text-muted-foreground">reset to default</button>
        </div>
      </form>
    </details>
  );
}
```

(Keep the copy strings exactly as the contract test greps them. The literal `0.30 on deep reads and 0.62 when the reader didn't run` in the test matches because `toFixed(2)` of the defaults renders those numbers; if the test should be independent of env, grep the template pieces instead — `on deep reads and` / `when the reader didn` — the intent is the same.)

`web/app/dashboard/page.tsx`:
- `REPO_COLUMNS`: add `{ label: "flag line", cls: "w-[150px]" }` after `needs you`.
- `RepositoryTable` gains props `settings: Map<string, { id: number; needs_you_threshold: number | null }>` and `defaults: { reader: number; fallback: number }`; renders, per row:

```tsx
            <TableCell className={TD}>
              {settings.has(row.repo) ? (
                <FlagLineControl
                  githubRepoId={settings.get(row.repo)!.id}
                  value={settings.get(row.repo)!.needs_you_threshold}
                  defaults={defaults}
                />
              ) : (
                <span className="mono text-[12px] text-[var(--dim)]">—</span>
              )}
            </TableCell>
```

("not connected" rows have no `installation_repos` row and get no control.)
- At the call site, build `settings` from `door.current.repositories` (`new Map(repos.map(r => [r.full_name, { id: r.id, needs_you_threshold: r.needs_you_threshold }]))`) and pass `defaults={connectionsResponse.default_needs_you_threshold}` — the page already has the connections response from `getConnections(accessToken)` at `:1164`; keep the whole response, not just `connections`.

- [ ] **Step 4: Run** — `cd web && npm test && npx tsc --noEmit && npm run lint` → PASS. Then `/run` the web app against a local API with one repo set and eyeball the Repositories view: gear reads "preview at…", the column reads "flag line", unset shows both numbers.

- [ ] **Step 5: Commit**

```bash
git add web/components/threshold-gear.tsx web/components/flag-line-control.tsx web/app/dashboard/actions.ts web/app/dashboard/page.tsx web/lib/dashboard-model.ts web/lib/dashboard-contract.test.mjs web/lib/dashboard-model.test.mjs
git commit -m "feat(web): per-repository flag line on the Repositories view; gear is now 'preview at…'

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 11: Rewrite the lens header, write ADR-0013, close the handoff

**Files:**
- Modify: `web/lib/threshold-lens.ts:1-36` (header comment)
- Create: `docs/decisions/ADR-0013-needs-you-line-is-a-per-repo-setting.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Rewrite the header** of `web/lib/threshold-lens.ts` — replace the paragraph beginning "It is not a setting because it cannot be" with:

```ts
// The needs-you line as a PREVIEW, distinct from the SETTING.
//
// The SETTING is per-repository, forward-only, and lives on
// installation_repos.needs_you_threshold (api/doug/store.py); the worker
// reads it at scoring time, both scorers honour it, and the resolved line
// is stamped on each verdict row (`verdicts.threshold`). Past verdicts keep
// the line they were scored against — see ADR-0013 and the Repositories
// view's "flag line" column.
//
// The LENS here does something else: it re-derives a band from a score Doug
// already recorded, against a line the reader chooses, and says so on
// screen. It never changes what Doug did. (/v1/queue?threshold= is the
// API's equivalent preview.) The two are named differently on purpose —
// "preview at…" on the gear, "flag line" on the setting — and a contract
// test keeps it that way.
```

Keep the rest of the header (the boundary-rewrite rationale) as is.

- [ ] **Step 2: Write the ADR** — `docs/decisions/ADR-0013-needs-you-line-is-a-per-repo-setting.md`:

```markdown
---
title: The needs-you line is a per-repository setting, forward-only, one number for both scorers
status: accepted
date: 2026-08-18
---

## Context

The line above which Doug says "needs you" was process-wide: DOUG_THRESHOLD
(0.62, deterministic scorer) and DOUG_READER_THRESHOLD (30/100, reader).
Production runs the reader, so most verdicts were scored against 0.30 and
only fallbacks against 0.62. A docs-only repo and a Terraform repo have very
different costs for a false "needs you" and shared one line. The dashboard's
threshold lens argued the line "is not a setting because it cannot be" —
true of the wiring, not a constraint. Spec:
docs/superpowers/specs/2026-08-18-per-repo-needs-you-threshold-design.md.

## Decision

- Per-repository: `installation_repos.needs_you_threshold` (0..1, NULL =
  inherit), set via `PATCH /v1/sessions/repositories/{id}` behind the
  `settings:write` session scope, edited on the Repositories view.
- Forward-only: read at scoring time and stamped on the verdict; existing
  verdicts keep their line; open PRs keep their check until a new commit.
- One number for both scorers; the reader receives round(t*100).
- The unset state is displayed as both defaults (0.30 deep read / 0.62
  fallback), never one.
- Authority: any member of the bound WorkOS org whose live entitlement
  reaches the repo. Weaker than key minting (repo admin) and bind
  (installer); accepted because org membership is operator-curated and
  the setting is reversible and audited by the verdicts it produces.
- Two-PR deploy: web response guards tolerate the new fields first, because
  the API is promoted before web.

## Rejected

- Retroactive re-banding of the ledger — the ledger would stop matching
  the check runs posted to GitHub.
- An in-repo config file (`.doug.yml`), or both — a file fetch per review;
  two sources of truth. Can be layered later without moving the column.
- Two knobs (reader / deterministic) — two settings for one question.
- Displaying a single "default" of 0.62 — false in production, and the
  lie `_banding_threshold` was built to end.
- Installer-only writes via `_prove_installer` — a WorkOS read per write
  and policy locked to one person.

## Consequences

- The lens survives as a preview; the gear is "preview at…", the setting is
  the "flag line", and a contract test keeps the names apart.
- Setting one number moves the two scorers in opposite directions from
  their defaults; the control's copy says so.
- `/v1/queue` `summary.threshold` is a mode and can mislead once an
  installation's repos differ; deferred (`?repo=` is exact).
- Uninstall + reinstall yields a new installation and the setting does not
  carry; remove + re-add of a repo under the same installation keeps it.
- Reader-fed: this record is `accepted`, so the reader will flag PRs that
  reintroduce a process-wide-only line or bump `updated_at` from the PATCH.
```

- [ ] **Step 3: HANDOFF.md** — set `State: review`, `Next: open PR 2 against main after PR 1 is merged and deployed; PR body links the spec, the ADR and the review disposition`, and record any decision made during implementation.

- [ ] **Step 4: Full suites** — `make test` (api + console + web) and `make lint` → all PASS; report exact output.

- [ ] **Step 5: Commit**

```bash
git add web/lib/threshold-lens.ts docs/decisions/ADR-0013-needs-you-line-is-a-per-repo-setting.md HANDOFF.md
git commit -m "docs: ADR-0013 the needs-you line is a per-repo setting; lens header says preview

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Then open PR 2 (`feat: per-repository needs-you flag line`) with the spec, ADR, and the three review reports' disposition summarised in the body. Do not merge before PR 1 is deployed.

---

## Self-review

- **Spec coverage:** §3.1 → Task 2/3; §3.2 → Task 4/5 (round, all four exits, log lines); §3.3 → Task 6 (scope, keyed write, strict body, 200 body, audit) and Task 7 (read + both defaults); §3.4 → Task 9/10 (types, PATCH client, gear rename, flag line column/control/copy, server action, contract tests, orphan rows) and Task 11 (lens header, ADR with Rejected); check-run clause → Task 8; §3.6 → PR split, Task 1; §5 tests → each task's Step 1; queue-heuristic deferral, "since" annotation, `threshold_source` column → deliberately not built (spec §3.5).
- **Placeholders:** none; the two "use the file's existing helper" notes name what to look for (`_rv`, `_mint_key_for`, `_run_one_job`) and where.
- **Type consistency:** `repo_threshold`/`set_repo_threshold` (Task 3) match Tasks 5/6/7; `score_one(..., threshold=)` (Task 4) matches Task 5 and its fakes; `setRepositoryThreshold(accessToken, githubRepoId, value)` (Task 9) matches Task 10's action; `default_needs_you_threshold: {reader, fallback}` is the same shape in Tasks 1/7/9/10; the copy strings in Task 10's control match its contract test.
