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

# Always-runtime ecosystems. JS package.json is handled separately —
# root app manifests count; eslint/jest-only bumps are filtered via title.
RUNTIME_MANIFESTS = {
    "pyproject.toml",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "composer.lock",
    "requirements.txt",
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
}

JS_MANIFESTS = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}

# Title cues that the dep bump is tooling, not runtime — sentry top-10%
# was dominated by eslint/jest/esbuild/lodash bumps that almost never revert.
_DEV_DEP_TITLE_RE = re.compile(
    r"\b(eslint|jest|prettier|lodash|figma|esbuild|typescript-eslint|@types/)\b",
    re.IGNORECASE,
)

# Cheap deterministic proxy for "crosses a boundary that matters".
SENSITIVE_SEGMENTS = {
    "auth",
    "authn",
    "authz",
    "accesscontrol",
    "rbac",
    "acl",
    "permission",
    "permissions",
    "billing",
    "payments",
    "payment",
    "security",
    "secret",
    "secrets",
    "iam",
    "identity",
    "oauth",
    "session",
    "ledger",
    "credential",
    "credentials",
}

# Trees that showed elevated revert density on sentry (and similar SaaS apps).
# Generic enough to apply elsewhere; not a per-repo fit.
HOTSPOT_SEGMENTS = {
    "preprod",
    "grouping",
    "nodestore",
    "objectstore",
    "workflow_engine",
    "seer",
    "taskworker",
    "snapshots",
    "hybridcloud",
    "relocation",
}

_SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[^a-z])(?:secret|secrets|auth|authn|authz|rbac|oauth|credential|token)s?(?:[^a-z]|$)",
    re.IGNORECASE,
)

_MIGRATION_RE = re.compile(r"(^|/)(migrations?|schema)(/|$)|\.sql$", re.IGNORECASE)
_TEST_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)|(^|[._/])test_|_test\.|\.(test|spec)\.",
    re.IGNORECASE,
)
_CONFIG_FLAG_RE = re.compile(
    r"(^|/)(options/defaults\.py|features/temporary\.py|feature[_-]?flags?/|"
    r"flags\.ya?ml|config/experiments/)",
    re.IGNORECASE,
)
_DEV_PATH_RE = re.compile(
    r"(^|/)\.github/|(^|/)(e2e|playground|storybook|eslint|jest)(/|$)",
    re.IGNORECASE,
)

# Conventional-commit refactor prefix ("ref(scope):", "refactor:").
_REFACTOR_TITLE_RE = re.compile(r"^\s*(ref|refactor)[(:!]", re.IGNORECASE)

# Below this churn a "refactor" or deletion is trivial noise.
_MIN_SHAPE_CHURN = 20


def _is_test(path: str) -> bool:
    return bool(_TEST_RE.search(path))


def _is_sensitive(path: str) -> bool:
    p = PurePosixPath(path)
    if any(part.lower() in SENSITIVE_SEGMENTS for part in p.parts):
        return True
    return bool(_SENSITIVE_NAME_RE.search(p.name))


def _is_hotspot(path: str, extra: set[str] | None = None) -> bool:
    parts = [p.lower() for p in PurePosixPath(path).parts]
    hot = HOTSPOT_SEGMENTS | (extra or set())
    if any(p in hot for p in parts):
        return True
    # Learned bigrams like "preprod/api".
    for a, b in zip(parts, parts[1:], strict=False):
        if f"{a}/{b}" in hot:
            return True
    return False


def _runtime_dep(files: list[str]) -> bool:
    names = [PurePosixPath(f).name for f in files]
    if any(n in RUNTIME_MANIFESTS for n in names):
        return True
    js = [f for f in files if PurePosixPath(f).name in JS_MANIFESTS]
    if not js:
        return False
    # JS lock/manifest changes under .github/e2e/playground don't count.
    return any(not _DEV_PATH_RE.search(f) for f in js)


def extract_features(
    pr: PRMetadata, extra_hotspots: set[str] | None = None
) -> Features:
    names = [PurePosixPath(f).name for f in pr.files]
    test_files = sum(1 for f in pr.files if _is_test(f))
    lockfile = any(n in LOCKFILES for n in names)
    manifest = any(n in MANIFESTS for n in names)
    dep_names = LOCKFILES | MANIFESTS
    dep_only = (lockfile or manifest) and all(
        PurePosixPath(f).name in dep_names or _is_test(f) for f in pr.files
    )
    return Features(
        size=pr.additions + pr.deletions,
        file_count=len(pr.files),
        migration=any(_MIGRATION_RE.search(f) for f in pr.files),
        lockfile=lockfile,
        manifest=manifest,
        runtime_dep=_runtime_dep(pr.files) if (lockfile or manifest) else False,
        dev_tool_dep=bool(_DEV_DEP_TITLE_RE.search(pr.title)),
        dep_only=dep_only,
        sensitive_path=any(_is_sensitive(f) for f in pr.files),
        hotspot_path=any(_is_hotspot(f, extra_hotspots) for f in pr.files),
        config_flag=any(_CONFIG_FLAG_RE.search(f) for f in pr.files),
        test_files=test_files,
        code_files=len(pr.files) - test_files,
        refactor_title=bool(_REFACTOR_TITLE_RE.match(pr.title)),
        # Every file edited in place, nothing new added: behavior change
        # hiding inside "no functional change". Unknown statuses (old
        # caches, details not fetched) never count — unknown ≠ signal.
        pure_modification=(
            pr.files_modified is not None
            and len(pr.files) > 0
            and pr.files_modified == len(pr.files)
            and pr.additions + pr.deletions >= _MIN_SHAPE_CHURN
        ),
        deletion_leaning=(
            pr.deletions >= 1.5 * pr.additions
            and pr.additions + pr.deletions >= _MIN_SHAPE_CHURN
        ),
        agent_authored=pr.author_type is AuthorType.AGENT or pr.author.endswith("[bot]"),
        approvals=pr.approvals,
        approval_latency_s=pr.approval_latency_s,
        days_since_last_human_commit=pr.days_since_last_human_commit,
    )
