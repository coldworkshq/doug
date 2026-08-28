"""The merge commit sha, from the field that is going away or the event that is not.

GitHub is removing the long-deprecated `merge_commit_sha` and `assignee` from
REST pull payloads (#259). During the rollout the same request returns 46 keys
or 48 depending on which backend pool it lands on, and responses are sticky per
keep-alive connection — so one long-lived client can see the trimmed shape for
every PR it reads. That is what made `doug-outcome-reconciler` sweep zero on
both of its first executions: the guard worked, the field it guards failed.

The issue events API carries the same fact and is not part of the deprecated
pair. A merged PR has exactly one `merged` event, whose `commit_id` is the merge
commit. Checked against five merged PRs on 2026-08-28 (#84, #111, #252, #257,
#260): `commit_id` identical to `merge_commit_sha` in every case, on 2-5 events
per PR, so the fallback is one page and one call.

Events, not the timeline: the timeline interleaves comments and review threads,
so a busy PR pages many times to reach the same event.

One helper, called from both places that need the fact. `worker.reconcile_outcomes`
is the site that is failing today; `api._record_merge` is the site that fails
when the removal reaches webhook serialization, and covering it now is the
difference between a fix and a second incident.
"""

import re
import sys

_PER_PAGE = 100
# A merged PR carries a handful of issue events, not hundreds. The cap is here
# so that a pathological thread cannot turn one reconcile pass into an
# unbounded page walk with the whole installation waiting behind it. It is a
# request budget, not a reachable depth — see the walk order below.
_MAX_PAGES = 3

# rel="last" from a Link header, which is how GitHub says how many pages there
# are without a count endpoint.
_LAST_PAGE = re.compile(r'[?&]page=(\d+)[^>]*>;\s*rel="last"')


def _usable(value, column) -> str | None:
    """A sha that will survive the INSERT, or None.

    Mirrors `api._text(raw, column)` deliberately rather than importing it:
    that helper lives in the web layer, and this module is called from the
    worker, which must not import the API to write a row. The length check is
    the same one and exists for the same reason — the column is a VARCHAR and
    Postgres answers an over-long INSERT with StringDataRightTruncation, which
    here would unwind a whole installation's pass.
    """
    if not isinstance(value, str) or not value:
        return None
    if len(value) > column.type.length:
        return None
    return value


def _last_page(headers) -> int | None:
    """The `rel="last"` page number from a Link header, or None."""
    link = headers.get("link") or headers.get("Link")
    if not link:
        return None
    found = _LAST_PAGE.search(link)
    return int(found.group(1)) if found else None


def from_merged_event(client, *, owner: str, repo: str, number: int, column) -> str | None:
    """The `commit_id` of the PR's `merged` event, or None.

    **Walks backwards from the last page after the first.** Issue events come
    back oldest-first and a merge is the last thing that happens to a PR, so on
    a busy thread the event is at the END. Doug caught the first version of this
    walking forward under a 3-page cap (`reader:incomplete-pagination`) and was
    right about the consequence being permanent rather than retried: the
    reconciler uses this same helper on every pass, so a PR past the cap would
    be skipped forever, silently. Page 1 is still tried first because almost
    every PR fits there — five checked on 2026-08-28 carried 2 to 5 events — and
    that keeps the ordinary case at one call.

    Fails soft on everything. A transport error, an unreadable body, a PR with
    no merged event, or a commit_id too long for the column all return None and
    leave the caller's existing skip path in charge. This is a fallback for a
    fact the caller has already failed to get; it must not be able to turn a
    skipped row into a raised exception.
    """
    page, budget, last = 1, _MAX_PAGES, None
    while page is not None and budget > 0:
        try:
            resp = client.rest.issues.list_events(
                owner=owner, repo=repo, issue_number=number,
                per_page=_PER_PAGE, page=page,
            )
            events = resp.raw_response.json()
        except Exception as e:  # noqa: BLE001 — one unreadable PR is not fatal
            print(
                f"doug: merged-event lookup failed for {owner}/{repo}#{number} "
                f"({type(e).__name__}: {e})",
                file=sys.stderr,
            )
            return None
        budget -= 1
        if not isinstance(events, list):
            return None
        for event in events:
            if not isinstance(event, dict) or event.get("event") != "merged":
                continue
            sha = _usable(event.get("commit_id"), column)
            if sha is None:
                print(
                    f"doug: {owner}/{repo}#{number} has a merged event whose "
                    "commit_id is missing or over-long",
                    file=sys.stderr,
                )
            return sha
        if page == 1:
            last = _last_page(getattr(resp.raw_response, "headers", {}) or {})
            page = last if last and last > 1 else None
        else:
            page = page - 1 if page - 1 > 1 else None
    if last and last > 1:
        print(
            f"doug: no merged event for {owner}/{repo}#{number} in the first "
            f"and last {_MAX_PAGES - 1} of {last} event pages",
            file=sys.stderr,
        )
    return None


def resolve(carried, *, column, client, owner: str, repo: str, number: int) -> str | None:
    """The merge commit sha for a merged PR, or None if neither source has it.

    `carried` is what the payload or the REST response supplied. When it is
    usable this costs nothing — the fallback is one extra call per PR and only
    on the PRs whose field is absent, so it is free while the rollout has not
    reached the caller and correct after it has.

    `client` is a zero-argument callable, not a client, so the webhook path does
    not mint an installation token for a fact it usually already has.
    """
    sha = _usable(carried, column)
    if sha is not None:
        return sha
    try:
        gh = client()
    except Exception as e:  # noqa: BLE001 — no client is a skip, not a 500
        print(
            f"doug: no client for the merged-event fallback on "
            f"{owner}/{repo}#{number} ({type(e).__name__}: {e})",
            file=sys.stderr,
        )
        return None
    return from_merged_event(gh, owner=owner, repo=repo, number=number, column=column)
