"""Harvest merged-PR metadata from GitHub.

Three REST calls per PR (detail, files, reviews) — no cloning, no
diffs. Enrichment runs concurrently over a shared connection pool;
results are cached to disk as JSON so reruns and re-labeling are free.
A 300-PR harvest costs ~900 requests against a 5,000/hour limit.
"""

import asyncio
import json
import subprocess
from pathlib import Path

from githubkit import GitHub
from githubkit.retry import RETRY_SERVER_ERROR, RetryChainDecision, RetryRateLimit
from pydantic import BaseModel

CONCURRENCY = 4
# Default githubkit only retries a rate-limit once; long harvests need more.
_RETRY = RetryChainDecision(RetryRateLimit(max_retry=6), RETRY_SERVER_ERROR)


class HarvestedPR(BaseModel):
    number: int
    title: str
    body: str
    author: str
    author_is_bot: bool
    additions: int
    deletions: int
    files: list[str]
    created_at: str
    merged_at: str
    approvals: int
    first_approval_at: str | None


def resolve_token(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    import os

    if tok := os.environ.get("GITHUB_TOKEN"):
        return tok
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except OSError:
        pass
    return None


async def _enrich(gh: GitHub, owner: str, repo: str, pull, sem: asyncio.Semaphore) -> HarvestedPR:
    async with sem:
        detail = (
            await gh.rest.pulls.async_get(owner=owner, repo=repo, pull_number=pull.number)
        ).parsed_data
        files = [
            f.filename
            async for f in gh.rest.paginate(
                gh.rest.pulls.async_list_files, owner=owner, repo=repo, pull_number=pull.number
            )
        ]
        reviews = [
            r
            async for r in gh.rest.paginate(
                gh.rest.pulls.async_list_reviews, owner=owner, repo=repo, pull_number=pull.number
            )
        ]
    approved = sorted(
        r.submitted_at for r in reviews if r.state == "APPROVED" and r.submitted_at
    )
    user = pull.user
    return HarvestedPR(
        number=pull.number,
        title=pull.title or "",
        body=pull.body or "",
        author=user.login if user else "unknown",
        author_is_bot=bool(user and user.type == "Bot"),
        additions=detail.additions,
        deletions=detail.deletions,
        files=files,
        created_at=str(pull.created_at),
        merged_at=str(pull.merged_at),
        approvals=len(approved),
        first_approval_at=str(approved[0]) if approved else None,
    )


def _load_partial(path: Path) -> dict[int, HarvestedPR]:
    if not path.exists():
        return {}
    prs = (
        HarvestedPR.model_validate(json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    )
    return {pr.number: pr for pr in prs}


async def _enrich_all(
    gh, owner: str, repo: str, merged: list, partial: Path | None
) -> list[HarvestedPR]:
    # Checkpoint each enriched PR to a JSONL sidecar: a multi-hour harvest
    # spans rate-limit windows and can be killed mid-run; without this,
    # every interruption re-spends the whole quota.
    done = _load_partial(partial) if partial else {}
    if done:
        print(f"  resuming: {len(done)} PRs already enriched in checkpoint", flush=True)
    sem = asyncio.Semaphore(CONCURRENCY)
    count = 0

    async def one(pull) -> HarvestedPR:
        nonlocal count
        if (hit := done.get(pull.number)) is not None:
            result = hit
        else:
            result = await _enrich(gh, owner, repo, pull, sem)
            if partial is not None:
                with partial.open("a") as f:
                    f.write(json.dumps(result.model_dump()) + "\n")
        count += 1
        if count % 50 == 0:
            print(f"  enriched {count}/{len(merged)}…", flush=True)
        return result

    return list(await asyncio.gather(*(one(p) for p in merged)))


async def _harvest(
    owner: str,
    repo: str,
    limit: int,
    token: str | None,
    before: str | None,
    partial: Path | None = None,
) -> list[HarvestedPR]:
    async with GitHub(token, auto_retry=_RETRY) as gh:
        merged = []
        seen = 0
        async for pull in gh.rest.paginate(
            gh.rest.pulls.async_list,
            owner=owner,
            repo=repo,
            state="closed",
            sort="created",
            direction="desc",
        ):
            seen += 1
            # Right-censoring guard: the newest PRs haven't had time to be
            # reverted yet, so sampling them deflates the defect rate.
            # --before skips forward past the young end of history.
            if before and str(pull.created_at) >= before:
                continue
            # Closed-unmerged PRs never shipped, so they can't have caused
            # an incident; they are outside the population being scored.
            if pull.merged_at is not None:
                merged.append(pull)
                if len(merged) >= limit:
                    break
            elif seen > limit * 6 + 3000:
                break  # mostly-unmerged history; stop scanning

        print(f"  listing done: {len(merged)} merged PRs; enriching…", flush=True)
        return await _enrich_all(gh, owner, repo, merged, partial)


async def _search_reverts(owner: str, repo: str, token: str | None) -> list[tuple[str, str]]:
    async with GitHub(token, auto_retry=_RETRY) as gh:
        results = []
        async for item in gh.rest.paginate(
            gh.rest.search.async_issues_and_pull_requests,
            map_func=lambda r: r.parsed_data.items,
            q=f"repo:{owner}/{repo} is:pr is:merged revert in:title",
        ):
            results.append((item.title or "", item.body or ""))
        return results


def search_reverts(
    owner: str, repo: str, token: str | None, cache_dir: Path
) -> list[tuple[str, str]]:
    """Repo-wide revert-PR titles/bodies via the search API (~1 request per
    100 reverts, separate rate bucket). Decouples labeling from the harvest
    window: a PR harvested today still gets labeled if its revert landed
    after the window closed."""
    cache = cache_dir / f"{owner}-{repo}-reverts.json"
    if cache.exists():
        return [tuple(x) for x in json.loads(cache.read_text())]
    results = asyncio.run(_search_reverts(owner, repo, token))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(results, indent=1))
    return results


def harvest(
    owner: str,
    repo: str,
    limit: int,
    token: str | None,
    cache_dir: Path,
    before: str | None = None,
) -> list[HarvestedPR]:
    suffix = f"-before-{before}" if before else ""
    cache = cache_dir / f"{owner}-{repo}-{limit}{suffix}.json"
    if cache.exists():
        return [HarvestedPR.model_validate(x) for x in json.loads(cache.read_text())]

    cache_dir.mkdir(parents=True, exist_ok=True)
    partial = cache_dir / f"{owner}-{repo}-{limit}{suffix}.partial.jsonl"
    harvested = asyncio.run(_harvest(owner, repo, limit, token, before, partial))

    cache.write_text(json.dumps([p.model_dump() for p in harvested], indent=1))
    partial.unlink(missing_ok=True)
    return harvested
