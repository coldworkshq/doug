# Outcome-Lane Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the one place Doug's outcome ledger trusts a webhook alone — a lost `pull_request: closed` (merged) delivery currently loses that merge forever, silently, with no reconciliation path — by giving the outcome lane the same "re-derive from the API, let the unique index dedupe" mechanism the review lane already has.

**Architecture:** Adds `worker.reconcile_outcomes`/`reconcile_all_outcomes`, the outcome-lane siblings of the existing `reconcile_installation`/`reconcile_all`, which re-derive recently-closed PRs from GitHub and re-enqueue any merge `_record_merge` may have missed (idempotent via `outcome_jobs`' own `ON CONFLICT DO NOTHING`). Wires them into the two existing lifecycle triggers (process cold start, `installation.created`) for immediate best-effort coverage, and adds a new, independently-scheduled Cloud Run Job as the reliable backstop that does not depend on a cold start ever happening. Does **not** touch `publication-preregistration.md`'s locked metric, denominator, windows, or censoring logic — this is an ingestion-completeness fix only, the same "mechanism, not the published metric" boundary v8 already drew for the atomic 14/60-day write.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (Postgres in production, sqlite in tests via `DATABASE_URL`), githubkit (schema `v2026_03_10`), pytest, bash (`deploy/gcp.sh`, no Terraform).

## Global Constraints

- No new dependencies. githubkit is already installed and already exposes everything needed, including the raw-response escape hatch Task 1 uses.
- Test conventions: pytest, no `conftest.py` — every test file defines its own local helpers. Fixtures are pytest's built-in `tmp_path`/`monkeypatch`/`capsys`. GitHub is faked with `types.SimpleNamespace`, never `unittest.mock`. Store-side state is seeded through real `store.*` calls against a temp sqlite `DATABASE_URL`, never mocked.
- Log line convention: `"doug: <what> <verb> <detail>"` to `sys.stderr`, one line, no exceptions swallowed silently — every `except Exception` that isn't re-raised prints why (`# noqa: BLE001 — <reason>`).
- Does not add a fork or draft gate to anything in the outcome lane: `_record_merge` (`api.py:2244`) applies neither, per `publication-preregistration.md` §2.4 ("no fork gate, no draft gate, no verdict-existence check — those live only on the review path"). Matching that gate here would silently exclude merges the webhook path itself would have recorded, which is a correctness regression, not a hardening.
- Does not modify `store.enqueue_outcome_jobs`, the `outcome_jobs` table, or anything in `adjudicate.py` / `outcome_backfill.py`. The dedup mechanism (`ON CONFLICT DO NOTHING` on `uq_outcome_job`) already does exactly what a reconciliation caller needs.

---

## Task 1: `worker.reconcile_outcomes` and `worker.reconcile_all_outcomes`

**Files:**
- Modify: `api/doug/worker.py` (imports near line 20; new functions appended after `reconcile_all()`, which ends around line 638 — it is the last function in the file today)
- Test: `api/tests/test_worker.py` (new tests appended after the existing `reconcile_installation` tests, which run through roughly line 1406)

**Interfaces:**
- Consumes: `store.active_repos(installation_id) -> list[tuple[int, str]]`, `store.active_installations() -> list[int]`, `store.enqueue_outcome_jobs(installation_id, github_repo_id, pr_number, merge_commit_sha, merged_at, base_ref, *, window_days=(14,60), merged_head_sha=None) -> dict[int, int]` (all pre-existing, unmodified), `app_auth.installation_client(installation_id) -> GitHub` (pre-existing).
- Produces: `worker.reconcile_outcomes(installation_id: int) -> int` (count of newly-enqueued windows for one installation), `worker.reconcile_all_outcomes() -> int` (same, summed across every active installation). Task 2 and Task 3 call these by name.

### Why this shape (read before writing code)

`_record_merge` (`api.py:2244-2299`) is the **only** code path that ever writes an `outcome_jobs` row, and it runs exclusively off the `pull_request`/`closed` webhook. Its own guard logs and returns — never raises — when a payload is missing a required fact, which is correct (a 500 would just trigger a GitHub redelivery loop over a body that will never carry the missing fact) but means a *lost* delivery (not a malformed one — one that never arrives, or is 202'd and then lost to a Cloud Run restart) leaves no trace anywhere. `reconcile_installation` (`worker.py:461`) already solved this exact failure class for the review lane — its own docstring: *"a delivery this service 202s and then loses to a restart is never retried... recovery does not trust webhooks at all, it re-derives the world from the API and lets the queue's unique index throw away what it already has."* That mechanism cannot cover merges: it calls `pulls.list(..., state="open", ...)`, and a merged PR is closed by definition.

Two things a straight copy of `reconcile_installation` would get wrong here, verified against the installed schema rather than assumed:

1. **`state="open"` → `state="closed"`, and it needs a bound.** "Every open PR" is naturally bounded; "every closed PR" is not — a repo's closed-PR history only grows. `pulls.list` accepts `sort`/`direction` (confirmed against `githubkit_schemas/v2026_03_10/rest/pulls.py:87-103`: `sort: Missing[Literal["created","updated","popularity","long-running"]]`, `direction: Missing[Literal["asc","desc"]]`), so `sort="updated", direction="desc"` lets the sweep stop at the first page whose oldest PR falls outside a lookback window, rather than paginating a repo's whole history every pass.
2. **`pulls.list`'s `PullRequestSimple` has no `merge_commit_sha` field.** Checked directly against `githubkit_schemas/v2026_03_10/models/group_0178.py` (`PullRequestSimple`) and `group_0439.py` (the full `PullRequest`, returned by `pulls.get`) — neither model declares `merge_commit_sha`, even though `pulls.get`'s own docstring (auto-generated from GitHub's OpenAPI description text) still names it: *"If mergeable is true, then merge_commit_sha will be the SHA of the test merge commit."* That description text does not exist without the field existing on GitHub's side — this is a githubkit codegen gap, not GitHub dropping the field. The escape hatch is `githubkit.Response.raw_response` (`githubkit/response.py:31`, `-> httpx.Response`), which exposes the real JSON body underneath the incomplete typed model. So: `merged_at` is required and can only come from `pulls.get`, one extra API call per merge candidate (not per closed PR — closed-without-merge PRs never reach it). This is the one place this function is not cheap, and it is still bounded by the same window and cap as everything else here.
3. **Attribute access, not dict access.** `pulls.list`/`pulls.get` return githubkit pydantic models (`getattr(p, "field", None)`), not the raw webhook JSON dict `_record_merge` reads with `.get(...)`. `reconcile_installation`'s own existing code (`getattr(getattr(p, "head", None), "sha", None)`) is the pattern to follow, not `_record_merge`'s `_obj`/`_text` helpers.
4. **`merged_at` is already a `datetime`.** Confirmed directly against the installed package: `PullRequestSimple.merged_at: Union[_dt.datetime, None]` and `PullRequestSimple.updated_at: _dt.datetime` (required, never `None`) — githubkit/pydantic parses GitHub's ISO-8601 timestamps for you. No `_payload_timestamp`-style string parsing is needed; only the same defensive naive→UTC normalisation `_payload_timestamp` already applies to the webhook's own copy of this fact, in case a future githubkit upgrade ever changes that.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_worker.py`, after the existing `reconcile_installation` tests (near line 1406, after `test_reconcile_installation_caps_and_logs_a_pathological_repo`):

```python
def _closed_pull(
    number=1,
    *,
    merged_at=None,
    updated_at=None,
    merge_commit_sha="c" * 40,
    base_ref="main",
    base_repo_id=42,
    head_sha="a" * 40,
):
    """A closed PR as pulls.list returns it (PullRequestSimple) — no
    merge_commit_sha field, by design (see reconcile_outcomes' docstring);
    a FakeListGH pairs this with a FakeGetGH that supplies it separately,
    the same split the real githubkit schema forces."""
    return SimpleNamespace(
        number=number,
        updated_at=updated_at or (merged_at or NOW),
        merged_at=merged_at,
        base=SimpleNamespace(
            ref=base_ref,
            repo=SimpleNamespace(id=base_repo_id, full_name="o/r"),
        ),
        head=SimpleNamespace(sha=head_sha),
    )


class FakeReconcileGH:
    """pulls.list (no merge_commit_sha) + pulls.get (raw_response.json()
    carries it) — the two-call shape reconcile_outcomes actually uses."""

    def __init__(self, pulls, merge_shas):
        self._merge_shas = merge_shas

        def _get(*, owner, repo, pull_number):
            body = {"merge_commit_sha": self._merge_shas.get(pull_number)}
            return SimpleNamespace(raw_response=SimpleNamespace(json=lambda: body))

        self.rest = SimpleNamespace(
            pulls=SimpleNamespace(
                list=lambda **kw: SimpleNamespace(parsed_data=pulls),
                get=_get,
            )
        )


def test_reconcile_outcomes_enqueues_a_missed_merge(tmp_path, monkeypatch):
    _installed(tmp_path, monkeypatch)
    pull = _closed_pull(number=5, merged_at=NOW - timedelta(days=1))
    gh = FakeReconcileGH([pull], {5: "c" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 2  # 14- and 60-day windows

    url = f"sqlite:///{tmp_path}/doug.db"
    (row_14, row_60) = sorted(
        _rows(url, store.outcome_jobs), key=lambda r: r["window_days"]
    )
    assert row_14["window_days"] == 14 and row_60["window_days"] == 60
    assert row_14["pr_number"] == 5 and row_14["github_repo_id"] == 42
    assert row_14["merge_commit_sha"] == "c" * 40
    assert row_14["base_ref"] == "main"
    assert row_14["merged_head_sha"] == "a" * 40


def test_reconcile_outcomes_skips_a_pr_closed_without_merging(tmp_path, monkeypatch):
    _installed(tmp_path, monkeypatch)
    pull = _closed_pull(number=6, merged_at=None, updated_at=NOW)
    gh = FakeReconcileGH([pull], {})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    assert _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs) == []


def test_reconcile_outcomes_is_a_no_op_against_a_merge_the_webhook_already_recorded(
    tmp_path, monkeypatch
):
    """The dedup proof: seed the row _record_merge would have written, then
    run reconcile over the same merge, and nothing doubles."""
    _installed(tmp_path, monkeypatch)
    merged_at = NOW - timedelta(days=1)
    store.enqueue_outcome_jobs(1, 42, 5, "c" * 40, merged_at, "main")
    pull = _closed_pull(number=5, merged_at=merged_at)
    gh = FakeReconcileGH([pull], {5: "c" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    rows = _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs)
    assert len(rows) == 2  # still exactly the 14/60-day pair, not four


def test_reconcile_outcomes_ignores_a_merge_outside_the_lookback_window(
    tmp_path, monkeypatch
):
    _installed(tmp_path, monkeypatch)
    stale = _closed_pull(
        number=7, merged_at=NOW - timedelta(days=40), updated_at=NOW - timedelta(days=40)
    )
    gh = FakeReconcileGH([stale], {7: "d" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    assert _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs) == []


def test_reconcile_outcomes_skips_a_pr_whose_base_repo_disagrees_with_the_ledger(
    tmp_path, monkeypatch, capsys
):
    _installed(tmp_path, monkeypatch)
    wrong_repo = _closed_pull(number=8, merged_at=NOW, base_repo_id=999)
    gh = FakeReconcileGH([wrong_repo], {8: "e" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    err = capsys.readouterr().err
    assert "base repo id 999" in err and "installation_repos' 42" in err


def test_reconcile_all_outcomes_sums_every_active_installation(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    store.upsert_installation(1, "o1", "Organization", "active")
    store.set_installation_repos(1, [(42, "o1/r")], replace=True)
    store.upsert_installation(2, "o2", "Organization", "active")
    store.set_installation_repos(2, [(43, "o2/r")], replace=True)

    def _client(installation_id):
        pulls = [
            _closed_pull(number=1, merged_at=NOW, base_repo_id=42 if installation_id == 1 else 43)
        ]
        shas = {1: f"{installation_id}" * 40}
        return FakeReconcileGH(pulls, shas)

    monkeypatch.setattr(worker.app_auth, "installation_client", _client)
    assert worker.reconcile_all_outcomes() == 4  # 2 installations * 2 windows each


def test_reconcile_all_outcomes_survives_one_bad_installation(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    store.upsert_installation(1, "o1", "Organization", "active")
    store.set_installation_repos(1, [(42, "o1/r")], replace=True)
    store.upsert_installation(2, "o2", "Organization", "active")
    store.set_installation_repos(2, [(43, "o2/r")], replace=True)

    def _client(installation_id):
        if installation_id == 1:
            raise RuntimeError("github said no")
        return FakeReconcileGH(
            [_closed_pull(number=1, merged_at=NOW, base_repo_id=43)], {1: "f" * 40}
        )

    monkeypatch.setattr(worker.app_auth, "installation_client", _client)
    assert worker.reconcile_all_outcomes() == 2  # installation 2 still ran
    err = capsys.readouterr().err
    assert "outcome reconcile failed for installation 1" in err and "github said no" in err


def test_reconcile_outcomes_paginates_past_the_first_page(tmp_path, monkeypatch):
    """pulls.list caps a single response at 100 results, the same ceiling
    test_reconcile_installation_paginates_past_the_first_page pins for the
    review lane. sort=updated,direction=desc means the 101st-newest closed
    PR is still inside the lookback window and must not be silently
    dropped for want of a second page."""
    _installed(tmp_path, monkeypatch)
    page1 = [_closed_pull(number=n, merged_at=NOW, updated_at=NOW) for n in range(1, 101)]
    page2 = [_closed_pull(number=101, merged_at=NOW, updated_at=NOW)]
    merge_shas = {n: f"{n:040d}" for n in range(1, 102)}

    def _list(*, page=1, **kw):
        data = {1: page1, 2: page2}.get(page, [])
        return SimpleNamespace(parsed_data=data)

    def _get(*, owner, repo, pull_number):
        body = {"merge_commit_sha": merge_shas[pull_number]}
        return SimpleNamespace(raw_response=SimpleNamespace(json=lambda: body))

    gh = SimpleNamespace(rest=SimpleNamespace(pulls=SimpleNamespace(list=_list, get=_get)))
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 202  # 101 merges * 2 windows each
    url = f"sqlite:///{tmp_path}/doug.db"
    seen = {r["pr_number"] for r in _rows(url, store.outcome_jobs)}
    assert seen == set(range(1, 102))


def test_reconcile_outcomes_caps_and_logs_a_pathological_repo(tmp_path, monkeypatch, capsys):
    """The outcome lane's sibling of
    test_reconcile_installation_caps_and_logs_a_pathological_repo — same
    monkeypatch-the-constant-down technique, same log-and-truncate shape."""
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "_MAX_CLOSED_PRS_PER_REPO", 3)
    pulls = [_closed_pull(number=n, merged_at=NOW, updated_at=NOW) for n in range(1, 5)]
    gh = FakeReconcileGH(pulls, {n: f"{n:040d}" for n in range(1, 5)})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 6  # capped at 3 PRs * 2 windows
    err = capsys.readouterr().err
    assert "capped at 3 closed PRs for o/r" in err
```

`NOW` must exist at module scope — check first whether `test_worker.py` already defines a `NOW = datetime.now(UTC)` constant (`test_outcome_worker.py` has one at its own top; `test_worker.py` may not). If it is missing, add `NOW = datetime.now(UTC)` next to the file's other module-level constants, and add `from datetime import timedelta` to its imports if not already present (it already imports `datetime`/`UTC` for other tests — confirm rather than assume, and add only what is missing).

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd api && uv run pytest tests/test_worker.py -k "reconcile_outcomes or reconcile_all_outcomes" -v
```

Expected: every new test FAILS with `AttributeError: module 'doug.worker' has no attribute 'reconcile_outcomes'` (or `reconcile_all_outcomes`).

- [ ] **Step 3: Add the datetime import**

Modify `api/doug/worker.py`'s import block (currently, near the top of the file):

```python
import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version

from . import app_auth, check_run, example_pack_capture, ingest, reader, review, store
```

to:

```python
import os
import platform
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version

from . import app_auth, check_run, example_pack_capture, ingest, reader, review, store
```

(`worker.py` does not import `datetime` today — confirmed by reading the file's current import block in full.)

- [ ] **Step 4: Implement `reconcile_outcomes` and `reconcile_all_outcomes`**

Append to the end of `api/doug/worker.py`, immediately after `reconcile_all()`'s closing `return total`:

```python
# Bounded by TIME, not count: an installation's OPEN PRs are naturally
# bounded (reconcile_installation's _MAX_OPEN_PRS_PER_REPO exists only as a
# backstop against a pathological repo), but "every closed PR" grows
# without bound over a repo's lifetime. sort=updated,direction=desc lets a
# reconcile pass stop the moment a page's oldest PR falls outside the
# window, so a healthy repo costs one page, not its whole history.
_MERGE_RECONCILE_LOOKBACK = timedelta(days=14)

# Backstop for a repo that closes an implausible number of PRs inside the
# lookback window — the outcome lane's sibling of _MAX_OPEN_PRS_PER_REPO,
# logged the same way when hit.
_MAX_CLOSED_PRS_PER_REPO = 300


def _aware(dt: datetime) -> datetime:
    """githubkit's ISO-8601 timestamps come back tz-aware in every field
    checked against the installed schema (PullRequestSimple.merged_at,
    .updated_at). Normalised defensively anyway — the same guard
    api.py's _payload_timestamp applies to the webhook's own copy of the
    same fact — so a future githubkit upgrade that ever changes this
    cannot turn into a naive/aware TypeError here."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def reconcile_outcomes(installation_id: int) -> int:
    """Enqueue outcome-observation windows for every merge this
    installation's webhook may have missed.

    The outcome lane's analogue of reconcile_installation, healing the same
    failure it heals: "a delivery this service 202s and then loses to a
    restart is never retried" (reconcile_installation's own docstring).
    _record_merge (api.py) is the ONLY other path that ever writes an
    outcome_jobs row, and it runs exclusively off the pull_request/closed
    webhook — there is no drain, no claim, no revive to fall back on the
    way review_jobs has, so a lost delivery here is healed by nothing else
    in this codebase today. This re-derives recently-closed PRs from the
    API and lets enqueue_outcome_jobs's ON CONFLICT DO NOTHING
    (store.py's uq_outcome_job) throw away what it already has — the
    identical "never trust the webhook alone" principle, applied to the
    one lane that has never had it.

    No draft/fork gate: _record_merge applies neither
    (publication-preregistration.md §2.4 — "no fork gate, no draft gate,
    no verdict-existence check"), and a merged PR is never a draft, so
    mirroring reconcile_installation's _skip_reason here would silently
    exclude merges the webhook path itself would have recorded.

    pulls.list's PullRequestSimple carries no merge_commit_sha (githubkit
    v2026_03_10 does not model that field, though GitHub's own OpenAPI
    description text for pulls.get — reproduced verbatim in its own
    docstring — still names it), so each merge candidate costs a second
    call, pulls.get, read from its raw response body rather than the typed
    model. That is the one place this function is not cheap; it is still
    bounded by the same lookback window and cap as everything else here.
    """
    gh = app_auth.installation_client(installation_id)
    cutoff = datetime.now(UTC) - _MERGE_RECONCILE_LOOKBACK
    count = 0
    for repo_id, full_name in store.active_repos(installation_id):
        owner, _, name = full_name.partition("/")
        pulls: list = []
        page = 1
        try:
            while True:
                batch = gh.rest.pulls.list(
                    owner=owner, repo=name, state="closed",
                    sort="updated", direction="desc",
                    per_page=100, page=page,
                ).parsed_data
                if not batch:
                    break
                pulls.extend(batch)
                oldest = getattr(batch[-1], "updated_at", None)
                stale = isinstance(oldest, datetime) and _aware(oldest) < cutoff
                if stale or len(batch) < 100 or len(pulls) >= _MAX_CLOSED_PRS_PER_REPO:
                    break
                page += 1
        except Exception as e:  # noqa: BLE001 — one unreadable repo is not fatal
            print(
                f"doug: outcome reconcile skipped {full_name} ({type(e).__name__}: {e})",
                file=sys.stderr,
            )
            continue
        if len(pulls) >= _MAX_CLOSED_PRS_PER_REPO:
            pulls = pulls[:_MAX_CLOSED_PRS_PER_REPO]
            print(
                f"doug: outcome reconcile capped at {_MAX_CLOSED_PRS_PER_REPO} closed PRs "
                f"for {full_name}; the rest were not reconciled this pass",
                file=sys.stderr,
            )
        for p in pulls:
            updated_at = getattr(p, "updated_at", None)
            if isinstance(updated_at, datetime) and _aware(updated_at) < cutoff:
                continue
            merged_at = getattr(p, "merged_at", None)
            if merged_at is None:
                continue  # closed without merging
            merged_at = _aware(merged_at)
            number = getattr(p, "number", None)
            base = getattr(p, "base", None)
            base_ref = getattr(base, "ref", None)
            base_repo_id = getattr(getattr(base, "repo", None), "id", None)
            if not isinstance(number, int):
                continue
            if base_repo_id != repo_id:
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    f"(base repo id {base_repo_id} != installation_repos' {repo_id})",
                    file=sys.stderr,
                )
                continue
            if not isinstance(base_ref, str) or not base_ref:
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    "(missing base.ref)",
                    file=sys.stderr,
                )
                continue
            try:
                detail = gh.rest.pulls.get(owner=owner, repo=name, pull_number=number)
            except Exception as e:  # noqa: BLE001 — one unreadable PR is not fatal
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    f"(pulls.get failed: {type(e).__name__}: {e})",
                    file=sys.stderr,
                )
                continue
            merge_sha = detail.raw_response.json().get("merge_commit_sha")
            if not isinstance(merge_sha, str) or not merge_sha:
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    "(missing merge_commit_sha)",
                    file=sys.stderr,
                )
                continue
            merged_head_sha = getattr(getattr(p, "head", None), "sha", None)
            if not isinstance(merged_head_sha, str):
                merged_head_sha = None
            inserted = store.enqueue_outcome_jobs(
                installation_id, repo_id, number, merge_sha, merged_at, base_ref,
                merged_head_sha=merged_head_sha,
            )
            count += len(inserted)
    return count


def reconcile_all_outcomes() -> int:
    """The outcome lane's analogue of reconcile_all — every active
    installation, and one bad tenant must not stop the rest.

    Deliberately does NOT call ingest.reclaim_stalled(): that sweep exists
    for review_jobs' claim/lease model (a row stuck 'running' because the
    worker holding it died), and outcome_jobs has no such state to
    reclaim — enqueue_outcome_jobs's only two outcomes are 'inserted' and
    'already there' (ON CONFLICT DO NOTHING), never a claim to strand.
    """
    total = 0
    for installation_id in store.active_installations():
        try:
            total += reconcile_outcomes(installation_id)
        except Exception as e:  # noqa: BLE001 — one bad tenant must not stop the rest
            print(
                f"doug: outcome reconcile failed for installation {installation_id} "
                f"({type(e).__name__}: {e})",
                file=sys.stderr,
            )
    return total
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd api && uv run pytest tests/test_worker.py -k "reconcile_outcomes or reconcile_all_outcomes" -v
```

Expected: all pass. Then run the whole file to confirm nothing existing broke:

```bash
cd api && uv run pytest tests/test_worker.py -v
```

- [ ] **Step 6: Commit**

```bash
git add api/doug/worker.py api/tests/test_worker.py
git commit -m "feat(api): add outcome-lane reconciliation (reconcile_outcomes)"
```

---

## Task 2: Wire reconciliation into the two existing lifecycle triggers

**Files:**
- Modify: `api/doug/api.py:73-128` (`_startup_reconcile`), `api/doug/api.py:2147-2171` (`_reconcile_then_drain`)
- Test: `api/tests/test_api.py` (extend `_startup_guards`-based tests near lines 304-506, extend `_hook_env` near line 523, add one new test near line 850)

**Interfaces:**
- Consumes: `worker.reconcile_all_outcomes() -> int`, `worker.reconcile_outcomes(installation_id: int) -> int` (Task 1).
- Produces: nothing new callable — this task only changes what the two existing entrypoints do.

### Why touching shared test helpers is in scope

`_startup_guards` (`test_api.py:282`) does not stub `worker.reconcile_all`/`worker.drain` itself — each test stubs them individually. Six existing tests already stub `worker.reconcile_all` for exactly the reason this task needs: without a stub, `_startup_reconcile` would call the real function, which walks every active installation's real GitHub App auth. One of those six (`test_a_failing_startup_reconcile_neither_escapes_nor_reaches_the_drain`) stubs `reconcile_all` to raise immediately, so execution never reaches the new call at all regardless of any stub — it is correctly excluded below. Of the remaining five, one seeds a real row in `store.installations` (`test_startup_warns_when_verdicts_reference_repos_the_ledger_lacks` calls `store.upsert_installation`), so `store.active_installations()` returns a real installation there and a stray unstubbed call to `reconcile_all_outcomes` would attempt a real GitHub App auth; the other four don't seed one, so it would silently no-op rather than fail — but relying on that incidentally is exactly the kind of fragility this plan is closing elsewhere, so all five get an explicit stub, not just the one that would otherwise break.

Similarly, `_hook_env` (`test_api.py:523`) already stubs `worker.reconcile_installation` for every one of its many callers, specifically so a webhook test does not make a real API call by accident. It must gain the same stub for `worker.reconcile_outcomes` — but as a **silent no-op**, not one that appends to the shared `kicks` list: several existing tests assert `kicks` by exact equality (e.g. `test_installation_created_records_the_account_and_its_repos` and its neighbors: `assert kicks == [(150424894, "reconcile"), "drain"]`), and a stub that also appended to `kicks` would break every one of them for a fact they are not testing. A dedicated new test re-monkeypatches `reconcile_outcomes` to verify it is actually called.

- [ ] **Step 1: Write the failing tests**

In `api/tests/test_api.py`, add `monkeypatch.setattr(worker, "reconcile_all_outcomes", lambda: 0)` to each of these five existing tests, placed immediately next to their existing `monkeypatch.setattr(worker, "reconcile_all", ...)` line (do not otherwise change these five tests yet, other than the one rewritten fully just below — this step only adds the missing stub so Step 3's real change cannot make any of them flake):

- `test_startup_reconciles_the_backlog_before_it_drains_it` (~line 304)
- `test_startup_serves_before_the_reconcile_it_started_finishes` (~line 338)
- `test_startup_warns_when_verdicts_reference_installations_the_ledger_lacks` (~line 444)
- `test_startup_warns_when_verdicts_reference_repos_the_ledger_lacks` (~line 462)
- `test_a_failing_drift_check_never_blocks_the_catchup_sweep` (~line 484)

(`test_a_failing_startup_reconcile_neither_escapes_nor_reaches_the_drain`, ~line 410, needs no change: its stub for `worker.reconcile_all` raises immediately, so execution never reaches the new call at all — that is itself the property the test pins, unchanged.)

Then update `test_startup_reconciles_the_backlog_before_it_drains_it` to assert the new call's position, since that test's whole purpose is asserting call order:

```python
def test_startup_reconciles_the_backlog_before_it_drains_it(monkeypatch):
    calls: list[str] = []
    drained = threading.Event()

    def fake_reconcile() -> int:
        calls.append("reconcile")
        return 3

    def fake_reconcile_outcomes() -> int:
        calls.append("outcome-reconcile")
        return 2

    def fake_drain() -> int:
        calls.append("drain")
        drained.set()
        return 0

    monkeypatch.setattr(worker, "reconcile_all", fake_reconcile)
    monkeypatch.setattr(worker, "reconcile_all_outcomes", fake_reconcile_outcomes)
    monkeypatch.setattr(worker, "drain", fake_drain)
    _startup_guards(monkeypatch, app_enabled=True, ledger=True)

    with TestClient(app):
        assert drained.wait(timeout=5), "startup never reached the drain"
    _join_startup_threads()
    assert calls == ["reconcile", "outcome-reconcile", "drain"]
```

(This replaces the earlier plain `lambda: 0` stub for this one test only — the other five keep the plain no-op stub, since they are not testing ordering.)

Add a new test for the DRIFT-adjacent log line:

```python
def test_startup_logs_how_many_outcome_windows_reconcile_enqueued(monkeypatch, capsys):
    monkeypatch.setattr(worker, "reconcile_all", lambda: 0)
    monkeypatch.setattr(worker, "reconcile_all_outcomes", lambda: 5)
    monkeypatch.setattr(worker, "drain", lambda: None)
    _startup_guards(monkeypatch, app_enabled=True, ledger=True)

    with TestClient(app):
        pass
    _join_startup_threads()
    assert "outcome reconcile enqueued 5 window(s)" in capsys.readouterr().err
```

In `_hook_env` (`test_api.py:523`), add the silent default stub:

```python
def _hook_env(tmp_path, monkeypatch) -> list:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    assert store.enabled()
    kicks: list = []
    monkeypatch.setattr(worker, "drain", lambda *a, **k: kicks.append("drain"))
    monkeypatch.setattr(
        worker,
        "reconcile_installation",
        lambda i, *, trigger="live": kicks.append((i, trigger)),
    )
    # Silent by default — does NOT append to kicks, unlike the stub above.
    # Every _hook_env caller that asserts kicks by exact equality (most of
    # them) is testing something unrelated to outcome reconciliation, and a
    # stub that recorded a kick here would fail all of them for a fact they
    # do not test. test_installation_created_reconciles_outcomes_too
    # re-monkeypatches this one, deliberately, to verify it fires.
    monkeypatch.setattr(worker, "reconcile_outcomes", lambda i: 0)
    return kicks
```

Add the dedicated new test, near `test_the_installation_created_handler_asks_for_the_sweeps_terms` (~line 833):

```python
def test_installation_created_reconciles_outcomes_too(tmp_path, monkeypatch):
    """The outcome lane's own catch-up, on the same event review's already
    gets — a fresh install may already have merges from before the App was
    on it, the same reason reconcile_installation runs here at all."""
    kicks = _hook_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker, "reconcile_outcomes", lambda i: kicks.append(("outcomes", i))
    )
    _webhook(
        "installation",
        {"action": "created", "installation": INSTALLATION, "repositories": []},
    )
    assert kicks == [(150424894, "reconcile"), ("outcomes", 150424894), "drain"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd api && uv run pytest tests/test_api.py -k "startup or installation_created" -v
```

Expected: the two new/updated ordering assertions FAIL (`AttributeError: <module 'doug.worker'> does not have the attribute 'reconcile_all_outcomes'` for tests referencing it, and the ordering test fails with a `calls`/`kicks` mismatch once the attribute exists but the wiring doesn't).

- [ ] **Step 3: Wire the calls into `_startup_reconcile` and `_reconcile_then_drain`**

In `api/doug/api.py`, `_startup_reconcile` currently ends:

```python
        n = worker.reconcile_all()
        print(f"doug: reconcile enqueued {n} job(s)", file=sys.stderr)
        worker.drain()
    except Exception as e:  # noqa: BLE001 — catch-up is best-effort, never fatal
        print(f"doug: startup reconcile failed ({type(e).__name__}: {e})", file=sys.stderr)
```

Change to:

```python
        n = worker.reconcile_all()
        print(f"doug: reconcile enqueued {n} job(s)", file=sys.stderr)
        m = worker.reconcile_all_outcomes()
        print(f"doug: outcome reconcile enqueued {m} window(s)", file=sys.stderr)
        worker.drain()
    except Exception as e:  # noqa: BLE001 — catch-up is best-effort, never fatal
        print(f"doug: startup reconcile failed ({type(e).__name__}: {e})", file=sys.stderr)
```

(Deliberately inside the same outer `try`: cold-start reconciliation is already best-effort/never-fatal for the review lane, and the outcome lane's catch-up belongs to the identical philosophy — unlike the standalone Job in Task 3/4, this is not the fail-loud adjudicator entrypoint.)

`_reconcile_then_drain` currently reads:

```python
def _reconcile_then_drain(installation_id: int) -> None:
    """Heal the backlog, then actually review it.
    ...
    """
    worker.reconcile_installation(installation_id, trigger="reconcile")
    worker.drain()
```

Change to:

```python
def _reconcile_then_drain(installation_id: int) -> None:
    """Heal the backlog, then actually review it.
    ...
    """
    worker.reconcile_installation(installation_id, trigger="reconcile")
    worker.reconcile_outcomes(installation_id)
    worker.drain()
```

(Single-installation `reconcile_outcomes`, matching `reconcile_installation` right above it — not `reconcile_all_outcomes`, which would redundantly re-scan every other tenant on every new install.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd api && uv run pytest tests/test_api.py -v
```

Expected: full file passes, including every test touched in Step 1.

- [ ] **Step 5: Commit**

```bash
git add api/doug/api.py api/tests/test_api.py
git commit -m "feat(api): reconcile the outcome lane on cold start and install"
```

---

## Task 3: `doug/reconcile_worker.py` — standalone Cloud Run Job entrypoint

**Files:**
- Create: `api/doug/reconcile_worker.py`
- Test: `api/tests/test_reconcile_worker.py`

**Interfaces:**
- Consumes: `app_auth.enabled() -> bool` (pre-existing), `worker.reconcile_all_outcomes() -> int` (Task 1).
- Produces: `reconcile_worker.run() -> ReconcileSummary`, `reconcile_worker.main() -> None`. Task 4's Cloud Run Job runs this file as `python -m doug.reconcile_worker`.

### Why a separate Job rather than folding into `outcome_worker.py`

`outcome_worker.py`'s `drain()`/`main()` is deliberately fail-loud: its own comment states *"Pure-classifier and ledger defects are systemic. They escape so the Cloud Run execution is red... counting them as repository attempts would hide a broken deployment."* `main()` has no top-level `try`/`except` — an uncaught exception is the point. Folding a best-effort, per-tenant-isolated reconciliation pass into that same entrypoint means either (a) it inherits fail-loud semantics, so one tenant's GitHub hiccup reds out the whole adjudicator run before it even reaches the due jobs it exists to drain, or (b) it needs its own defensive wrapping bolted onto a function that is deliberately unwrapped everywhere else — a mixed reliability posture in one entrypoint that a future edit could silently simplify away. `reconcile_all_outcomes` already isolates per-installation failures (Task 1); giving it its own entrypoint keeps that isolation intact end to end, and keeps the adjudicator's existing, tested fail-loud contract completely untouched. The cost is one more Cloud Run Job + Scheduler pair (Task 4) — a small, well-precedented amount of new infrastructure in a codebase that already runs exactly this pattern for `doug-adjudicator`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_reconcile_worker.py`:

```python
"""Cloud Run Job entrypoint for outcome-lane reconciliation."""

import pytest

from doug import app_auth, reconcile_worker, worker


def test_run_refuses_without_app_credentials(monkeypatch):
    monkeypatch.setattr(app_auth, "enabled", lambda: False)
    with pytest.raises(RuntimeError, match="DOUG_GITHUB_APP_ID"):
        reconcile_worker.run()


def test_run_reports_the_windows_reconcile_all_outcomes_enqueued(monkeypatch):
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(worker, "reconcile_all_outcomes", lambda: 7)
    summary = reconcile_worker.run()
    assert summary.windows_enqueued == 7


def test_main_prints_the_summary_as_json(monkeypatch, capsys):
    monkeypatch.setattr(app_auth, "enabled", lambda: True)
    monkeypatch.setattr(worker, "reconcile_all_outcomes", lambda: 3)
    reconcile_worker.main()
    out = capsys.readouterr().out
    assert out.strip() == '{"windows_enqueued": 3}'
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd api && uv run pytest tests/test_reconcile_worker.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'doug.reconcile_worker'`.

- [ ] **Step 3: Write `doug/reconcile_worker.py`**

```python
"""Cloud Run Job entrypoint for outcome-lane reconciliation.

Runs worker.reconcile_all_outcomes() on its own cadence, independent of the
adjudicator's daily drain. Kept as its own Job rather than folded into
doug.outcome_worker: the adjudicator's drain() is deliberately fail-loud (a
systemic defect must turn the Cloud Run execution red — outcome_worker.py's
own comment says so), and reconciliation is deliberately best-effort (one
tenant's GitHub API hiccup must not block every other tenant's catch-up,
same as worker.reconcile_all already is for the review lane). Mixing those
two philosophies in one entrypoint risks a future edit quietly dropping
whichever one wasn't the file's obvious default.

See docs/superpowers/plans/2026-08-12-outcome-lane-reconciliation.md for the
full design rationale.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import app_auth, worker


@dataclass(frozen=True)
class ReconcileSummary:
    windows_enqueued: int = 0


def run() -> ReconcileSummary:
    if not app_auth.enabled():
        raise RuntimeError(
            "DOUG_GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must be configured "
            "before reconciling"
        )
    return ReconcileSummary(windows_enqueued=worker.reconcile_all_outcomes())


def main() -> None:
    summary = run()
    print(json.dumps(asdict(summary), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd api && uv run pytest tests/test_reconcile_worker.py -v
```

- [ ] **Step 5: Commit**

```bash
git add api/doug/reconcile_worker.py api/tests/test_reconcile_worker.py
git commit -m "feat(api): add the outcome-reconciliation Cloud Run Job entrypoint"
```

---

## Task 4: Deploy — new Cloud Run Job and Cloud Scheduler entry

**Files:**
- Modify: `api/deploy/gcp.sh`

**Interfaces:**
- Consumes: `doug.reconcile_worker` (Task 3), the existing `$PROJECT`/`$REGION`/`$CONN`/`$SERVICE` variables and `doug-adjudicator-sa` service account this script already sets up for `adjudicator()`.
- Produces: two new named functions, callable exactly like the existing `adjudicator`/`schedule` targets described in the script's own usage header.

### Read first

Correction (post-implementation): this claim was wrong — `api/tests/test_deploy_gcp.py` already exists and already tests this script against a fake `gcloud`. This task's Step 4 shipped without coverage for the two new targets as a result; a later fix wave added it. Before editing, open `api/deploy/gcp.sh` and locate three things by eye, since exact line numbers may have shifted since this plan was written:
1. The usage header near the top (documents each target — this is where the two new targets get documented, following the existing one-line-per-target style: `#   PROJECT=... REGION=... ./deploy/gcp.sh adjudicator # deploy M3 Job`).
2. The `adjudicator()` and `schedule()` function bodies — the exact template Step 1 below mirrors, quoted here as it reads today so this task is checkable without re-opening the script first:

```bash
adjudicator() {
  local api_image prereg_hash
  preregistration_preflight
  prereg_hash=$(compute_prereg_hash)
  api_image=$(gcloud run services describe "$SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --format='value(spec.template.spec.containers[0].image)')
  if [ -z "$api_image" ]; then
    echo "ERROR: $SERVICE has no deployed image; deploy the API first." >&2
    return 1
  fi

  gcloud run jobs deploy "$ADJUDICATOR_JOB" \
    --image "$api_image" \
    --project "$PROJECT" --region "$REGION" \
    --command python --args=-m,doug.outcome_worker \
    --service-account "doug-adjudicator-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest" \
    --set-env-vars "DOUG_GITHUB_APP_ID=4450932,DOUG_PREREG_HASH=$prereg_hash" \
    --memory 2Gi --cpu 1 --tasks 1 --max-retries 0 --task-timeout 3600s
  echo "adjudicator deployed from $api_image"
}

schedule() {
  local scheduler_sa uri action
  scheduler_sa="doug-scheduler-sa@$PROJECT.iam.gserviceaccount.com"
  uri="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$ADJUDICATOR_JOB:run"

  gcloud run jobs add-iam-policy-binding "$ADJUDICATOR_JOB" \
    --project "$PROJECT" --region "$REGION" \
    --member="serviceAccount:$scheduler_sa" --role=roles/run.invoker >/dev/null

  if gcloud scheduler jobs describe "$SCHEDULER_JOB" \
      --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    action=update
  else
    action=create
  fi
  gcloud scheduler jobs "$action" http "$SCHEDULER_JOB" \
    --project "$PROJECT" --location "$REGION" \
    --schedule "0 3 * * *" --time-zone "Etc/UTC" \
    --uri "$uri" --http-method POST \
    --oauth-service-account-email "$scheduler_sa" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --max-retry-attempts 0
  echo "scheduled: $SCHEDULER_JOB -> $ADJUDICATOR_JOB daily at 03:00 UTC"
}
```

`reconcile_job()`/`schedule_reconcile()` below drop `preregistration_preflight`/`compute_prereg_hash` and the `DOUG_PREREG_HASH` env var entirely — reconciliation never adjudicates or publishes, so the hash preflight that guards the adjudicator's Job does not apply to it, and requiring it would block a reconcile deploy on a document this task never touches.
3. The end of `deploy()`, where it currently calls `adjudicator` after the API's own `gcloud run deploy` + smoke-test block — and the dispatch block at the bottom of the file (a `case "$1" in ... esac` or equivalent) that maps CLI subcommands to these functions.

- [ ] **Step 1: Add `reconcile_job()` and `schedule_reconcile()`**

Add these two functions immediately after `schedule()`'s closing brace:

```bash
reconcile_job() {
  local api_image
  api_image=$(gcloud run services describe "$SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --format='value(spec.template.spec.containers[0].image)')
  if [ -z "$api_image" ]; then
    echo "ERROR: $SERVICE has no deployed image; deploy the API first." >&2
    return 1
  fi

  # No DOUG_PREREG_HASH: reconciliation only enqueues outcome_jobs rows, it
  # never adjudicates or publishes anything, so the hash preflight the
  # adjudicator requires does not apply here.
  gcloud run jobs deploy "$RECONCILE_JOB" \
    --image "$api_image" \
    --project "$PROJECT" --region "$REGION" \
    --command python --args=-m,doug.reconcile_worker \
    --service-account "doug-adjudicator-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-cloudsql-instances "$CONN" \
    --set-secrets "DATABASE_URL=doug-database-url:latest,GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest" \
    --set-env-vars "DOUG_GITHUB_APP_ID=4450932" \
    --memory 512Mi --cpu 1 --tasks 1 --max-retries 0 --task-timeout 900s
  echo "outcome reconciler deployed from $api_image"
}

schedule_reconcile() {
  local scheduler_sa uri action
  scheduler_sa="doug-scheduler-sa@$PROJECT.iam.gserviceaccount.com"
  uri="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$RECONCILE_JOB:run"

  gcloud run jobs add-iam-policy-binding "$RECONCILE_JOB" \
    --project "$PROJECT" --region "$REGION" \
    --member="serviceAccount:$scheduler_sa" --role=roles/run.invoker >/dev/null

  if gcloud scheduler jobs describe "$RECONCILE_SCHEDULER_JOB" \
      --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    action=update
  else
    action=create
  fi
  # Every 6 hours, not daily: reconciliation is cheap (no cloning, no model
  # reads — pulls.list + pulls.get only), and the whole point is shrinking
  # the window a lost webhook can sit undiscovered. The adjudicator stays
  # daily because adjudication itself is expensive and nothing about that
  # cadence is what this Job is fixing.
  gcloud scheduler jobs "$action" http "$RECONCILE_SCHEDULER_JOB" \
    --project "$PROJECT" --location "$REGION" \
    --schedule "0 */6 * * *" --time-zone "Etc/UTC" \
    --uri "$uri" --http-method POST \
    --oauth-service-account-email "$scheduler_sa" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --max-retry-attempts 0
  echo "scheduled: $RECONCILE_SCHEDULER_JOB -> $RECONCILE_JOB every 6h"
}
```

- [ ] **Step 2: Add the two new job-name constants**

Immediately after the existing `ADJUDICATOR_JOB=doug-adjudicator` / `SCHEDULER_JOB=doug-adjudicator-daily` lines, add:

```bash
RECONCILE_JOB=doug-outcome-reconciler
RECONCILE_SCHEDULER_JOB=doug-outcome-reconciler-6h
```

- [ ] **Step 3: Wire `reconcile_job` into `deploy()` and add both new targets to the dispatch block**

In `deploy()`, immediately after its existing call to `adjudicator` (find this by searching the function body for `adjudicator` — it is the last non-echo line before the function returns), add a call to `reconcile_job`, in the same style:

```bash
  adjudicator
  reconcile_job
```

In the script's dispatch block at the bottom (find the `case "$1" in` block that currently has an `adjudicator)` and `schedule)` arm), add two new arms in the same style, immediately after the existing `schedule)` arm:

```bash
  reconcile-job)
    reconcile_job
    ;;
  schedule-reconcile)
    schedule_reconcile
    ;;
```

Add the matching lines to the usage header at the top of the file, immediately after the existing `schedule` line:

```
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh reconcile-job # deploy outcome reconciler Job
#   PROJECT=doug-prod0 REGION=us-central1 ./deploy/gcp.sh schedule-reconcile # create/update 6h trigger
```

- [ ] **Step 4: Verify — no automated test exists for this file, so verify by hand**

```bash
cd api && bash -n deploy/gcp.sh
```

Expected: no output (bash `-n` only checks syntax; a non-zero exit or any output means a syntax error to fix before continuing). This does **not** verify the `gcloud` calls themselves — running `reconcile-job`/`schedule-reconcile` against real infrastructure is a deploy-time action outside this plan's scope, and needs its own explicit go-ahead the same way `adjudicator-setup`/`adjudicator`/`schedule` already do in this script's existing usage.

- [ ] **Step 5: Commit**

```bash
git add api/deploy/gcp.sh
git commit -m "feat(deploy): schedule the outcome reconciler as its own Cloud Run Job"
```

---

## Self-review notes (from the writing-plans skill's required pass)

- **Spec coverage:** every gap named in the architecture summary has a task — missing reconciliation function (Task 1), missing wiring into the two existing triggers (Task 2), missing standalone cadence (Tasks 3–4). Nothing in `publication-preregistration.md`'s locked metric logic is touched, and no task modifies `store.enqueue_outcome_jobs`, `adjudicate.py`, or `outcome_backfill.py`.
- **Placeholder scan:** every step has real, complete code — no "add appropriate error handling," no "similar to Task N" elisions. Task 4 is the one exception the plan states explicitly rather than fakes: no test harness exists for `deploy/gcp.sh` in this repository, so its "test" step is a syntax check plus a named, deliberate deferral of the live `gcloud` verification to deploy time.
- **Coverage parity with the mechanism this ports from:** the review lane's own test suite pins pagination (`test_reconcile_installation_paginates_past_the_first_page`) and the pathological-repo cap (`test_reconcile_installation_caps_and_logs_a_pathological_repo`) as separate, named cases — Task 1 mirrors both rather than leaving them as an implicit, unverified consequence of the single-page happy-path tests.
- **Type/name consistency:** `reconcile_outcomes(installation_id: int) -> int` and `reconcile_all_outcomes() -> int` are the exact names and signatures used identically across Tasks 1, 2, and 3. `ReconcileSummary.windows_enqueued` is the one field, used identically in Task 3's implementation and its tests.
