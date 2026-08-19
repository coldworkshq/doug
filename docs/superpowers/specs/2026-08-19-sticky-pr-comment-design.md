# One sticky PR comment that mirrors the check run

**Date:** 2026-08-19
**Status:** design approved in chat 2026-08-19 (D1–D5); revised the same day after a three-lens adversarial review (correctness of code claims, security/abuse, product/honesty) — D6–D9 added from it; two judgment calls flagged for Andrew in §2 (D3a, D3b); then an implementation plan
**Branch:** `claude/sticky-pr-comment` (depends on #120 — the per-repo settings row, `PATCH /v1/sessions/repositories/{id}`, the Repositories view control)
**Amends:** ADR-0010 §Rejected "PR comments" (→ ADR-0014). The check run and its `neutral` conclusion stand.

---

## 1. The gap, and the objection this has to answer honestly

Doug's only surface on a pull request is one check run named `Doug`, conclusion always `neutral` (ADR-0010, `api/doug/check_run.py`). GitHub folds neutral checks under "1 neutral check", below the required checks; on #119 the verdict *Cleared · risk 0.16 · diff read* was there and effectively invisible. A surface nobody sees is not the conservative option — it is the absent one, which is the argument ADR-0010 itself made against shipping the App with no surface at all.

ADR-0003 and ADR-0010 rejected PR comments: *"a wrong comment notifies every subscriber and it persists."* ADR-0010 also kept a condition that binds this case by name: *"Holding the surface until a precision number is published … That condition was written about surfaces that can block or notify, and it still binds those. A neutral check run does neither."* A PR comment notifies. The precision number does not exist (`adjudicated 0` as of 2026-08-18). This spec does not pretend otherwise. Two things are different from what ADR-0003 pictured, and the decision is to ship on the strength of them while naming what they do not fix:

- **Reach is bounded, not removed.** A comment that is created once per PR and edited in place thereafter notifies once per *created* comment; edits do not notify. That answers the volume half of "notifies every subscriber" — not the existence of a notification.
- **Content is not new.** The body is the check run's rendered summary, byte-for-byte (D2). A wrong comment is exactly as wrong as the check run already is — it is not a second claim.

What neither fixes: the comment **persists in the conversation timeline** in a way a SHA-bound check does not; a first comment on every active PR is still one notification per PR per tenant on the day it turns on. D3a and D3b below are where that cost is priced.

## 2. Decisions

- **D1 — One sticky comment per PR; Doug PATCHes the marked comment when one it authored exists and POSTs only when none does.** Never a review (approve / request-changes); never an inline comment on code. "At most one Doug comment per PR" is a *property* (§4 names the one way it can fail), not an absolute the reader should flag against. Rejected: a comment per push (the notification spam ADR-0003 actually rejected); comment only when flagged (the cleared case is the one that was invisible).
- **D2 — Body = a frame around `check_run.render()`'s summary, verbatim.** The middle is the summary, byte-for-byte, including its title line; the frame says only what the summary *cannot* (which commit, that it is edited in place, where the receipt is). Rejected: a short card + link (findings a click away — the "never viewed" problem again); a distinct richer layout first (prettier than it is honest until the data behind it exists); a header repeating the title/threshold/"not a gate" (all three are already the summary's first lines — the frame would stutter).
- **D3 — On by default, opt-out per repository; Doug never deletes a comment.** `installation_repos.pr_comment BOOLEAN NOT NULL DEFAULT TRUE`, toggled beside the flag line. "On" means *for repos the tenant can see and toggle* — the worker posts only when an **active** `installation_repos` row exists with `pr_comment = TRUE` (D6). Turning it off stops updates; the last comment stays. Rejected: off by default forever; split by band.
  - **D3a — judgment call for Andrew (recommended: yes): stage the first release behind an installation allowlist.** Column ships `DEFAULT TRUE`; the worker's post is additionally gated by `DOUG_PR_COMMENT_INSTALLATIONS` (same shape and rationale as `DOUG_INTENT_INSTALLATIONS` in `api/deploy/gcp.sh` — "opting a real tenant into an experiment is a deliberate act, not a default") for one release on the dogfood installation, plus a `/docs/changelog` row; then the allowlist is removed. The first POST per PR is the one irreversible act here; one reversible week costs nothing and gives ADR-0014 a real mitigation to cite. The interim allowlist is recorded in ADR-0014's Consequences as temporary, so the reader does not flag its removal.
  - **D3b — judgment call for Andrew (recommended: keep "never deletes", open a standing issue):** opt-out is forward-only; already-posted comments stay and removal is manual, per PR. `pull_requests: write` *does* allow deletion, so "delete Doug's comments on opt-out" is buildable; it is not built here because deleting under a bot identity on a tenant's PRs is its own surprise, and because the record of what Doug said is the thing the receipt exists to preserve. Recorded as a GitHub issue per the standing-issues rule, and priced in ADR-0014's Consequences as the persist half of ADR-0003's objection.
- **D4 — Link target is the dashboard receipt page** `{DOUG_WEB_URL}/dashboard/pr/{number}?repo={quote("owner/name", safe="")}` — exists today, session-bound; the footer says **sign-in required** and also carries one public link (`/docs/what-doug-gets-wrong`) so the footer always has something it can honour for a reader without a Doug session. Rejected: a public unauthenticated receipt (a new tenancy surface, bigger than this feature); no link.
- **D5 — The App permission is `pull_requests: write`; its blast radius is stated; failure to post is swallowed, logged, and changes nothing else.** Set in the GitHub App settings (not in this repo); every existing installation must re-accept. Beyond comments, the scope permits the App to create/submit/dismiss reviews (including approve / request changes), edit PR title/body/base, close/reopen, request reviewers, and delete any PR comment; it does **not** permit merging (`contents: write`). Doug uses it for comments only — structurally: `pr_comment` exposes `upsert` and nothing capable of writing a review, the same move ADR-0010 made with `check_run.post` taking no conclusion. `issues: write` was considered and is wider, not narrower. Until an installation re-accepts, the call 403s; the worker logs and moves on; the check run is unaffected; the dashboard shows the denial (D8). Rejected: gating the review on the comment.
- **D6 — The worker posts only for an active settings row.** `store.repo_pr_comment(installation_id, github_repo_id)` returns `True` only when an `installation_repos` row exists with `state='active'` and `pr_comment = TRUE`; absent row or `removed` → `False`. Why: the worker does *not* otherwise require a row (`api.py` prints a DRIFT line at startup for verdicts whose repo has no row; those repos are invisible on the dashboard) — the set a tenant cannot see must not be the set that gets an un-disableable public comment. Rejected: absent → `True` (the first draft's reading; refuted by the drift check).
- **D7 — Model-authored text is neutralised for both surfaces, in `check_run`, so byte-identity holds.** A check-run summary and a PR comment render the same markdown but do not have the same side effects: in a comment, `@handle`/`@org/team` notifies and subscribes, `#123` / `owner/repo#4` writes a cross-reference into another issue's timeline, `[text](url)` is a live link under a trusted bot identity, an unterminated `<!--` swallows the rest of the body. `check_run._oneline` (the existing chokepoint both `r.label` and `d.description` pass through) gains neutralisation of those forms; `_quote` routes through it too. The check run loses nothing (those forms were inert there) and the comment inherits safe text without diverging. Rejected: neutralising only in the comment (breaks D2's test and makes the two surfaces differ).
- **D8 — Permission denial is visible on the dashboard.** `installations.pr_comment_denied_at TIMESTAMPTZ NULL` set when `upsert` returns `denied`, cleared on the next `created|updated`; one banner on the Repositories view: *"Doug's last attempt to comment was refused (403). The usual cause is the pull-requests write permission not being re-accepted in GitHub; a locked conversation or an archived repository produce the same code."* Rejected: shipping a toggle that reads "on" while nothing ever posts and the only trace is a stderr line in a project with no alerting.
- **D9 — The comment carries its commit and a sequence, and the marker is matched on authorship.** Marker `<!-- doug:verdict head={head_sha} seq={job_id} -->`; `upsert` matches `startswith("<!-- doug:verdict")` **and** App authorship (`performed_via_github_app.id == app id`, or the App's bot login), skips the update when the existing `seq` is greater than this job's, and stores the comment id so the lookup is one call and the create is claimed (§3.2). Why: a check run is bound to a SHA and a comment is not — without the SHA the comment implicitly claims a currency the check run never does; two drainers are the deployed configuration (`--max-instances 2`, `SKIP LOCKED`) so last-writer-wins is ordinary; and with `pull_requests: write` the App *can* overwrite a human's marked comment under their name (any GitHub account can post one on a public repo), so marker-only matching is a slot-hijack. Rejected: marker-only match; list-scan on every post.

## 3. Design

### 3.1 Storage + setting

- `installation_repos.pr_comment BOOLEAN NOT NULL` with **`server_default=sa.true()` in the Table home** and `DEFAULT TRUE` in the migration (next free version at implementation time — 11 is #120's; 12 unless MT3 lands first). `server_default` is mandatory, not optional: `set_installation_repos` inserts an explicit `values` dict that omits the column, and on a `create_all()` schema a bare `nullable=False` column raises `NOT NULL constraint failed` on every repo insert (every install, every `installation_repositories` webhook). Test: a *new* repo row inserts and reads `True`; `replace=True` preserves an explicit `False`.
- `installations.pr_comment_denied_at TIMESTAMPTZ NULL` (D8), same migration.
- `pr_comments(installation_id, github_repo_id, pr_number, comment_id BIGINT, updated_at)` with `UNIQUE(installation_id, github_repo_id, pr_number)` (D9 / §3.2).
- Store: `repo_pr_comment(installation_id, github_repo_id) -> bool` (active row only — D6; `False` when storage is disabled); `set_repo_pr_comment(installation_id, github_repo_id, value: bool) -> bool` (active row only; writes only that column; never bumps `updated_at` — `repo_id_for` tiebreak, as #120); `claim_pr_comment(...)`, `pr_comment_id(...)`, `set_pr_comment_id(...)`, `forget_pr_comment(...)`; `mark_pr_comment_denied(installation_id, at | None)`.
- **PATCH `/v1/sessions/repositories/{github_repo_id}`** body becomes `{"needs_you_threshold"?: number|null, "pr_comment"?: bool}` with `extra="forbid"` and a `model_validator(mode="after")` that rejects an empty `model_fields_set` (→ 422 via the existing global handler). **Each write is gated on `"field" in body.model_fields_set`, never on `is not None`** — `null` is a meaningful value for the flag line (the "reset to default" form), and an unconditional `set_repo_threshold(…, None)` on `{"pr_comment": false}` would wipe the repo's line. `pr_comment` is strict (`"true"` and `1` → 422). Response returns both current values. Audit line names only the field(s) actually written. Test: `PATCH {"pr_comment": false}` on a repo with a 0.75 line leaves `needs_you_threshold == 0.75` stored and returned.
- `GET /v1/sessions/connections` `repositories[]` entries gain `pr_comment: bool`; the connection gains `pr_comment_denied_at: string|null`.
- **Web, two PRs (PR A then PR B), same reason as #119/#120 (API promotes before web) — and PR A must relax TWO guards:** `repository()` (the `repositories[]` entry) **and** the `setRepositoryThreshold` response guard (`exact(body, ["needs_you_threshold"])` would throw on the new two-key response, breaking every "save"/"reset" click between the API and web promotions). PR A re-adds `exactWithOptional`; PR B tightens. The toggle is **its own** form posting only `{"pr_comment"}` via `setFlagLineCommentAction` (the flag-line control is deliberately JS-free with two forms because a shared field name is picked up by `formData.get` — a form carrying both fields would clear the line). Label "PR comment · on/off"; contract test; denial banner (D8).

### 3.2 `api/doug/pr_comment.py` (new; sibling of `check_run.py`)

```python
MARKER_PREFIX = "<!-- doug:verdict"      # startswith() on the raw body, line 1

def receipt_url(owner, repo, pr_number) -> str | None:
    """{DOUG_WEB_URL}/dashboard/pr/{n}?repo={quote(owner/repo, safe='')};
    None when the env is unset or empty (os.environ.get(...) or None —
    Cloud Run sets DOUG_WEB_URL="" on a bootstrap before doug-web exists)."""

def render(summary, *, head_sha, seq, receipt_url) -> str:
    """marker line, blank line, one italic header line, blank line, the
    check-run SUMMARY BYTE-FOR-BYTE, TWO newlines, '---', footer."""

def upsert(gh, owner, repo, pr_number, body, *, installation_id, github_repo_id, seq) -> str:
    """Returns 'created' | 'updated' | 'skipped-stale' | 'denied:403' | 'failed:<code|net>'."""
```

**Frame.** Header: `_The \`Doug\` check run for {head_sha[:7]}, repeated here in full. Doug edits this comment in place on every review; it is never re-posted._` — this resolves the summary's own "this check" references, carries the commit (D9), and explains the one behaviour a reader cannot infer. Footer: `Doug · [full receipt on Doug HQ]({receipt_url}) — sign-in required · [what Doug gets wrong]({DOUG_WEB_URL}/docs/what-doug-gets-wrong)`; without `DOUG_WEB_URL` both links are omitted and one stderr line is printed per process. **Joins are pinned:** a blank line between header and summary, and **two** newlines before `---` — `check_run.render` can end on a list item (`- none`) or a plain paragraph, and a `---` on the very next line is a setext `<h2>` underline or a GFM lazy continuation, both of which `check_run.py` already documents having to avoid. Size: `SUMMARY_LIMIT (60,000) + FRAME_MAX ≤ 65,536` is an **asserted invariant**, not a truncation branch (a second truncation would diverge the middle silently).

**Upsert algorithm (D9):**
1. `comment_id = store.pr_comment_id(...)`. If present → `issues.update_comment(owner, repo, comment_id, body=...)`; on 404 → `store.forget_pr_comment(...)` and continue to step 2 (someone deleted it; re-create is correct and its notification cost is named in §4).
2. Else `gh.paginate(gh.rest.issues.list_comments, owner=…, repo=…, issue_number=pr_number)` **bounded** (e.g. 10 pages); a comment matches iff `(getattr(c, "body", "") or "").startswith(MARKER_PREFIX)` **and** it is App-authored (`performed_via_github_app.id == app_auth.app_id()`; fall back to `user.type == "Bot"` and the App's login). First match → store its id, parse its `seq`; if the existing `seq` > this job's → `skipped-stale`, no write; else update. A marked comment by a human is **never** matched or written.
3. No match **after the listing completed** → `store.claim_pr_comment(...)` (`INSERT … ON CONFLICT DO NOTHING`); if the claim is lost, re-read the id and update; else `issues.create_comment(owner, repo, pr_number, body=...)` and store the id.
4. A listing failure or reaching the page bound returns `failed:…` **without** creating — "none found" is only asserted after a complete listing, because the wrong default there is a duplicate comment and a fresh notification on every push for as long as the fault lasts.

Catch `githubkit.exception.RequestFailed` (403 → `denied:403`; other codes → `failed:<code>`) and `RequestError` (→ `failed:net`); everything else propagates — `upsert` has real logic and a blanket except would turn its own bugs into `failed` on 100% of PRs with nothing red. githubkit shapes: `list_comments(owner, repo, issue_number, *, per_page, page)`, `create_comment(owner, repo, issue_number, *, body)`, `update_comment(owner, repo, comment_id, *, body)`; `IssueComment.body` is `Missing[str]`.

### 3.3 Worker

In **both** post sites, after `check_run.post(...)` (which is already after `ingest.complete`, so a lost claim posts nothing):

```python
if store.repo_pr_comment(job["installation_id"], job["github_repo_id"]) and _comment_allowed(job):  # D3a allowlist, temporary
    if pr_comment.target_matches(gh, owner, name, job["pr_number"], job["github_repo_id"]):
        outcome = pr_comment.upsert(gh, owner, name, job["pr_number"],
                                    pr_comment.render(summary, head_sha=job["head_sha"], seq=job["id"],
                                                      receipt_url=pr_comment.receipt_url(owner, name, job["pr_number"])),
                                    installation_id=job["installation_id"], github_repo_id=job["github_repo_id"], seq=job["id"])
    else:
        outcome = "skipped-target"
else:
    outcome = "skipped"
print(f"doug: comment {outcome} {job['repo_full_name']}#{job['pr_number']}@{job['head_sha'][:12]}", file=sys.stderr)
```

- **Own log line**, not an amendment of the "reviewed"/"replayed" lines — those are deliberately printed *before* `ingest.complete` so a lost claim cannot erase the record of what the attempt cost.
- **`target_matches`**: `repo_full_name` is display-only and goes stale on rename (no `repository` webhook handler). The check run is safe by construction (a foreign `head_sha` 422s); a comment needs only the PR *number* to exist — a stale name could put repo A's findings and receipt link on repo B's PR within the same installation. The fresh path already fetched the PR; the replay path did not. One `pulls.get` on the replay path, assert `base.repo.id == job["github_repo_id"]`, else skip. (Tenant isolation is already bounded by the installation token; this is intra-tenant.)
- `denied:403` → `store.mark_pr_comment_denied(installation_id, now)`; `created|updated` → clear it.
- Replay re-asserts the same body (idempotent via D9). Named consequence: a replay without a new push (`reclaim_stalled`, `_revive`) can create a *first* comment on a PR reviewed before deploy — "forward-only" is "only reviews that run after deploy", not "only new pushes".

### 3.4 `check_run.py` changes (both surfaces inherit)

- `_oneline` neutralises `@` mentions, `#` / `owner/repo#` cross-references, and `<!--` in model-authored spans (D7); `_quote` routes through `_oneline` (its labels splice file paths, which may contain `@` or newlines).
- `CLEARED_NOTE` when `band == CLEARED` — *"Cleared means Doug found nothing it wanted a human to look at; it is not a statement that the change is safe."* (`experience.md` surface 4 already promised the cleared band a permanent footnote; that was tolerable folded under "1 neutral check" and is not tolerable once Cleared is promoted into the conversation).
- Header comment names the sibling and the byte-identity contract.

### 3.5 Docs

- **ADR-0014** "Doug's surface is a neutral check run and one sticky PR comment that mirrors it": Context **quotes** ADR-0010's precision clause and states plainly that this surface falls inside it, that the number does not exist, and that the decision ships anyway because invisibility is also a failure — with D3a as the mitigation. Decision D1–D9 as mechanisms, not absolutes. **Rejected** (per-push; flagged-only; short card; public receipt; deleting on opt-out — or adopting it, per D3b; gating; marker-only match; absent-row-on). Consequences: one notification per *created* comment per PR (and the delete→re-create cycle is unbounded); comments persist after opt-out and after uninstall (no bulk removal; link to a dashboard the org may no longer have); the permission's blast radius and that declining it keeps today's behaviour; the interim allowlist is temporary; the converse failure — a comment without a check run when `check_run.post` fails — is possible and means the mirror claim is one-directional; most PR readers hit sign-in on the receipt link (and become orgless WorkOS users — a support-ticket shape to expect). **Reader-fed** paragraph (ADR-0013's pattern) naming what to flag (a second comment-writing function; a review; a path that writes without an active row; neutralisation removed) and what not to (re-create after deletion; the allowlist's removal).
- **ADR-0010**: stays `accepted`; its §Rejected "PR comments" paragraph gains one sentence — *"Amended by ADR-0014: one sticky, App-authored comment that mirrors this check run, edited in place."* — because that paragraph is the text the reader actually sees, and left alone it keeps flagging the feature as a deviation from Doug's own binding record.
- `docs/design/outcome-loop/experience.md` surface 1 ("Never a comment") amended; siblings grepped for the same sentence. `/docs/changelog` row. Runbook (HANDOFF + ADR): the App-permission change is a manual step done once, before PR B deploys.
- Standing issues opened at plan time: delete-on-opt-out (D3b); "Flagged" vs "needs you" wording in `_headline` (amplified by this surface; pre-existing).

### 3.6 Out of scope

Public receipts; inline/code comments; deleting comments (D3b); anything in the frame beyond header/footer; pinning; backfilling comments on already-reviewed open PRs; alerting on `denied` beyond the dashboard banner.

## 4. Failure modes considered

- **Permission not granted (403)** — `denied:403`, logged, banner (D8); check run unaffected. A 403 also means a locked conversation, an archived repo, or secondary rate limiting — the token names the code, the banner names the usual cause.
- **Model text with side effects in a comment** — neutralised at the chokepoint for both surfaces (D7); test with a label containing `@doug`, `#1`, `owner/repo#2`, `<!--`, `](http`.
- **A human plants the marker** — never matched (authorship), never written; Doug creates its own (D9).
- **Someone deletes Doug's comment** — next review re-creates (notifies again); unbounded if repeated; named.
- **Two drainers, two jobs, one PR** — `seq` guard prevents an older verdict overwriting a newer one; the claim row prevents two creates. Residual: `SKIP LOCKED` + two instances is the deployed configuration, so this is ordinary, not exotic.
- **Listing fails / page bound hit** — `failed`, no create.
- **Comment posted, check run not** (`check_run.post` swallows) — mirror claim is one-directional; named in ADR-0014.
- **Stale `repo_full_name` on replay** — `target_matches` skip.
- **Repo with no / removed settings row** — no comment (D6).
- **`{"pr_comment": false}` clearing the flag line** — `model_fields_set` gating; test.
- **Deploy window** — PR A relaxes both web guards; PR B tightens; App permission is a third, manual step before PR B deploys.
- **`DOUG_WEB_URL` empty** — links omitted, one log line, comment still posts; `api/tests/test_deploy_gcp.py` pins the env line on the API service.

## 5. Tests that encode intent

- **Worker-level mirror test**: for one job, capture the `summary` passed to `check_run.post` and the `body` passed to `upsert`; assert `summary in body` — *the ADR's claim tested where it can actually fail* (a `render`-only test compares render's output to its own input and passes trivially).
- `pr_comment.render`: marker is line 1 and carries `head`/`seq`; blank line before the summary; two newlines before `---`; footer says sign-in required and carries both links; `receipt_url=None` → no links; `SUMMARY_LIMIT + FRAME_MAX ≤ 65_536` asserted.
- `pr_comment.upsert`: stored id → `update_comment` only; id 404 → forget, then list; human-authored marked comment → not matched, `create_comment` called; App-authored marked comment with higher `seq` → `skipped-stale`, no write; list raises → `failed`, **no** create; page bound → `failed`, no create; claim lost → update not create; 403 → `denied:403` and no raise; body `UNSET` does not crash; `RequestError` → `failed:net`.
- worker: setting off / no row / removed row → `skipped`, no GitHub call; replay path upserts the same body as the fresh path; `target_matches` false → `skipped-target`; `denied` sets `pr_comment_denied_at`, next success clears it; own `doug: comment …` line present and the "reviewed" line unchanged.
- `check_run._oneline`/`_quote`: neutralisation cases above; check-run summary with a `CLEARED_NOTE` when cleared.
- store: new repo row inserts with `pr_comment=True` (server_default); `replace=True` preserves `False`; `set_repo_pr_comment` keyed on the active installation row; `updated_at` unchanged; claim/forget round-trip.
- api: `PATCH {"pr_comment": false}` → 200 with both values and the flag line unchanged; `{}` → 422; `{"pr_commnt": false}` → 422 (`extra="forbid"`); `"true"`/`1` → 422; connections carry `pr_comment` and `pr_comment_denied_at`; audit line names only written fields.
- web: PR A — both guards accept bodies with and without the new keys; PR B — require; toggle form posts only `pr_comment`; contract test for the label and the banner copy.
- migrations: two homes for all three tables; `test_deploy_gcp` pins `DOUG_WEB_URL` on the API service.
