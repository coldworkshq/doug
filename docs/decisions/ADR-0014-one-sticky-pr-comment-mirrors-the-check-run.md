---
title: One sticky PR comment mirrors the check run, edited in place
status: accepted
date: 2026-08-19
---

## Context

Doug's only surface on a pull request is one check run named `Doug`, conclusion
always `neutral` (ADR-0010). GitHub folds neutral checks under "1 neutral
check", below the required checks; on #119 the verdict *Cleared · risk 0.16 ·
diff read* sat there, effectively invisible. A surface nobody sees is not the
conservative choice — it is the absent one, the same argument ADR-0010 made
against shipping the App with no surface at all.

ADR-0010 kept one condition from ADR-0003 in force: *"Holding the surface
until a precision number is published … That condition was written about
surfaces that can block or notify, and it still binds those. A neutral check
run does neither."* A PR comment is not a neutral check run. It notifies
every subscriber on the PR — the objection ADR-0003 raised against comments
in the first place — so the condition's own text binds this surface by name.
The precision number it asks for does not exist: `adjudicated 0` as of
2026-08-18.

Two things are different from what ADR-0003 pictured, and only one of them
answers the condition. Reach is bounded, not removed: a comment created once
per PR and edited in place thereafter notifies once per *created* comment,
not once per push. That answers the volume half of "notifies every
subscriber." The other difference — the comment's content is not new, it is
the check run's rendered summary, byte-for-byte — answers a different
question. It says a wrong comment is exactly as wrong as the check run
already is, not a second, independent claim. It does not say the precision
number exists, and it does not make the surface stop notifying. This record
does not treat "the content is not new" as satisfying the precision clause;
the clause is about whether the surface notifies, not about whether its
wording is original, and on that question the answer is still no.

The decision is to ship anyway, because invisibility is also a failure — a
verdict nobody reads governs nothing, calibrated or not — and to price the
gap rather than paper over it. The staged rollout (D3a: an installation
allowlist for one release, Doug's own repositories first) is the mitigation:
the first tenant to receive a notifying, unvalidated surface is Doug's own,
not a customer's.

**Amended 2026-08-20 (issue #144): the D3a allowlist is removed.** The
rollout it gated is finished and the record below is kept as accepted rather
than rewritten; this note says what changed. The week produced 18 landed
writes (12 `updated`, 6 `created`), no `denied:403`, no `failed:*`, and no PR
carrying two Doug comments. The mitigation's own sentence — that the first
tenant to receive this surface is Doug's own and not a customer's — turned
out to be guaranteed by the population rather than by the env var: the entire
live footprint on that date was five repositories across three installations,
all of them Andrew's. What the allowlist actually bought after the first week
was a second, invisible switch: `coldworkshq/coldworks` sat dark for two days
with its dashboard toggle reading "on" and no denial banner to explain it,
because nothing was ever attempted and there was therefore no 403 to report.
That is the state D8 exists to refuse, arrived at from the other direction.
`installation_repos.pr_comment` (D3) is now the only gate.

## Decision

- **D1 — One sticky comment per PR, mechanically.** Doug PATCHes the marked
  comment it authored when one exists on the PR and POSTs only when none
  does. Never a review (approve / request-changes); never an inline comment
  on code. "At most one Doug comment per PR" is a property this mechanism
  produces in the ordinary case, not an absolute — §"Consequences" below
  names the two ways it can still fail.
- **D2 — Body is a frame around the check run's rendered summary,
  verbatim.** The middle is `check_run.render()`'s summary, byte-for-byte,
  including its title line; the frame states only what the summary cannot —
  which commit it is about, that the comment is edited in place rather than
  re-posted, and where the full receipt is.
- **D3 — On by default, opt-out per repository; Doug never deletes a
  comment.** `installation_repos.pr_comment` defaults `TRUE`, toggled beside
  the flag line. The worker posts only when an active `installation_repos`
  row exists with `pr_comment = TRUE` (D6). Turning the setting off stops
  future updates; the last comment stays — persistence after opt-out is
  priced below and tracked as issue #141.
  - **D3a — a temporary installation allowlist gates the rollout.** The
    column ships `DEFAULT TRUE`, but the worker's post is additionally
    gated by an env-var allowlist (`DOUG_PR_COMMENT_INSTALLATIONS`, same
    shape as `intent.enabled_for`'s) for one release, scoped to Doug's own
    dogfood installation, before the general population sees the surface.
  - **D3b — opt-out is forward-only by design, not by oversight.** Already
    posted comments are not deleted when a repository opts out; removal, if
    ever wanted, is manual. Tracked as issue #141, which records the
    argument on both sides.
- **D4 — The link target is the dashboard receipt page**, session-bound;
  the footer states sign-in is required and also carries one link that
  needs no session (`/docs/what-doug-gets-wrong`), so the footer always has
  something it can honour for a reader without a Doug account.
- **D5 — The App permission is `pull_requests: write`; failure to post is
  swallowed, logged, and changes nothing else.** Every existing installation
  must re-accept it. `pr_comment.upsert` is the only function this
  permission is exercised through — it exposes no path that submits a
  review, the same move ADR-0010 made when `check_run.post` was given no
  conclusion argument for a caller to get wrong. Until an installation
  re-accepts, the call 403s, the worker logs and moves on, and the check
  run is unaffected.
- **D6 — The worker posts only for an active settings row.**
  `store.repo_pr_comment(installation_id, github_repo_id)` returns `True`
  only when an `installation_repos` row exists with `state='active'` and
  `pr_comment = TRUE`; an absent or removed row returns `False`. The set a
  tenant cannot see on the dashboard must not be the set that receives an
  un-disableable public comment.
- **D7 — Model-authored text is neutralised once, upstream of both
  surfaces.** `check_run._oneline` neutralises `@` mentions, `#` /
  `owner/repo#` cross-references, unterminated `<!--`, `](` links and bare
  `://` URLs — forms that are inert in a check-run summary but notify,
  cross-reference, link under a trusted identity, or corrupt rendering in a
  live PR comment. Every span the summary splices goes through it, with no
  exceptions — not only the obviously model-authored label and deviation
  description, but equally the rule (`reader:{category_slug}`, built from a
  free-form schema field carrying no enum and no pattern), the `Judged
  against:` record ids (a repo-controlled filename stem — `IntentDoc.id`
  falls back to a raw filename outside the `ADR-NNNN` convention), and the
  two enum-constrained fields the Python models nonetheless type as bare
  `str`. The absolute is the point: an exemption argued from a schema is a
  bypass the next reader has to re-derive. Inside a code span the backtick
  is dropped rather than split, since it is the one character that would
  close the span and hand the rest to the renderer. The check run loses
  nothing; the comment inherits safe text without a second pass that could
  diverge from it.
- **D8 — Permission denial is visible on the dashboard.**
  `installations.pr_comment_denied_at` is set when `upsert` returns
  `denied:403` and cleared on the next `created`/`updated`; a banner on the
  Repositories view names the timestamp of the last refusal and the usual
  causes (the permission not being re-accepted, a locked conversation, an
  archived repository, secondary rate limiting) without asserting which one
  applies — the response code does not distinguish them.
- **D9 — The comment carries its commit and a sequence number; the marker
  is matched on authorship, not text alone.** The marker line
  (`<!-- doug:verdict head={sha} seq={job_id} -->`) is matched by prefix
  **and** by App authorship before `upsert` will write to a comment it
  finds; a marked comment posted by a human is never touched. Within the
  matched, App-authored comment, `upsert` compares `seq` against the
  existing marker and skips an update whose `seq` is not newer — on the
  path that discovers the comment by listing. *Amended by issue #142: as
  accepted, this decision stopped there, and the sentence that followed
  said the path writing through an already-stored comment id does not
  repeat the comparison. It does now. That path never lists, so it has no
  marker to read; it compares against `pr_comments.last_seq`, a high-water
  mark of the last `seq` reserved for the slot, advanced by
  `store.claim_pr_comment_seq` in the same statement that tests it and
  before the GitHub write. The decision D9 records is unchanged — `seq`
  guards the write — and the amendment is that it now holds on every path
  rather than one.*

## Rejected

- **A comment on every push.** The volume ADR-0003 actually objected to;
  editing in place instead is the entire point of D1/D9.
- **A comment only when the verdict is flagged.** The cleared case was the
  one that was invisible under the check run alone; posting only for
  flagged verdicts would repeat that failure by a different route.
- **A short card that links out for detail.** Findings a click away is the
  "never viewed" problem again, restated inside the comment itself.
- **A distinct, richer layout before the receipt data exists to back it.**
  Prettier than it is honest until the underlying data is real.
- **A public, unauthenticated receipt page.** A new tenancy surface, larger
  than this feature; out of scope here.
- **Deleting Doug's comments automatically when a repository opts out.**
  Considered as part of D3b and rejected for now — the App's
  `pull_requests: write` scope makes it buildable, but deleting a tenant's
  PR comment under a bot identity, unprompted, is its own surprise, and the
  comment is part of what the receipt exists to preserve. Recorded as issue
  #141, including the case for reversing this.
- **Gating the review itself on the comment succeeding.** The comment is
  advisory; making a durable, already-scored verdict depend on a second
  network call to GitHub would turn an advisory surface into a point of
  failure for the verdict it is supposed to mirror.
- **Matching an existing comment on its marker text alone, without
  checking authorship.** Any account can post text starting with the
  marker on a public repository; with `pull_requests: write` the App can
  edit any comment on the PR. Marker-only matching would let a human's
  comment be silently rewritten under their name the first time Doug ran.
- **Treating an absent `installation_repos` row as "on."** Refuted by the
  drift check the worker already runs: rows absent from that table are
  invisible on the dashboard today, and the set a tenant cannot see must
  not be the set that receives a comment it cannot toggle off.
- **Shipping the toggle with no visible signal when posting fails.** A
  setting that reads "on" while nothing ever posts, with the only trace a
  stderr line in a project with no alerting, leaves the operator to notice
  an absence they would have to go looking for. D8's dashboard banner
  exists so the failure has a surface.
- **`issues: write` as a narrower permission than `pull_requests:
  write`.** Considered and rejected — it is wider, not narrower: on GitHub
  a repository's issue-comment and PR-comment endpoints are the same API
  surface, and `issues: write` alone would not grant the review-adjacent
  PR actions this ADR states plainly under `pull_requests: write` instead,
  while still exposing comment writes across every issue in the repository,
  not only pull requests.

## Consequences

- **One notification per *created* comment**, not per push — the mechanism
  D1 buys. Two ways "at most one Doug comment per PR" can still fail:
  - Someone deletes Doug's comment. The next review does not know it is
    gone until `update_comment` 404s, at which point `upsert` forgets the
    stored id and re-creates — a second notification, and unbounded if the
    deletion repeats.
  - The claim on a new comment is lost with a `NULL` stored `comment_id`
    while two drainers race the same PR seconds apart (the deployed
    configuration is `--max-instances 2` with `SKIP LOCKED`, so this is
    ordinary, not exotic): both can reach the create step before either's
    write is visible to the other, producing two comments for one PR. The
    duplicate is permanent absent manual removal, not self-healing: as soon
    as either drainer's `set_pr_comment_id` lands, every later job takes the
    stored-id branch and updates through it without listing again, so nothing
    ever revisits the orphan. Only a human deleting the tracked comment — the
    404 that forces `upsert` back to a listing — brings the surviving pair
    back to one.
- **Comments persist after opt-out and after uninstall.** D3 never deletes;
  there is no bulk-removal path. A repository that opts out, or a tenant
  that uninstalls the App entirely, leaves every comment Doug already
  posted exactly where it was, including its link to a dashboard the org
  may no longer have access to. Priced and argued in issue #141.
- **`pull_requests: write`'s blast radius is wider than comments.** Beyond
  posting and editing comments, the scope permits the App to create,
  submit, and dismiss reviews (including approve and request-changes),
  edit a PR's title, body, and base branch, close and reopen PRs, request
  reviewers, and delete any comment on any PR — including a human's.
  It does **not** permit merging, which needs `contents: write`. Doug uses
  none of the wider grant; that it is available at all is a fact about the
  App's install footprint, not about what this code does. Declining the
  permission re-acceptance on an installation keeps today's
  check-run-only behaviour — the comment surface simply never activates
  for that tenant, with no other change.
- **The interim allowlist (D3a) is temporary.** It exists to scope the
  first release to Doug's own repositories, not as a permanent access
  control; its removal in a follow-up PR is expected and is not a
  deviation from this record. **Removed 2026-08-20 (#144)** — see the
  amendment in Context for what the week showed and why the allowlist had
  become a liability rather than a mitigation.
- **The mirror claim is one-directional.** `check_run.post` can itself fail
  and swallow the error (ADR-0010); when it does, the comment can still
  post successfully, producing a PR with a sticky comment mirroring a
  check run that never appeared. "Mirrors the check run" describes the
  comment's content, not a guarantee that both surfaces always exist
  together.
- **A reserved `seq` is not released when the write fails.** *(Amended by
  issue #142. As originally accepted, this entry read that the
  stored-`comment_id` path skipped the guard entirely and could let an older
  verdict overwrite a newer one.)* Closing that gap made the guard a
  reservation rather than a read: `store.claim_pr_comment_seq` advances
  `pr_comments.last_seq` before the GitHub write, so an older job loses the
  row rather than the race. Nothing rolls the mark back when that write then
  fails, and that is the deliberate half. A failed PATCH is not proof the
  edit did not land — a `5xx` or a dropped connection can follow a request
  GitHub already applied — so releasing the reservation would clear an older
  job to write over a newer verdict that is live on the PR, which is the
  overwrite the guard exists to stop. The price paid instead is narrower: a
  job whose `seq` falls between the last landed write and a failed
  reservation is refused. The same job's retry keeps its id and passes on
  equality, and every later push carries a higher one, so the residual is
  the one priced elsewhere here — a stale comment that self-heals on the
  next push.
- **Comments that predate `last_seq` get one unguarded write each.** A
  `pr_comments` row written before issue #142 carries a `comment_id` and a
  NULL mark, and NULL never blocks. The seq such a comment carries is
  legible only in its own body, so no backfill can set the mark from the
  database. The residual is one write per pre-existing PR, after which the
  mark is set and every later write is guarded. Forcing those rows through a
  listing to read the marker was rejected: a PR past `pr_comment._PAGE_BOUND`
  would then fail every write forever rather than once.
- **Most PR readers hit sign-in on the receipt link.** The footer's
  dashboard link (D4) requires a Doug session; a reader who is not already
  a Doug user lands on a sign-in wall rather than the receipt, and signing
  in creates an orgless WorkOS account — a support-ticket shape to expect,
  not a defect in this design.

**Reader-fed:** this record is `accepted`, so Doug's own reader will flag
against it. Flag: a second function anywhere in the codebase that writes PR
comments outside `pr_comment.upsert`; any code path that submits, approves,
or requests changes on a review; a write path that posts or edits a comment
without first checking an active `installation_repos.pr_comment` row (D6);
neutralisation removed from `check_run._oneline` while a PR comment surface
still exists; **any reintroduction of an installation-level gate on the
comment write** — `DOUG_PR_COMMENT_INSTALLATIONS`, a `pr_comment.allowed`,
or a new equivalent — because a second switch a tenant cannot see is what
#144 removed and what D8 refuses. Do not flag: `upsert` re-creating a comment
after a human deletes it (named above as a priced consequence, not a bug);
the absence of the `DOUG_PR_COMMENT_INSTALLATIONS` allowlist (D3a named its
removal as the expected outcome, and it happened on 2026-08-20).
