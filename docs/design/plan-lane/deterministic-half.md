# Plan lane — the deterministic half, measured

**Date:** 2026-08-18 · **Status:** superseded as design by `design.md` (2026-08-18) — **stands as the measurement record**
**Companion to:** `idea.md` (capture-only). Every number in `design.md` is sourced here.

> Superseded, not corrected. The measurements below hold; what changed is the design they support —
> from a single plan's progress to verticals, lanes and checkpoints. Following ADR-0012's precedent,
> this record is left intact rather than rewritten in place.
**Scope:** the git-join half **only**. Drift detection and stale-doc flagging are deliberately out — they ride the deviation instrument, still labelled `unvalidated` after the 2026-07-31 derangement-check FAIL, and ADR-0007 binds a new unvalidated signal to its own stream.

Question asked: *can a build plan be turned into a git-driven progress view using nothing but git and markdown parsing?*

**Answer: yes for the parse, no for the part that made it exciting.** The corpus parses with one parser. But the `- [ ]` checkbox carries no signal at all, and the file join tops out at ~69% task resolution. What remains is real and worth a day — it is just a narrower instrument than the capture note assumed.

---

## 1. Is the corpus regular enough to parse? (yes, with a declared reject bucket)

Measured over `docs/superpowers/plans/*.md` on `main`: **25 plans, 155 tasks, 149 `**Files:**` declarations** (96% of tasks carry one).

> **Correction to `idea.md`:** the note says "~40 files". Actual is **25 on `main`, 31 across all branches**. Not material to the idea; recorded because it is a factual input to it.

The load-bearing regularity: **the first backticked token on a `**Files:**` body line resolves to a real repo path 309/312 times = 99.0%** (checked against every path ever present in git history, all branches). The three misses are globs and one gitignored artifact — `docs/design/outcome-loop/*.md`, `*.test.mjs`, `api/.backtest-cache/llm-probe/api-key` — i.e. a small, nameable, rejectable class.

So a single parser with no per-file special-casing is achievable. These are the ragged cases it must survive:

| # | Ragged case | Count | Why it bites |
|---|---|---|---|
| 1 | **Two grammars.** Block form — `**Files:**` alone on its line, bullets below — vs **inline** form, where the paths follow on the same line | 140 block / **9 inline** | Different parse path entirely |
| 2 | **Inline form hard-wrapped** across 2–3 source lines | 3 | `lane1-phase-b.md:321` wraps mid-clause: a line-oriented reader sees `RULING 1 = pinned-light); Delete …` as a Files entry |
| 3 | **Extra real paths in the line tail** | **48** | First-token-only *under-reads* by 48 genuine paths |
| 4 | **Tail ambiguity** — comma-lists are paths, prose tails are symbols | — | ``Modify: `x.py`, `y.py` `` (both paths) vs ``Modify: `x.py` (add `helper`)`` (second is a symbol). The single hardest call in the parse |
| 5 | **Bare sibling filenames** inheriting the dir from the first token | 8 | ``Create `web/lib/search.ts`, `sorting.ts`, `paging.ts` `` … — later tokens are not repo-relative |
| 6 | **`path:line-range` citations**, and bare `` `:13` `` refs inheriting a path from earlier in the same line | ~12 | ``Modify: `api/doug/api.py:46-143` (delete), `:13` (import), `:151` `` |
| 7 | **Lines with no backticked token**, incl. legitimate `- Create: none`, `**Files:** none (git only)`, `- Verify only; …` | 7 | "No files" is a valid honest declaration, not a parse failure |
| 8 | **Open-ended verb set**: `Modify` 68, `Test` 42, `Create` 36, verbless bullet 9, `Verify` 6, `Delete` 6, plus `Reference only:`, `Leave untouched:` | — | Do not enumerate verbs; treat them as unvalidated labels |
| 9 | **Task IDs are not integers**: `Task B1`–`B8`, `Task 7a`/`7b` | — | ID must be a string |
| 10 | **Lifecycle annotations in the header**: `### Task 6: … — **MERGED INTO TASK 5**` | 1 | A node that must not render |
| 11 | **`**Files:**` count ≠ Task count** | 3 plans | phase-1a 11/9, lane0 4/3, lane1-phase-b 8/5 |
| 12 | **A plan with 9 `**Files:**` and zero checkboxes** (`hosted-example-pack-workbench`) | 1 | Step-count-based progress divides by zero |

**Verdict:** regular enough to parse **without per-file special-casing**, and *not* regular enough to parse silently. The parser must emit an explicit `unparsed` bucket and show its size. A parser that reports 100% coverage of this corpus is lying.

---

## 2. What can a node's state honestly mean, from git alone?

Four candidate claims. They are not interchangeable, and only two survive.

### Box ticked — **computable, and carries zero information**

This is the finding that reshapes the idea.

Across all 31 plans on all branches, **76 `- [x]` lines have ever been added to a plan file. Every single one landed in the same commit that created the file.** Not one checkbox has ever been flipped in a follow-up commit.

The strongest case: `2026-08-09-front-door-phase-1a.md` has **13 commits of active editing** — subjects like *"plan: close Task 10 restoration window"*, *"plan: expand Task 7 into 7a/7b"*, *"plan: merge Task 6 into Task 5"*. Checkboxes ticked in those 13 commits: **0.** The `- [ ]` lines that disappear are steps being *rewritten or deleted*, not completed.

Plans here are **living design documents that get re-planned during execution, not checklists that get ticked.** `- [ ]` is a step *delimiter*; it is not a state field.

`idea.md` says the lane should be driven from git "rather than from a checkbox someone remembered to tick." The data is harder than that: **nobody has ever remembered.** Consequence — the note's proposed core signal, *"files touched and box unticked, or vice versa"*, is half-dead on arrival. "Box ticked, files untouched" can essentially never fire. "Files touched, box unticked" fires for **every** completed task in the repo's history, so it is not a signal, it is the baseline. Drop the checkbox as a state input; keep it only to enumerate steps.

### Declared files touched — **computable, with a hard resolution ceiling**

`git log --name-only base..head` joined to the declared set. Real, deterministic, replayable. Two structural limits:

- **Intra-plan collision.** **36 of 116 tasks (31%) declare no file that is unique within their own plan**; 63 distinct paths are declared by two or more tasks. For those tasks a file-touch join can *never* say which task a commit belongs to. Worst: `tenant-api-keys` 8/12 tasks fully ambiguous, `doug-console-phase-1` 5/10. Clean: `m3-adjudicator-job-scheduler`, `retire-compare-path`, `lane2-agent-door`, `outcome-lane-reconciliation`, `lane0-strike` at 0/N.
- **Squash merge erases task granularity.** `main` is linear — every commit has exactly one parent. At merge the entire plan collapses into one commit, so per-task attribution exists **only while the branch is alive**. And branches are often coarser than the plan anyway: PR #78's whole branch was **one commit for a four-task plan**.

There is one genuine task-level join key in the repo, but it is not general: branches named `task-6-webhook-ingest`, `task-7a-reconcile`, `task-8-adr-0010` (~10 branches, all from one plan's execution). Commit subjects carry `Task N` only 9 times in 400, and mostly on plan edits.

### Tests green — **not computable from git, at any granularity**

Requires the GitHub Checks API, not git. And `.github/workflows/ci.yml` runs `uv run ruff check .` + `uv run pytest` — **whole-suite, per commit**. There is no per-task test scope in this repo and no way to synthesize one. This claim cannot be made per node, by a model or otherwise.

### Merged — **computable from git, plan granularity only**

`git merge-base --is-ancestor` against `main`. The only one of the four that survives the squash.

### Honest node vocabulary

| State | Source | Honest? |
|---|---|---|
| `declared` | plan markdown | yes |
| `touched` | git, branch alive, files unique to this task | yes |
| `unresolved` | declared files shared with ≥1 sibling task | yes — and must be **visibly** distinct from "not started" |
| `merged` | git ancestry, plan-level | yes |
| ~~`done`~~ | — | **no** — no git fact means done |
| ~~`passing`~~ | — | **no** — needs Checks API, and is whole-suite anyway |

The 31% ambiguous rate is the design's central honesty problem. Rendering an ambiguous task as an untouched node is a false claim. The session lane already ruled on exactly this shape: *"On ambiguous multi-match, no join — silence over speculation."* Adopt that rule verbatim.

---

## 3. Overlap with `docs/design/session-lane/` — substantial, and it argues for reuse

Four real collisions, none fatal, all needing a decision before anything is built:

1. **The file-touch fact has two producers.** Session-lane source B emits `footprint { entity, role: read|modified|created, at }` from harness tool calls. That is the *same* declared-vs-actual join the plan lane would compute from git. Two instruments, one fact, different provenance — and the session lane's version is `observed` register with per-event timestamps, which is *strictly richer* than a git diff for this purpose.
2. **Plan markdown is already inside lane C's declared scope.** Source C is "committed code, architecture docs and ADR markdown in the repo." A plan file in `docs/superpowers/plans/` is a committed doc. A standalone plan-markdown reader duplicates ingest that lane C already claims.
3. **The correlator already solved the join discipline** — branch name match, pushed commit SHAs, PR `head_ref`, and no join on ambiguity. That is precisely the rule the 31% ambiguous tasks need, and it also answers `idea.md`'s open question *"is the unit the plan or the branch?"* — the join is to the **branch**, and the plan is what the branch is joined *to*.
4. **Both want the same surface.** Session-lane §6 already claims a section on the ADR-0010 neutral check run. If the plan lane ever becomes customer-facing it is competing for that one surface — a strong additional reason to keep the prototype internal.

Also a scheduling difference worth naming: the session lane is explicitly *"not on the M3 path; builds nothing until M3 closes."* An internal read-only tool carries no such gate. A customer surface would inherit it.

---

## 4. Smallest prototype

**It is internal tooling.** Unambiguously, and the classification should be made explicitly rather than drifted into. It reads in-tree markdown and local git; it emits nothing to a customer; it makes no claim Doug is accountable for. Per session-lane §8, the honesty contract attaches to what Doug *says to a customer* — this says nothing to anyone but us. Internal ⇒ ships in a day, inherits none of the contract. **The moment it renders on a check run it becomes a customer surface and inherits all of it** — including "we refuse to claim" discipline and pre-registered bars. That transition needs its own decision, not a follow-up commit.

**The prototype:** one read-only local CLI. Input: a plan path + a base ref. Output: one row per task.

```
plan-lane docs/superpowers/plans/2026-08-11-lane2-agent-door.md --base main
```

```
Task 1  Convergence scoring          touched     3/3 declared   (api/doug/convergence.py, …)
Task 2  Verdict MCP v0               touched     2/4 declared   (missing: api/tests/test_mcp.py)
Task 3  Wire the door                unresolved  shares all declared files with Task 2
Task 4  Docs                         declared    0/2 touched
                                     unparsed:   1 Files line (glob)
```

No database. No API. No check run. No service. No model call. Reads `git log --name-only base..HEAD` and the markdown; prints a table.

**What it must show to earn more work — the success criterion:** *the tool must be able to disagree with the plan author.* If every row it prints is something the plan already asserts, it is a renderer, not an instrument. Run it against 5–6 already-merged plans with their branches still present (`lane1-phase-b`, `front-door-phase-1`, `m3-60-day-backfill`, `read-budget-routing`, `tenant-token-dispense` all survive with 13–37 commits) and count the rows where declared and actual genuinely diverge. Divergences found on real history is the number that decides this.

**Kill conditions, pre-registered:**
- If `unresolved` exceeds ~⅓ of rows in practice, the vertical job-graph rendering is dishonest — a graph implies per-node truth it does not have. It stays a table.
- If the divergence count on real merged plans is ~0, the plan lane is a renderer and should be dropped.

**Explicit non-goals for the prototype:** no drift detection, no staleness flagging, no score or band contribution, no check-run section, no per-task test status. The first three are locked out by ADR-0007 and the `unvalidated` label; the fourth is what makes it internal; the fifth is not computable.

**Constraints honoured, not reopened:** route-never-block · Doug never writes code, never opens a PR · ADR-0007 (deviations never touch `risk_score` or band) · ADR-0010 (the surface is an always-`neutral` check run). Nothing here proposes a new customer surface, a new score input, or a blocking signal.

---

## 5. Open, for whoever picks this up

- **Does the plan lane build a git-based file join at all, or wait for session-lane footprints?** The footprint stream is richer and already designed. The counter-argument: it does not exist yet and the git join is a day's work against history that already exists. Recommendation — build the internal CLI on git now, and treat it as a throwaway probe of whether the *plan* half is worth anything, not as the foundation of a lane.
- **Should `- [ ]` be salvaged?** The finding says the box is unused. A cheaper intervention than any of this: make the executing agent tick boxes as it goes, and the signal appears for free. That is a workflow change, not a product, and it would need a different note.
- The 48 tail-smuggled paths (case 3) and the tail-ambiguity rule (case 4) are the only genuinely fiddly part of the parser. Budget for them.
