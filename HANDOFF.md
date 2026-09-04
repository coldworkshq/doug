# HANDOFF — doug

State:    review — PR open off main 6b16591, branch
          `adr-0033-renumber-the-vertex-reversal`. api 1846 pass, ruff clean.
          #293 MERGED as 6b16591 carrying a DUPLICATE ADR number.
Next:     Andrew reviews the renumbering PR, then rules on #294 — the dense
          arm's `proposed` ADR-0032 goes to signature on three premises the
          Vertex reversal changed. Langfuse tracing is still off in
          production (#289).
Blockers: none for code. FOUNDER: #294 (amend a proposed record — R11), #289
          (Langfuse subprocessor listing and DPA).

Decisions this session (2026-09-04):
- The Vertex reversal is renumbered ADR-0032 -> ADR-0033. Two ADR-0032 files
  reached main on the same day: the dense arm's embedder (#285, merged as
  88cbddf) and the Vertex reversal (#293, merged as 6b16591). I raced R5's
  serialized ADR sequence by branching off 1d205b9 and never re-checking the
  number before opening the PR.
- `test_no_two_decision_records_claim_the_same_number` now derives uniqueness
  from the filenames. Nothing was checking, which is why the collision merged
  and was then found by eye. Mutation-checked by recreating the duplicate.
- ADR-0033 gained "What this does to the dense arm's record". Three premises
  in the `proposed` ADR-0032 are now false: ADR-0029 never actually moved the
  reader to Vertex, "one cloud relationship" is now two, and the Vertex
  preflight it inherits is gated on `READER_TRANSPORT = vertex` and no longer
  fires. The third has a code consequence — the embedder would ship with no
  model-access check. Filed as #294; amending a record awaiting signature is
  R11, not an agent's call.

NEAR MISS worth keeping: a hand-run `gcp.sh deploy` from the langfuse worktree
was attempted while that tree was 3 commits behind main. `deploy` runs
`gcloud run deploy --source .`, so it would have shipped a tree missing
4ae5b25 — the fix for the callback path that took sign-in down (#286) —
reverting it in production. It failed instead, on the pre-ADR-0033
`VERTEX_REGION` refusal. Nothing checks the deploying tree against main.

Pointers: docs/decisions/ADR-0033 · ADR-0028/0029/0030 banners ·
          api/tests/test_intent.py `test_no_two_decision_records...` ·
          api/deploy/gcp.sh · .github/workflows/deploy.yml ·
          docs/OPERATIONS.md · #294 · #291 · #289

--- prior stream (#290 Langfuse tracing, MERGED as 6af8d60) below, preserved ---


State:    review — PR #290 OPEN, branch
          `claude/doug-langfuse-integration-0dd80f`, merged up to main
          1d205b9 (#287). Langfuse tracing for the four paid model calls.
          api 1836 pass, ruff clean, five mutation checks red. Traced a real read
          through the real Langfuse SDK with an in-memory OTel exporter:
          `reader.risk` nests under `review coldworkshq/doug#284`, carrying
          model, effort, usage, stop_reason, scope and session.
Next:     Andrew reviews the PR. Tracing is OFF in production and stays off:
          creating `doug-langfuse-public-key` and `doug-langfuse-secret-key`
          is what turns it on, and that is founder-only (#289).
Blockers: none for code. FOUNDER (#289): Langfuse becomes a subprocessor
          holding tenant source code. Needs naming in the privacy surface, a
          DPA, and rulings on residency and retention before the secrets exist.

Decisions this session (2026-09-03):
- Seam is the request dict, not the client. `tracing.create(client, request,
  kind=, scope=, pr=)` replaces `client.messages.create(**request)` at all
  four sites and forwards `request` untouched, reading model/system/messages
  out of that same dict — so tracing cannot become the path by which the
  ADR-0002/0012 freeze moves, and a pass that changes its model cannot forget
  to update its tracing. Two tests pin it, including one asserting the SDK
  kwargs are identical with tracing on and off.
  Rejected: wrapping `_build_client` (a proxy sees the exception but not
  stop_reason, the parsed output or the spend cap, and every reader test
  injects `client=` so it would never run under test); emitting from
  `_record_attempt` (gated on example-pack capture, hardcodes MODEL, carries
  no scope).
- Existence of the two secrets IS the switch — no separate TRACING variable.
  A flag and a credential that can disagree gives two quiet half-configured
  states. `langfuse_configured` in gcp.sh requires both; the fake gcloud in
  test_deploy_gcp.py now defaults them ABSENT, so the two exact-allowlist pins
  kept their lists unchanged and the on-state is pinned separately.
- Trace root is the review job (drain wraps process_job), session is the head
  SHA so a second push is a second session. Flush once per drain.
- Measured: flush against an unreachable Langfuse costs ~4s for one span and
  ~10s for a job's worth, bounded by the OTel exporter's retry budget, NOT by
  the client `timeout` (2 and 5 gave the same figure). Reads themselves are
  untouched — three traced reads took 0.2s. That measurement is why flush is
  per drain and absent from the synchronous read route.
- Langfuse Cloud US host, full prompt and response payloads. Andrew's call,
  asked and answered this session. What leaves the boundary is stated plainly
  in ADR-0031, the tracing.py docstring, OPERATIONS.md and .env.example.
- Fail-soft is absolute and every guard has a test that goes red without it.
  A tracing fault would otherwise read as "the reader is down" on every PR,
  which is the misdiagnosis the Vertex transport already cost once.

Pointers: api/doug/tracing.py · api/doug/reader.py:760,1481,1657,1894 ·
          api/doug/worker.py `drain` · api/tests/test_tracing.py ·
          api/tests/test_deploy_gcp.py `langfuse_configured` pins ·
          api/deploy/gcp.sh · .github/workflows/deploy.yml LANGFUSE_HOST ·
          ADR-0031 · docs/OPERATIONS.md "Langfuse tracing" · #289

--- prior stream (#287 settle precision + slug fold) below, preserved ---

MERGED as 1d205b9. The text below was written while it was still open and
says so; it is kept for its decisions, not its state.

State:    review — #284 MERGED (c99fae2) one commit short of its tip; the
          dropped commit (pyproject pin) is re-landed on #287. #287 OPEN,
          branch `accuracy-settle-names-and-slug-fold`: settle.py
          claimed_names precision, patterns slug fold (#244), PR-title
          verbs in the intent stop list, ADR-0026 facts note. api 1818
          pass, ruff clean, every guard mutation-red. Doug's four reads of
          #287 dispositioned (18 rows, 8 changed code); each round's medium
          on settle.py was right and the extractor now lets the file at
          head resolve an ambiguous prose name. Round four was repeats plus
          three lows, so the review has converged; stop pushing.
Next:     Andrew merges #287 and CHECKS main carries its tip (three squash
          merges have now dropped the last commit: #251, #284, and the
          #257 recovery). Then runs the #244 production query (on #244).
Blockers: FOUNDER (#274): Vertex capacity is gated on a Google account
          team; transport stays `anthropic` until the probe answers 400.
          DENIED this session: reading doug-database-url for the #244
          measurement. Handed over as a query, not routed around; the
          check-run corpus (672 distinct slugs, 0 dirty) says it is empty.

Lanes measured and closed this session, all offline:
- #264 intent leak 20/22 -> 3/23 (naming rule + PR-verb stop words);
  graded deviations lose no cited record (21/21); 60 real PRs still read.
- settle.py missed PR #278's third read on the prose word `being`; fixed,
  then Doug caught my over-broad dotted-root claim and that is fixed too.
- #244 slug fold; 0 of 672 emitted slugs dirty, so no regrouping.
Disproved reader rows are diverse (59 rules / 74 rows); no further
deterministic settlement class is measurable yet. #245, #207 remain.

Decisions this session (2026-09-02):
- #264 mechanism: `intent._bears_on` — a record is a candidate only if the
  change NAMES it in the record's title (a PR-title word or a changed file's
  name), and one shared word is a coincidence unless it is the file's own
  name. Path tokens are file stems only (no directories, no extensions).
  Plural/past-tense folded (`_normalise`: -s at >=4, -ed at >=5; no stemmer).
  MIN_RELEVANCE / RELATIVE_FLOOR untouched — nothing was retuned.
  Measured on 28 accepted records: cosmetic leak 20/22 -> 5/23 (residual
  named in the sampled test); every realistic positive intact; 60 real PRs
  still 58/60 read, set sizes now 1-3 instead of 3-6.
  Rejected: corpus-derived stop list (drops `reader`, kills the freeze
  record); prefix matching (`mode` ~ `model`, lema pin breaks); retuning the
  ratio floor (cannot separate two incidental words from two naming words).
- lema pin relaxed from "ADR-0006 first" to "top two == {0006, 0022}":
  ADR-0022 fills the provider slot 0006 left empty and postdates the pin;
  with `providers`->`provider` its title names the changed file. Both bind.
- pyproject pin flipped: ruff bump on api/pyproject.toml -> [] (its old
  rationale was a body match, i.e. the noise); a change naming
  anthropic[vertex] reaches ADR-0027/0028. Both halves pinned.
- Vertex: `vertex_host` in gcp.sh mirrors the SDK table (us/eu -> rep hosts,
  global -> bare host, else regional). deploy.yml stages VERTEX_REGION=us.
  Workflow test now pins region in {us, global}. SDK host table pinned in
  test_reader. OPERATIONS.md section rewritten for lineage quota;
  ADR-0029 got a dated facts note (decision unchanged, no new ADR).
  Probed 2026-09-02: `us` and `global` resolve, 429 on lineage quota.

Pointers: api/doug/intent.py `_bears_on` `_file_names` `_normalise` ·
          api/tests/test_intent.py (sampled negatives test) ·
          api/deploy/gcp.sh `vertex_host` · .github/workflows/deploy.yml ·
          api/tests/test_deploy_gcp.py `test_the_preflight_probes_the_host…` ·
          api/tests/test_reader.py `test_the_installed_sdk_addresses…` ·
          docs/OPERATIONS.md · ADR-0029 item 5 note · #264 · #274

--- prior stream (#273 Vertex transport, merged) below, preserved ---

State:    review — PR #273, branch `adr-0029-vertex-transport`, api 1773 pass,
          ruff clean. Transport is Vertex, DEFAULT_TRANSPORT="vertex". NOT
          DEPLOYED, and the deploy now REFUSES until quota exists.
Next:     Andrew requests Vertex quota (below), then VERTEX_REGION=us-central1
          and merge #273. Also rules on #268.
Blockers: FOUNDER — Vertex throughput quota is ZERO in every serving region.
          The deploy cannot succeed until it is granted. Tracked in #274.

THE REGION QUESTION IS ANSWERED, by probe, not by guess (2026-08-28):
- Model Garden enablement is DONE. `claude-opus-5` resolves in exactly THREE of
  13 regions: us-east5, us-central1, europe-west4. `global` 404s — it is NOT
  available, so any earlier suggestion to use the global endpoint is dead.
- USE us-central1. The api service already runs there, so the call stays
  in-region inside a request already bounded at 240s. europe-west4 would move
  tenant source code to the EU for no reason; us-east5 adds a hop for none.
- ALL THREE return 429: "Quota exceeded for
  online_prediction_input_tokens_per_minute_per_base_model with base model
  anthropic-claude-opus-5". The probe sends an EMPTY BODY and consumes no input
  tokens — a quota rejection therefore means the allocation is ZERO, not that
  the endpoint is busy. Access and throughput are separate grants and this
  project has only the first.
- Request quota for BOTH anthropic-claude-opus-5 AND anthropic-claude-sonnet-5
  in us-central1: the mechanical tier rides the same transport and quota is per
  base model. https://console.cloud.google.com/iam-admin/quotas?project=doug-prod0
- Re-probe after: a 400 instead of a 429 means quota landed. 400 is the healthy
  answer — the empty body is rejected on validation, having generated nothing.

THE DEPLOY PREFLIGHT (`vertex_preflight` in gcp.sh), added this round:
A set region is not a working one, and there are now TWO PROVEN ways the
transport can be live and unusable while the deploy looks green: a region that
does not serve the model (10 of 13), and access without quota (all 3). Both end
in the same place — every read falls soft into the deterministic score, the
check run still renders, and the deep read is silently gone. The preflight
probes EACH model (ids read from reader.py, so they cannot drift) in the
configured region and refuses on 404 / 401 / 403 / 429 with a distinct message
each. 400 passes: the route resolved and nothing was generated.
It does NOT check the runtime identity — it runs as the operator, not
doug-api-sa. That half is the roles/aiplatform.user binding in `setup`, and
ADR-0029 names the gap rather than papering over it.

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
DOUG'S REVIEW OF #273 — risk 0.62, 1 high / 3 medium / 2 low + 5 deviations.
All nine dispositioned in docs/findings-log.jsonl. Four changed the code:
- unsafe-default-flip (medium, REAL): DEFAULT_TRANSPORT was vertex, conflating
  "where the deploy goes" with "what unconfigured environments get". A laptop,
  script or CI job has no region and no ADC, so the client raises and every
  read falls soft — silently. NOW DEFAULT_TRANSPORT=anthropic and the DEPLOY
  pins vertex. ADR-0028 item 6's rollback property is unaffected.
- deploy-blocking-precondition (medium, REAL): quota is zero, so an
  unconditional preflight made every unrelated hotfix hostage to a founder
  grant. R1 conflict. NOW `READER_TRANSPORT=anthropic ./deploy/gcp.sh deploy`
  ships the current transport and never touches Vertex.
- incomplete-error-handling (low, REAL): the preflight was a denylist, so 5xx
  and empty output passed the gate it exists to provide. NOW an allowlist —
  only 200 and 400.
- missing-from-pr (deviation, REAL, THE BEST FINDING): ADR-0012's banner still
  said "No traffic has moved" and named the deleted guard test as the
  enforcement. Both false after this diff. ADR-0012 now carries
  amended_by: ADR-0029 and a corrected banner; ADR-0027 got the same for the
  mechanical tier's transport.
- metric-label-change (medium, DISPROVED): checked every `provider` across
  api/doug, web/ and console/ — only the manifest field and the reader setting
  it. Every other hit is the IDENTITY provider. Recorded in ADR-0029.
- unverified-external-api-contract (HIGH, REAL, NOT FIXED): #275, with the part
  Doug missed — vertex_preflight CANNOT catch it. The probe posts an empty body
  and pins 400 as healthy, and an unsupported output_config is ALSO a 400. The
  gate is structurally blind to this exact failure. Fix is a second well-formed
  probe where 200 is healthy; that is a paid call per deploy, so FOUNDER.

SIDE FINDING — #264 is worse than its title. Adding ADR-0029 failed
test_selection_on_dougs_own_records, and measuring showed why: across all 27
accepted records "Correct a spelling mistake" selects 2, "Update the copyright
year" selects 2, "Rename a css class" selects 3. Mechanism: hits_body counts a
token appearing ANYWHERE in a record body, path segments (web/app/api/
components) are in the change vocabulary, and 2 hits over a 6-token denominator
is 0.333 against MIN_RELEVANCE 0.25. The one surviving negative case passes
only because bump/ruff/makefile/gitignore appear in no record — lucky
vocabulary, not a working floor. PINNED as the defect rather than relocated a
second time, so fixing #264 fails that line and forces it back to []. Evidence
posted to #264. NOT fixed here: a scoring change to an unvalidated tier does
not belong in a transport migration.

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
