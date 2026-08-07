# HANDOFF — doug

State:    M3 STARTED. HEAD main is `3fec72a` (#57, doug-console Phase 1).
          M1 CLOSED (#54). M2 closed but for two `[~]`: the bot-author half
          and doug-web's SA ops cutover. MT PROVEN 2026-08-05 (16/16,
          `prove-isolation.sh`, two real installations).
          M3 item 1 (`adjudicate.py`) is BUILT and item 7 (the publication
          pre-registration) is DRAFTED. Both are in review as TWO PRs, split
          because the combined diff is 121k chars against a 100k DIFF_BUDGET
          — one PR could not have been read whole, on the very PR that
          defines what a partial read may claim.
            · `m3-adjudicate` — api/ only, 66k. Closes M3 item 1.
            · `m3-publication-preregistration` — docs only, 55k. M3 item 7
              stays `[ ]`: the document is DRAFT, unlocked, unhashed, and
              its 60-day backfill runbook is unwritten.
          The full development history, with every review round, is on
          `claude/doug-console-next-steps-7oomm4`.
Next:     1) doug-console IS NOW DEPLOYED (2026-08-06, revision
          `doug-console-00001-cz4`, on next 16.2.12). IAM-gated as designed:
          `--no-allow-unauthenticated`, runtime SA `doug-console-sa`, and
          exactly one invoke binding (`user:drew.jst@gmail.com`) — a raw
          fetch of the service URL is 403 and MUST stay that way. Reach it
          with `gcloud run services proxy doug-console --project doug-prod0
          --region us-central1`. `gcp.sh setup` was NOT run and must not be:
          its lines 38-47 rotate the production SQL password unconditionally.
          Only the `console()` block was applied.
          CONSEQUENCE FOR THE DEPENDENCY HOLD (below): its stated release
          condition — "HELD until the console has been deployed on 16.2.12"
          — is now MET. The next → 16.3.0 bump is unblocked whenever Andrew
          wants it.
          CAUTION: console changes do NOT auto-deploy. deploy.yml's
          `changes` job greps only `^api/` and `^web/`; there is no
          `console` branch in that filter, so a merged console PR ships
          nothing until `gcp.sh console` is run by hand (or the filter is
          extended).
          2) PR #63 (console-ux) — runs grouped by PR as an accordion, facet
          pills, column sorting, plus the `SCOREPULL REQUEST` header bug and
          the unrendered `RunSummary.url` from #57's review. CI green on
          f978914; needs a redeploy after merge per the caution above.
          3) Merge the two PRs above. 4) M3 item 2, the Cloud Run Job +
          Scheduler that drains the adjudicator. 5) Migration 006 — it now
          carries THREE columns, not one: `reads.files_dropped`,
          `reads.changed_files`, and `outcomes.merge_commit_sha` (without
          the last, the numerator has no job discriminator and the
          `N_done = misses + clean + censored` identity can be false while
          every stated rule is obeyed). 6) Still open from before: #44's web
          SA cutover; the bot-author ruling; log dispositions with
          `python -m doug.findings_log append`.
Rulings:  2026-08-07, four of five settled — see §11 of the pre-registration
          for each with its reasoning. The window's lower bound adopted at
          TOLERANCE_DAYS = 1 (the only one that changes a published number,
          and it LOWERS it); two-sided decidability; quarterly cadence as a
          FLOOR, with publishing sooner/more often free and only lengthening
          bounded; adjudication `max_attempts = 10`, higher than the review
          path's 3 because an adjudication retry buys a clone, not a model
          read. STILL OPEN: tenant consent posture — whose repos appear in a
          public table. Deliberately not inferred; no recommendation was
          ever put on it.
Blockers: none for code. Everything above in (1) and (4) is operator-only.
Decisions: DEPENDENCY BUMP HELD (Andrew, 2026-08-07). GitHub reports 13
          Dependabot alerts on main (8 high, 5 moderate). The npm half (9:
          web 6, console 3) was triaged and NONE is reachable from a serving
          path — `sharp`/libvips has no reachable input (`next/image` used
          nowhere, no `remotePatterns`, and the only assets are SVGs, which
          Next refuses to optimize by default); `postcss` runs at build over
          CSS we authored; `js-yaml` is web-only and reaches solely via
          `eslint` and `shadcn`, both devDependencies, so it is never in the
          runtime image. The fix is `next 16.2.12 → 16.3.0` across web/ and
          console/, HELD until the console has been deployed on 16.2.12 —
          the version #57 was reviewed, built and image-tested against.
          Bumping first would put the console's first production deploy on
          an untested framework version and make any breakage ambiguous
          between console bug and framework bump. NOT reachable ≠ fixed:
          the day someone adds an `<Image>` or a remote pattern, sharp goes
          live silently. The Python half (~4 alerts) is UNAUDITED — no
          pip-audit in the cloud session, and matching uv.lock against
          advisories by hand would be guesswork. Needs the real Dependabot
          list from the security tab.
          Reader improved via settle/findings-log, not frozen prompt
          (ADR-0002).
Pointers: ROADMAP M3 · REVIEWING.md · `docs/design/outcome-loop/
          publication-preregistration.md` (DRAFT v2, not locked — its hash
          must not enter a receipt until the ⚠ rulings land) · #45
          follow-ups (typing.TYPE_CHECKING / function-local import
          over-drop) unfixed if we care.

---

State (historical, still useful below): M0 CLOSED. TASK 10 IS DONE: the App
          path is LIVE and verified in production on drewjst/doug (neutral
          check run, "Cleared · risk 0.02 · diff read", on PR #33 — tier in
          the title, so it was a real read and not a deterministic fallback).
          M1 code is complete except TASK 9, which is now the last M1 task.
          ONE PR PER TASK (Andrew's call, 2026-08-01: more Doug verdicts +
          smaller diffs Doug can actually read whole). Merged to main: Tasks
          1-2 (#18), 3 (#19), 4 (#20), 5 (#23), 7a Steps 1-3 (#24, + the #26
          cooloff fix), 8 (#22, ADR-0010), 6 (#27, the webhook rewrite),
          7b (#28, startup sweep + the review-state casing fix — which
          CLOSES Task 7), #29 (the late #24 re-review), 10 (#32, code) with
          the operator cutover run 2026-08-01, and #34 (m1-cutover-done).

          #34 (m1-cutover-done) was not a plan task. The cutover
          exposed that worker.process_job wrote NOTHING to the log on any
          successful outcome, so "the review ran" and "the job was never
          claimed" were indistinguishable — answering "did that review
          actually run?" took four tool calls, a dashboard fetch and a
          browser screenshot. It adds one line per outcome, and the fresh
          review and the idempotent replay are worded so they can never be
          confused: only the fresh one says "paid read", because only it
          bought one. See the decision below for why that distinction is
          the change rather than a detail of it.
Next:     A SOAK on the live App path, then M1 Task 9. Task 9 (retire the
          CI token path: delete .github/workflows/doug-review.yml and
          /v1/review) is unblocked and code-ready, and is deliberately NOT
          the next thing anyone does. Andrew's
          call, 2026-08-02: the CI path and the App path run in PARALLEL
          until the App path has been watched against an independent
          reviewer, because Task 9 deletes that reviewer. Exit criteria are
          counted in PRs, not days — see the soak decision below, which
          also carries the reason and the concurrent UI work reading the
          same rows. That decision supersedes nothing about the 10-then-9
          resequencing; it adds a gate in front of the 9.
          Rebase vs. merged #15 still to be done deliberately. AFTER the
          soak and Task 9, M1's exit gate is checkable end to end.

          SOAK TALLY as of 2026-08-02 ~15:30Z (counted from the prod logs;
          nothing was counting it before, so re-count rather than trust this
          if much time has passed). Source: `gcloud run services logs read
          doug-api --region us-central1 --project doug-prod0 | grep
          "doug: reviewed"`.
          1. MULTIPLE PUSHES — MET, twice: #37 (78649827, bc0968a5) and #38
             (1294e160, bee606e2) each scored at two head SHAs.
          2. COLD START, sweep enqueues >0 — NOT MET, and it will NOT be met
             by waiting. Every reconcile line in the window says "enqueued 0
             job(s)". The webhook path drains jobs promptly, so at any boot
             there is nothing pending for the sweep to find. The criterion
             asks the backstop to prove itself, and passive soaking cannot
             create the condition it needs. ANDREW RULED 2026-08-02: FORCE
             THE CONDITION, rather than rewrite the criterion or drop it —
             it was written to test an untested claim, so weakening it to
             pass would defeat its purpose. Procedure agreed, NOT YET RUN
             and deliberately not run unattended, because step 1 is a
             deliberate production degradation: (1) stop deliveries reaching
             the queue, (2) push to an open PR so no job is enqueued, (3)
             let the service cold-start, (4) expect "doug: reconcile
             enqueued 1 job(s)" plus a check run for that SHA. Costs one
             paid read. Run this WITH Andrew, not for him.
          3. MERGE writes an outcome_jobs row — UNVERIFIED. #35/#36/#37 all
             merged 2026-08-02 and no log line covers this path, so it needs
             a ledger read, not a grep. Cheapest honest check available.
          4. ~10 CHECK RUNS none missing — 7/10. Reviews: #30@afee4cac,
             #35@5c59fe84, #36@36606df3, #37 ×2, #38 ×2. No gaps: every PR
             that saw a push since the line existed produced one. Note the
             count only starts at #34's merge (06:22Z), because the
             "reviewed" line did not exist before it.

          M2 SAFETY WORK IS NOW MOSTLY DONE, out of order and deliberately,
          because the cutover changed the risk: paid reads are now triggered
          by webhook deliveries — PR activity Doug does not control — rather
          than by our own CI. Merged: #35 (/v1/score/read was unauthenticated
          AND paid on a public --allow-unauthenticated service; now gated)
          and #37 (MERGED 2026-08-02T07:26Z, a8cc396, main's HEAD): the spend
          cap wired to every paid call site, plus per-read cost capture.
          Spend is now bounded AND measured — the cost lines are live in
          production, confirmed on the serving revision from 15:16Z.

          The remaining M2 items, in the order I would do them:
          0. NEW, FOUND 2026-08-02 BY READING #37's OWN COST LINES — the
             intent read's per-installation flag DOES NOT EXIST. design-lock
             .md:62 (red-team mitigation "overclaim #4 = scope #1") commits
             to "per-installation flag, default OFF, ON for the dogfood
             install; labeled experimental; stays off until the pre-
             registered positive control passes." What is actually in the
             code is a PROCESS-WIDE env var: intent.enabled() is
             `os.environ.get("DOUG_INTENT") == "1"` (api/doug/intent.py:73,
             duplicated at api/doug/reader.py:527), consulted once in
             review.read_intent (api/doug/review.py:307) and never per
             installation. It is ON in production — the kind=intent lines
             prove it. Harmless at one installation; the moment there is a
             second, that tenant gets the experimental read, charged to
             THEIR ceiling, with no per-tenant off switch. M2's exit gate is
             "safe to point at strangers", so this belongs in M2 and is not
             on the roadmap's M2 list at all. NOT a live incident: install
             visibility is still "Only on this account".
             BUILT — PR #39 OPEN (branch intent-per-installation-flag; 500
             passed, was 492; ruff clean; 6 mutations caught). Doug reviewed
             it: FLAGGED 0.32 vs 0.30, and its 90% PARTIAL READ was caused by
             a stray file this branch should never have carried (see the
             git-add note below). Findings answered in a PR comment — 2
             fixed (canonical scope parsing; the deploy test now pins "and
             nobody else" instead of unpacking one line), 1 disproved
             (reader.intent_enabled had no caller anywhere), 1 already
             disclosed (config drift until gcp.sh runs). Andrew ruled ENV
             ALLOWLIST over an installations column — no migration, no
             collision with 005, right size for one install; it becomes a
             column when item 3's dispense work opens that table anyway.
             Shape: intent.enabled_for(installation_id) over
             DOUG_INTENT_INSTALLATIONS, with the id derived from the SAME
             scope string the spend cap charges (reader.installation_from_
             scope), so payer and opted-in party cannot drift. Untenanted
             callers → None → no intent read, which also halves the soak's
             intent spend. gcp.sh switched to the allowlist and PINNED by a
             test, because silent-off is the safe direction and therefore
             the easy one to ship by accident.
             NOT YET DEPLOYED — until gcp.sh runs, prod still has the old
             DOUG_INTENT=1 and the fix is source-only.
             Cost context, first real numbers Doug has ever had: on #38 each
             push bought FOUR reads, because the soak dual-runs both paths —
             risk and intent, each on scope=installation:150424894 and again
             on scope=untenanted. The intent read is the LARGER of the two
             (in=16601/out=1305 vs in=14031/out=925), so the unvalidated
             feature is over half the input tokens per PR. Cross-reference
             the derangement check below: intent findings are UNBELIEVED and
             a positive control is still unrun.
          1. Migration 005 — DONE (#43). UNIQUE App-path verdict identity.
          2. doug-web's own service account — CODE DONE (#44). Ops cutover
             may remain: first `gcp.sh web` as `doug-web-sa`, then revoke
             default compute SA’s leftover `doug-api-token` accessor.
          3. Per-installation scoped reads + token dispense. This is the
             one that actually gates real tenants, and it is untouched.
          4. Bot-author exclusion — RE-SCOPE THIS BEFORE BUILDING IT. The
             roadmap wants bot-authored PRs excluded from deep reads to
             save money, but Doug's thesis is AI-review routing and the
             agentic-trust surface, so those are the PRs it exists to
             grade. api.py already says as much for the reviewer lane
             ("grading bot reviewers is the point of the lane"). Probably
             metering, not exclusion. Andrew has not ruled on it.

          What the cutover actually put in production, verified on the
          serving revision: doug-api runs as its OWN service account
          doug-api-sa (not the default compute SA, which holds
          roles/editor on doug-prod0); DOUG_GITHUB_APP_ID and
          GITHUB_APP_PRIVATE_KEY are both in --set-secrets, so
          app_auth.enabled() is TRUE in prod for the first time;
          --no-cpu-throttling is set, without which the background drain
          is suspended the moment its request returns; and Task 7b's
          startup sweep runs at boot, which needs both of those at once.
          doug-web SA code is on main (#44); confirm the serving web
          revision identity after the next web deploy.
Blockers: NONE. Both Andrew-only items closed 2026-08-02 and verified:
          - "Pull request review" event subscription ENABLED (Andrew
            confirmed). The tier='external' grader lane can now receive.
            Nothing has exercised it yet in production — the first
            third-party review on a PR is what proves it, and no log line
            fires when it works, only when the state is unrecognized.
          - Anthropic key rotation CLOSED: v2 live, v1 DISABLED in Secret
            Manager (verified `state: disabled`), local plaintext file
            deleted. Every secret binding is `version=latest` — verified
            on the serving revision — so disabling v1 was safe. NOTE that
            `latest` means a future v3 is picked up silently; nothing pins
            a version anywhere.

          Standing hazard, not a blocker: GitHub's REST quota is 5,000/hr
          and is SHARED across every concurrent session and agent. It was
          exhausted twice on 2026-08-02. Prefer `gcloud run services logs
          read doug-api` over `gh` for anything the logs can answer —
          since #34 and #37 they answer most of it.

Execution model (do not rediscover this):
- One PR per task. Doug reviews each (ADR-0008); read its findings, but
  VERIFY before fixing or dismissing — roughly half are disproved by files
  outside the diff. See docs/REVIEWING.md, which is the accumulated
  lessons from ~20 findings across two review layers.
- Per task: fresh implementer subagent from an extracted brief, then an
  INDEPENDENT reviewer, then a fix round, then a scoped re-review. Do not
  let the implementer grade its own work, and do not fix findings in the
  controller session.
- Extract a brief with sed from the plan; never make a subagent read all
  4591 lines. Task line ranges: T6 2638-3395, T7 3396-3716 (Step 4 starts
  at 3267 of that slice), T9 4025-4244, T10 4245-4591.

Standing rules this branch learned the hard way:
- NEVER `git add -A` at this repo's root. The main worktree carries other
  sessions' UNTRACKED files — .claude/worktrees/ holds six live branches —
  and a repo-wide add swept a landing-theme design spec into #39. It cost a
  commit to undo and it degraded Doug's review of that PR to a 90% partial
  read, cut inside the stray itself. Stage explicit paths. Undo with
  `git rm --cached` so the other session's on-disk copy survives.
- Doug's deviation stream is UNBELIEVED by policy (failed derangement check)
  and has now flagged the real defect TWICE on the same subject: arms.json:187
  had already caught the DOUG_INTENT=1 service-wide deviation that #39 fixes,
  and the #39 review's beyond-ticket finding is what caught the stray file.
  This is NOT validation — a failed derangement check validates nothing in
  either direction — but it is the concrete argument for scheduling the
  positive control instead of leaving the tier disbelieved indefinitely.
- A docstring asserting a durability/ordering/concurrency property must be
  TRUE. Eight separate findings here were comments promising guarantees
  the code did not make. If nothing enforces the claim, the comment is the
  bug.
- Plan INTENT governs over the plan's literal code sample. Several samples
  violated constraints the same plan states in prose. Fix it, and record
  the ruling in the PR body rather than applying it silently.
- A test that cannot fail when its named behavior regresses is an
  Important finding. Two shipped tests here were vacuous; both were caught
  by mutation, not by reading.

Key facts for the executor:
- App: dougs-review, App ID 4450932, installation 150424894 on drewjst
  (User, selected: doug only). Perms checks:write/contents:read/
  pull_requests:read/metadata:read; events: pull_request. Private key in
  Secret Manager doug-github-app-key — Task 10 SETTLED the custody
  question: it is granted to the dedicated doug-api-sa, not to the default
  compute SA. Webhook secret doug-webhook-secret v2 (v1 has a trailing
  newline; bound as :latest, which IS v2 — this file once claimed it was
  pinned to :2 and that was never true). Webhook verified end-to-end in
  prod: ping + installation events 202 with valid signatures. Deliveries
  no longer verify-and-discard — Task 6 (#27) dispatches them, and since
  the 2026-08-01 cutover that is what production is actually running: the
  discarding revision is gone.
- Install visibility is "Only on this account" — flip to "Any account"
  before installing on lemahq/lema (Task 10 cutover).
- Carried forward for the doug-web SA follow-on, verified during Task 10's
  scoping and still true of doug-web: the default compute SA holds
  roles/editor on doug-prod0, and roles/editor does NOT include
  secretmanager.versions.access. So the explicit secretAccessor bindings in
  api/deploy/gcp.sh:88-98 are LOAD-BEARING, not belt-and-braces, and the
  gcp.sh:84-87 comment saying so is accurate as written. Do not "simplify"
  those bindings away on the assumption editor covers them.
- The plan was built by 3 drafting agents on locked interfaces, reviewed by
  2 adversarial verifiers (both verify by execution), 3 blockers + 5 majors
  fixed. Deepest invariants (do not "tidy" these away): enqueue REVIVES
  failed/superseded rows in place with a STABLE id; drain's seen-set bounds
  both retry burn and the force-push supersede/revive ping-pong; the
  no-ledger 503 is scoped to the three handled webhook events only.
- Derangement check (2026-07-31): BAR FAILED and the instrument is invalid
  for constraint-style records — validates nothing either way. Deviation
  findings stay UNBELIEVED; check-run copy must keep the "unvalidated"
  label. Positive-control experiment needed before further intent-stream
  investment. Full analysis: workspace/research/phase1-entry-preregistration.md
  (workspace/ is untracked — lives only on Andrew's machine).

Decisions this session (2026-08-01/02, cutover + the logging it exposed):
- TASK 9 WAITS FOR A SOAK (Andrew, 2026-08-02). The CI path and the App
  path run in parallel on purpose, so the new path can be compared against
  an INDEPENDENT reviewer before the old one is deleted. The reason is the
  App path's characteristic failure mode: SILENCE. Nothing turns red, no
  job fails, no alert fires — the check run simply never appears, and an
  absent check run looks exactly like a PR nobody pushed to. The CI job
  summary is the second, independently-triggered observer that would make
  that visible, and Task 9 is what deletes it, so it goes last.
  Note this is a different claim from the logging work above: that logging
  makes a review the operator ASKS about answerable in one grep. It cannot
  reveal a review that was never triggered, because the missing line and
  the un-triggered job are the same absence. Only a second path scoring
  the same PR can.
  EXIT CRITERIA — counted in PRs, not days. All four:
  1. a PR with MULTIPLE PUSHES (exercises supersede + re-enqueue),
  2. a COLD START whose startup sweep enqueues >0 jobs — it has only ever
     logged 0 in production, so the backstop has never actually done
     anything and is currently an untested claim, not a verified one,
  3. a MERGE that writes an outcome_jobs row,
  4. ~10 CHECK RUNS with none missing.
- A SECOND SESSION is concurrently building the dual-run comparison UI in
  web/, on branch dashboard-dual-run. It owns web/**, api/tests/test_api.py
  and api/tests/test_store.py, and appends only in api/doug/api.py and
  api/doug/store.py. What makes the comparison possible, and is NOT obvious
  from the schema: both current App and CI paths write head_sha as shared
  commit identity for idempotency. App alone also writes installation_id and
  github_repo_id. Current CI therefore has both App ids NULL and head_sha
  populated; legacy CI rows may have all three NULL. The comparison separates
  paths by the App id pair after the store predicate qualifies a row, and
  excludes either one-id shape, both App ids without a head SHA, and
  tier='external'. `/v1/review` replay is scoped to the same null App-id pair,
  so an App verdict cannot suppress the independent CI measurement. A legacy
  row with no head remains visible as neutral, unpairable evidence; it cannot
  establish that either path is missing.
- A FRESH REVIEW AND AN IDEMPOTENT REPLAY MUST NOT LOG ALIKE. They agree on
  every field either line could carry — repo, PR, head SHA, tier, band,
  score, verdict id — and differ in exactly one thing: the fresh one bought
  a model read and the replay re-rendered a row already in the ledger. So
  the difference has to live in the WORDING or it does not exist: one line
  covering both would make spend unauditable from the logs, with an
  operator counting reviews counting replays that cost nothing. Only the
  fresh line says "paid read" — rejected: a single "job N complete" line,
  which is what "add a success log" naturally produces and is worse than
  the silence it replaces.
- The fresh line is emitted BEFORE ingest.complete, not after. By that
  point the read is paid for and the verdict durable, and complete()
  raising is the one failure that re-pends a job in exactly that state — it
  must not be able to erase the record of what the attempt cost. It is
  still not a complete spend ledger (a read dying before save_review
  commits leaves only drain's failure line) and the code says so rather
  than claiming a guarantee it does not make.
- Key rotation CLOSED and verified rather than trusted: the plaintext
  api/.backtest-cache/llm-probe/api-key is gone (whole llm-probe/ directory
  with it) and doug-anthropic-key has a v2 created 2026-08-02. The "v1 still
  enabled" loose end this line used to carry is CLOSED — v1 is disabled and
  verified; see Blockers, which is the current record.
- ROADMAP's Task 10/Task 9 item SPLIT into two boxes. One box covering two
  tasks cannot record that one is done and the other is not — rejected:
  ticking the combined line, which would have read as Task 9 being done.

Decisions this session (2026-08-01, M1 Tasks 6–7b):
- Task 9 RESEQUENCED AFTER Task 10 (Andrew, 2026-08-01): Task 9 deletes
  .github/workflows/doug-review.yml, which is the surface producing Doug's
  reviews on this repo today. Deleting it before the App's check run is
  verified working in production would leave every PR — including the ones
  fixing that — reviewed by nothing, with no fallback to roll back to —
  rejected: the plan's 9-then-10 order.
- Task 7b tested the lifespan wiring the brief shipped untested. The brief's
  own note ("both guards are off in tests, so TestClient never spawns the
  thread") describes the gap rather than justifying it; the tests patch
  app_auth.enabled/store.enabled instead of the env behind them, and the
  thread is named so "no thread was started" is assertable rather than a
  race — rejected: shipping Step 4 with the coverage the brief specified.

Decisions this session (2026-08-01, M1 Tasks 1–2):
- outcome_jobs is a store.metadata table, NOT a migration (Global
  Constraint: new tables via create_all; migrations are for columns on
  existing prod tables) — rejected: ROADMAP's literal "migration 002"
  framing for the table.
- installation.created token mint SKIPPED: hash-only storage makes an
  install-time mint unrecoverable dead weight; M2's dispense endpoint
  mints and writes installations.token_hash (column landed in Task 2) —
  rejected: minting a token nobody can ever read back.
- verdicts.source widened to String(64) ('review:<login>' needs 46) —
  rejected: plan's String(20).
- Two plan-mandated defects fixed against the plan's literal code because
  the plan's own stated invariants condemned them: apply()'s version
  insert now swallows the duplicate-version race (docstring: "already
  done is satisfied, not failed"); drift test now pins BOTH directions
  (baseline + migrations == metadata) — rejected: shipping the plan's
  verbatim body over its intent.
- pull_request_review ingest design (for Task 6): tier='external',
  band cleared/flagged from review state, dedup on (inst, repo, pr,
  source, head_sha, scored_at); latest_reviews/find_review must exclude
  tier='external'. GitHub App needs the "Pull request review" event
  subscription — MANUAL step, Task 10 cutover checklist.

Decisions this session (2026-07-31/08-01, M0 pass):
- workflow-summary-test-fidelity: DROPPED, branch deleted (local + remote).
  Its only real content vs main was a test regex fix, already byte-identical
  on main; the branch's sole diff was a stale HANDOFF.md snapshot —
  rejected: merging it (nothing to merge).
- PR #15 was already merged upstream before this session acted on it
  (by a concurrent session); local main fast-forwarded, no rebase needed.
- Intent-stream posture (per-installation flag, default OFF for tenants,
  ON for dogfood, experimental label) needed no new decision — confirmed
  already written into design-lock.md:62 — rejected: re-deciding it.
- Key rotation at api/.backtest-cache/llm-probe/api-key deferred by Andrew
  this session (needs Anthropic console access) — rejected: deleting the
  file without rotating first (would just lose the credential, not retire
  it).

Prior decisions this session (2026-07-31/08-01, step-2 plan):
- Step-2 plan pushed straight to main (Andrew's instruction, sole session);
  execution returns to PRs. — rejected: PRing the plan doc (explicitly
  overridden by Andrew).
- ADR-0003 will be superseded by ADR-0010 (neutral check run) in the same
  commit as the check-run code; ADR-0007 and ADR-0008 get prose corrections
  only (their decisions stand, their surface references die with CI).
- Anthropic key rotation staged create-then-revoke-after-verify (Task 10)
  so the live reader never breaks between rotation and deploy.

Pointers:
- Plan: docs/superpowers/plans/2026-07-31-step-2-github-app-webhook-ingest.md
  (commits d51eec8..94f87e9+). Spec: docs/superpowers/specs/
  2026-07-30-github-app-tenancy-dashboard-design.md (lema mentions
  clarified 2026-08-01).
- Roadmap: docs/design/outcome-loop/ROADMAP.md — the tracking document,
  M0 through M6.
- Full session state: ../HANDOFF.md on Andrew's machine (project root,
  above this repo) is the richer, hook-maintained handoff.
- PR #16 open: docs/outcome-loop-design-lock (design docs + landing-page
  section + .env.example MAGPIE_*→DOUG_* fix).
- stash@{0} (queue-polish era): dashboard repoint + the lost step-1 plan
  file. Both obsolete (repoint shipped via deploy config; plan content
  landed in #14) — drop deliberately when convenient.
- Carried forward: reader-feedback items 3 & 4 (invariant-vs-mechanism;
  severity = impact × confidence) need a frozen v2 prompt + validation run —
  credits now exist, still unscheduled. lema#643 had FOUR reader findings
  (reader:brittle-test-assertion, low, unscored) — evidence the reader
  reads tests it is given.
