# HANDOFF — doug

--- docs lane (2026-09-15): one docs site at /docs, in the audit docs' look ---

State:    review — **doug#350**, branch docs/one-docs-site (off origin/main
          2561e5f, worktree .claude/worktrees/docs-one-docs-site). Andrew, in
          session: everything under coldworks.dev/docs, the /docs/audit look
          kept, and the audit maybe not its own docs page; the UI structure
          was left to the agent. Verified 2026-09-15: lint rc 0, tsc rc 0,
          unit tests 463 passed, the build-and-serve integration test 16
          passed, 29 of 29 planted mutants killed, and a production build
          serving the docs module CSS, the four docs fonts, and the
          redirects. Auto-fix is on for #350 (Andrew, 2026-09-15).
Next:     auto-fix wakes this session on CI failures, conflicts, and review
          comments. The merge is the founder's click. coldworks#93 moves
          concept.md's citation of the deleted cli.html to the page's URL.
Blockers: none.
Decisions this session:
- One docs shell: the audit is a section of /docs, not a second site with
  its own chrome and a "Doug's docs" link out — rejected: the audit pages
  as external anchors (what shipped in D3), and product tabs, which keep
  two trees.
- /docs is one overview in the audit page's layout: Doug's introduction and
  the audit overview become its two sections, and /docs/audit redirects to
  /docs#the-audit with a 307 — rejected: a hub plus two section intros (the
  hero sentence twice), and moving Doug's pages to /docs/doug/* (breaks the
  PR-comment footer link and every link already written).
- Every other URL keeps resolving: the audit pages stay at
  /docs/audit/{quickstart,connect,cli}, and their .html forms redirect.
- Doug reviews comes before the audit in the sidebar, in the door's order.
- The docs wear the audit's flat top bar with the site header's NAV_LINKS,
  theme toggle, and Sign in, so the nav keeps one source (ADR-0034 T7).
- The look is a CSS module, not global CSS: globals.css already defines
  `.code`, and the audit's class names are generic. Fonts load through
  next/font/local from the landing's own woff2 files (byte-identical).
- Doug's pages go to one column, each example after its prose — rejected:
  a sticky rail beside a 760px reading column. One sentence followed:
  "beside this paragraph" became "in the panel below".
- `.code-rail` and `--docs-content-offset` left globals.css, because the
  docs were their only users; the design-system scan's code-rail exemption
  went with them, and a pin holds the docs' code panel to ink in both themes.
- The top bar has a fixed 61px height: with the theme toggle and Sign in it
  measured 61px, and a sidebar stuck at 57px slid under it.
- Doug's read of 8d27bc4 (3 medium, 2 low), answered on #350. Fixed: the
  www rule forwarded every /docs path to /docs/audit, so www/docs/report
  was a 404 and www/docs/audit/cli went to /docs/audit/audit/cli; it now
  forwards only the audit's legacy page names. Both URLs are in the
  integration table, and a test reads the #the-audit heading from the
  served overview; each failed on a planted input first. Refuted: removed
  exports (no importer anywhere, and CI built every page), the pager's
  external branch (no entry can be external), and the globals.css removals
  (no users). Kept: the two-hop www chain for the audit's home, because its
  first hop is a cached 308 and must land on a stable apex URL; the review
  below moved www's .html page names onto their routes in one hop. The
  beyond-ticket deviation (a second top bar) is Andrew's ADR call, doug#358.
- Doug's read of cecdb8e (1 medium, 4 low), answered on #350 with no code
  change: redirect-chain restates the kept two-hop chain; broken-link holds
  only for docs.css, deliberately; stale-reference restates
  css-contract-drift; duplicate-markup and semantic-drift are refuted
  (display: none hides one nav at every width, and no panel pairs Fn with
  Ok). Every disposition from both reads is a findings-log row, the two
  deviations included (0a0f522).
- main merged into the branch on auto-fix: #349 and #352 changed the
  caching copy in the static cli.html and connect.html this PR deletes, so
  the wording moved into the two routes, checked equal to main's text.
- Adversarial review at max effort, on Andrew's request: ten finder angles,
  one verifier per candidate (18 verified in session after the 20-agent
  cap), and a gap sweep; 42 candidates, 2 refuted (the lost <article>, and
  the docs' chip words against lib/state-chip.ts, whose closed vocabulary
  governs the dashboard). Fixed in 0a0f522: the index URLs, www .html in
  one hop, the audit half's claim scope and the lede, AA inks, link
  underlines, the long chip's wrap, a 320px top bar, the mono fallback, the
  menu and sidebar closing, the filter, list semantics, chip tones, and new
  pins (13 of 13 planted mutants killed, 2 of them in the integration test). Filed: #358, #359 (self-serve
  copy), #360 (root fonts on docs routes). Not changed: DocsArticle itself,
  DocsCrumb's client boundary, and the landing's inlined fonts.
Pointers: web/app/docs/ · web/components/docs/ · web/lib/docs-nav.ts ·
          web/next.config.ts · web/lib/{shell-contract,docs-nav,design-system,
          auth-entry.integration}.test.mjs · web/public/docs/audit/ (removed)

--- reader lane (2026-09-14): annotate a broken-syntax deviation beside a syntax settlement, doug#345 ---

State:    review — **doug#346** (closes #345), branch
          reader/deviation-syntax-annotation off origin/main 1bbade1, worktree
          .claude/worktrees/doug-deviation-annotate. check_run.render appends
          SYNTAX_DEVIATION_CHIP to a deviation whose description claims broken
          syntax, when the same verdict carries a `settled-syntax-error`
          notice. The deviation row, text, severity, band and score are
          untouched. make check green; full suite 1,984 passed at 81e1efc;
          9 of 9 mutants killed. Decision recorded on #345.
Next:     watch CI and Doug's read on #346; the merge is the founder's click.
Blockers: none.
Decisions this session:
- Annotate, not drop (Andrew, 2026-09-14) — the deviations table is what
  ADR-0007's eventual evaluation reads, so a filter would change what it
  measures — rejected: dropping the deviation with settle.py's syntax class.
- The chip keys on the settlement in the same verdict, not a fresh parse —
  DeviationFinding carries no file, and parsing every changed .py file per
  deviation costs a fetch per file (98 on #339) — rejected: parsing the PR's
  Python files for each syntax-claiming deviation.
- The chip states what the parser found, never that the deviation is wrong —
  the deviation may be about a file the reader did not flag.
- Known limit: no chip when the reader flagged nothing or its findings were
  not settled; the deviation then stands as written.
- Doug's reads of #346 at 81e1efc and 33e08e3, answered on #346. The
  `reader:regex-false-positive` low is valid and fixed: the matcher now
  wants a phrase (`SyntaxError`, "syntax error", or syntax within twelve
  words of fatal, invalid, break, broken or crash, either order), so "the new
  match syntax changes the import order" and "the import of the syntax
  helper failed lint" get no chip — rejected: keeping import, parse, error
  and fail as breakage words. `reader:semantic-mismatch` is partly valid: a
  deviation names no file, so the chip now says the files are listed under
  `settled-syntax-error`. `reader:missing-import` is refuted (`import re` at
  check_run.py:35), and settlement kept it because "import time" vetoes
  `claimed_names`; filed as #347. The `beyond-ticket` deviation (no ADR
  covers composing the chip into the line) is answered by the decision on
  #345 and docs/REVIEWING.md; an ADR is Andrew's call.
- Doug's read of #346 at 0f862ed (3 low), answered on #346:
  `reader:doc-code-mismatch` valid, fixed — docs/REVIEWING.md still listed
  the old trigger words. `reader:regex-backtracking` refuted with timings:
  33 ms on a 100,000-character adversarial description, 0.07 ms on 2,000
  characters, and the reader's output cap keeps real descriptions far
  shorter — rejected: an input-length guard. `reader:heuristic-false-
  positive` accepted as the window's known miss and named in
  docs/REVIEWING.md — rejected: a narrower window, which would miss the #339
  wording ("fatal" nine words after "syntax").
Pointers: api/doug/check_run.py (SYNTAX_DEVIATION_CHIP, claims_broken_syntax) ·
          api/tests/test_check_run.py · docs/REVIEWING.md · #345 · #231 (same bullet)

--- tooling lane (2026-09-13): a static gate for api/ and agent hooks, doug#337 ---

State:    review — **doug#339**, branch tooling/static-gate off origin/main
          507f8b0, in the worktree .claude/worktrees/doug-static-gate.
          6aad653 formats api/ and changes nothing else (98 files); 2ac8b06
          adds `make check`: ruff format and lint with a 195-pair debt table,
          basedpyright standard against a 1,522-entry baseline, `uv lock
          --check`, and .github/scripts/check_ratchets.py; CI's api job and a
          Stop hook run it. Each gate shown red on a planted input and green
          after restore, including debt and baseline growth in a clone whose
          origin/main carried both. Full suite 1,966 passed.
          2026-09-14: merged origin/main e7d65f3 (#340, #341, #343, #344).
          HANDOFF.md was the only conflict. The merge formats #344's five
          files and drops one stale debt entry (ERA001 in convergence.py,
          194 pairs left); `make check` green on the merged tree.
Next:     watch CI on #339; the merge is the founder's click. #331 and #332
          rebase with `ruff format` on their branches. Once deep read is on
          for this repository, Doug's next read of #339 is the first live
          test of #344's `settled-syntax-error` on the eight PEP 758 clauses.
Blockers: none.
Decisions this session:
- Measured 2026-09-13 at 507f8b0: ruff format would rewrite 98 of 130
  files; the extended rules report 5,870 violations (259 in doug/, 125 in
  scripts/, the rest in tests); pyright basic reports 1,519 errors and
  strict 19,216. Debt only shrinks — rejected: flipping any of them on.
- basedpyright with its native baseline, not pyright — a plain run shrinks
  the baseline when an error is fixed (measured: "went down by 1") and only
  --writebaseline grows it, so the ratchet counts baseline entries per rule
  against the merge base and fails a rewritten, uncommitted baseline.
- No `filterwarnings = error`: with it the suite reports 324 failures and 14
  errors, 1,129 of them ResourceWarnings from unclosed sqlite connections —
  a real leak, filed as doug#338 rather than hidden.
- Doug's read on 9964a78 (5 high, 1 medium, 1 low), answered on #339. The
  five `reader:syntax-error` highs are refuted: `ruff format` rewrote eight
  clauses to PEP 758 `except A, B:`, which 3.14.7 parses and 3.13.15 rejects,
  and api/ already needed 3.14 (507f8b0 api.py:1389 annotates a method with
  its own class, no `from __future__ import annotations`). Filed the reader
  false positive as doug#342 — rejected: pinning ruff to py313 to keep the
  parentheses, which makes ruff report F821 on that annotation. Medium partly
  valid (open branches and dependency bumps meet the gate), no code change;
  low refuted (blocks once; stop_hook_active).
- Formatting is its own commit — doug#331 and doug#332 touch three api/
  files and rebase with one `ruff format` — rejected: reformatting on touch,
  which spreads format noise across every later diff.
Pointers: api/pyproject.toml · Makefile `check` · .github/scripts/check_ratchets.py ·
          .claude/{settings.json,hooks/} · api/tests/test_{check_ratchets,claude_hooks}.py

--- reader lane (2026-09-14): syntax-error findings the declared Python parses, doug#342 ---

State:    review — **doug#344** (closes #342), branch reader/syntax-claims-parse
          off origin/main 8ffb734, worktree .claude/worktrees/doug-reader-syntax.
          settle.py's fourth class, `settled-syntax-error`: a finding whose slug
          names a Python syntax error on a .py file is dropped when the file at
          head passes `ast.parse(feature_version=<oldest declared 3.x>)` and
          `compile`. The declaration is the nearest requires-python, else the
          nearest .python-version. Full suite 1,953 passed at dfa7341; ruff
          clean; 13 of 13 mutants killed; the added lines carry 0 violations
          under #339's rules and 0 basedpyright standard errors.
Next:     watch CI and Doug's read on #344 and answer its findings; the merge
          is the founder's click.
Blockers: none. Independent of #339; if #339 merges first, this branch
          rebases with `ruff format` over api/.
Decisions this session:
- A post-read settlement, not a prompt change — ADR-0002 freezes the reader
  prompt, and the three existing classes use the same seam — rejected:
  telling the reader the repository's Python version.
- The oldest declared version decides, and a minimum below 3.8 or above the
  running interpreter abstains — a file that parses only on newer Pythons is
  broken for a supported one, and feature_version models the grammar, not
  compiler rules (`continue` in `finally` before 3.8) — rejected: parsing
  with the running interpreter, which settles a true claim for a 3.10 repo.
- Candidates come from the slug alone, with a veto on descriptions naming
  another grammar — "literal_eval raises SyntaxError" and invalid SQL are
  real runtime claims about files that parse — rejected: matching
  "SyntaxError" in descriptions.
- Dockerfile base images are not read, narrower than #342's text — a base
  image names a runtime, not the range a project supports.
- #339's five disproved rows are logged in docs/findings-log.jsonl.
Pointers: api/doug/settle.py (fourth class) · api/doug/review.py score_one ·
          api/tests/test_settle.py · docs/REVIEWING.md · #342 · #339

--- shell lane (2026-09-14): D5 and the www half merged; FQ-29 landed ---

State:    done in code and deployed. #340 (D5) squash-merged as 242db1a and
          #341 (www redirects to the apex, the code half of #333) as 94cd0a5;
          main carries both tips (checked). FQ-29 is landed: both repository
          variables are set on this repo (values never enter it) and the
          founder's dispatched web deploy (run 34811345583) promoted
          doug-web-00160-lay with COLDWORKS_REGISTRY_URL and
          DOUG_GUARDS_INSTALLATIONS non-empty. The 94cd0a5 push deploy that
          carries the www rule follows it in the queue; the rule is inert
          until www is mapped onto doug-web.
Next:     Founder: after the 94cd0a5 web deploy, `domains.sh map` for www,
          `status` until READY, never `cutover` (the script refuses it);
          delete the registry's www mapping last, or first if the
          certificate will not issue while the registry serves the domain,
          the FQ-28 path. In a browser at coldworks.dev: Phase 0 items 2 to
          5, said aloud to the agent, who dates them on hq frontdoor-12.8.
          Agent, after www serves doug-web: the coldworks PR that removes
          the registry's www forwards and criterion 10's local www block.
Blockers: none in code. The registry snapshot reads stale from 2026-09-26
          about 04:28Z; items 2 and 5 observed after that need a mirror
          push first.
Decisions this session (2026-09-14):
- Repository variables, not secrets and not literals — neither value is a
  credential, and the mapping names an engine tenant that stays the
  founder's setting outside a public file — rejected: a literal in
  deploy.yml; a Secret Manager entry.
- The pin derives the forwarded names from gcp.sh's --set-env-vars line —
  a third forwarded variable is caught the day it is added — rejected: two
  literal asserts.
- www's docs URLs forward to /docs/audit, mirroring the registry, ahead of
  the path-preserving catch-all — on the apex /docs/cli.html and
  /docs/docs.css are 404 and /docs/cli is Doug's own page (probed
  2026-09-14) — rejected: one path-preserving rule.
- 308 for the www rules — the alias is settled, and a later move of the
  audit docs is the apex's own redirect to add — rejected: the registry's
  temporary forwards, which were interim on a host that was leaving.
- www joins RETIRED_HOSTS in auth-origin.ts and the cutover refusal in
  domains.sh — a 308 host holding the redirect URI loops with the proxy's
  307, the case ADR-0034 closed for the subdomain — rejected: the
  issue's prose "never cutover" alone.
- Doug's reads adjudicated on both PRs: #340 two low refuted; #341 one
  medium (a stale RETIRED_DOMAIN reference: none exists, map and status
  reach gcloud under set -u behind a shim) and two low refuted.
Pointers: .github/workflows/deploy.yml (web Deploy env) · api/deploy/gcp.sh
          web() --set-env-vars · api/tests/test_deploy_gcp.py
          _web_passthrough_env · web/next.config.ts redirects() ·
          web/lib/auth-origin.ts RETIRED_HOSTS · api/deploy/domains.sh
          RETIRED_DOMAINS · web/lib/auth-entry.integration.test.mjs
          (single-host suite) · #333 · hq
          docs/cross-repo/one-shell/handoff-close.md · roadmap frontdoor-12.8

--- shell lane (2026-09-14): ADR-0034 accepted, merged as #336 (507f8b0) ---

The squash is the signature (FQ-27): ADR-0034 `proposed` to `accepted` on
the founder's instruction in session. The registry deploy that ships the
snapshot route landed the same day (coldworks-registry-00007-dqv), and
Phase 0 item 6 is recorded on hq frontdoor-12.8 for the checks a remote base
can run.
Pointers: #323 · docs/decisions/ADR-0034-*.md · coldworks#77 · hq
          docs/cross-repo/one-shell/handoff-s2.md

--- shell lane (2026-09-11): doug D4, merged as #328 (081f03f) ---

Decisions this session (2026-09-11):
- The redirect is a build-time `redirects()` keyed on the literal retired
  host — Next reads Host and the design forbids env-keying (deploy.yml
  already sets DOUG_WEB_DOMAIN, so it would fire on merge); rejected: an
  env-keyed or proxy-based runtime redirect.
- `permanent: true` (308) — ADR-0034 decision 1 rules a permanent redirect;
  rejected: a 307 to ease rollback, which contradicts the signed ADR.
- The merge hold is code, not prose: `gcp.sh` refuses the web deploy while
  the apex is unmapped, before a candidate revision exists — rejected: the
  draft flag alone (the founder lifted it before FQ-28) and a post-promotion
  smoke alone (reports after tenants are already redirected).
- `auth-origin.ts` refuses a redirect URI on the retired host (503, loud) —
  rejected: a secret-reading gate in gcp.sh (the deployer holds
  secretmanager.viewer only, and a failed lookup would block every deploy,
  R1).
- The candidate revision proves the secret: `web()` promotes only when the
  candidate's /sign-in answers 307, so a merge between `map` and `cutover`
  stops before traffic instead of taking sign-in down — rejected: keying
  the gate on doug-api's DOUG_WEB_URL (cutover flips it after the rebuild,
  so cutover's own rebuild would be refused).
- Doug's reads answered on the PR: read 1 (2 fixed, 2 refuted), read 2 of
  54361c2 (see the adjudication comment); the ready click also means Doug
  reads every further push.
Pointers: doug#328 · web/next.config.ts redirects() · web/lib/auth-origin.ts
          RETIRED_HOSTS · web/lib/auth-entry.integration.test.mjs (single-host
          suite) · web/scripts/smoke-subdomain-redirect.sh + its test ·
          .github/workflows/deploy.yml "Confirm the subdomain redirects" ·
          api/deploy/gcp.sh require_apex_mapped · api/deploy/domains.sh ·
          api/tests/test_deploy_gcp.py (both pins) · hq design/one-shell
          (hq#24): docs/cross-repo/one-shell/handoff-d4.md, founder-commands.md,
          roadmap frontdoor-12 (FQ-27/28/29 live there, not on hq main) ·
          env slots at deploy: COLDWORKS_REGISTRY_URL, DOUG_GUARDS_INSTALLATIONS
          (gcp.sh web env), DOUG_WEB_DOMAIN (deploy.yml).

State:    review — PR #316, branch `claude/issue-308-outside-read` off main f1c4731
          (#314 merged; main carries its tip, checked). #308: a finding is
          tagged at emit time with what the read held of its file, and the
          check run says so beside the finding.
Next:     PR #316 open (closes #308); CI, then Andrew reviews. After merge,
          check main carries the branch tip.
          Then #303 (exclude generated content), #304 (same-hunks replay),
          #306 + #199.
Blockers: none.

Decisions this session (2026-09-05):
- Tag at emit time in score_one from the same Coverage the verdict ships
  with (`reader.classify_by_coverage`), carried on Reason.evidence
  off-wire like `file` — rejected: deriving it at render time only (the
  receipt and the ledger would never see it; and the replay path has no
  coverage to derive from).
- Ordering: an outside-read finding sorts after in-read peers of the SAME
  severity, never across a bucket — rejected: a one-grade discount (#232
  option 3), because a file the budget dropped is where a real defect can
  hide, and n=2 is not a measurement.
- A path not in the diff at all is "unread" (that is the #175 shape);
  suffix match both ways so a shortened spelling is not a stranger.
- head-cited stays head-cited: the verify tier read the file at head.
- Persisted only in verdicts.raw (save_review stores rv.findings whole,
  evidence included); the findings table has no evidence column and the
  web receipt does not show the chip (no wire change). Follow-up
  candidates, not done here.
- Mutation restores copy from scratchpad, never `git checkout --`.

Pointers: api/doug/reader.py Coverage.read_of / classify_by_coverage ·
          api/doug/models.py Reason.evidence · api/doug/check_run.py
          _EVIDENCE_CHIPS / _by_severity · api/doug/review.py score_one ·
          tests/test_coverage.py · tests/test_check_run.py · docs/REVIEWING.md

--- prior stream (#302 Langfuse secrets deploy check, MERGED as a7ddcc6) below, preserved ---


State:    review — branch `claude/langfuse-traces-doug-70831b`. Why no
          Langfuse traces: both secrets exist (created 2026-09-04 05:07),
          bound to doug-api-sa, but every CI deploy since printed
          `tracing: off (… not both present)` and the serving revision
          (doug-api-00218-mob) carries no LANGFUSE_* or DOUG_TRACING at all.
          `langfuse_configured` runs `gcloud secrets describe` as
          doug-deployer, which holds no Secret Manager role, and the check
          read PERMISSION_DENIED as "absent". TRACING IS NOW ON: Andrew
          bound viewer on the two secrets by hand, dispatch run 33941891276
          printed `tracing: ON`, and doug-api-00222-rez carries
          DOUG_TRACING=1, both mounts, host, environment=production.
          PR #302 open. Doug's review found the first cut wrong (it aborted
          the deploy on PERMISSION_DENIED, which GCP also returns for an
          absent secret to a principal without project-level get, so a
          fresh project or the delete-to-turn-off path would never deploy
          again). Second cut: the guard is loud but non-blocking (`::error::`
          annotation, tracing off), and the grant is project-level
          roles/secretmanager.viewer in setup-cicd.sh. api 1858 pass,
          `ruff check` clean, both halves red under mutation.
          THEN: still one trace in Langfuse. doug-api logs show every
          export since 03:42 failing `401 Unauthorized`. Both secrets are 9
          bytes: the literal placeholder `pk-lf-...` / `sk-lf-...`, not
          keys (verified: 401 against US and EU hosts, stripped and
          swapped). Nothing from production has ever reached Langfuse; the
          one trace is local. Fourth cut: `tracing._client` runs
          `auth_check` once per process and turns tracing off with a
          `doug: tracing client construction failed: Langfuse rejected the
          keys` line on 401/403; a non-answer keeps it on. Runbook now says
          to curl the pair before storing it and to write the file with
          printf, no trailing newline.
          DONE 2026-09-05 04:18: Andrew stored real keys as version 2 of
          both secrets (42 bytes, Langfuse answers 200), dispatch run
          33944214230 redeployed, doug-api-00226-wuc serving since 04:23.
          PROVEN 2026-09-05 06:08: Doug's review of b9b05a7 (job 2333) is
          Langfuse trace 4bb06610…, env production, session = head SHA,
          tag repo:coldworkshq/doug, root span `review coldworkshq/doug#302`
          with reader.risk, reader.verify x2, reader.intent nested under it,
          token counts matching the `paid read` log lines. No `doug:
          tracing` and no `Failed to export` line on 00226. Verified through
          the public API (GET /api/public/traces/{id}) with the keys read
          from Secret Manager into the shell, never printed.
Next:     Andrew reviews and merges #302, then checks main carries the
          branch tip. Then the project-level grant (agent is blocked from IAM):
            gcloud projects add-iam-policy-binding doug-prod0
              --member=serviceAccount:doug-deployer@doug-prod0.iam.gserviceaccount.com
              --role=roles/secretmanager.viewer --condition=None
          The two per-secret viewer bindings he already made are redundant
          after that and can stay. Then review and merge #302; check main
          carries the branch tip. First traced review: Doug's re-review of
          #302 itself. Look for `doug: tracing client construction failed`
          in doug-api logs; its absence plus a trace in Langfuse tagged
          `production` closes this.
Blockers: project-level grant is founder-run (see Next). #289
          (subprocessor listing and DPA) is still OPEN and says tracing is
          off; it now describes a live state.

Decisions this session (2026-09-04):
- Denied is not absent. `gcloud secrets describe` exits 1 for both, and the
  check collapsed them, so a green deploy silently shipped less than the
  operator configured. Ruling: NOT_FOUND alone resolves to off quietly; any
  other answer deploys with tracing off AND emits a red Actions annotation
  naming the grant. Rejected: abort the deploy (first cut — Doug showed it
  strands bootstrap and the delete path, and ADR-0025 says a merge deploys;
  R1 says production wins over a dashboard); a WARN line in stdout only
  (the state that lost a day); a repo variable as the switch (two facts
  that can disagree, rejected in ADR-0031).
- Viewer is project-level, in setup-cicd.sh with the deployer's other
  roles. Per-secret viewer cannot answer NOT_FOUND for a secret that is not
  there, and it vanishes with the secret. Rejected: per-secret grants in
  gcp.sh setup (first cut).
- Text match on NOT_FOUND stays: it is the gRPC status name, gcloud has no
  other channel, and a miss degrades into the loud branch, not a wrong
  answer.
- Third cut, after Doug's second pass: the probe asks three times (2s apart)
  before the loud branch, because that branch changes what the revision
  carries and one throttled call must not do that; NOT_FOUND is never
  retried. Annotation moved to stderr so a captured stdout cannot eat it.
  ADR-0031 item 4 carries a dated amendment naming the third state and the
  project-level grant. Rejected: an env knob to shorten the sleep for tests
  (4s of test time is cheaper than a test-only switch in the deploy script).
- ADR-0031's "tracing is off in production until the secrets exist" left
  as written: a record, and #289 owns the live state.

Pointers: api/deploy/gcp.sh `langfuse_configured` · api/deploy/setup-cicd.sh
          roles loop · api/tests/test_deploy_gcp.py `GCLOUD_LANGFUSE=
          half|denied`, `test_a_deployer_that_cannot_see…deploys_off…`,
          `test_an_absent_langfuse_secret_is_off_without_an_annotation`,
          `test_the_deployer_can_see_whether_a_secret_exists…` ·
          docs/OPERATIONS.md "Turn it on", "When a trace is missing" ·
          deploy runs 33927066970 (off) and 33941891276 (ON) · #302 · #289

--- prior stream (#301 queue liveness, MERGED as 37c61b5) below, preserved ---

State:    review — branch `claude/queue-liveness-uptime-alerts-1a658e`,
          PR #301 open, merged up to main a8e015f. api 1859 pass, ruff
          clean, four mutation checks red.
Next:     Andrew reviews the PR. Then #261 needs one `/v1/health` read to say
          whether any rows reached the attempts cap during the six days —
          that is what decides whether the recovery was real or the queue
          gave up (#299).
Blockers: none for code. FOUNDER: #294, #289 (both from the prior stream).

Decisions this session (2026-09-04):
- The 6-day queue-liveness alert (2026-08-28T22:09:52Z to 2026-09-04T03:03:21Z)
  was a true positive on the outcome lane, not API death. The service answered
  every poll. Root cause is #270, fixed by f6ea059 and shipped 2026-09-03;
  the first adjudicator run carrying it (2026-09-04T03:00) reported
  `failed_repositories 0` and the next uptime poll was 200, 41 s later.
- `outcome_worker.drain` now prints one stderr line per failed repository,
  carrying REPOSITORY_FAILURE_LOG_TOKEN, the installation/repo key, the
  display name, the rows moved, the attempt against MAX_ATTEMPTS, and the
  redacted error. `failed_repositories` sat at 1 or 2 on every run from
  2026-08-21 and named nothing, which is why the cause took 13 days to find.
  Rejected: adding the log-based metric and policy too — that is the alarm
  question, and it is deferred with the give-up cliff it belongs to.
- Both fail_batch call sites route through `_fail_repository`, pinned by a
  source-level test, because a third site added later would restore the
  silence and every behavioural test would still pass.

Not fixed here, both filed:
- #299 — at MAX_ATTEMPTS a row turns terminally `failed` and leaves the
  overdue set /healthz/queues grades on, so a repository that never recovers
  ends by turning the alert green. #190 is this shape in the review lane.
  Carries the unbuilt alarm on REPOSITORY_FAILURE_LOG_TOKEN.
- #300 — Google's frontend answers the literal path /healthz on run.app with
  its own 404 before the request reaches the container. /Healthz and
  /nope-xyz reach the app. api/README.md:16 documents it as the liveness
  route.

Open question needing the ledger: whether any outcome rows reached the
attempts cap during the six days and were written off rather than settled.
`curl -s -H "X-Doug-Token: $DOUG_OPERATOR_TOKEN" https://<host>/v1/health`.

Pointers: api/doug/outcome_worker.py · api/tests/test_outcome_worker.py ·
          api/doug/outcome_queue.py `_fail_job` · api/doug/api.py
          `healthz_queues` · #261 · #299 · #300 · #272 · #267 · #190 · f6ea059

--- prior stream (#234 fold opener, MERGED as a8e015f) below, preserved ---

State:    MERGED as a8e015f (#292). Was: branch
          `claude/issue-234-status-a71df9`, fixing #234:
          `check_run._oneline` let a raw `<` in model text open a real
          `<details>` that swallowed every finding after it. Fixed with
          `_TAG_OPEN_RE`; `_COMMENT_OPEN_RE` folded into it. api 1845 pass,
          ruff clean, both guard tests red under mutation. GitHub's own
          markdown API renders the defused label as `&lt;` and leaves the
          module's own fold a real `<details>`.
Next:     Andrew reviews and merges the PR, then checks main carries the
          branch tip (squash merges have dropped the last commit before).
Blockers: none.

Decisions this session (2026-09-03):
- Neutralise `<` only where CommonMark can start inline raw HTML: before an
  ASCII letter, `/`, `!` or `?` (open tag, closing tag, comment/declaration,
  processing instruction). Same ruling as `_REF_RE`: scope to what is live,
  not to what looks like prose. `<!--` folds into this rule, so the
  neutralised form becomes `<ZWSP!--` and the three tests pinning `<!-ZWSP-`
  move with it. Rejected: an unconditional `<` (ZWSPs in every `x < y`);
  keeping a separate comment rule (two rules for one token).
- HTML blocks need not be chased: they start at a line start and every
  `_oneline` span sits behind `- `, `> ` or a code span.

Pointers: api/doug/check_run.py `_oneline` · api/tests/test_check_run.py
          `test_oneline_neutralises_the_forms…`,
          `test_a_label_cannot_forge_a_fold_opener` · #234 · #233

--- prior stream (ADR-0033 renumber #295, MERGED as da83679) below, preserved ---

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
