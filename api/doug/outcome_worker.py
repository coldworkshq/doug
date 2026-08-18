"""Cloud Run Job entrypoint for the M3 outcome loop."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from githubkit.exception import RequestError

from . import app_auth, outcome_queue
from .adjudicate import adjudicate
from .backtest import git_labels

_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class DrainSummary:
    repositories: int = 0
    done: int = 0
    retried: int = 0
    failed_repositories: int = 0
    reclaimed: int = 0


def _github_context(installation_id: int, repo_full_name: str) -> tuple[str, str]:
    """Mint this installation's clone token and read its default branch."""
    owner, separator, repo = repo_full_name.partition("/")
    if not separator or not owner or not repo:
        raise ValueError(f"invalid repository full name {repo_full_name!r}")
    # Both clients are bound to a local for the duration of their call.
    # githubkit's .rest namespace holds its client with a weakref, so a
    # construct-and-chain temporary is collected the instant .rest is
    # evaluated and the next attribute raises "GitHub client has already
    # been collected" — before any request, so no stub or fixture sees it.
    # tenancy.py:220 stated the rule after #52 hit the dispense identity
    # check in prod on 2026-08-05; this function was written with the defect
    # anyway and failed every adjudication from 2026-08-17 until 2026-08-18.
    # test_client_lifetime.py now enforces it across the package.
    app = app_auth.app_client()
    token_response = app.rest.apps.create_installation_access_token(installation_id)
    token = token_response.parsed_data.token
    installation = app_auth.installation_client(installation_id)
    repo_response = installation.rest.repos.get(owner, repo)
    default_branch = repo_response.parsed_data.default_branch
    if not token or not default_branch:
        raise RuntimeError("GitHub returned an empty installation token or default branch")
    return str(token), str(default_branch)


def _repository_evidence(batch, clone_root: Path):
    if batch.repo_full_name is None:
        raise RuntimeError("repository identity is unavailable")
    owner, separator, repo = batch.repo_full_name.partition("/")
    if not separator or not owner or not repo:
        raise ValueError(f"invalid repository full name {batch.repo_full_name!r}")
    token, default_branch = _github_context(batch.key.installation_id, batch.repo_full_name)
    revert_map = git_labels.find_reverted_prs_evidenced(
        owner,
        repo,
        clone_root / f"{batch.key.installation_id}-{batch.key.github_repo_id}",
        token=token,
    )
    return revert_map, default_branch


def _safe_repository_error(exc: Exception) -> str:
    """A clone exception's argv may contain the installation token."""
    return f"repository evidence failed ({type(exc).__name__})"


def drain(*, prereg_hash: str | None, clone_root: Path) -> DrainSummary:
    """Process each repository with due work at most once this invocation."""
    reclaimed = outcome_queue.reclaim_stalled()
    keys = outcome_queue.due_repositories()
    if not keys:
        return DrainSummary(reclaimed=reclaimed)
    if prereg_hash is None or _SHA256.fullmatch(prereg_hash) is None:
        raise RuntimeError("DOUG_PREREG_HASH must be a lowercase SHA-256 before adjudication")
    if not app_auth.enabled():
        raise RuntimeError(
            "DOUG_GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must be configured before adjudication"
        )

    repositories = done = retried = failed_repositories = 0
    for key in keys:
        batch = outcome_queue.claim_repository(key)
        if batch is None:
            continue
        repositories += 1
        if batch.repo_full_name is None:
            # Missing MT0/backfill registry state is not enough evidence to
            # invent a display identity. Even a deleted installation cannot
            # produce an auditable censoring row without one, but it also must
            # not block the rest of today's repository snapshot.
            outcome_queue.fail_batch(batch, "repository identity unavailable")
            retried += len(batch.jobs)
            failed_repositories += 1
            continue
        if batch.permanently_unreachable:
            revert_map, default_branch = {}, None
        else:
            try:
                revert_map, default_branch = _repository_evidence(batch, clone_root)
            except (
                RequestError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ) as exc:
                outcome_queue.fail_batch(batch, _safe_repository_error(exc))
                retried += len(batch.jobs)
                failed_repositories += 1
                continue
        # Pure-classifier and ledger defects are systemic. They escape so the
        # Cloud Run execution is red and the lease can be reclaimed; counting
        # them as repository attempts would hide a broken deployment.
        result = adjudicate(batch.jobs, revert_map, default_branch=default_branch)
        settled, refused = outcome_queue.settle_batch(
            batch,
            result,
            repo_full_name=batch.repo_full_name,
            observed_at=datetime.now(UTC),
            prereg_hash=prereg_hash,
        )
        done += settled
        retried += refused

    return DrainSummary(
        repositories=repositories,
        done=done,
        retried=retried,
        failed_repositories=failed_repositories,
        reclaimed=reclaimed,
    )


def main() -> None:
    summary = drain(
        prereg_hash=os.environ.get("DOUG_PREREG_HASH"),
        clone_root=Path(os.environ.get("DOUG_ADJUDICATOR_CACHE", "/tmp/doug-adjudicator")),
    )
    print(json.dumps(asdict(summary), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
