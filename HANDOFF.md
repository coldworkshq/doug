# HANDOFF — doug

--- reader-model lane (2026-09-25 UTC): MODEL moves to claude-opus-5-5, ADR-0037 ---

State:    review — claimed under R5 at 2026-09-25T03:39Z on branch
          claude/reader-opus-5-5 off origin/main eb1c66e, worktree
          .claude/worktrees/reader-opus-5-5. ADR-0037 claimed after checking
          origin/main, every remote branch, and open PRs: nothing named 0037.
          Opened as a DRAFT PR. `reader.MODEL` is claude-opus-5-5; the
          probe, the intent probe, and MECHANICAL_MODEL did not move.
          ADR-0037 amends ADR-0012 and ADR-0016, banners on both sides.
          `make check` 0; api suite 2074 passed, 0 skipped; 5 of 5 mutants
          killed (reader back, probe follows, mechanical follows, each paid
          request site on MECHANICAL_MODEL).
Next:     Founder, before the merge (a merge to main deploys): confirm
          `GET /v1/models/claude-opus-5-5` returns 200 with the org's
          credential. If it does not, every read falls back. Then
          `gh pr ready`, and merge.
Blockers: Model availability is unverified: no local credential reaches
          the Models API.
Decisions this session:
- MODEL leaves the freeze by the founder's direction (2026-09-25), for
  price, without a run — rejected: measuring first, which ADR-0018 costs
  at about a day of blind dispositioning.
- No server-side model fallback on refusal — rejected: a silent rescue on
  another model would record one model and score with another.
- The new test imports the probe by name (importlib) — rejected: a fourth
  static `import llm_probe`, which grows the basedpyright baseline.
Pointers: api/doug/reader.py MODEL · api/tests/test_reader.py
          test_model_diverges_from_the_probe_on_purpose · docs/decisions/ADR-0037

--- carry lane (2026-09-23 UTC): the author's rulings carried forward within a PR, doug#369 ---

State:    review. Lane claimed under R5 at 2026-09-23T06:45Z; ADR-0036
          claimed on doug#369 (issuecomment-5790274380). Worktree
          .claude/worktrees/doug-369-carry-rulings.
          - doug#377 (PR 1): MERGED 2026-09-23T15:14Z as aded2cc.
          - doug#378 (PR 2): MERGED 2026-09-24T04:02Z as 60ed1f3.
          - doug#379 (PR 3): merged 2026-09-24T04:03Z into its base,
            claude/doug-369-carry-pass (cc55a87), NOT into main: its base
            was never retargeted after #378 merged. Re-landed on branch
            claude/doug-369-carry-render-reland off 60ed1f3, same tree as
            cc55a87, as its own PR.
          - doug#381: MERGED 2026-09-24 as eb1c66e, the findings-log rows
            for the later reads.
          - doug#382 (the re-land): rebased onto eb1c66e 2026-09-24 UTC and
            marked ready; also carries 14 rows for Doug's reads of the
            rebased #378 (c4fa32a) and #379 (856ccea), none real.
          PROMPT_HASH 8bd26c67…9a951cdf unchanged; api/tests/test_reader.py
          untouched.
Next:     ANDREW: merge #382 after its read. Each merge deploys
          (ADR-0025) with the flag off. A stacked PR's base must move to
          main before its merge click, or the merge lands on the dead
          branch.
Blockers: three R11 decisions, parked on doug#369: the model tier
          (issuecomment-5790617496; CARRY_MODEL sends the mechanical tier
          until Andrew rules), the findings-log shape of a carried finding,
          and the measured run's bars and corpus. The flag stays off and the
          measured run waits until the bars are frozen in writing.
Decisions this session:
- The description comes from the pulls.get the worker already makes for
  the head check (review.pr_description), not from a new fetch_pr return
  value — rejected: changing fetch_pr's 2-tuple, which touches 20 call
  sites and monkeypatches for no new information.
- Two doug-rulings blocks read as no rulings; an unclosed block, or one an
  earlier unclosed fence swallows, reads as no rows and says why —
  rejected: merging or picking one, both guesses.
- Each ruling is anchored to a stored reader finding with the same rule
  (spelling folded) on the same file of the named read, and resolves to the
  path Doug stored; a short path matching two stored files is skipped; the
  pass offers a finding only rulings anchored to its exact path — rejected:
  resolving rulings by model alone, and suffix matching in the pass (Doug's
  read of bc42b46).
- Carry decisions are stored on findings.carry (migration 018) and ride the
  replay bundle — rejected: recomputing on replay (a second paid pass) or
  not storing (unauditable).
- A changed: true ruling is offered to the model but never carries, so the
  finding can be labeled raised again; a ruling never carries more findings
  than it anchors; decisions apply only after the whole response validates.
- The skip notice is a weight-0 rulings-skipped reason, shown as a note and
  never counted — rejected: stderr only, which the author never sees.

--- earlier lanes (moved 2026-09-26 UTC) ---

Every finished lane's block moved, unchanged, to
`docs/handoff-archive/through-2026-09-26.md`, which is this whole file as of
da9a765, byte for byte, so a line cite into the old file resolves there. Keep
this file to open lanes: overwrite a lane's slots in place, and move a
finished lane's block to the archive.
