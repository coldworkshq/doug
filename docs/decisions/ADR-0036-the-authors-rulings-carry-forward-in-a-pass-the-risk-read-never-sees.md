---
title: The author's rulings carry forward in a post-read pass that the risk read never sees
status: proposed
date: 2026-09-23
---

## Context

Every push to a PR starts a fresh read that knows nothing about what the
author already ruled on. On coldworkshq/coldworks#105, 9 of Doug's 26
findings repeated something the author had ruled on earlier in the same PR
(doug#369). The author answered each one again, and each push that carried
the answers bought another read.

#310 matches a repeat by rule name and a byte-identical hunk. It carries none
of those nine: the rule names drift (#207 measured why), each round of fixes
edits the hunks, and none of the nine followed a `disproved` ruling. Deciding
that a finding repeats a ruled one is a judgment about meaning, so it needs a
model. It can't be the risk read's model call, for two reasons:

- **The risk read is frozen.** `SYSTEM`, `SCHEMA`, `MODEL`, and `MAX_TOKENS`
  are frozen under ADR-0012, and `PROMPT_HASH` is the anchor that receipts
  and the pre-registration point at.
- **The rulings would reach the governing verdict.** The publication's
  governing verdict is the last reader verdict at or before merge
  (`publication-preregistration.md` §2.1). Later pushes are exactly the reads
  that carry rulings, so author text in the risk read's input could move
  `risk_score` and the band on the verdicts that get published.

ADR-0015 solved the same shape once already: hunk attribution is a separate
post-read pass with its own frozen prompt pair and hash.

## Decision

### The rulings block

The author keeps a fenced `doug-rulings` block in the PR description. Each
line is one JSON object whose fields match a findings-log row:

| Field | Required | Meaning |
|---|---|---|
| `read` | Yes | The head sha of the read that raised the finding, as Doug's comment names it. 7 to 40 lowercase hex characters. |
| `rule` | Yes | The finding's rule, checked with `findings_log`'s own pattern. |
| `file` | Yes | The file the finding names. |
| `verdict` | Yes | `real`, `disproved`, or `adjacent`. |
| `changed` | Yes | Whether the author changed the code for it. |
| `ref` | No | Where the finding is held, such as an issue. |
| `reason` | Yes | The author's reason, in one line. |

Code parses the block, and only code (`api/doug/rulings.py`). The parser
never guesses:

- A malformed row is skipped, and the parser returns it with its reason.
- More than one block means no block. The author maintains one list. Two
  lists are an ambiguity only the author can settle, and both merging them
  and picking one are guesses. Reading none renders every finding fresh,
  which is the safe direction.
- A block that is never closed is read as no rows.
- No block means the pass doesn't run.

The description reaches the worker through the `pulls.get` call it already
makes to check the head. It isn't stored on `PRMetadata`, because `pr_meta`
is stored at every tier and a PR description doesn't belong in that row.

### Each ruling is anchored to a finding Doug raised

Before the pass runs, code resolves every row against the PR's stored
reader-tier verdicts. A row survives only if its `read` is a prefix of
exactly one stored head sha of this PR, and that read stored a `reader:`
finding with the same rule (spelling folded by `patterns.slugify`) on the
same file. A path the author shortens matches a stored path that ends with
it, but a path that matches stored findings on two files is skipped, because
anchoring to either one is a guess. Anything else is skipped and named.

The resolved ruling carries the path exactly as Doug stored it and the stored
finding's own label. The pass matches findings against that stored path, not
the author's spelling, and compares Doug's earlier words with Doug's current
words, with the author's reason beside them.

An author therefore can't rule on a finding that Doug never raised, and a
ruling can't cover a file that its finding didn't name.

### The carry pass

`reader.carry_findings` is a sibling of `attribute_findings`: one batched,
charged call per reader-tier read that has at least one resolved ruling.

- **Its own frozen pair.** `CARRY_SYSTEM` and `CARRY_SCHEMA`, with
  `CARRY_PROMPT_HASH` computed the way `ATTRIBUTION_PROMPT_HASH` is.
- **A closed choice.** For each finding, the model returns a list of the
  ruling ids that the finding repeats, and a boolean for whether the diff at
  head changes the basis of that ruling. Code validates every id. An empty
  list means the finding repeats nothing. More than one id, an id out of
  range, a repeated finding id, or a ruling on another file carries nothing.
- **Only same-file rulings are candidates.** Code lists, for each finding,
  only the rulings anchored to the exact file it names. The model can't carry
  a finding across files.
- **`changed: true` never carries.** A finding that repeats such a ruling
  renders fresh, labeled as raised again after a fix at that read. The label
  is a signal, not proof.
- **A changed basis never carries.** A finding whose ruling the model says
  the diff at head undermines renders fresh.
- **Author text is untrusted input.** It enters the prompt quoted, with its
  length capped, and the output is a closed choice that code checks. Nothing
  the author writes can move the score, the band, or the flag line, because
  the pass runs after the verdict is built.
- **Dark by default.** `carry_enabled_for(installation_id)` reads
  `DOUG_CARRY_INSTALLATIONS`, a per-installation allowlist on the
  `verify_enabled_for` pattern. Unset or empty enables no installation.
- **Off the published meter.** The pass charges its own `carry:` scope prefix.
- **Fails soft.** A spend cap, a transport error, a stop reason, a parse
  failure, or an invalid pick carries nothing, and every finding renders
  fresh, as it does today.

### Storage

The carry decision is stored on the finding's row (`findings.carry`, a JSON
column), written by `save_review` in the same transaction as the verdict,
the way `findings.hunks` stores attribution. This does two things:

- **The decision is auditable.** Each stored decision names the ruled read,
  the verdict, the reason, and `CARRY_PROMPT_HASH`.
- **A replayed check run matches the first one.** The replay path renders
  from stored rows and never buys a second pass.

Convergence doesn't read the column. The `### Since` section and its
identities are unchanged.

### Rendering

A carried finding is never removed. It renders in a collapsed section of the
check run, and the sticky comment mirrors the check run (ADR-0014). Each
carried finding reads as settled on read `<sha12>` as `<verdict>`, followed by
the author's reason and a note that it's the author's ruling, not verified by
Doug. The finding counts show carried findings separately. Doug has no
`resolved` state (`convergence.py`), and a carried finding is settled by the
author's word and says so.

### How this relates to ADR-0010 and ADR-0015

This record extends the check-run surface the way ADR-0015 did. ADR-0010
confined the surface to the risk verdict and the labeled deviations, and
ADR-0015 added the `### Since` section. This record adds the carried
findings section. Unlike the `### Since` section, it shows the author's
claim and not Doug's measurement, and it labels itself that way.

It adds no `resolved` state. ADR-0015 rules that edit-evidence never
resolves and that Doug never stops carrying a finding on its own inference.
A carried finding isn't resolved and isn't Doug's inference. It stays in the
check run and the counts, and it says whose word collapsed it. Doug's own
paths to a future `resolved` stay the two that ADR-0015 pre-registered.

If this record is accepted, ADR-0010 and ADR-0015 each gain an
`amended_by: ADR-0036` line in the same change, and this record gains
`amends: ADR-0010, ADR-0015`. `docs/decisions/README.md` requires both sides
to be marked. Neither side is marked while this record is proposed, so no
accepted record points at an unaccepted one.

### What doesn't change

`read_diff`, `SYSTEM`, `SCHEMA`, `PROMPT_HASH`, `MODEL`, `MAX_TOKENS`, the
risk read's input policy, `risk_score`, the band, and the flag line. The
findings log (`docs/findings-log.jsonl`) stays the accuracy record, with one
row per finding per read.

## Decisions this record leaves to Andrew

These are R11. The code lands dark without them, and each is parked on
doug#369.

1. **The model tier.** The build sends `CARRY_MODEL = MECHANICAL_MODEL`, on
   the attribution precedent: a closed choice that code validates. The case
   against it is ADR-0016's own test: a mechanical pass is one where a wrong
   pick "can only cost an abstention, never a wrong row", and a wrong carry
   collapses a new finding. The measured run should run on the tier Andrew
   picks.
2. **The findings-log row for a carried finding.** One row per finding per
   read stands either way. What is open is whether and how that row says the
   finding was carried.
3. **The bars and the corpus for the measured run.** doug#369 proposes the
   five reads of coldworkshq/coldworks#105 and the eleven of
   coldworkshq/coldworks#104, with the pass carrying at least 8 of the 9
   repeats on #105 and none of the 17 findings that repeat nothing. No
   installation joins the allowlist until the run is scored against bars
   frozen in writing beforehand.

## Rejected

**Rulings in the risk read's prompt.** This changes `PROMPT_HASH`, reopens
ADR-0012's freeze, and puts author text into the input of the governing
verdict.

**#310's rule-name and byte-identical-hunk match.** It carries none of the
nine repeats on coldworkshq/coldworks#105. Keep it for the byte-identical
case or close it in favor of this record.

**Rulings stored by Doug instead of written by the author.** Doug has no
record of the author's ruling to store. The per-finding record that exists,
`ExampleAdjudicationV0`, serves evaluation packs, and nothing writes one
during review.

**Hiding a carried finding.** A ruling is the author's claim. Hiding the
finding would let a false ruling remove a real defect where nobody can see it.

**Merging two blocks, or reading the first.** Either one guesses which list
the author meant.

**Rulings the pass resolves by itself, without a stored finding to anchor
them.** An unanchored ruling lets author text alone decide what a ruling
covers.

## Consequences

- One more model call on each read of an allowlisted installation that has a
  resolved ruling. Its cost is measured against the repeats it saves before
  the flag goes on.
- The block only pays off if authors keep it. This lane fills one by hand in
  each of its own PRs after the parser merges.
- A false carry, which collapses a new defect under an old ruling, is the
  failure that costs the most. The bars must weigh it more heavily than a
  missed carry, and the measured run reports the two separately.
- The reader is nondeterministic (#135), so the measured run double-runs
  every read, and a carry that flips between runs counts against the pass.
- A migration number and this ADR number were claimed, not raced (R5).
