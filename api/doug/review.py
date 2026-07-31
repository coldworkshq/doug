"""Review a repo's OPEN pull requests — the dogfood surface.

`doug-review owner/repo` pulls the open PRs, scores each through the
reader tier when it's enabled (DOUG_READER=1 + credential; see reader.py),
falls back to the deterministic scorer otherwise, and prints the routed
queue. Read-only: it never comments, labels, or blocks — posting an
opinion to a PR is a product decision, not a side effect of scoring.

Open PRs have no approval history yet, so approval-shaped deterministic
rules simply don't fire here; the reader doesn't use them at all.

    uv run doug-review grafana/grafana --limit 10
    DOUG_READER=1 uv run doug-review drewjst/lema
"""

import argparse
import functools
import sys

from pydantic import BaseModel

from . import intent, intent_providers, reader
from .backtest.harvest import resolve_token
from .models import AuthorType, Band, PRMetadata, Reason, Verdict
from .scoring import score

print = functools.partial(print, flush=True)  # noqa: A001


class ReviewItem(BaseModel):
    pr: PRMetadata
    verdict: Verdict


def _html_url(p) -> str | None:
    """PR permalink, tolerant of what the field actually is.

    githubkit models absent fields as the UNSET sentinel rather than None,
    and cached payloads from earlier harvests predate the field entirely.
    Anything that is not a string is no link — api.py reconstructs one from
    the repo and number in that case.
    """
    url = getattr(p, "html_url", None)
    return url if isinstance(url, str) else None


def fetch_open_prs(gh, owner: str, repo: str, limit: int) -> list[tuple[PRMetadata, str]]:
    pulls = gh.rest.pulls.list(
        owner=owner, repo=repo, state="open", sort="created", direction="desc",
        per_page=min(limit, 100),
    ).parsed_data[:limit]
    out = []
    for p in pulls:
        files = gh.rest.pulls.list_files(
            owner=owner, repo=repo, pull_number=p.number, per_page=100
        ).parsed_data
        meta = PRMetadata(
            number=p.number,
            title=p.title,
            author=p.user.login if p.user else "unknown",
            author_type=(
                AuthorType.AGENT
                if p.user and (p.user.type == "Bot" or p.user.login.endswith("[bot]"))
                else AuthorType.HUMAN
            ),
            # pulls.list omits additions/deletions; per-file stats carry them.
            additions=sum(f.additions for f in files),
            deletions=sum(f.deletions for f in files),
            files=[f.filename for f in files],
            approvals=0,
            approval_latency_s=None,
            days_since_last_human_commit=None,
            files_added=sum(1 for f in files if f.status == "added"),
            files_modified=sum(1 for f in files if f.status == "modified"),
            url=_html_url(p),
        )
        diff = "\n\n".join(
            f"### {f.filename} ({f.status}, +{f.additions}/-{f.deletions})\n{f.patch}"
            for f in files
            if f.patch
        )
        out.append((meta, diff))
    return out


def fetch_pr(gh, owner: str, repo: str, number: int) -> tuple[PRMetadata, str]:
    p = gh.rest.pulls.get(owner=owner, repo=repo, pull_number=number).parsed_data
    files = gh.rest.pulls.list_files(
        owner=owner, repo=repo, pull_number=number, per_page=100
    ).parsed_data
    meta = PRMetadata(
        number=p.number,
        title=p.title,
        author=p.user.login if p.user else "unknown",
        author_type=(
            AuthorType.AGENT
            if p.user and (p.user.type == "Bot" or p.user.login.endswith("[bot]"))
            else AuthorType.HUMAN
        ),
        additions=sum(f.additions for f in files),
        deletions=sum(f.deletions for f in files),
        files=[f.filename for f in files],
        approvals=0,
        approval_latency_s=None,
        days_since_last_human_commit=None,
        files_added=sum(1 for f in files if f.status == "added"),
        files_modified=sum(1 for f in files if f.status == "modified"),
        url=_html_url(p),
    )
    diff = "\n\n".join(
        f"### {f.filename} ({f.status}, +{f.additions}/-{f.deletions})\n{f.patch}"
        for f in files
        if f.patch
    )
    return meta, diff


def score_one(meta: PRMetadata, diff: str):
    """Tier dispatch: (tier, verdict, reader_verdict|None, coverage|None).

    Reader failures fall back loudly — the deterministic verdict says
    reader-unavailable. Reader *successes* can also be partial, and say so
    the same way: coverage rides out with the verdict rather than being
    recomputed by whoever remembers to, because forgetting is how a 44% read
    came to look exactly like a whole one. None on the deterministic tier,
    which never opens the diff.
    """
    if reader.enabled():
        try:
            rv = reader.read_diff(meta, diff)
            verdict = reader.verdict_from_reader(rv)
            cov = reader.coverage(meta, diff)
            if notice := reader.truncation_reason(cov):
                verdict.reasons.append(notice)
            return "reader", verdict, rv, cov
        except reader.ReaderError as e:
            verdict = score(meta)
            verdict.reasons.append(
                Reason(rule="reader-unavailable", label=str(e), weight=0.0)
            )
            return "deterministic", verdict, None, None
    return "deterministic", score(meta), None, None


class IntentRead(BaseModel):
    """The intent tier's output. Separate from Verdict by design (ADR-0007)."""

    alignment: int
    refs: list[str]
    findings: list[reader.DeviationFinding]


def read_intent(gh, owner: str, repo: str, meta: PRMetadata, diff: str) -> IntentRead | None:
    """Judge the change against the repo's binding decisions, or None.

    None means no read happened — the feature is off, the repo keeps no
    decision records, none of them bear on this change, or the read
    failed. Every one of those is ordinary, and none of them may disturb
    the risk verdict this runs alongside.
    """
    if not (intent.enabled() and reader.enabled()):
        return None
    try:
        docs = intent_providers.fetch(gh, owner, repo)
        chosen = [intent.truncate(d) for d in intent.select(docs, meta.title, meta.files)]
        if not chosen:
            return None
        rv = reader.read_with_decisions(meta, diff, chosen)
    except Exception as e:  # noqa: BLE001 — advisory path, never fails a review
        # Swallowed, but not silently: a read that fails every time would
        # otherwise be indistinguishable from a repo that keeps no records,
        # and the feature would look "quiet" rather than broken.
        print(f"doug: intent read skipped ({type(e).__name__}: {e})", file=sys.stderr)
        return None
    return IntentRead(
        alignment=rv.intent_alignment,
        refs=[d.id for d in chosen],
        findings=rv.deviation_findings,
    )


def review_repo(gh, owner: str, repo: str, limit: int) -> list[ReviewItem]:
    items = []
    for meta, diff in fetch_open_prs(gh, owner, repo, limit):
        _, verdict, _, _ = score_one(meta, diff)
        items.append(ReviewItem(pr=meta, verdict=verdict))
    items.sort(key=lambda i: i.verdict.score, reverse=True)
    return items


def render(items: list[ReviewItem]) -> str:
    lines = []
    flagged = [i for i in items if i.verdict.band is Band.FLAGGED]
    lines.append(
        f"{len(items)} open PRs · {len(flagged)} flagged · {len(items) - len(flagged)} cleared"
    )
    for i in items:
        mark = "▲" if i.verdict.band is Band.FLAGGED else "·"
        lines.append(f"{mark} {i.verdict.score:>4.2f}  #{i.pr.number:<6} {i.pr.title[:70]}")
        for r in i.verdict.reasons:
            lines.append(f"         - {r.rule}: {r.label[:90]}")
    return "\n".join(lines)


def main() -> int:
    from githubkit import GitHub

    parser = argparse.ArgumentParser(description="Score a repo's open PRs")
    parser.add_argument("repo", help="owner/repo")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    owner, repo = args.repo.split("/", 1)
    gh = GitHub(resolve_token(None))
    tier = "reader" if reader.enabled() else "deterministic (set DOUG_READER=1 for the reader)"
    print(f"scoring open PRs on {args.repo} · tier: {tier}")
    print(render(review_repo(gh, owner, repo, args.limit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
