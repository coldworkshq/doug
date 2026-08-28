"""The merge commit sha, from the field that is going away or the graph that is not.

GitHub is removing the long-deprecated `merge_commit_sha` and `assignee` from
REST pull payloads (#259). During the rollout the same request returns 46 keys
or 48 depending on which backend pool it lands on, and responses are sticky per
keep-alive connection — so one long-lived client can see the trimmed shape for
every PR it reads. That is what made `doug-outcome-reconciler` sweep zero on
both of its first executions: the guard worked, the field it guards failed.

GraphQL's `PullRequest.mergeCommit.oid` is the same fact from the supported
source. Checked against #111 and #252 on 2026-08-28: identical to
`merge_commit_sha` in both cases.

**Not the issue-events API, which two earlier drafts of this used.** Events
carry a `merged` event with the same `commit_id`, but reaching it means paging:
events come back oldest-first, a merge is late, and post-merge activity —
comments, cross-references, deployments — pushes it back into the middle. A
forward walk misses it on a busy PR; a walk inwards from both ends misses it
too, which Doug caught after the first fix. Since the reconciler runs this
helper on every pass, any bounded page walk skips the same PR permanently and
silently, which is the failure this module exists to end rather than relocate.
GraphQL asks for one field and pages not at all. It also names the CURRENT
merge commit, where the first `merged` event on a merged-reverted-remerged PR
names the older one.

One helper, called from both places that need the fact.
`worker.reconcile_outcomes` is the site failing today; `api._record_merge` is
the site that fails when the removal reaches webhook serialization, and it
calls this only AFTER its 202 — ADR-0023 keeps that branch latency-bound.
"""

import sys

_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) { mergeCommit { oid } }
  }
}"""


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


def _dig(data, *keys):
    """Walk a GraphQL response, treating any missing or null level as absent.

    A PR that was closed without merging answers `mergeCommit: null`, which is
    a correct answer and not an error, so every level here has to tolerate null
    without raising.
    """
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def from_merge_commit(client, *, owner: str, repo: str, number: int, column) -> str | None:
    """`PullRequest.mergeCommit.oid`, or None.

    Fails soft on everything. A transport error, a GraphQL error, an unmerged
    PR, or an oid too long for the column all return None and leave the
    caller's existing skip path in charge. This is a fallback for a fact the
    caller has already failed to get; it must not be able to turn a skipped row
    into a raised exception.
    """
    try:
        data = client.graphql(_QUERY, {"owner": owner, "name": repo, "number": number})
    except Exception as e:  # noqa: BLE001 — one unreadable PR is not fatal
        print(
            f"doug: merge-commit lookup failed for {owner}/{repo}#{number} "
            f"({type(e).__name__}: {e})",
            file=sys.stderr,
        )
        return None
    oid = _dig(data, "repository", "pullRequest", "mergeCommit", "oid")
    if oid is None:
        print(
            f"doug: {owner}/{repo}#{number} has no mergeCommit in the graph",
            file=sys.stderr,
        )
        return None
    sha = _usable(oid, column)
    if sha is None:
        print(
            f"doug: {owner}/{repo}#{number} has a mergeCommit oid that is "
            "empty or too long for the column",
            file=sys.stderr,
        )
    return sha


def resolve(carried, *, column, client, owner: str, repo: str, number: int) -> str | None:
    """The merge commit sha for a merged PR, or None if neither source has it.

    `carried` is what the payload or the REST response supplied. When it is
    usable this costs nothing — the lookup is one extra call per PR and only on
    the PRs whose field is absent, so it is free while the rollout has not
    reached the caller and correct after it has.

    `client` is a zero-argument callable, not a client, so a caller does not
    mint an installation token for a fact it usually already has.
    """
    sha = _usable(carried, column)
    if sha is not None:
        return sha
    try:
        gh = client()
    except Exception as e:  # noqa: BLE001 — no client is a skip, not a 500
        print(
            f"doug: no client for the merge-commit lookup on "
            f"{owner}/{repo}#{number} ({type(e).__name__}: {e})",
            file=sys.stderr,
        )
        return None
    return from_merge_commit(gh, owner=owner, repo=repo, number=number, column=column)
