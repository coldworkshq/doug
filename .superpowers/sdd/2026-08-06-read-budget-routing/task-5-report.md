# Task 5 report — ADR-0012 runnable gate and reconciliation

## Delivered

- Added `api/scripts/read_budget_gate.py` exactly as pre-registered: fixed `END_SHA = "135c8e5"`, 30 first-parent commits, a 95% bar, and no model calls.
- Corrected the source implementation plan's final count to `653 (642 baseline + 11 net new tests)`.
- Replaced the six specified current-policy ADR-0002 statements with ADR-0012 / its retained five-constant freeze.
- Corrected the stale current `docs/REVIEWING.md` coverage example from the former 30k ceiling to the 100k ceiling.

## Gate output

```text
ADR-0012 coverage bar — DIFF_BUDGET = 100,000
range: 30 first-parent commits ending 135c8e5

      sha  files      chars  all-code-sent
----------------------------------------------
  135c8e5      1        785  yes
  e1aea0f     12     53,703  yes
  d91b521      6      8,100  yes
  f781fb2      2      5,065  yes
  34aaa4e      3     13,906  yes
  41182c1     18    276,775  yes
  f065f0d     11     29,275  yes
  ed5aa3e     11    129,549  yes
  0d3e10e      1      1,359  yes
  9090dce      2      6,728  yes
  5b06214      3      8,634  yes
  024fd6c     10     31,839  yes
  8d4ab1c     12     65,870  yes
  5757fe8      9     46,268  yes
  3f7d156      2     10,127  yes
  5310e29      9     34,899  yes
  05e128b     15    114,604  yes
  a8cc396     14     72,500  yes
  eb1783a      5     20,333  yes
  0320e6a      6     22,227  yes
  47379ea     16     81,618  yes
  bf07cd5      4     28,058  yes
  f3fcee8      1      7,155  yes
  816d730      6     15,848  yes
  f05bc12      6     39,416  yes
  5ffa415      4     30,429  yes
  4f576e7      6    112,836  yes
  0fbb3eb      4     20,390  yes
  97ae636     10     48,180  yes
  079e646      7     51,338  yes

all code sent on 30/30 (100%); bar is 95%
PASS
```

The gate was run before the sweep and again after the full test/lint run; both runs produced the output above and exited zero.

## Stale-number sweep

Executed the required grep under zsh with `noglob` (the literal unquoted `--include=*.md` form otherwise errors before grep runs). The only stale current statement was `docs/REVIEWING.md:82-87`; it now uses `100,000 of 120,481` and the matching 121k example.

Every remaining hit was retained, with this disposition:

| Hits | Disposition |
| --- | --- |
| `docs/decisions/ADR-0012-*:15,28,54,67,88,91` | Allow-list: the accepted ADR describes the old 30k configuration, frozen probe, and resulting decision. |
| `docs/superpowers/plans/2026-08-06-read-budget-routing.md:7,18,328,458,494,501,510,517,524,531,534,543,564,577,603,616,637,640,704,855,902` | Source plan / embedded implementation and ADR record. Historical text retained; only its final test-count line was corrected. |
| `docs/superpowers/plans/2026-07-31-step-2-github-app-webhook-ingest.md:1600` | Historical plan fixture. |
| `docs/superpowers/specs/2026-08-06-read-budget-routing-design.md:9,58,110,112,120,132,155,168,221` | Historical design explaining the 30k-to-100k decision. |
| `api/doug/reader.py:36,39,379` | Approved final reader comments: probe value and historical lema#643 evidence; no Task 5 edit. |
| `api/tests/test_reader.py:596,603,612` | Allow-list: explicitly pins the probe-side divergence. |
| `api/tests/test_coverage.py:58,123,157` | Synthetic monkeypatched budget fixtures, not a live-policy assertion. |
| `api/tests/test_check_run.py:41` | Coverage rendering fixture. |
| `api/tests/test_store.py:463,476` | Stored historical coverage fixture. |
| `api/tests/test_review.py:514,525` | Allow-list: old-budget routing regressions. |
| `api/scripts/llm_probe.py:55` | Allow-list: measured frozen probe stays at 30k; file is unchanged. |
| `.superpowers/sdd/2026-08-06-read-budget-routing/task-3-report.md:46,85` | Historical Task 3 report. |
| `.superpowers/sdd/2026-08-06-read-budget-routing/task-4-report.md:11` | Historical red-phase assertion evidence. |
| `.superpowers/sdd/2026-08-06-read-budget-routing/task-3-brief.md:50` | Historical task brief fixture. |
| `.superpowers/sdd/2026-08-06-read-budget-routing/task-4-brief.md:13,49,56,65,72,79,86,89,98,119,132,158,171,192,195,259` | Historical Task 4 requirements and embedded ADR text. |
| `.superpowers/sdd/2026-08-06-read-budget-routing/task-5-brief.md:139,186` | This task's historical command and allow-list requirements. |

## ADR-0002 sweep

Updated the requested current statements in `api/doug/review.py`, `api/doug/settle.py`, `api/doug/findings_log.py`, `docs/REVIEWING.md:183`, `docs/design/outcome-loop/design-lock.md`, and both current champion/challenger statements in `docs/design/outcome-loop/addendum-agentic-architecture.md`.

Retained all other ADR-0002 references as historical ADRs, old plans/specs, roadmap/build-plan material, fixture references, examples, or retrospective prose. `docs/REVIEWING.md:493` is a historical self-referential-test example. `api/doug/reader.py:120` is an approved, untouched historical prompt comment.

Status check:

```text
docs/decisions/ADR-0002-reader-prompt-is-frozen.md: status: superseded
docs/decisions/ADR-0002-reader-prompt-is-frozen.md: superseded_by: ADR-0012
docs/decisions/ADR-0012-diff-budget-is-governed-by-a-coverage-bar.md: status: accepted
```

## Full verification output

```text
$ make test
cd api && uv run pytest
============================= test session starts ==============================
platform darwin -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andrew/Projects/doughq/repo/api
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.2
collected 653 items

tests/test_api.py ...................................................... [  8%]
........................................................................ [ 19%]
.............                                                            [ 21%]
tests/test_app_auth.py ........                                          [ 22%]
tests/test_backtest.py .........................                         [ 26%]
tests/test_check_run.py ..........................                       [ 30%]
tests/test_coverage.py ....................                              [ 33%]
tests/test_deploy_gcp.py ...                                             [ 33%]
tests/test_deviations.py .....................                           [ 37%]
tests/test_features.py ...................                               [ 39%]
tests/test_findings_log.py .......                                       [ 41%]
tests/test_git_labels.py ..................                              [ 43%]
tests/test_hotspots.py .....                                             [ 44%]
tests/test_ingest.py ....................................                [ 50%]
tests/test_intent.py .........................                           [ 53%]
tests/test_keyformat.py ......                                           [ 54%]
tests/test_migrations.py ..................                              [ 57%]
tests/test_pattern_precision.py ............                             [ 59%]
tests/test_patterns.py ....                                              [ 60%]
tests/test_reader.py ................................                    [ 64%]
tests/test_review.py ...........................                         [ 69%]
tests/test_scoring.py ..........                                         [ 70%]
tests/test_settle.py ..................                                  [ 73%]
tests/test_store.py .................................................... [ 81%]
......................................                                   [ 87%]
tests/test_tenancy.py .................................                  [ 92%]
tests/test_worker.py ................................................... [100%]

=============================== warnings summary ===============================
.venv/lib/python3.14/site-packages/fastapi/testclient.py:1
  /Users/andrew/Projects/doughq/repo/api/.venv/lib/python3.14/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

======================= 653 passed, 1 warning in 10.09s ========================

$ make lint
cd api && uv run ruff check .
All checks passed!
cd web && npm run lint

> web@0.1.0 lint
> eslint
```

## Frozen-file and commit checks

- `git diff origin/main -- api/scripts/llm_probe.py` was empty.
- `git diff 3000f0c49949a911cdd12414afdbcd769f387f70 -- api/doug/reader.py` was empty: Task 5 made no reader change.
- `git diff --check` was clean.
- Before this Task 5 commit, the four implementation commits were `fe490cc`, `255cc98`, `bd52eb3`, and `3000f0c`; this commit is the fifth.

## Files changed

- `api/scripts/read_budget_gate.py`
- `api/doug/review.py`, `api/doug/settle.py`, `api/doug/findings_log.py`
- `docs/REVIEWING.md`
- `docs/design/outcome-loop/design-lock.md`
- `docs/design/outcome-loop/addendum-agentic-architecture.md`
- `docs/superpowers/plans/2026-08-06-read-budget-routing.md`
- this report

## Self-review and concerns

The gate uses the specified Git reconstruction and conservatively includes Git headers that GitHub's patch payload omits. No selector, coverage, read-order, budget, ADR body, or test changed. The sole concern is the known pre-existing Starlette deprecation warning reported by the full suite.
