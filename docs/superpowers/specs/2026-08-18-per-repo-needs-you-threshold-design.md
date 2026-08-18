# Per-repo "needs you" threshold

**Date:** 2026-08-18
**Status:** design approved in chat 2026-08-18 (D1–D3 locked below); awaiting adversarial review, then an implementation plan
**Branch:** `claude/per-repo-needs-you-threshold-f075db`

---

## 1. The gap

Doug decides "needs you" by comparing a 0–1 score to a line. That line is
**process-wide** today, and nothing a tenant can reach moves it:

- `DOUG_THRESHOLD` (default `0.62`) — the deterministic scorer,
  `api/doug/scoring.py:21` (`default_threshold()`), compared at
  `scoring.py:146` with `>=`.
- `DOUG_READER_THRESHOLD` (default `30`, in 0–100 risk points) — the LLM
  reader, `api/doug/reader.py:347` (`reader_threshold()`), compared at
  `reader.py:957` with `>=`, and normalised to 0–1 when stamped on the
  verdict (`reader.py:971`, `threshold=thr / 100`).

Both `score()` (`scoring.py:138`) and `verdict_from_reader()`
(`reader.py:955`) already accept an optional `threshold` argument. **No
production caller passes one.** `review.score_one()` (`review.py:303`) — the
single scoring seam the worker uses (`worker.py:250`) — has no `threshold`
parameter at all, so its four exits (`reader`, `reader-capped`,
`reader-unavailable`, `deterministic`) all fall through to the env default.

The resolved line is stamped on every verdict (`store.py:75`,
`verdicts.threshold NOT NULL`) and printed in the check run
(`check_run.py:143`, "Risk 0.71 against a flag line of 0.62"). The
dashboard's threshold **lens** (`web/lib/threshold-lens.ts`) can re-band
recorded scores against a reader-chosen line — as a *view* — and its header
comment argues the line "is not a setting because it cannot be." That
statement describes the current wiring, not a constraint; this spec reverses
it deliberately.

A docs-only repo and a Terraform repo have very different costs for a false
"needs you", and today they share one line.

## 2. Decisions (locked)

- **D1 — Forward-only.** The setting changes verdicts scored *after* it is
  set. Existing verdicts keep the threshold they were scored against; the
  ledger stays a record of what Doug did and posted. The lens remains the
  way to preview a different line over history. Rejected: retroactive
  re-banding of the ledger (the ledger would stop matching the check runs
  posted to GitHub).
- **D2 — Dashboard setting, stored per repo.** A nullable column on
  `installation_repos`, written through a session-authenticated API
  endpoint, edited on the dashboard's Repositories view. Rejected: an
  in-repo config file (`.doug.yml`) — adds a file fetch per review, and the
  dashboard could display but not edit it; and "both" — two sources of
  truth. A repo-file source can be layered later without changing the
  column or the resolution seam.
- **D3 — One 0–1 number, applied to both scorers.** Verdicts already
  normalise to 0–1 and the lens shares that range. The reader receives
  `value * 100`. Rejected: separate deterministic/reader settings (two
  knobs for one question, and the tenant never sees which scorer ran until
  after the fact).

**Non-goal, named so it isn't smuggled in:** per-repo *scope* rules ("for
docs repos only look at structure/config files, not content"). That is a
different feature — it changes what Doug looks at, not where the line sits.
A 0.9 line on a docs repo means "flag only when the score is very high"
(the deterministic scorer caps at 0.99; most rules weigh 0.20–0.35), which
is close to "flag nothing" — the tenant should see that plainly, not have
it dressed up as scoping.

## 3. Design

### 3.1 Storage

`installation_repos.needs_you_threshold FLOAT NULL` — both homes per
`migrations.py`'s module docstring: the `Table` definition at `store.py:221`
**and** migration version 11:

```
ALTER TABLE installation_repos ADD COLUMN needs_you_threshold FLOAT
```

`NULL` means "inherit the process default" — the state every existing row
is in and the state a new repo row is created in. There is no per-tenant
or per-installation tier; a repo either has its own line or uses the
default. `store.set_installation_repos()` (webhook path, `api.py:2184`,
`:2194`, `:2215`) must **preserve** the column when it upserts or replaces
rows for an installation — a `installation_repositories` webhook or a
re-sync must not silently reset a tenant's setting. If `replace=True`
currently deletes-and-reinserts, that path needs to carry the value across
(or become an upsert that leaves the column alone). This is a test, not a
note.

Range is `0 ≤ x ≤ 1`, endpoints included, matching `threshold-lens.ts`
(`MIN_LENS`/`MAX_LENS`) and the reason it gives: 0 ("flag everything") and
1 ("flag nothing this scorer reaches" — `score()` caps at 0.99, so 1 is
unreachable and bands everything cleared) are both legitimate requests.
Validated at the write endpoint (§3.3), never coerced.

### 3.2 Resolution and the scoring seam

One read, one place:

```python
# store.py
def repo_threshold(installation_id: int, github_repo_id: int) -> float | None:
    """The repo's own needs-you line, or None to inherit the default."""
```

Reads `installation_repos` by `(installation_id, github_repo_id)` regardless
of `state` — a repo removed mid-job still scores against the line it was
configured with; the job admission path is what refuses removed repos.

`review.score_one()` gains `threshold: float | None = None` and threads it
to **every** exit:

- `reader.verdict_from_reader(rv, threshold=None if t is None else t * 100)`
- `score(meta, threshold=t)` on `reader-capped`, `reader-unavailable`, and
  the reader-disabled path.

The fallbacks matter as much as the happy path: a capped read on a 0.9 repo
must not band at 0.62 because the fallback forgot the argument. Both
functions keep their `None → env default` behaviour, so every other caller
(`review.py:463` example-pack replay with `SENTINEL_SCOPE`, `api.py:245`,
tests) is unchanged.

`worker.py:250` becomes:

```python
threshold = store.repo_threshold(job["installation_id"], job["github_repo_id"])
tier, verdict, rv, cov = review.score_one(
    meta, diff, scope=scope, threshold=threshold,
    resolve_file=resolve, resolve_schema=store.columns_of,
)
```

Read **inside the job**, at scoring time — not at admission — so the line
in effect when Doug actually scores is the one stamped. `Verdict.threshold`
is stamped exactly as today, so:

- the ledger row records the line the repo had (`verdicts.threshold`);
- the check run prints it (`check_run.py:143`) with no change;
- the queue's mode-of-thresholds heuristic (`api.py:286`) keeps working and
  now has something real to be a mode of;
- `_replay_recorded` (a peer already owns the identity) replays the peer's
  stamped line, which is correct — the peer scored it.

Nothing else in the review pipeline changes. `read_intent` is unaffected;
the settle/coverage notices append to `verdict.reasons` after banding as
they do now.

### 3.3 API

**Write.** `PATCH /v1/sessions/repositories/{github_repo_id}` — body
`{"needs_you_threshold": <number 0..1> | null}` → `204`. Authenticated by
`session_auth.resolve_session()` — the scoped, org-bound path, not the
claims-only path `GET /v1/sessions/connections` uses, because this writes.
The `github_repo_id` must be in the session's **live** scope (the same
`tenancy` intersection reads use, which honours `installations.state` and
`installation_repos.state`); a removed repo, another tenant's repo, or a
stale entitlement fails closed. Out-of-scope is `404`, not `403` — same
posture as the run detail endpoints: do not confirm the repo exists.

Validation (`422` on failure): a JSON number, finite, `0 ≤ x ≤ 1`, or JSON
`null` to clear. Strings are rejected even if numeric — `"62"` and `"0.9"`
both `422` — mirroring `parseThresholdLens`'s refusal to guess. Storage
rounds to two decimals to match `Verdict.score`'s precision
(`scoring.py:147`) — a line of `0.6249` and a score of `0.62` would compare
in a way the display could not show.

`updated_at` on the row is bumped. No audit trail beyond that in this spec
(the verdicts themselves record which line each PR was scored against, and
that is the trail that matters to a tenant).

**Read.** `GET /v1/sessions/connections` (`api.py:1877`) adds
`needs_you_threshold: number | null` to each entry of `repositories[]`.
`store.session_connections_for()` (`store.py:3189`) is where the repo list
is built, so the column joins there. Additive: nothing that reads
`repositories[]` today breaks. The response also carries the process
default once, top-level — `default_needs_you_threshold: number` — so the
dashboard can print "0.62 (default)" without knowing `DOUG_THRESHOLD`.
(The reader default is intentionally *not* exposed as a second number: D3
says one line; the tenant's setting is what they see and what both scorers
honour, and the process default surfaced is the deterministic one that the
unset state's stamped verdicts already show.)

### 3.4 Web

`web/lib/session-api.ts`: `RepositoryConnection.repositories[]` gains
`needs_you_threshold: number | null`; `ConnectionsResponse` gains
`default_needs_you_threshold: number`; a `setRepositoryThreshold(accessToken,
githubRepoId, value)` client for the PATCH.

Dashboard Repositories view (`web/app/dashboard/page.tsx`, repositories
table around `:833`): each row shows its line — "0.62 · default" or "0.90"
— with an edit affordance that opens a small inline control (the
`threshold-gear` visual language, but visibly a *setting*: distinct label,
distinct placement from the ledger's lens, and a "Reset to default"
action). Submit goes through a server action in
`web/app/dashboard/actions.ts` → PATCH → `revalidatePath`. Copy under the
control, verbatim intent: **"Applies to reviews from now on. Past verdicts
keep the line they were scored against."**

Only `status: "ready"` connections get the control; `setup_required` and
`reauthorize_required` rows show the value read-only if present, since the
write path would fail closed anyway and a disabled control is more honest
than a failing one.

The `threshold-lens.ts` header is rewritten: the lens is a **preview** over
recorded scores; the **setting** is per-repo, forward-only, and lives on
`installation_repos`. Both stay, with distinct jobs, and the comment names
the other so a reader landing on either finds both. Same reversal recorded
as `docs/decisions/ADR-0013-needs-you-line-is-a-per-repo-setting.md`
(short: context, decision D1–D3, consequences — including that the lens's
"cannot be a setting" argument no longer holds and why the lens survives).

Console (`console/`) is untouched: the five byte-locked readers
(`buildFacets`, `matchesFacets`, `groupRunsByPr`, `BandChip`,
`runMatchesQuery`) still read `run.band` and nothing here changes what
`band` means on a row.

### 3.5 Out of scope (named)

- Lens auto-defaulting to the repo's setting when the ledger is filtered
  to one repo. Nice later; not needed to ship the setting.
- Per-installation / per-org default tiers.
- Re-scoring open PRs when the setting changes. A tenant who wants a PR
  re-banded pushes a commit or re-runs the check, as today.
- Per-repo scope/path rules (§2 non-goal).
- Exposing the setting on the tenant API-key surface (`/v1/queue` etc.).

## 4. Failure modes considered

- **Setting reset by webhook re-sync.** Covered in §3.1; a test asserts
  the column survives `set_installation_repos(..., replace=True)`.
- **Fallback path forgets the line.** §3.2 threads it to all four exits;
  the worker test below exercises the `reader-unavailable` path
  explicitly.
- **Cross-tenant write.** Endpoint resolves scope via the same live
  intersection reads use; out-of-scope is `404`.
- **A percentage typed as `62`.** `422`; the UI control is a bounded
  numeric input in 0–1 (step 0.01 — the same units the check run and the
  lens already speak), never a free-text field that could send `62`.
- **Reader unit mismatch.** Reader receives `t * 100` and stamps `/100`;
  the stamped `verdicts.threshold` equals the tenant's setting on both
  scorers, and a test asserts it does.
- **Deploy ordering.** Column is nullable and `apply()` runs after
  `create_all()`; old code ignores the column, new code treats absent as
  `None`. No in-flight data at risk (ADR-0011).

## 5. Tests that encode intent

- `worker` / `review`: a PR whose deterministic score is `0.71` bands
  `flagged` on an unset repo and `cleared` on a repo set to `0.9`; and the
  same on the `reader-unavailable` fallback — *because the setting must
  reach the scoring seam and survive fallback, or the tenant's line is
  fiction on exactly the reviews they can't see happening.*
- `reader.verdict_from_reader`: a repo line of `0.5` bands a `risk_score`
  of `50` `flagged` and `49` `cleared`, and stamps `threshold == 0.5` —
  *one number, both scorers, no unit leak.*
- `store`: `set_installation_repos(replace=True)` after a set threshold
  leaves it in place; `repo_threshold` returns `None` for unset and for an
  unknown repo — *webhooks must not erase tenant configuration.*
- `api`: PATCH `422` on `1.5`, `-0.1`, `"0.9"`, `NaN`; `204` on `0.9` and
  `null`; `404` for a repo outside the session's live scope; connections
  response carries the value and the default — *fail closed, don't guess,
  don't leak.*
- `migrations`: version 11 present, two-homes agreement (the existing
  drift test pattern).
- `web/lib/session-api.test.mjs`: new fields parse; `setRepositoryThreshold`
  sends a JSON number or `null`, never a string.
