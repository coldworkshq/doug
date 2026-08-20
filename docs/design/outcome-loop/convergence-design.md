# Convergence scoring — design note (pre-registered)

**Date:** 2026-08-11 · **Status:** pre-registered before implementation ·
**Charter:** `docs/superpowers/specs/2026-08-11-two-lane-plan-design.md` §3.

Convergence answers "is this PR converging?" beside the risk score's "how hard
should we look?". It is a finding-diff over verdict rows already in the ledger:
no new read, no new paid call, no schema change. Tasks 2–4 implement THIS NOTE
verbatim; a flaw found during implementation is fixed here first, in its own
commit, with the reason recorded.

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
(adding one is an ADR-0012 experiment — out of scope). [Amended 2026-08-20:
identity gains the cited file's hunk-hash multiset and, where stored, a
validated per-finding attribution — see "Rule 5 replaced" below. The reader
SCHEMA still carries no line numbers; ADR-0012 stays closed.]

## Classification of a prior finding, against the LATER verdict

1. Identity present in later verdict            → persisted
2. Identity incomplete (file NULL, either side) → unknown(identity-incomplete)
3. later read has file in files_unseen, or file_cut covers it, or file in
   files_dropped, or later read row missing     → unknown(file-uncovered)
4. later verdict's reasons include a settlement-notice rule whose label
   names this finding's file and slug           → unknown(settled)
   [Doug disproved it; nobody fixed anything]
5. otherwise                                    → resolved
   [superseded 2026-08-20 — see "Rule 5 replaced" below; absence of a
   mention is not evidence of a fix]

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

**Labelable pair** (the term bar 1's STOP threshold counts): a consecutive
reader-verdict pair whose *earlier* verdict carries at least one reader finding
with a complete identity. Anything less has nothing for a human to grade — a
pair of empty verdicts is not evidence that the classifier is right. Defined
here rather than in the evaluation script so the STOP threshold cannot be
loosened by redefining what it counts.

## Invariants

Not in score() (structural test); no new paid re-read at classify time;
derived from stored rows. [Amended 2026-08-20: one additive nullable JSON
column on `reads` and one on `findings` (migration 12); reader `SCHEMA` and
`PROMPT_HASH` untouched. The attribution pass (ADR-0014) is one small model
call at read time, never at classify time.]

## Per-finding classification (amendment, 2026-08-11 — see the amendment log)

`classify(prior_findings, later_findings, later_reasons, later_read)` returns
one entry per input row: the row itself, which side it came from, its state,
and, for `unknown`, the reason. `compare` is defined as the aggregate of exactly
this list, so the counts a receipt shows and the labels a human grades are the
same classification, computed once.

| state | side | meaning |
| --- | --- | --- |
| `persisted` | prior | rule 1 — the identity is still there |
| `resolved` | prior | rule 5 |
| `unknown` | either | rules 2–4, with the reason attached |
| `excluded` | either | not a reader finding (`from_rule` is None) |
| `new` | later | first appearance of a complete identity |
| `matched` | later | the later occurrence that made a prior row `persisted` |

`matched` exists only so every input row gets exactly one entry; a persisted
finding is counted once, on the prior side. Each count in `ConvergenceReport` is
the number of entries in the corresponding state, `unknown` broken down by
reason — no state is counted twice and none is dropped.

Where an identity appears `p` times before and `l` times after with `p > l`, the
first `l` prior rows in input order are `persisted` and the remainder run rules
3–5. The choice is arbitrary — the rows are indistinguishable under an identity
that carries no line number — but it is fixed so the same ledger always yields
the same labels.

## Rule 5 replaced — hunk-evidence classification (amendment, 2026-08-20 — see the amendment log)

Bar 1 of `convergence-eval-results.md` FAILED: 26 of 43 sampled findings were
"resolved" on files nobody touched, because rule 5 reads the reader's silence
as evidence. The redesign is locked in `docs/design/walked-out/design-lock.md`
(the lane folder wins on conflict); this section is the note-resident
pre-registration the implementation binds to.

**Input rows.** `classify(prior_findings, later_findings, later_reasons,
later_read, prior_read)` — both reads' rows now carry `hunks`
(`{path: [sha256, …]}`, the content-hash index of the unified hunks each read
was SENT; hash over `+`/`-` lines only, no `@@` numbers, no context), and each
finding may carry `hunks` (the validated attribution: the subset of its file's
hunk hashes the finding was attributed to at read time; NULL when absent).
`classify` stays pure; every hash and attribution is an input, never derived
here.

**Rules 1–4 and their order are unchanged.** Rule 5 is replaced. For a prior
identity absent from the later read and not abstained by rules 2–4:

| Condition | State |
|---|---|
| `file` absent from the PRIOR index (prior read did not send it, or the path is model text that was never in a patch) | `unknown(file-uncovered)` — rule 3 extended to the prior side; an absent key is not an empty set |
| either read has no index (pre-migration row; old revision) | `unknown(no-hunk-index)` |
| prior multiset == later multiset | `persisted(basis=by-construction)`, with `pair_delta ∈ {unchanged, changed-elsewhere}` from whether any file's multiset differs between the reads |
| every prior hash absent; `file` present in the later patch with ≥1 hunk | `resolved(basis=hunk-edited)` |
| every prior hash absent; `file` absent from the later patch | `unknown(left-diff)` — covers file reverted to base, pure rename, and hunks absorbed into base |
| some prior hashes survive, or prior ⊂ later | `unknown(not-reconfirmed)`, then the attribution refinement below |

**Attribution refinement (span-verification verdict, 2026-08-20).** For a
finding that would classify `unknown(not-reconfirmed)` and carries a stored
attribution: every attributed hash still present in the later multiset →
`persisted(basis=attributed-surviving)`; every attributed hash absent →
`resolved(basis=attributed-edited)`; mixed, invalid against the prior index,
or NULL → `unknown(not-reconfirmed)` unchanged. The attribution is model
output validated at read time against the sent hunks
(`docs/design/walked-out/span-verification.md`: 0/84 state flips across
identical double runs, 42/42 controls, 0/25 danger-class contradictions,
50/59 yield on the abstention class); it is stored once and never re-derived
at classify time. ADR-0014 records the pass; generative model-emitted spans
remain out (ADR-0015+, vNext).

`new` findings carry `code_changed: bool` from the same indexes. Rule 4 keeps
its output `unknown(settled)` in v1. `ratio` keeps its definition; `unknown`
never enters it.

**The `left-the-pr` label** (evaluation vocabulary, not a classifier state): a
defect present in the `to_head` tree but absent from the PR's three-dot delta
— neither fixed nor still-present in the change under review. Used when
hand-labelling `unknown(left-diff)` units so "left the diff" is never graded
as either a fix or a miss.

**Emulation assumptions** (every historical-index number carries the label
`hunk-emulated`): main is append-only, and PR ancestors reach main only
through this PR's squash. The emulated base is `git merge-base origin/main
<head>` per side.

### Pre-registered bars for the replaced rule (declared before the re-run's labels)

Bar 1 above stays FAILED as recorded; these are new bars on the redesigned
rule, evaluated on the same immutable 43-unit sample (frame and seed per
`convergence-eval-results.md`), and reported for BOTH classifiers: the pure
file-delta table and the attribution-refined one (refined inputs join the
frozen attributions from `docs/design/walked-out/span-verification/`, so the
re-run stays $0 and offline).

- **Bar A(B) — zero false `resolved`.** Every unit the redesigned rule calls
  `resolved` is hand-checked; zero may be false. Pure-table n = 6 (the spike's
  seventh, `#67 web/package-lock.json`, is `unknown(left-diff)` under the
  lock); the licensed sentence is "0 of n retrospective `resolved` units were
  false; self-labelled; hunk-emulated", with the Clopper-Pearson 95% upper
  bound reported beside n. The refined classifier's additional `resolved`
  units enter the same bar with the same zero-false requirement.
- **Bar B — false `persisted` ≤ 1 of 26.** The 26 by-construction units are
  labelled by Andrew (`hunk_multiplicity.csv`, `in_sample=True,
  optB=by-construction`); a unit is false-`persisted` when the defect was in
  fact addressed although the cited file's diff is byte-unchanged. `#75`
  (deploy-ordering; fix landed in another file) is pre-declared as the
  expected member of this class.
- **Coverage covariate (bar 2's measurement, carried forward):** the re-run
  reports whether any prior finding's `file` failed to string-match a path in
  the later read's coverage lists.

### Silence rate — sibling pre-registration (publication, v1.1)

- **Numerator:** earlier findings on files whose diff is unchanged between
  consecutive reader-tier reads of the same PR that the later read did not
  mention again.
- **Denominator:** all earlier findings on files whose diff is unchanged
  between those reads.
- **Population sentence (ADR-0005 form):** "On Doug's own repository,
  supervised sessions, across consecutive reader reads of the same PR: of
  {denominator} earlier findings on files unchanged between the reads, the
  reader did not mention {numerator} ({rate}) again." File grain, emulated
  from history (160/213 = 75% on the eval corpus); the prospective hunk-grain
  figure replaces it when it exists.
- The **per-PR silence count** is a fact on Doug's own check runs and ships in
  v1 (Andrew's ruling 2, 2026-08-20). The rate goes to the scoreboard in
  v1.1, web-validator-first. The reland-labeler gate does not apply — the
  rate carries no defect labels (Andrew's ruling 3, 2026-08-20). No ratio or
  rate appears on any check run.

---

The sections above are the pre-registration. Everything below pins the details
the rules above name but do not spell out — the exact strings, the exact
matching semantics, and the cases the rule list leaves open. They are part of
the pre-registration and bind the implementation identically.

## Pinned vocabulary — the settlement notices (rule 4's keys)

Exactly two rule strings, both emitted as weight-0 `Reason`s appended to the
later verdict's reasons by `review.py` after `settle.py` drops a finding:

| rule string | emitter | label |
| --- | --- | --- |
| `settled-missing-import` | `settle.settlement_notice` (settle.py:192) | `Dropped {n} finding(s) disproved by runtime import at head — {segments}` |
| `settled-schema-dependency` | `settle.schema_settlement_notice` (settle.py:291) | `Dropped {n} finding(s) disproved by the live schema — {segments}` |

`segments` is `"; ".join(f"{d.file}: {d.category_slug} ({extra})")` over the
dropped findings, where `extra` is `claimed_names(d)` for the import notice and
`claimed_columns(d)` for the schema notice (settle.py:187-190, 287-289). Both
labels use an em dash (` — `) as the header/segments separator.

"Names this finding's file and slug" therefore means, precisely: split the
label once on ` — `, split the remainder on `"; "`, and read each segment as
`file`, `": "`, `slug`, `" ("`. A segment matches a prior finding when the
segment's file equals the finding's `file` string AND
`patterns.normalize(segment_slug.removeprefix("reader:"))` equals the finding's
canonical pattern. The `removeprefix` mirrors settle.py:72 and :208, which
tolerate a `category_slug` that already carries the prefix; the normalize call
is what makes rule 4 agree with the identity key rather than with the raw slug.

A settlement notice whose label does not parse into segments (a future emitter
changing the format) matches nothing, so rule 4 stops abstaining and rule 5
starts calling those findings `resolved` — the dangerous direction. `settle.py`
and `convergence.py` are pinned to each other by a test asserting the two rule
strings and the label grammar; changing either emitter must break that test.

## Pinned matching semantics

- **Path comparison is exact string equality**, everywhere: the coverage lists
  (`files_unseen`, `files_dropped`), `file_cut`, and identity. `findings.file`
  is model-emitted (`ReaderFinding.file`) while the coverage paths are derived
  from the diff headers, so the two can in principle disagree on form for the
  same file. No normalization, no suffix matching: a rule that guesses which
  paths mean the same file is a rule that can guess wrong in both directions,
  and the cheap guard (suffix matching) only shifts the error, it does not
  remove it. The exposure is real and it fails toward `resolved`, so **Task 3's
  evaluation must report whether any prior finding's `file` failed to string-
  match a path in the later read's coverage lists** — that measurement is what
  bar 2 exists to make.
- **`file_cut` covers a file** when `file_cut == file`. `file_cut` is a single
  path — the file the budget landed inside, seen in part (reader.py:429-431) —
  and a partially-seen file cannot settle an absence.
- **A missing later read row** (`later_read is None`) makes every prior finding
  `unknown(file-uncovered)`. Only reader-tier verdicts get a `reads` row
  (store.py:143-150); no row means we cannot say what the later verdict saw.
- **Coverage fields may be NULL**: `changed_files` and `files_dropped` are
  migration-007 columns, NULL on historical rows (store.py:161-164). A NULL
  `files_dropped` is read as "not tracked", i.e. contributes no coverage
  evidence — it does not abstain by itself and it does not resolve by itself.

## Pinned open cases (what the rule list above leaves unstated)

- **Later-side findings with `file IS NULL` are `unknown(identity-incomplete)`,
  not `new`.** "Every comparison involving it" includes the later side: such a
  finding is set aside before matching, so it can neither absorb a prior
  finding into `persisted` nor inflate `new`. `new` therefore means "a
  complete-identity finding that was not there before".
- **Non-reader rows are excluded on both sides before anything else runs**
  (`patterns.from_rule(...) is None`), including the settlement notices
  themselves, the deterministic tier's reasons, and the truncation notice.
  They are read only as rule-4 evidence, never as findings.
- **Count matching within one identity**: with `p` prior and `l` later
  findings of the same identity, `min(p, l)` are `persisted`, the `p - l`
  surplus prior findings each run rules 3–5 independently, and the `l - p`
  surplus later findings are `new`.
- **`unknown` reports only non-zero reasons.** An empty dict means no
  abstentions, not "the reasons are unavailable".

## Invariant tests (each invariant gets one)

| invariant | test |
| --- | --- |
| never enters `score()` | structural test: no module under `api/doug/` except the receipt path imports `convergence` (`scoring.py:138` is the scorer) |
| no new paid read | the module is pure — no store import, no engine, no clock, no network; enforced by the same structural test reading its source |
| three states, `unknown` never folded into a ratio | `ratio` uses only `resolved` and `persisted`; test pins that adding an unknown does not move it |
| coverage-aware | uncovered-file and missing-read-row tests |
| settle-aware | settled-finding test, plus the settle.py↔convergence.py pinning test |

## Spend

Phase 1 is $0 — ledger reads only. No paid probe is pre-registered here; one
would have to be added to this note before it ran.

## Amendment log

**2026-08-11, during Task 3 Step 1 — added `classify`.** The note as first
written pre-registered bar 1 (`resolved` precision on a hand-labelled sample)
against an interface that returns counts only. Precision needs to know *which*
prior findings were called `resolved` so a human can mark each one
actually-fixed or not; counts cannot be labelled. The bar was therefore
unmeasurable as pre-registered.

The alternative — the evaluation script re-deriving classifications from these
rules on its own — was rejected: a second implementation would grade labels the
shipped classifier never produced, and the bar would then say nothing about what
a receipt shows. One classification path, two views of it.

No rule, order, identity key, bar, or floor changed. Recorded before the
implementation, per the pre-registration discipline.

**2026-08-11, same task — the state set gained `matched`.** The amendment above
first listed five states, which cannot give one entry per input row: a later
finding that keeps a prior one alive is an input row with no state of its own,
and reusing `persisted` for it would double every persisted finding in any count
taken over the list. `matched` names that row and is counted nowhere. Recorded
before implementing, same discipline.

**2026-08-11, same task — defined "labelable pair".** Bar 1 STOPs below 10
labelable pairs, but the note never said what makes a pair labelable, which
would have left the threshold to whatever the evaluation script happened to
count. Defined under the bars above, before the script was written. The
threshold itself is unchanged.

**2026-08-20, after the Task 3 evaluation — rule 5 replaced; hunk-identity
input; attribution refinement.** Bar 1 failed arithmetically (5 confirmed
false-`resolved` in the 43-unit sample ⇒ precision ≤ 0.884 < 0.90), and the
root cause was upstream of the rules: rule 5 reads the reader's silence as
evidence, and the reader is nondeterministic — 26 of 43 sampled findings were
"resolved" on files nobody touched. No repair of the sample or reordering of
rules 1–4 can fix a rule that treats absence of a mention as a fix.

The replacement (designed and locked in `docs/design/walked-out/`, debated,
red-teamed, and measured there) makes `resolved` require deterministic
evidence: the cited file's hunk-hash multiset changed, or — under the
attribution refinement validated by the pre-registered span-verification pass
— every hunk the finding was attributed to was edited. Byte-unchanged files
carry forward by construction; everything else abstains with a named reason.
The alternatives killed, with reasons, are in the lock's "Resolved tensions".

This entry was recorded before any implementation code, per the discipline.
The original bars 1–3 stand as recorded (bar 1 FAILED); the new bars and the
silence-rate sibling pre-registration above were declared before the Phase 0
re-run produced labels. The note's original "no schema change, no migration"
invariant was rewritten honestly rather than silently violated: migration 12
adds one nullable JSON column to `reads` and one to `findings`; the reader
`SCHEMA` and `PROMPT_HASH` are untouched, and ADR-0012 stays closed.
