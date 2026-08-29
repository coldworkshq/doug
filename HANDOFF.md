# HANDOFF — doug

State:    review — ADR-0029 branch `adr-0028-paired-run`, api 1764 pass, ruff
          clean. The reader's transport is Vertex, DEFAULT_TRANSPORT="vertex".
          NOT DEPLOYED. The deploy needs VERTEX_REGION and will refuse without it.
Next:     Andrew (1) confirms the Vertex region that serves claude-opus-5 — the
          deploy refuses without VERTEX_REGION and no default is supplied on
          purpose; (2) reviews and merges the PR; (3) rules on #268.
Blockers: the region value is founder-only (R11 spend/seam). Everything else is
          landed and green.

## What this is, and what it costs

Andrew: the Anthropic console balance is running out, everything has to leave
it. Directed the Vertex move REGARDLESS of ADR-0028's bar. That bar was never
run and now never will be in its declared form. ADR-0029 records the direction,
the reason, and that the new instrument era ships governed by nothing. ADR-0018
is the precedent for the shape; ADR-0028 warned that doing it twice makes the
exception the practice, and this is the second time.

Production's whole console spend is four calls behind two clients. `settle.py`
makes NO model call (pure AST) — verified, so there is no fifth. Both clients
move, so nothing is left billing Anthropic.

## Decisions this session

- RULING (Andrew): move to Vertex without the paired run. The balance funds the
  study or the cutover, not both. Rejected: run the bar first (the option that
  should have won, lost only on funding); a smaller sample (reopens the ruled
  300 and buys a number that cannot fail); re-declaring a corrected bar in the
  same change that benefits from the answer.
- ADR-0028's scope ambiguity settled: its prose said "risk and intent reads"
  but its facts table and guard test both named `_verify_client`, which serves
  neither. Both clients move. The mechanical tier's TRANSPORT moves; its VENDOR
  does not — ADR-0027's C1/C2/C3 all still bind.
- `provider` is computed, not hardcoded: "anthropic-vertex" vs "anthropic". This
  moves instrument_id and partitions the corpus at the cutover, which is the one
  part of ADR-0028 that survives intact.
- No MODEL mapping layer, pinned by test. Vertex serves current-generation
  models under the bare first-party id. A dated snapshot would break that and
  reopens ADR-0028 rather than earning a mapping.
- ANTHROPIC_API_KEY STAYS MOUNTED. It is the rollback
  (`DOUG_READER_TRANSPORT=anthropic` on the running service, no deploy). It has
  a clock: when the balance hits zero the rollback stops existing.
- Region deliberately NOT defaulted. A wrong region fails every read soft into
  the deterministic fallback, which reads as "the reader is down". The deploy
  refuses instead.
- Reopened #263 — it closed as COMPLETED by ACCIDENT, on the phrase "close #263
  first" in 837ce57's body. That PR changed ADR text only; the manifest still
  has no mechanical field, so ADR-0027 C3 is undischarged.

## #268 — ADR-0028's bar was also not runnable, and this is FOUNDER work

- The baseline does not reproduce. The record names `rate --repo doug
  --rule-prefix reader:` and reports n=153 at 44.4/32.0/23.5. That command on
  837ce57 itself returns n=201 at 49.3/30.8/19.9. All 8 scoping combinations
  and every date cutoff checked; 68 `real` never occurs. The thresholds are
  DERIVED from that table, so the declared 39.4% floor is 9.9 pp below the true
  baseline — the 10 pp option ADR-0028 enumerates and rejects.
- The corpus cannot produce the quantity. Dispositions live only in
  docs/findings-log.jsonl, are hand-settled, and cover 34 doug PRs. The 653 is
  llm-probe/sample.json (sentry 136+230) + llm-probe-grafana/sample.json
  (grafana 57+230): PR NUMBERS and a binary defect/clean label. No findings, no
  adjudicator. ~3,500 hand dispositions would be needed against a total of 201.

## Verified

- 1764 api tests pass, ruff clean. Five new reader tests, four new deploy tests.
- Mutation-checked red: provider literal restored -> capture test fails;
  DEFAULT_TRANSPORT flipped -> default test fails; env vars dropped, aiplatform
  removed, IAM role changed -> deploy tests fail.
- AnthropicVertex verified in the installed SDK 0.120.2: region REQUIRED,
  project_id from ADC, max_retries defaults to 2 so it is still passed.
- UNVERIFIED, and it needs a live call: that Vertex accepts the `output_config`
  block (effort + json_schema) these requests send. ADR-0028 asserts effort is
  GA there; the structured-output shape was not confirmed against the wire.

Pointers: branch adr-0028-paired-run · ADR-0029 + ADR-0028 amendment banner ·
          api/doug/reader.py `_build_client` / `transport` / `provider_name` ·
          api/deploy/gcp.sh (region guard, aiplatform, roles/aiplatform.user) ·
          #268 (FOUNDER, the bar) · #263 (C3, reopened)

--- prior stream (fail-closed mint cap) below, preserved ---

State:    review — fail-closed daily mint cap, tests green
Next:     Andrew merges the fail-closed mint cap PR. Over-cap stays 404;
          count `None` is 503 and does not mint.
Blockers: none

Decisions this session:
- RULING (Andrew): the daily mint cap fails closed. A count of `None` is
  `503` (`no ledger configured`), the same deployment-fault class as a
  missing ledger. Over-cap stays `404`. Rejected: keep fail-open (unbounded
  mint during an outage); 404 on count failure (operators could not tell
  "ledger down" from "you are over the cap").
- Historical specs that named fail-open (`docs/superpowers/specs/2026-08-04-tenant-api-keys-design.md`,
  ROADMAP MT5 closed line) stay as the record of what shipped. The live
  contract is the caller.

Pointers: api/doug/api.py `dispense_token` · api/tests/test_api.py
          `test_dispense_daily_cap_*`

--- prior stream (#257 lineage pairing / transfer repair) below, preserved ---

State:    review — PR #257 OPEN off main (9d56db2, branch
          enforce-lineage-pairing, worktree
          .claude/worktrees/backfill-historical-runs). All 6 checks green,
          MERGEABLE, Doug CLEARED at 0.28. api 1731, ruff clean, web 376,
          console 114. Its parent #251 is MERGED (334c37d) and DEPLOYED
          (doug-api-00175-wad, 04:58:40Z; the adjudicator job shares that
          image digest). The production repair RAN at 05:18Z.
Next:     Andrew merges #257. Then the ONLY thing outstanding is watching
          the 2026-08-29 03:00 UTC drain settle the 15 repaired jobs.
Blockers: none. No deadline left — the fix is deployed, so nothing new is
          being censored.

## What this was

Andrew asked why the dashboard had lost every pre-org-move run. It had —
261 runs / 121 PRs behind an installation filter, nothing deleted. Under
that, the outcome adjudicator had been censoring the dogfood corpus daily
since the 2026-08-26 transfer: `_repository_identity` read
`installations.state='deleted' or installation_repos.state != 'active'` as
permanent blindness, which is exactly what a transfer leaves behind while
the repo stays readable under its successor. Censoring is terminal and
removes a PR from the risk set, so it ran in the flattering direction with
nothing to alert on. 15 PRs lost their 14-day grade (93-107); 165 jobs were
queued to follow through 2026-10-25.

## Repair: APPLIED 2026-08-28 05:18Z — verified

  manifest  ~/doug-transfer-repair-2026-08-28.json  (11 KB — KEEP until the
            drain is confirmed; `--rollback --expect-outcomes 15` undoes it)
  wrongly-censored outcomes remaining   0  (was 15)
  legitimate base_ref censorings        PRs 40, 46 SURVIVED
  14-day jobs for PRs 93-107            15 pending, attempts still 0
  drewjst/doug outcome rows (#256 fork) gone
  total outcomes                        717 (was 732 — exactly 15, nothing else)

The last drain ran 03:02Z, two hours BEFORE the repair, so it has not seen
the requeued jobs. Next drain 2026-08-29 03:00 UTC (scheduler
doug-adjudicator-daily, `0 3 * * *`). Confirm with:

  SELECT kind, count(*) FROM outcomes
  WHERE github_repo_id = 1314318717 AND observed_at >= CURRENT_DATE GROUP BY 1;

Want clean/revert. If `censored` returns, the deployed job is not running
the new code — roll back with the manifest.

## Decisions this session

- RULING (Andrew): fix identity resolution, not migration 18. Rejected:
  flipping installation_id across 261 verdicts + 269 review_jobs + 79
  outcomes + 244 outcome_jobs — a one-off that erases that drewjst ever
  scored those runs. Precedent: #218, #228.
- RULING (Andrew): the pre-App CI-token era stays out (87 runs / 43 PRs,
  PRs 9-53, NULL installation_id AND github_repo_id). Issue #249.
- `receipt` and `_select_governing_verdict` NOT widened: §2.2's publication
  partition keys on installation_id, so widening changes a published
  quantity. Issue #250 — until it lands, restored runs' receipt LINKS 404.
- #251's squash merge (04:54:58Z) landed one commit behind the branch, so
  two hardening commits missed it. That is what #257 recovers. Neither was
  a live defect; the repair behaved identically either way.
- 21 Doug findings dispositioned across four review rounds, all in
  docs/findings-log.jsonl. Three earned issues: #256 (run_history joins
  outcomes on repo NAME, already forked in prod), #258 (make the read-scope
  pairing a TYPE — the same finding recurred four times and the fourth read
  correctly said the pairing is verified by grep, not by types).
- Pushed back once and recorded it: Doug wanted an unparseable manifest
  timestamp to fall back to inserting the raw value. Writing text into a
  timestamp column and calling the ledger restored is worse than stopping.
  The abort stays; what changed is that it now names file, row, column and
  value.

## Issues opened

#249 pre-App runs invisible · #250 receipts/queue installation-pinned ·
#255 should a transfer between UNRELATED accounts carry review history
(tenancy contract decision debt) · #256 name-keyed outcome join ·
#258 ReadScope type. Commented on #218 and #228 (#228's hazard has ALREADY
FIRED — old junction row is `removed`, so historical receipt links 404 now).

Pointers: api/doug/outcome_queue.py `_live_registration` ·
          api/doug/outcome_worker.py `reader_installation_id` ·
          api/doug/store.py `installation_lineage` / `_tenant_ids` ·
          api/doug/api.py `_readable_installations` ·
          api/doug/transfer_repair.py + scripts/repair_transfer_censored.py

--- prior stream (#252 landing facelift) below, preserved ---

State:    review — landing facelift is PR #252 OPEN off origin/main
          (e61fa03), branch landing-facelift, one commit, rebased over #246
          (HANDOFF.md conflict resolved by stacking streams). Verified after
          the rebase: web 376 pass, tsc clean, eslint clean (2 pre-existing
          <img> warnings on /about). Screenshotted at 1280 light+dark and
          390 light, fixture data only — no local API.
Next:     Watch CI on #252, then Andrew merges. Open question for Andrew:
          the cost section names `/code-review` by name — keep or
          generalise.
Blockers: none

Decisions this session:
- 2026-08-27: palette and tokens stay (design-system/dashboard-contract/
  site-bar tests pin them); the facelift is layout, type, structure, copy.
  Bricolage gets its opsz+wdth axes for a condensed hero — rejected: a new
  display face (the console shares the brand tokens).
- The hero object is a facsimile of the neutral check run rendered from the
  live queue + scoreboard (headline, table, Needs-you note, footer lines) —
  rejected: the stat card, which no competitor could not also render.
- Cost claim is structural, no dollar figures: one bounded read per PR and
  a human reads only the flagged fraction — ADR-0004 forbids "no model in
  the hot path"; pricing belongs in the private hq repo.
- Pinned copy stays in app/page.tsx (landing-copy.test.mjs,
  public-surface.test.mjs, auth-entry.integration.test.mjs read it).
Pointers: branch landing-facelift · web/app/page.tsx ·
          web/components/landing/ · web/app/layout.tsx (font axes) ·
          web/app/globals.css (landing utilities, ABOVE the lockstep block)

--- prior stream (#246 deploy gate, merged) below, preserved ---

State:    review — PR #246 OPEN off origin/main (6d907b1, branch
          worktree-restore-auto-deploy, in worktree
          .claude/worktrees/restore-auto-deploy). Restores automated
          deploy-on-merge: ADR-0021's reviewer gate retired, its WIF ref
          pin kept. The `production` GitHub environment is already DELETED
          live (2026-08-28) — that half is done and does not wait on merge.
          Doug's 3 findings + 2 deviations on e72f135 all settled;
          5 rows in docs/findings-log.jsonl. Rebased onto c081aaa (#243)
          to clear a findings-log conflict. All six CI checks green;
          mergeable.
          ALREADY PROVEN LIVE: run 33141122253 deployed c081aaa to
          production in 10m08s with no approval step, vs 17h00m / 8h56m /
          one cancelled at 13h29m under the gate. Both services promoted,
          which also settles auth-config-change empirically.
Next:     Andrew merges #246. Nothing to click afterwards.
Blockers: none

Decisions this session:
- 2026-08-28: retire ADR-0021's reviewer gate, keep its ref pin — the gate
  cancelled #229's deploy outright (run 33042841775, evicted from the
  concurrency group's pending slot one second after the next merge's run
  was created) and held others up to 17h, so main and production disagreed
  for most of two days. Rejected: keeping the environment and deleting only
  the reviewer rule (a settings click could re-gate with no diff), and
  fixing the eviction with a per-SHA concurrency group (closes the silent
  cancellation, leaves the hours of drift, which is the gate working as
  designed).
- 2026-08-28: delete the environment rather than strip it, and pin the
  ABSENCE of `environment:` in test_deploy_jobs_name_no_github_environment
  — the protection rule lives in GitHub settings where no diff shows it, so
  the reviewable artifact has to be the workflow key.
- 2026-08-28: ADR-0025 `amends` ADR-0021, not `supersedes` — the ref pin
  survives and must keep reaching the reader. Markers on both sides, plus
  ADR-0009's banner corrected (it still asserted the gate).
- 2026-08-28: Doug's auth-config-change and missing-config-dependency are
  both DISPROVED, but only after checking live rather than asserting —
  deployer SA's only binding is the principalSet on attribute.repository
  (no principal://.../subject/ member), applied condition is
  repository && refs/heads/main, deploy.yml has zero secrets.* and two
  repo-scoped vars.*. Rejected: leaving ADR-0025's "verified while settling
  #223" citation, which was the thing the finding correctly objected to.
- 2026-08-28: beyond-ticket was the sharpest finding — the ref pin became a
  single point of failure and was defended only in prose. Two of ADR-0021's
  three "must agree" legs now pinned by
  test_setup_cicd_pins_both_the_repository_and_the_ref (mutation-verified
  red). Third leg deferred to #247, NOT landed blind: it needs a gcloud
  call from the deploy job and the deployer SA probably cannot read the
  pool — a 403 would fail healthy deploys, the same trap #225 named.

Watch out:
- Running a mutation test on a file the background /code-review agent is
  also editing will clobber its fix on restore. It happened here with
  deploy.yml; re-check `git status` after any backup-restore cycle.
- api/.venv in THIS worktree is fresh. The one in the main checkout still
  needs `uv sync --reinstall` after the org move.

Pointers: branch worktree-restore-auto-deploy · PR #246 · issues #247 (open,
          WIF drift check) and #225 (closing from #246 as obsolete) ·
          .github/workflows/deploy.yml · api/deploy/setup-cicd.sh ·
          api/tests/test_deploy_gcp.py (both new guards) ·
          docs/decisions/ADR-0025-a-merge-deploys-without-waiting.md ·
          ADR-0021 and ADR-0009 amendment banners ·
          docs/findings-log.jsonl (last 5 rows).
          Prior session's #235/PR #243 work is on branch
          fix-235-findings-log-rule-prefix in the main checkout.
