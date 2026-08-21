# Product Spec: Walked Out

Written 2026-08-19 from [design-lock.md](design-lock.md); the lock wins on conflict.

## How it changes everything

**Human reviewer on the check run.** Before: a finding the reader stops mentioning disappears; you cannot tell fixed from forgotten. After: every check run carries a `### Since <sha12>` section. The first line says how many of Doug's earlier findings on unchanged files the reader went silent on. Each earlier finding is listed as carried forward, as no longer carried with the evidence named, or as something Doug cannot judge, with the reason. This is the load-bearing change. The Saint Bernard leaves when it sees you walk out, not when it loses sight of you.

**Coding agent in a fix loop.** Before: no signal. After v1: still none. The agent surface (`get_convergence`, the receipt) ships in v1.1 with the guidance string. In v1 this is a future user, not a served one.

**EM reading a published number.** Before: no number. After v1: a per-PR count on Doug's own check runs and a pre-registered definition of the silence rate. The scoreboard number is v1.1; until then the EM gets a method, not a dashboard. A nice-to-have.

## Journeys

**Before.** Push, read, list. Push again, read again, a different list. Nobody knows what the second list dropped, or why.

**After.** Doug hashes every hunk it was sent, stores the index with the read, and one small attribution call maps each finding to the hunks it rests on (code validates the numbers; a failed call stores nothing and costs nothing). On the next reader-tier read of the same PR the classification compares stored rows only — no model call, no network call at classify time, replayable from rows.

Cliffs, each named on the check run:

- **Renamed file.** Exact-path identity; the old path leaves the later patch, so `unknown(left-diff)`: "no longer in this PR's diff."
- **Force-push or rebase.** Doug compares the last two reader reads it has, whatever history did between them. Hunks pulled into base leave the diff and read `unknown(left-diff)`.
- **File outside coverage.** If either read cut or skipped the file, `unknown(file-uncovered)`. An absent file in the prior index is not an empty set.
- **Pre-migration first pair.** The first read after the migration has no prior index, so every earlier finding is `unknown(no-hunk-index)`: one "cannot compare" pair per open PR. Expected.
- **Multi-hunk partial edit.** The stored attribution decides: every attributed hunk survives → carried forward; every attributed hunk edited and the reader silent → Doug stops carrying it; mixed, missing, or abstained attribution → `unknown(not-reconfirmed)`, named on the check run. On the measured corpus this answers 50 of the 59 findings the pure file-delta design abstained on; the 9 that straddle edited and surviving hunks stay abstentions.
- **Fix landed in another file (#75).** The cited file is unchanged, so the finding is carried forward with `pair_delta=changed-elsewhere` and a sentence saying a human should look. The pre-declared false-`persisted` class; Bar B bounds it at ≤1/26.
- **Base absorption.** Another PR lands the same hunks in main; they vanish from this patch. `unknown(left-diff)`, never `resolved`.
- **Reader flips toward `new`.** The later read reports a finding on a file whose diff did not change. Doug lists it under "New on files unchanged since <sha12>" and never hides it. The reader's noise runs both ways; both are printed.

## v1 / vNext

**v1 (load-bearing minimum).** `reads.hunks` column and per-finding attributed hunk hashes (migration 12). The post-read attribution pass (ADR-0014). `convergence.classify` with the new rule 5 table plus the attribution refinement. `store.convergence_for(verdict_id)` as the only importer, degrading to a weight-0 notice on a DB error. One `### Since <sha12>` section: headline count, provenance, states. Silence-rate pre-registration as a sibling in `convergence-design.md`. Bars A(B) and B pre-registered and run on the immutable 43-unit sample with the emulated index. No wire, API, or web change.

**vNext, each with its promotion trigger:**

- **Guidance string, `disproved`, `nothing-carried`.** Trigger: a first consumer (MCP `get_convergence` or the receipt); ≥10 prospective `resolved` units with an index on both sides, hand-checked, zero false; a Bar-B-style false-`persisted` sample. Payload frozen by addendum before that consumer.
- **Scoreboard silence rate.** Trigger: sibling pre-registration in place; Andrew's ruling on the reland-labeler gate. Web validator first, API second, ADR-0005 form.
- **Option A spans + ADR-0014.** Trigger: a published prospective abstention rate after ≥N pairs; a pre-registered span-validation design against sent hunks; an ADR superseding ADR-0012's SCHEMA clause.
- **Governor shadow → live + prereg v10.** Trigger: shadow over the 37 zero-overlap pairs shows ≤1 real `new` on touched files; then a prospective v10, never retroactive.
- **Stuck-loop alarm.** Trigger: the first autonomous loop with ground truth, which needs the MCP surface.
- **Comparative study of other reviewers.** Trigger: Bar A(B) passes; `hunk_index` reused as a library on public repos; third-party terms checked first.
- **Compare-API base-absorption evidence.** Trigger: the prospective `left-diff` share matters to a consumer. Never in the classification path.

## Honesty contract

**We claim.** Doug stops carrying a finding forward only with deterministic evidence. Doug carries a finding forward by construction when the cited file's diff is byte-unchanged. Doug abstains everywhere else and names the reason. Doug prints, on every check run, how many of its own earlier findings on unchanged files its reader did not mention again. Advisory; never blocks; never writes the fix.

**We refuse to claim.** "Fixed" or "verified." "The defect cannot have moved." Any hunk-grain precision number before prospective rows exist. Any rate or ratio on the check run. Any comparison to another tool. "Doug knows your agent is stuck." "Finer than GitHub's `outdated`" (it is stricter and reproducible). That Doug's deterministic index knows which hunk a finding is about: it does not — the attribution is model output, validated against the sent hunks, stored once, and never re-derived at classify time.

**On the edge cases.** `resolved` means "Doug stops carrying it," never a verified fix. `persisted` inherits the reader's `file` field, which is model text and was wrong on disk once (#75). Bar A(B) at n=6 licenses exactly: "0 of 6 retrospective `resolved` units were false; self-labelled; emulated; Clopper-Pearson 95% upper bound about 0.39." (The 43-unit split under this design is 6 resolved, 26 carried forward by construction, 11 cannot say.) The emulation assumes main is append-only and PR ancestors reach main only through this PR's squash.

**v1 check-run copy.** Never contains the strings `stale`, `failure`, `success`, `cancelled`, `timed_out`, or `miss rate`. After the headline and provenance, each finding line opens `` `rule` · path — `` and continues:

- Headline: "Of N earlier findings on files unchanged since `<sha12>`, M were not mentioned by this read." Number agreement follows the counts ("Of 1 earlier finding … 1 was"), and a zero denominator renders "No earlier findings on files unchanged since `<sha12>`." — never "Of 0" (amended 2026-08-20, from Doug's own review of PR #164).
- Provenance: "Compared with Doug's last diff read at `<sha12>`. This section grades Doug's own reader, not your change; the reader's silence is not evidence. Advisory, like everything on this surface: it enters no score and blocks nothing." (The last sentence was added with ADR-0015's explicit extension of ADR-0010's surface, same review.)
- **Still here** — by-construction, unchanged: "cited file's diff is byte-unchanged since `<sha12>`; carried forward, not re-verified."
- **Still here** — by-construction, changed-elsewhere: "cited file's diff is byte-unchanged since `<sha12>`; other code in this PR changed. Carried forward, not re-verified. If you addressed it elsewhere, a human should look."
- **Still here** — attributed-surviving: "the hunks this finding was attributed to are unchanged since `<sha12>`; other parts of the file changed. Carried forward, not re-verified."
- **Can't say** — edited-not-verified (attributed): "the hunks this finding was attributed to changed since `<sha12>` and this read did not report it again; Doug has not verified a fix, so it stays listed."
- **Can't say** — not-reconfirmed: "part of the cited file's diff changed since `<sha12>`; this read did not confirm or clear it, and Doug has no usable attribution for it."
- **Can't say** — no-hunk-index: "Doug has no hunk record for one of the two reads, so it cannot compare."
- **Can't say** — file-uncovered: "Doug did not read this file in one of the two reads (cut or unseen)."
- **Can't say** — left-diff: "no longer in this PR's diff (reverted, renamed, or landed another way); Doug cannot tell which."
- **Can't say** — settled: "Doug's own deterministic check disproved this finding at this head; not counted as your progress."
- **Can't say** — edited-not-verified: "the cited file's diff changed since `<sha12>` and this read did not report it again; Doug has not verified a fix, so it stays listed."
- **New (N)** — as today.
- **New on files unchanged since `<sha12>` (M)** — "this read reported a finding on a file whose diff did not change; the earlier read did not."

**Silence rate, ADR-0005 form (scoreboard, v1.1).** "On Doug's own repository, supervised sessions, across consecutive reader reads of the same PR: of 213 earlier findings on files unchanged between the reads, the reader did not mention 160 (75%) again. File grain, emulated from history; the prospective hunk-grain figure replaces it when it exists."

## Andrew's rulings (2026-08-20)

1. **Identity: measured, ruled.** Andrew ordered a verification pass instead of confirming either option. The pass ran 2026-08-20 and all three pre-declared bars passed ([span-verification.md](span-verification.md)). **A-prime is in v1**: a validated attribution pass refines option B's hunk identity, so most multi-hunk partial edits now get an answer instead of an abstention (50 of 59 on the measured corpus). Reader schema untouched; ADR-0012 stays closed; ADR-0014 records the pass.
2. **Per-PR count: keep.** The count on Doug's own check runs is a fact about that PR, not a published number under the prereg. Ships in v1 as specified.
3. **Labeler gate: does not apply.** The silence rate carries no defect labels, so the reland-labeler fix does not gate it. The fix still gates any defect-labelled publication.
4. **The `resolved` direction: demoted (Andrew's ruling, 2026-08-20).** Bar A(B) failed — 6 of 11 sample `resolved` units were false ([phase0-results.md](phase0-results.md)). v1 has no `resolved` state: edit-based calls render `unknown(edited-not-verified)`, and in v1 Doug never stops carrying a finding on its own inference. Verify-at-resolve is pre-registered for v1.1 (full prereg with its own bars before implementation).
