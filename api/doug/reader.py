"""LLM diff-reader — the tier the Phase-1 probes validated.

Prompt, schema, and read parameters are byte-identical to
scripts/llm_probe.py as of commit 0064e6b, where they were validated
pre-registered on two repos (AUC 0.687 sentry / 0.668 grafana against best
deterministic baselines of 0.591 / 0.518, ReDef polarity counterfactual
passed on both). They are load-bearing evidence — a change here is a new
experiment, not a tweak.

Opt-in twice over: DOUG_READER=1 AND a resolvable Anthropic credential.
Callers fall back to the deterministic score when either is missing or a
read fails, and the fallback verdict says so in its reasons. The flag
threshold (default 30) sits at the ~75-80th percentile of clean-PR risk
scores on both probe repos — roughly the top quarter gets flagged.
"""

import os

from pydantic import BaseModel

from .models import Band, Reason, Verdict

MODEL = "claude-opus-5"
MAX_TOKENS = 6000
EFFORT = "medium"
DIFF_BUDGET = 30_000  # chars
DEFAULT_READER_THRESHOLD = 30  # risk_score points, 0-100

SYSTEM = (
    "You are reviewing a single pull request diff from a large production "
    "codebase. Judge the risk that this specific change introduces a defect "
    "that will later be reverted or hot-fixed. Flag concrete defect risks in "
    "the change itself — logic errors, unsafe migrations, concurrency "
    "hazards, error-handling gaps, contract mismatches — not style, tests, "
    "or hypothetical improvements. Most changes in a healthy repo are safe; "
    "score accordingly."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "risk_score": {
            "type": "integer",
            "description": (
                "0-100 risk that this change causes a revert or hotfix. "
                "Most PRs deserve <30; reserve >70 for changes you would block."
            ),
        },
        "rationale": {"type": "string", "description": "One or two sentences."},
        "findings": {
            "type": "array",
            "description": "Concrete defect risks in this change; empty if none.",
            "items": {
                "type": "object",
                "properties": {
                    "category_slug": {
                        "type": "string",
                        "description": (
                            "Short kebab-case defect pattern, reusable across "
                            "PRs — e.g. unsafe-migration, race-condition, "
                            "missing-null-check, api-contract-change."
                        ),
                    },
                    "description": {"type": "string"},
                    "file": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["category_slug", "description", "file", "severity"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["risk_score", "rationale", "findings"],
    "additionalProperties": False,
}


# --- Intent tier -----------------------------------------------------------
#
# A second, separate read: the diff judged against the decisions the team
# already recorded. INTENT_SCHEMA is verbatim from scripts/intent_probe.py,
# the Experiment B v2 shape that passed (HIGH-severity deviations on 4% of
# matched PRs vs 100% of mismatched, alignment 80 vs 2).
#
# The system prompt is NOT verbatim, and the difference matters. B v2's
# prompt says "the issue/ticket this PR claims to resolve" and defines
# missing-from-pr as "things the ticket asks for that the PR does not do".
# A recorded decision asks nothing of a PR. Reusing that wording would be
# false on its face, so this is a sibling prompt — frozen from creation on
# the same terms as SYSTEM (ADR-0002), and unvalidated until the
# derangement check runs. B v2 is prior evidence the capability is real,
# not evidence that this prompt works.

DECISION_INTENT_SYSTEM = (
    "You are reviewing a single pull request diff from a large production "
    "codebase, together with the architecture decisions this team has "
    "already recorded and still considers binding. Judge whether the change "
    "departs from those decisions. Report a deviation when the diff makes a "
    "material change a recorded decision does not sanction (beyond-ticket), "
    "when it contradicts a recorded decision outright (contradicts-ticket), "
    "or when it claims to implement a decision but leaves a required part "
    "undone (missing-from-pr). Routine implementation detail the decisions "
    "leave open is NOT a deviation, and neither is work that is simply "
    "unrelated to every decision you were given — most changes touch none "
    "of them. Judge only against the decisions provided; do not invent "
    "policy. Also report defect risks in the change itself, as usual."
)

INTENT_SCHEMA = {
    **{k: v for k, v in SCHEMA.items() if k != "properties"},
    "properties": {
        **SCHEMA["properties"],
        "intent_alignment": {
            "type": "integer",
            "description": (
                "0-100: how fully and faithfully the diff implements the ticket's intent."
            ),
        },
        "deviation_findings": {
            "type": "array",
            "description": (
                "Gaps between ticket intent and diff behavior; empty if the PR "
                "does what the ticket asks."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["missing-from-pr", "beyond-ticket", "contradicts-ticket"],
                    },
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["type", "description", "severity"],
                "additionalProperties": False,
            },
        },
    },
    "required": [*SCHEMA["required"], "intent_alignment", "deviation_findings"],
}


class ReaderError(RuntimeError):
    """A read failed (refusal, truncation, transport) — fall back and say so."""


class ReaderFinding(BaseModel):
    category_slug: str
    description: str
    file: str
    severity: str


class ReaderVerdict(BaseModel):
    risk_score: int
    rationale: str
    findings: list[ReaderFinding]


def enabled() -> bool:
    return os.environ.get("DOUG_READER") == "1"


def reader_threshold() -> float:
    return float(os.environ.get("DOUG_READER_THRESHOLD", DEFAULT_READER_THRESHOLD))


def _user_text(pr, diff: str) -> str:
    truncated = len(diff) > DIFF_BUDGET
    return (
        f"Title: {pr.title}\n"
        f"Files changed: {', '.join(pr.files)}\n"
        + ("[diff truncated at budget]\n" if truncated else "")
        + f"\n{diff[:DIFF_BUDGET]}"
    )


def read_diff(pr, diff: str, client=None) -> ReaderVerdict:
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": _user_text(pr, diff)}],
    )
    if response.stop_reason != "end_turn":
        raise ReaderError(f"read stopped with {response.stop_reason}")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return ReaderVerdict.model_validate_json(text)
    except ValueError as e:
        raise ReaderError(f"unparseable reader output: {e}") from e


class DeviationFinding(BaseModel):
    type: str
    description: str
    severity: str


class IntentReaderVerdict(ReaderVerdict):
    intent_alignment: int
    deviation_findings: list[DeviationFinding]


def intent_enabled() -> bool:
    return os.environ.get("DOUG_INTENT") == "1"


def _intent_text(pr, diff: str, docs) -> str:
    """Decisions first, then the diff — same ordering the probe validated."""
    block = "\n\n".join(
        f"[{d.id}] {d.title}\n{d.body}" for d in docs
    )
    return (
        "Recorded architecture decisions this team considers binding:\n"
        f"{block}\n\n---\n" + _user_text(pr, diff)
    )


def read_with_decisions(pr, diff: str, docs, client=None) -> IntentReaderVerdict:
    """The intent read. Never called with an empty `docs` — a read with no
    decisions in it is the diff-only read, and asking the model to compare
    against nothing invites invented findings."""
    if not docs:
        raise ReaderError("no decision records to read against")
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        output_config={
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": INTENT_SCHEMA},
        },
        system=DECISION_INTENT_SYSTEM,
        messages=[{"role": "user", "content": _intent_text(pr, diff, docs)}],
    )
    if response.stop_reason != "end_turn":
        raise ReaderError(f"intent read stopped with {response.stop_reason}")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return IntentReaderVerdict.model_validate_json(text)
    except ValueError as e:
        raise ReaderError(f"unparseable intent output: {e}") from e


def verdict_from_reader(rv: ReaderVerdict, threshold: float | None = None) -> Verdict:
    thr = reader_threshold() if threshold is None else threshold
    band = Band.FLAGGED if rv.risk_score >= thr else Band.CLEARED
    reasons = [
        Reason(rule=f"reader:{f.category_slug}", label=f.description, weight=0.0)
        for f in rv.findings
    ]
    return Verdict(
        score=round(rv.risk_score / 100, 2),
        band=band,
        threshold=thr / 100,
        reasons=reasons,
    )
