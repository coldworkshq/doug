# Read-budget routing: order the diff, then raise the ceiling

**Status:** design approved (Andrew, 2026-08-06) · **Milestone:** none — reader
quality, ahead of M3
**Closes:** HANDOFF "Next 3" — read-budget routing (#3)

Doug's thesis is that model attention is scarce and should be routed to where
the risk is. Inside its own deep read, it routes alphabetically. `DIFF_BUDGET`
cuts the assembled diff at 30,000 characters in whatever order GitHub's
`list_files` returned, so which files the reader sees is decided by path
sorting.

---

## The evidence

Three consecutive reviews of the tenancy work never read `tenancy.py`.
Reconstructing where the cut landed on PR #50 (`41182c1`, 18 files, 275,858
chars, 11% coverage):

| | file | chars | sent |
|---|---|---|---|
| | `api/deploy/gcp.sh` | 2,126 | full |
| | `api/doug/api.py` | **18,606** | full — **62% of the entire budget** |
| | `api/doug/check_run.py` | 1,158 | full |
| | `api/doug/keyformat.py` | 2,812 | full |
| | `api/doug/migrations.py` | 3,341 | full |
| | `api/doug/store.py` | 15,404 | cut at 1,957 |
| ← | `api/doug/tenancy.py` | 13,014 | **never sent** |
| | 5 test files | 80,631 | never sent |
| | 4 docs files | 133,017 | never sent |

`api.py` sorts before `tenancy.py`. That is the whole mechanism.

**The plan of record does not fix this.** HANDOFF proposed routing "by sensitive
paths first". Doug's own predicates were run against the file list:

```
api/doug/tenancy.py      sensitive=False  test=False  migration=False
api/doug/keyformat.py    sensitive=False  test=False  migration=False
api/doug/migrations.py   sensitive=False  test=False  migration=False
```

`_SENSITIVE_NAME_RE` matches `secret|auth|authn|authz|rbac|oauth|credential|
token`. It fires on **zero** files in the PR that motivated the work.
Sensitivity-ordering would have changed nothing.

**How often this bites**, over the last 30 first-parent commits:

| | share |
|---|---|
| Diff exceeds the 30k budget | **37%** |
| **Code alone** exceeds 30k | **20%** |

The 17-point gap is prose and tests crowding out code on PRs whose code fits
comfortably — `ed5aa3e` is 128,942 chars total but 22,126 of code; `a8cc396`
is 71,836 / 21,385. Those are fixed by ordering alone. The remaining 20% are
not: at 30,000 characters you are choosing which half of PR #50's 57,441 chars
of code to miss, not whether to miss it.

---

## Two changes, and why both

### 1. Order the diff before the cut

One pure function in `review.py`, called at both join sites (`fetch_pr:225`,
`fetch_open_prs:148`) before `CHUNK_SEPARATOR.join(...)`:

```python
def read_order(files: list) -> list:
    """The order files reach the model. Pure; same objects, reordered."""
```

Three sort keys:

| | key | source |
|---|---|---|
| 1 | tier: code/infra → tests → prose | `features._is_test` (reused) + new `_is_prose` |
| 2 | patch size ascending | `len(f.patch)` |
| 3 | original path order | deterministic tiebreak |

`_is_prose` covers `.md` / `.txt` / `.rst` and lockfiles, except that known
manifests such as `requirements.txt` stay code. It lands in `features.py`
beside `_is_test` — path classification lives in one module, so the tier rule
and the scorer can never drift apart on what counts as a test. Everything that
is neither prose nor test is tier 0.

**Nothing in `reader.py` changes except the one constant in §2.** `_sent_slice`,
`_user_text` and `coverage()` are untouched, and no new truncation logic is
written: order the chunks and the existing linear cut admits whole files until
one does not fit. The `coverage()` invariant — a partial read cannot look like
a complete one — holds by construction, because `coverage()` re-derives from
the same assembled string.

**Why smallest-first, not risk-first.** Doug's path predicates fire on zero
files here (above), so risk-ordering would mean inventing new path vocabulary.
That is precisely the move that failed replication: `hotspot_path` and
`config_flag` fire zero times across all 12,000 grafana PRs because both
dictionaries are sentry vocabulary (THESIS.md §1a). Smallest-first needs no
vocabulary, works in any language, and maximises how many files the reader sees
**whole** — which is what lets it reason correctly rather than half-correctly.

**The cost, stated rather than implied:** smallest-first makes the largest file
in a tier the likeliest to be dropped, and the largest file is often the
most-changed. On PR #50 that is `api.py`. This is a real trade — "reason
correctly about six files" bought with "never see the biggest one" — not a free
win. The mitigation already ships: `coverage.files_unseen` lists it and
`truncation_reason` renders `Never sent: api.py` on the check run.

### 2. `DIFF_BUDGET` 30,000 → 100,000

Ordering cannot fix the 20% of PRs whose code alone busts the budget. 30,000
characters is roughly 7,500 tokens, on a model with a 1M-token context window.

Coverage at candidate budgets, **with the tiering applied**, over the same 30
commits:

| budget | all code sent | code+tests sent | mean $/read | vs today |
|---|---|---|---|---|
| 30,000 | 80% | 70% | $0.056 | — |
| 60,000 | **100%** | 83% | $0.066 | +$0.011 |
| **100,000** | **100%** | **97%** | **$0.074** | **+$0.019** |
| 200,000 | 100% | 100% | $0.081 | +$0.026 |

Max code-only in the sample is 58,977 chars, so 60k already covers every line
of code. **100k is where code+tests saturates**, and tests are load-bearing for
this reader: `reader.py`'s own comment records lema#643, where the
mutation-verified test file that would have deduped two findings was never sent
at all. 200k buys three points of "docs also sent" for another $0.007.

**The budget is a ceiling, not a spend.** Median diff is 21,785 chars, so 63% of
PRs already fit under 30,000 and cost nothing more when the ceiling rises. The
+$0.019 is a mean over real PRs; the worst case — a PR that saturates 100k — is
about +$0.09.

Spend caps are unaffected in shape: `_charge(scope)` still runs before the
client is constructed, and the cap counts reads, not tokens. The 4,000
reads/installation/month ceiling now admits a more expensive read, which is the
point.

---

## ADR-0002 is superseded, not edited

ADR-0002 freezes six constants byte-identical to `scripts/llm_probe.py` at
commit `0064e6b`: `SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT`, `MAX_TOKENS`,
`DIFF_BUDGET`. Changing one of them is a new experiment by its own terms, at
any price.

This lands as **ADR-0012, superseding ADR-0002** rather than an in-place edit.
Editing ADR-0002 would erase the record of what was frozen and why, and
`docs/decisions/README.md` is explicit that decision records are an input to
Doug's own reader — a stale record does not merely mislead a human, it produces
a confident false finding. A record that still said `DIFF_BUDGET` was frozen at
30,000 would generate exactly that on this PR.

ADR-0012 restates the whole rule:

- **Five constants stay frozen** — `SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT`,
  `MAX_TOKENS`, still pinned by the existing cross-pin test.
- **`DIFF_BUDGET` is governed by a pre-registered coverage bar instead of by
  the probe.** The bar: *every code-tier file sent whole on ≥95% of PRs, over
  the 30 first-parent commits ending at `135c8e5`.* Verified deterministically — `coverage()`
  is a pure function, so the bar costs **zero model calls** to check.

**The honest limit, and it is the reason this needs a record at all.** After
this change, "the shipped reader is the one that scored AUC 0.687 sentry /
0.668 grafana" is false. Those numbers describe the 30,000-character
configuration. We are **not** re-running the probe at 100k (Andrew,
2026-08-06); ADR-0012 records instead that the probe evidence attaches to the
frozen prompt/schema/model/effort and to a 30k budget, and that the shipped
reader now reads more and in a different file order than the probe did. Any
future citation of those AUC figures must say which configuration produced
them.

---

## Testing

TDD. Each test encodes why the behaviour matters, not just what it does.

| test | encodes |
|---|---|
| 100k of markdown + 5k of code → all code sent whole | the accepted policy routes code before lower-signal prose |
| `test_tenancy.py` does not displace `tenancy.py` | tests are context for the code, not competitors with it |
| PR #50's shape reconstructed through both callers → `tenancy.py` sent whole, `file_cut` names `store.py`, and `files_unseen` names `api.py` | the motivating defect, pinned without mistaking a partial file for a whole one |
| same input ordered twice → identical output | no set iteration; a nondeterministic order makes verdicts unreproducible |
| `coverage().files_unseen` names every unsent file after reordering | the partial-read-cannot-look-complete invariant survives reordering |
| a fully-fitting PR sends every file regardless of order | ordering must be a no-op below the budget |
| `DIFF_BUDGET == 100_000` pinned, and the five frozen constants still cross-pin to `llm_probe.py` | ADR-0012's split: one constant moved, five did not |

**Exit gate:** the pre-registered 95% coverage bar above, the pinned range's
known 30/30 sanity result, the full suite green, and ruff clean. A code-tier
`file_cut` is a miss just like a code-tier `files_unseen` entry: the file did
not arrive whole. The script requires exactly 30 SHAs, exactly 30 evaluated
rows, and 30/30 passing rows, so an incomplete sample cannot shrink the
denominator or pass merely because it remains above 95%. A negative regression
runs the real fixed range at 30k and requires strict 24/30 plus exit 1.

The gate reconstructs every patch available in local Git over the **fixed
commit range pinned in the script** (the 30 first-parent commits ending at
this branch's merge base) — not "the last 30", which would move under the gate
and let a later commit re-open it silently. Local Git cannot model GitHub
`patch=None` omissions; production `files_dropped` receipts cover that
separate hole. Zero model calls, so the gate is re-runnable by anyone at any
time.

---

## Out of scope, deliberately

- **Excluding prose from the diff entirely.** Excluding files would make
  `coverage()` report `complete` on a PR whose docs were never sent — silent
  completeness, the exact failure mode that module exists to prevent. Ranking
  them last costs them everything and keeps them visible in `files_unseen`.
- **Re-running the probe at 100k.** Decided against (above); the limit is
  recorded instead.
- **Interdiff / convergence scoring.** Separate idea, captured in
  `workspace/IDEAS.md` 2026-08-05.
- **Any change to the five remaining frozen constants.**

---

## Rejected alternatives

| rejected | why it lost |
|---|---|
| Route by sensitive paths first (the plan of record) | Disproved by measurement: `_is_sensitive` / `_MIGRATION_RE` fire on zero files in the motivating PRs |
| Per-file floor + cap (spread the budget across every file) | Makes *every* file the partial case that `reader.py:405` names as most dangerous — "enough of it to reason about and not enough to be right" |
| Largest-file-first within tier | Worst breadth; one big file consumes the budget, which is the current failure with extra steps |
| Ordering only, leave `DIFF_BUDGET` at 30,000 | Leaves 20% of PRs with code the reader structurally cannot see |
| `DIFF_BUDGET = 200,000` | +$0.007/read over 100k for three points of docs coverage; code+tests already saturates at 100k |
| Edit ADR-0002 in place | Erases what was frozen and why, in a file the reader consumes |
