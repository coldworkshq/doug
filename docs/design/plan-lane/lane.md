---
lane: plan-lane
vertical: Console
status: parked
opened: 2026-08-18
closed:
next: build design.md §9 step 1 — verticals.toml (declared path→area map) plus a read-only CLI over `git worktree list`. One day, no infra, no model.
branches: [claude/great-villani-bb55c4]
prs: [129]
supersedes:
---

# Lane: plan lane — verticals, lanes, and checkpoints

A board for work several people or agents do at once in one repo, without colliding, and a way to stop at a checkpoint so anyone else resumes exactly where you left off. Doug watches it and never blocks it.

**Status: designed, not built.** The design is locked; nothing has been implemented. `next` above is the first build step.

## Read in this order

1. **[idea.md](idea.md)** — the capture. From a GitHub Actions run graph rendered vertical. Records the split that must hold: the deterministic git-join half ships; the drift and stale-doc half rides the `unvalidated` deviation instrument and must not ride in on the first half's cost.
2. **[deterministic-half.md](deterministic-half.md)** — the measurement record. Corpus census, the dead-checkbox finding, the 31% intra-plan collision rate. Superseded as design, authoritative as evidence.
3. **[design.md](design.md)** — the locked design. **Start at §0**, which states why Doug holds this and carries the commands to reproduce every number in it.

## What a resumer most needs to know

- **The `- [ ]` checkbox is dead.** 76 `- [x]` lines have ever been added across 31 plans and every one landed in the commit that created the file — never once flipped. Do not build progress on it.
- **31% of tasks (36/116) declare no file unique within their own plan.** They can never be attributed by a file join and must render as `unresolved`, visibly distinct from `not started`.
- **41 of 45 branches with unmerged commits are 5+ days cold.** That is the rescue case, and the reason the board earns its keep.
- **This is internal tooling, deliberately.** It inherits none of the honesty contract. The moment it renders on a check run it becomes a customer surface and inherits all of it — a separate decision, not a follow-up commit.

## Out of scope, and why

Design-drift and stale-doc flagging. They ride the deviation instrument, still labelled `unvalidated` after the 2026-07-31 derangement-check FAIL, and ADR-0007 binds a new unvalidated signal to its own stream. Their deterministic cousin — plan churn, measurable with `git log` on one file — is in scope.

## Related

`../session-lane/` — overlapping and deferred-adjacent. Its `footprint` events are a richer source for the same join, and its deferred collision warnings are this lane's core feature, already specced. `design.md` §8 states the seam.
