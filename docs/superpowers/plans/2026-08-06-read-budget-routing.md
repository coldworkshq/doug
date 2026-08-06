# Read-Budget Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the reader see the files that matter — tier the diff before the budget cuts it, and raise the budget where tiering cannot help.

**Architecture:** One pure sort function (`review.read_order`) reorders files before they are joined into the diff string; the existing linear cut at `reader._sent_slice` then admits whole files until one does not fit. No new truncation logic. `DIFF_BUDGET` moves 30,000 → 100,000, which breaks ADR-0002's freeze, so ADR-0012 supersedes it and the cross-pin test splits into "five constants still frozen" plus "one deliberately diverged".

**Tech Stack:** Python 3.14, pytest, ruff. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-06-read-budget-routing-design.md`. Read it before Task 1.
- Branch: `read-budget-routing`, already created, spec committed at `c61f842`. Off `main` @ `135c8e5`.
- Run tests: `make test` (= `cd api && uv run pytest`). Run lint: `make lint`.
- **Baseline is 642 passing in ~12s.** Every task ends green. If the count drops, something was deleted — stop and say so.
- `reader.py`'s **live read path** has exactly one behavior change: the
  `DIFF_BUDGET` integer in Task 4. `SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT`,
  `MAX_TOKENS`, `_user_text`, and `truncation_reason` are not changed. The
  approved final evidence correction may let `_sent_slice`/`coverage` accept an
  explicit historical budget, provided their default remains the live global
  and a regression proves concurrent live coverage is unchanged. Any other
  executable edit there requires a new decision.
- `api/scripts/llm_probe.py` is **never** modified. It is the frozen instrument; its `DIFF_BUDGET = 30_000` is what the probe actually measured.
- Do **not** add a test asserting `PROMPT_HASH` is unmoved by the budget change. `PROMPT_HASH = sha256(SYSTEM + repr(SCHEMA))` — `DIFF_BUDGET` was never an input, so such a test cannot fail and would violate the house rule that a test must be able to fail when behaviour changes. The existing `test_prompt_hash_is_stable_and_changes_with_the_frozen_bytes` already pins the hash's inputs.
- Commit after every task. Conventional-commit prefixes (`feat:`, `test:`, `docs:`).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `api/doug/features.py` | add `_is_prose` beside `_is_test` — path classification lives in one module | 1 |
| `api/tests/test_features.py` | `_is_prose` behaviour | 1 |
| `api/doug/review.py` | add `_read_tier` + `read_order`; call it at both join sites | 2, 3 |
| `api/tests/test_review.py` | ordering behaviour; PR #50 regression; coverage invariant | 2, 3 |
| `api/doug/reader.py` | live `DIFF_BUDGET` change; evidence-only explicit budget with unchanged live default | 4, final review |
| `api/tests/test_reader.py` | split the ADR-0002 cross-pin | 4 |
| `docs/decisions/ADR-0012-diff-budget-is-governed-by-a-coverage-bar.md` | new record | 4 |
| `docs/decisions/ADR-0002-reader-prompt-is-frozen.md` | frontmatter → superseded | 4 |
| `api/scripts/read_budget_gate.py` | the pre-registered exit gate, zero model calls | 5 |
| `api/scripts/backfill_ledger.py` | measure Phase-1 receipts with the probe's historical 30k budget | final review |
| `api/tests/test_read_budget_scripts.py` | real-range negative gate and historical probe-coverage regressions | final review |

---

### Task 1: `_is_prose` in features.py

**Files:**
- Modify: `api/doug/features.py` (add after `_is_test`, ~line 137)
- Test: `api/tests/test_features.py`

**Interfaces:**
- Consumes: existing `LOCKFILES` and `MANIFESTS` sets, `PurePosixPath` (already imported)
- Produces: `features._is_prose(path: str) -> bool`

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_features.py`:

```python
def test_prose_covers_docs_and_lockfiles_but_not_their_manifests():
    """The reader is asked for logic errors, unsafe migrations, concurrency
    hazards, error-handling gaps and contract mismatches (reader.SYSTEM).
    The accepted routing policy ranks prose and generated lockfiles after
    code and tests for that review task.

    A manifest carries real dependency decisions, including conventional
    requirements/constraints variants despite their suffix. Manifests stay
    code."""
    assert features._is_prose("docs/design/outcome-loop/ROADMAP.md")
    assert features._is_prose("README.rst")
    assert features._is_prose("notes.txt")
    assert features._is_prose("web/package-lock.json")
    assert features._is_prose("uv.lock")
    assert features._is_prose("api/CHANGELOG.MD")  # case-insensitive

    assert not features._is_prose("web/package.json")
    assert not features._is_prose("api/pyproject.toml")
    assert not features._is_prose("api/requirements.txt")
    assert not features._is_prose("api/requirements-dev.txt")
    assert not features._is_prose("api/constraints.txt")
    assert not features._is_prose("api/doug/tenancy.py")
    assert not features._is_prose("api/deploy/gcp.sh")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_features.py::test_prose_covers_docs_and_lockfiles_but_not_their_manifests -v`
Expected: FAIL with `AttributeError: module 'doug.features' has no attribute '_is_prose'`

- [ ] **Step 3: Write minimal implementation**

In `api/doug/features.py`, immediately after `_is_test` (~line 137):

```python
_PROSE_SUFFIXES = (".md", ".txt", ".rst")
_DEPENDENCY_TEXT_RE = re.compile(
    r"^(?:requirements|constraints)(?:[-_.].*)?\.txt$", re.IGNORECASE
)


def _is_prose(path: str) -> bool:
    """Files the accepted routing policy ranks after code and tests.

    Used only by the read-budget tiering (review.read_order, ADR-0012), not
    by scoring — a docs-only PR still scores normally, it just loses the
    contest for the reader's budget.

    Lockfiles count as prose deliberately: generated, enormous, and never
    read by a human in review. Known manifests are code and stay tier 0,
    including conventional requirements/constraints variants despite their
    otherwise-prose suffix.
    """
    name = PurePosixPath(path).name
    if name in MANIFESTS or _DEPENDENCY_TEXT_RE.fullmatch(name):
        return False
    return name in LOCKFILES or name.lower().endswith(_PROSE_SUFFIXES)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_features.py -v`
Expected: PASS, all existing feature tests still green

- [ ] **Step 5: Commit**

```bash
git add api/doug/features.py api/tests/test_features.py
git commit -m "feat: classify prose paths for the read budget

Docs and lockfiles cannot contain the defect class reader.SYSTEM asks
for. Manifests can, so they stay code. Lives beside _is_test so path
classification has one home and the tier rule cannot drift from the
scorer on what counts as a test."
```

---

### Task 2: `read_order()` in review.py

**Files:**
- Modify: `api/doug/review.py` (imports at line 24; new functions before `fetch_open_prs`, ~line 111)
- Test: `api/tests/test_review.py`

**Interfaces:**
- Consumes: `features._is_prose` (Task 1), `features._is_test` (existing)
- Produces: `review.read_order(files: list) -> list` — same objects, reordered. `review._read_tier(filename: str) -> int` — 0 code, 1 test, 2 prose. Callers must read `.filename` and `.patch` off each element; nothing else is touched.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_review.py`:

```python
from types import SimpleNamespace


def _f(filename: str, patch_len: int, status: str = "modified"):
    """A GitHub file object as far as read_order cares: .filename + .patch."""
    return SimpleNamespace(
        filename=filename,
        status=status,
        additions=1,
        deletions=0,
        patch="x" * patch_len,
    )


def test_read_order_puts_code_before_tests_before_prose():
    """DIFF_BUDGET cuts the assembled diff linearly, so whatever sorts last
    is what the reader never sees. Prose last is the single biggest win:
    across 30 first-parent commits, 37% of diffs truncated but only 20% had
    CODE over budget — the gap was docs and tests crowding out code."""
    files = [
        _f("docs/ROADMAP.md", 100),
        _f("api/tests/test_tenancy.py", 100),
        _f("api/doug/tenancy.py", 100),
    ]
    assert [f.filename for f in review.read_order(files)] == [
        "api/doug/tenancy.py",
        "api/tests/test_tenancy.py",
        "docs/ROADMAP.md",
    ]


def test_read_order_sends_smallest_first_within_a_tier():
    """Smallest-patch-first usually maximises whole files, which is what lets
    the reader reason correctly rather than half-correctly. The cost — the
    biggest patch in a tier is likeliest to be cut or dropped — is paid visibly
    via coverage.file_cut or coverage.files_unseen, not silently."""
    files = [_f("big.py", 900), _f("small.py", 100), _f("mid.py", 500)]
    assert [f.filename for f in review.read_order(files)] == [
        "small.py",
        "mid.py",
        "big.py",
    ]


def test_read_order_is_deterministic_for_equal_keys():
    """Two files of identical tier and size must not swap between runs.
    A nondeterministic order makes the same head_sha produce different
    reads, which would make verdicts unreproducible and quietly break the
    idempotency pre-read's assumption that a re-run sees the same input."""
    files = [_f("b.py", 100), _f("a.py", 100), _f("c.py", 100)]
    once = [f.filename for f in review.read_order(files)]
    twice = [f.filename for f in review.read_order(list(files))]
    assert once == twice == ["b.py", "a.py", "c.py"]  # input order preserved


def test_read_order_tolerates_files_with_no_patch():
    """GitHub returns binaries and too-large-to-inline files with
    patch=None. They are filtered out at the join, but read_order sees them
    first and must not raise on len(None)."""
    files = [_f("a.py", 100), SimpleNamespace(filename="logo.png", patch=None)]
    assert len(review.read_order(files)) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_review.py -k read_order -v`
Expected: 4 FAIL with `AttributeError: module 'doug.review' has no attribute 'read_order'`

- [ ] **Step 3: Write minimal implementation**

In `api/doug/review.py`, change line 24 from:

```python
from . import intent, intent_providers, reader, settle
```

to:

```python
from . import features, intent, intent_providers, reader, settle
```

Then add, immediately before `def fetch_open_prs` (~line 111):

```python
def _read_tier(filename: str) -> int:
    """Lower tiers reach the model first. See ADR-0012."""
    if features._is_prose(filename):
        return 2
    if features._is_test(filename):
        return 1
    return 0


def read_order(files: list) -> list:
    """The order files reach the model, highest-value first.

    DIFF_BUDGET cuts the assembled diff linearly, so order *is* selection:
    whatever sorts last is what the reader never sees. Two keys — tier
    (code, then tests, then prose) and patch size ascending. Python's sort
    is stable, so files with equal keys keep GitHub's own order; that
    stability is the deterministic tiebreak and is pinned by test.

    Patch length is a cheap proxy for the assembled chunk length; header
    overhead can invert contrived near-ties. Smallest-patch-first usually
    maximises how many files arrive WHOLE, which is what lets the reader
    reason correctly rather than half-correctly. It also makes the largest
    file in a tier the likeliest to be cut or dropped — that file is named
    in coverage.file_cut or coverage.files_unseen and rendered on the check
    run by truncation_reason, so the cost is visible rather than silent.

    Deliberately NOT risk-ordered. features._is_sensitive and _MIGRATION_RE
    fire on zero files in the PRs that motivated this work (tenancy.py,
    keyformat.py, migrations.py all False), and inventing new path
    vocabulary to fix that is the move that already failed replication:
    hotspot_path and config_flag fire zero times across all 12,000 grafana
    PRs because both dictionaries are sentry vocabulary (THESIS.md §1a).
    """
    return sorted(files, key=lambda f: (_read_tier(f.filename), len(f.patch or "")))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_review.py -v`
Expected: PASS, all existing review tests still green

- [ ] **Step 5: Commit**

```bash
git add api/doug/review.py api/tests/test_review.py
git commit -m "feat: read_order() tiers the diff before the budget cuts it

Code before tests before prose, smallest-first within tier. Pure sort;
no new truncation logic — the existing linear cut at _sent_slice does
the admission once the order is right.

Not risk-ordered on purpose: _is_sensitive fires on zero files in the
PRs that motivated this, and inventing path vocabulary is what failed
replication on grafana."
```

---

### Task 3: Wire `read_order` into both join sites

**Files:**
- Modify: `api/doug/review.py:148` (`fetch_open_prs`) and `api/doug/review.py:225` (`fetch_pr`)
- Test: `api/tests/test_review.py`

**Interfaces:**
- Consumes: `review.read_order` (Task 2), `reader.diff_chunk`, `reader.CHUNK_SEPARATOR`, `reader.coverage` (all existing)
- Produces: no new public names. The `diff` string built at both sites is now tier-ordered.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_review.py`:

```python
def _assemble(files):
    """Exactly what fetch_pr/fetch_open_prs build, so these tests exercise
    the real join rather than a lookalike."""
    return reader.CHUNK_SEPARATOR.join(
        reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
        for f in review.read_order(files)
        if f.patch
    )


def _pr50_files():
    """PR #50 (41182c1) at its real per-file sizes. 18 files, 275,858 chars,
    11% coverage — the PR that motivated this work."""
    return [
        _f("api/deploy/gcp.sh", 2126),
        _f("api/doug/api.py", 18606),
        _f("api/doug/check_run.py", 1158),
        _f("api/doug/keyformat.py", 2812),
        _f("api/doug/migrations.py", 3341),
        _f("api/doug/store.py", 15404),
        _f("api/doug/tenancy.py", 13014),
        _f("api/tests/test_api.py", 39769),
        _f("docs/superpowers/plans/2026-08-04-tenant-api-keys.md", 105749),
    ]


def test_pr50_reads_tenancy_at_the_old_budget(monkeypatch):
    """The regression, pinned at the OLD 30k budget so it tests the
    ORDERING alone and stays meaningful independent of Task 4.

    Three consecutive reviews of the tenancy work never read tenancy.py:
    api.py (18,606 chars) ate 62% of the budget purely because 'a' sorts
    before 't'. After tiering, the 13,014-char tenancy.py is sent whole and
    api.py is the one named as unseen."""
    monkeypatch.setattr(reader, "DIFF_BUDGET", 30_000)
    cov = reader.coverage(_assemble(_pr50_files()))

    assert "api/doug/tenancy.py" not in cov.files_unseen
    assert cov.file_cut == "api/doug/store.py"
    assert "api/doug/api.py" in cov.files_unseen


def test_pr50_reads_every_code_file_at_the_shipped_budget():
    """At 100k the ordering plus the raised ceiling send all 57,441 chars
    of PR #50's code. Docs still rank last and still lose — that is the
    design, not a gap."""
    cov = reader.coverage(_assemble(_pr50_files()))

    for code_file in (
        "api/doug/tenancy.py",
        "api/doug/api.py",
        "api/doug/store.py",
        "api/doug/keyformat.py",
        "api/doug/migrations.py",
        "api/doug/check_run.py",
        "api/deploy/gcp.sh",
    ):
        assert code_file not in cov.files_unseen, code_file

    assert "docs/superpowers/plans/2026-08-04-tenant-api-keys.md" in cov.files_unseen


def test_reordering_keeps_coverage_honest(monkeypatch):
    """The invariant reader.py's coverage block exists to protect: a
    partial read must never look like a complete one. Reordering changes
    WHICH files are dropped, so it must not change whether the drop is
    reported — every unsent file still appears in files_unseen, and
    complete stays False."""
    monkeypatch.setattr(reader, "DIFF_BUDGET", 5_000)
    cov = reader.coverage(_assemble(_pr50_files()))

    assert not cov.complete
    assert len(cov.files_unseen) > 0
    sent = {f.filename for f in _pr50_files()} - set(cov.files_unseen)
    assert sent, "at least one file should have been sent"
    assert len(cov.files_unseen) + len(sent) == 9


def test_ordering_is_a_noop_below_the_budget():
    """A PR that fits sends every file no matter how it is ordered. This
    guards against a tiering bug that silently drops a file even when
    there was room for it."""
    files = [_f("docs/a.md", 50), _f("b.py", 50), _f("tests/test_c.py", 50)]
    cov = reader.coverage(_assemble(files))

    assert cov.complete
    assert cov.files_unseen == []
    assert cov.files_sent == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_review.py -k "pr50 or coverage_honest or noop" -v`
Expected: `test_pr50_reads_tenancy_at_the_old_budget` FAILS (`api/doug/tenancy.py` is in `files_unseen`) — this is the bug, reproduced. `test_pr50_reads_every_code_file_at_the_shipped_budget` also FAILS until Task 4 raises the budget.

Note: the two tests that fail for *different* reasons is expected and correct — the first proves the ordering bug, the second proves the budget bug. Do not "fix" the second here.

- [ ] **Step 3: Wire both join sites**

In `api/doug/review.py`, `fetch_open_prs` (~line 148), change:

```python
        diff = reader.CHUNK_SEPARATOR.join(
            reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
            for f in files
            if f.patch
        )
```

to:

```python
        diff = reader.CHUNK_SEPARATOR.join(
            reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
            for f in read_order(files)
            if f.patch
        )
```

In `fetch_pr` (~line 225), make the identical change to the second copy:

```python
    diff = reader.CHUNK_SEPARATOR.join(
        reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
        for f in read_order(files)
        if f.patch
    )
```

- [ ] **Step 4: Run tests**

Run: `cd api && uv run pytest tests/test_review.py -v`
Expected: `test_pr50_reads_tenancy_at_the_old_budget`, `test_reordering_keeps_coverage_honest` and `test_ordering_is_a_noop_below_the_budget` PASS. `test_pr50_reads_every_code_file_at_the_shipped_budget` still FAILS — it needs Task 4.

Then: `cd api && uv run pytest` — everything except that one test passes.

- [ ] **Step 5: Commit**

```bash
git add api/doug/review.py api/tests/test_review.py
git commit -m "feat: order the diff at both join sites

fetch_pr and fetch_open_prs each built the diff string with their own
copy of the join; both now order first. PR #50's shape is pinned as a
regression at the old 30k budget, so it keeps testing the ordering
after the budget moves.

One test is red on purpose: reading all of PR #50's code needs the
budget raise in the next commit."
```

---

### Task 4: `DIFF_BUDGET` → 100,000, ADR-0012, cross-pin split

This is the ADR-0002 boundary. The constant, its governance, and the test that enforces the governance land together or `main` is inconsistent.

**Files:**
- Modify: `api/doug/reader.py:35`
- Modify: `api/tests/test_reader.py:567-589`
- Create: `docs/decisions/ADR-0012-diff-budget-is-governed-by-a-coverage-bar.md`
- Modify: `docs/decisions/ADR-0002-reader-prompt-is-frozen.md` (frontmatter only)

**Interfaces:**
- Consumes: nothing new
- Produces: `reader.DIFF_BUDGET == 100_000`; `llm_probe.DIFF_BUDGET` stays `30_000`

- [ ] **Step 1: Write the failing test**

In `api/tests/test_reader.py`, replace **only** the function `test_reader_and_probe_share_the_validated_prompt_bytes` (starts line 567, its last assert is line 589) with the pair below. The next function in the file, `test_prompt_hash_is_stable_and_changes_with_the_frozen_bytes`, must be left exactly as it is — it pins the hash's inputs and is what makes the "do not add a PROMPT_HASH budget test" constraint safe.

Note the assertion list **grows**: ADR-0002 always claimed six constants were frozen but the test only checked four — `MAX_TOKENS` and `EFFORT` were never pinned.

```python
def test_reader_and_probe_share_the_validated_prompt_bytes():
    """ADR-0002 froze six constants byte-identical to scripts/llm_probe.py,
    the module the Phase-1 probes actually validated (AUC 0.687/0.668,
    pre-registered, replicated). llm_probe.py keeps its own independent
    copies (unlike SLUG_MERGES, which it imports from doug.patterns), so
    only a real cross-module comparison can catch the two drifting — at
    which point the live service would be running an unvalidated
    instrument under a validated instrument's claimed AUC.

    ADR-0012 supersedes ADR-0002 and narrows the freeze to FIVE constants;
    DIFF_BUDGET is now governed by a coverage bar instead and is asserted
    separately below. MAX_TOKENS and EFFORT are pinned here for the first
    time — ADR-0002 always claimed them, this test never checked them."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import llm_probe

    assert reader.SYSTEM == llm_probe.SYSTEM
    assert reader.SCHEMA == llm_probe.SCHEMA
    assert reader.MODEL == llm_probe.MODEL
    assert reader.MAX_TOKENS == llm_probe.MAX_TOKENS
    assert reader.EFFORT == llm_probe.EFFORT


def test_diff_budget_diverges_from_the_probe_on_purpose():
    """ADR-0012. The probe's DIFF_BUDGET stays at the 30,000 it actually
    measured; the shipped reader reads more. Asserting BOTH sides pins the
    divergence as intentional and sized: anyone who 'fixes the drift' by
    syncing either constant to the other breaks this test and gets sent to
    ADR-0012 rather than silently re-anchoring the instrument.

    The consequence this encodes, which ADR-0012 states in full: AUC
    0.687 sentry / 0.668 grafana describe the 30,000-char configuration,
    not what ships."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import llm_probe

    assert reader.DIFF_BUDGET == 100_000
    assert llm_probe.DIFF_BUDGET == 30_000
    assert reader.DIFF_BUDGET > llm_probe.DIFF_BUDGET
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_reader.py -k "validated_prompt_bytes or diverges" -v`
Expected: `test_diff_budget_diverges_from_the_probe_on_purpose` FAILS with `assert 30000 == 100000`

- [ ] **Step 3: Change the constant**

In `api/doug/reader.py`, line 35, change:

```python
DIFF_BUDGET = 30_000  # chars
```

to:

```python
# chars. Governed by ADR-0012's coverage bar, NOT by the probe — the
# probe's own DIFF_BUDGET stays at the 30,000 it measured. 100,000 is
# where code+tests coverage saturates (100%/97% over 30 first-parent
# commits) at +$0.019 mean per read; the budget is a ceiling, not a
# spend, and 63% of PRs already fit under 30,000.
DIFF_BUDGET = 100_000
```

- [ ] **Step 4: Run the full suite**

Run: `cd api && uv run pytest`
Expected: PASS — including `test_pr50_reads_every_code_file_at_the_shipped_budget` from Task 3, which was deliberately red.

If `tests/test_coverage.py` is slow now, that is expected: several of its cases build strings sized from `reader.DIFF_BUDGET`. If any of them *fail*, stop — they use relative sizes and should be budget-agnostic; a failure means one hardcoded 30,000 somewhere.

- [ ] **Step 5: Write ADR-0012**

Create `docs/decisions/ADR-0012-diff-budget-is-governed-by-a-coverage-bar.md`:

```markdown
---
title: Govern DIFF_BUDGET by a coverage bar, not by the probe
status: accepted
date: 2026-08-06
supersedes: ADR-0002
---

## Context

ADR-0002 froze six constants byte-identical to `scripts/llm_probe.py` at
commit `0064e6b`: `SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT`, `MAX_TOKENS` and
`DIFF_BUDGET`. The reasoning holds for five of them. It does not hold for
`DIFF_BUDGET`, and keeping it frozen has a measured cost.

`DIFF_BUDGET` is 30,000 characters — roughly 7,500 tokens, on a model with
a 1M-token context window. Measured over the last 30 first-parent commits:

| | share |
|---|---|
| Diff exceeds the budget | 37% |
| **Code alone** exceeds the budget | 20% |

Three consecutive reviews of the tenancy work never read `tenancy.py`. On
PR #50 (`41182c1`), `api.py` consumed 18,606 chars — 62% of the whole
budget — because `a` sorts before `t`, and the 13,014-char `tenancy.py`
was never sent. Ordering the diff (`review.read_order`) fixes the 17-point
gap where prose and tests crowd out code. It cannot fix the 20% where code
alone exceeds the budget: at 30,000 characters you are choosing which half
of PR #50's 57,441 chars of code to miss, not whether to miss it.

The five other constants have no equivalent problem. Nothing about the
prompt, schema, model, effort or output cap is measurably wrong.

## Decision

`SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT` and `MAX_TOKENS` remain frozen
byte-identical to `scripts/llm_probe.py`, pinned by
`test_reader_and_probe_share_the_validated_prompt_bytes`. ADR-0002's rule
survives for them intact.

`DIFF_BUDGET` is removed from the freeze and governed instead by a
pre-registered coverage bar:

> **Every code-tier file sent whole on ≥95% of PRs**, over the 30
> first-parent commits ending at `135c8e5`.

It is set to **100,000 characters**. The bar is checked by
`api/scripts/read_budget_gate.py`, which costs **zero model calls** —
`reader.coverage` is a pure function over the assembled diff, so the
governing metric is verifiable by anyone at any time without spending a
cent. That is the property that makes a coverage bar a safe replacement
for a freeze.

The pinned range is also a fixed sanity sample with a known 30/30 result.
The shipped gate requires exactly 30 SHAs, exactly 30 evaluated rows, and
30/30 whole-code rows; the 95% statistical bar does not permit this fixed
sample to shrink or regress. A code-tier `file_cut` is a miss, not a sent
file. Local Git reconstructs every patch available in Git but cannot model
GitHub `patch=None` omissions; live `files_dropped` receipts cover that
separate production hole.

The probe's own `DIFF_BUDGET` stays at 30,000. It is the frozen
instrument and must keep reporting what it actually measured.

## Rejected

**Leave `DIFF_BUDGET` frozen and ship ordering alone.** Leaves 20% of PRs
with code the reader structurally cannot see. Ordering would improve which
half is missed while the miss itself stayed guaranteed.

**Edit ADR-0002 in place.** Would erase the record of what was frozen and
why. Worse here than in an ordinary codebase: `docs/decisions/README.md`
records that these files are an input to Doug's own reader, so a stale
record does not merely mislead a human, it produces a confident false
finding. A record still claiming `DIFF_BUDGET` was frozen at 30,000 would
have generated exactly that on the PR that changed it.

**60,000.** Covers 100% of code in the sample but only 83% of code+tests.
Tests are load-bearing for this reader: `reader.py`'s coverage comment
records lema#643, where the mutation-verified test file that would have
deduped two findings was never sent.

**200,000.** +$0.007 per read over 100,000 for three points of docs
coverage, on files deliberately ranked last because they are lower-signal
for the defect class the reader is asked for.

**Re-run the probe at 100,000 to keep the AUC claim attached to what
ships.** Costs real money on the 653-PR corpus. Declined (Andrew,
2026-08-06) in favour of recording the limit honestly — see Consequences.

## Consequences

- Coverage at 100,000, with tiering, over the pinned range: **100% of code
  sent, 97% of code+tests**, at **+$0.019 mean per read** ($0.056 →
  $0.074). The budget is a ceiling, not a spend: median diff is 21,785
  chars, so 63% of PRs already fit under 30,000 and cost nothing more. A
  PR that saturates 100,000 costs about +$0.09.
- **"The shipped reader is the one that scored AUC 0.687 sentry / 0.668
  grafana" is now false.** Those figures describe the 30,000-character
  configuration in its original file order. The prompt, schema, model and
  effort are unchanged, but the live input now differs in both amount and
  order. Neither change was measured by that probe. Historical backfill
  receipts deliberately retain the probe's original order and 30,000-character
  cut so they describe what actually ran. Any future citation of those AUC
  figures must name the configuration that produced them. This is the price
  of the decision, paid openly rather than hidden.
- Spend caps are unaffected in shape. `_charge(scope)` still runs before
  the client is constructed and still counts reads, not tokens. The
  4,000 reads/installation/month ceiling now admits a more expensive
  read, which is the intent.
- `PROMPT_HASH` is unmoved: it is `sha256(SYSTEM + repr(SCHEMA))` and
  `DIFF_BUDGET` was never an input. Verdicts written before and after this
  change stay comparable on prompt identity, and the M3 receipt that
  carries the hash does not silently re-anchor.
- Raising the budget again is not free: it needs a new pre-registered bar
  and a new record. The friction ADR-0002 created is retained, moved from
  "never change this" to "change it against a stated, checkable bar".
```

- [ ] **Step 6: Mark ADR-0002 superseded**

In `docs/decisions/ADR-0002-reader-prompt-is-frozen.md`, change the frontmatter from:

```markdown
---
title: Freeze the reader's prompt and schema to the validated probe
status: accepted
date: 2026-07-29
---
```

to:

```markdown
---
title: Freeze the reader's prompt and schema to the validated probe
status: superseded
date: 2026-07-29
superseded_by: ADR-0012
---
```

Change nothing else in the file. Its Context, Decision, Rejected and
Consequences are the historical record of what was frozen and why, and
`docs/decisions/README.md` says only `accepted` records are fed to the
reader — flipping the status is what stops it producing a false finding.

- [ ] **Step 7: Run everything**

Run: `cd api && uv run pytest` — expect 642 + new tests, all green
Run: `make lint` — expect clean

- [ ] **Step 8: Commit**

```bash
git add api/doug/reader.py api/tests/test_reader.py docs/decisions/
git commit -m "feat: DIFF_BUDGET 30k -> 100k, governed by a coverage bar

ADR-0012 supersedes ADR-0002. Five constants stay frozen to the probe;
DIFF_BUDGET moves to a pre-registered coverage bar that costs zero model
calls to verify, because reader.coverage is pure.

New ADR rather than an in-place edit: decision records feed Doug's own
reader, so a record still claiming 'frozen at 30,000' would have produced
a confident false finding on this very PR.

The cross-pin test splits and GROWS — ADR-0002 always claimed six frozen
constants but only four were ever asserted; MAX_TOKENS and EFFORT are
pinned here for the first time.

Records the honest limit: AUC 0.687/0.668 describe the 30k config, not
what ships. We are not re-running the probe."
```

---

### Task 5: Exit-gate script and stale-number sweep

**Files:**
- Create: `api/scripts/read_budget_gate.py`
- Test: `api/tests/test_read_budget_scripts.py` runs the real fixed range at
  30k and proves the gate fails at strict 24/30 rather than false-passing at
  29/30.

**Interfaces:**
- Consumes: `doug.review.read_order`, `doug.reader` (`DIFF_BUDGET`, `diff_chunk`, `CHUNK_SEPARATOR`, `coverage`), `doug.features._is_prose`/`_is_test`
- Produces: exit code 0 (bar met) or 1 (bar missed), plus a printed table

- [ ] **Step 1: Write the gate**

Create `api/scripts/read_budget_gate.py`:

```python
"""ADR-0012's pre-registered coverage bar, checked against real history.

    uv run python scripts/read_budget_gate.py

The statistical bar: every code-tier file sent whole on >=95% of PRs, over
the 30 first-parent commits ending at END_SHA. This pinned range is also a
fixed sanity sample whose observed result is 30/30; the shipped gate requires
that exact sample and result rather than silently accepting a smaller set.

Costs ZERO model calls — reader.coverage is pure over the assembled diff
string, so the metric governing DIFF_BUDGET is verifiable by anyone at any
time without spending a cent. That property is why a coverage bar is a
safe replacement for ADR-0002's freeze.

END_SHA is pinned rather than "the last 30 commits" on purpose: a moving
window would drift under the gate and let a later commit re-open it
silently.

Honest limit, stated rather than discovered later: this reconstructs every
patch available in local Git. Its per-file output carries `diff --git` and
index headers that GitHub's `f.patch` does not, so those reconstructed sizes
run slightly larger than the service input. Local Git cannot model a separate
GitHub API omission where `patch=None`; production `files_dropped` receipts
cover that hole. This gate therefore makes no universal no-false-pass claim.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doug import features, reader, review  # noqa: E402

END_SHA = "135c8e5"
N_COMMITS = 30
BAR = 0.95
REPO = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True
    ).stdout


class _File:
    """The subset of a GitHub file object that read_order and diff_chunk read."""

    def __init__(self, filename: str, patch: str):
        self.filename = filename
        self.patch = patch
        self.status = "modified"
        self.additions = 1
        self.deletions = 0


def _files_for(sha: str) -> list[_File]:
    names = [n for n in _git("diff", "--name-only", f"{sha}^", sha).splitlines() if n]
    out = []
    for name in names:
        patch = _git("diff", f"{sha}^", sha, "--", name)
        if patch:
            out.append(_File(name, patch))
    return out


def _is_code(filename: str) -> bool:
    return not features._is_prose(filename) and not features._is_test(filename)


def main() -> int:
    shas = _git("log", "--first-parent", f"-{N_COMMITS}", "--format=%h", END_SHA).split()
    rows, met = [], 0

    for sha in shas:
        files = _files_for(sha)
        if not files:
            continue
        diff = reader.CHUNK_SEPARATOR.join(
            reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
            for f in review.read_order(files)
        )
        cov = reader.coverage(diff)
        code = [f.filename for f in files if _is_code(f.filename)]
        missed_evidence = set(cov.files_unseen)
        if cov.file_cut is not None:
            missed_evidence.add(cov.file_cut)
        missed = list(dict.fromkeys(f for f in code if f in missed_evidence))
        ok = not missed
        met += ok
        rows.append((sha, len(files), cov.diff_chars, ok, missed))

    total = len(rows)
    rate = met / total if total else 0.0

    print(f"ADR-0012 coverage bar — DIFF_BUDGET = {reader.DIFF_BUDGET:,}")
    print(f"range: {N_COMMITS} first-parent commits ending {END_SHA}\n")
    print(f"{'sha':>9}  {'files':>5}  {'chars':>9}  all-code-whole")
    print("-" * 46)
    for sha, nfiles, chars, ok, missed in rows:
        mark = "yes" if ok else f"NO  {', '.join(missed[:2])}"
        print(f"{sha:>9}  {nfiles:>5}  {chars:>9,}  {mark}")

    print(f"\nall code sent whole on {met}/{total} ({rate:.0%})")
    print(f"statistical bar: >= {BAR:.0%}")
    print(
        f"fixed-sample sanity: {len(shas)}/{N_COMMITS} SHAs, "
        f"{total}/{N_COMMITS} evaluated rows, {met}/{N_COMMITS} passing; "
        f"requires {N_COMMITS}/{N_COMMITS}"
    )
    sample_complete = len(shas) == N_COMMITS and total == N_COMMITS
    if sample_complete and met == N_COMMITS and rate >= BAR:
        print("PASS")
        return 0
    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the gate**

Run: `cd api && uv run python scripts/read_budget_gate.py`
Expected: `PASS`, with `all code sent whole on 30/30 (100%)` and the
fixed-sample sanity line showing exactly 30 SHAs and 30 evaluated rows.

Run the focused negative regression with `reader.DIFF_BUDGET` monkeypatched
to the probe's 30k ceiling. Expected: strict `24/30 (80%)`, `FAIL`, exit 1.

If it reports below 100%, do not adjust the bar — report the numbers and stop. The measured max code-only in this range is 58,977 chars, well inside 100,000, so a miss means the tiering or the gate is wrong, not the budget.

- [ ] **Step 3: Sweep for stale statements of the old number**

Run:

```bash
grep -rn "30,000\|30_000\|30000" --include=*.md --include=*.py . \
  | grep -v node_modules | grep -v .venv | grep -v worktrees
```

Every hit must be one of:
- `scripts/llm_probe.py` — correct, the probe keeps its measured value
- `docs/decisions/ADR-0002-*` — correct, historical record, now `superseded`
- `docs/decisions/ADR-0012-*` or the spec — correct, they discuss the change
- `tests/test_reader.py` — correct, pins the probe side of the divergence
- `tests/test_review.py` — correct, the monkeypatched old-budget regression

Anything else is a doc asserting a value that is no longer true — fix it. Pay particular attention to `docs/REVIEWING.md` and `docs/design/outcome-loop/ROADMAP.md`; a stale sentence there is read by Doug's own reader.

- [ ] **Step 4: Full verification**

```bash
make test    # 655 passed after the two final-review regressions
make lint    # clean
cd api && uv run python scripts/read_budget_gate.py   # PASS
```

- [ ] **Step 5: Commit**

```bash
git add api/scripts/read_budget_gate.py
git add -u
git commit -m "test: ADR-0012's coverage bar as a runnable gate

Pins the commit range rather than taking 'the last 30', which would
drift under the gate. Zero model calls — reader.coverage is pure, so
the metric governing DIFF_BUDGET is checkable by anyone for free.

Reconstructs diffs from git, whose per-file output carries headers
GitHub's f.patch does not, so sizes run slightly large and the gate
cannot model GitHub patch=None omissions; production files_dropped
receipts cover that separate hole."
```

---

### Final-review correction: historical probe receipts

Phase-1 backfill reconstructs the exact pre-slice diff in the probe's original
file-detail order. Both database and `--emit-sql` paths must call a shared
`_probe_coverage(diff)` helper that passes `llm_probe.DIFF_BUDGET` explicitly to
`reader.coverage`. The live `reader.DIFF_BUDGET` global is never mutated. The
constant is imported from the frozen probe, never duplicated. The regression
pauses coverage in another thread and requires the live budget to remain 100k
during the historical call, plus `sent_chars == 30_000`, incomplete coverage,
and the expected `file_cut`.

`api/scripts/llm_probe.py` remains frozen. No selector, scoring, live-read, or
read-order behavior changes in this correction; the new coverage keyword is
for evidence reconstruction and defaults to the live budget.

---

## Done means

- [ ] `make test` green, 655 (the observed post-fix count; two focused final-review regressions added)
- [ ] `make lint` clean
- [ ] `uv run python scripts/read_budget_gate.py` exits 0 with strict 30/30 whole-code coverage; the real-range 30k regression exits 1 at 24/30
- [ ] `reader.py`'s live path changes only `DIFF_BUDGET`; historical coverage may pass an explicit budget without mutating the live global
- [ ] `git diff origin/main -- api/scripts/llm_probe.py` is empty
- [ ] ADR-0002 status is `superseded`, ADR-0012 is `accepted`
- [ ] No doc outside the allow-list in Task 5 Step 3 still asserts a 30,000 budget
- [ ] One consolidated final-review `fix:` commit contains the correction wave

Then open the PR and let Doug review it. This repo's convention is to verify each finding by reproduction before fixing or dismissing — roughly half of Doug's findings on its own PRs are disproved by files outside the diff. Log every finding to `docs/findings-log.jsonl` (25 rows today: 12 disproved, 8 real, 5 adjacent) whichever way it goes.
