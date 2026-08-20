"""One sticky PR comment that mirrors the check run. Sibling of check_run.py.

The middle of the body is `check_run.render()`'s summary BYTE-FOR-BYTE; the
frame says only what the summary cannot — which commit it is about, that it
is edited in place rather than re-posted, and where the full receipt is.
Anything that must not reach a live PR conversation is neutralised once, in
`check_run._oneline`, so both surfaces stay identical (ADR-0014 / D7). Do not
sanitise here: a second pass would diverge the middle silently, which is the
one thing the mirror claim cannot survive.

Three rules in `upsert` are load-bearing (D9, spec §3.2):

  * Authorship, not the marker, decides ownership. With `pull_requests:
    write` the App can edit ANY comment on the PR, and anyone can post one
    starting with the marker on a public repo.
  * `seq` (the job id) guards the write. Two drainers are the deployed
    configuration (`--max-instances 2`, `SKIP LOCKED`), so an older job
    finishing last is ordinary, not exotic.
  * "No comment exists" is concluded only after a listing that COMPLETED.
    The wrong default there is a duplicate comment — and a fresh
    notification — on every push for as long as the fault lasts.
"""

import os
import re
import sys
from typing import NamedTuple
from urllib.parse import quote

from githubkit.exception import RequestError, RequestFailed

from . import app_auth, store

# Matched with startswith() against the raw body's first line.
MARKER_PREFIX = "<!-- doug:verdict"
_MARKER_RE = re.compile(r"^<!-- doug:verdict head=([0-9a-f]{7,64}) seq=(\d+) -->")

# D3a: the interim allowlist. Parsed exactly like intent.enabled_for's, and
# for the same reason — an unset allowlist enables nobody, not everybody.
ALLOWLIST_ENV = "DOUG_PR_COMMENT_INSTALLATIONS"

_PER_PAGE = 100
_PAGE_BOUND = 10

# GitHub rejects a comment body over 65,536 chars outright. The frame is
# bounded so `check_run.SUMMARY_LIMIT + FRAME_MAX <= 65_536` holds, and
# `render` ENFORCES that bound on the frame rather than trusting it: the
# summary half is capped in `check_run.render`, but the frame carries
# DOUG_WEB_URL, which is operator-controlled and unbounded. The middle is
# never truncated here — that would diverge it from the check run without
# saying so — so an oversized frame drops its links instead (see `render`).
FRAME_MAX = 1_000

_DOCS_PATH = "/docs/what-doug-gets-wrong"
_WARNED_NO_WEB_URL = False


def allowed(installation_id: int) -> bool:
    """Is the sticky comment on for THIS installation (D3a)?

    Temporary: the allowlist exists so the first weeks of a surface that
    notifies real reviewers are scoped to installs that agreed to it. An
    empty or unset env enables nobody.
    """
    allow = os.environ.get(ALLOWLIST_ENV, "")
    return str(installation_id) in {i.strip() for i in allow.split(",") if i.strip()}


class Links(NamedTuple):
    """The footer's two destinations, carried together rather than one being
    reconstructed from the other.

    The docs URL used to be derived by splitting the receipt at
    '/dashboard/', which silently pointed a link in a PUBLIC PR comment at
    the wrong place whenever DOUG_WEB_URL itself contained that path. The
    split existed so `render` would stay a pure function of its arguments —
    a second os.environ read there could disagree with the URL the caller
    was handed — and that motivation still holds: the caller supplies the
    base too.
    """

    base: str
    receipt: str


def receipt_links(owner: str, repo: str, pr_number: int) -> Links | None:
    """The footer's links for this PR, or None when DOUG_WEB_URL is unset.

    `or None` rather than a plain get: Cloud Run sets DOUG_WEB_URL="" on a
    bootstrap deploy, before doug-web exists, and an empty base would render
    a link to "/dashboard/...".
    """
    global _WARNED_NO_WEB_URL
    base = os.environ.get("DOUG_WEB_URL") or None
    if base is None:
        if not _WARNED_NO_WEB_URL:
            _WARNED_NO_WEB_URL = True
            print(
                "doug: DOUG_WEB_URL unset — PR comments will carry no receipt link",
                file=sys.stderr,
            )
        return None
    base = base.rstrip("/")
    slug = quote(f"{owner}/{repo}", safe="")
    return Links(base=base, receipt=f"{base}/dashboard/pr/{pr_number}?repo={slug}")


def _body(summary: str, *, head_sha: str, seq: int, links: Links | None) -> str:
    header = (
        f"_The `Doug` check run for {head_sha[:7]}, repeated here in full. "
        "Doug edits this comment in place on every review; it is never re-posted._"
    )
    if links is None:
        footer = "Doug · not a gate"
    else:
        footer = (
            f"Doug · [full receipt on Doug HQ]({links.receipt}) — sign-in required · "
            f"[what Doug gets wrong]({links.base}{_DOCS_PATH})"
        )
    marker = f"{MARKER_PREFIX} head={head_sha} seq={seq} -->"
    return f"{marker}\n\n{header}\n\n{summary}\n\n---\n{footer}"


def render(summary: str, *, head_sha: str, seq: int, links: Links | None) -> str:
    """The comment body: marker line, blank line, one italic header line,
    blank line, the check-run summary VERBATIM, two newlines, `---`, footer.

    The joins are pinned, not incidental. `check_run.render` can end on a
    list item (`- none`) or a plain paragraph, and a `---` on the very next
    line is a setext `<h2>` underline or a GFM lazy continuation — the same
    defect `check_run._footer` already documents having to avoid.

    FRAME_MAX is checked, not assumed. The links carry DOUG_WEB_URL, which
    no one bounds, and a frame over its budget puts a full-length body past
    GitHub's 65,536-char cap — which fails EVERY write for that PR with a
    422 that reads like a GitHub fault. Degrading to the no-link footer
    (already the shape used when DOUG_WEB_URL is unset) keeps the mirror,
    which is the half that exists nowhere else, and loses only two links
    that a misconfigured base was pointing wrong anyway. The raise below is
    a backstop for a frame that overruns without any links to drop: the
    worker's `except Exception` turns it into a loud `failed:internal`.
    """
    body = _body(summary, head_sha=head_sha, seq=seq, links=links)
    if links is not None and len(body) - len(summary) > FRAME_MAX:
        print(
            f"doug: comment frame is {len(body) - len(summary)} chars, over FRAME_MAX "
            f"({FRAME_MAX}) — check DOUG_WEB_URL; posting without links",
            file=sys.stderr,
        )
        body = _body(summary, head_sha=head_sha, seq=seq, links=None)
    frame = len(body) - len(summary)
    if frame > FRAME_MAX:
        raise RuntimeError(f"comment frame is {frame} chars with no links, over {FRAME_MAX}")
    return body


def _is_ours(comment) -> bool:
    """A comment is Doug's iff it carries the marker AND this App wrote it.

    Marker-only matching is a slot hijack: any account can post
    `<!-- doug:verdict ...` on a public repo, and the App's
    `pull_requests: write` would then let Doug rewrite a human's comment
    under their name. With no app id configured nothing matches — the open
    failure is a duplicate, never an overwrite of someone else's text.
    """
    body = getattr(comment, "body", "") or ""  # IssueComment.body is Missing[str]
    if not body.startswith(MARKER_PREFIX):
        return False
    ours = app_auth.app_id()
    if not ours:
        return False
    app = getattr(comment, "performed_via_github_app", None)
    return app is not None and str(getattr(app, "id", "") or "") == str(ours)


def _seq_of(comment) -> int:
    """The job id in an existing comment's marker; 0 when it has none (an
    older format, or ours by authorship but with an unreadable marker) —
    which loses the guard rather than the write."""
    match = _MARKER_RE.match(getattr(comment, "body", "") or "")
    return int(match.group(2)) if match is not None else 0


def _log(owner: str, repo: str, pr_number: int, outcome: str, detail: str | None) -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"doug: comment {outcome} on {owner}/{repo}#{pr_number}{suffix}", file=sys.stderr)


def target_matches(gh, owner: str, repo: str, pr_number: int, github_repo_id: int) -> bool:
    """Does this PR number really belong to the repo the job names?

    `repo_full_name` is display-only and goes stale on rename (there is no
    `repository` webhook handler). The check run is safe by construction — a
    foreign head_sha 422s — but a comment needs only the PR number to exist,
    so a stale name could put repo A's findings and receipt link on repo B's
    PR inside the same installation. Cross-tenant is already bounded by the
    installation token; this is the intra-tenant case.
    """
    try:
        pull = gh.rest.pulls.get(owner=owner, repo=repo, pull_number=pr_number).parsed_data
    except (RequestFailed, RequestError):
        return False
    base = getattr(pull, "base", None)
    base_repo = getattr(base, "repo", None) if base is not None else None
    return base_repo is not None and base_repo.id == github_repo_id


def upsert(
    gh,
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    *,
    installation_id: int,
    github_repo_id: int,
    seq: int,
) -> str:
    """Write the sticky comment. Returns one of:

    `created` | `updated` | `skipped-stale` | `denied:403` | `failed:<code>` |
    `failed:net` | `failed:page-bound`.

    Only `RequestFailed`/`RequestError` become an outcome. Everything else
    propagates: this function has real logic, and a blanket except would
    report its own bugs as `failed` on 100% of PRs with nothing red anywhere.
    """
    key = (installation_id, github_repo_id, pr_number)
    try:
        stored = store.pr_comment_id(*key)
        if stored is not None:
            try:
                gh.rest.issues.update_comment(
                    owner=owner, repo=repo, comment_id=stored, body=body
                )
                return "updated"
            except RequestFailed as e:
                if e.response.status_code != 404:
                    raise
                # Someone deleted Doug's comment. Release the claim so the
                # create below can be reached; the re-notification that costs
                # is named in the ADR's consequences.
                store.forget_pr_comment(*key)

        found = None
        for page in range(1, _PAGE_BOUND + 1):
            batch = gh.rest.issues.list_comments(
                owner=owner,
                repo=repo,
                issue_number=pr_number,
                per_page=_PER_PAGE,
                page=page,
            ).parsed_data
            found = next((c for c in batch if _is_ours(c)), None)
            if found is not None or len(batch) < _PER_PAGE:
                break
        else:
            # A PR longer than the bound is indistinguishable from a broken
            # listing, and neither may fall through to create.
            _log(owner, repo, pr_number, "failed:page-bound", f"{_PAGE_BOUND} pages")
            return "failed:page-bound"

        if found is not None:
            # Record where it is even when the write is skipped: the next job
            # should not have to list again to find it.
            store.claim_pr_comment(*key)
            store.set_pr_comment_id(*key, found.id)
            if _seq_of(found) > seq:
                return "skipped-stale"
            gh.rest.issues.update_comment(
                owner=owner, repo=repo, comment_id=found.id, body=body
            )
            return "updated"

        if not store.claim_pr_comment(*key):
            other = store.pr_comment_id(*key)
            if other is not None:
                gh.rest.issues.update_comment(
                    owner=owner, repo=repo, comment_id=other, body=body
                )
                return "updated"
            # Claim held by a drainer that has not created yet (or died
            # before it could). Creating is the specified direction: a
            # duplicate is visible and self-corrects on the next listing,
            # whereas skipping would leave a dead slot and no comment ever.
        created = gh.rest.issues.create_comment(
            owner=owner, repo=repo, issue_number=pr_number, body=body
        ).parsed_data
        store.set_pr_comment_id(*key, created.id)
        return "created"
    except RequestFailed as e:
        code = e.response.status_code
        outcome = "denied:403" if code == 403 else f"failed:{code}"
        detail = f"HTTP {code}"
    except RequestError as e:
        outcome = "failed:net"
        detail = f"{type(e.exc).__name__}: {e.exc}"
    _log(owner, repo, pr_number, outcome, detail)
    return outcome
