"""Wire and domain models.

PRMetadata is deliberately restricted to what the GitHub API hands out for
free. If a field would require cloning or parsing the repo, it does not
belong here yet — that is the thesis's phase discipline: metadata first,
prove the parsing half is needed before building it.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class AuthorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class PRMetadata(BaseModel):
    number: int
    title: str
    author: str
    author_type: AuthorType = AuthorType.HUMAN
    additions: int = 0
    deletions: int = 0
    files: list[str] = Field(default_factory=list)
    approvals: int = 0
    # Seconds from PR open to first approval. None = not yet approved.
    approval_latency_s: int | None = None
    # None = unknown (e.g. new repo, no history fetched). Never guessed.
    days_since_last_human_commit: int | None = None
    # File-status counts from the same list-files call that yields `files`.
    # None = statuses not fetched (old caches); never inferred from names.
    files_added: int | None = None
    files_modified: int | None = None
    url: str | None = None


class Features(BaseModel):
    size: int
    file_count: int
    migration: bool
    lockfile: bool
    manifest: bool
    runtime_dep: bool = False
    dev_tool_dep: bool = False
    dep_only: bool = False
    sensitive_path: bool
    hotspot_path: bool = False
    config_flag: bool = False
    test_files: int
    code_files: int
    refactor_title: bool = False
    pure_modification: bool = False
    deletion_leaning: bool = False
    agent_authored: bool
    approvals: int
    approval_latency_s: int | None
    days_since_last_human_commit: int | None


class Reason(BaseModel):
    rule: str
    label: str
    weight: float
    # Reader findings carry a severity and no weight; deterministic rules
    # carry a weight and no severity. Both travel here so a surface can
    # show whichever one is meaningful instead of a constant 0.00.
    severity: str | None = None


class Band(StrEnum):
    CLEARED = "cleared"
    FLAGGED = "flagged"


class Verdict(BaseModel):
    score: float
    band: Band
    threshold: float
    reasons: list[Reason]


class QueueItem(BaseModel):
    pr: PRMetadata
    verdict: Verdict


class ReadScoreRequest(BaseModel):
    """Diff-carrying score request — the reader tier's input."""

    pr: PRMetadata
    diff: str


class QueueSummary(BaseModel):
    open: int
    flagged: int
    cleared: int
    threshold: float


class QueueResponse(BaseModel):
    summary: QueueSummary
    items: list[QueueItem]
