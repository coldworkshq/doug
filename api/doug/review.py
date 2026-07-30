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

from pydantic import BaseModel

from . import reader
from .backtest.harvest import resolve_token
from .models import AuthorType, Band, PRMetadata, Reason, Verdict
from .scoring import score

print = functools.partial(print, flush=True)  # noqa: A001


class ReviewItem(BaseModel):
    pr: PRMetadata
    verdict: Verdict


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
        )
        diff = "\n\n".join(
            f"### {f.filename} ({f.status}, +{f.additions}/-{f.deletions})\n{f.patch}"
            for f in files
            if f.patch
        )
        out.append((meta, diff))
    return out


def review_repo(gh, owner: str, repo: str, limit: int) -> list[ReviewItem]:
    items = []
    for meta, diff in fetch_open_prs(gh, owner, repo, limit):
        if reader.enabled():
            try:
                verdict = reader.verdict_from_reader(reader.read_diff(meta, diff))
            except reader.ReaderError as e:
                verdict = score(meta)
                verdict.reasons.append(
                    Reason(rule="reader-unavailable", label=str(e), weight=0.0)
                )
        else:
            verdict = score(meta)
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
