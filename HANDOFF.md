# HANDOFF — doug

State:    building — PR open: check-run findings get file links and a triage
          layout (branch comment-file-links-and-triage). Andrew asked for two
          things off the #227 review comment: links to the file/line of each
          finding, and a condensed attention router. File links: DONE. Line
          links: NOT possible without settling #131 (verify tier is shown no
          diff, so it cannot derive a line; DOUG_VERIFY_INSTALLATIONS empty;
          hunk hashes deliberately drop the @@ header, hunks.py:46-60) —
          filed as #230.
Next:     Andrew reviews/merges the PR (all 6 CI checks green). The merge
          deploys and the first check run after it IS the proof that GitHub
          renders <details> in a check run SUMMARY — the one thing here no
          local test can reach. Prior art says yes: dorny/test-reporter
          posts <details> through the Checks API under the same 65535 cap.
          If it renders literally, revert the two _fold calls; links and
          severity ordering are unaffected. Doug's check on #229 itself is
          the DEPLOYED renderer, so it shows the old shape.
Blockers: none. Doug's own read of 3eb5776 dispositioned in
          docs/reviews/2026-08-27-pr-229-doug-self-review.md: 4 of 5 real
          and fixed/accepted, the ONE high is a false positive (claimed
          _verdict_bundle KeyErrors on r["file"] because the diff shows no
          SELECT change — the query is select(findings), whole-table). Clean
          instance of #175. Round 2 @ 5983ef9: 1 more false positive
          (missing-import; import sys is at worker.py:23) + 1 REAL defect
          Doug found and 11 fold tests missed — an all-low list folded
          itself into an empty ### Findings under a Flagged title. Fixed.
          Both false positives describe states CI ALREADY makes unreachable
          (1,677 tests; ruff F821) → filed #232, sharper form of #175.
          Suites green: api 1677, web 376, console 113, ruff check clean
          (ruff format is NOT a gate — 74 files predate it).
Decisions this session:
- File links are built from THIS module's owner/repo/head_sha with the path
  percent-encoded, NOT validated against PRMetadata.files — rejected the
  closed-set check because the repair path has no file list
  (_verdict_bundle rebuilds a Reason from four columns), so links would
  render on the paid read and vanish from the comment that ADR-0014 says
  reproduces it byte for byte. A rule that holds on one path is worse than
  a weaker rule that holds on both.
- store._verdict_bundle now selects findings.c.file. Safe on the wire
  because every consumer builds a Reason and Reason.file is exclude=True;
  pinned by test_run_detail_reason_carries_exactly_the_keys_the_client_validates.
- Low findings fold behind a <details> that NAMES ITS COUNT; ungraded
  reasons never fold. Rejected a top-N cap: folding by position is a claim
  about importance this module cannot make, and an unlabelled fold is #181's
  defect (dropping findings without saying how many) reached by choice.
- Model text may go in a <details> BODY (parsed as markdown, _oneline
  governs it) and never in a <summary> LINE (raw HTML). _fold takes the
  summary as a separate argument so the rule is enforceable, not remembered.
- Deviation bullets deliberately left in the old shape — separate
  unvalidated section, no file to link. Filed as #231, not left as a PR
  aside.
- Paths carrying a backtick or `]` are no longer linked at all: _path_span
  must drop both, the href used the raw path, so the link would have shown
  one filename and addressed another — rejected: linking anyway and
  accepting the mismatch.
- The <details> risk is ACCEPTED, not resolved. No live check run carrying
  <details> exists to inspect (scanned test-reporter, junit-report,
  publish-unit-test-result-action, 8 large repos). Chain: docs say
  output.summary "Can contain Markdown"; details/summary are on GitHub's
  sanitizer allowlist; dorny/test-reporter ships them through checks.create
  under the same 65535 cap. Downside is cosmetic on the SECONDARY surface
  and reverts in two lines — rejected: writing a synthetic check run with
  production app credentials to prove it (Andrew's call, not mine).
Pointers: PR #229 · branch comment-file-links-and-triage ·
          api/doug/check_run.py (Source, _file_link, _fold, _by_severity,
          _triage, _bullet) · worker._source · store._verdict_bundle ·
          #230 (line links, blocked by #131) · #231 (deviation bullets)

--- prior stream (org move #226/#227, landed ea6d362) below, preserved ---

State:    building — ORG MOVE IN FLIGHT (#226). Repo TRANSFERRED to
          coldworkshq/doug (id 1314318717, redirects live). WIF provider
          condition repointed (coldworkshq/doug && refs/heads/main — ref pin
          was ALREADY live in prod, script text was stale) and the new
          principalSet binding added; the stale drewjst/doug binding remains
          (inert; classifier blocked the remove — Andrew runs the
          one-liner). Slug flip done in links.ts, quickstart, rest-api,
          llms.txt, setup-cicd.sh header; git remote updated.
Next:     Andrew merges the follow-up PR on this branch (migration 17 rename
          backfill + env flip to installation 153075663 + ADR-0017
          amendment). The merge deploys via the repaired WIF — that deploy
          IS the end-to-end proof. Still Andrew's: App ownership transfer
          (UI), App homepage, Claude PR app re-grant on coldworkshq, stale
          WIF binding removal (one-liner in #226).
Blockers: none — webhooks LIVE again: doug added to coldworkshq
          installation 153075663 (delivery d8783110, 202 Accepted in prod
          logs). Suites green: api 1662, web 368, console 113, ruff clean.
Decisions this session:
- RULING 2026-08-26 (Andrew): M4 interviews DEFERRED, not run — nothing is
  public; Doug opens to the public first "so it has a face," then re-raise.
  Kill criterion not retired; it cannot fire while deferred. Consequence:
  the org-move window's "after the interviews" gate dissolves — rejected:
  running interviews pre-launch (no public surface to pitch from).
- RULING 2026-08-26 (Andrew): start the org migration (drewjst/doug + App →
  coldworkshq) now. Verified pre-move facts: deploy.yml still has NO
  environment: gate, setup-cicd.sh:86 pins only assertion.repository (both
  approved fixes UNLANDED); DOUG_INTENT/VERIFY_INSTALLATIONS=150424894 stop
  covering doug at transfer; hardcoded slugs in web/lib/links.ts:5,
  gcp.sh:55 SHOWCASE_REPO, quickstart/rest-api pages, llms.txt.
- The MCP in question is Doug's (memory verbs, Stage 4, ex-lema), not
  coldworks' — coldworks only reads a versioned view as `recovered`.
  Corrected Andrew's "maybe that MCP is coldworks?" with the artifact +
  ruling trail — rejected: treating the coldworks umbrella as owning
  product surfaces.
- Drift filed as issues per AGENTS.md: drewjst/doug#221 (ADR renumbering —
  has drifted TWICE), drewjst/doug#222 (merge design has no in-repo record;
  ADR-0006 unamended), coldworkshq/coldworks#20 (memory-store repo gated on
  Stage-0 paper; home ruled private → own repo 2026-08-25).
- Integration plan written to coldworkshq/coldworks docs/integration-plan.md
  (repo-resident record; artifact a04b895b stays the visual companion) —
  rejected: another artifact-only home, the exact failure mode being fixed.
- The 2026-08-24 pass's build orders copied from /private/tmp scratchpad to
  coldworks docs/build-orders/ with PROVENANCE.md (fleet mechanics
  unapproved; 54 unrepaired script defects) — they would not have survived
  a reboot.
Pointers: coldworks docs/integration-plan.md · docs/build-orders/ ·
          doug#221 #222 · coldworks#20 · artifacts a04b895b, b2942090

--- prior stream (PR #213) below, preserved ---

State:    review — PR #213 open, MERGEABLE, all six CI jobs green. Merged
          origin/main a third time (99f059f, #212);
          HANDOFF.md is the only file that conflicts, and it has now blocked
          CI twice — a CONFLICTING PR has no mergeable ref, so workflows
          never fire and the PR reads "no checks" rather than "blocked".
          Doug read cf7a978:
          Cleared, risk 0.38, 2 medium + 3 low + 2 deviations. All seven
          dispositioned; web 366/366, console 113/113, api 1661/1661.
Next:     Push the findings commit, watch Doug's read of the new head, then
          Andrew reviews PR #213.
Blockers: none

CORRECTED AFTER MERGING #211: the palette shift's one accepted cost — losing
parity with the gh-pages marketing site — does not exist. origin/gh-pages is
now a bare <meta refresh> redirect and renders no palette, so there is no
second surface to disagree with. ADR-0020's Consequences and issue #214 both
updated; #214's recommendation is now REPAINT the mark (two hexes, one file),
since the only remaining objection is that it is also the favicon.

Doug's findings, dispositioned:
- missing-provider-dependency (med) — NOT REAL: app/layout.tsx is the only
  layout above /dashboard and mounts ThemeProvider. The fragility was real
  and untested (next-themes returns a no-op setTheme outside a provider, so
  the row would go dead silently). Pinned; mutation-tested both arms.
- broad-visual-regression (med) — REAL, and it found a bug the first pin
  missed: doug-logo carried #111311/#D1571E, the PREVIOUS palette. The scan
  now WALKS app/ and components/ instead of reading an 11-file list. Mark
  itself is a justified exemption (self-grounded, always worked on dark);
  its rust vs the new accent is issue #214.
- token-contract-change (low) — INVERTED: every bg-[var(--iridescent)] site
  is a solid fill (2px bar, 1px line, a dot) that was BROKEN in dark before.
  The gradient consumers read --brand-wash, still a gradient in dark.
- brittle-regex-assertions (low) — PARTLY VALID: selector regexes now
  whitespace-tolerant, file list replaced by the walk. Source-text pins stay
  (documented house rule, design-system.test.mjs header).
- stale-documented-invariant (low) — VALID, FIXED: now "ΔE2000 9.2 from
  --flag", formula named, in both stylesheets + the assertion. #210 narrowed
  to the durable fix (compute it, stop hardcoding it).
- deviation, ADR-0019 account gear — VALID: ADR-0020 written, both sides
  marked per docs/decisions/README. Theme is NOT on /dashboard/settings
  because that page is per-repository and theme is per-person.
- deviation, RULING 1 unrecorded — VALID: ADR-0020 + an amendment note at
  RULING 1's source in the Phase B plan.

CAUGHT BY api/tests/test_intent.py, worth remembering: ADR-0020 as first
written scored 0.50 on "fix a typo in the footer" (floor 0.25) purely on the
tokens `components`, `tsx`, `fix` — an ADR's own vocabulary decides which PRs
Doug reads it against, so spelling out file paths in a record manufactures
false findings. Rewritten to 0.000 on that probe, 0.857 on a real theme change.

Decisions this session:
- The "hard to read" report is NOT a contrast failure: --muted-foreground was
  already 7.06:1 on #fcfcfa. The faults were (a) help copy set at 10.5px,
  (b) --card vs --background at 1.03:1 and --border at 1.23:1, so items had no
  boundary, (c) the /SETTINGS chip at 3.65:1, genuinely below AA — rejected:
  darkening body text, which would have fixed nothing.
- Phase B RULING 1 AMENDED, not deleted: light stays the default, dark is
  reachable from the rail's account menu. `.dark .dashboard-surface` (0,2,0)
  deliberately beats the light pin (0,1,0) — rejected: a toggle on public
  pages only, which cannot change the page it sits on.
- Neutrals went cool, the accent stayed warm. Warm-on-warm is why nothing
  separated; splitting the temperature buys separation at no contrast cost.
- --iridescent is now a COLOUR in both themes; the gradient moved to
  --brand-wash. .dark used to set it to a linear-gradient, which is invalid in
  all 34 `text-[…]`/`border-[…]`/`color-mix(…)` call sites — every focus ring
  in the console would have silently stopped rendering the moment dark
  reached it. Latent before, load-bearing now.
- The dot grid got --surface-dot. It painted with --border, so raising
  --border for item separation turned the paper texture into noise. Caught in
  the browser, not by a test; now pinned by one.
- --cov-track/--cov-fill/--cov-unread are tokens. The utilities that read them
  are under a character-identical lockstep with console's, so per-theme values
  had to move OUT of that block; console got the identical edit.

Measured (against the surface each renders on):
  --card vs --background   1.03 -> 1.14 : 1
  --border vs --card       1.26 -> 1.64 : 1
  --border vs --background 1.23 -> 1.43 : 1
  --iridescent as text     4.01 -> 5.03 : 1   (was below AA)
  /SETTINGS chip           3.65 -> 5.15 : 1   (was below AA)
  every text pair in BOTH themes now clears AA.

- The ΔE figure was corrected to a measured, formula-named ΔE2000 9.2 in
  both stylesheets and the assertion together — rejected: leaving a spec
  sentence that no formula reproduces, which is how 6.1 survived one palette
  change already. #210 stays open for retiring the hardcoded constant.

Pointers: branch feat/palette-contrast-dark-mode · web/app/globals.css +
          console/app/globals.css · web/components/theme-menu-item.tsx (new) ·
          tests rewritten: dashboard-contract.test.mjs ("light is the
          console's default, and dark is reachable on purpose"),
          design-system.test.mjs (surface values pinned in both themes,
          --iridescent-is-a-colour, one-theme-hex scan, dot-grid coupling) ·
          the #193 branch work is stashed: `git stash list`

---

# ARCHIVE — inherited from main

Everything below arrived on main in HANDOFF.md and is kept because this branch
has no business deleting it. Its State/Next slots are dropped on merge: they
describe whichever branch wrote them, and two status blocks in one file is how
a handoff starts lying. This file conflicts on EVERY merge for exactly that
reason — one mutable slot block, every branch rewriting it — and a conflicted
PR has no mergeable ref, so CI silently does not run and the PR reads "no
checks" rather than "blocked". That has now happened three times on #213.


## #122 SETTLED — the detector's first positive, audited 2026-08-24

**The positive.** PR #68 merged 2026-08-07T20:23:41Z and #70 reverted it the
same day. Its 14-day clock came due 2026-08-21T20:23:41Z and adjudicated
`kind: revert` at 2026-08-22T03:02:21Z, one scheduler pass later.
`GET /v1/prs/68/receipt?repo=drewjst/doug` carries `revert_sha` `bf7a440b`,
`anchor_sha` `99011b78`, `revert_instant` 2026-08-08T00:47:57Z,
`window_starts_at` 2026-08-06T20:23:41Z (the `TOLERANCE_DAYS = 1` lower
bound), `source: git-labels`, `prereg_hash` `c8e30da3…60f2`. Manual `git log`
agrees: `bf7a440` says `This reverts commit 99011b78…` and is the only revert
commit in this repository's history.

**I audited the other direction too, which the issue did not ask for.** A
false positive would discredit the instrument exactly as fast as a false
negative. Every merged PR by receipt — 143 numbers from the GitHub API, NOT
from `main`'s subjects, because that list silently misses merges to other
branches — gives 53 `done` rows, matching the live scoreboard's
`adjudicated: 53` exactly: 50 `clean`, 2 `censored`, 1 `revert`. Nothing else
is labelled `revert`, including #70 itself, which is correctly `clean`. The
two `censored` are #40 and #46, merged to `gh-pages`, `censor_reason:
base_ref` — the `base_ref` censoring item running in production, not in
fixtures. #166's title-fallback collision cannot touch #68: `bf7a440`
attributes by sha, and #68 was never relanded.

**THE PART THAT IS EASY TO MISREAD: this does not move the miss rate.** #68's
governing verdict was **0.34 against a 0.30 threshold — `band: flagged`**.
Prereg §2.1's denominator is `tier='reader' AND band='cleared'`. Doug flagged
the one PR that got reverted, so the first positive sits OUTSIDE the published
denominator. Anyone quoting "the detector's first miss" would be wrong twice
over, because `instrument_snapshot` also hardcodes `miss_rate=None`
(`store.py:2020`) and no surface computes a rate at all yet.

**The M3 gate does not close on this.** One full webhook-started 14-day cycle
is now complete, but "observed" is still not implemented: I verified this
cycle by hand, three days after it closed, which is the same posture that let
the first cycle run dead for two days. #121 stays open and the gate's last
clause stays unmet.

**Evidence for #121, NOT yet posted there — ask Andrew first.** The live
scoreboard read
`first_due: 2026-08-25T03:48:04Z` against `as_of: 2026-08-25T04:47:10Z` — a
`first_due` strictly in the past with work outstanding, which is the exact
contradiction #121 proposes to alert on, occurring while nothing is wrong. The
adjudicator runs daily at 03:00Z, so any clock due after that sits untouched
for up to about 24 hours by design. The check needs a tolerance of at least one
scheduler period, or it fires every day.

## Still unfiled — decision debt, Andrew's call

Raised 2026-08-24 while answering "when do we move doug to coldworks and give
it a public surface", deliberately NOT filed as issues yet because both are
questions for Andrew rather than work:

1. **Publication venue portability — SHARPER after #211.** The prereg names
   `https://drewjst.github.io/doug/publication/` and §12 requires every prior
   version stay published. #211 retired gh-pages to a redirect stub
   (bd67e4a), and checked 2026-08-25: `drewjst.github.io/doug/` answers 200
   while `drewjst.github.io/doug/publication/` answers **404**. Nothing is
   lost — no publication exists yet, the first is provisionally 2027-01-15 —
   but the venue a hashed document names is now a 404 under a retired site,
   and a repo transfer to `coldworkshq` would move that host again. #211 did
   not amend the prereg, and §12 says a venue change needs a new hashed
   version. Decide where the venue lives before the first publication, not
   after.
2. **Series identity across a transfer.** The ledger keys on
   `(installation_id, github_repo_id)`; only `github_repo_id` survives a
   transfer between accounts. Decide which one the published denominator uses
   BEFORE transferring — a ruling made once the split is visible is
   indistinguishable from picking the flattering framing.

---

## Prior slot — docs accuracy sweep (#211, merged 2026-08-25)

State:    review — docs accuracy sweep is a PR against main from branch
          docs/accuracy-sweep (worktree .worktrees/docs-accuracy), 3 commits,
          branch level with origin/main so CI fires. web 363/363, api
          1661/1661, console 113/113, tsc clean, eslint clean (2 pre-existing
          <img> warnings on /about). SHIPPED separately: gh-pages bd67e4a is
          pushed and live — drewjst.github.io/doug is now a redirect to the
          Cloud Run site. That push was the deploy; there is no PR for it.
Next:     Andrew reviews and merges #211. Merging deploys (ADR-0009), so the
          corrected /docs copy goes out with it. Doug already read it —
          Cleared, risk 0.32, 1 medium + 3 low + 2 deviations, ALL SETTLED in
          docs/findings-log.jsonl (4 real, 1 adjacent, 1 disproved) and fixed
          in 94be0d3. Doug will read the new head; expect a second pass.
Blockers: none.

Not fixed, each a judgment call Andrew owns:
- docs/design/competitor-imports/ is named for a concept that died in its own
  grounding phase; the six files inside are all "cited head reads". The new
  lane.md says so rather than renaming, because 3 files outside the folder
  point at the path. Rename is a clean follow-up if wanted.
- ADR-0018 owes a 20-PR cost pilot (~$1) before anyone quotes a per-read cost
  after EFFORT went to high. No issue exists for it; AGENTS.md says there
  should be one.
- docs/design/reader-effort/preregistration.md's header still names ADR-0016
  as its companion; ADR-0018 is what governs. Left as the record of what was
  written then; lane.md carries the correction.

Decisions this session:
- Verified every number against code or the live API, never against another
  doc — the two hosted surfaces already disagreed, so doc-vs-doc agreement
  proves nothing — rejected: trusting the surface that looked freshest.
- Retired gh-pages instead of rewriting it (Andrew's call) — repairing keeps
  two copies of every claim, which is the mechanism that produced the drift —
  rejected: fixing the ~9 false claims in place.
- The docs copy states a DATED SNAPSHOT and names the command that prints
  today's figure, and the pins check growth-invariants instead of exact counts
  — an exact derived pin fails on every settle forever, so the copy becomes a
  chore on unrelated PRs and the first person in a hurry deletes the pin rather
  than the staleness (Doug's medium on #211, real). Verified: a prospective
  append stays green, a backfill append fails — rejected: the exact derived
  pin, and rejected: computing at render time, which .dockerignore forbids
  (/docs is not in the web image's build context).
- The rest-api sample shows field placeholders, not live counters — printing
  53/179 and a frozen timestamp reintroduced the exact drift class this PR
  removes, my own regression, caught by Doug (reader:docs-sample-drift) —
  rejected: real values with a "counters move" caveat under them.
- HANDOFF.md was NOT touched in the main checkout: a concurrent session owns
  it there (feat/palette-contrast-dark-mode). This slot lives on the docs
  branch only, so it will conflict on merge — drop this commit if that is not
  worth it — rejected: editing the file another session is mid-write on.
- gh-pages went out as a direct push, not a PR — it is a separate branch with
  no CI, no reviewer and no deploy pipeline, and the push IS the publish;
  a PR would have added a review surface for nobody — rejected: routing a
  static-site retirement through main.
Pointers: branch docs/accuracy-sweep @ bd5886b · branch gh-pages @ bd67e4a ·
          web/app/docs/*, web/public/llms.txt, web/lib/public-surface.test.mjs ·
          api/README.md · docs/REVIEWING.md (#186 conflict marker, closed) ·
          docs/design/{walked-out,competitor-imports,reader-effort}/lane.md ·
          live API https://doug-api-g7rm4l4e3q-uc.a.run.app

---

## Prior slot — PR #202 (#154)


State:    review — PR #202 (fixes #154) open against main, four commits,
          rebased onto 7cb45ec (#200). Doug read it three times — 8dc74d0
          (6 findings), 1db64a3 (5 + 3 deviations), b008221 (5 + 2). All
          settled. 1658 tests pass, ruff clean.

Next:     Force-push the rebase; watch Doug's read of the new head. Then
          Andrew reviews and merges.

Blockers: none.

## What #154 was

`worker._post_pr_comment` ran after `ingest.complete` marked the job 'done';
`ingest.REVIVABLE` is ('failed', 'superseded'); the next delivery for that SHA
collides on `uq_review_job`. A comment lost to a process death or a 5xx was
lost until somebody pushed. Since ADR-0014 the comment is the surface GitHub
actually shows (neutral checks stay folded), so that was a lost review, not a
missing badge. Fixed by recording what every comment write did and sweeping
the ones that never landed at the end of each `drain`.

## The shape it arrived at, after three reads

- `ingest.complete` stamps `store.PR_COMMENT_OWED` in the SAME statement that
  marks the job done. The sweep selects on that POSITIVE marker.
- It started as "NULL means never posted", which needed a full-table UPDATE in
  migration 016 to disambiguate, and swept every job an older instance
  finished mid-rollout. Both went away with the marker. Migration 016 now
  rewrites nothing.
- `store.claim_pr_comment_retry` reserves a row before any GitHub call, in one
  conditional UPDATE that also spends the repair budget, answered by RETURNING
  the way `ingest.claim` answers its own.
- `worker.retry_unposted_comments` repairs the COMMENT ALONE. Re-pending the
  job would reach it through `_replay_recorded`, which also calls
  `check_run.post` (= `checks.create`) — a second check run on the commit
  every time.
- Bounds: 2 repairs, 300s settled, 24h lookback, 20 per pass.

## Doug's six reads, dispositioned

Read 1 (8dc74d0) — 5 real, all fixed: race-condition (unlocked SELECT, both
instances sweep the same rows every pass), unbounded-retry, error-handling-gap,
index-mismatch ((status, pr_comment_outcome) -> (status, finished_at)),
api-contract-change (token vocabulary now pinned by a parametrized test).
1 disproved: a rollout-overlap row past `pr_comment._PAGE_BOUND` cannot create
a duplicate — that branch RETURNS `failed:page-bound` and its own comment says
neither a long PR nor a broken listing may fall through.

Read 2 (1db64a3) — 3 real, all fixed: driver-rowcount-portability (rowcount is
a property of the DRIVER and no CI job runs Postgres; a matched-not-changed
driver would hand BOTH sweepers the claim — switched to RETURNING),
state-overwrite-on-error (moving the post inside the try created the mirror
defect: a raise past it overwrote a landed outcome with the RETRIABLE
`failed:internal`), row-shape-coupling (the docstring claimed `ingest.claim`'s
shape; `claim` adds a bumped `claim_generation`). 1 disproved:
duplicate-side-effect — created-but-unrecorded leaves `failed:internal`, the
retry's listing finds the comment by its own marker and this App's authorship
and edits in place. 1 deferred: #203. 1 deviation REAL — I deleted this file's
archive, which it already records losing twice. Restored; memory saved as
`handoff-archive-is-not-ephemeral`.

Read 3 (b008221) — 3 real, all fixed: unsafe-migration (the full-table
backfill; deleted by the owed marker), error-handling-gap (`_post_pr_comment`
now records BEFORE it logs — the old order bought nothing, since that write
swallows and logs its own failure, and cost a retry budget to an f-string
raise between them), silent-truncation (now loud; and truncation cannot flip
the classification, because that reads a prefix). 1 already tracked (#203).
1 NOT fixed and now said plainly instead of overclaimed: the settle period
NARROWS the slow-first-worker window, it does not close it. Time is a
heuristic for liveness, not a fence. What remains is `pr_comment.upsert`'s own
priced trade — its listing falls through to create rather than leave a comment
that never appears — and a real fence would have to be held by the original
writer.

Read 4 (691371b) — 3 real, all fixed: invariant-depends-on-caller (the owed
marker was stamped by `ingest.complete` unconditionally, so any future
completion path that does not attempt a comment would leave a marker the sweep
acts on — now `owes_comment`, defaulting to False, so a caller that forgets
loses a repair rather than writing to a live PR); doc-code-mismatch (three
docstrings still described the NULL-means-never-posted rule the marker
replaced, and one still cited a backfill the migration no longer has);
duplicate-side-effect (not closable, but the settle window went 300s -> 900s,
which is `ingest.STALL_LEASE_SECONDS` — this codebase has already decided how
long a worker may be silent before it is presumed dead, and answering that
twice with two numbers means one is wrong). Deviation REAL: ADR-0014's D10
said `NULL` was retriable in one sentence and unselectable in the next — the
exact rule that decides whether a repair can duplicate a live comment. D10 is
rewritten. Repeats already tracked: #204 (index lock), #203 (client mints),
#201 (dark exhausted state).

Read 5 (cf76a89, FLAGGED 0.40 — at the line, not over it) — 2 real, both
fixed, plus one deviation. ddl-column-mismatch is the one worth reading: the
review_jobs stub I added to the version-9-gap test had no `finished_at`, so
migration 16's CREATE INDEX failed, `_satisfied` swallowed it as "no such
column", and the migration RECORDED ITSELF AS APPLIED with no index built.
Verified by hand: `applied: [16]`, `indexes on review_jobs: []`. Fixture
fixed and the test now asserts the index exists, not just the version row.
I tried narrowing `_satisfied` so only DROP COLUMN may shrug at a missing
column and REVERTED IT: five migration tests fail, including migration 007's
`uq_outcomes_job_identity` — a UNIQUE index relying on the same swallow. That
is repo-wide and pre-existing, so it is issue #205 (with the evidence and the
"check whether the index actually exists in production" clause), not a
passenger in a comment-retry PR. logic-edge-case also real: `owes_comment` is
now `verdict_id is not None`, because the marker promises a repair and a
repair renders from the durable verdict. Deviation REAL: the residual
paragraph still said "A NULL outcome means no write recorded" — the SAME
contradiction D10 was rewritten for, surviving in the paragraph below it.
Fixed. Repeats: #204, #203, #201, and invariant-depends-on-caller now flagged
in the OPPOSITE direction from read 4 (low, not medium) — that is the
expected shape of choosing a fail-direction, and the choice is in the ADR's
rejected list.

Read 6 (48aeb90, cleared 0.36) — CONVERGED. 1 real, fixed:
invariant-depends-on-caller, now framed as "every path out of
_post_pr_comment must clear the marker". True, and it was a convention. The
record + log moved into `_record_and_log`, called from a `finally`, so the
next early return added inside that try cannot break it silently.
1 disproved: schema-metadata-drift — migrations.py's own docstring says
indexes live in migrations and NOT on Table definitions, precisely to avoid
create_all-only drift, and `migrations.apply(engine)` runs inside
`store._get_engine()` (store.py:736), so every create_all environment applies
them. Every other index in the file follows the same rule.
1 half-correction: the ALTER ... ADD COLUMN NOT NULL DEFAULT 0 named in
unsafe-migration does NOT rewrite the table — non-rewriting defaults landed in
Postgres 11 and gcp.sh provisions POSTGRES_18. The CREATE INDEX half stays
#204. The other three findings and the deviation are all priced residuals or
tracked issues repeating.

STOPPING POINT: reads 5 and 6 produced no new class of defect — only repeats
of #201/#203/#204/#205 and the two priced residuals (the time-based liveness
heuristic, the ADR amendment riding along with the code). Further rounds
would be re-reading the same trade-offs.

CI GREEN on cf76a89: api, web, console and all three images.

CI GREEN on 691371b: api, web, console and all three images. The web suite ran
there rather than locally — this worktree has no node_modules — and the diff
touches no web files.

Deferred, with issues (AGENTS.md): #201 (a comment that exhausts its repairs
goes dark, the shape D8 refuses), #203 (drain mints an installation client per
job — the sweep matches what the claim loop beside it already does, so fixing
one alone leaves the worker inconsistent), #204 (the non-concurrent CREATE
INDEX in a startup migration). All three numbers are written next to the thing
they describe so they cannot drift.

Pointers: PR https://github.com/drewjst/doug/pull/202 · #201, #203, #204
          api/doug/ingest.py `complete` (stamps the marker)
          api/doug/store.py `PR_COMMENT_OWED`, `_pr_comment_unlanded`,
          `claim_pr_comment_retry`, `record_pr_comment_outcome`
          api/doug/worker.py `retry_unposted_comments`, `_render_recorded`
          api/doug/migrations.py migration 16
          api/tests/test_worker.py — PR_COMMENT_TOKENS and the tail block

---

## Prior stream — #176 / PR #200: the refused-authority 403 (2026-08-25)

Kept verbatim, per the convention this file adopted in #155: newest slot block
on top, everything superseded below rather than dropped.

State:    review — #176 fixed on claude/issue-176-verification-3f44bb.
          Full suite green: 1620 pytest, 361 web, console clean. tsc clean,
          lint clean (2 pre-existing <img> warnings in about/page.tsx).
Next:     Open the PR against main and let Andrew review it.
Blockers: none.

## #176 — verified, then fixed

VERIFIED FIRST, and the loop is real. `/install/callback` answers the API's 404
with a 403 whose only action linked to `/install/callback?reauth=github`; that
handler verified the flow cookie and re-signed the reader in through WorkOS with
`prompt: "consent"`, returnTo `/install/callback`. Per #167 (production,
2026-08-21, recorded in docs/OPERATIONS.md) WorkOS honours that parameter itself
and never forwards it, and GitHub accepts only `prompt=select_account`. The flow
cookie survives the round trip, so the reader came back with the same session,
the same WorkOS `sub`, the same 404, and the same page offering the same link.

WHAT MAKES IT UNFIXABLE BY RE-AUTH, not just badly parameterised: the 404 comes
from `api._prove_installer`, and every one of its arms is immune to a refreshed
session — a legacy row whose `installed_by_github_user_id` is NULL, a WorkOS user
with no GitHub identity at all, or a GitHub id that is not the installer's. The
last would need account switching AT GITHUB, which is exactly what the missing
`select_account` would have done. So option A in the issue (make the remedy
work) cannot close it; option B is the only honest one.

WHY IT SHIPPED: the test at install-flow.test.mjs stubbed the SECOND bind call
to 204, manufacturing a success the deployed path could not produce. That test
is gone. Its replacement holds the API at 404 for every call and then FOLLOWS
the links the page offers.

Changed:
- The 403 body names the condition, the one remedy that can change the answer
  (sign out, sign in to GitHub as the installing account, connect again), and
  the case where nothing the reader does will help — with a link to the issues
  page rather than a dead end. It does not assert WHICH of the three causes it
  is, because the API returns one 404 for all three on purpose.
- The `reauth=github` arm is deleted. A stale bookmark now falls through to the
  normal path and retries the bind, spending no WorkOS round trip.
- `setup_action=update` keeps `prompt: "consent"` (it only needs to land the
  reader on /dashboard) but now carries the #167 measurement as a comment, so
  the parameter cannot be read as working and copied into a remedy again.
- node-next-loader.mjs: one rule for the whole `@/lib/*` alias. The three
  hand-written entries had drifted into two shapes, two of them resolving
  against the IMPORTER and only correct at three segments deep.

Four mutations verified, each fails exactly one pin: re-adding the self-link,
dropping the sign-out remedy, stripping every link from the body, and restoring
the `reauth=github` arm.

NOT DONE, and deliberately: #167 stays OPEN. Its step 4 — the `maxAge: 0`
variant — has never been run and needs a deploy, so its Done-when is not met
even though the bug it predicted is now closed. #169 (receipt page's
unauthorized arm) is a different surface and untouched.

NOT VERIFIED: I did not reproduce the loop in production. The mechanism is
#167's production evidence plus a read of both code paths, and the fix is
pinned by tests, not by a production round trip.

## Review round 1 — Doug on 6293571, plus /code-review low

Doug: Cleared, risk 0.22, 4 low findings + 1 unvalidated deviation.
/code-review low found 2, both overlapping Doug's. Settled: 2 real+changed,
2 disproved with evidence, 1 half-real, 1 deviation accepted as a judgment call.

REAL, changed:
- The `@/lib/*` rule appended `.ts` UNCONDITIONALLY, which contradicts the
  extensionless-ONLY rule the same function states twenty lines later. Its
  reason is identical: `@/lib/queue-fixture.json` would report
  `queue-fixture.json.ts` missing and mask the real error. Now resolves a
  specifier that names its extension exactly as written, and there is a new
  lib/node-next-loader.test.mjs holding it.
- The 403's remedy was an UNCONDITIONAL instruction, while the block comment
  above it said the page cannot tell which of three causes it is. Rewritten so
  the goal precedes the instruction, one instruction covers both fixable causes
  (signing in to GitHub as the installing account fixes the wrong-account and
  the no-GitHub-identity cases alike), and the third is named by a trigger the
  READER can check — you did it and this page came back — instead of a claim
  about who they are, which this page cannot make.

DISPROVED with evidence:
- `removed-route-branch`: a stale ?reauth=github with an absent or expired
  cookie is said to now get the generic invalid-flow response "rather than a
  re-auth". The DELETED branch returned `invalidFlow()` on exactly that
  condition (its own lines 88-92). Behaviour is identical. And a repo-wide grep
  finds no link, doc, or template pointing at the path outside the comments
  describing its removal.
- `missing-import-verification`: the exports exist and `tsc --noEmit` is green,
  which is what proves it. The half worth acting on was the untested link, so
  the 403 test now imports GITHUB_REPO_URL from lib/links.ts and pins the
  rendered href against it — a rename fails the test, not production.
- The `.tsx` / directory-index half of the alias finding: every `@/lib/*`
  import in the tree resolves to a flat `.ts` sibling, and the resolver
  fallback Doug supposed "might have worked" cannot — `@/` is not a real
  package, so it always threw. That is how #176's own import failed.

DEVIATION `beyond-ticket`, accepted: rewriting three loader entries into one
IS wider than adding a fourth line. The ticket forced a loader change either
way, the file is test-only, and two of the three entries were wrong in a way a
fourth would have copied. Recorded here rather than in an ADR: an ADR for a
test-runner resolve hook would be the first of its kind in docs/decisions.

Nine mutations verified across both rounds, each failing exactly one pin.

Pointers: branch claude/issue-176-verification-3f44bb ·
          web/app/install/callback/route.ts (the 403 body, the deleted arm,
          the update-arm comment) · web/lib/install-flow.test.mjs (two new
          tests replacing one) · web/lib/node-next-loader.mjs ·
          docs/OPERATIONS.md:295-320 is where #167's answer lives ·
          api/doug/api.py `_prove_installer` is the 404's source

## Prior stream — #198, per-repo deep read (kept, still open against main)

State:    review — #198 open against main, carrying the stranded #195 work
          plus Andrew's three UI follow-ups. Doug reviewed cd3f2fd: 7 findings,
          all settled (3 real+changed, 4 disproved).
          Real: an orphaned unclosed docblock in the rail (my line-range
          extraction overran a boundary — swept the other three touched files,
          clean); the fail-open deep_read default also costs SPEND, not just
          silence, because deep reads are metered — added to ADR-0019; and
          ADR-0019 said nothing about the rail while the code comment it
          shipped with said "Deliberately NOT a rail-and-ledger shell", which
          this PR reverses. The rail, the rejected route-segment layout, and
          the reversal are now all in the record.
          Disproved with evidence: the exact() rollback window is already #197;
          migrations.apply() runs inside _get_engine() under the engine lock,
          so no API instance can SELECT deep_read before migration 15 ran in
          its own process; lint (no-unused-vars) was already green and
          signOutAction is still used at page.tsx:1138 and :1255; the threshold
          shift is the most-documented behaviour in the PR.

          I REPEATED A MISTAKE I HAD ALREADY WRITTEN DOWN: citing web file
          paths in an ADR. `components/dashboard-rail.tsx` and `layout.tsx`
          tokenise to {components, dashboard, tsx, layout} and pulled ADR-0019
          into "Fix a typo in the footer" again —
          test_selection_on_dougs_own_records caught it a second time. RULE:
          in any ADR, name the COMPONENT, never its path.
Blockers: none.

SEEN, not just tested: /dashboard/settings was rendered through a temporary
harness route (deleted, tree clean) against fixture data, because the real
page needs WorkOS auth + the API and has no fixture mode. That look caught two
real defects, both fixed in 8acd9eb — the flat panel gave three settings no
grouping, and a repo already set to deep-read-off was told what turning it off
"would" do to its band. Verified across all three states. What the harness
CANNOT show: the real page under real auth, an installation with many repos,
and the redirect arms.

Known and deliberately not fixed: three paragraphs per repository is a lot of
page at forty repositories. Thinning it by splitting the copy between the page
and the control would put the same forward-only promise in two files, which is
what FlagLineControl's one-component design exists to refuse.

PR 2, as built:
- installation_repos.deep_read, NOT NULL DEFAULT TRUE (migration 15). TRUE is
  the only honest backfill: every repo that existed before the column WAS read
  whenever DOUG_READER was on.
- NARROWS ONLY. review.score_one gates on `reader.enabled() and deep_read`.
- read_intent takes the SAME gate. A repo that turned the LLM off turned off
  the LLM, not one of the two things Doug asks it.
- Off gets its own verdict rule, `deep-read-off`, distinct from
  reader-unavailable (a fault) and reader-capped (a budget).
- store.repo_deep_read defaults a MISSING row to True — the opposite of
  repo_pr_comment, argued in ADR-0019: resolving that fault towards "off" here
  silently downgrades the verdict AND moves the band, with nothing on the
  check run saying why.
- All three settings writes revalidate BOTH surfaces.
- Doug's own intent selector caught a real defect in ADR-0019 before it
  shipped: citing `web/components/*.tsx` tokenises to {web, components, tsx}
  and pulled the record into "Fix a typo in the footer"
  (test_selection_on_dougs_own_records). Fixed by naming the components, not
  their paths. Worth remembering for any future ADR that cites a web file.

Plan — the settings page (decided):
Plan — the settings page (decided):
Plan — the settings page (decided):
Plan — the settings page (decided, not yet built):
- TWO PRs, mandatory, not a preference. deploy.yml:162 promotes API before
  web, and session-api.ts's `exact()` guards reject a body with an unknown
  key — so the API emitting `deep_read` before web tolerates it would break
  every dashboard with "Doug could not load your connected spaces". Same
  sequence ADR-0013 used and session-api.ts:196 documents.
- THE FLAG-LINE CELL STAYS on the repositories table. ADR-0013's reason for
  putting it there (page.tsx:886 — read the line beside the "needs you"
  count) still holds, and a settings page does not have that count. The
  amendment is "both places, one API", not "moved".
- The header link is a STATIC "Dashboard" link, not auth-aware. Making
  SiteHeader call withAuth() would turn /, /docs, /queue, /scoreboard,
  /about dynamic to change one word. Signed out, the link still works —
  proxy.ts redirects /dashboard to AuthKit.
- DEEP READ NARROWS ONLY. `reader.enabled()` (DOUG_READER=1) stays the
  master switch and the spend control; the per-repo flag can only turn a
  deep read OFF, never on. Composition is `reader.enabled() and deep_read`.
- Turning it off MOVES THE LINE, and the copy has to say so: an unset repo
  scores at 0.30 on a deep read and 0.62 on the fallback, so opting out of
  the read silently re-bands the repo unless a flag line is also set.
- read_intent (review.py:473) gets the same gate. A repo opted out of LLM
  reads must not still get an LLM intent read.
- Consequences that are correct and must not be "fixed": tier records as
  deterministic, coverage is null, and the repositories table's "read"
  column shows an em dash for that repo.

Decisions this session:
- The 1620 dock stop stays at 400 — measured, a 440 dock leaves the title
  column ~148px there vs ~188px, which buys dock prose with the master
  column's ability to name a row — rejected: widening all three stops.
- Only --dim and --rule-soft were retuned, not the whole palette — --dim at
  2.3:1 was painting the smallest text on the page; --rule-soft is capped by
  --border (1.22:1) so row separation came from height (34→38px) instead —
  rejected: darker dividers, zebra striping.
- design-system.test.mjs pin MOVED to the new hex rather than loosened — the
  A5.6 ruling forbids substituting a palette neighbour, not correcting a value
  that fails to be legible — rejected: a range assertion.
- Verified against a static 2000px mock served over localhost, not the real
  dashboard — /dashboard needs WorkOS auth + the API and has no fixture mode —
  rejected: standing up auth locally for a CSS change.
- PR #193's first push ran NO CI: the branch came off a stale local main (3
  behind origin) and conflicted on HANDOFF.md, and GitHub cannot build the
  merge ref for a CONFLICTING pr, so `pull_request` workflows never fire. The
  only check was Doug's own, reporting `skipping`. A checks-empty PR page is
  the symptom to watch for — rejected: reading the silence as "nothing to run".
- Updated the branch by MERGING origin/main, not rebasing — the force-push a
  rebase needs was blocked by the permission classifier, and the merged tree
  was verified byte-identical to the rebased one before pushing — rejected:
  asking for force-push rights for a change that did not need history rewritten.
- REVERSED: the HANDOFF.md trim was NOT safe and is no longer in this PR.
  workspace/handoff-archive-2026-08-23.md is outside the repo and untracked, so
  the diff proved a copy exists on one machine, not that the text survives in
  the repo — which is the only thing AGENTS.md's rule is about. Doug's medium
  (reader:documentation-loss) caught it and cited the file's own line 292
  recording the same drop being reverted once before. HANDOFF.md is now +55/-0,
  newest slots on top, prior stream verbatim below — rejected: the trim.
- Outcome cells stayed at 11.5px while the rest of the row grew — MEASURED,
  `○ censored` sets 72.3px at 12px against 72px of column, i.e. it truncates.
  Doug's reader:fixed-width-overflow (low) was right; the COLUMNS widths were
  measured against 11.5px text and nothing re-measured them — rejected: bumping
  the type without widening the column, which would raise the 876px floor.
Pointers: PR #193 · branch feat/wider-dock-legible-ledger, merged up to
          origin/main @ a309395 ·
          web/app/dashboard/page.tsx (dock grid ~line 1600, COLUMNS, TD/TH) ·
          web/app/globals.css (.dashboard-surface tokens) ·
          mock + screenshots in the session scratchpad (mock.py, before.html,
          after.html, ledger-before.jpg, ledger-after.jpg)
          NOTE: a stash holds the PR #188 branch's uncommitted HANDOFF.md trim
          ("pr188 handoff trim"), backed up at scratchpad/HANDOFF-pr188-backup.md

---

## Prior stream — through PR #187 (2026-08-23)

Kept verbatim, per the convention this file adopted in #155: newest slot block
on top, everything superseded below rather than dropped. It was dropped once
before and restored, because it carries decision debt ("Decision debt —
Andrew's call, blocks the scoreboard spec", below) that AGENTS.md says must not
live only in a transcript. A copy also sits at
workspace/handoff-archive-2026-08-23.md, but that path is OUTSIDE this
repository and untracked, so it is not a substitute for keeping the text here.

RANKING ITEM #1 WAS ALREADY BUILT. Carry-forward shipped in Walked Out v1
(#164, merged 2026-08-21): convergence.classify carries a finding forward by
construction on a byte-unchanged hunk delta, store.convergence_for pairs the
verdicts, and worker.process_job passes it to check_run.render at BOTH call
sites (:228 fresh, :473 replay) where _since_section renders `### Since
<sha12>`. 44 tests green. My evidence for ranking it #1 — 28 re-raises in
findings-log.jsonl — comes from a log ending 2026-08-20, ONE DAY before the
fix merged. I ranked a solved problem first and called it unproposed.
THE REAL REMAINING GAP: convergence carries DOUG's own findings across reads.
It has no notion of a HUMAN disposition. findings_log.py is a CLI/reporting
tool that nothing in api/doug imports; the dispositions live in a hand-written
JSONL nobody reads at review time. And the Since section ANNOTATES, it never
suppresses — Andrew's 2026-08-20 ruling (no resolved state, ever). That
ruling's reason is that Doug must not infer resolution from its own silence.
A human disposition is evidence, not inference, so the ruling as stated does
not cover it. Worth Andrew's call.

State:    review — PR #185 open (remove the PR-comment allowlist), rebased
          onto main @ d6dd0eb and conflict-free. Doug's own findings on it
          are verified and fixed; dispositions in docs/findings-log.jsonl.
Next:     Andrew merges #185. On deploy, four repos start commenting for the
          first time (coldworks, lema, lema-mcp, lema-verify) — watch for
          `denied:403`, which means that installation has not re-accepted
          `Pull requests: Read and write` (ADR-0014 D5); it shows as a banner
          on the Repositories view. Separately, #157's blocking check is still
          open: confirm a GitHub alert renders inside a CHECK RUN summary.
Blockers: none.
Decisions this session:
- Rebase conflict with #184 resolved by keeping DOUG_VERIFY_INSTALLATIONS and dropping DOUG_PR_COMMENT_INSTALLATIONS — the two changes edit the same --set-env-vars line for unrelated reasons. Also fixed a stale cross-reference the text merge could not see: #184's comment said 150424894 is "the same dogfood installation the two allowlists above name", and after #144 there is one
- HANDOFF.md conflicts resolved to main's copy rather than merged half-by-half — the file is ephemeral session state by design (AGENTS.md), so merging two stale halves manufactures a third wrong version. This is the second HANDOFF conflict this branch produced; the first shipped markers into ff8019f
- Doug's `reader:observability-gap` fixed here rather than deferred (closes #173): this PR is what makes the gap bite, on four repos at once. `skipped` became skipped:off | skipped:no-active-row | skipped:no-ledger
- `reader:deploy-config-drift` disproved: a Cloud Run revision pins image and env together, so a rollback restores the gate and its reader as one — there is no revision where the variable is set and unread
- Filed #186: docs/REVIEWING.md:716 carries a committed conflict marker on main, from 525f733, plus a proposal for the CI grep that would have caught both instances

State:    building — reader accuracy/cost work on branch
          claude/doug-pr-review-accuracy-232a1f. Suite green (1600), ruff
          clean. One code change landed, one doc written, one costed.
Issues opened 2026-08-23: #178 (Cloud Run timeout vs retried read), #179
(ground_findings charges before the call), #180 (additive assertion compares
slugs), #181 (SUMMARY_LIMIT drops findings unnamed), #182 (.json under docs/
ranks tier 0), #183 (design-lock L1 rationale is stale).

DOUG_VERIFY IS ON, as an allowlist. Converted verify_enabled() ->
verify_enabled_for(installation_id) + DOUG_VERIFY_INSTALLATIONS=150424894,
matching intent.enabled_for and pr_comment.allowed. Reason: design-lock.md:64
records DOUG_INTENT=1 shipping as a process-wide switch that enabled an
experimental tier for every installation, "harmless only because there has
only ever been one installation." A boolean would repeat it. Two mutations
verified. Known limit at switch-on: VERIFY_SCHEMA's predicate enum holds
exactly one check (constant_value_is), so most findings will abstain.
MERGING THIS DEPLOYS IT (ADR-0009).

Next:     Andrew reads docs/design/reader-effort/preregistration.md and
          decides whether to fund the EFFORT run (~$5 of API, ~1 day of
          blind dispositioning). Open the four issues listed below.
Blockers: none. The EFFORT change cannot ship without the pre-registered
          run — EFFORT is one of ADR-0012's five frozen constants.

Decisions this session:
- Verify + attribution moved to claude-sonnet-5 via a NEW constant pair
  (MECHANICAL_MODEL / MECHANICAL_EFFORT), not by editing MODEL — why: the
  freeze binds the risk read's instrument, and neither pass was in the
  probe. Both validate their output in code before it reaches a stored
  row, so a weaker model costs an abstention, never a wrong row. rejected:
  editing MODEL (breaks test_reader_and_probe_share_the_validated_prompt_bytes
  and silently re-anchors the risk read); haiku-4.5 (Andrew chose sonnet).
- _report_cost takes `model` as a parameter now — why: it interpolated the
  MODEL constant, which was correct only while one model served every
  call. Its own docstring warned about exactly this split. Three mutations
  verified, including the silent one (Sonnet sent, Opus reported).
- Settlement pass RECOSTED after agent verification. My first design — ask
  the model "does the full file at head disprove this?" and drop on yes —
  is exactly what design-lock L1 already kills, with a measured
  counterexample (PR #107: the refuter quoted models.py:133, the quote was
  true and byte-matched, and the conclusion was still wrong). The locked
  design is a closed predicate vocabulary: the model supplies
  {file,line_start,line_end,quoted_text,predicate} and CODE runs the
  predicate. VERIFY_SCHEMA ships enum ["constant_value_is"] — ONE of the
  five the design names. Widening the enum is free; the cost driver is
  MAX_VERIFY_READS_PER_REVIEW (2 today). At cap 6 on sonnet-5 that is
  $0.058/review, +78% on the risk read. Two of the five predicates already
  exist as code in settle.py and are reachable only via hardcoded slug
  matching, not the verify channel.
- EFFORT run is pre-registered against docs/findings-log.jsonl (153
  findings / 27 PRs), NOT a re-run of the 653-PR AUC probe — why: ADR-0012
  already declined that on cost for the analogous DIFF_BUDGET change, and
  the question is about finding precision, not revert-prediction AUC.
  Power stated before the run: n=153 detects only 32.0% -> 19.6% or better.

Three settled decisions re-opened (Andrew: "don't treat settled as never
re-open"). Each tested by whether its REASON still holds:
- design-lock L1 (kills `refuted: bool`) rests on "ReaderFinding carries no
  line numbers, so the refuter picks its own target with nothing to check it
  against." L1 is dated 2026-08-18; ADR-0015 shipped hunk attribution
  2026-08-20 and #164 merged 2026-08-21. PREMISE IS STALE — but not yet in
  practice: `hunks` lives on Reason, not ReaderFinding, and attribution runs
  AFTER grounding in score_one. The repair is an ORDERING change (attribute,
  then verify against the named hunk), not a schema change. L1's conclusion
  survives; its reason needs amending.
- ADR-0012's "re-running the 653-PR probe costs real money. Declined
  (2026-08-06)" DOES NOT SURVIVE ARITHMETIC. llm_probe.py:250 already submits
  through client.messages.batches.create, so the 50% batch discount was
  already in force. Full two-repo replication (520 reads) at high effort is
  ~$24 batched. Pre-registration amended: AUC replication is now the PRIMARY
  arm, findings-log is secondary.
- ADR-0012's coverage bar (30/30, 100% code whole) is measured on a window
  ending 135c8e5, 2026-08-06 — 17 days stale. Re-ran the same zero-model-call
  measurement on the latest 30 first-parent commits: 29/30 (96.7%) after
  discounting a classifier artifact, versus 30/30 pinned. Still above the 95%
  bar, by one commit instead of five. Pressure indicators doubled: PRs over
  the 100k budget 13% -> 27%, p90 diff 114,604 -> 205,002 chars, max 276,775
  -> 429,126. One real code-tier loss: web/app/dashboard/page.tsx at 8e1d774
  (176,819 chars) — the SAME file PR #114's read was cut inside.
- CLASSIFIER DEFECT found by that run: `.json` is not in
  features._PROSE_SUFFIXES, so docs/design/walked-out/*.json data fixtures
  rank TIER 0 and compete with real source for the budget. Two of them are
  what "failed" commit 6fa1633.

Corrected by the impact pass — numbers I had wrong:
- findings-log.jsonl CANNOT record a miss (all 153 rows are layer=doug and
  presuppose an emitted finding). Every recall claim rests on 11 external
  findings across PR #106 and #114, which are NOT in the log.
- Only 14 of 49 disproved findings are settleable by fetching the file the
  finding names; 3 are already handled. Incremental core is 7 of 49 (14%),
  not "nearly every disproved finding" as I first read it.
- Split-read for truncation is near-worthless at the current budget: 100%
  of code sent whole on ADR-0012's pinned 30-commit sample, and only 2 of
  26 logged PRs lose any code tier at 100k. It also costs 1.92x reads on
  the real corpus and multiplies a process with a measured 75% silence rate
  between reads of byte-identical content.
- The dominant miss class is files ABSENT from the PR entirely (4 of 8 on
  PR #106). Neither settlement nor split-read reaches it. DOUG_VERIFY does.
- Cheapest unexploited lever: 28 of 153 findings (18%) are explicit
  re-raises across review rounds. Carrying a disposition forward is
  deterministic and costs zero model calls.

Verified against the code this session (agent pass, adversarial):
- Production makes UP TO two paid reads per PR on installation 150424894,
  not one — intent.select can return nothing, so the second is conditional.
- reader._client sets timeout=120 and no max_retries, so the SDK default of
  2 applies: worst case 360s+. reader.py:67's comment ("whole read incl.
  retries' backoff") is FALSE — the timeout is per attempt.
- Cloud Run deploys --timeout 300 (gcp.sh:693) while POST /v1/score/read
  (api.py:247) buys a read synchronously inside the request. Worst-case
  read outlives the platform timeout. Webhook path is insulated (202 first).
- ground_findings increments its spend counter BEFORE the call, so two
  transport failures exhaust the per-review verify budget grounding nothing.
- No request in the repo sets cache_control. Nothing is cached at all.

Pointers: branch claude/doug-pr-review-accuracy-232a1f ·
          api/doug/reader.py (MECHANICAL_MODEL at :64, _report_cost at :498) ·
          api/tests/test_reader.py (3 tests, mutation-verified) ·
          docs/design/reader-effort/preregistration.md (new) ·
          docs/findings-log.jsonl is the corpus · ADR-0012 is the precedent
          for narrowing the freeze against a stated bar.

---

## Prior stream — WorkOS sign-in, #167/#168/#170, PR #174 (kept verbatim)

State:    review — PR #174 open (#168 + #170), rebased onto main @ fd881cb.
          Suite green (345), tsc clean, lint clean. Eight mutations verified
          across the two changes.
Next:     Andrew reviews and merges #174. Then deploy and re-run #167 with a
          `maxAge` variant — #170's log line is now shipped, so the retest is
          readable for the first time.
Blockers: reconnect-in-place stays blocked. `maxAge` is the only untested
          variant and needs a DEPLOY: NEXT_PUBLIC_WORKOS_REDIRECT_URI pins the
          callback to the production origin, so it cannot run locally.
Decisions this session:
- #167 ANSWERED, negative (2026-08-21, production). Two round trips —
  /install/callback?setup_action=update (ships prompt:"consent") at 17:58:02Z
  and /sign-in (no prompt) at 17:58:52Z — both completed through WorkOS and
  landed on /dashboard in ~15s with no consent screen. GitHub's security log at
  18:05:58Z showed NO new token: newest Dougs Review event still 17:55:20Z.
  Instrument validated first — Doug mints log as a pair (drewjst
  oauth_access.create with IP + GitHub System oauth_access.regenerate) at one
  second, three times on 2026-08-21, each matching a real sign-in.
  prompt=consent is honored at WorkOS and never reaches GitHub, which accepts
  only prompt=select_account — exactly as the security lens predicted
- CONFIRMED LIVE BUG: /install/callback?reauth=github (route.ts:85-98) is a
  dead loop. route.ts:178-184 offers it as the ONLY remedy on a user-facing 403
- Evidence limit, stated in #167: this proves no NEW GitHub token was minted,
  not that WorkOS returned nothing. A replayed cached token dies on the same 8h
  clock, so it cannot refresh an expired scope either way
- #168: three arms — `declined` (401 only), `unavailable` (503 only),
  `unreachable` (everything else, incl. status:null) — rejected: one generic arm
- #168 mapping lives in dashboard-model.ts as `ledgerFailure` — same reason #99
  moved the front-door states there — rejected: inline ternary
- #168: only `declined` offers sign-out — rejected: sign-out on every arm
- #168 sign-out pin initially SURVIVED (lazy [\s\S]*? crossed arm boundaries);
  strengthened to (?:(?!signOut:)[\s\S])*? until all four mutations fail
- #170: the skip at entitlements.ts is WARNING, not ERROR — a Password sign-in
  reaching it is correct and expected, and paging on it would train the reader
  to mute the event that matters. The signal is a RATE: GitHubOAuth sign-ins
  arriving there at all — rejected: ERROR, and rejected: reusing the
  `entitlement_derivation_failed` event name
- #170: the skip still does NOT withdraw SCOPE_UNCONFIRMED — the existing
  comment is right that a skipped attempt must not clear a standing note
- #170's runbook half landed in docs/OPERATIONS.md with the Cloud Logging query
  and the GitHub security-log method. The connection config is now RECORDED
  (2026-08-21, Andrew read it): Return GitHub OAuth tokens is CHECKED, client id
  begins Iv23li (a GitHub App), client secret is set, Scopes = user:email only.
  So #170's Done-when is fully met and the toggle is eliminated as the cheap
  explanation for #167 — its negative stands as real WorkOS behaviour
- The Scopes=user:email field is expected INERT (scopes apply only to OAuth
  Apps; the Iv prefix and the working GET /user/installations call both say
  GitHub App). Written into the runbook rather than filed as an issue, because
  the failure it would cause is indistinguishable from #170's skip event and
  that is where someone would be looking — rejected: a third issue
- #171 cost argument CORRECTED, posture argument stands. The GitHub client
  secret exists (in WorkOS, not doug's Secret Manager), and with the toggle on
  and a GitHub App connection WorkOS returns refreshToken + expiresAt — SDK
  types it at factory-DmBBe791.d.mts:1161-1166, web/lib/entitlements.ts:6
  narrows it away. So doug is HANDED the 6-month refresh token at every sign-in
  and discards it; it does not have to acquire one. The reason to say no is
  still posture (no reversible secret anywhere in api/doug), not cost
- HANDOFF conflict on rebase resolved by keeping both sides, per the precedent
  PR #162 set for the same file
- The mixed case (one space live, one expired) is UNREACHABLE — store.py:3325
  stamps once per call, :3335 writes it to every row. No issue filed
- WORKOS_COOKIE_MAX_AGE is 28800 in production (gcp.sh:897), not the ~400 days
  api/doug/entitlements.py:26-31 claims. Comment is wrong as deployed, unfixed
Pointers: branch claude/login-workos-redirect-9d9711 · PR #174 ·
          #167 ANSWERED-negative (method in its comment), #168 + #170 in #174,
          #169 blocked on a positive #167, #171 Pipes, #172 preemptive refresh ·
          touched: web/app/dashboard/page.tsx (LedgerUnreachable + guarded
          read), web/lib/dashboard-model.ts (ledgerFailure),
          web/lib/entitlements.ts (the skip line), docs/OPERATIONS.md,
          three .test.mjs files ·
          node_modules installed in the worktree — 18 tests were failing on
          module resolution before that, on a clean tree too ·
          CI does not run on this branch yet; ci.yml is pull_request-triggered
          and had not reported at push time — check before merging ·
          full workflow output: scratchpad tasks/wptwl85el.output (226KB)
---

## Prior stream — check-run relayout + needs-you alert (kept, not this session's work)


---

## Prior stream — #152 secret-accessor sweep, PR #162 (kept, per that PR's own precedent)

State:    review — PR for issue #152 is open:
          https://github.com/drewjst/doug/pull/162
          Rebuilt on main after #155 (d8c4b48) landed; only HANDOFF.md
          conflicted and both sides are kept below. Production IAM already
          mutated (4 revokes, below) — that part is done, not pending review.
Next:     Andrew reviews and merges #162. Nothing in it deploys: `gcp.sh` gains
          a comment only, and the revokes were applied by hand on 2026-08-20.
          #161 carries the roles/editor remainder and needs a scoped
          doug-build-sa first.
Blockers: none.
Decisions this session:
- Done-when 1 PROVEN: doug-web serves 100% on doug-web-00090-wiw and the
  twenty most recent revisions all run doug-web-sa@doug-prod0. Later web
  deploys had already cut it over, so the M2 `[~]` was stale, not open ops.
- Done-when 2 was a no-op AS WRITTEN — doug-api-token never held the default
  compute SA. Swept all 11 secrets instead and found it on three others.
  REVOKED (Andrew approved "all four", 2026-08-20): default-compute accessor
  on doug-anthropic-key, doug-database-url, doug-webhook-secret; plus
  doug-web-sa's own accessor on doug-api-token (dead since Front Door Phase 0
  dropped that secret from web()). Every secret in doug-prod0 is now clean of
  the default compute SA. Before-policies are in the session scratchpad; each
  revoke reverses with one add-iam-policy-binding.
- Safety argument is the WORKLOAD INVENTORY, not logs: 3 Run services, 2 Run
  jobs, 1 scheduler job all hold dedicated SAs; no GCE; functions/eventarc/
  workflows APIs disabled. Rejected as evidence: the empty secretmanager
  audit query — doug-prod0 sets no auditConfigs, so Data Access logging is
  off and the silence proves nothing. Post-revoke: doug-api /openapi.json and
  doug-web / both 200; the live web revision mounts only the five workos/
  install-flow secrets, so cold start cannot regress either.
- The one-off runbook became a REPEATABLE SWEEP over every secret — chasing
  one named secret is exactly what let three others sit unnoticed for a
  milestone — rejected: fixing the one-off to name the right secret.
- Doug's own review of daf8355 raised `reader:docs-script-mismatch` (low) on
  that sweep. REAL, and the mechanism is sharper than reported: `json(name)`
  proves the API field is the full resource path
  (projects/1004699192359/secrets/…) and `value(name)` short-names it only via
  a command-specific display transform. Fixed with `name.basename()`, which is
  byte-identical on SDK 579.0.0 and drops the dependency on that transform.
  Dispositioned real/changed in docs/findings-log.jsonl.
- No new test. test_setup_creates_doug_web_sa_and_binds_only_its_front_door_secrets
  already asserts LIST EQUALITY on web's bindings, so doug-api-token cannot be
  reintroduced silently — a stronger pin than anything added here.
- HANDOFF.md convention followed from #155: newest slot block on top, each
  superseded block kept verbatim under its own "Prior stream" heading with a
  correction note. An earlier overwrite this session dropped the whole 448-line
  archive wholesale; it was restored, and it holds decision debt ("Andrew's
  call, blocks the scoreboard spec") that AGENTS.md says must not live only in
  a transcript.
Pointers: branch claude/github-issue-152-aa87ae · api/deploy/gcp.sh:174 (web
          SA create) · :896 (web deploy flags) · :200 (comment rewritten) ·
          docs/OPERATIONS.md:198 "Service identities" (one-off → sweep) ·
          docs/design/outcome-loop/ROADMAP.md:222 (ticked) ·
          api/tests/test_deploy_gcp.py:42,49 · docs/findings-log.jsonl

---

## Prior stream: sticky-comment seq guard (#155 merged as d8c4b48) — kept verbatim

> **CORRECTION 2026-08-20 (this session):** the block below says "PR for issue
> #142 is open" and "Andrew reviews and merges #155". It shipped — #155 is
> merged as d8c4b48 and is what this branch rebased onto. Its note that #157's
> open question (does a GitHub alert render inside a CHECK RUN summary?) is
> unaffected still holds, and that question is still open.

State:    review — PR for issue #142 is open:
          https://github.com/drewjst/doug/pull/155
          Rebuilt on main after #157 (db6d51c) landed; only HANDOFF.md
          conflicted and both sides are kept below.
Next:     Andrew reviews and merges #155. Migration 13 ships with it, so the
          API deploy applies the ALTER on start — nothing manual. #157's own
          open question (does a GitHub alert render inside a CHECK RUN
          summary?) is unaffected by this branch and is kept verbatim under
          "Prior stream: check-run relayout" below.
Blockers: none.
Decisions this session:
- The stored-`comment_id` `seq` guard is a RESERVATION, not a read:
  `store.claim_pr_comment_seq` tests `last_seq <= seq` and advances the mark
  BEFORE the GitHub write — rejected: read last_seq, compare, then write,
  which leaves the whole round trip as the window
- The claim's win/loss answer is RE-READ from the row, never taken from the
  UPDATE's rowcount — the equality retry writes a row the value it already
  holds, which is the matched-but-unchanged case drivers disagree on, and no
  CI job runs on Postgres — rejected: `rowcount == 1`, which Doug caught
- A reservation is NOT released when the GitHub write fails — a failed PATCH
  is not proof the edit did not land, so releasing would clear an older job
  to overwrite a newer verdict live on the PR — rejected: CAS rollback to the
  previous mark
- `last_seq` is nullable with no backfill — NULL means "nothing written yet"
  and never blocks; a row predating the column gets ONE unguarded write —
  rejected: forcing those rows through a listing, which would make a PR past
  `_PAGE_BOUND` fail every write forever instead of once
- The discovery path keeps BOTH comparisons (the marker's seq and the
  reservation): the marker is the only guard that survives storage being
  disabled and reads GitHub's actual state, the reservation is the only one
  that closes the window between deciding and writing — rejected: dropping
  the marker check as redundant
- All THREE of `upsert`'s update sites are gated, including the
  claim-lost-then-read-the-winner's-id path the issue did not name
- Doug's four findings on 6438a99 are dispositioned in
  docs/findings-log.jsonl (1 real+fixed, 1 adjacent, 1 real+documented,
  1 disproved) — the repo's rule is one row per finding at disposition time
Pointers: branch claude/issue-142-verification-fix-1a077f ·
          api/doug/store.py (pr_comments.last_seq, claim_pr_comment_seq,
          set_pr_comment_id) · api/doug/pr_comment.py (upsert's three write
          sites) · migration 13 · ADR-0014 D9 + Consequences amended ·
          spec 2026-08-19-sticky-pr-comment-design.md §4 ·
          docs/findings-log.jsonl

---

## Prior stream: check-run relayout (#157 merged as db6d51c) — kept verbatim

> **CORRECTION 2026-08-19 (this session):** the block below says "building …
> uncommitted". It shipped: #157 is merged and is what this branch rebased
> onto. Its open question — whether a GitHub alert renders inside a check-run
> summary — is still open, as is the `pr_comment.py` fold it names.

State:    building — check-run summary relayout + the needs-you alert are in
          the working tree on claude/doug-pr-review-llm-b10317 (uncommitted).
          api/doug/check_run.py + api/tests/test_check_run.py. Full suite
          green (1540), ruff clean.
Next:     Verify a GitHub alert actually renders inside a CHECK RUN summary —
          post one on a scratch commit. No public example exists to copy
          (sampled 5 large repos' check runs, zero carry `[!KIND]`). If it
          does not render, the alert moves to pr_comment.py's frame and the
          mirror keeps a bold line. Then decide whether the agent-handoff
          fold ships in the same change.
Blockers: none. (#148 merged as c8da9d7.)
Decisions this session:
- Comment layout: standing caveats (risk-is-not-a-grade, never-blocks, flag-line) move BELOW the findings under "### How to read this"; run-specific honesty (fallback, partial read, band) stays above — ~120 words of unconditional preamble was burying the only part that changes per push — rejected: leaving the order alone, folding the notes into `<details>` (unverified in a check run)
- The alert is keyed to the BAND, never to a finding's severity — the band is computed against installation_repos.needs_you_threshold (ADR-0013); a severity is model output (enum in reader.py's schema, `str | None` unvalidated in models.py). A Cleared verdict routinely carries a medium, so severity-keying puts a callout on a change the same summary just cleared — rejected: CAUTION on high/medium severity
- Exactly one alert, by precedence: fallback > partial read > Flagged > nothing. Cleared+clean read renders none — quiet is the signal — rejected: one block per condition (two stacked callouts train the reader to skip both)
- CAUTION (red) is never used; a surface that never blocks and has adjudicated 0 has not earned it. IMPORTANT (purple) carries "needs you" — Andrew, 2026-08-19
- Summary numbers become a markdown table, and no model-authored text may enter a cell: a `|` shifts every column and `_oneline` does not neutralise it, so severity words come from a fixed vocabulary and an unrecognised one degrades the cell to a plain count — rejected: escaping `|` at the cell
- Copy-for-LLM is a fenced block in the comment FRAME; GitHub attaches its own copy control to every fence (verified: drewjst/doug#143, and inside a closed `<details>` on microsoft/vscode#331454). We cannot build a button — `<button onclick>` and `style` are stripped (verified through POST /markdown)
- Still open, not filed as issues because they are this session's live state: the pr_comment.py fold + FRAME_MAX rework, the MCP `doug.review(repo, pr)` route, and whether a Cleared comment should collapse entirely

- Sticky PR comment: D1 one comment/PR edited in place · D2 body = check-run summary verbatim in a header/footer frame · D3 on by default, opt-out per repo · D4 link = dashboard receipt page · D5 403 swallowed, check run unaffected — rejected: per-push comments, flagged-only, short card, public receipt, gating
- D1 forward-only: setting changes future verdicts, ledger keeps stamped line — honest ledger vs. GitHub — rejected: retroactive re-band
- D2 dashboard setting on installation_repos + session PATCH — where the ledger is — rejected: .doug.yml file, or both
- D3 one 0–1 number for both scorers (reader ×100) — verdicts already normalise — rejected: two knobs
- D4 unset shows both defaults (0.30 reader / 0.62 fallback) — prod runs DOUG_READER=1 — rejected: single 0.62
- D5 write authority = org member + live repo entitlement, new settings:write scope — weaker than mint/bind, named — rejected: installer-only
- D6 two PRs, web exact() guards first — API deploys before web — rejected: one PR (dashboard outage window)
- D7 a global RequestValidationError handler on api.py (stock handler, non-finite floats stringified) so a NaN/Infinity threshold body 422s instead of 500 — recorded as an ADR-0013 consequence
- Threshold ≠ scope: "docs repo only cares about structure" is a path-rule feature, named as non-goal
Pointers: branch claude/per-repo-needs-you-threshold-f075db · spec a23c427 ·
          plan 098cf40 (11 tasks, two PRs) · ADR-0013
          docs/decisions/ADR-0013-needs-you-line-is-a-per-repo-setting.md ·
          seams: review.score_one (review.py:303), worker.py:250,
          store.set_installation_repos, api.py:1877 connections,
          web/lib/threshold-lens.ts (header rewritten to name the setting)

---

## Prior stream (production-dark; #116 merged) — original head kept for context

State:    **blocked — PRODUCTION STILL DARK.** Second defect in the same
          never-executed path. #113 (383daf6), #114 (8e1d774) and #115
          (22156d9) are all MERGED. **PR #116 IS OPEN** and is the last thing
          between here and a live loop:
          https://github.com/drewjst/doug/pull/116
          Branch `fix/adjudicator-needs-git`, verified locally red→green
          (pre-fix image: `exec: "git": executable file not found`, exit 127;
          fixed image: git 2.47.3 + a real `--filter=tree:0` clone of a public
          repo, which also proves TLS/CA).

Next:     1. Merge #116. **Deploy is AUTOMATIC** — see the correction below;
             do NOT run `gcp.sh adjudicator` by hand, that instruction was
             mine and it was wrong.
          2. **At or after 16:25 UTC / 9:25 AM PDT**, execute the Job:
             gcloud run jobs execute doug-adjudicator \
               --project doug-prod0 --region us-central1 --wait
             Earlier than that it exits 0 having done nothing — see the lease
             note below. Success = non-zero `done` in the DrainSummary and
             `/v1/showcase/scoreboard` leaving `adjudicated 0`.
          3. The liveness item — NOT built, recorded in the roadmap under M3.
          4. MT3 (spec approved, decisions locked below).

Blockers: the claim lease until 16:20 UTC.

> **CORRECTION 2026-08-18 (later session):** "#116 IS OPEN" above is now false —
> #116 is MERGED and is `main`'s HEAD (`3eddbf0`). Step 1 of Next is done.
> Steps 2-4 are UNVERIFIED from here: this session did not execute the Job and
> cannot say whether production is live. Check the scoreboard before trusting
> any of the narrative below that assumes #116 unmerged.

## LANE: plan-lane design — verticals, lanes, checkpoints (2026-08-18)

Branch `claude/great-villani-bb55c4` · worktree `dashboard-redesign-left-nav-efb4d7`
**Separate lane from everything below.** Nothing here touches production, MT3,
or the incident narrative.

State:    **design LOCKED by Andrew.** Nothing built, nothing committed.
          `docs/design/plan-lane/` is untracked.
Next:     Build §9 step 1 — `verticals.toml` (declared path→area map) plus a
          read-only CLI over `git worktree list`. One day, no infra, no model.
Blockers: none.

Read in this order — the design opens with §0, which is the entry point:
  docs/design/plan-lane/idea.md              the capture (lives on MT3's branch,
                                             commit 1b5a617 — not on main)
  docs/design/plan-lane/deterministic-half.md  the MEASUREMENT record
  docs/design/plan-lane/design.md            the locked design (§0 = why Doug)

Decisions this session:
- The unit is the BRANCH, not the plan — a plan can have several lanes
  (`lane1-phase-b` + `-rebuild`). Rejected: plan as the unit.
- Verticals are DECLARED, never inferred — inference filed `console-design`
  under Deploy at 11% and left 6 lanes unmatched. Rejected: path heuristics.
- Lane→plan join = the plan file is ON the branch: 15/38 lanes, zero false
  positives. Rejected: file-overlap inference (24/38, obvious garbage —
  `landing-brand-match` → the dual-run plan at 44%).
- INTERNAL tooling, explicitly. Rejected: a check-run surface, which would
  inherit the whole honesty contract and collide with session-lane's §6 claim.
- Drift/stale-doc detection stays OUT — rides the `unvalidated` deviation
  instrument (ADR-0007). Its deterministic cousin, plan churn, is in.

Findings that constrain any build (all reproducible, commands in design.md §0):
- **The checkbox is dead.** 76 `- [x]` lines ever added across 31 plans, every
  one in the commit that created the file. Never once flipped. Do not build
  progress on it.
- 36/116 tasks (31%) declare no file unique within their plan → `unresolved`,
  which must render differently from `not started`.
- 41 of 45 branches with unmerged commits are 5+ days cold. That is the
  rescue case and the reason the board earns its keep.
- **This file is contested by 12 live lanes** and is the 5th-hottest merge
  conflict in the tree — which is exactly the cardinality problem design.md §7
  describes. The slots are right; one-per-repo is wrong.

Mock (real repo data, iterated to a locked direction):
  https://claude.ai/code/artifact/351031ae-5947-4cb5-8269-c8c1e9237a24
  Working files: <scratchpad>/canvas/{Main.dc.html, canvas.json}

## THE LEASE — why re-running early "succeeds" and does nothing

The 14:20Z crash died AFTER `claim_repository`, so those rows sit at
`status='running'`. `drain()` opens with `reclaim_stalled()`, which only
returns rows older than `STALL_LEASE_SECONDS = 7200`, and
`due_repositories()` selects `status == 'pending'` only. The claim landed at
~14:22:40Z (the traceback is 14:22:44Z), so the lease clears at ~16:22:40Z and
9:25 AM PDT carries a margin. Every execution before then finds nothing due
and exits 0 — exactly what
`-m7vmr` (14:27Z, "Execution completed successfully") did. Scoreboard right
after it: `adjudicated 0 · pending 170`. The lease RESETS on each crash: if
the next run dies mid-way, add another two hours.

## CORRECTION — I was wrong about the deploy trap, and it spread

The "merging does not deploy the adjudicator" claim in commit 86807ee, PR
#113's body, this file, and the ROADMAP is **FALSE**. `deploy()` in `gcp.sh`
calls `adjudicator` and `reconcile_job` at its end, and `deploy.yml:132` says
so: "then refreshes doug-adjudicator from the promoted image". Proven: after
#113 merged, API and Job both moved to `@sha256:d12a4f4c` with no manual step.
Origin of the error: a `grep | head -20` that truncated before those lines,
plus reading gcp.sh's header ("`deploy` and `web` are what CI runs") as the
full list of what deploy does.

**It propagated.** main's HANDOFF carried it forward as its step 1 ("Run
`gcp.sh adjudicator` BY HAND ... merging #113 did not deploy the
adjudicator"), so a second session was about to act on my wrong claim. Fixed
here, struck through in the ROADMAP (#116), and corrected on #113 itself:
https://github.com/drewjst/doug/pull/113#issuecomment-5329880253

What survives: `doug-outcome-reconciler` still has ZERO executions and Cloud
Scheduler still holds only `doug-adjudicator-daily`. That was about the
scheduler, and `deploy` does not create schedulers.

## THE SECOND DEFECT — 2026-08-18, verified in prod (fix = #116)

    doug-adjudicator-hvdfn  14:20Z  exit 1
      File "/app/doug/backtest/git_labels.py", line 112, in clone_treeless
        subprocess.run([...])
      FileNotFoundError: [Errno 2] No such file or directory: 'git'

- Final stage is `python:3.14-slim-trixie`, copies only `/app`, installs
  nothing. The Job runs `python -m doug.outcome_worker` from that image.
- `git` is the ONLY missing binary: the import closure of `outcome_worker`
  reaches `backtest.git_labels` (git clone/fetch/log) and never `harvest`
  (the only `gh` caller). `_git_auth_env` injects `GIT_CONFIG_*` — no
  credential helper, no netrc, nothing else needed.
- Hidden by the SAME structural fact as the client bug, third time running:
  the drain path had never executed against real work, so twelve green Job
  executions carried no evidence about any of it.
- `docker build api` in CI never ran the image it built. #116 makes it run
  `git --version` against the built image.

## Dashboard redesign — PR #114 (MERGED as 8e1d774)

04df04a shell + census · 262f8e7 Repositories view · 3461657 the doc ·
03af44a the three review findings, fixed.

REVIEW ROUND, dispositioned in docs/reviews/2026-08-18-pr-114-external-review.md:
Doug scored 1 of 5. Its one true finding (severity bar drew three segments over
a total the three buckets need not sum to — `findings.severity` is nullable and
store.py counts total as COUNT(*) against three conditional SUMs) it ranked
LOW; its two most confident findings both die to `session-api.ts`'s boundary
validation, a file the diff never contained. The external pass found the defect
Doug missed, and it was the one this PR was most at risk of: `RepoCountLine`
branched on `atCap` before `filtering`, so at the cap with a filter on it named
a denominator 5x larger than the set actually counted — and disagreed with the
census panel on the same screen. Both fixed with tests watched failing first
and proven by mutation; `countedOver()` now owns the branch order for both
sentences and a parity test makes the disagreement unrepresentable.
CALIBRATION: Doug's severity ranking is now anti-correlated with truth across
#109, #106 and #114. That is the axis to work on, not its cross-file tracing,
which was correct here.

Tab-strip header → three-column instrument shell: a 212px left rail (scope,
sections, live in-view readout, settings gear), the ledger, and a right dock
holding either the selected run's evidence or a census of the ledger. Rail and
dock scroll independently, so the page itself does not scroll above 1620px.

NO API CHANGE. `web/lib/ledger-census.ts` counts what `/v1/sessions/runs` has
always returned and the dashboard never rendered: `finding_counts` (severity
mix), the three job timestamps (queue wait, read duration, retries), `url` (the
PR link, now an action), and the per-window outcome census including the
CENSORING RATE prereg §3 requires. Every number is a count of the array the
table is rendering, so the two cannot disagree; `censusScope()` prints the
denominator once, above all of them.

Decisions:
- Repositories is `?view=`, not a route — both views read one fetch, one filter
  set, one lens. Rejected: a second route (duplicates the shell) and a dashboard
  layout (cannot see the page's rows to fill the rail readout).
- The repository table is a FULL OUTER join. A connected repo with no runs is
  the most useful row on the screen; a repo with runs but no connection entry
  still holds real verdicts. Both directions mutation-proven. Rejected: joining
  from either side alone — each hides a different truth.
- Census is over the FILTERED rows in view, not `fetched`. Denominator stated.
- Dock breakpoint 1620px, MEASURED. Arithmetic said 1600 and was 9px wrong
  (chrome 669px + table 940px). At 1360 the PR title rendered 40px wide.
  Rejected: crushing the title to keep a dock on a 1440 laptop.
- Breakpoint classes written out literally at all five sites — a runtime
  `${DOCK_AT}:h-screen` is invisible to Tailwind's scanner and ships no rule.
- Settings gear is a `<details>`, not a popover. A view control that fails to
  hydrate costs a view; a sign-out that fails to hydrate strands you signed in.
- Band column did NOT shrink with the others — "needs you" wraps under 102px.
  Severity renders on the NEUTRAL ramp; a finding's severity is not a verdict
  about a PR. Two data colours still.
- The `min-w` pin is DERIVED from each COLUMNS array and sliced PER ARRAY. The
  first version scanned the whole file and REPO_COLUMNS broke it one commit
  later — same cross-record defect class as #109's regexes.
- The "health"/"tenant all"/"illustrative" bans stand untouched. This is one
  tenant's own runs, not fleet health.

VERIFICATION TRAPS, both hit on this branch and both look like real failures:
`next build` fails while a dev server holds port 3000 (the auth integration
tests shell out to it), and a stale `.next/dev/types/validator.ts` naming a
deleted route fails it too. `rm -rf .next` and stop the server before believing
a red suite.

Pointers: web/lib/ledger-census.ts (+ .test.mjs, 19 tests; band, outcome tone
          and both join directions mutation-proven) ·
          web/components/census-panel.tsx · web/app/dashboard/page.tsx ·
          web/lib/dashboard-contract.test.mjs
          · fixture-data preview harness (shell, census, evidence pane and
          repositories view, no auth or API needed) parked OUTSIDE the repo at
          <scratchpad>/design-preview-harness.tsx — restore to
          web/app/design-preview/page.tsx AND temporarily `export` Evidence +
          RepositoryTable in page.tsx. Both must come off before committing;
          the surface-token test catches the harness, nothing catches the
          exports.

## What was fixed

`api/doug/outcome_worker.py:36,40` — both GitHub clients now bound to a local
for the life of their call. Three tests, each watched failing first except
where noted:

- `test_client_lifetime.py` (new) — AST guard over the whole `doug` package:
  no attribute may be taken off a client factory's return value. RED before
  the fix, naming `outcome_worker.py:36` and `:40`. Carries a second test
  proving the walk can see the banned shape, so green means clean, not blind.
- `test_outcome_worker.py::test_github_context_holds_each_client_alive_across_its_own_call`
  — reproduces the production error at the production line against a client
  held the way githubkit holds it (weakref namespace). RED before the fix
  with the exact prod message.
- `test_app_auth.py::test_a_chained_client_is_collected_mid_expression_but_a_bound_one_survives`
  — characterization against REAL githubkit; passes immediately by design
  (it pins upstream, it drives no production code). It is what justifies the
  weakref fake in the test above.

## THE LIVE DEFECT — verified against prod 2026-08-18

`doug-adjudicator` exit 1 on both runs since the first job became due:

    2026-08-18T03:00Z  doug-adjudicator-szjvw  failedCount 1
    2026-08-17T03:00Z  doug-adjudicator-swwhk  failedCount 1
    2026-08-16T03:00Z  doug-adjudicator-ncpws  succeeded (nothing due yet)

    RuntimeError: GitHub client has already been collected.
      outcome_worker.py:36 in _github_context
      app_auth.app_client().rest.apps.create_installation_access_token(...)

Live `GET /v1/showcase/scoreboard` (2026-08-18T05:00Z):
`adjudicated 0 · pending 166 · first_due 2026-08-16T04:24:51Z` — two days
past due, zero adjudications, and the surface reads exactly like the honest
empty state it was designed to render. **Nothing said anything.**

- `outcome_worker.py:36,40` are the ONLY two unbound `client().rest.x.y()`
  chains left in `api/doug`. Every other call site binds to a local.
- This is #52 again — `tenancy.py:220-225` documents the identical failure
  from prod 2026-08-05, names the string, AND warns "Tests stub
  _caller_client wholesale, so only prod traffic exercises this."
- `test_outcome_worker.py:121` stubs `app_client` with a locally-bound fake,
  so it is structurally incapable of reproducing the failure. Third
  consecutive PR whose green check passes for the wrong reason — this one
  escaped to prod, in the component whose only job is to tell the truth.
- No data loss and no countdown: `reclaim_stalled` returns the lease
  "without spending an attempt", so the pre-registered ten attempts are
  intact. The clock is stalled, not burning.

## Also found (2026-08-18, prod)

- **MT0 is CLOSED.** Zero DRIFT lines in 7d of `doug-api` logs while the
  cold-start check ran repeatedly (6 startup sweeps in the last 7h). The
  roadmap already said so ("MT0 was closed operationally the same day",
  2026-08-05); the unchecked `- [ ] MT0` box and the old handoff disagreed.
  **Tick the box.**
- **`doug-outcome-reconciler` has NEVER executed.** The Job is deployed;
  Cloud Scheduler holds only `doug-adjudicator-daily`. `schedule-reconcile`
  was never run. So the outcome-reconcile lane runs only in the reaped
  startup thread → MT3's coverage hole is live today, not hypothetical.
  (Check intent first: MT3's D2 moves the full sweep INTO that Job, so
  leaving it unscheduled may be deliberate.)
- **Zero alert policies, zero notification channels** in doug-prod0.
- ~~The Job runs stale code after every merge.~~ **WRONG — see the
  correction at the top of this file.** `deploy()` refreshes both Jobs.
- `deep_reads 200/200` on the public meter is `PLAN_DEEP_READ_CAP`
  saturating for display only; enforcement is `INSTALLATION_MONTHLY_READ_CAP
  = 4000`. Not blocking, but the public meter reads pegged for August.

## Recommended order

1. ~~The two-line bind + a test that can fail~~ DONE, uncommitted.
   Deploy + manual execution remain — see Next, and note that merging alone
   does NOT deploy the Job.
2. Watch one real adjudication land; check one receipt end-to-end. That
   closes the last open half of the M3 exit gate.
3. The liveness item: surface `first_due` in the past + `adjudicated 0` as
   the contradiction it is, and alert on adjudicator `failedCount >= 1`.
   Roadmap has it under M3; nothing is built.
4. MT3 (spec approved, decisions locked below).
5. M4's 3 prospect interviews — highest information per hour in the plan,
   and they carry the standing kill criterion. Gated on a scoreboard that
   shows a real number, which is gated on step 1.

## MT3 — decisions locked (do not re-litigate)

- D1 Design for the org-install case (10k repos), not design-partner scale.
- D2 Full sweep moves to its own scheduled Cloud Run Job, mirroring
     doug-outcome-reconciler. Startup thread drops the full sweep.
- D3 Job ENQUEUES ONLY; drain stays in the API. Keeps the Job SA narrow.
- D4 One shared primitive applied to BOTH lanes.
- D5 Startup thread keeps a BOUNDED stalest-N pass — not nothing.
     Rejected: accept the regression; shorten the Job cadence.
- CONSEQUENCE: THREE entry points, three different bounds — unbounded
  (installation.created), budgeted (Job), bounded (startup). Collapsing any
  two is a regression that looks like correct behaviour. One test per site.
- Design: staleness within a tenant, round-robin across tenants.
- REJECTED: global staleness ordering — a 10k-repo tenant joining degrades
  every other tenant 200x, which is MT3's own complaint.
- REFUTED: that global interleaving re-mints a token per repo. githubkit's
  DEFAULT_CACHE_STRATEGY is a module-level singleton — verified empirically.
- MT3 takes migration **12** (9 = Front Door 1a, 10 = review_jobs.base_sha,
  11 = installation_repos.needs_you_threshold, taken 2026-08-18).
  `installations.reconciled_at` cannot close it: sweep state is per REPO.
- MT3 is a CORRECTNESS item: `active_repos` has no ORDER BY and
  `reconcile_all`'s only caller is a reaped daemon thread, so the tail is
  never swept on any cold start.

## Decision debt — Andrew's call, blocks the scoreboard spec

- #106 ships ten fields (`api.py:718-727`) and **none** of prereg §3's
  disclosure columns — no `censoring_rate`, `N_at_risk`, `misses`,
  `unverdicted_merges`, `partial_read_share`, `repos_withheld`. §3 says
  "Published together, never separately."
- Approach A §4.3 says the venue "can be the scoreboard page"; the later
  ruling ("the scoreboard is proof, not venue") says the opposite. Later
  ruling should govern and §4.3 should be amended. Neither is written down
  outside a session transcript, so no code review can see it.
- Latent trap live on main: the zero state is pinned in three coupled places
  (`miss_rate: None` in Pydantic, `miss_rate: null` as a TS literal, and
  `isScoreboardResponse` rejecting anything else), and on validation failure
  `cachedShowcaseFetch` silently serves a fixture reading `adjudicated: 0`.
  **Note the shape** — that fallback is the same mask as the defect above.

Pointers: branch `claude/doug-next-priorities-5851da` off main @ 412298e ·
          fix in `api/doug/outcome_worker.py:36,40` ·
          precedent + lifetime note `api/doug/tenancy.py:220-225` · the
          test that cannot fail `api/tests/test_outcome_worker.py:121` ·
          MT3 spec
          docs/superpowers/specs/2026-08-17-reconcile-sweep-scheduling-design.md
          · roadmap docs/design/outcome-loop/ROADMAP.md (grep item names,
          line numbers shift) · prereg §3
          docs/design/outcome-loop/publication-preregistration.md:337

---

# SIDE LANE — cited head reads (PR #118)

Isolated in worktree `managed-agent-pr-review-76fe26`, branch
`claude/managed-agent-pr-review-76fe26`. Touches nothing the main lane above
holds. Read the main lane's Next list first — the 2026-08-21 detector test is
time-critical and this lane is not.

State:    review — PR #118 open, Tasks 1-6 of 9 done. WIRED BUT DARK:
          DOUG_VERIFY is unset, so merging changes nothing for anyone.

Next:     Task 9 HARNESS DONE, not yet run — needs ANTHROPIC_API_KEY and
          costs real money (1 risk read + up to 2 verify reads per run).
          `uv run python scripts/smoke_cited_reads.py --dry-run` verifies the
          wiring for free. Then Task 7 (surface) -> Task 8 (ADR-0013).
          9 before 7 deliberately: Convergence Bar 1 already
          FAILED with reader nondeterminism as root cause, and this adds a
          nondeterministic call that ADDS published findings, so the spread
          must be known before anything renders to a customer.

Blockers: none. P0.1 is NOT a blocker — see below.

## The design, in one paragraph

Doug's reader gets `f.patch` and nothing else (review.py:190,267), yet
review.py:273 head_file_text is wired only into settle.py's drop_disproved_*
— so the system's one outside-the-diff capability is licensed to SUBTRACT
findings and forbidden to RAISE them. 7 of PR #106's 8 external findings
needed >=1 byte Doug never received. This reverses that licence: a finding
may CITE bounded head reads to ground an existence-or-value claim.

## Locked decisions (do not reopen — design-lock L1-L9)

- Model has ZERO delete authority. VERIFY_SCHEMA has no `refuted` field and
  no boolean. Why: PR #107 serialization-contract — a byte-matching,
  grep-derivable, factually TRUE quote carrying a FALSE refutation
  (models.py:113-125). A true quote can carry a false conclusion.
- A byte-match is NOT the predicate. constant_value_is parses the range with
  ast and needs exactly ONE binding of a LITERAL, so `LIMIT = CAP` quotes
  perfectly and still abstains. Drop that step and it degenerates to "the
  quote matched".
- Existence-and-value claims only. Absence/universality claims are never
  citation-certified — the citation shows one place out of a complement the
  model chose and never reported.
- Verify spend uses a DIFFERENT scope prefix so instrument_snapshot cannot
  see it; charging installation:<id> would render allowance the customer
  never spent, and at the 200 clamp reads as an exhausted plan.
- CUT: the citation-receipt PR (settle.py has fired ZERO times since it
  landed) and the per-source grading table (461 Co-authored-by, zero
  Reviewed-by).

## P0.1 is DONE — I was wrong twice; do not re-raise it

- Digest at 44b409c per the doc's own S12 protocol:
  c8e30da386362351a8d320e1ce91e725655a2f6517e5568c61cd9ad0168e60f2 —
  matches ROADMAP:330's `c8e30da3...60f2`, deployed 2026-08-11.
- deploy/gcp.sh:611 derives it from the document at deploy time; :674 sets it
  on doug-api and :719 on the adjudicator Job, from the SAME call site
  (:606-610 explains why one call site). deploy() runs
  preregistration_preflight, which refuses unless the doc is LOCKED.
  deploy.yml fires on push to main. The repo is PUBLIC, so it is published.
- publication-preregistration.md:8 still says the deployment has not
  happened. STALE, and UNFIXABLE: S12 makes any edit a new version with a new
  hash, invalidating the deployed value. DO NOT "correct" that line.

## Task 9 — scripts/smoke_cited_reads.py

Labeled a SMOKE TEST everywhere, in the docstring and in its own output,
because it is not a bar: the answer key is committed in-repo, its "deltas
worth encoding" named the gap this capability closes, and all 8 findings were
classified before the spec was written.

The ceiling is 1 of 8 and a low number is NOT a failure. 4 of the 8 live in
files absent from the PR (api.py, worker.py, test_deploy_gcp.py,
web/lib/api.ts) so no reader handed a diff can reach them. Of the 4 in files
Doug saw, only #2 (meter vs cap 200 while spend enforces 4000) is an
existence-and-value claim, the only shape constant_value_is can ground.

Dry run confirms the path exists without spending: 7/7 files with patches,
10,206-char diff, and the resolver returns api/doug/reader.py — a file NOT in
the PR — with INSTALLATION_MONTHLY_READ_CAP at line 230, which is exactly the
byte finding #2 needs.

No matching is automated. Deciding whether a Doug finding "is" an external
finding takes judgement, and a script that guessed would invent a metric.
Runs >=3 times by default and reports the spread, because open risk #2
(nondeterminism) must be measured rather than assumed.

## A mutation test caught a real bug in my own code

ground_findings' first draft repaired a short output list by re-slicing the
original from len(out). With 3 findings where the middle went missing, that
restored the LENGTH by dropping finding[1] and appending finding[2] twice —
count assertion passed, corruption silent. Restructured so each finding is
appended exactly once; the assertion now compares slug identity and ORDER.
Same mutant now kills 5 tests. Every task in the PR was mutation-checked.

Pointers: docs/design/competitor-imports/ (6 artifacts, design-lock L1-L9) ·
          docs/superpowers/specs/2026-08-18-cited-head-reads-design.md (D1-D9) ·
          docs/superpowers/plans/2026-08-18-cited-head-reads.md (Tasks 1-9) ·
          api/doug/{reader,verify,review}.py · api/tests/test_ground.py ·
          docs/reviews/2026-08-12-pr-106-external-review.md (the answer key —
          SPENT, it shaped this design; the replay is a smoke test not a bar) ·
          docs/design/plan-lane/idea.md (captured, unevaluated)
