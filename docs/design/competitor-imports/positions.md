# Phase 2 — opening positions (condensed, faithful)

Three cold, independent subagents. Convergences and live tensions marked by the Chief.

---

## CONVERGED WITHOUT DEBATE (all three, independently)

1. **A model may not delete a finding.** Architect: "only mechanically-recomputable evidence may DELETE." PE: "suppression is a byte-match against head, or it doesn't happen." PM: "Model → Narrowed only. Code deletes."
2. **Nothing agentic writes `verdicts`** — not `tier='app'` (silently swallowed → bogus check-run replay), not `tier='external'` (score/threshold hardcoded 0.0, writes no findings by contract). Example Pack lane or nothing.
3. **Verify spend must not touch the customer's advertised meter.** `instrument_snapshot` renders the same counter as `deep reads N/200` on the customer's check run — and it now *clamps* at 200, so overspend shows as an exhausted allowance the customer never used. Separate scope, separate cap.
4. **No finding disappears silently.** `settle.py:192-206` already emits a weight-0 notice on every drop; that is the floor, not the ceiling.

---

## ARCHITECT

**Stance.** Three parts, two builds, one already-built subsystem. Boundary is not deterministic-vs-LLM, it's **suppress-vs-annotate**. On PR #106 the LLM's contribution was 100% refinement, 0% deletion. `settle.py:227-243` records a *measured* false settlement by a deterministic settler — handing delete authority to a model is strictly worse. Build A = settle.py extension (live, zero spend). Build B = agentic instrument in the Example Pack lane (parts 1-LLM and 2 are the same object). Build C = Approach B, ~70% built already. **Sequence A → C → B.**

**New constraints found.** `convergence.py:38` hardcodes a local copy of the settled-rule set and parses settle's label grammar at `:246-270` — a third class means editing both or convergence silently degrades to `unknown`. `web/lib/session-api.ts:289-292` validates `Reason` with exact key-set equality — the same trap flagged only for `PRMetadata`; annotations must ride `ReaderFinding` → `verdicts.raw`, which is unvalidated and absent from the run-detail key list. `run_id = f"{prefix}:{attempt_kind}"` collides across two arms. Hosted requires `attempt_kinds == ("risk",)` exactly. Redeploy doesn't split hosted partitions — it hard-skips capture via `ApplicationRevisionMismatch`.

**Red-lines.** No model call deletes. Challenger never writes `verdicts` (incl. not as external). No new wire-visible key on `Reason`/`PRMetadata` without the paired TS change in the same PR. Challenger doesn't charge `installation:<id>`. No third settled class without updating `convergence.py` grammar in the same change. Part 1's LLM half never graduates to live on offline evidence alone (ADR-0007 precedent).

**Tensions forced.**
- **T2 (sharp):** PR #106's two most valuable bugs were **misses**, not false positives — visible only by *rendering the output*. Verification moves precision. "Do not let a precision build be justified by a recall failure."
- **T4:** `WholeInstrumentManifestV0` is `extra="forbid"` with no orchestration-graph field. Two materially different agent policies can share an `instrument_id`. Add a field or say so out loud.
- **T5:** coverage's zero-call verifiability doesn't transfer. Either B's coverage governs nothing, or build a zero-call gate over the tool-call log — **"every file cited in a finding appears in the read log."** Calls this the most interesting unclaimed piece in the lane.

---

## PRINCIPAL ENGINEER

**Stance.** **Two designs, not three.** Parts 1 and 2 are *the same call at two tool budgets* — the verifier is an agentic reader crippled to one tool, one finding, one question. Part 3 shares zero lines.

**The citation gate (PE's central mechanism).** Second frozen prompt (`VERIFY_SYSTEM`/`VERIFY_SCHEMA`; exact precedent at `reader.py:140,155`). Output forces `{refuted, file, line_start, line_end, quoted_text}`. **Deterministic honor gate in settle.py: the refutation suppresses only if `quoted_text` byte-matches head at the cited lines.** No match ⇒ discarded, finding survives. Zero model calls at check time — satisfies the ADR-0012 discipline the same way `read_budget_gate.py` does. The LLM navigates ambiguity; the suppression is a byte comparison a third party re-derives with grep.

**Testable for intent.** `test_settle.py` is 18 pure tests with `lambda p: FILE` as the entire mock. Citation-integrity tests (fabricated quote ⇒ no suppression; off-by-one range ⇒ no suppression) fail the moment someone loosens the gate. **And the regression corpus already exists:** the 58 `real` rows in `findings-log.jsonl` — "the verifier suppresses zero of the 58."

**Order.** **P0 (days, no code): turn capture on** — `DOUG_EXAMPLE_PACK_CAPTURE=1`. Zero packs on disk is the hard blocker; decide `application_revision` pinning *before* the first pack. P1 = cited-refutation verify, hard cap **≤2 verifies/PR**. P2 = same call, tools unlocked, off the live path, `SENTINEL_SCOPE`. **Cut from v1: Part 3 entirely.**

**Most likely to blow up: spend and threadpool, together.** `api.py:2630` schedules `worker.drain`; `drain(max_jobs=20)` runs 20 jobs sequentially in one Starlette threadpool worker, sharing the ~40-worker pool with `/healthz`. Today 20 × 2 reads × 120s. Add 2 verifies → 20 × 4 × 120s plus capture writes. Mandatory in P1: own scope `verify:<id>`, third branch in `cap_for`, shorter timeout.

**Corrections.** A third `attempt_kind` **raises** at 5 sites in 4 files, not just a Literal. And `tier='external'` **is** already a working quarantine (unique index excludes it; 6 aggregation sites filter it) — the brief was right that `source` isn't one, wrong that none exists.

**Red-lines.** No LLM output suppresses directly. Every suppression writes a ledger row with the verbatim citation. Verify spend off the customer meter. Nothing agentic writes `verdicts`. No capture cohort before the `application_revision` question is answered. **P1 doesn't ship without the 58-real-rows regression green.** Part 3 not in this design — "a second product smuggled into a plan so the first looks bigger."

**Tensions forced.** The cut is 2 verify calls/PR and going bigger is a **repricing**, not a config knob. Latency is a first-class cost nobody has priced. Convergence Bar 1 already failed on **reader nondeterminism** — a verify pass adds a second nondeterministic call that *removes* published findings; **the citation gate is what makes it survivable**, and without it P1 makes the failed bar strictly worse and should not be built at all.

---

## PM

**The measurement that decides it.** 123 prospective rows, `verdict` × `changed`: real 26/31, **adjacent 10/19**, disproved 3/34. **39 findings changed code; 13 were not true as stated.** `REVIEWING.md:272` already says `adjacent` is "the valuable one and the easiest to throw away." On PR #106 Doug's two dispositioned-wrong findings sat on the exact two sites the external review found real bugs.

**The user-facing change.** Every finding carries a **disposition**: **Held** (refutation ran and failed — the check is named), **Refuted** (raised then disproved — *shown, not hidden*), **Narrowed** (first claim didn't hold; here's the one that did). **Narrowed is the product** — the LLM noticing something is off, plus the verifier saying precisely what. Not new machinery: `settle.py:192-206` + `check_run.py:66-71` already ship "a suppressed finding leaves a receipt."

**v1** = the disposition surface + expanded refuters + finding `file` persistence fix. **Only deterministic refuters may produce Refuted** (deletion is irreversible, needs a third-party-rerunnable check). A model may produce **Narrowed** text under a separate frozen prompt. **vNext** = cross-file refuters, per-source table shipped **empty and dated**. **Not on the user roadmap at all: the agentic reader** — day-one user value zero.

**One story, three trains, one departure time:** *Doug grades review claims, including its own.*

**Shippable copy.** "Doug raised 7 findings and refuted 3 of its own. The 4 below survived a refutation attempt. Surviving a refutation attempt is not proof — it means Doug tried and failed." / "Every finding Doug publishes has had a refutation attempt run against it, and the check that ran is named. Refuted findings are shown, not deleted. Doug cannot verify a finding; it can only fail to kill one."

**Refuses to claim:** "fewer false positives" or any FP rate; **"verified"/"confirmed"/"validated"** or a green check on a finding; "Doug learns which findings are wrong"; any comparison to another reviewer's FP rate; any `findings-log.jsonl` number as a rate.

**Red-lines.** No finding disappears without a line. **No refuter may delete an adjacent** (10/29 changed code) — if Narrowed can't ship in v1, adjacents stay **Held** and we ship two states. No per-finding confidence number. Agentic reader gets no customer surface until a pre-registered bar clears on unspent holdout. **The word "coverage" does not transfer** — an agent's tool log is a self-report; ship "Doug opened 6 files and 2 definitions; it chose them. There is no denominator here" or it doesn't surface. "Keep Bugbot. Doug grades it." doesn't ship before the table has rows. Per-source comparison ships with its confound inside it.

**Tensions forced.** Better verification makes the check run **longer**, not shorter — and the first person to tune for a quiet surface kills the adjacents first. The refutation **rate is not a quality metric**: it rises when the reader gets worse *and* when the refuters get better, and we can't separate them. **T6:** `web/app/page.tsx:248-259` renders "0.69 / 0.67" under "What's actually measured" — every visitor reads it as Doug's number. Before any new-reader work is announced, that panel gets the correction sentence, or we don't get to talk about a third reader's quality at all.

---

## LIVE TENSIONS FOR ROUND 1 (Chief's list)

- **T-A — How is the LLM's judgment honored?** PE's **citation gate** (model *can* cause deletion when its quote byte-matches head) vs Architect+PM's **never-delete** (model → annotate/Narrow only; only deterministic refuters delete). Same convergence, incompatible mechanisms.
- **T-B — Is the headline problem precision or recall?** Architect T2: #106's two best bugs were misses found by *rendering the output*; a precision build justified by a recall failure ships the wrong thing. PM: the 13-of-39 number makes labeling, not filtering, the v1.
- **T-C — Scope and v1.** Architect A→C→B; PE two designs, cut Part 3 entirely; PM one story, Part 3 vNext empty-and-dated, Part 2 off the roadmap.
- **T-D — Does capture-on gate P1, or only P2?** PE says both. P1's regression corpus is `findings-log.jsonl`, not packs — Chief to resolve.
- **T-E — The zero-call gate over the tool-call log.** Architect T5(b) and PE's citation gate are the same mechanism at two scopes. Make it explicit or lose it.
