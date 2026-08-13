"""Wire and domain models.

PRMetadata is deliberately restricted to what the GitHub API hands out for
free. If a field would require cloning or parsing the repo, it does not
belong here yet — that is the thesis's phase discipline: metadata first,
prove the parsing half is needed before building it.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AuthorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


def is_bot_author(user_type: str | None, login: str | None) -> bool:
    """One predicate for "this PR author is a GitHub App".

    Shared by the webhook enqueue gate (api), reconcile's skip (worker),
    and review's author classification — they must agree or a PR skipped
    by one path is charged by another, and prose-coupled copies diverged
    once already (see worker._skip_reason's docstring). A missing user is
    not a bot: callers pass None fields through and proceed on False. The
    isinstance guard is load-bearing for the webhook path, whose login
    comes from an untrusted payload and need not be a string at all.
    """
    return user_type == "Bot" or (isinstance(login, str) and login.endswith("[bot]"))


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
    # Head commit as fetched — the identity review paths dedup repeats on.
    # None = not fetched (old caches, direct /v1/score callers); a review
    # without it is simply never treated as a repeat.
    head_sha: str | None = None
    # GitHub's own changed-file count (fetch_pr) or the paginated file
    # count (fetch_open_prs, whose list endpoint omits this field) — feeds
    # Coverage.complete. None = not fetched; never inferred from len(files).
    changed_files: int | None = None
    # Filenames GitHub reported but that carried no patch (binary, or too
    # large to inline) — never had a chance to be read at all, which
    # Coverage.complete treats as incomplete regardless of budget.
    files_dropped: list[str] = Field(default_factory=list)


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


class ScoreboardResponse(BaseModel):
    """Public Doug-on-Doug instrument. Distinct from the queue.

    `miss_rate` is always null in this increment: the first publication
    is the empty / not-yet-decidable state. `decidable` is therefore
    always false. The label travels in the payload so a client cannot
    invent a rate from the counts.
    """

    repo: str
    adjudicated: int
    pending: int
    as_of: datetime
    first_due: datetime | None
    deep_reads: int | None
    deep_read_cap: int
    miss_rate: None
    decidable: bool
    label: str


class RunCoverage(BaseModel):
    """What the reader was actually given. None on the whole object means no
    read happened — never zeros, which would claim Doug read nothing of a
    diff it never opened."""

    diff_chars: int
    sent_chars: int
    files_sent: int
    files_unseen: list[str]
    file_cut: str | None


class RunFindingCounts(BaseModel):
    total: int
    high: int
    medium: int
    low: int


class RunJob(BaseModel):
    status: str
    attempts: int
    error: str | None
    enqueued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class RunSummaryItem(BaseModel):
    verdict_id: int
    repo: str
    installation_id: int | None
    github_repo_id: int | None
    pr_number: int
    title: str
    url: str | None
    scored_at: datetime
    tier: str
    source: str | None
    score: float
    band: Band
    threshold: float
    coverage: RunCoverage | None
    changed_files: int | None
    finding_counts: RunFindingCounts
    job: RunJob | None
    outcome_14: str | None


class RunListResponse(BaseModel):
    items: list[RunSummaryItem]
    limit: int
    offset: int


class ReviewLaneHealth(BaseModel):
    pending: int
    oldest_pending_at: datetime | None
    retrying: int
    oldest_retry_at: datetime | None
    running: int
    stalled: int
    failed: int
    failed_24h: int
    stall_lease_seconds: int
    max_attempts: int


class OutcomeLaneHealth(BaseModel):
    pending: int
    overdue: int
    next_due_at: datetime | None
    oldest_overdue_due_at: datetime | None
    running: int
    stalled: int
    failed: int
    stall_lease_seconds: int
    max_attempts: int


class HealthResponse(BaseModel):
    """Fixed-size aggregates, no rows. The strip renders on every page, so
    this response's cost must not grow with the queue."""

    review: ReviewLaneHealth
    outcome: OutcomeLaneHealth
    as_of: datetime


class JobItem(BaseModel):
    """One job from either lane. Lane-specific fields are None on the other
    lane rather than absent, so the console has one row type to render.

    `repo` is nullable because outcome_jobs carries only github_repo_id and
    installation_repos can be stale or missing entirely — the console renders
    the bare id in that case rather than guessing a name.
    """

    id: int
    lane: str
    repo: str | None
    github_repo_id: int
    installation_id: int
    pr_number: int
    status: str
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    stalled: bool
    # Review lane only.
    head_sha: str | None = None
    enqueued_at: datetime | None = None
    verdict_id: int | None = None
    retrying: bool = False
    # Outcome lane only.
    merge_commit_sha: str | None = None
    window_days: int | None = None
    due_at: datetime | None = None
    merged_at: datetime | None = None
    overdue: bool = False


class JobListResponse(BaseModel):
    items: list[JobItem]
    limit: int
    offset: int


class RunOutcome(BaseModel):
    kind: str
    window_days: int | None
    observed_at: datetime
    source: str
    detail: str | None


class RunOutcomeJob(BaseModel):
    window_days: int
    status: str
    due_at: datetime
    merged_at: datetime


class RunDetailJob(BaseModel):
    status: str
    attempts: int
    claim_generation: int
    error: str | None
    enqueued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class RunDeviation(BaseModel):
    type: str
    description: str
    severity: str


class RunDetailResponse(BaseModel):
    verdict_id: int
    repo: str
    pr_number: int
    installation_id: int | None
    github_repo_id: int | None
    # None when the row carries no pr_meta (nullable column; save_review
    # defaults it to None) — every worker-path row before pr_meta capture,
    # and the CLI's caller, land here. Never synthesized the way
    # RunSummaryItem's flattened title/url are: PRMetadata.author has no
    # default and this row does not know one, so a placeholder would be a
    # guessed fact of exactly the kind PRMetadata's own fields refuse to
    # carry ("never guessed").
    pr: PRMetadata | None
    scored_at: datetime
    tier: str
    # None means the row predates prompt-hash stamping on the worker path.
    # It is NOT a match against the frozen prompt and must never render as one.
    prompt_hash: str | None
    model: str | None
    source: str | None
    head_sha: str | None
    risk_score: int | None
    rationale: str | None
    score: float
    band: Band
    threshold: float
    coverage: RunCoverage | None
    reasons: list[Reason]
    deviations: list[RunDeviation]
    intent_alignment: int | None
    intent_refs: list[str]
    job: RunDetailJob | None
    outcomes: list[RunOutcome]
    outcome_jobs: list[RunOutcomeJob]
