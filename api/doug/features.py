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


_PROSE_SUFFIXES = (".md", ".txt", ".rst")
_CODE_TEXT_NAMES = {"CMakeLists.txt"}
# Data that lives under docs/ is evidence, not program text. Scoped by
# DIRECTORY rather than by suffix because the same suffixes are how real
# config ships — package.json, tsconfig.json, and the migration fixtures are
# all correctly tier 0, and a suffix rule would demote every one of them.
_DOCS_DATA_ROOT = "docs"
_DOCS_DATA_SUFFIXES = (".json", ".jsonl", ".csv", ".yaml", ".yml")
# ...and `docs/` is not a private directory. Doug reviews other people's
# repositories, where a published API contract or generated schema under docs/
# is load-bearing config, not evidence — Doug flagged exactly this on b767f2e:
# "any repo that stores meaningful config or generated schema under docs/ (e.g.
# docs/**/openapi.json) would now be deprioritized or cut without notice."
#
# The first draft of this rule reasoned only from THIS repo's layout, which is
# the multi-tenant version of settling a claim by re-reading the diff. These
# names stay tier 0 wherever they live. The list is deliberately short and
# conservative: a name here costs nothing when absent, while a missing name
# silently demotes a customer's contract file. `openapi` and `swagger` also
# match `openapi.v2.json` and similar via the stem check below.
_CONTRACT_STEMS = frozenset(
    {"openapi", "swagger", "schema", "asyncapi", "graphql", "jsonschema"}
)
_DEPENDENCY_TEXT_RE = re.compile(
    r"^(?:requirements|constraints)(?:[-_.].*)?\.txt$", re.IGNORECASE
)


def _is_prose(path: str) -> bool:
    """Files the accepted routing policy ranks after code and tests.

    Used only by the read-budget tiering (review.read_order, ADR-0012), not
    by scoring — a docs-only PR still scores normally, it just loses the
    contest for the reader's budget.

    Lockfiles count as prose deliberately: generated, enormous, and never
    read by a human in review. Known manifests are code and stay tier 0,
    including conventional requirements/constraints variants despite their
    otherwise-prose suffix. Code-bearing text entry points use routing-only
    exceptions so this helper does not change scoring features.

    Committed data under `docs/` is prose for the same reason lockfiles are:
    it is evidence a review reads about, not program text a review reasons
    over. It got here as tier 0 because the suffix list stops at `.md`/`.txt`/
    `.rst`, and `read_order` sorts `(tier, len(patch))` ascending — so a large
    evidence fixture did not merely occupy tier 0, it sorted last within it and
    became the likeliest thing to be cut, displacing real code that would have
    fit. Measured: on the 30 first-parent commits ending at HEAD on 2026-08-23,
    `6fa1633` reported a code-tier miss whose only "code" files were
    `docs/design/walked-out/phase0_units.json` and
    `span-verification/barb_evidence.json`, on a 429,126-char diff.

    Scoped to the `docs/` root, NOT to the suffix. `package.json`,
    `tsconfig.json` and migration fixtures carry real decisions and stay tier 0;
    a suffix rule would demote all of them.

    Contract files are excepted wherever they live, `docs/` included. Doug
    reviews other people's repositories, and a published `docs/openapi.json` is
    config, not evidence — demoting it would cut a customer's API contract out
    of the read without notice. Routing only, like the exceptions above:
    `extract_features` never calls this, so scoring is untouched, and a test
    pins that by breaking this function and asserting the features do not move.
    """
    p = PurePosixPath(path)
    name = p.name
    if (
        name in MANIFESTS
        or name in _CODE_TEXT_NAMES
        or _DEPENDENCY_TEXT_RE.fullmatch(name)
    ):
        return False
    lowered = name.lower()
    if p.parts and p.parts[0] == _DOCS_DATA_ROOT and lowered.endswith(
        _DOCS_DATA_SUFFIXES
    ):
        # `openapi.v2.json` -> "openapi": the first dot-segment, so a versioned
        # or dated contract file is still recognised as one.
        return lowered.split(".", 1)[0] not in _CONTRACT_STEMS
    return name in LOCKFILES or lowered.endswith(_PROSE_SUFFIXES)


def _is_sensitive(path: str) -> bool:
    p = PurePosixPath(path)
    if any(part.lower() in SENSITIVE_SEGMENTS for part in p.parts):
        return True
    return bool(_SENSITIVE_NAME_RE.search(p.name))


def _is_hotspot(path: str, hot: set[str]) -> bool:
    # `hot` is the already-merged HOTSPOT_SEGMENTS | extra — merged once per
    # PR by the caller, not per file: this is the hottest per-PR function in
    # the pipeline, and a replay calls it for every file of every PR.
    parts = [p.lower() for p in PurePosixPath(path).parts]
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
    hot = HOTSPOT_SEGMENTS | (extra_hotspots or set())
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
        hotspot_path=any(_is_hotspot(f, hot) for f in pr.files),
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
