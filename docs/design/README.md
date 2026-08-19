# Lanes — how a unit of work is captured in `docs/`

**One folder per lane.** A lane is one unit of work run to a defined end state, by a person or an agent. Its folder holds everything about it — what was decided, how it was to be built, what happened — and outlives the branch that did the work.

This is not a new idea in this repo; it is the `outcome-loop/` folder's shape, named so the next lane can follow it. See `plan-lane/design.md` for the model this serves (`vertical → lane → node`).

## Why not the dated `superpowers/` folders

They split one lane across two directories by file type. **Twelve of the twenty-five plans have their spec sitting in `superpowers/specs/` under a near-identical name** — `2026-08-04-tenant-api-keys.md` and `2026-08-04-tenant-api-keys-design.md`. Nothing joins them but the filename, and neither knows what happened to the other.

## Shape

```
docs/design/<slug>/
  lane.md      ← index + machine-readable status.  REQUIRED. Everything else is optional.
  spec.md      ← what and why
  plan.md      ← the build plan: `- [ ]` steps, per-task `**Files:**`
  roadmap.md   ← sequencing / task list, when the lane is big enough to need one
  rounds/      ← iterations: review rounds, eval results, PR improvement passes
```

Add whatever else the lane needs. `outcome-loop/` carries preregistrations, runbooks and results, and that is correct — the folder is the record, not a fixed template.

## `lane.md`

Opens with YAML frontmatter, same style as `docs/decisions/`. The frontmatter is the part machines read; the body is for people.

```markdown
---
lane: plan-lane
vertical: Console
status: parked
opened: 2026-08-18
closed:
next: build §9 step 1 — verticals.toml + the read-only CLI
branches: [claude/great-villani-bb55c4]
prs: [129]
supersedes:
---

One paragraph: what this lane is for and why it exists.
Then links to the files in this folder, in reading order.
```

| Field | Required | Meaning |
|---|---|---|
| `lane` | yes | the slug; matches the folder name |
| `vertical` | yes | the business area, from the declared vertical map |
| `status` | yes | see below |
| `opened` | yes | ISO date the lane started |
| `closed` | on close | ISO date it reached a terminal status |
| `next` | while open | the one concrete next action — the checkpoint's Next slot |
| `branches` | as they exist | branches doing this lane's work |
| `prs` | as they exist | PR numbers |
| `supersedes` | if applicable | the lane this replaces |

## Status

| Status | Means | Terminal |
|---|---|---|
| `active` | someone or something is working it now | no |
| `parked` | checkpoint left; `next` says what to do; anyone may pick it up | no |
| `shipped` | merged and live | yes |
| `abandoned` | stopped unfinished — the body says why | yes |
| `superseded` | replaced; `supersedes` on the new lane names this one | yes |

**Why five and not "complete".** `shipped` and `abandoned` are different facts, and one word for both lets stopped work read as finished. This repo has already been bitten by exactly that shape: the `- [ ]` checkbox was never once flipped in the history of the plans corpus, so an untouched box says nothing about whether the work happened. A status field that cannot distinguish "we finished" from "we stopped" is the same mistake with better formatting. Forty-one of forty-five branches carrying unmerged commits are five or more days cold; they need a word that says so.

## Lifecycle

**Opening.** Create the folder, write `lane.md` with `status: active`. Everything else can follow.

**Iterating.** Later rounds — a review pass, a rebuild, PR improvements — go in `rounds/` with a dated name. Do not overwrite the original; a lane that gets revisited should show both what was designed then and what changed.

**Parking.** Set `status: parked` and fill `next`. That is the handoff: a lane with an honest `next` is one anyone can resume.

**Closing.** Set `status` to a terminal value and fill `closed`. **Change nothing else.** The files stay exactly as they were, which is what preserves what was designed *then* — `ADR-0012` rejected editing a record in place for this reason: a rewritten record does not merely mislead, it produces a confident false finding in a reader that trusts it.

## Rules

- **Do not migrate the dated folders.** Seventy-seven references point at `docs/superpowers/*.md` paths — 52 from inside that folder, and 25 from outside it (`docs/design`, `api/`, `HANDOFF.md`, `docs/decisions`). Moving 43 dated files breaks those links in a repo whose stated worst defect is a reference that outlives its truth. This convention applies to new lanes; existing dated files stay where they are and age out.
- **ADRs stay in `docs/decisions/`.** They are cited by number across the codebase and are cross-cutting by nature — they belong to no single lane.
- **Put the lane's plan on the lane's branch.** This is how a branch is joined to its plan without guessing: measured across live branches, "the plan file is on the branch" matched 15 of 38 lanes with zero false positives, where inferring the same link from file overlap matched 24 with obvious wrong ones. See `plan-lane/design.md` §3.

## For an agent picking up a lane

1. Read `lane.md`. `status` says whether it is yours to take; `next` says what to do first.
2. Read the folder in the order `lane.md` lists.
3. `rounds/` is history — read it to avoid relitigating, not to take direction from.
4. On leaving: update `status` and `next`. That is the whole handoff protocol.
