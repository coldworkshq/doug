# Design: verticals, lanes, and checkpoints

**Date:** 2026-08-18 · **Status:** design — locked by Andrew, 2026-08-18 · **Class:** internal tooling
**Builds on:** `idea.md` (capture-only), `deterministic-half.md` (the measurement record — every number below is sourced there or restated here with its command)
**Companion:** `../session-lane/design.md` — overlapping and deferred-adjacent; §8 states the seam.

---

## 0. Why Doug holds this

**The gap.** Doug sees a change the moment it becomes a PR, and everything after. It sees nothing before. Work in flight — 39 lanes on this repo right now — is invisible to it and to everyone else, because the only view of it is `git worktree list`.

This design points Doug's **existing** instrument one altitude lower. `intent.py` and the `deviations` table already do declared-vs-actual at the PR. The board does the same thing at the task, from the same kind of declaration (`**Files:**`) against the same source (commits). Nothing new is invented; the aperture widens backward.

```
work in flight  →  checkpoint  →  PR opens  →  merged  →  outcome graded
└──── the board (this design) ──┘  └──── Doug, today (already built) ────┘
```

One instrument, three units: **task** (the board), **PR** (the neutral check run), **outcome** (the ledger).

### Watching

Doug reads what a plan declared and what the branch actually did, continuously, with no model and no new ingest. Every state on the board is a fact about git or an absence of one. §5 lists what it must refuse to say — that list is load-bearing and belongs on the board itself, not only in this doc.

### Rescuing

The strongest evidence in the whole exploration, and the plainest: **of 45 branches carrying unmerged commits, 41 have not been touched in 5 or more days.** Sixteen are 10+ days cold; the oldest is 18 days. That is finished-and-forgotten work — tokens spent, decisions made, tests written — that nobody returns to because nobody can see it.

Rescue is two cheap mechanisms:

- **Visibility.** A cold lane showing `partial · 1 of 2` with the missing file named is recoverable at a glance. A cold branch name is not.
- **Resumability.** The checkpoint carries `State / Next / Blockers / Decisions-and-what-was-rejected`. §7 shows those slots are already right in `HANDOFF.md` and already at the wrong cardinality.

**The limit, stated plainly: Doug surfaces a rescuable lane; it never rescues one.** Never writes code, never opens a PR. It makes abandoned work findable and takeable — a person or an agent does the taking.

### Helping, at the PR

By the time a lane becomes a PR the declared-vs-actual answer is already computed, so Doug's existing review gets sharper for free:

- **declared but never touched** — the real case from `lane2-agent-door`: `convergence-eval-results.md` declared by Task 3, never written, while the eval script was committed with *"not yet run"* in its own subject. A node that reads finished and is not.
- **touched but never declared** — files the change carries that no task planned.
- **contested** — the other live lanes editing the same file, said before the merge rather than during it.

All of it as a section on the existing always-`neutral` check run. No status change, no score, no band.

### What is genuinely new

Almost nothing, which is the argument for building it. The instrument exists (`intent.py`). The visual exists (`web/components/run-spine.tsx` already draws a vertical node run, and its own comments set the colour rules this design obeys). The checkpoint slots exist (`HANDOFF.md`). The collision warning is already specced, verbatim, in `session-lane`'s deferred list (§8). Missing: one declared file and one read-only script.

### Provenance — read these in order

1. `idea.md` — the capture. Andrew, from a GitHub Actions run graph rendered vertical. Records the split that must hold: the deterministic git-join half ships; the drift/stale-doc half rides the `unvalidated` deviation instrument and must not ride in on the first half's cost.
2. `deterministic-half.md` — the measurement record. Corpus census, the dead-checkbox finding, the 31% intra-plan collision rate. Superseded as *design*, still authoritative as *evidence*.
3. **This document** — the design, locked 2026-08-18.

### Reproducing the numbers

Every figure here came from read-only git. A session that wants to verify before building:

```bash
git worktree list                                      # the lanes
git log --name-only --pretty=format: main..<branch>    # what a lane touched
git log --all -p -- 'docs/superpowers/plans/*.md' | grep -c '^+.*- \[x\]'   # the dead checkbox
grep -A6 '\*\*Files:\*\*' docs/superpowers/plans/*.md   # the declarations
git log --name-only --pretty=format: main..<branch> | grep '^docs/superpowers/plans/'  # lane→plan join
```

Collision counts are pairwise set-intersection over those file lists; staleness is `git log -1 --format=%ct` per branch. No database, no API, no model call anywhere in this design.

---

## 1. What this is

A board for work that several people or agents do at once, in one repo, without colliding — and a way to stop mid-flight so someone else picks up exactly where you left off. Version control for the agentic workflow rather than for the code. Doug watches it and never blocks it.

The shape is three nested things, and the visual is the run-graph: **verticals** are columns, **lanes** stack inside them, and each lane is a vertical chain of **node** cards running to a declared end state. A node expands to what was done and what it left behind.

**This is internal tooling and the classification is deliberate.** It reads in-tree markdown and local git, emits nothing customer-visible, and makes no claim Doug is accountable for. Per `idea.md`, internal inherits none of the honesty contract and can ship in a day. The moment any of it renders on a check run it becomes a customer surface and inherits all of it — that is a separate decision, not a follow-up commit.

## 2. The model

Four nouns. What separates them is not importance but **provenance** — whether a human declares it or git computes it. Getting that boundary wrong is how this becomes confidently false.

| Noun | Is | Provenance | Cardinality |
|---|---|---|---|
| **Vertical** | a business area — Front door, Outcome loop, Console, Review pipe, Deploy | **Declared**, once, in a path→name map | a repo has 4–8 |
| **Lane** | one unit of work to a defined end state | **Derived** — it *is* a branch/worktree | 39 live today |
| **Node** | one task within the lane's plan | **Derived** — `**Files:**` joined to commits | 2–12 per lane |
| **Checkpoint** | a resumable state of a lane | **Declared** by whoever leaves | 0–1 live per lane |

**Verticals must be declared.** Naming your business areas is a judgment, and inference fails measurably: classifying the 39 live lanes by dominant path filed `console-design` under **Deploy at 11% confidence** (it is obviously a Console lane), left 6 lanes matching nothing, and put `front-door-phase-1` in Front door on only 27% of its files. Five lanes span three or more verticals. A twenty-line map written by hand and changed twice a year beats a heuristic that is wrong about a third of the board.

**A lane is a branch, not a plan.** `idea.md` left this open. The data closes it: a plan can have several lanes (`lane1-phase-b` and `lane1-phase-b-rebuild` execute one plan), and a lane can outlive or precede any plan. The branch is the thing that exists, gets held, and can be handed over.

## 3. The three joins

Every honest field on the board comes from one of these. Each is **declared, then computed** — never inferred.

**Vertical ← path map.** Declared file. Lane membership computed by dominant classified path. When the dominant share is under ~50% the card says so (`spans 3 · only 27% here`) rather than claiming a home.

**Lane ← plan: the plan file is on the branch.** This is the one that matters, and the measurement is unambiguous:

- Inferring by file overlap: **24 of 38 lanes matched**, with obvious false positives — `landing-brand-match` → the dual-run dashboard plan at 44%, `spend-cap-wiring` → the example-pack workbench plan at 54%. Hot files (`api.py`, `store.py`) are declared by many plans, so any lane touching them matches something.
- Requiring the plan file on the branch: **15 of 38 lanes matched, zero false positives.** Every one correct — `console-design`→`doug-console-phase-1`, `dashboard-ux`→`dashboard-ux`, `front-door-phase-1`→`front-door-phase-1a`.

Take precision over recall. This is `session-lane`'s correlator rule already field-tested: *"On ambiguous multi-match, no join — silence over speculation."* The other 23 lanes render as `no plan · nodes not computable`, which is true and visibly fixable — commit the plan on the branch and the lane lights up. That is a workflow convention, not an engineering problem.

**Node ← commit: the task's declared `**Files:**`.** Parses cleanly — the first backticked token on a `**Files:**` body line resolves to a real repo path **309/312 = 99.0%** across the corpus. Twelve ragged classes are catalogued in `deterministic-half.md`; the parser needs an explicit `unparsed` bucket and must show its size.

## 4. What a node can honestly say

| State | Means | Source |
|---|---|---|
| `done · n of n` | every declared file touched on this branch | git |
| `partial · n of m` | some touched, and it names the missing ones | git |
| `not started · 0 of m` | none touched | git |
| `unresolved` | declared files are all shared with a sibling task | plan |
| `no plan` | no `**Files:**` to join against | absence |

`unresolved` is not cosmetic: **36 of 116 tasks (31%) declare no file unique within their own plan**, and 63 paths are declared by two or more tasks. Those tasks can never be attributed by a file join. They must render visibly differently from `not started` — showing an unresolvable task as an empty node is a false claim about work.

### The expansion

A node card expands to two panels, and only one of them is free:

- **Done** — assembled from the subjects of the commits that touched this task's declared files. Deterministic, and it works here because this repo's commit messages carry real information: `lane2-agent-door`'s eval-script commit is titled *"convergence ledger evaluation script (read-only, **not yet run**)"*, which is the finding. On a repo of `wip` and `fix stuff` this panel is empty. **It rides commit hygiene rather than a model, and that trade is the design.**
- **Outstanding** — fully deterministic in every repo: declared-but-untouched files, touched-but-undeclared files, contested files, and plan churn.

Worked example, real, from `lane2-agent-door` node 3 (`evaluate vs ledger`, `partial · 1 of 2`):

> **Done** — convergence ledger evaluation script, read-only (`22fc300`)
> **Outstanding** — the script is committed *"not yet run"*, per its own subject · `convergence-eval-results.md` declared, never written · `test_convergence_eval_script.py` touched, undeclared

That is a node which looks finished and is not, found without a model.

## 5. What the board must refuse to say

Three refusals, printed on the board itself rather than buried here.

**"% complete."** The checkbox is dead. Across 31 plans and 155 tasks, **76 `- [x]` lines have ever been added and every one landed in the commit that created the file.** Not one has ever been flipped afterwards. `front-door-phase-1a` took 13 commits of active editing — *"close Task 10 restoration window"*, *"merge Task 6 into Task 5"* — with zero ticks. Plans here are living design documents that get re-planned, not checklists that get ticked. `- [ ]` is a step delimiter, not a state field. Node counts measure **declared files touched**, which is not the same as work done, and the board must not round it into a percentage.

**"This will conflict."** Same file is not the same hunk. Overlap is observed; conflict is predicted. The board states the first and refuses the second.

**"Held."** Git has no lock, and a worktree existing does not mean anyone is in it. Today `held` can only honestly mean *last-commit age*. A true held/open signal needs an explicit claim — see §7.

## 6. Collision

Measured live, 2026-08-18: **39 lanes ahead of `main`, 292 colliding pairs.** Hottest contested paths — `api/doug/store.py`, `api/doug/api.py`, `api/tests/test_store.py` at **15 lanes each**, `api/tests/test_api.py` at 13.

Contested files surface in two places: on the node that touches them, and in the lane's expansion. Never as a block, never as a score. ADR-0007 governs — a new signal gets its own stream and never moves `risk_score` or band.

The same instrument reads forward as well as backward. Because tasks declare files *before* work starts, two tasks declaring the same path are two lanes that **will** contend, visible before either agent begins. That is the 31% intra-plan collision rate from §4 read as a feature rather than a defect.

## 7. Checkpoints and handoff

A checkpoint is the point of the whole design: leave at any node boundary, and anyone — person or agent — resumes from it.

`HANDOFF.md` already proves the slots are right. `State / Next / Blockers / Decisions (with what was rejected) / Pointers` is exactly what a resumer needs, and a hook already maintains it.

**Its cardinality is wrong, and the repo says so out loud: `HANDOFF.md` is contested by 12 live lanes — the 5th-hottest merge conflict in the tree.** One file with one set of slots cannot survive the parallelism it exists to serve. The fix is structural, not clever: the checkpoint belongs to the **lane**, so it lives on the branch and merges when the branch does. Same slots, correct cardinality.

A checkpoint is a state of the lane, not a step in it — it renders in the lane header beside `open`, not as a node in the chain. (The mock currently draws it as a terminal node; that is a known error, recorded here so it is fixed rather than inherited.)

## 8. The seam with the session lane

Substantial overlap, and it argues for reuse rather than a second system:

1. **`footprint { entity, role: read|modified|created, at }`** is the same declared-vs-actual join this design computes from git, from a richer source with per-event timestamps.
2. **This design is session-lane's deferred item.** Verbatim from its §6: *"collision warnings ('session B is modifying your footprint right now' — interval intersection, cheap once cards exist)."* That is this, already specced, waiting on session cards.
3. **`boot { …, resumed_from? }` is handoff lineage** and **`checkpoint { next_action?, open_questions? }` on Stop** is the checkpoint. Both already designed.
4. **Lane C already claims plan markdown** — "committed code, architecture docs and ADR markdown in the repo."
5. **Both want the ADR-0010 check run.** Session-lane §6 already claims a section on it. A further reason this stays internal.

**Recommendation:** build the git version now as a read-only probe, and treat it as disposable. If the board proves useful, the durable implementation is session-lane's footprint stream, not a second producer of the same fact.

## 9. Build order

1. **`verticals.toml` + a read-only CLI.** Walks `git worktree list`, classifies lanes, joins plans found on branches, prints the board as text. No service, no database, no model, no infra. A day.
2. **The board renders the CLI's output.** If the CLI is right the board is a rendering; if the CLI is wrong no amount of UI saves it.
3. **Only then, if `held` is wanted:** an explicit claim/lease. This is the line where the design stops being a read-only view of git and becomes a system with state of its own. Cross it deliberately.

**Success criterion, unchanged from `deterministic-half.md`:** the tool must be able to **disagree** with the plan author. If every row restates what the plan already asserts, it is a renderer, not an instrument. It already cleared this bar in testing — the `lane2-agent-door` finding in §4 was produced by the prototype join, not by reading.

**Kill condition:** if `unresolved` plus `no plan` exceeds roughly half the visible nodes, the board implies per-node truth it does not have and should stay a table.

## 10. Constraints honoured, not reopened

**route-never-block** · **Doug never writes code, never opens a PR** · **ADR-0007** — deviations and now lane collisions never touch `risk_score` or band · **ADR-0010** — the surface is an always-`neutral` check run, and nothing here proposes a new one.

Two house rules from the code are also load-bearing here and are obeyed: `run-spine.tsx` — *"Every node here is neutral (done) or hollow (wait)… colouring the SAME fact a second time on a bare dot with no word next to it would assert it twice"*; and `band-chip.tsx` — *"The colour is ALWAYS accompanied by its word."* Every state on the board carries its word.

**Out of scope, deliberately:** design drift and stale-doc flagging. They ride the deviation instrument, still labelled `unvalidated` after the 2026-07-31 derangement-check FAIL. One deterministic cousin *is* in scope and cheap — **plan churn**: `lane2-agent-door`'s first node took 4 commits for a 1-file task, three of them amendments (*"amend convergence note"*, *"name the sixth classification state"*). "The plan was rewritten while you built it" is pure `git log` on one file and needs no instrument.

## 11. Open

- **Cross-vertical lanes.** A card shows one column with a `spans N` chip. Five lanes touch 3+ verticals and one touches all four. Does a lane ever bridge columns visually, or is the chip enough?
- **Many-to-many plans.** `docs/two-lane-plan-2026-08-11` touches two plans; `lane1-phase-b` and `-rebuild` share one. The common case is 1:1; the model should not pretend it always is.
- **Squash-merge erases node granularity at merge.** `main` is linear, single-parent. After merge a whole plan collapses to one commit, so per-node state exists only while the branch is alive. Is a landed lane worth rendering at all, or does it leave the board?
- **Retention.** When does a merged or abandoned lane disappear? 39 live lanes today, many long dead.
