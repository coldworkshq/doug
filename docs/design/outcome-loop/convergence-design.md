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

## Per-finding classification (amendment, 2026-08-11 — see the amendment log)

`classify(prior_findings, later_findings, later_reasons, later_read)` returns
one entry per input row: the row itself, which side it came from, its state
(`persisted` / `resolved` / `new` / `unknown` / `excluded`), and, for `unknown`,
the reason. `compare` is defined as the aggregate of exactly this list, so the
counts a receipt shows and the labels a human grades are the same
classification, computed once.

Where an identity appears `p` times before and `l` times after with `p > l`, the
first `l` prior rows in input order are `persisted` and the remainder run rules
3–5. The choice is arbitrary — the rows are indistinguishable under an identity
that carries no line number — but it is fixed so the same ledger always yields
the same labels.

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
