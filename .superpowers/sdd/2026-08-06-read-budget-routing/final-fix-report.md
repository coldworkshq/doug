# Final fix report — read-budget routing

## Result

The approved whole-branch fix wave is implemented as one final-review change.
The gate now treats a code-tier `file_cut` as missed, requires the complete
fixed 30-commit sample and its known 30/30 result, and retains the independent
95% statistical bar. Historical Phase-1 receipts are measured with the
probe's actual 30,000-character budget in both backfill paths. The two PR #50
caller regressions now prove `tenancy.py` arrived whole by pinning
`file_cut == "api/doug/store.py"`.

No live reader, selector, read-order, scoring, or coverage behavior changed in
this wave. `api/scripts/llm_probe.py` remains frozen.

## Strict TDD transcripts

### Gate regression — RED

Command:

```text
cd api && uv run pytest tests/test_read_budget_scripts.py::test_gate_rejects_partially_sent_code_at_the_probe_budget -q
```

Before the fix, the new regression failed for the reproduced defect:

```text
E       AssertionError: assert 0 == 1

all code sent on 29/30 (97%); bar is 95%
PASS
1 failed in 3.14s
```

The old predicate counted only `files_unseen`; it therefore ignored five
commits whose budget landed inside a code file.

### Gate regression — GREEN

After including `file_cut`, de-duplicating missed filenames, and enforcing the
complete fixed sample:

```text
.                                                                        [100%]
1 passed in 3.09s
```

The real fixed range at 30k now produces:

```text
all code sent whole on 24/30 (80%)
statistical bar: >= 95%
fixed-sample sanity: 30/30 SHAs, 30/30 evaluated rows, 24/30 passing; requires 30/30
FAIL
returned: 1
```

### Historical backfill regression — RED

Command:

```text
cd api && uv run pytest tests/test_read_budget_scripts.py::test_historical_probe_coverage_uses_the_probe_budget_and_restores_live_budget -q
```

Before the fix, the synthetic 68k Phase-1 diff was measured with the live
100k ceiling:

```text
E       AssertionError: assert 68036 == 30000
E        +  where 68036 = Coverage(diff_chars=68036, sent_chars=68036,
E           files_sent=1, files_unseen=[], file_cut=None, ...).sent_chars
1 failed in 1.84s
```

### Historical backfill regression — GREEN

After adding `_probe_coverage(diff)` using the imported
`llm_probe.DIFF_BUDGET` under `try/finally` restoration, and routing both the
database and `--emit-sql` paths through it:

```text
.                                                                        [100%]
1 passed in 1.22s
```

The regression asserts `sent_chars == 30_000`, incomplete coverage,
`file_cut == "historical.py"`, and an unchanged live reader budget after the
helper returns.

### Focused final regression set

```text
cd api && uv run pytest tests/test_read_budget_scripts.py \
  tests/test_review.py::test_pr50_fetch_pr_reads_tenancy_at_the_old_budget \
  tests/test_review.py::test_pr50_fetch_open_prs_reads_tenancy_at_the_old_budget -q
....                                                                     [100%]
4 passed in 4.24s
```

Both real caller tests independently produced
`file_cut == "api/doug/store.py"`, while `tenancy.py` was absent from
`files_unseen`; together those facts prove `tenancy.py` arrived whole.

## Full verification

### Tests

```text
$ make test
collected 655 items
...
======================= 655 passed, 1 warning in 12.87s ========================
```

The warning is the existing Starlette `httpx` deprecation warning. No tests
were skipped. The exact post-fix count is **655**.

### Lint

```text
$ make lint
cd api && uv run ruff check .
All checks passed!
cd web && npm run lint
> web@0.1.0 lint
> eslint
```

### Shipped 100k gate

Command: `cd api && uv run python scripts/read_budget_gate.py`

```text
ADR-0012 coverage bar — DIFF_BUDGET = 100,000
range: 30 first-parent commits ending 135c8e5

      sha  files      chars  all-code-whole
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

all code sent whole on 30/30 (100%)
statistical bar: >= 95%
fixed-sample sanity: 30/30 SHAs, 30/30 evaluated rows, 30/30 passing; requires 30/30
PASS
```

Exit code: 0. The shipped result remained exactly 30/30; neither the range,
budget, nor bar was adjusted.

## Files changed in this wave

- `api/doug/intent.py` — current 100k evidence comment.
- `api/doug/reader.py` — module-docstring evidence correction only.
- `api/doug/review.py` — `file_cut`/`files_unseen` docstring correction only.
- `api/scripts/backfill_ledger.py` — probe-budget helper and both callers.
- `api/scripts/read_budget_gate.py` — strict whole-file and fixed-sample gate.
- `api/tests/test_read_budget_scripts.py` — two focused regressions.
- `api/tests/test_review.py` — both caller-level `file_cut` assertions and
  evidence wording.
- `docs/decisions/ADR-0004-llm-reader-in-the-scoring-path.md` — current ADR
  pointer.
- `docs/decisions/ADR-0012-diff-budget-is-governed-by-a-coverage-bar.md` —
  whole-file gate, fixed-sample requirement, and GitHub omission caveat.
- `docs/design/outcome-loop/design-lock.md` — current closed ADR list.
- `docs/superpowers/plans/2026-08-06-read-budget-routing.md` — executable
  snippets, negative regression, historical backfill, scope, and 655 Done
  check.
- `docs/superpowers/specs/2026-08-06-read-budget-routing-design.md` — whole
  PR #50 evidence and strict gate semantics.
- `.superpowers/sdd/2026-08-06-read-budget-routing/final-fix-report.md` — this
  report.

## Frozen-file and executable-scope checks

- `git diff origin/main -- api/scripts/llm_probe.py` produced no output.
- `git diff HEAD -- api/doug/reader.py` contains only the approved module
  docstring correction for this wave.
- An AST comparison of `origin/main:api/doug/reader.py` against the final
  branch, excluding the module docstring and comments, found 49 top-level
  statements on both sides and exactly one executable difference:

  ```text
  AST difference #9: DIFF_BUDGET -> DIFF_BUDGET
    before: DIFF_BUDGET = 30000
    after:  DIFF_BUDGET = 100000
  ```

- No executable change was made to `reader.coverage`, `_sent_slice`,
  `_user_text`, selectors, scoring, `review.read_order`, or either diff-join
  call site.
- `_rebuild_diff` still iterates `pr.file_details` directly and therefore
  preserves the exact original-order Phase-1 pre-slice diff.
- `git diff --check` is clean.

## Self-review

- The gate's `missed_evidence` set unifies `files_unseen` and `file_cut`, then
  `dict.fromkeys` preserves code order while preventing duplicate filenames.
- PASS requires all four facts: 30 requested SHAs, 30 evaluated rows, all 30
  rows passing, and rate at or above `BAR == 0.95`. Empty or incomplete
  samples print their counts and fail.
- The 95% statistical bar and the fixed range's 30/30 sanity result are
  printed separately.
- The gate claim is qualified: local Git covers patches available in Git but
  cannot simulate GitHub `patch=None`; live `files_dropped` receipts remain
  responsible for that hole.
- `_probe_coverage` restores the live module global in `finally`, including
  if `reader.coverage` raises. The backfill command is synchronous, so the
  narrow temporary global override does not introduce concurrent-reader
  ambiguity.
- Both persistence paths call `_probe_coverage`; neither duplicates the
  frozen 30k constant.
- The new tests assert behavior and receipts, not source text or mock calls.

## Concerns

No blocking concern. Two explicit limits remain: the gate cannot reproduce a
GitHub `patch=None` omission from local Git, and historical probe coverage uses
a temporary module-global budget override. The first is covered by production
`files_dropped` receipts; the second is bounded to the synchronous backfill
helper and restored with `try/finally`.
