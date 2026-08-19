# Cited Head Reads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a finding cite bounded reads at head to ground an existence-or-value claim, reversing the directional licence that currently lets Doug's outside-the-diff fetcher only subtract findings.
**Architecture:** The fetcher already exists and is wired — `review.py:273 head_file_text`, threaded as `resolve_file` at `review.py:307-337` / `worker.py:237-251`, versioned by `verifier_versions` (`worker.py:31-34`). This increment adds a *second* frozen prompt that emits `{file, line_start, line_end, quoted_text, predicate}`, a predicate runner that executes the check rather than the model's conclusion, an `evidence` discriminator on `ReaderFinding` riding `verdicts.raw`, and an isolated spend scope. The shipped `SYSTEM`/`SCHEMA` and `PROMPT_HASH` are untouched.
**Tech Stack:** Python 3.14, FastAPI, pydantic, uv; pytest. Web is read-only here — no TS change by design.
**Spec:** `docs/superpowers/specs/2026-08-18-cited-head-reads-design.md` [D1–D9]
**Design:** `docs/design/competitor-imports/design-lock.md` [L1–L9]
**Worktree:** `/Users/andrew/Projects/doughq/repo/.claude/worktrees/managed-agent-pr-review-76fe26`, branch `claude/managed-agent-pr-review-76fe26`, cut from `origin/main` @ `b8e3659`

## Global Constraints

- **The model never deletes a finding.** `refuted` must not appear in any schema. Enforced by the superset assertion (Task 6).
- **Existence and value claims only.** Absence and universality claims render `unresolved`, never citation-certified (D3).
- **Predicate names are permanent** — the verify prompt is frozen. Ship `constant_value_is` only. Do not name a predicate that isn't built (D4).
- **Do not touch** `SYSTEM`, `SCHEMA`, `MODEL`, `EFFORT`, `MAX_TOKENS`, or anything feeding `PROMPT_HASH`. `test_reader_and_probe_share_the_validated_prompt_bytes` (`api/tests/test_reader.py:1027`) must stay green untouched.
- **No new key on `Reason` or `PRMetadata`.** Both are validated with exact key-set equality in `web/lib/session-api.ts` (`:170-178`, `:289-292`) — a new key is a rejected payload, not an ignored field.
- **Never charge `installation:<id>`** for verify reads. `instrument_snapshot` (`store.py:1314-1330`) renders that counter as `deep reads N/200` on the customer's check run.
- **Nothing writes `verdicts` beyond today's single row.** No second verdict per PR@sha (`migrations.py:186-188`; a collision is silently swallowed at `store.py:874-885` and triggers a bogus check-run replay at `worker.py:286-301`).
- **Guard:** if any change alters `settle.py`'s notice label grammar, `convergence.py:38` and `:246-270` move in the **same commit** or convergence degrades silently to `unknown`. This increment should not touch that grammar — verify it doesn't.
- No migration. Next free number stays **11** and this plan does not use it.
- MT3 is the main-lane critical path. Touch no file MT3 holds; stay in this worktree.

---

### Task 1: `evidence` discriminator on `ReaderFinding`, round-tripped
**Files:** `api/doug/reader.py`, `api/doug/store.py`, `api/doug/api.py`, `api/tests/test_reader.py`, `api/tests/test_api.py`

- [ ] Add `evidence: Literal["diff", "head-cited"] = "diff"` and `citations: list[Citation] = []` to `ReaderFinding` (`reader.py:330-334`). Default `"diff"` so every existing finding is unchanged.
- [ ] Define `Citation` — `path`, `head_sha`, `line_start`, `line_end`, `sha256`. No `quoted_text` on the persisted record; the hash is the receipt.
- [ ] Confirm it round-trips: `verdicts.raw` (`store.py:81`) already dumps the whole `ReaderVerdict` at `store.py:825`.
- [ ] Test: a finding with `evidence="head-cited"` and one citation survives `save_review` → receipt API unchanged in key set.
- [ ] Test: the run-detail payload key set is **byte-identical** to before (guards the `session-api.ts` validators).
- [ ] Verify `PROMPT_HASH` is unmoved and `test_reader_and_probe_share_the_validated_prompt_bytes` is green.

### Task 2: SHA-anchored citation receipt helper
**Files:** `api/doug/example_pack_verifiers.py` or a new small module, `api/tests/`

- [ ] Extract the byte-slice + sha256 primitive (`example_pack_verifiers.py:133-172`) into a helper that takes *bytes* (not a `Path`) — `settle.py`/`review.py` receive content from the GitHub contents API, not a working tree.
- [ ] Emit `path@<head_sha>#Lstart-Lend` + `sha256` (D6). `sha256_hex` already exists at `example_pack.py:105`; reuse it.
- [ ] Test: the locator is reproducible by `git show <sha>:<path>` for a known fixture.
- [ ] Test: an off-by-one line range produces a different hash — the receipt is range-sensitive.

### Task 3: The separate frozen verify prompt
**Files:** `api/doug/reader.py`, `api/tests/test_reader.py`

- [ ] Add `VERIFY_SYSTEM` and `VERIFY_SCHEMA` alongside `DECISION_INTENT_SYSTEM`/`INTENT_SCHEMA` (`reader.py:135-138`) — the in-repo precedent for a second frozen prompt.
- [ ] `VERIFY_SCHEMA` fields: `file`, `line_start`, `line_end`, `quoted_text`, `predicate`. `predicate` is an enum with exactly one member: `constant_value_is`. **No `refuted` field** (D2).
- [ ] `additionalProperties: False`, matching the shipped schema's posture (`reader.py:70-106`).
- [ ] Test: `refuted` is not an accepted key — a model response containing it fails validation.
- [ ] Test: the shipped `PROMPT_HASH` is unchanged by this addition.

### Task 4: The `constant_value_is` predicate runner
**Files:** new module (e.g. `api/doug/verify.py`), `api/tests/`

- [ ] Pure function: given the head bytes, the cited range, and the expected value, return whether the constant at that location holds the claimed value. Follow `settle.py`'s shape — pure, resolvers injected, `lambda p: FILE` is the whole mock.
- [ ] **Abstain on ambiguity**, matching `settle.py:239`'s rule: if the target cannot be identified unambiguously, return unresolved rather than guessing.
- [ ] Test: fabricated quote → unresolved, finding survives ungrounded.
- [ ] Test: off-by-one range → unresolved.
- [ ] Test: `resolve_file` returns `None` → unresolved.
- [ ] Test: a finding phrased as a universal ("this is the only cap") → unresolved, never grounded (D3).

### Task 5: Spend isolation — land this BEFORE wiring
**Files:** `api/doug/reader.py`, `api/doug/store.py`, `api/tests/test_reader.py`

- [ ] Add a `verify:<id>` scope; third branch in `cap_for` (`reader.py:267`).
- [ ] Hard per-PR verify-read cap; timeout strictly below the 120s read timeout (`reader.py:52`).
- [ ] Test — **the one that fails loudly if anyone reroutes the scope:** a run performing verify reads leaves `instrument_snapshot`'s counter (`store.py:1314-1330`) unchanged, so the customer's `deep reads N/200` footer does not move.
- [ ] Test: charge-before-client ordering is preserved (the existing `assert order == ["spend:…","create"]` pattern at `test_reader.py:596-610`).

### Task 6: Wire into the review path
**Files:** `api/doug/review.py`, `api/doug/worker.py`, `api/tests/`

- [ ] Call the verify path only for findings that name a value/definition target; reuse the existing `resolve_file` threading (`review.py:307-337`).
- [ ] Mark grounded findings `evidence="head-cited"` with their citations; leave everything else `"diff"`.
- [ ] **Superset assertion** — the finding set out is a superset of the finding set in. This is the property that makes "the model never deletes" checkable (Global Constraints).
- [ ] Test: evidence classes never mix — a citation implies `head-cited`, its absence implies `diff`.
- [ ] Test: a verify failure (timeout, cap, error) leaves every finding intact and `diff`-classed.

### Task 7: Surface
**Files:** `api/doug/check_run.py`, `api/tests/test_check_run.py`

- [ ] Render the citation inside `label` via the existing `_oneline` path (`check_run.py:184-190`) — no new `Reason` key.
- [ ] A `head-cited` finding prints: *"This finding rests on code outside the diff. Doug chose which files to open."*
- [ ] Add the D8 coverage sentence: *"Coverage below describes the diff Doug was sent. Files Doug opened at head are not part of that percentage and have no denominator."*
- [ ] Test: the conclusion is still always `neutral` (ADR-0010).
- [ ] Test: `_oneline` still collapses model-authored text — no forged section boundary.

### Task 8: ADR-0013
**Files:** `docs/decisions/ADR-0013-a-citation-may-ground-a-finding.md`

- [ ] House format: frontmatter `title`/`status: accepted`/`date`; sections Context / Decision / **Rejected** (not optional) / Consequences.
- [ ] Must state: a citation changes the finding's **evidence class only** — never `risk_score`, never `band`. The ADR-0007 precedent.
- [ ] Rejected section records: `{refuted: bool}` behind a byte-match; model-authored suppression; the four 0/8 predicates; absence claims as citation-certifiable.

### Task 9: Labeled smoke test
**Files:** `api/tests/` or `api/scripts/`

- [ ] Replay PR #106 @ `616ff99`; report how many of the 8 external findings are recovered.
- [ ] **Label it a smoke test in the code and in any output.** Not a bar: the answers are committed at `docs/reviews/2026-08-12-pr-106-external-review.md`, their "deltas worth encoding" specified this capability, and all 8 were scored before the spec was written.
- [ ] Run it ≥3 times and report the spread — open risk #2 (nondeterminism) is measured, not assumed.

---

## Done means

`make test` and `make lint` green from cold; `PROMPT_HASH` unmoved; the run-detail payload key set unchanged; the customer's deep-read meter unmoved by verify reads; the superset assertion green; the smoke-test spread reported, not claimed. **Merge additionally requires P0.1** — the locked v9 pre-registration published with its hash live.
