# Ground truth brief — competitor-imports lane

**Date:** 2026-08-17 · **Method:** design-debate Phase 1, four independent grounding agents · **Status:** brief only — the concept it was written against did not survive it · **Baseline:** worktree @ `b8e3659`

Everything below is `file:line`-verified. Phases 2–5 ride on this document.

---

## 1. The three parts as briefed, against what the code says

### Part 1 — code-semantic feature into `features.py` → `scoring.py`

**Aimed at a tier that is, by ruling, not the product.**

- `score()` is reached on the live path only at `review.py:381` (spend capped), `:385` (reader error), `:390` (reader disabled). Otherwise `verdict_from_reader(rv)` (`review.py:366`) sets score and band and the deterministic score is **discarded, not blended** (`reader.py:955-973`).
- No admission gate consults it — `api.py:2257-2289` gates deep reads on draft / fork / bot author only.
- `ADR-0004:31-34` and `design-lock.md:78`: deterministic ranking "is not the product (near-random on repo #2); it is the loud, labeled fallback."
- Therefore a feature here changes the fallback verdict's score and **nothing else**. Making it route deep reads reopens ADR-0004, which explicitly rejected the cost wedge.

**Three further blockers, any one of which is fatal to the naive form:**

- **Eviction arithmetic.** The hotspot band is 581/2500 ≈ 23% of PRs, which *is* the 20% flag budget, at 2.34× lift (`workspace/research/backtest-phase0-notes.md:157-165`). A new rule must fire **outside** hotspot ∪ sensitive at **>2.34× lift** or it is a strictly losing swap. This mechanism killed the v4 shape rules twice (`scoring.py:124-133`).
- **Portability.** `screen_features.py:10-12` — `hotspot_path` and `config_flag` fire **0/12,000 times on grafana**. Code-semantic rules carry language-specific vocabulary and are *more* repo-shaped than path rules, not less. sentry is Python; grafana is TS/Go.
- **Prior.** `ADR-0004:14-20` — shape rules, rolling hotspots, and RF on Kamei's 14 all hit ~0.54-0.61 on sentry and ≤random on grafana. A code-semantic deterministic feature is the **fifth** structural-feature family and inherits that prior.

**What is actually replayable** (the brief's premise was half-wrong in both directions):

- `harvest.py:1-7`'s "no cloning, no diffs" docstring is **stale**. Patches *are* persisted (`harvest.py:71-79, 120, 271`). Measured: sentry-10000 → 75,567 file rows, 2.7% `patch: null`; grafana-12000 → 110,320 rows, 3.7% null. `.backtest-cache/` is gitignored, generated, ~640 MB, this machine only.
- The 653 is a **ledger sample**, not a harvest file: `llm-probe/sample.json` (366) + `llm-probe-grafana/sample.json` (287), seed 0, `diff_budget: 30000`, pre-filtered to PRs that have patch text.
- **Base-commit trees are absent.** The clones are `partialclonefilter=tree:0` promisor clones; blobs fail `cat-file` under `GIT_NO_LAZY_FETCH=1`, root trees are `TREE-MISSING` beyond ~1k commits, and `HarvestedPR` carries no SHA field at all.
- **The boundary:** hunk-local lexical/structural analysis of changed lines (±3 context) is free and replayable today across ~6 repos and ~150k file-diffs. Anything that must resolve a symbol to its definition, or see an unchanged line >3 lines away, is new harvest machinery at monorepo network scale.

**Wire constraints.** `Features` is serialized nowhere and pinned by no test — adding a field is free. `PRMetadata` is the opposite: `web/lib/session-api.ts:170-178` validates it with **exact key-set equality**, so a 17th field is a rejected run-detail payload. `models.py:3-6` states the rule directly: "If a field would require cloning or parsing the repo, it does not belong here yet." Feeding patch text to `score()` means changing `replay.py:56` — the exact line `design-lock.md:75` names.

**The holdout, not money, is the scarce resource.** sentry newer-2500 is already twice-spent (`backtest-phase0-notes.md:8`). Ship bar is pre-committed: @20% ≥ 36.2% AND @30% ≥ 57.0% AND AUC ≥ 0.6401. Three eligibility gates precede any holdout spend. Unspent surface: airflow-2000, prometheus-2000, backstage-2000, otel-collector-2000 under `pc1-replication-preregistration.md`.

### Part 2 — agentic reader as a new instrument era

**Adopted in principle as A2; two things break the naive implementation, and they compound.**

- **The ledger physically cannot hold a second verdict for one PR@sha, and fails *silently*.** `uq_verdicts_app_identity` (`migrations.py:186-188`) is UNIQUE on `(installation_id, github_repo_id, pr_number, head_sha)`. `save_review` catches the `IntegrityError` and returns the peer's id with `created=[False]` (`store.py:874-885`); `worker.process_job` reads that as a lost race and **replays the champion's check run** (`worker.py:286-301`). A challenger write doesn't error — it vanishes and triggers a bogus replay.
- **`verdicts.source` is not a quarantine.** It is used as a predicate in exactly one place (`store.py:951`). `pattern_join` (`store.py:2161-2200`), which feeds `precision.corpus_table` and `/v1/patterns`, selects `max(verdicts.id) GROUP BY (repo, pr_number)` filtered **only** on `tier != external` — a challenger row with a higher id becomes "the latest verdict" and its findings enter **published** per-pattern precision. A2:24's "quarantine label" describes an intention with no implementation.

**But the correct lane already exists and is already right.** `instrument_id` partitioning is end-to-end today: `WholeInstrumentManifestV0` + `instrument_id()` (`example_pack.py:179-201`) → `EvaluationIdentityV0` keyed per (instrument, PR@sha) (`example_pack_hosted.py:74-91`) → `score_packs_by_instrument` (`example_pack_eval.py:208-237`, docstring: *"Partition before scoring so whole-instrument revisions never mix"*) → `CohortDetailV0.instruments`, with null/spam controls. Two arms coexist with **no contract change**. Capture is currently OFF — zero packs on disk.

**Gaps in that lane, all real:** `attempt_kind` is a closed two-value `Literal`; the manifest is `extra="forbid"` with **no orchestration-graph/roles field** (the one A2 component with no home in code); `PACK_LIMIT = 500` per cohort, so two arms halve effective size to 250; `application_revision` is an input to `instrument_id`, so **any redeploy mid-cohort silently splits every partition**; capture is best-effort and silent-failing by contract, with a 5.0s GCS budget.

**Honesty gap.** `reader.coverage` is pure over a pre-computed input string, which is exactly why `read_budget_gate.py` verifies ADR-0012's bar at **zero model calls** (`ADR-0012:48-52`). For an agent choosing its own reads the analogue must be *observed* (tool-call log, files opened) — a different epistemic class a third party cannot recompute. That property does not transfer.

**Two measured warnings.** Convergence Bar 1 FAILed with **reader nondeterminism** named as root cause — agentic reading increases it. And spend: `record_deep_read` counts **one unit per call**; `store.instrument_snapshot` renders the same counter as `deep reads N/200` on the **customer's** check-run footer and the public scoreboard, so a challenger charging `installation:<id>` visibly eats the customer's advertised allowance.

**The reframe grounding hands us:** `addendum:36` requires G1's panel to beat a **"compute-matched grounded single reader."** An agentic, cross-file, tool-calling *single* reader **is** that comparator. Part 2 is a prerequisite of G1's gate, not a competitor to it.

### Part 3 — recall signal from human review comments

**Blocked at the unit of analysis, and the data source isn't subscribed.**

- **Finding-level recall is forbidden by name, three times.** `example-pack-v0-design.md:281`: "They are not precision or recall… Git outcomes remain separate PR-level associations and **never adjudicate an individual finding**." `addendum:26,36`: "Findings are **nested evidence within a PR, never independent sample units**." `REVIEWING.md:286-289`: "Never report a rate from this log as precision."
- **The source isn't ingested.** The webhook subscribes to four event/action pairs (`api.py:2575-2583`). `issue_comment` and `pull_request_review_comment` appear nowhere in the repo. `commented` reviews — "by far the most common review state on GitHub" (`api.py:2399-2402`) — are explicitly dropped as stance-less. A reviewer writing "this leaks a token" produces **zero rows today**.
- **There is nowhere to put it.** `findings` is `verdict_id`-anchored (a miss has no verdict row). `outcomes.kind` is a closed enum whose `N_done = misses + clean + censored` identity is structurally enforced (`adjudicate.py:19-25`, `outcome_queue.py:259-260`). `findings-log.jsonl`'s three verdicts all presuppose Doug **emitted** something; all 135 rows are `layer=doug`.
- **Contamination cuts both ways and has no censoring analogue.** Flagging causes scrutiny (inflates apparent misses where Doug engaged); a clean check run suppresses scrutiny (deflates the cleared band — the population §2.1 publishes on). The revert detector is immune to the second; this is not. And you cannot compute a censoring rate for defects nobody happened to mention.
- **Label noise is ~34%** — this repo's own measured `disproved` rate is 46/135. An unadjudicated comment is a third noise; an adjudicated one is a recurring human hand-audit.
- **It is the incumbents' metric.** `product-spec.md:23`: "Greptile's benchmark is **recall-only** and self-run." `unbeatable-doug-research.md:45`: "Opposite of a miss rate on a population you declined to inspect."
- **And there is no data.** `drewjst/doug` is solo (`ADR-0008:51`); it produces no human review comments naming missed bugs.

**What is already chartered instead:** `design-lock.md:60` — third-party verdicts via `pull_request_review` are **built**, and "Doug becomes the neutral grader, which is the uncontested lane"; comment-format parsing for named bots is **deferred with a trigger** (a design partner asks). `unbeatable-doug-research.md:133-139` specs "Approach B": bot-comment ingest, **per-source cleared-band table**, sales sentence *"Keep Bugbot. Doug grades it."* — PR-level, not finding-level.

---

## 2. Do-not-reopen (binding on every phase)

1. Never writes code, never opens a PR, never blocks; conclusion is always `neutral` (`ADR-0010:33-46`).
2. Nothing outcome-derived enters `score()` unless `replay.py:56` can replay it; any garden→review candidate clears a pre-registered margin on **temporal and repository** holdouts (`design-lock.md:75`).
3. `SYSTEM`/`SCHEMA`/`MODEL`/`EFFORT`/`MAX_TOKENS` frozen; a new input policy needs a **separate** frozen prompt (`ADR-0012:36-40`, `ADR-0002:40-41`).
4. Any new governing metric must be checkable at zero model calls, like `read_budget_gate.py` (`ADR-0012:41-52`).
5. New unvalidated signals get their own stream and never move the score — the ADR-0007 precedent.
6. No precision figure without ADR-0005's two tables; the caveat travels **inside** the payload.
7. No instrument inherits AUC 0.687/0.668; the shipped reader has no measured AUC to be a baseline (`ADR-0012:98-100`).
8. Agents on every PR: killed. Agent Engine for the live path: rejected (`addendum:41-43`).

## 3. Approved-not-built we must not re-design

- **A2 champion–challenger** is a chartered track with a trigger (`ROADMAP.md:489`). Part 2 is *firing it early*, not a new concept.
- **Whole-instrument identity is BUILT** (`example_pack.py:179-201`). Do not invent a second scheme.
- **The paired-evaluation harness is BUILT** (`example_pack_eval.py:218-229`, `EXAMPLE_PACK.md:190-197`). Capture is off; zero packs on disk.
- **Approach B** (bot-comment ingest → per-source cleared-band grading) is specced (`unbeatable-doug-research.md:133-139`).
- **`settle.py` expansion is the named highest-ROI finding-quality work without model spend** (`unbeatable-doug-research.md:111`) — and it is *already* the deterministic, code-semantic, outside-the-diff verifier lane (`review.py:273-298` `head_file_text`, `store.columns_of`), with the boundary stated: it reads outside the diff to **disprove**, never to ground a finding.
- MT3 is the main-lane critical path; next free migration is **11**.

## 4. House formats

- **ADR** — `docs/decisions/README.md:13-38`; frontmatter `title/status/date[/supersedes/superseded_by]`; sections Context / Decision / **Rejected** (not optional) / Consequences. Next number **ADR-0013**.
- **Design doc** — H1, bold metadata line, `---`, numbered `## N.` sections.
- **Spec** — `docs/superpowers/specs/YYYY-MM-DD-<slug>-design.md`; Date / Status / Roadmap item / Blocks; decisions labelled `D1–Dn`; evidence `file:line` against a named baseline SHA.
- **Plan** — `docs/superpowers/plans/YYYY-MM-DD-<slug>.md`; H1 `<Name> Implementation Plan`; the agentic-worker blockquote; Goal / Architecture / Tech Stack / Spec / Worktree; `## Global Constraints`; `### Task N:` with `**Files:**`.
