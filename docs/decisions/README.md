# Decision records

Doug's architecture decisions, one file per decision, newest number wins.

These exist for two reasons. The ordinary one: a decision's *rejected
alternatives* are the expensive thing to reconstruct later, and neither
the code nor the git history records them. The Doug-specific one: these
files are an input to Doug's own reader. Given a PR and the decisions
that bear on it, the reader reports where the change deviates from what
was already decided — so a record that is wrong or stale does not just
mislead a human, it produces a confident false finding.

A record that changes part of an earlier one uses `amends` / `amended_by`, not
`supersedes`. The distinction is load-bearing: ADR-0018 removed one constant
from ADR-0012's freeze while leaving ADR-0012's coverage bar fully in force, and
`supersedes` would have read as retiring the bar too. Mark BOTH sides — an
amendment recorded only on the newer record leaves the older one asserting
something untrue to every reader, including this reader.

## Format

Frontmatter is parsed, so it is a contract, not decoration:

```markdown
---
title: Short imperative statement of the decision
status: accepted | proposed | superseded | deprecated | rejected
date: YYYY-MM-DD
supersedes: ADR-0002        # optional — this record replaces that one wholesale
superseded_by: ADR-0009     # optional
amends: ADR-0012            # optional — this record changes PART of that one
amended_by: ADR-0018        # optional
---

## Context
What forced a decision. Evidence, with numbers where they exist.

## Decision
What was chosen.

## Rejected
What else was considered, and why it lost. Not optional — a record
without this is a note, not a decision.

## Consequences
What this commits us to, including the costs.
```

Only `accepted` records are fed to the reader. A superseded record stays
on disk with `status: superseded` and a `superseded_by` pointer — the
history is the point — but it never reaches the model, because a reader
told "we rejected LLM-assisted scoring" would flag the shipped reader
as a deviation and be exactly wrong.
