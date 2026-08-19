# One sticky PR comment that mirrors the check run

**Date:** 2026-08-19
**Status:** design approved in chat 2026-08-19 (D1–D5 locked); awaiting adversarial review, then an implementation plan
**Branch:** `claude/sticky-pr-comment` (depends on #120 — the per-repo settings row, `PATCH /v1/sessions/repositories/{id}`, and the Repositories view control)
**Amends:** ADR-0010's rejection of PR comments (→ ADR-0014); the check run and its `neutral` conclusion stand

---

## 1. The gap

Doug's only surface on a pull request is one check run named `Doug`, conclusion always `neutral` (ADR-0010, `api/doug/check_run.py`). GitHub folds neutral checks under "1 neutral check", below the required checks; on #119 the verdict *Cleared · risk 0.16 · diff read* was there and effectively invisible. A surface nobody sees is not the conservative option — it is the absent one, which is the same argument ADR-0010 itself made against shipping the App with no surface at all.

ADR-0003 and ADR-0010 rejected PR comments for one stated reason: *a wrong comment notifies every subscriber and it persists.* That reasoning targeted a comment that would say something new. A comment whose body is the check run's, edited in place on every push, notifies once (on creation — edits do not notify) and persists exactly as much as the check run already does. That is the specific counter this spec makes, and ADR-0014 records it.

## 2. Decisions (locked)

- **D1 — One sticky comment per PR, edited in place.** Identified by the first line `<!-- doug:verdict -->`. On every review of the PR the worker finds the marked comment and PATCHes it; it POSTs only when none exists. Never a second comment; never a review (approve / request-changes); never an inline comment on code. Rejected: a comment per push (notification spam — what the ADRs actually rejected); comment only when flagged (the cleared case is the one that was invisible).
- **D2 — Body = fixed frame around `check_run.render()`'s summary, verbatim.** Header line, the check-run summary byte-for-byte, footer with the receipt link. The middle never diverges from the check run; the frame (header/footer) is where later additions land. Rejected: a short card + link (findings stay a click away — the "never viewed" problem again); a distinct richer layout first (prettier than it is honest until the data behind it exists).
- **D3 — On by default, opt-out per repository.** `installation_repos.pr_comment BOOLEAN NOT NULL DEFAULT TRUE`, toggled beside the flag line. Consequence stated plainly: on deploy, every installed repository's **next reviewed PR** gets a comment (one per PR, forward-only, nothing retroactive). Turning it off leaves existing comments as they are — Doug never deletes; it stops updating. Rejected: off by default (the feature would exist for two repos); split by band.
- **D4 — Link target is the dashboard receipt page** `{DOUG_WEB_URL}/dashboard/pr/{number}?repo={owner/name}` — exists today, session-bound. Rejected: a public unauthenticated receipt (a new tenancy surface, bigger than this feature); no link.
- **D5 — Permission failure is swallowed and logged, and changes nothing else.** Posting needs the App permission `pull_requests: write`, set in the GitHub App settings (not in this repo); every existing installation must re-accept it. Until they do the call 403s; the worker logs and moves on; the check run is unaffected. Rejected: gating the review on the comment (ADR-0010: the check run is the output of a review, not a step in one — same for the comment).

## 3. Design

### 3.1 Storage + setting

`installation_repos.pr_comment BOOLEAN NOT NULL DEFAULT TRUE` — both homes (Table + migration; next free version at implementation time — 11 is taken by #120, so 12 unless MT3 lands first). `set_installation_repos` never touches it (same rule and test as `needs_you_threshold`). Store: `repo_pr_comment(installation_id, github_repo_id) -> bool` (`True` when the row is absent — the worker only runs for rows that exist, and the column is `NOT NULL DEFAULT TRUE`, so absent-means-default is the only consistent reading) and `set_repo_pr_comment(installation_id, github_repo_id, value: bool) -> bool` (active row only; never bumps `updated_at`).

`PATCH /v1/sessions/repositories/{github_repo_id}` body becomes `{"needs_you_threshold"?: number|null, "pr_comment"?: bool}` — **at least one key required** (`{}` stays 422), each key strict (`pr_comment` rejects `"true"` and `1`), same `settings:write` scope, same keyed write, same audit line with the field named. Response returns both current values `{"needs_you_threshold": …, "pr_comment": …}`. `GET /v1/sessions/connections` `repositories[]` entries gain `pr_comment: bool`. Web: guards tightened in the same two-PR pattern as #119/#120 (**PR A**: web tolerates the key; **PR B**: everything else), types, `setRepositoryPrComment(accessToken, id, value)`, a toggle inside the flag-line control's disclosure ("PR comment · on/off"), contract test that the label exists.

### 3.2 `api/doug/pr_comment.py` (new; sibling of `check_run.py`)

```python
MARKER = "<!-- doug:verdict -->"

def receipt_url(owner: str, repo: str, pr_number: int) -> str | None:
    """{DOUG_WEB_URL}/dashboard/pr/{n}?repo={owner/repo}, or None if the env is unset."""

def render(title: str, summary: str, *, threshold: float, receipt_url: str | None) -> str:
    """MARKER, a one-line header, the check-run summary VERBATIM, a footer."""

def upsert(gh, owner: str, repo: str, pr_number: int, body: str) -> str:
    """Find the marked comment (issues.list_comments, paginated, first whose
    body startswith MARKER) -> issues.update_comment; else issues.create_comment.
    Never raises: 403 (permission not granted), 404 (PR gone), 5xx, network
    are logged to stderr and swallowed. Returns created|updated|denied|failed."""
```

Header: `**{title}** — flag line {threshold:.2f} · not a gate`. Footer: `---` then `Doug · [full receipt on Doug HQ]({receipt_url}) · the flag line is set per repository on the Doug dashboard` (without the link when `receipt_url` is `None`). Body cap is GitHub's 65,536 chars; the summary is already ≤ `SUMMARY_LIMIT = 60_000`, so the frame fits; if the total would exceed the cap, truncate the *summary* with the same truncation notice pattern `check_run` uses — never the marker or footer. The marker is line 1 so `startswith` is exact; a human comment that merely mentions the string mid-body is not matched.

`DOUG_WEB_URL` is new; `deploy/gcp.sh` sets it on the API service to the web service URL. Absent → link omitted and one stderr line per process (`doug: DOUG_WEB_URL unset; PR comment carries no receipt link`); the comment still posts.

### 3.3 Worker

In **both** post sites — the fresh path after `check_run.post(...)` and `_replay_recorded` after its `check_run.post(...)`:

```python
if store.repo_pr_comment(job["installation_id"], job["github_repo_id"]):
    outcome = pr_comment.upsert(
        gh, owner, name, job["pr_number"],
        pr_comment.render(
            title, summary, threshold=verdict.threshold,
            receipt_url=pr_comment.receipt_url(owner, name, job["pr_number"]),
        ),
    )
else:
    outcome = "skipped"
```

Same ordering rule as the check run: after `ingest.complete` (a lost claim posts nothing). Replay re-asserts the same body — idempotent by construction. The success log gains `comment={outcome}`.

### 3.4 Docs

ADR-0014 "Doug's surface is a neutral check run and one sticky PR comment that mirrors it" — Context (the fold; #119), Decision (D1–D5), **Rejected** (per-push comments; flagged-only; short card; public receipt; deleting on opt-out; gating the review), Consequences (first-day notification per active PR; the App-permission re-accept and the 403 posture; the frame as the growth point; ADR-0010's PR-comments rejection is amended *only* on this point — the check run and its neutral conclusion stand). ADR-0010 stays `accepted` and is not marked superseded; ADR-0014's Context says "amends ADR-0010 §Rejected / PR comments". `check_run.py` header gains one sentence naming the sibling. Runbook line (HANDOFF + the ADR): the App-permission change is a manual step in GitHub App settings, done once, before PR B deploys.

### 3.5 Out of scope

Public receipts; inline/code comments; deleting comments on opt-out or uninstall; anything in the frame beyond header/footer (risk-over-pushes, weekly repo counts — later, on the same frame); pinning the comment (`issues.pin_comment` — pins are shared state and one more thing to explain; revisit); backfilling comments on already-reviewed open PRs.

## 4. Failure modes considered

- **Permission not granted (403)** — logged, swallowed, check run unaffected (D5); test.
- **Two workers race on the same PR** — both list, both see none, both create → two comments. `ingest.complete` serialises "who posts" per job, and pushes to one PR are processed FIFO by one drainer today, so this needs two drainers on two jobs for the same PR at once. Documented, not solved: the next upsert updates the *first* marked comment and the duplicate stays. Named as a consequence in ADR-0014.
- **Marker spoofed by a human** — `startswith(MARKER)` on the raw body; a comment that deliberately starts with the marker gets overwritten — acceptable and unlikely.
- **PR closed/converted between review and post** — 404/422 swallowed like the check run.
- **Body over 65,536** — summary truncated with notice; marker + footer intact.
- **`DOUG_WEB_URL` unset** — link omitted, logged once, comment still posts.
- **Setting toggled off mid-flight** — read at post time; the last comment stays as-is.
- **Deploy order** — as #119/#120: web tolerates `pr_comment` in `repositories[]` first (PR A), then API emits + UI reads (PR B). The App permission is a third, manual step done before PR B deploys.

## 5. Tests that encode intent

- `pr_comment.render`: the middle is **byte-identical** to the `summary` passed in — *the ADR argument as a test: the comment says nothing the check run doesn't*; marker is line 1; footer carries the receipt URL; `receipt_url=None` → footer without a link.
- `pr_comment.upsert`: marked comment present → `update_comment` called and `create_comment` not — *edits don't notify; one comment per PR*; absent → `create_comment`; a comment merely containing the marker mid-body is not matched; 403/404/5xx → no raise, stderr line, returns `denied`/`failed`.
- worker: setting off → no comment call and `comment=skipped`; replay path upserts the same body as the fresh path; a 403 leaves the check run posted.
- store: `set_installation_repos(replace=True)` preserves `pr_comment`; `set_repo_pr_comment` keyed on the installation row; `updated_at` unchanged.
- api: PATCH `{"pr_comment": false}` → 200 with both values; `"true"`/`1` → 422; `{}` still 422; connections carry `pr_comment`; audit line names the field.
- web: guards accept (PR A) then require (PR B) `pr_comment`; toggle wired; contract test.
- migrations: two homes.
