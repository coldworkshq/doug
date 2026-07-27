"""Feature extraction: PR metadata -> feature vector.

Pure function, no I/O. The backtest replays it over history; the webhook
calls it live. Keeping this seam pure is the continuity guarantee the
whole build order depends on.
"""

import re
from pathlib import PurePosixPath

from .models import AuthorType, Features, PRMetadata

LOCKFILES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "go.sum",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
}

MANIFESTS = {
    "package.json",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    "Gemfile",
    "composer.json",
    "requirements.txt",
}

# Cheap deterministic proxy for "crosses a boundary that matters".
# The real boundary model needs an import graph; these path segments are
# the metadata-only stand-in until the backtest proves the graph is needed.
SENSITIVE_SEGMENTS = {
    "auth",
    "authn",
    "authz",
    "billing",
    "payments",
    "payment",
    "security",
    "secrets",
    "iam",
    "ledger",
}

_MIGRATION_RE = re.compile(r"(^|/)(migrations?|schema)(/|$)|\.sql$", re.IGNORECASE)
_TEST_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)|(^|[._/])test_|_test\.|\.(test|spec)\.",
    re.IGNORECASE,
)


def _is_test(path: str) -> bool:
    return bool(_TEST_RE.search(path))


def _is_sensitive(path: str) -> bool:
    return any(part.lower() in SENSITIVE_SEGMENTS for part in PurePosixPath(path).parts)


def extract_features(pr: PRMetadata) -> Features:
    names = [PurePosixPath(f).name for f in pr.files]
    test_files = sum(1 for f in pr.files if _is_test(f))
    return Features(
        size=pr.additions + pr.deletions,
        file_count=len(pr.files),
        migration=any(_MIGRATION_RE.search(f) for f in pr.files),
        lockfile=any(n in LOCKFILES for n in names),
        manifest=any(n in MANIFESTS for n in names),
        sensitive_path=any(_is_sensitive(f) for f in pr.files),
        test_files=test_files,
        code_files=len(pr.files) - test_files,
        agent_authored=pr.author_type is AuthorType.AGENT or pr.author.endswith("[bot]"),
        approvals=pr.approvals,
        approval_latency_s=pr.approval_latency_s,
        days_since_last_human_commit=pr.days_since_last_human_commit,
    )
