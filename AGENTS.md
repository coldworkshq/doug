# Working rules — doug

## Standing issues

**Anything that outlives the task you are in becomes a GitHub issue, opened at
the moment you decide to defer it** — not at session end, and not "mentioned in
the PR body".

Open one when:

- You write **"follow-up"**, **"not done here"**, **"out of scope"**, **"narrower
  than the spec"**, or **"later"** anywhere — PR body, commit message, roadmap,
  code comment. The words are the trigger. If it was worth writing down, it is
  worth an issue.
- A review finding is real and you are **deliberately not fixing it in this PR**.
- A decision needs Andrew and **blocks nothing right now** (decision debt).
- A check falls on **a date** — a window closing, a clock coming due.
- Production shows you something that is **not the thing you came to fix**.

A roadmap line is **not** a substitute. Discovered-and-deferred work gets an
issue *even when it also earns a roadmap item* — write the issue number next to
the roadmap line so the two cannot drift. MT0 was lost for twelve days
precisely because an unchecked checkbox was its only tracker, and a checkbox
notifies nobody.

Do **not** open one for work already sequenced inside an active milestone's
plan, or for live state belonging to the current session. Those have homes:

| Where | What lives there |
|---|---|
| `docs/design/outcome-loop/ROADMAP.md` | The plan — milestones, gates, sequenced work |
| `HANDOFF.md` | This session's live state. Ephemeral by design |
| GitHub issues | Everything deferred with no home in either. Survives the session, visible without reading a file |

### The issue itself

- **It must stand alone.** Someone who was not in the session must be able to act
  on it: file paths, the evidence, and what "done" looks like. An issue that only
  makes sense to its author is a note, not a task.
- **Link it both ways.** Reference the PR or commit that spawned it, and put the
  issue number next to the deferral in whatever doc mentions it, so the doc and
  the issue cannot drift apart.
- **Close it from the PR that resolves it** (`Closes #N`), never by hand.

### Why this rule exists

This repo has lost follow-ups three distinct ways, all of them found by accident:

1. A **stale roadmap checkbox** — MT0 sat unchecked for twelve days after it was
   closed operationally, and was still being read as the critical path.
2. **"Follow-up, not done here"** buried mid-paragraph in a roadmap item nobody
   re-reads — the receipt shape that shipped narrower than its spec.
3. **Decision debt that lived only in a session transcript**, so no code review
   could see it, and the later ruling that should have governed never amended the
   document it contradicted.

A prose aside in a long document is not a tracking system. An issue is.
