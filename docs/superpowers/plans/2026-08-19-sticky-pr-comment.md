# Sticky PR Comment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post one App-authored, sticky PR comment per pull request that mirrors the `Doug` check run byte-for-byte inside a small frame, edited in place on every review, opt-out per repository, never a second comment, never a review.

**Architecture:** A new `api/doug/pr_comment.py` (sibling of `check_run.py`) renders `marker + header + <check-run summary verbatim> + footer` and upserts it via a stored comment id (claim-before-create, authorship-matched fallback scan, `seq` guard). The worker calls it from both post sites after `check_run.post`, gated by an active `installation_repos` row with `pr_comment = TRUE` and, for the first release, an installation allowlist. `check_run._oneline` neutralises model-authored mentions/refs/links/HTML-comment openers for BOTH surfaces so byte-identity holds. The PATCH endpoint grows an optional `pr_comment` key with `model_fields_set`-gated writes; the dashboard gets a toggle and a permission-denied banner. Three-stage deploy: **PR A** (web guard tolerance) → **manual App permission** `pull_requests: write` → **PR B** (everything else).

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy Core / pydantic v2 / githubkit / pytest (`cd api && uv run pytest`; `uv run ruff check .`); Next.js App Router / TypeScript / `node --test` (`npm test --workspace=web`, `npx tsc --noEmit`, `npm run lint --workspace=web`).

**Spec:** `docs/superpowers/specs/2026-08-19-sticky-pr-comment-design.md` (D1–D9; D3a staged rollout = yes; D3b never-delete = keep + standing issue)

## Global Constraints

- The comment's middle is `check_run.render()`'s `summary` **byte-for-byte**; the only transform applied to model text happens inside `check_run._oneline` and therefore reaches both surfaces identically.
- Marker is line 1: `<!-- doug:verdict head=<full head_sha> seq=<job id> -->`; match is `body.startswith("<!-- doug:verdict")` **and** `performed_via_github_app.id == app_auth.app_id()`. A human-authored marked comment is never matched or written.
- Upsert order: stored id → update (404 → forget) → bounded list scan (10 pages × 100) with authorship match and `seq` guard → claim row → create. A listing failure or hitting the page bound returns `failed:…` and **never** creates.
- Joins pinned: marker, blank line, header, blank line, summary, **two** newlines, `---`, footer. `SUMMARY_LIMIT + FRAME_MAX <= 65_536` is asserted, never truncated.
- Worker posts only when `store.repo_pr_comment(...)` is True (an **active** row with `pr_comment = TRUE`; absent/removed → False) AND `pr_comment.allowed(job["installation_id"])` (env `DOUG_PR_COMMENT_INSTALLATIONS`, temporary — D3a). Own stderr line `doug: comment <outcome> <repo>#<pr>@<sha12>`; the "reviewed"/"replayed" lines are untouched.
- `target_matches` on the replay path: `pulls.get(...).base.repo.id == job["github_repo_id"]` else `skipped-target`.
- Neutralisation in `_oneline` (zero-width space U+200B after the trigger): `@name` → `@​name`; `#123` / `owner/repo#4` → `#​123`; `<!--` → `<!-​-`; `](` → `]​(`. `_quote` routes through `_oneline`.
- `CLEARED_NOTE` rendered in `check_run.render` when `band == CLEARED`: exactly `Cleared means Doug found nothing it wanted a human to look at; it is not a statement that the change is safe.`
- PATCH body: `needs_you_threshold?: float|None` (strict, 0..1), `pr_comment?: bool` (strict), `extra="forbid"`, `model_validator` rejects empty `model_fields_set` (→ 422 via the global handler); **each store write gated on `"field" in body.model_fields_set`**; response `{"needs_you_threshold": …, "pr_comment": …}`; audit line names only written fields.
- Schema: `installation_repos.pr_comment BOOLEAN NOT NULL` with `server_default=sa.true()` in the Table **and** `DEFAULT TRUE` in the migration; `installations.pr_comment_denied_at TIMESTAMPTZ NULL`; `pr_comments(installation_id BIGINT, github_repo_id BIGINT, pr_number INT, comment_id BIGINT, updated_at TIMESTAMPTZ, UNIQUE(installation_id, github_repo_id, pr_number))`. Migration version = `MIGRATIONS[-1][0] + 1` (12 today).
- `set_installation_repos` never touches `pr_comment`; `set_repo_pr_comment` never bumps `updated_at`.
- Deploy: **PR A = Task 1 only** (merge + confirm web deployed). **Manual step** before PR B deploys: add `pull_requests: write` to the GitHub App in its settings. **PR B = Tasks 2–10**. `deploy.yml` promotes API before web.
- Lines ≤ 100 cols; `uv run ruff check .` clean; web `npm test && npx tsc --noEmit && npm run lint` clean; console untouched.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

## PR A — web tolerance (ships and deploys first)

### Task 1: Web guards tolerate `pr_comment` and a two-key PATCH response

**Files:**
- Modify: `web/lib/session-api.ts` (`repository()` ~:198, `setRepositoryThreshold` response guard ~:434)
- Test: `web/lib/session-api.test.mjs`

**Interfaces:**
- Produces: `repository()` accepts `{id, full_name, needs_you_threshold}` with or without `pr_comment: boolean`; `setRepositoryThreshold`'s response guard accepts `{needs_you_threshold}` with or without `pr_comment: boolean`. No new types yet.

- [ ] **Step 1: Failing test** — append to `web/lib/session-api.test.mjs`:

```js
test("the connections and PATCH guards accept bodies with and without pr_comment (deploy-order safety)", async () => {
  // API promotes before web (deploy.yml); the API will start emitting
  // `pr_comment` on repositories[] and on the PATCH response. Web must accept
  // both shapes before that, or every dashboard load / every flag-line save
  // fails between the two promotions — the #119 lesson, second verse.
  const { getConnections, setRepositoryThreshold } = await import("./session-api.ts?pr-comment-tolerance");
  const withField = {
    ...validConnections,
    connections: [{
      ...validConnections.connections[0],
      repositories: validConnections.connections[0].repositories.map((r, i) => ({ ...r, pr_comment: i === 0 })),
    }],
  };
  for (const [label, body] of [["old", validConnections], ["new", withField]]) {
    const oldFetch = globalThis.fetch;
    globalThis.fetch = async () => new Response(JSON.stringify(body), { status: 200 });
    try { assert.equal((await getConnections("t")).connections.length, 1, label); }
    finally { globalThis.fetch = oldFetch; }
  }
  for (const body of [{ needs_you_threshold: 0.5 }, { needs_you_threshold: 0.5, pr_comment: true }]) {
    const oldFetch = globalThis.fetch;
    globalThis.fetch = async () => new Response(JSON.stringify(body), { status: 200 });
    try { assert.equal(await setRepositoryThreshold("t", 11, 0.5), 0.5); }
    finally { globalThis.fetch = oldFetch; }
  }
  // Unknown keys still reject on both.
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ needs_you_threshold: 0.5, surprise: 1 }), { status: 200 });
  try { await assert.rejects(() => setRepositoryThreshold("t", 11, 0.5)); }
  finally { globalThis.fetch = oldFetch; }
});
```

(Adjust `validConnections` usage to the file's current fixture shape — it already carries `needs_you_threshold` and `default_needs_you_threshold` after #120.)

- [ ] **Step 2: Run** — `cd web && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test --experimental-strip-types lib/session-api.test.mjs` → FAIL on the "new" body and on the two-key PATCH response.

- [ ] **Step 3: Implement** — re-add the helper (it was removed when #120 tightened):

```ts
/** `exact` plus keys that MAY be present. Only used while the API is about
 *  to start emitting a field this build does not read yet (API promotes
 *  before web). Tightened back to `exact` in the feature PR. */
function exactWithOptional(value: Record<string, unknown>, required: readonly string[], optional: readonly string[]): boolean {
  const allowed = new Set([...required, ...optional]);
  return required.every((k) => k in value) && Object.keys(value).every((k) => allowed.has(k));
}
```

In `repository()`: `exactWithOptional(value, ["id","full_name","needs_you_threshold"], ["pr_comment"])` and `(!("pr_comment" in value) || typeof value.pr_comment === "boolean")`. In `setRepositoryThreshold`'s response guard: `exactWithOptional(body, ["needs_you_threshold"], ["pr_comment"])` and the same boolean check.

- [ ] **Step 4: Run** — `cd web && npm test && npx tsc --noEmit && npm run lint` → PASS.

- [ ] **Step 5: Commit, open PR A**

```bash
git add web/lib/session-api.ts web/lib/session-api.test.mjs
git commit -m "fix(web): tolerate pr_comment in connections and the PATCH response ahead of the API

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

PR title: `fix(web): tolerate pr_comment fields ahead of the API`. **Merge and confirm the web revision deployed before PR B merges.**

---

## Manual gate (not a task): App permission

Before PR B deploys: in the GitHub App settings for Doug, set **Pull requests: Read and write**. Installations get a "review new permissions" prompt; until accepted, the comment call 403s and the dashboard banner (Task 8) says so. Record the date in HANDOFF.md and in ADR-0014 (Task 10).

---

## PR B — the feature

### Task 2: Schema — three columns/tables, one migration, two homes

**Files:**
- Modify: `api/doug/store.py` (`installations` Table ~:196, `installation_repos` Table ~:221, new `pr_comments` Table)
- Modify: `api/doug/migrations.py` (append version 12)
- Test: `api/tests/test_migrations.py`, `api/tests/test_store.py`

**Interfaces:**
- Produces: columns/tables per Global Constraints. `sa.true()` is `from sqlalchemy import true` (check the file's import block; `Boolean`, `BigInteger`, `DateTime` already imported).

- [ ] **Step 1: Failing tests** — `api/tests/test_migrations.py`, next to `M11_COLUMNS`:

```python
M12_COLUMNS = {
    "installation_repos": {"pr_comment"},
    "installations": {"pr_comment_denied_at"},
}


def test_migration_012_declares_the_same_columns_as_their_tables(tmp_path):
    """Two homes: the Table gets a fresh database the columns; the migration
    gets production the same columns. pr_comments is a NEW table and so is
    create_all()'s alone — asserted present on a fresh schema below."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl12.db")
    store.metadata.create_all(engine)
    assert _statements_by_table(dict(migrations.MIGRATIONS)[12]) == M12_COLUMNS
    for table, columns in M12_COLUMNS.items():
        assert columns <= _columns(engine, table)
    assert "pr_comments" in inspect(engine).get_table_names()
```

(`_statements_by_table` parses `ALTER TABLE x ADD COLUMN y`; the `CREATE TABLE pr_comments` statement in the migration must be excluded from that parse or the helper extended — read the helper first and choose; say which in the report. `inspect` is `from sqlalchemy import inspect`.)

`api/tests/test_store.py`:

```python
def test_a_new_repo_row_gets_pr_comment_true_from_the_server_default(tmp_path, monkeypatch):
    """set_installation_repos inserts an explicit values dict that omits the
    column; without server_default on the Table home, every repo insert on a
    create_all() schema would raise NOT NULL constraint failed."""
    _db(tmp_path, monkeypatch)
    store.upsert_installation(101, "acme", "Organization", "active")
    store.set_installation_repos(101, [(11, "acme/one")], replace=False)
    with store._get_engine().connect() as conn:
        value = conn.execute(
            select(store.installation_repos.c.pr_comment)
            .where(store.installation_repos.c.github_repo_id == 11)
        ).scalar_one()
    assert value is True or value == 1
```

- [ ] **Step 2: Run** — `cd api && uv run pytest tests/test_migrations.py tests/test_store.py -k "012 or server_default" -q` → FAIL.

- [ ] **Step 3: Implement**

`store.py`, `installation_repos` Table after `needs_you_threshold`:
```python
    # Whether Doug keeps one sticky PR comment mirroring its check run on
    # this repo's PRs (spec 2026-08-19-sticky-pr-comment, D3). server_default
    # is load-bearing: set_installation_repos inserts an explicit values dict
    # that omits this column, so a bare NOT NULL breaks every repo insert on
    # a create_all() schema. Written ONLY by set_repo_pr_comment.
    Column("pr_comment", Boolean, nullable=False, server_default=true()),
```
`installations` Table after `installed_by_github_user_id`:
```python
    # Last time a PR-comment write was refused with 403 (permission not
    # re-accepted, locked conversation, archived repo). Cleared on the next
    # successful create/update. Drives the Repositories-view banner (D8).
    Column("pr_comment_denied_at", DateTime(timezone=True), nullable=True),
```
New Table:
```python
pr_comments = Table(
    "pr_comments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False),
    Column("github_repo_id", BigInteger, nullable=False),
    Column("pr_number", Integer, nullable=False),
    # NULL between claim and create: the row is the claim (D9), the id
    # arrives once create_comment returns.
    Column("comment_id", BigInteger, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("installation_id", "github_repo_id", "pr_number", name="uq_pr_comment"),
)
```
`migrations.py`, append:
```python
    (
        12,
        (
            "ALTER TABLE installation_repos ADD COLUMN pr_comment BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE installations ADD COLUMN pr_comment_denied_at TIMESTAMP",
            "CREATE TABLE IF NOT EXISTS pr_comments ("
            "id INTEGER PRIMARY KEY, installation_id BIGINT NOT NULL, "
            "github_repo_id BIGINT NOT NULL, pr_number INTEGER NOT NULL, "
            "comment_id BIGINT, updated_at TIMESTAMP NOT NULL, "
            "CONSTRAINT uq_pr_comment UNIQUE (installation_id, github_repo_id, pr_number))",
        ),
    ),
```
(Postgres `TIMESTAMP` here must match how version 9/10 wrote timezone-aware columns — copy the exact type token the earlier migrations use for `DateTime(timezone=True)`; `INTEGER PRIMARY KEY` autoincrements on sqlite; on Postgres use the same pattern the file used for any previously created table, or `BIGSERIAL`/`SERIAL` — read the file and match.)

- [ ] **Step 4: Run** — `uv run pytest tests/test_migrations.py tests/test_store.py -q` then `uv run pytest -q` + `uv run ruff check .` → PASS.

- [ ] **Step 5: Commit** — `feat(store): pr_comment setting, denial timestamp, pr_comments claim table — migration 12`.

### Task 3: Store functions

**Files:** Modify `api/doug/store.py` (after `set_repo_threshold`); Test `api/tests/test_store.py`

**Interfaces — Produces:**
```python
def repo_pr_comment(installation_id: int, github_repo_id: int) -> bool            # ACTIVE row with pr_comment true; else False; storage disabled -> False
def set_repo_pr_comment(installation_id: int, github_repo_id: int, value: bool) -> bool   # active row only; writes only that column; rowcount==1
def pr_comment_id(installation_id: int, github_repo_id: int, pr_number: int) -> int | None
def claim_pr_comment(installation_id: int, github_repo_id: int, pr_number: int) -> bool   # INSERT ... ON CONFLICT DO NOTHING; True iff inserted
def set_pr_comment_id(installation_id: int, github_repo_id: int, pr_number: int, comment_id: int) -> None
def forget_pr_comment(installation_id: int, github_repo_id: int, pr_number: int) -> None  # DELETE the row
def mark_pr_comment_denied(installation_id: int, at: datetime | None) -> None
def pr_comment_denied_at(installation_id: int) -> datetime | None
```

- [ ] **Step 1: Failing tests** (`test_store.py`):

```python
def test_repo_pr_comment_is_true_only_for_an_active_row_that_says_so(tmp_path, monkeypatch):
    """D6: absent row -> False (a repo the tenant cannot see on the dashboard
    must not get an un-disableable public comment); removed row -> False;
    new active row -> True by server default; explicit False sticks."""
    _db(tmp_path, monkeypatch)
    store.upsert_installation(101, "acme", "Organization", "active")
    assert store.repo_pr_comment(101, 11) is False
    store.set_installation_repos(101, [(11, "acme/one")], replace=False)
    assert store.repo_pr_comment(101, 11) is True
    assert store.set_repo_pr_comment(101, 11, False) is True
    assert store.repo_pr_comment(101, 11) is False
    store.set_repo_pr_comment(101, 11, True)
    store.set_installation_repos(101, [], replace=True)  # removed
    assert store.repo_pr_comment(101, 11) is False
    assert store.set_repo_pr_comment(101, 11, False) is False


def test_set_repo_pr_comment_keys_on_the_installation_row_and_leaves_updated_at(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    for inst, login in ((101, "acme"), (202, "other")):
        store.upsert_installation(inst, login, "Organization", "active")
        store.set_installation_repos(inst, [(11, f"{login}/one")], replace=False)
    with store._get_engine().connect() as conn:
        before = conn.execute(select(store.installation_repos.c.updated_at)
                              .where(store.installation_repos.c.installation_id == 101)).scalar_one()
    assert store.set_repo_pr_comment(101, 11, False) is True
    assert store.repo_pr_comment(202, 11) is True
    with store._get_engine().connect() as conn:
        after = conn.execute(select(store.installation_repos.c.updated_at)
                             .where(store.installation_repos.c.installation_id == 101)).scalar_one()
    assert after == before
    # webhook re-add preserves an explicit False
    store.set_installation_repos(101, [], replace=True)
    store.set_installation_repos(101, [(11, "acme/one")], replace=False)
    assert store.repo_pr_comment(101, 11) is False


def test_pr_comment_claim_round_trip(tmp_path, monkeypatch):
    """D9: the claim row is what makes create_comment single-winner; forget
    reopens it after a 404 (someone deleted Doug's comment)."""
    _db(tmp_path, monkeypatch)
    assert store.pr_comment_id(101, 11, 7) is None
    assert store.claim_pr_comment(101, 11, 7) is True
    assert store.claim_pr_comment(101, 11, 7) is False
    store.set_pr_comment_id(101, 11, 7, 987654)
    assert store.pr_comment_id(101, 11, 7) == 987654
    store.forget_pr_comment(101, 11, 7)
    assert store.pr_comment_id(101, 11, 7) is None
    assert store.claim_pr_comment(101, 11, 7) is True


def test_pr_comment_denied_marker_sets_and_clears(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.upsert_installation(101, "acme", "Organization", "active")
    assert store.pr_comment_denied_at(101) is None
    at = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    store.mark_pr_comment_denied(101, at)
    assert store.pr_comment_denied_at(101) == at
    store.mark_pr_comment_denied(101, None)
    assert store.pr_comment_denied_at(101) is None
```

- [ ] **Step 2: Run** → FAIL (AttributeError).

- [ ] **Step 3: Implement** — follow `repo_threshold`/`set_repo_threshold` exactly for engine handling. `repo_pr_comment`: `select(installation_repos.c.pr_comment).where(installation_id==, github_repo_id==, state=="active")` → `bool(value)` or `False`. `set_repo_pr_comment`: `update(...).where(..., state=="active").values(pr_comment=bool(value))` → `rowcount == 1`. `claim_pr_comment`: use the file's existing `postgresql_insert`/`sqlite_insert` dialect pattern (`on_conflict_do_nothing(index_elements=[...])`) and return `result.rowcount == 1`; `updated_at=now`. `set_pr_comment_id`: `update(pr_comments).values(comment_id=, updated_at=now)`. `mark_pr_comment_denied`: `update(installations).values(pr_comment_denied_at=at)`. Docstrings: carry the D6 reason on `repo_pr_comment` and the `updated_at` reason on `set_repo_pr_comment`.

- [ ] **Step 4: Run** — `uv run pytest tests/test_store.py -q` then full + ruff → PASS.
- [ ] **Step 5: Commit** — `feat(store): pr_comment read/write, claim table, denial marker`.

### Task 4: `check_run` — neutralise model text for both surfaces; `CLEARED_NOTE`

**Files:** Modify `api/doug/check_run.py` (`_oneline` :110, `_quote` :122, `render` :129, header comment); Test `api/tests/test_check_run.py` (byte-locked expectations may change)

- [ ] **Step 1: Failing tests** (`test_check_run.py`):

```python
def test_oneline_neutralises_the_forms_that_have_side_effects_in_a_pr_comment():
    """The same markdown renders in a check run and in a PR comment, but only
    the comment notifies @mentions, writes #refs into other timelines, and
    links under a trusted bot identity; an unterminated <!-- swallows the
    rest of the body. Neutralised HERE so both surfaces stay byte-identical."""
    z = "​"
    assert check_run._oneline("ping @doug now") == f"ping @{z}doug now"
    assert check_run._oneline("see #123 and owner/repo#4") == f"see #{z}123 and owner/repo#{z}4"
    assert check_run._oneline("x <!-- y") == f"x <!-{z}- y"
    assert check_run._oneline("[click](https://evil)") == f"[click]{z}(https://evil)"
    assert check_run._oneline("email a@b.c") == "email a@b.c"  # not a mention: no leading space/start
    assert check_run._oneline("line\nbreak") == "line break"


def test_quote_goes_through_oneline():
    reason = Reason(rule="x", label="Partial read: paths/@user\nfile", weight=0.0)
    assert check_run._quote(reason) == ["", "> Partial read: paths/@user file"]


def test_render_carries_the_cleared_note_only_when_cleared():
    # build a cleared verdict and a flagged one with the file's fixtures
    _, cleared = check_run.render("reader", CLEARED_VERDICT, None, None)
    _, flagged = check_run.render("reader", FLAGGED_VERDICT, None, None)
    assert check_run.CLEARED_NOTE in cleared
    assert check_run.CLEARED_NOTE not in flagged
```

(`CLEARED_VERDICT`/`FLAGGED_VERDICT`: reuse the file's existing verdict fixtures.) Mention rule: `(?<![\w.])@(\w)` → `@​\1`; refs: `(?<![\w/])#(\d)` → `#​\1` and `(\w/\w+)#(\d)` → keep the repo part and insert ZWSP after `#`; `<!--` → `<!-​-`; `](` → `]​(`. Run on the whitespace-collapsed string.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — in `_oneline`, after the whitespace collapse, apply the four `re.sub`s; document each with the side effect it prevents and that a ZWSP is invisible in rendered markdown but breaks the tokeniser. `_quote`: `f"> {_oneline(reason.label)}"`. Add:

```python
CLEARED_NOTE = (
    "Cleared means Doug found nothing it wanted a human to look at; it is not a "
    "statement that the change is safe."
)
```
and in `render`, right after the `RISK_NOTE`/`NEUTRAL_NOTE` lines: `if verdict.band is Band.CLEARED: lines += ["", CLEARED_NOTE]`. Update any byte-locked test expectation that breaks (cleared fixtures now carry the note). Module header: one sentence — *"`pr_comment.py` mirrors this summary byte-for-byte inside a PR comment; anything that must not reach a comment must be neutralised here, not there."*

- [ ] **Step 4: Run** — `uv run pytest tests/test_check_run.py tests/test_worker.py -q`, full, ruff → PASS.
- [ ] **Step 5: Commit** — `feat(check-run): neutralise mentions/refs/links/HTML-comment openers; CLEARED_NOTE`.

### Task 5: `api/doug/pr_comment.py`

**Files:** Create `api/doug/pr_comment.py`; Test create `api/tests/test_pr_comment.py`

**Interfaces — Produces:**
```python
MARKER_PREFIX = "<!-- doug:verdict"
ALLOWLIST_ENV = "DOUG_PR_COMMENT_INSTALLATIONS"
def allowed(installation_id: int) -> bool                       # D3a: empty env -> False; same parse as intent.enabled_for
def receipt_url(owner: str, repo: str, pr_number: int) -> str | None
def render(summary: str, *, head_sha: str, seq: int, receipt_url: str | None) -> str
def target_matches(gh, owner: str, repo: str, pr_number: int, github_repo_id: int) -> bool
def upsert(gh, owner, repo, pr_number, body, *, installation_id, github_repo_id, seq) -> str
```
Outcome strings: `created | updated | skipped-stale | denied:403 | failed:<code> | failed:net`.

- [ ] **Step 1: Failing tests** (`test_pr_comment.py`) — build a fake `gh` with `rest.issues.list_comments/create_comment/update_comment` (return `SimpleNamespace(parsed_data=...)`) and `rest.pulls.get`; a fake comment is `SimpleNamespace(id=, body=, performed_via_github_app=SimpleNamespace(id=4450932) | None, user=SimpleNamespace(type="User", login="x"))`. Monkeypatch `app_auth.app_id` → `"4450932"`. Use `_db(...)` from test_store's pattern for the claim table.

```python
def test_render_frames_the_summary_verbatim_with_pinned_joins():
    body = pr_comment.render("**T**\n\n- none", head_sha="a"*40, seq=7, receipt_url="https://hq/dashboard/pr/3?repo=o%2Fr")
    lines = body.split("\n")
    assert lines[0] == f"<!-- doug:verdict head={'a'*40} seq=7 -->"
    assert lines[1] == ""
    assert lines[2].startswith("_The `Doug` check run for aaaaaaa, repeated here in full.")
    assert lines[3] == ""
    assert "\n\n- none\n\n---\n" in body            # summary ends on a list item: TWO newlines before ---
    assert "**T**\n\n- none" in body                 # byte-identical middle
    assert "[full receipt on Doug HQ](https://hq/dashboard/pr/3?repo=o%2Fr) — sign-in required" in body
    assert "/docs/what-doug-gets-wrong" in body

def test_render_without_a_web_url_omits_both_links_and_still_renders(): ...
def test_frame_plus_summary_limit_fits_githubs_comment_cap():
    assert check_run.SUMMARY_LIMIT + pr_comment.FRAME_MAX <= 65_536

def test_receipt_url_encodes_the_repo_and_is_none_when_env_empty(monkeypatch):
    monkeypatch.setenv("DOUG_WEB_URL", "")
    assert pr_comment.receipt_url("o", "r", 3) is None
    monkeypatch.setenv("DOUG_WEB_URL", "https://hq")
    assert pr_comment.receipt_url("o", "r", 3) == "https://hq/dashboard/pr/3?repo=o%2Fr"

def test_upsert_updates_by_stored_id_and_never_lists(): ...
def test_upsert_on_a_404_for_the_stored_id_forgets_then_lists_then_creates(): ...
def test_upsert_never_matches_a_human_authored_marked_comment_and_creates_its_own(): ...
def test_upsert_skips_when_the_existing_seq_is_newer(): ...
def test_upsert_on_listing_failure_returns_failed_and_never_creates(): ...
def test_upsert_on_page_bound_returns_failed_and_never_creates(): ...
def test_upsert_claim_lost_updates_instead_of_creating(): ...
def test_upsert_403_is_denied_and_does_not_raise(): ...
def test_upsert_tolerates_a_comment_with_unset_body(): ...
def test_upsert_network_error_is_failed_net(): ...
def test_target_matches_compares_base_repo_id(): ...
def test_allowed_reads_the_allowlist_env_like_intent(monkeypatch): ...
```
Each `...` must be a real test; the RED run must show each failing for the expected reason. For `RequestFailed`, construct `githubkit.exception.RequestFailed(SimpleNamespace(status_code=403, ...))` — read the exception's constructor first and build it the way `tests/test_app_auth.py` or `test_intent_providers`-style tests already do (grep `RequestFailed(` in api/tests).

- [ ] **Step 2: Run** → FAIL (module missing).
- [ ] **Step 3: Implement** — per spec §3.2. Sketch:

```python
"""One sticky PR comment that mirrors the check run. Sibling of check_run.py.

The middle of the body is check_run.render()'s summary BYTE-FOR-BYTE; the
frame says only what the summary cannot (which commit, edited in place,
where the receipt is). Anything that must not reach a comment is neutralised
in check_run._oneline so both surfaces stay identical (ADR-0014 / D7).
"""
import os, re, sys
from datetime import UTC, datetime
from urllib.parse import quote
from githubkit.exception import RequestError, RequestFailed
from . import app_auth, store

MARKER_PREFIX = "<!-- doug:verdict"
_MARKER_RE = re.compile(r"^<!-- doug:verdict head=([0-9a-f]{7,64}) seq=(\d+) -->")
ALLOWLIST_ENV = "DOUG_PR_COMMENT_INSTALLATIONS"
_PAGE_BOUND = 10
_PER_PAGE = 100
FRAME_MAX = 1_000  # asserted in tests against SUMMARY_LIMIT

def allowed(installation_id): ...  # same parse as intent.enabled_for
def receipt_url(owner, repo, pr_number):
    base = os.environ.get("DOUG_WEB_URL") or None
    return None if base is None else f"{base.rstrip('/')}/dashboard/pr/{pr_number}?repo={quote(f'{owner}/{repo}', safe='')}"

def render(summary, *, head_sha, seq, receipt_url):
    header = (f"_The `Doug` check run for {head_sha[:7]}, repeated here in full. "
              "Doug edits this comment in place on every review; it is never re-posted._")
    web = os.environ.get("DOUG_WEB_URL") or None
    if receipt_url is None:
        footer = "Doug · not a gate"
    else:
        footer = (f"Doug · [full receipt on Doug HQ]({receipt_url}) — sign-in required · "
                  f"[what Doug gets wrong]({web.rstrip('/')}/docs/what-doug-gets-wrong)")
    return f"{MARKER_PREFIX} head={head_sha} seq={seq} -->\n\n{header}\n\n{summary}\n\n---\n{footer}"

def _is_ours(c) -> bool:
    body = getattr(c, "body", "") or ""
    app = getattr(c, "performed_via_github_app", None)
    return body.startswith(MARKER_PREFIX) and app is not None and str(getattr(app, "id", "")) == (app_auth.app_id() or "")

def _seq_of(c) -> int: ...  # parse; 0 if no match

def target_matches(gh, owner, repo, pr_number, github_repo_id) -> bool:
    try:
        pr = gh.rest.pulls.get(owner=owner, repo=repo, pull_number=pr_number).parsed_data
    except (RequestFailed, RequestError):
        return False
    return getattr(getattr(pr, "base", None), "repo", None) is not None and pr.base.repo.id == github_repo_id

def upsert(gh, owner, repo, pr_number, body, *, installation_id, github_repo_id, seq) -> str:
    key = (installation_id, github_repo_id, pr_number)
    try:
        cid = store.pr_comment_id(*key)
        if cid is not None:
            try:
                gh.rest.issues.update_comment(owner=owner, repo=repo, comment_id=cid, body=body)
                return "updated"
            except RequestFailed as e:
                if e.response.status_code != 404:
                    raise
                store.forget_pr_comment(*key)
        # bounded listing; "none found" only after it completed
        found = None
        for page in range(1, _PAGE_BOUND + 1):
            batch = gh.rest.issues.list_comments(owner=owner, repo=repo, issue_number=pr_number,
                                                 per_page=_PER_PAGE, page=page).parsed_data
            for c in batch:
                if _is_ours(c):
                    found = c; break
            if found is not None or len(batch) < _PER_PAGE:
                break
        else:
            _log(owner, repo, pr_number, "failed:page-bound"); return "failed:page-bound"
        if found is not None:
            store.claim_pr_comment(*key); store.set_pr_comment_id(*key, found.id)
            if _seq_of(found) > seq:
                return "skipped-stale"
            gh.rest.issues.update_comment(owner=owner, repo=repo, comment_id=found.id, body=body)
            return "updated"
        if not store.claim_pr_comment(*key):
            cid = store.pr_comment_id(*key)
            if cid is not None:
                gh.rest.issues.update_comment(owner=owner, repo=repo, comment_id=cid, body=body)
                return "updated"
        created = gh.rest.issues.create_comment(owner=owner, repo=repo, issue_number=pr_number, body=body).parsed_data
        store.set_pr_comment_id(*key, created.id)
        return "created"
    except RequestFailed as e:
        code = e.response.status_code
        outcome = "denied:403" if code == 403 else f"failed:{code}"
    except RequestError:
        outcome = "failed:net"
    _log(owner, repo, pr_number, outcome)
    return outcome
```
Anything not `RequestFailed`/`RequestError` propagates (a wrong kwarg must not read as GitHub being unhappy). Keep lines ≤ 100 cols.

- [ ] **Step 4: Run** — `uv run pytest tests/test_pr_comment.py -q`, full, ruff → PASS.
- [ ] **Step 5: Commit** — `feat(pr-comment): render the framed mirror and upsert it by id, authorship and seq`.

### Task 6: Worker — both post sites, allowlist, own log line, denial marker, mirror test

**Files:** Modify `api/doug/worker.py` (`_replay_recorded` ~:148, `process_job` ~:355); Test `api/tests/test_worker.py`

- [ ] **Step 1: Failing tests** (`test_worker.py`; extend `_wire` to also monkeypatch `pr_comment.upsert` into a list, and add `issues`/`pulls.get` to `_gh` as needed):

```python
def test_the_pr_comment_mirrors_the_check_run_summary_and_logs_its_own_line(tmp_path, monkeypatch, capsys):
    """The ADR claim tested where it can actually fail: the SAME summary
    string handed to check_run.post must appear inside the comment body."""
    posted = _wire(...)                     # check_run.post captured
    upserts = _wire_pr_comment(monkeypatch) # pr_comment.upsert captured -> returns "created"
    monkeypatch.setenv("DOUG_PR_COMMENT_INSTALLATIONS", "101")
    # seed install 101 / repo 11 (active, pr_comment default True) / job
    _run_one_job()
    assert posted[0]["summary"] in upserts[0]["body"]
    assert "doug: comment created acme/one#1@" in capsys.readouterr().err
    # the reviewed line is untouched (still precedes complete)
    ...

def test_no_comment_when_the_repo_setting_is_off_or_the_row_is_missing_or_not_allowlisted(...):
    # three cases -> no upsert call, log says comment skipped

def test_a_denied_comment_marks_the_installation_and_a_success_clears_it(...):
    # upsert returns "denied:403" -> store.pr_comment_denied_at(101) set; next run "updated" -> None

def test_the_replay_path_posts_the_same_body_and_verifies_the_target(...):
    # existing verdict identity -> _replay_recorded; target_matches False -> "skipped-target", no upsert

def test_a_lost_claim_posts_no_comment(...):  # mirror of test_a_lost_claim_after_save_skips_the_check_run
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — add to both sites immediately after `check_run.post(...)`:

```python
    _post_pr_comment(gh, owner, name, job, title, summary, fresh=True)   # fresh path
    _post_pr_comment(gh, owner, name, job, title, summary, fresh=False)  # replay path
```
with
```python
def _post_pr_comment(gh, owner, name, job, title, summary, *, fresh: bool) -> None:
    """Sticky PR comment mirroring the check run (spec 2026-08-19). Runs after
    ingest.complete like check_run.post. Own stderr line: the reviewed/replayed
    lines are printed BEFORE complete on purpose and must not move."""
    inst, repo_id, pr = job["installation_id"], job["github_repo_id"], job["pr_number"]
    if not (store.repo_pr_comment(inst, repo_id) and pr_comment.allowed(inst)):
        outcome = "skipped"
    elif not fresh and not pr_comment.target_matches(gh, owner, name, pr, repo_id):
        outcome = "skipped-target"
    else:
        body = pr_comment.render(summary, head_sha=job["head_sha"], seq=job["id"],
                                 receipt_url=pr_comment.receipt_url(owner, name, pr))
        outcome = pr_comment.upsert(gh, owner, name, pr, body,
                                    installation_id=inst, github_repo_id=repo_id, seq=job["id"])
        if outcome == "denied:403":
            store.mark_pr_comment_denied(inst, datetime.now(UTC))
        elif outcome in ("created", "updated"):
            store.mark_pr_comment_denied(inst, None)
    print(f"doug: comment {outcome} {job['repo_full_name']}#{pr}@{job['head_sha'][:12]}", file=sys.stderr)
```
(`title` unused today; keep the parameter out if ruff complains — pass only `summary`.) Fresh path already fetched/validated the PR earlier, so `target_matches` only runs on replay. Import `pr_comment`.

- [ ] **Step 4: Run** — `uv run pytest tests/test_worker.py -q`, full, ruff → PASS.
- [ ] **Step 5: Commit** — `feat(worker): post the sticky PR comment from both sites behind the repo setting and allowlist`.

### Task 7: API — PATCH grows `pr_comment`; connections carry it and the denial timestamp

**Files:** Modify `api/doug/api.py` (`RepositorySettingsPatch` :1236, `RepositorySettings` :1244, `set_repository_flag_line` :1249, `session_connections` :1967–2040); `api/doug/store.py` (`session_connections_for` :3245 — add `pr_comment` to the select and the repo dict; add `installations.pr_comment_denied_at` to the row); Test `api/tests/test_api.py`

- [ ] **Step 1: Failing tests** (`test_api.py`, next to the flag_line tests):

```python
def test_patch_pr_comment_alone_does_not_touch_the_flag_line(tmp_path, monkeypatch):
    """Optional fields: absent and explicit-null both arrive as None; the
    write must be gated on model_fields_set or toggling comments would wipe
    the repo's flag line."""
    headers = _session_scope(tmp_path, monkeypatch, repos=(11,), claim=(11,))
    assert _patch_line(headers, 11, {"needs_you_threshold": 0.75}).status_code == 200
    r = _patch_line(headers, 11, {"pr_comment": False})
    assert r.status_code == 200 and r.json() == {"needs_you_threshold": 0.75, "pr_comment": False}
    assert store.repo_threshold(101, 11) == 0.75 and store.repo_pr_comment(101, 11) is False
    r = _patch_line(headers, 11, {"needs_you_threshold": None})   # explicit null still clears
    assert r.json() == {"needs_you_threshold": None, "pr_comment": False}

def test_patch_rejects_empty_unknown_and_coerced_bodies(...):
    assert _patch_line(headers, 11, {}).status_code == 422
    assert _patch_line(headers, 11, {"pr_commnt": False}).status_code == 422
    for bad in ("true", 1, 0, "false"):
        assert _patch_line(headers, 11, {"pr_comment": bad}).status_code == 422, bad

def test_audit_line_names_only_the_written_field(..., capsys):
    # pr_comment toggle -> "doug: repo_settings installation=101 repo=11 pr_comment True->False by sub=..."
    # and NOT "needs_you_threshold" in that line

def test_connections_carry_pr_comment_and_the_denial_timestamp(...):
    store.set_repo_pr_comment(101, 12, False); store.mark_pr_comment_denied(101, at)
    body = ...get("/v1/sessions/connections")...
    repos = {r["id"]: r for r in body["connections"][0]["repositories"]}
    assert repos[11]["pr_comment"] is True and repos[12]["pr_comment"] is False
    assert body["connections"][0]["pr_comment_denied_at"] == at.isoformat()
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**

```python
class RepositorySettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Both optional; `{}` is rejected below. Writes are gated on
    # model_fields_set, NEVER on `is not None`: null is how the flag line is
    # cleared, and absent must not look like null.
    needs_you_threshold: float | None = Field(None, strict=True, allow_inf_nan=False, ge=0, le=1)
    pr_comment: bool | None = Field(None, strict=True)

    @model_validator(mode="after")
    def _at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("at least one of needs_you_threshold, pr_comment is required")
        return self


class RepositorySettings(BaseModel):
    needs_you_threshold: float | None
    pr_comment: bool
```
Endpoint: after the scope check, `written = []`; if `"needs_you_threshold" in body.model_fields_set`: before/after as today, `set_repo_threshold`, `written.append(("needs_you_threshold", before, after))`; if `"pr_comment" in body.model_fields_set`: `before = store.repo_pr_comment(...)`; `set_repo_pr_comment(...)` (rowcount 0 → 404); `written.append(("pr_comment", before, after))`. One audit line per written field: `doug: repo_settings installation={id} repo={id} {field} {before}->{after} by sub={sub}` (keep the old `needs_you_threshold installation=` prefix format if any test pins it — check; otherwise unify on `repo_settings`). Return both current values. `session_connections_for`: add `installation_repos.c.pr_comment` and `installations.c.pr_comment_denied_at` to the select; repo dict gains `"pr_comment": bool(row["pr_comment"])`; connection dict gains `"pr_comment_denied_at": _as_utc(...)`; `session_connections` passes it through as ISO string or null on both branches (ready and reauthorize_required). Imports: `ConfigDict`, `model_validator` from pydantic. The `{"needs_you_threshold": 1}` int-accepted behaviour stays (strict float accepts int).

- [ ] **Step 4: Run** — `uv run pytest tests/test_api.py -q`, full, ruff → PASS. Existing whole-body connections assertions gain the new keys.
- [ ] **Step 5: Commit** — `feat(api): PATCH pr_comment with field-set-gated writes; connections carry it and the denial marker`.

### Task 8: Web — tighten guards, types, toggle form + action, denial banner

**Files:** Modify `web/lib/session-api.ts` (types; `repository()`; `setRepositoryThreshold` response guard → require `pr_comment`; new `setRepositoryPrComment`); `web/components/flag-line-control.tsx` (third form: toggle); `web/app/dashboard/actions.ts` (`setFlagLineCommentAction`); `web/app/dashboard/page.tsx` (pass `pr_comment` per row; banner when `door.current.pr_comment_denied_at`); `web/lib/dashboard-model.ts` (`parseBool`); Tests `web/lib/session-api.test.mjs`, `web/lib/dashboard-contract.test.mjs`, `web/lib/dashboard-model.test.mjs`

- [ ] **Step 1: Failing tests**
  - session-api: guards now REQUIRE `pr_comment` on repositories[] and on the PATCH response; `setRepositoryPrComment("t", 11, false)` PATCHes `{"pr_comment": false}` (strict deepStrictEqual + `typeof === "boolean"`), returns the response object.
  - dashboard-contract: `flag-line-control.tsx` contains `PR comment`, `setFlagLineCommentAction`, and a form whose only named field is `pr_comment` (grep that the toggle form does NOT contain `name="needs_you_threshold"`); `actions.ts` exports `setFlagLineCommentAction`; `page.tsx` contains the banner copy `Doug's last attempt to comment was refused (403)` and `re-accepted in GitHub`.
  - dashboard-model: `parseBool("true") === true`, `"false" → false`, anything else → undefined.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — types: repositories entry gains `pr_comment: boolean`; `RepositoryConnection` gains `pr_comment_denied_at: string | null` (update `connection()` guard's exact key list). Replace `exactWithOptional` uses with `exact` + required checks; delete the helper. `setRepositoryPrComment(accessToken, githubRepoId, value: boolean): Promise<{needs_you_threshold: number|null; pr_comment: boolean}>`. Control: third `<form action={setFlagLineCommentAction}>` with hidden `github_repo_id`, hidden `pr_comment` = the *opposite* of current, and a button labelled `PR comment · on` / `PR comment · off` (button text shows current state; click flips). Action mirrors `setFlagLineAction` (parse, withAuth, frontDoor pre-check, call, revalidatePath). Banner: in the Repositories view, when `door.current.pr_comment_denied_at` is non-null, render a one-line notice above the table: *"PR comments are not posting: Doug's last attempt to comment was refused (403) at {date}. The usual cause is the pull-requests write permission not being re-accepted in GitHub; a locked conversation or an archived repository produce the same code."*
- [ ] **Step 4: Run** — `cd web && npm test && npx tsc --noEmit && npm run lint`; `npm run build --workspace=web` from root → PASS.
- [ ] **Step 5: Commit** — `feat(web): PR comment toggle beside the flag line; denial banner; guards require pr_comment`.

### Task 9: Deploy env — `DOUG_WEB_URL` and the temporary allowlist on the API service

**Files:** Modify `api/deploy/gcp.sh` (env line ~:674; reuse `web_url()` ~:919); Test `api/tests/test_deploy_gcp.py`

- [ ] **Step 1: Failing test** — pin, like the existing `test_api_deploy_carries_the_showcase_repo`, that the API `--set-env-vars` line contains `DOUG_WEB_URL=$(web_url)` and `DOUG_PR_COMMENT_INSTALLATIONS=150424894` (dogfood installation id — same id `DOUG_INTENT_INSTALLATIONS` uses), with a docstring saying the allowlist is temporary (D3a) and what removing it means.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — append both to the `--set-env-vars` string at :674 (the comment above warns the flag replaces the whole block — keep every existing var). `web_url()` must be defined before `deploy()` runs it; if it is declared later in the file that is fine in bash as long as it is defined before the call executes — verify by reading the file's call order, or move it. Document next to `DOUG_INTENT_INSTALLATIONS`'s comment that `DOUG_PR_COMMENT_INSTALLATIONS` is the same shape and is temporary.
- [ ] **Step 4: Run** — `uv run pytest tests/test_deploy_gcp.py -q` → PASS. Commit — `deploy: DOUG_WEB_URL and the temporary PR-comment allowlist on the API service`.

### Task 10: Docs — ADR-0014, ADR-0010 amendment, experience.md, changelog, standing issues, handoff, full suites

**Files:** Create `docs/decisions/ADR-0014-one-sticky-pr-comment-mirrors-the-check-run.md`; Modify `docs/decisions/ADR-0010-surface-is-a-neutral-check-run.md` (one sentence in §Rejected "PR comments"), `docs/design/outcome-loop/experience.md:13` (surface 1), `web/app/docs/changelog/page.tsx` (new top row), `HANDOFF.md`

- [ ] **Step 1: ADR-0014** — frontmatter `title/status: accepted/date: 2026-08-19`; Context **quotes** ADR-0010's precision clause ("That condition was written about surfaces that can block or notify, and it still binds those") and states the number does not exist and the decision ships anyway with the allowlist as mitigation; Decision = spec D1–D9 as mechanisms; **Rejected** = per-push comments; flagged-only; short card; richer layout first; public receipt; deleting on opt-out (standing issue #…); gating the review; marker-only match; absent-row-on; `issues: write`; Consequences = one notification per *created* comment and the delete→re-create cycle; comments persist after opt-out and uninstall; permission blast radius (reviews, PR edits, close/reopen, reviewers, delete comments; not merge); the converse (comment without check run when `check_run.post` fails); most readers hit sign-in on the receipt link; interim allowlist is temporary; `Reader-fed:` paragraph (flag: a second comment-writing function; a review call; a write path without an active row; neutralisation removed from `_oneline`; do not flag: re-create after deletion; removal of the allowlist). **Token check:** `api/tests/test_intent.py` scans docs/decisions — run it after writing and reword if a fixture collides (see the ADR-0013 precedent: avoid `bump`, keep `api` to one hit).
- [ ] **Step 2: ADR-0010** §Rejected "PR comments" paragraph: append *"Amended by ADR-0014: one sticky, App-authored comment that mirrors this check run, edited in place."* Status stays `accepted`.
- [ ] **Step 3: experience.md:13** — replace "Never a comment, never a block, never a red X." with "One sticky PR comment that mirrors the check run (ADR-0014); never a block, never a red X." and grep siblings (`product-spec.md`, `design-lock.md`) for "never a comment".
- [ ] **Step 4: Changelog row** at the top of `ParamsTable` in `web/app/docs/changelog/page.tsx`: `name: "2026-08-19"`, description: *"Doug leaves one sticky comment on each reviewed PR that repeats its check run word for word, edited in place on every push — on by default, opt-out per repository beside the flag line. Rolling out to Doug's own repositories first."*
- [ ] **Step 5: Standing issues** — open two GitHub issues (per AGENTS.md): (1) delete-on-opt-out (D3b) with the spec/ADR pointers and what "done" looks like; (2) "Flagged" vs "needs you" wording in `check_run._headline`, now amplified. Put the numbers in ADR-0014's Rejected/Consequences and in the spec §3.5.
- [ ] **Step 6: HANDOFF** — `State: review`; `Next:` open PR B after PR A deployed AND the App permission is re-accepted on the dogfood installation; then remove the allowlist in a follow-up PR once a week of dogfood comments look right.
- [ ] **Step 7: Full suites** — `make test` and `make lint`; report exact final lines.
- [ ] **Step 8: Commit** — `docs: ADR-0014 one sticky PR comment mirrors the check run; amend ADR-0010; changelog`.

Then open PR B (`feat: one sticky PR comment that mirrors the check run`) — body links spec, ADR-0014, the manual permission step, and the two standing issues. **Do not merge before PR A is deployed and the App permission is updated.**

---

## Self-review

- **Spec coverage:** §3.1 → T2/T3/T7/T8; §3.2 → T5; §3.3 → T6; §3.4 → T4; §3.5 → T10; D3a → T5 `allowed` + T6 gate + T9 env; D8 → T2/T3 col + T6 marking + T7 connections + T8 banner; D9 → T5; deploy split → T1 + manual gate; §5 tests → each task's Step 1 (worker-level mirror test in T6).
- **Placeholders:** T5 lists test names with `...` — each is a required real test; the RED run must show each; T6's `_wire_pr_comment`/`_run_one_job` name the file's helper pattern to extend (the threshold plan's T5 did the same and the implementer built them).
- **Type consistency:** `repo_pr_comment/set_repo_pr_comment/pr_comment_id/claim_pr_comment/set_pr_comment_id/forget_pr_comment/mark_pr_comment_denied/pr_comment_denied_at` (T3) match T5/T6/T7; `pr_comment.render(summary, *, head_sha, seq, receipt_url)` / `upsert(..., *, installation_id, github_repo_id, seq)` / `allowed` / `target_matches` (T5) match T6; response shape `{needs_you_threshold, pr_comment}` is the same in T1/T7/T8; outcome tokens `created|updated|skipped-stale|denied:403|failed:*` plus worker-only `skipped|skipped-target` consistent in T5/T6.
