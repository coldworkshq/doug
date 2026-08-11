# Lane 2: Agent Door Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convergence scoring (finding-diff over existing verdicts — the fix-loop halt signal), then a verdict MCP v0 that serves receipt + verdict + convergence to a coding agent (Reading A: the customer's agent consumes; Doug never writes code).

**Architecture:** Phase 1 (Tasks 1–4, stepped) builds convergence as a pure module over ledger rows, pre-registers its bars, evaluates on the multi-round PRs already in the ledger, and surfaces it on the receipt. Phase 2 (MCP v0) is SPECIFIED, NOT STEPPED — expand after Phase 1's bars pass.

**Tech Stack:** Python 3 (api/), pytest, SQLAlchemy rows as plain dicts. Phase 2: the Python `mcp` SDK (not yet a dependency).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-two-lane-plan-design.md` §3. Baseline origin/main @ `2b56376`.
- Worktree: `git -C /Users/andrew/Projects/doughq/repo worktree add .worktrees/lane2 -b lane2-agent-door origin/main`
- **Invariants (each gets a test):** convergence never enters `score()`; no new paid read; three states with `unknown` reported alongside and never folded into a ratio; coverage-aware; settle-aware.
- Convergence must NOT touch any `/v1/sessions/*` response shape (web's exact-key validators + api-before-web deploy order = outage window). The receipt endpoint has zero consumers — extending it is safe.
- No migration is needed anywhere in Phase 1. If you believe you need one, re-read `api/doug/migrations.py:1` (create_all owns new tables) and compute the next free number with the one-liner in HANDOFF — do not trust any doc's "next free" claim.
- Verification the controller re-runs cold after each task: `cd api && uv run pytest -q && uv run ruff check .`
- Report-to-file before idle: `.worktrees/lane2/LANE2-REPORT.md`.
- Spend: Phase 1 costs $0 (ledger-only). Any paid probe ≤ $25 must be pre-registered in the design note first.

---

### Task 1: Pin ledger semantics, write the convergence design note

**Files:**
- Create: `docs/design/outcome-loop/convergence-design.md`

**Interfaces:**
- Produces: the finding-identity definition, the classification rules, and the pre-registered bars that Tasks 2–3 implement VERBATIM. Tasks 2–3 must not deviate from this note without returning to it first.

- [ ] **Step 1: Pin the settlement-notice vocabulary**

Run: `grep -n "rule=\"settled" api/doug/settle.py`
Expected: `settled-missing-import` (settle.py:~191) and the schema sibling from `schema_settlement_notice` (find it: `grep -n "def schema_settlement_notice" -A 12 api/doug/settle.py`). Record BOTH exact rule strings — the classifier keys on them.

- [ ] **Step 2: Pin the findings/reads row shapes**

Run: `sed -n '100,170p' api/doug/store.py` (findings + reads columns) and `grep -n "def run_detail" -A 5 api/doug/store.py`. Confirm: findings rows carry `rule`, `label`, `file` (nullable), `severity`; reads carry `files_unseen`, `file_cut`, `files_dropped`, `changed_files`. Note that deterministic-tier reasons share the findings table — `patterns.from_rule` returns `None` for them, which is the exclusion mechanism.

- [ ] **Step 3: Write the design note.** Contents, all mandatory:

```markdown
# Convergence scoring — design note (pre-registered)

## Identity
A finding's identity is `(pattern, file)` where
`pattern = patterns.from_rule(findings.rule)` (None ⇒ not a reader finding ⇒
excluded entirely) and `file = findings.file`. `file IS NULL` ⇒ identity is
incomplete ⇒ every comparison involving it classifies `unknown
(identity-incomplete)` — store.py backfills `file` by exact
description-match and can lose it (store.py:825-838), and a lost file must
not fabricate a resolution. Multiple findings sharing one identity within a
verdict are matched by COUNT (2 before, 1 after ⇒ 1 resolved, 1 persisted).
Line numbers do not exist in the schema and are NOT part of identity
(adding one is an ADR-0012 experiment — out of scope).

## Classification of a prior finding, against the LATER verdict
1. Identity present in later verdict            → persisted
2. Identity incomplete (file NULL, either side) → unknown(identity-incomplete)
3. later read has file in files_unseen, or file_cut covers it, or file in
   files_dropped, or later read row missing     → unknown(file-uncovered)
4. later verdict's reasons include a settlement-notice rule whose label
   names this finding's file and slug           → unknown(settled)
   [Doug disproved it; nobody fixed anything]
5. otherwise                                    → resolved
Order matters: 2–4 are checked BEFORE 5 — every abstention beats a false
"resolved". Findings first appearing in the later verdict count as `new`.

## Report
resolved / persisted / new as counts; unknown as a count WITH per-reason
breakdown, reported alongside — never in any ratio. The only ratio:
resolved / (resolved + persisted), None when the denominator is 0.

## Pre-registered bars (evaluated in Task 3, declared here first)
1. `resolved` precision ≥ 0.90 on the hand-labelled consecutive-pair sample
   (asymmetric failure: false-resolved tells an agent it is done).
   If the ledger yields < 10 labelable pairs, report the count and get
   controller sign-off on proceeding with a smaller n before evaluating.
2. ZERO false-resolved on any finding whose file was dropped/cut/unseen in
   the later read (hard bar — by construction rule 3, but the EVALUATION
   must include such pairs to prove the construction holds on real rows).
3. settle-dropped findings never classify resolved (rule 4; same proviso).
Slug drift recorded as a covariate: distinct raw slugs / distinct patterns
in the sample (probe precedent: 276 slugs over 395 findings).

## Invariants
Not in score() (structural test); no new read; derived at query time — no
schema change, no migration.
```

The 0.90 floor is proposed here for pre-registration; the controller confirms it when reviewing this note — BEFORE Task 3 runs. Do not start Task 3 without that confirmation recorded in LANE2-REPORT.md.

- [ ] **Step 4: Commit** (`docs: pre-register convergence identity, classification, and bars`)

---

### Task 2: The convergence module (TDD)

**Files:**
- Create: `api/doug/convergence.py`
- Test: `api/tests/test_convergence.py`

**Interfaces:**
- Consumes: `patterns.from_rule` (`api/doug/patterns.py`); plain dicts shaped like `store.run_detail`'s `findings`/`reasons`/`coverage` outputs.
- Produces:

```python
@dataclass(frozen=True)
class ConvergenceReport:
    resolved: int
    persisted: int
    new: int
    unknown: dict[str, int]  # keys: identity-incomplete | file-uncovered | settled
    @property
    def unknown_total(self) -> int: ...
    @property
    def ratio(self) -> float | None: ...  # resolved/(resolved+persisted); None if 0

def compare(
    prior_findings: list[dict],   # rows: {rule, label, file, severity}
    later_findings: list[dict],
    later_reasons: list[dict],    # rows: {rule, label, weight, severity} — settlement notices live here
    later_read: dict | None,      # {files_unseen, file_cut, files_dropped, changed_files} or None
) -> ConvergenceReport: ...
```

- [ ] **Step 1: Write the failing tests — one per design-note rule, in this order**

`api/tests/test_convergence.py` (match `api/tests/` house style; plain dict fixtures):

```python
def _f(rule="reader:error-handling-gap", file="api/doug/api.py", label="x", severity="high"):
    return {"rule": rule, "label": label, "file": file, "severity": severity}

def test_absent_finding_with_covered_file_is_resolved(): ...
    # prior=[_f()], later=[], read covers the file → resolved=1
def test_present_identity_is_persisted(): ...
def test_null_file_never_resolves():
    # prior=[_f(file=None)], later=[] → unknown {"identity-incomplete": 1}, resolved=0
def test_uncovered_file_never_resolves():
    # later_read {"files_unseen": ["api/doug/api.py"], ...} → unknown {"file-uncovered": 1}
def test_missing_read_row_never_resolves(): ...   # later_read=None → file-uncovered
def test_settled_finding_never_resolves():
    # later_reasons include {"rule": "settled-missing-import", "label": "api/doug/api.py: error-handling-gap (…)", "weight": 0.0}
    # → unknown {"settled": 1}
def test_deterministic_reasons_are_excluded(): ...  # rule without "reader:" prefix ignored both sides
def test_count_matching_two_before_one_after(): ...  # resolved=1, persisted=1
def test_new_findings_counted(): ...
def test_ratio_none_on_empty_denominator(): ...
def test_slug_merge_map_applies():
    # prior rule "reader:unhandled-exception", later "reader:missing-error-handling"
    # — same canonical pattern → persisted, not resolved+new
```

- [ ] **Step 2: Run — all FAIL** (`uv run pytest -q tests/test_convergence.py`)

- [ ] **Step 3: Implement `convergence.py`** exactly per the design note's ordered rules. Keep it pure: no store import, no engine, no clock.

- [ ] **Step 4: Run — all PASS**

- [ ] **Step 5: Structural invariant test**

```python
def test_convergence_is_not_in_the_scoring_path():
    import doug.convergence  # noqa: F401 — import side-effect check only
    src = Path("doug/score.py").read_text() if Path("doug/score.py").exists() else ""
    for path in Path("doug").glob("*.py"):
        if path.name in {"convergence.py"}:
            continue
        assert "import convergence" not in path.read_text() and \
               "from doug import convergence" not in path.read_text() and \
               "from . import convergence" not in path.read_text(), path
```
(Adjust to the actual scorer filename — find it first: `grep -rn "def score(" api/doug/*.py`. The intent: nothing in the scoring/worker path imports convergence until Task 4 wires the RECEIPT path, at which point this test narrows to "not imported by the scorer module(s)" — leave a comment saying Task 4 will amend it.)

- [ ] **Step 6: Mutation proofs — the two hard bars**

(a) In `compare`, reorder so the resolved check precedes the coverage check → `test_uncovered_file_never_resolves` MUST fail. Restore.
(b) Delete the settlement-notice branch → `test_settled_finding_never_resolves` MUST fail. Restore. Clear `__pycache__` between weaken and restore (`find . -name __pycache__ -exec rm -rf {} +`) — same-second same-size restores keep testing the mutant.

- [ ] **Step 7: Ruff + full suite + commit** (`feat(api): convergence finding-diff module — pure, coverage- and settle-aware`)

---

### Task 3: Evaluate against the ledger (pre-registered bars)

**Files:**
- Create: `api/scripts/convergence_eval.py`
- Create: `docs/design/outcome-loop/convergence-eval-results.md`

**NOTE: needs production ledger read access (verdict pairs live in prod Postgres — PR #49 and #72 are the known multi-round cases). This task is CONTROLLER+ANDREW-assisted: the script is autonomous work; running it against prod and hand-labelling is done with Andrew's access, per the runbook pattern.**

- [ ] **Step 1: Write the script**

`convergence_eval.py`: takes `DATABASE_URL` env (read-only), finds every (installation_id, github_repo_id, pr_number) with ≥2 reader-tier verdicts, orders by scored_at, runs `convergence.compare` on each consecutive pair, and emits JSON: per-pair verdict ids, head_shas, the report, and the underlying finding rows (rule/label/file) so a human can label without DB access. No writes; assert the connection is used read-only (no `.begin()`).

- [ ] **Step 2: Bar-1 sample check** — if labelable pairs < 10, STOP per the design note; report the count and get controller sign-off before proceeding.

- [ ] **Step 3: Hand-label** — for each pair, the labeller (controller, using the PRs' actual GitHub history — these are Doug's own PRs) marks each prior finding: actually-fixed / still-present / can't-tell. Store labels in the results doc next to the classifier's output.

- [ ] **Step 4: Score the bars** — resolved-precision (bar 1), the two zero-bars (2, 3) — checking the evaluation SAMPLE actually contained uncovered-file and settled cases; if it contained none, say so explicitly (a bar passed on zero exposures is not a pass, it is no evidence — REVIEWING.md discipline). Record slug-drift covariate.

- [ ] **Step 5: Write `convergence-eval-results.md`** — verbatim script output, labels, per-bar PASS/FAIL, and the honest-exposure note from Step 4. FAIL on any bar ⇒ STOP the lane and report; Task 4 does not proceed on a failed bar.

- [ ] **Step 6: Commit** (`docs: convergence pre-registered evaluation results`)

---

### Task 4: Surface convergence on the receipt

**Files:**
- Modify: `api/doug/store.py` (`receipt()` — small, isolated change; ships as its OWN PR per spec §5 store.py rule)
- Modify: `api/doug/api.py` (`ReceiptResponse` + the route)
- Test: `api/tests/test_api.py` (receipt tests), `api/tests/test_store.py`

**Interfaces:**
- Produces: `ReceiptResponse.convergence: list[ReceiptConvergence]` where `ReceiptConvergence = {from_verdict_id: int, to_verdict_id: int, resolved: int, persisted: int, new: int, unknown: dict[str, int]}` — one entry per consecutive reader-verdict pair, oldest first. Receipt has ZERO consumers today (verified), so the shape addition is safe; it is also the MCP payload's convergence field.

- [ ] **Step 1: Failing store test** — seed two reader verdicts on one PR (second resolving one finding, persisting one), assert `store.receipt(...)["convergence"]` has one entry with `resolved == 1, persisted == 1`. Follow `test_store.py`'s seeding helpers; remember `latest_verdict` excludes `tier='external'` (store.py:1783-1791) — seed reader tier.
- [ ] **Step 2: Implement in `receipt()`** — fetch each verdict's findings + reasons + latest read row (the id-picking-subquery pattern run_history uses; read its comment at store.py:2160 first), call `convergence.compare` per consecutive pair. Amend Task 2's structural test comment: receipt path may import convergence; scorer path still must not.
- [ ] **Step 3: Failing API test → Pydantic model → PASS.** `prereg_hash` handling is untouched — it comes from the per-window stamp in `detail`, never env (api.py:850-857).
- [ ] **Step 4: Full suite + ruff + commit** (`feat(api): receipt carries per-pair convergence`)

---

## Phase 2 — Verdict MCP v0 (SPECIFIED, NOT STEPPED)

Gate: Phase 1 bars PASSED and recorded; Lane 0's v9 LOCKED AND DEPLOYED (a fix-loop on the published repo without the remediated_clears bucket is the contamination the spec exists to prevent).

Requirements for the expansion (to Phase-1 standard, one task at a time, controller sign-off on the expansion first):

1. **Service shape:** doug-mcp as its own Cloud Run service on the SAME image (architecture.md:144 — pinned there because "third-party agent clients are a different trust boundary and must never queue in front of ingest"). Python `mcp` SDK becomes an api/ dependency; read its current docs at expansion time — do not code from memory.
2. **Auth:** an MCP-scoped key minted through the existing tenancy machinery with a scope that does NOT include `queue:read` (the scopes column exists for exactly this — api.py:561, pinned by test_api.py:2286). `tenancy.py` imports FastAPI-free by design; keep it that way.
3. **Tools (v0, read-only):** `get_verdict(pr_number)` → latest reader verdict (band, score, threshold, rationale, findings with severity, coverage, deviations); `get_receipt(pr_number)` → the ReceiptResponse including convergence; `get_convergence(pr_number)` → the last pair's report + the halt guidance string. Payload MUST carry band + receipt + convergence — the differentiation is the point (me-too without them).
4. **Spend controls, before any loop use:** a per-PR read ceiling (new constant + enforcement at the worker admission point, with a test); document that convergence gates whether a re-review is bought. The 4,000/month cap is a backstop, not the mechanism.
5. **Dogfood exit gate:** a Claude Code session on this repo retrieves verdict + convergence for a live PR via the MCP server with the scoped key; the key provably cannot read the queue (test); Doug's own review of the MCP PR adjudicated into findings-log.
6. **Goodhart note travels into the tool descriptions:** the payload describes what WAS reviewed; it is not a pre-write oracle. Revisit before any tenant beyond dogfood.
7. **Roadmap correction ships with this phase** (spec §3): split ROADMAP.md's "MCP garden service" row (gated on adjudicated ≥ min-n — a historical claim needing history) from a new "verdict MCP" row (serves rows that exist today; gate = Phase 1 bars + v9 deployed). Same split in `architecture.md:144`'s gate column if it still says "adjudicated rows ≥ min-n" for doug-mcp.

## Lane exit gate (controller verifies cold)

Phase 1: all Task-3 bars PASS with real exposures; structural not-in-score test green; `uv run pytest -q` and `ruff check .` clean; receipt convergence live behind `receipt:read`. Phase 2 (when expanded): dogfood gate above.
