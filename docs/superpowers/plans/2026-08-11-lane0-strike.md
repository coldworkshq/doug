# Lane 0 Strike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the four time-critical items from the two-lane spec §1 before the 2026-08-16 adjudicator due clock: prereg v9 amendment, M3 Task 7 handoff, Example Pack capture enable, RF baseline record.

**Architecture:** Tasks 1 and 4 are session work on one branch (`lane0-strike`, worktree off origin/main). Tasks 2 and 3 are operator checklists for Andrew (prod gcloud) — the session's deliverable for them is a verified, up-to-date checklist handed to Andrew, not the execution.

**Tech Stack:** Markdown (prereg doc), bash (gcp.sh), Python via `uv run` (rf_kamei).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-two-lane-plan-design.md` (§1). Do not re-litigate its locked decisions (§0).
- **Clock:** v9 must be MERGED AND DEPLOYED (hash re-pinned) before 2026-08-16. If merge happens but no deploy is scheduled before the 16th, say so loudly — a v8-stamped first adjudication row is the exact outcome this lane exists to prevent.
- Worktree: `git -C /Users/andrew/Projects/doughq/repo worktree add .worktrees/lane0 -b lane0-strike origin/main`
- Report-to-file: before going idle, write your status/report to `.worktrees/lane0/LANE0-REPORT.md` (git-ignored is fine; the controller reads files, not memories).
- Cold verification: the controller re-runs every verification command itself; your claim is not evidence.
- `docs/findings-log.jsonl` is append-only; never round-trip it through `json.dumps` defaults.

---

### Task 1: Prereg v9 amendment — `remediated_clears`

**Files:**
- Modify: `docs/design/outcome-loop/publication-preregistration.md` (header line 3; new §2.6 after §2.5; §3 "Published together" table ~line 337; the amendment/version history in §12)

**Interfaces:**
- Produces: `LOCKED v9` doc whose sha256 the deploy path re-pins (`api/deploy/gcp.sh` `compute_prereg_hash`); the `remediated_clears` + `remediated_revert_count` published columns (definitions only — the publication query is built with the first publication, not now).

- [ ] **Step 1: Confirm the section map before editing**

Run: `grep -n "^### 2\.\|^## " docs/design/outcome-loop/publication-preregistration.md | head -30`
Expected: §2.1..§2.5 subsections exist; note the exact line of §2.5's end and of the §3 column table. If §2.6 already exists, STOP and report — the doc moved under you.

- [ ] **Step 2: Insert §2.6**

Insert after §2.5, matching the doc's voice:

```markdown
### 2.6 Remediated clears

A governing-cleared PR (§2.1) is a **remediated clear** when any earlier
verdict on the same identity `(installation_id, github_repo_id, pr_number)`
with `tier = 'reader'` and `scored_at <= merged_at` has `band = 'flagged'`.
§2.1's governing rule is unchanged — the PR stays in the cleared band and in
`N_at_risk` — but its count publishes beside the rate as `remediated_clears`,
with `remediated_revert_count`: a disclosure, never a comparator, exactly as
§2.4 treats `unverdicted_merges`. The cleared band otherwise pools two
populations — never-flagged PRs and flagged-then-repaired ones — with
different expected revert rates, and a pooled rate with no bucket lets
remediation quietly reshape the published population. Not hypothetical:
PR #49 on `drewjst/doug` (reviewed twice, five findings, all fixed, merged
cleared) is already in the band §1 commits to publishing. The rows needed
are already retained — verdicts are append-only and carry `band` and
`scored_at` — so this is a publication-time query, not a schema change.
```

- [ ] **Step 3: Add the two columns to §3's "Published together, never separately" table**

```markdown
| `remediated_clears` | §2.6 — count of governing-cleared PRs with an earlier flagged reader verdict |
| `remediated_revert_count` | §2.6 — their reverts; a disclosure, never a comparator |
```

- [ ] **Step 4: Bump the lock header and record the amendment**

Header line 3 becomes: `**Status:** LOCKED v9 — <today's date>`.
Find how v7→v8 recorded its change (`grep -n "v8\b" docs/design/outcome-loop/publication-preregistration.md`) and add a matching entry: v9 adds §2.6 + two §3 columns; a disclosure addition under the general amendment rule ("Amendments are permitted; silent ones are not") — deliberately NOT claimed as §12-"free", whose list is cadence-only. Zero adjudicated rows exist at amendment time, so no published row was ever governed by v8.

- [ ] **Step 5: Verify the deploy gate still passes and compute the hash**

Run: `grep -q '^\*\*Status:\*\* LOCKED ' docs/design/outcome-loop/publication-preregistration.md && echo LOCKED-OK`
Run: `python3 -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('docs/design/outcome-loop/publication-preregistration.md').read_bytes()).hexdigest())"`
Expected: `LOCKED-OK` and a 64-char hash. Record the hash in LANE0-REPORT.md.

- [ ] **Step 6: Run the doc-adjacent tests**

Run: `cd api && uv run pytest -q -k "prereg or preregistration or outcome_worker"`
Expected: PASS (the adjudicator tests validate hash *format*, not a pinned value — if any test pins the v8 hash bytes, update it in this commit and say so in the report).

- [ ] **Step 7: Commit**

```bash
git add docs/design/outcome-loop/publication-preregistration.md
git commit -m "docs: prereg v9 — publish remediated_clears beside the cleared rate"
```

- [ ] **Step 8: Open the PR and flag the deploy dependency**

PR body must state: "Merging is not enough — DOUG_PREREG_HASH re-pins at the next deploy; a deploy must happen before 2026-08-16 (Task 7's deploy qualifies)."

---

### Task 2: M3 Task 7 handoff checklist (ANDREW executes)

**Files:**
- Create: `.worktrees/lane0/LANE0-REPORT.md` § "Task 7 checklist" (not committed to the repo — the runbook is already the committed artifact)

- [ ] **Step 1: Re-verify the runbook against current state**

Read `docs/design/outcome-loop/60-day-backfill-runbook.md` end to end. Check its deploy step against the fact it will arrive with the **v9** hash already pinned by Task 1's deploy (the 2026-08-08 finding was that an ordinary deploy pins the hash before the runbook expects it — re-confirm which steps become no-ops).

- [ ] **Step 2: Write the checklist**

In LANE0-REPORT.md, list in order, each with the literal command from the runbook: pause Scheduler → prove quiescence → dry-run count → apply + verify manifest → one manual Job execution → SQL/CLI audits → resume Scheduler. Note the daily 03:00 UTC firing — do not start across it. Flag any runbook step that Step 1 found stale, with the correction.

- [ ] **Step 3: Hand off**

Tell the controller the checklist is ready; the controller surfaces it to Andrew. Do NOT run any gcloud command yourself — prod is Andrew's.

---

### Task 3: Example Pack capture-enable checklist (ANDREW executes)

- [ ] **Step 1: Assemble the exact env contract**

Copy the block from `docs/OPERATIONS.md` § "Enable one bounded cohort" into LANE0-REPORT.md and fill every value that can be pre-filled: `DOUG_EXAMPLE_PACK_COHORT=doug-dogfood-2026-08`, `DOUG_EXAMPLE_PACK_ADJUDICATOR=andrew`, `DOUG_EXAMPLE_PACK_INSTALLATION_IDS=150424894`, `DOUG_EXAMPLE_PACK_REPOSITORY_IDS=<numeric id of drewjst/doug — get it with: gh api repos/drewjst/doug --jq .id>`. Leave bucket name and the UTC window for Andrew (window end = his call; suggest 30 days). `DOUG_EXAMPLE_PACK_SOURCE_ROOT` must be a CLEAN checkout of the deployed revision — note `gcp.sh` rejects a dirty tree or revision mismatch.

- [ ] **Step 2: Record the re-enable trap**

Add to the checklist, verbatim from OPERATIONS.md: an ordinary API deploy drops capture admission settings — **after every deploy inside the window, re-run `./deploy/gcp.sh example-pack-enable`** (this includes Task 1/Task 7's own deploys).

---

### Task 4: Run and record the RF baseline

**Files:**
- Create: `docs/design/outcome-loop/rf-kamei-baseline-2026-08.md`

**Interfaces:**
- Consumes: `api/scripts/rf_kamei.py` (unchanged — do not edit it), harvest caches in `api/.backtest-cache/`.
- Produces: the committed results doc later work cites as the metadata-model baseline.

- [ ] **Step 1: Preflight the caches (the worktree does not have them — they are gitignored)**

```bash
ln -s /Users/andrew/Projects/doughq/repo/api/.backtest-cache \
      /Users/andrew/Projects/doughq/repo/.worktrees/lane0/api/.backtest-cache
ls api/.backtest-cache/ | grep -E "getsentry-sentry-10000-before-2026-03-20|grafana-grafana-12000-before-2026-06-15"
```
Expected: both files listed. If either is missing, STOP and report — do NOT let `harvest()` fall through to the network.

- [ ] **Step 2: Run it, capturing output**

Run: `cd api && uv run python scripts/rf_kamei.py 2>&1 | tee /tmp/rf-kamei-out.txt`
Expected: four split blocks (A, B, C both directions), each with RF / v3 / size rows, AUC CIs, importances. Takes minutes (500 trees × 22k PRs); no network.

- [ ] **Step 3: Write the results doc**

`docs/design/outcome-loop/rf-kamei-baseline-2026-08.md`: header (date, script path, cache filenames used, `git rev-parse HEAD`), the verbatim captured output in a code block, then an interpretation section that reads the numbers **against the pre-registered bars** — copy the bars in from `workspace/research/phase1-entry-preregistration.md` (outside the repo; quote them so the repo doc stands alone). State plainly whether RF beats the shipped reader's recorded AUC (0.687 sentry / 0.668 grafana, ADR-0004) and what that means for the reader's cost story. If a bar fails, write FAIL — do not soften it.

- [ ] **Step 4: Verify the doc builds no false claim**

Re-read the doc once: every number in prose must appear in the captured output block. No rounding that flips a comparison.

- [ ] **Step 5: Commit**

```bash
git add docs/design/outcome-loop/rf-kamei-baseline-2026-08.md
git commit -m "docs: record RF-on-Kamei-14 baseline results (pre-registered Phase-1 protocol)"
```

---

## Exit gate (controller verifies cold)

1. v9 PR open; header reads `LOCKED v9`; hash recorded; deploy-before-08-16 dependency named in the PR body.
2. Task 7 + capture checklists in LANE0-REPORT.md, surfaced to Andrew.
3. RF results doc committed; controller re-runs `grep -c "AUC" docs/design/outcome-loop/rf-kamei-baseline-2026-08.md` ≥ 8 and spot-checks two numbers against the output block.
4. `cd api && uv run pytest -q` green, `uv run ruff check .` clean on the branch.
