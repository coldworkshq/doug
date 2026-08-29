"""LLM diff-reader — descended from the tier the Phase-1 probes validated.

SYSTEM, SCHEMA, MODEL and MAX_TOKENS remain byte-identical to
scripts/llm_probe.py as of commit 0064e6b. The probe's AUC 0.687 sentry /
0.668 grafana and its ReDef polarity result belong to its 30k diff-budget
configuration. The shipped DIFF_BUDGET is 100k under ADR-0012 and its files
are tier-ordered, so those AUC figures do not validate the larger, reordered
live read. The four frozen parameters are load-bearing evidence — changing
one is a new experiment, not a tweak.

ADR-0002 froze six. TWO have left: DIFF_BUDGET (ADR-0012, governed by a
coverage bar) and EFFORT (ADR-0018, governed by an unrun pre-registration).
Four remain, and 2 + 4 = 6 — an earlier version of this paragraph said
"three have left" alongside "four remain", which Doug caught on b767f2e.
Each divergence is pinned on BOTH sides by test, so nobody can re-anchor the
instrument by "fixing the drift".

Opt-in twice over: DOUG_READER=1 AND a credential the selected transport can
resolve. Which credential that is depends on DOUG_READER_TRANSPORT (ADR-0029):
Vertex, the default, authenticates with GCP application default credentials and
needs no key, and the first-party API needs ANTHROPIC_API_KEY. Callers fall back
to the deterministic score when either half of the opt-in is missing or a read
fails, and the fallback verdict says so in its reasons. The flag threshold
(default 30) sits at the ~75-80th percentile of clean-PR risk scores on both
probe repos — roughly the top quarter gets flagged.

That fallback is load-bearing and it is also a hazard on this transport: a
misconfigured region or a missing IAM grant produces the same soft fallback a
stalled upstream does, so it reads as "the reader is down" rather than "the
deploy is wrong". deploy/gcp.sh refuses to deploy without a Vertex region for
exactly that reason.

Every read is charged to a caller-named scope against a monthly cap before
anything is sent (see _charge). On a deployment with a ledger that is a
real ceiling on spend; without one — local dogfooding, the open-source
path — store.record_deep_read returns True and reads are uncapped by
design.
"""

import hashlib
import json
import os
import re
import sys
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import example_pack_capture, hunks
from .example_pack import (
    CoverageV0,
    FailureV0,
    NameVersionV0,
    UsageV0,
    canonical_json_bytes,
    sha256_hex,
)
from .models import Band, Reason, Verdict

MODEL = "claude-opus-5"
MAX_TOKENS = 6000
# ADR-0018. The API default is "high"; the probe chose "medium" and this
# inherited it, so the shipped reader ran one step below the provider default.
# scripts/llm_probe.py stays at "medium" — it must go on reporting what it
# actually measured — and the divergence is pinned by test on both sides.
#
# UNMEASURED on this prompt. The pre-registration at
# docs/design/reader-effort/preregistration.md is written and has NOT been run.
# Nothing here claims this is better; ADR-0018 records why it shipped anyway
# and exactly what the run would settle.
EFFORT = "high"
# chars. Governed by ADR-0012's coverage bar, NOT by the probe — the
# probe's own DIFF_BUDGET stays at the 30,000 it measured. 100,000 is
# where code+tests coverage saturates (100%/97% over 30 first-parent
# commits) at +$0.019 mean per read; the budget is a ceiling, not a
# spend, and 63% of PRs already fit under 30,000.
DIFF_BUDGET = 100_000
# The mechanical tier: verify_finding and attribute_findings. Neither was
# in the probe, so neither is bound by ADR-0012's freeze — the five frozen
# constants govern the risk read's instrument, and these two are not it.
# Both are also the only paid calls whose output is fully validated in code
# before it can reach a stored row: attribution picks integers from an
# enumerated list checked against a range, and verify names a location
# `verify.run_check` either grounds against the file at head or abstains on.
# A weaker model can therefore only cost an abstention, never a wrong row,
# which is the property that makes this substitution safe and does not hold
# for the risk or intent reads.
MECHANICAL_MODEL = "claude-sonnet-5"
MECHANICAL_EFFORT = "medium"


def mechanical_parameters() -> tuple[NameVersionV0, ...]:
    """What the mechanical tier is configured to send, for the manifest.

    ADR-0027 C3. `WholeInstrumentManifestV0` described the risk or intent read
    and nothing else, so two reads that ran different mechanical models hashed
    to the same `instrument_id` — while ADR-0015 makes `attribute_findings`'
    validated output part of convergence identity, and `example_pack_eval.py`
    partitions the corpus by exactly that hash. The two populations pooled and
    nothing in the data said they should not.

    Named per pass rather than as one block, because ADR-0027 permits the two
    passes to run different models and a combined entry would hide that. The
    keys are `<pass>.<parameter>` so a vendor fork adds parameters here rather
    than translating `effort` into a foreign equivalent by guess, which
    ADR-0027 item 3 refuses.

    This describes CONFIGURATION, not a captured request. Attribution runs
    after the read whose manifest this lands in, so there is no "what was
    actually sent" to record at capture time. What keeps it honest is
    test_the_manifest_matches_what_the_mechanical_requests_actually_send,
    which asserts these values against the request dicts themselves.
    """
    return (
        NameVersionV0(name="verify_finding.model", version=MECHANICAL_MODEL),
        NameVersionV0(name="verify_finding.effort", version=MECHANICAL_EFFORT),
        NameVersionV0(name="attribute_findings.model", version=MECHANICAL_MODEL),
        NameVersionV0(name="attribute_findings.effort", version=MECHANICAL_EFFORT),
    )
DEFAULT_READER_THRESHOLD = 30  # risk_score points, 0-100
# seconds, PER HTTP ATTEMPT — not the whole read. This comment claimed "whole
# read incl. retries' backoff" until 2026-08-23; that was false, and it was the
# sentence anyone sizing the thread pool would have trusted.
DEFAULT_READ_TIMEOUT_S = 120
# Attempts = 1 + MAX_READ_RETRIES, so the whole read is bounded by
# DEFAULT_READ_TIMEOUT_S * 2 = 240s plus backoff. That bound exists to fit
# inside the api service's Cloud Run --timeout 300 (api/deploy/gcp.sh), because
# POST /v1/score/read buys its read synchronously inside the request: at the
# SDK's default of 2 retries the worst case is ~360s and Cloud Run kills the
# request mid-read, so the caller gets a platform 504 instead of the
# reader-unavailable fallback this module contracts for. Pinned against the
# deployed value by test_read_timeout_budget_fits_inside_the_cloud_run_timeout.
MAX_READ_RETRIES = 1
# ADR-0029. Which API surface both tiers call. A value read at client
# construction, never a build-time constant, because ADR-0028 item 6 asked for
# a rollback that is an env change on the running service: a forced transition
# whose rollback needs a deploy is a forced transition with an outage attached.
#
# The DEPLOY names the destination (`deploy/gcp.sh` pins it), and the default
# here is what every UNCONFIGURED environment gets. Those are different jobs and
# an earlier version of this conflated them, defaulting to Vertex so that the
# production value was also the fallback everywhere else.
#
# Doug caught it (`reader:unsafe-default-flip`) and was right. Vertex needs a
# region and application default credentials; a laptop, a script, a CI job or a
# future worker has neither, so the default would raise at client construction
# and every read would fail soft into the deterministic score. Silently — that
# fallback is contracted behaviour for a stalled upstream, so nothing would say
# the reader had stopped. Flipping the default confines this change to the one
# path that is actually configured for it, and leaves every other context
# behaving exactly as it did before.
#
# The rollback property ADR-0028 item 6 asked for is unaffected: production is
# pinned by env, so reverting is still `DOUG_READER_TRANSPORT=anthropic` (or
# clearing it) on the running service, with no release.
TRANSPORT_VERTEX = "vertex"
TRANSPORT_ANTHROPIC = "anthropic"
DEFAULT_TRANSPORT = TRANSPORT_ANTHROPIC
# What `provider` says on each transport. ADR-0028 item 1 ruled that the field
# names the API surface actually called and not the vendor of the weights, so
# this string moves instrument_id and partitions the labelled corpus at the
# cutover. That partition is the point: two serving stacks for the same weights
# can differ in defaults, snapshot pinning, retry and error surfaces, and none
# of those differences is visible in a verdict row.
PROVIDER_BY_TRANSPORT = {
    TRANSPORT_VERTEX: "anthropic-vertex",
    TRANSPORT_ANTHROPIC: "anthropic",
}
INPUT_POLICY_VERSION = "reader-input-v0"
COVERAGE_POLICY_VERSION = "reader-coverage-v0"
INFERENCE_PARAMETERS = (
    NameVersionV0(name="temperature", version="not-specified-provider-default"),
    NameVersionV0(name="top_p", version="not-specified-provider-default"),
)

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


def _compute_prompt_hash() -> str:
    """A stable fingerprint of the frozen bytes (SYSTEM + SCHEMA).

    The "these numbers are about the same instrument" anchor: a receipt or
    a pre-registration document can point at this hash, and it can only
    match a verdict actually produced by this exact prompt. repr(SCHEMA)
    is stable across runs because SCHEMA's key order never changes (it is
    a literal, not something built at import time from a variable set).
    """
    return hashlib.sha256((SYSTEM + repr(SCHEMA)).encode()).hexdigest()


PROMPT_HASH = _compute_prompt_hash()


# --- Verify tier -----------------------------------------------------------
#
# A third, separate read: given ONE finding the diff-reader already produced,
# name the place in the repo whose bytes would ground it. Frozen from creation
# on ADR-0002's terms, like DECISION_INTENT_SYSTEM, and carrying its own hash
# so a receipt can say which verify instrument ran.
#
# Two things are deliberately absent from VERIFY_SCHEMA and must stay absent.
#
# There is no `refuted` field, and no boolean of any kind. The model cannot
# express a conclusion here, so no conclusion of its can be honored. This is
# not defensiveness about hallucination — it is a measured failure. On PR #107
# a refutation of `reader:serialization-contract` quoted models.py's
# `exclude=True` line: byte-matching, grep-re-derivable, and factually true.
# The refutation was still wrong, because models.py records that `exclude` is
# honored by model_dump/FastAPI "and by nothing else". A true quote carried a
# false conclusion. Byte-matching proves the model did not invent the file; it
# proves nothing about the claim.
#
# There is no predicate for absence. `constant_value_is` is an existence-and-
# value claim, and a byte range discharges it completely. "Nothing else reads
# this" is not that shape: the citation shows one place out of a complement the
# model itself chose and never reported, which is exactly the error settle.py's
# docstring names — the check and the error are the same observation. Adding an
# absence predicate later is a new frozen prompt, not an edit to this one.
#
# `checks` is a list so that declining is the natural answer. An empty list
# means the finding needs no read outside the diff, or that no specific
# location can be named. Both leave the finding published and ungrounded,
# which is the only safe default: nothing here may remove a finding.

VERIFY_SYSTEM = (
    "You are given one finding from a code review of a pull request diff, and "
    "you decide what to read to ground it. Do not judge whether the finding is "
    "right or wrong — you are not being asked for a verdict, and nothing you "
    "return can remove the finding. Return the location whose contents would "
    "settle a claim about a specific named value or definition: the file, the "
    "line range, and the exact text you expect to find there. Only claims of "
    "the form 'this named thing is defined here and holds this value' can be "
    "grounded this way. A claim that something does not exist, that no other "
    "caller does X, or that a place is the only one of its kind cannot be "
    "settled by reading one location, and you must return no check for it. "
    "Return no check whenever the finding rests entirely on the diff, or when "
    "you cannot name a specific file and line range with confidence. Returning "
    "nothing is a correct and common answer."
)

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "description": (
                "Locations to read, or empty. Empty when the finding rests on "
                "the diff alone, when the claim is about an absence, or when no "
                "specific location can be named."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Repo-relative path, as it appears in the tree.",
                    },
                    "line_start": {
                        "type": "integer",
                        "description": "1-based, inclusive.",
                    },
                    "line_end": {
                        "type": "integer",
                        "description": "1-based, inclusive. Equal to line_start for one line.",
                    },
                    "quoted_text": {
                        "type": "string",
                        "description": (
                            "The exact text you expect at that range, verbatim and "
                            "including indentation. It is compared byte for byte; a "
                            "mismatch discards the check and the finding stands."
                        ),
                    },
                    "predicate": {
                        "type": "string",
                        "enum": ["constant_value_is"],
                        "description": (
                            "The only supported check: the named constant is defined "
                            "at this range and holds the value shown."
                        ),
                    },
                },
                "required": [
                    "file",
                    "line_start",
                    "line_end",
                    "quoted_text",
                    "predicate",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["checks"],
    "additionalProperties": False,
}

VERIFY_PROMPT_HASH = hashlib.sha256(
    (VERIFY_SYSTEM + repr(VERIFY_SCHEMA)).encode()
).hexdigest()


class VerifyCheck(BaseModel):
    """One location the model asks to have read. A request, never a conclusion."""

    model_config = ConfigDict(extra="forbid")

    file: str
    line_start: int
    line_end: int
    quoted_text: str
    predicate: Literal["constant_value_is"]


class VerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[VerifyCheck] = Field(default_factory=list)


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


class SpendCapExceeded(ReaderError):
    """This scope has spent its monthly deep-read budget; nothing was sent.

    A ReaderError subclass so that any caller which only knows about
    ReaderError still degrades to the deterministic verdict rather than
    500ing — the safe direction to be wrong in. Callers that can tell the
    two apart should: "the reader broke" and "we hit the ceiling" need
    different responses from whoever is on the other end.
    """


# --- The monthly deep-read cap -------------------------------------------
#
# Checked here, in the module that spends the money, rather than in each
# caller: a check in reader.py cannot be bypassed by adding a fourth entry
# point that forgets it, and every one of these functions is one Anthropic
# call away from a bill.
#
# Callers name the scope; this module only spends against it. Un-tenanted
# entry points (the CI review path, the /v1/score/read credential probe)
# charge SENTINEL_SCOPE, which has a ceiling of its own — the CI path is
# deliberately dual-running against the App path as the soak comparison,
# and it must not be able to consume the dogfood installation's budget on
# its way.

SENTINEL_SCOPE = "untenanted"

# Runaway guards, NOT plan limits. Their job today is to bound a redelivery
# loop, a misconfigured install or an abuser — per-installation pricing is
# M4, and nothing here is a considered business figure. One PR costs two
# units (a risk read and an intent read), so 4,000 is on the order of 2,000
# PRs from one installation in one calendar month: far past anything a real
# repo generates, which is the point. Tighten from the cost data the read
# lines below now emit, not from a guess about what a tenant "should" use;
# a ceiling low enough to touch honest traffic would quietly downgrade real
# reviews to the deterministic tier.
INSTALLATION_MONTHLY_READ_CAP = 4000
SENTINEL_MONTHLY_READ_CAP = 1000
# Verify reads spend on their OWN budget, and the separation is not tidiness.
# store.instrument_snapshot resolves its meter with installation_scope() and
# renders the result as `deep reads N/200` on the customer's check run, clamped
# at 200 — so a verify read charged to installation:<id> would show up as
# allowance the customer never used, and at the clamp it reads as exhausted.
# That is a pricing change wearing a feature's clothes. A separate prefix makes
# it structurally impossible rather than a rule someone has to remember.
#
# Same order of magnitude as the installation cap, by the same reasoning: at the
# per-review ceiling below, 4,000 units is ~2,000 PRs from one installation in a
# calendar month. A runaway guard, not a plan limit.
VERIFY_MONTHLY_READ_CAP = 4000

# Per review, not per month. Every verify read is a model call on the live path,
# inside worker.drain's 20-jobs-sequential loop on Starlette's shared pool — so
# this bounds latency as much as spend. Raising it is a repricing and a
# throughput change together, and needs to be argued as both.
MAX_VERIFY_READS_PER_REVIEW = 2

# Strictly below DEFAULT_READ_TIMEOUT_S. A verify read is a small, bounded
# question against one finding; if it has not answered in half the time the
# whole-diff read gets, the finding ships ungrounded and nobody waits.
DEFAULT_VERIFY_TIMEOUT_S = 60


_SCOPE_PREFIX = "installation:"
_VERIFY_SCOPE_PREFIX = "verify:"
_ATTRIBUTION_SCOPE_PREFIX = "attribution:"


def installation_scope(installation_id: int) -> str:
    """The one place an installation's scope string is built."""
    return f"{_SCOPE_PREFIX}{installation_id}"


def installation_from_scope(scope: str) -> int | None:
    """Inverse of installation_scope: whose read is this, if anyone's.

    Exists so a per-installation policy can read the SAME string the spend
    cap charges, rather than taking the installation id as a second
    parameter that could disagree with it. Un-tenanted callers charge
    SENTINEL_SCOPE and get None — there is no installation to have opted
    into anything, which is the safe direction to be wrong in.

    Canonical form only — exactly what installation_scope emits. A looser
    int() would accept "installation:007" as installation 7, which no code
    here can produce, and an allowlist entry of "007" would then fail to
    match the same id written the other way. Two spellings of one id that
    disagree is worse than not recognising the string at all, and an
    unrecognised scope names nobody, which is the safe direction.
    """
    if not scope.startswith(_SCOPE_PREFIX):
        return None
    rest = scope[len(_SCOPE_PREFIX):]
    if not rest.isdigit():
        return None
    value = int(rest)
    return value if str(value) == rest else None


def verify_scope(installation_id: int | None) -> str:
    """The one place a verify read's scope string is built.

    Deliberately NOT installation_scope's prefix: installation_from_scope only
    recognises "installation:", and instrument_snapshot only ever meters what
    installation_scope emits, so a verify read cannot reach the customer's
    published counter by construction.
    """
    if installation_id is None:
        return f"{_VERIFY_SCOPE_PREFIX}{SENTINEL_SCOPE}"
    return f"{_VERIFY_SCOPE_PREFIX}{installation_id}"


def is_verify_scope(scope: str) -> bool:
    return scope.startswith(_VERIFY_SCOPE_PREFIX)


def attribution_scope(installation_id: int | None) -> str:
    """Same posture as verify_scope: its own prefix, so an attribution call
    can never reach the customer's published `deep reads` meter."""
    if installation_id is None:
        return f"{_ATTRIBUTION_SCOPE_PREFIX}{SENTINEL_SCOPE}"
    return f"{_ATTRIBUTION_SCOPE_PREFIX}{installation_id}"


def cap_for(scope: str) -> int:
    if is_verify_scope(scope):
        return VERIFY_MONTHLY_READ_CAP
    return SENTINEL_MONTHLY_READ_CAP if scope == SENTINEL_SCOPE else INSTALLATION_MONTHLY_READ_CAP


def verify_timeout() -> float:
    return float(os.environ.get("DOUG_VERIFY_TIMEOUT_S", DEFAULT_VERIFY_TIMEOUT_S))


def _charge(scope: str) -> None:
    """Spend one read against `scope`, or raise before anything is sent.

    Called before the client is even constructed, let alone the request
    made: store.record_deep_read's contract is that the caller checks it
    BEFORE the model call it meters, since a cap enforced afterwards is not
    spend control, just a receipt.

    Charged on the attempt, not on success. A read that then fails still
    consumed a unit — the failure mode this guards against is a loop that
    retries something broken, and a cap only failed reads could not touch
    would not bound it.

    This is only a cap where there is a ledger to count in:
    record_deep_read returns True when DATABASE_URL is unset, so local
    dogfooding and the open-source path are deliberately uncapped. The
    guarantee is a property of deployments that have a ledger, not of this
    code.
    """
    from . import store  # local: store imports reader.Coverage at module level

    cap = cap_for(scope)
    if not store.record_deep_read(scope, cap):
        raise SpendCapExceeded(
            f"{scope} has spent its cap of {cap} deep reads for this month; "
            "no model call was made"
        )


def _report_cost(response, *, kind: str, scope: str, pr, model: str = MODEL) -> None:
    """One stderr line per paid read: what it cost and what bought it.

    Emitted here because this is the only place `response.usage` exists —
    and before the stop_reason check below, because a read that stops at
    max_tokens is billed for every one of those tokens and then thrown
    away. Reporting cost on the success path alone would hide the most
    expensive reads there are.

    `model` rides on every line and is now a PARAMETER, not the module
    constant it reads by default. The split this docstring used to warn
    about has happened: the risk and intent reads run MODEL, the verify and
    attribution passes run MECHANICAL_MODEL. A line that kept quoting MODEL
    for all four would report the wrong model for half the spend — silently,
    because the string would still be a real model name — which is the
    recurring defect the warning named.

    Unknown token counts print `?`, never 0 — the point of these lines is
    to set the cap from evidence, and a read of unknown cost summed in as a
    free one is worse than an admitted gap.
    """
    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "input_tokens", None)
    tokens_out = getattr(usage, "output_tokens", None)
    sha = getattr(pr, "head_sha", None)
    print(
        f"doug: read #{getattr(pr, 'number', '?')}@{sha[:12] if sha else '?'} (paid read) "
        f"kind={kind} scope={scope} model={model} "
        f"in={tokens_in if tokens_in is not None else '?'} "
        f"out={tokens_out if tokens_out is not None else '?'}",
        file=sys.stderr,
    )


class Citation(BaseModel):
    """Bytes at head that a finding rests on, addressed so a third party can re-derive them.

    `git show <head_sha>:<path>` plus the line range reproduces exactly the bytes
    whose sha256 is recorded here. That is the whole of what a citation establishes —
    the quote, never the conclusion. See ADR-0013 and design-lock L1/L3: the model
    chooses where to look and code runs the check, and a citation may only carry an
    existence-or-value claim. An absence ("nothing else reads this") is not citable,
    because the citation shows one place out of a complement the model itself selected
    and never reported.
    """

    path: str
    head_sha: str
    line_start: int
    line_end: int
    sha256: str

    def locator(self) -> str:
        return f"{self.path}@{self.head_sha}#L{self.line_start}-L{self.line_end}"


def cite(
    *, path: str, head_sha: str, text: str, line_start: int, line_end: int
) -> Citation | None:
    """Address exactly the bytes at `line_start..line_end`, or return None.

    Line numbers are 1-based and inclusive, matching git, every editor, and the
    `#L10-L12` fragment GitHub itself uses — so a reader can check the locator by
    eye against the page it names.

    Returns None rather than raising on a range the text cannot support. That is
    the whole safety property of this increment (design-lock L1): the model picks
    where to look and code checks the pick, so a bad pick has to be a no-op that
    leaves the finding ungrounded, never a wrong receipt. Raising here would turn
    a hallucinated line number into a failed review.

    Deliberately NOT shared with example_pack_verifiers._accepted_contract_receipt,
    which slices the same way. That one resolves a Path under a repo root and emits
    a locator carrying no ref, and its format is a contract in the Example Pack
    lane. Merging them would drag that ref-less format into this one, and a locator
    without a ref is not re-derivable — `git show` has nothing to resolve.
    """
    if line_start < 1 or line_end < line_start:
        return None
    lines = text.splitlines(keepends=True)
    if line_end > len(lines):
        return None
    exact = "".join(lines[line_start - 1 : line_end]).encode("utf-8")
    return Citation(
        path=path,
        head_sha=head_sha,
        line_start=line_start,
        line_end=line_end,
        sha256=sha256_hex(exact),
    )


class ReaderFinding(BaseModel):
    category_slug: str
    description: str
    file: str
    severity: str
    # Defaulted so every finding the frozen SCHEMA produces is unchanged and
    # PROMPT_HASH does not move: SCHEMA still emits exactly the four fields above.
    # `evidence` is what makes REVIEWING.md's "a finding that depends on code outside
    # the diff must say so" enforceable rather than a convention — the two claim
    # classes have to be machine-separable before they can be governed differently.
    evidence: Literal["diff", "head-cited"] = "diff"
    citations: list[Citation] = Field(default_factory=list)


class ReaderVerdict(BaseModel):
    risk_score: int
    rationale: str
    findings: list[ReaderFinding]


def _verify_user_text(finding: ReaderFinding) -> str:
    return (
        f"Finding: {finding.category_slug}\n"
        f"File named by the finding: {finding.file}\n"
        f"Claim: {finding.description}\n"
    )


def verify_finding(finding: ReaderFinding, *, scope: str, client=None) -> VerifyResponse:
    """Ask where to look to ground one finding. One charged model call.

    Deliberately NOT routed through _record_attempt. The Example Pack lane's
    attempt_kind is a closed two-value Literal that raises at five sites for
    anything else, and WholeInstrumentManifestV0 is extra="forbid" with no field
    that could describe this tier — so a verify attempt has no honest
    representation there. Emitting one would mean either widening a frozen
    schema or mislabelling this as a risk read. It stays out until the
    instrument question in design-lock L6 is answered.
    """
    _charge(scope)
    if client is None:
        client = _verify_client()
    request = {
        "model": MECHANICAL_MODEL,
        "max_tokens": MAX_TOKENS,
        "output_config": {
            "effort": MECHANICAL_EFFORT,
            "format": {"type": "json_schema", "schema": VERIFY_SCHEMA},
        },
        "system": VERIFY_SYSTEM,
        "messages": [{"role": "user", "content": _verify_user_text(finding)}],
    }
    try:
        response = client.messages.create(**request)
    except Exception as e:  # noqa: BLE001 — same contract as read_diff
        raise ReaderError(f"{type(e).__name__}: {e}") from e
    _report_cost(response, kind="verify", scope=scope, pr=None, model=MECHANICAL_MODEL)
    text = next((b.text for b in response.content if b.type == "text"), "")
    if response.stop_reason != "end_turn":
        raise ReaderError(f"verify stopped with {response.stop_reason}")
    try:
        return VerifyResponse.model_validate_json(text)
    except Exception as e:  # noqa: BLE001
        raise ReaderError(f"verify parse failed: {type(e).__name__}: {e}") from e


def ground_findings(
    rv: ReaderVerdict,
    *,
    head_sha: str | None,
    resolve_file,
    scope: str,
    client=None,
) -> tuple[ReaderVerdict, int]:
    """Attach citations to findings a head read can ground. Returns (rv, n_grounded).

    Additive and total: every finding that goes in comes out. The only change a
    finding can undergo here is gaining an evidence class and a citation — there
    is no path that removes one, and the assertion below states that as a
    property rather than trusting the loop to stay that way.

    Fails soft on everything. A spend cap, a transport error, a stopped
    generation, an unparseable response — all of them leave the review exactly
    as it was, with every finding published and diff-classed. The model chooses
    where to look, so a bad choice must cost nothing; the alternative is a
    hallucinated line number taking down a review.
    """
    if head_sha is None or resolve_file is None or not rv.findings:
        return rv, 0

    from . import verify as verify_mod

    grounded_count = 0
    spent = 0
    out: list[ReaderFinding] = []

    for i, finding in enumerate(rv.findings):
        if spent >= MAX_VERIFY_READS_PER_REVIEW:
            out.extend(rv.findings[i:])
            break
        try:
            spent += 1
            response = verify_finding(finding, scope=scope, client=client)
        except SpendCapExceeded as e:
            print(f"doug: verify capped ({e}); findings stay ungrounded", file=sys.stderr)
            out.extend(rv.findings[i:])
            break
        except ReaderError as e:
            print(f"doug: verify failed ({e}); finding stays ungrounded", file=sys.stderr)
            out.append(finding)
            continue
        except Exception as e:  # noqa: BLE001 — grounding must never break a review
            print(f"doug: verify errored ({type(e).__name__}: {e})", file=sys.stderr)
            out.append(finding)
            continue

        citations: list[Citation] = []
        for check in response.checks:
            outcome = verify_mod.run_check(
                check, head_sha=head_sha, resolve_file=resolve_file
            )
            if outcome.citation is not None:
                citations.append(outcome.citation)
            else:
                print(
                    f"doug: verify abstained for reader:{finding.category_slug} "
                    f"({outcome.abstained_because})",
                    file=sys.stderr,
                )
        if citations:
            grounded_count += 1
            out.append(
                finding.model_copy(
                    update={"evidence": "head-cited", "citations": citations}
                )
            )
        else:
            out.append(finding)

    # Identity, not count. An earlier draft repaired a short list by re-slicing
    # from the original, which restored the LENGTH while losing one finding and
    # duplicating another — the assertion passed and the corruption was silent.
    # A mutation test caught it. Compare what came out against what went in.
    assert [f.category_slug for f in out] == [
        f.category_slug for f in rv.findings
    ], "grounding must be additive: every finding in, the same findings out"
    return rv.model_copy(update={"findings": out}), grounded_count


def enabled() -> bool:
    return os.environ.get("DOUG_READER") == "1"


def attribution_enabled() -> bool:
    """Opt-in, default off — the same land-dark posture as DOUG_VERIFY. The
    convergence classifier degrades a missing attribution to
    unknown(not-reconfirmed), so running dark costs abstentions, never
    wrong answers."""
    return os.environ.get("DOUG_ATTRIBUTION") == "1"


VERIFY_ALLOWLIST_ENV = "DOUG_VERIFY_INSTALLATIONS"


def verify_enabled_for(installation_id: int | None) -> bool:
    """Is grounding on for THIS installation?

    Grounding adds paid model calls to the live path and changes what renders on
    a check run. Landing the code dark meant the PR that introduced it could be
    merged without changing what Doug does to anyone; switching it on is the
    deliberate act that posture was reserving.

    An ALLOWLIST rather than the process-wide `DOUG_VERIFY=1` boolean this
    replaced, for the reason design-lock.md:64 records against the identical
    mistake one tier down: `DOUG_INTENT=1` shipped as a process-wide switch and
    was "the opposite of 'default OFF', enabling the experimental tier for every
    installation the service reviewed. It was harmless only because there has
    only ever been one installation." Turning grounding on for the dogfood
    install is a decision about the dogfood install; a boolean would make it a
    decision about every tenant, and would keep making it silently for every
    tenant added later.

    Same shape and same failure mode as `intent.enabled_for` and
    `pr_comment.allowed`: an unset or empty allowlist enables nobody, never
    everybody. Un-tenanted callers (the CLI, the sentinel scope) are
    structurally excluded, because `installation_from_scope` returns None for
    them and None is not in any allowlist.
    """
    if installation_id is None:
        return False
    allow = os.environ.get(VERIFY_ALLOWLIST_ENV, "")
    return str(installation_id) in {i.strip() for i in allow.split(",") if i.strip()}


def reader_threshold() -> float:
    return float(os.environ.get("DOUG_READER_THRESHOLD", DEFAULT_READER_THRESHOLD))


def read_timeout() -> float:
    return float(os.environ.get("DOUG_READ_TIMEOUT_S", DEFAULT_READ_TIMEOUT_S))


def _client():
    """A client with a bounded timeout, never the SDK default.

    The SDK defaults to a 600s timeout, and both read entry points run
    synchronously on Starlette's shared request thread pool (~40 workers,
    /healthz included). At the default, one stalled upstream connection
    parks a worker; forty of them and the whole service reads as down. 120s
    is well above any legitimate read and turns the same stall into a
    contained ReaderError fallback instead.

    `max_retries` is passed for the same reason and is NOT the SDK default.
    The default of 2 makes the worst case three attempts — about six minutes —
    which outlives the api service's Cloud Run `--timeout 300` on the one route
    that buys a read synchronously inside the request (`POST /v1/score/read`).
    There the platform kills the request mid-read and the caller gets a 504
    instead of the `reader-unavailable` fallback this module contracts for. At
    MAX_READ_RETRIES = 1 the bound is 240s plus backoff, inside 300 with margin.

    The webhook path is insulated either way — it 202s first and drains in a
    background task — so this is about the synchronous route. Retrying once
    rather than not at all keeps the transient-5xx recovery the SDK gives us;
    the second retry is what does not fit.
    """
    return _build_client(read_timeout())


def _verify_client():
    """Same posture as _client, on the tighter verify budget — retry bound
    included, for the same Cloud Run arithmetic. Grounding runs inside
    score_one, which runs inside the same synchronous request."""
    return _build_client(verify_timeout())


def transport() -> str:
    """The API surface the next client will call. ADR-0029."""
    value = os.environ.get("DOUG_READER_TRANSPORT", DEFAULT_TRANSPORT).strip().lower()
    return value if value in PROVIDER_BY_TRANSPORT else DEFAULT_TRANSPORT


def provider_name() -> str:
    """What `provider` records for a read taken on the current transport."""
    return PROVIDER_BY_TRANSPORT[transport()]


def _build_client(timeout: float):
    """The one construction site for both tiers, on either transport.

    `MODEL` reaches the wire verbatim on both, with no transport-specific
    mapping. ADR-0028 refuses a mapping layer by name, and the reason is the
    freeze: a mapping is how `MODEL` comes to say one thing while the wire says
    another, which is the state ADR-0012 exists to make impossible. Vertex
    serves current-generation models under the bare first-party id, so the
    string is the same on both transports. If a dated snapshot is ever pinned
    the two stop sharing a string, and that reopens ADR-0028 rather than
    earning a mapping here.

    `region` is deliberately not defaulted. Claude is not served from every
    Vertex region, and the api service's own region is not necessarily one of
    them. A wrong region does not fail loudly: every read fails soft into the
    deterministic score, which reads as "the reader is down" rather than "the
    region is wrong". So the SDK's own ValueError — which names
    `CLOUD_ML_REGION` — is left to raise, and `deploy/gcp.sh` refuses to deploy
    without a value. `project_id` needs no such treatment because application
    default credentials carry the project on Cloud Run.

    `max_retries` is passed on both paths. AnthropicVertex defaults it to 2,
    exactly as Anthropic does, so the Cloud Run arithmetic in `_client` binds
    identically on the new transport and is not re-derived here.
    """
    import anthropic

    if transport() == TRANSPORT_VERTEX:
        return anthropic.AnthropicVertex(timeout=timeout, max_retries=MAX_READ_RETRIES)
    return anthropic.Anthropic(timeout=timeout, max_retries=MAX_READ_RETRIES)


def _sent_slice(diff: str, *, budget: int | None = None) -> str:
    """The exact bytes the selected budget admits — the one slice point.

    coverage() re-derives what a read saw from this same function, so it can
    never drift from what _user_text actually sent to the model. Historical
    evidence callers may name their own instrument budget without mutating the
    live module global.
    """
    return diff[: DIFF_BUDGET if budget is None else budget]


def _user_text(pr, diff: str) -> str:
    sent = _sent_slice(diff)
    truncated = len(diff) > len(sent)
    return (
        f"Title: {pr.title}\n"
        f"Files changed: {', '.join(pr.files)}\n"
        + ("[diff truncated at budget]\n" if truncated else "")
        + f"\n{sent}"
    )


# --- what the read actually saw ------------------------------------------
#
# _user_text cuts the diff at DIFF_BUDGET and moves on. That cut is silent
# everywhere downstream: a verdict from a fully-read PR and a verdict from a
# 44%-read PR are the same shape, store the same columns, and render the
# same way. lemahq/lema#643 cleared at 0.26 having been shown 30,000 of
# 68,430 chars; the tenancy leak a human later found was 2,266 chars past
# the cut, and the mutation-verified test file that would have deduped two
# of its other findings was never sent at all.
#
# These functions only observe the cut. DIFF_BUDGET is governed by
# ADR-0012's coverage bar and EFFORT by ADR-0018; SYSTEM, SCHEMA, MODEL and
# MAX_TOKENS remain frozen to the validated probe. A partial read therefore
# stops looking like a complete one.


def diff_chunk(filename: str, status: str, additions: int, deletions: int, patch: str) -> str:
    """One file's block, in the one shape review.py is allowed to build it.

    review.py used to write this f-string twice (fetch_pr, fetch_open_prs)
    and _FILE_HEADER re-derived the same shape a third time, independently.
    A format change in any one of the three would have silently broken
    coverage() — files_sent dropping to 0, a complete read reporting itself
    as fully unseen — without an error anywhere. One function, used
    everywhere the shape is needed, is what makes that impossible now.
    """
    return f"### {filename} ({status}, +{additions}/-{deletions})\n{patch}"


CHUNK_SEPARATOR = "\n\n"

_FILE_HEADER = re.compile(r"^### (.+) \([a-z]+, \+\d+/-\d+\)$", re.M)


class Coverage(BaseModel):
    """How much of a PR's diff reached the model.

    `file_cut` is the file the budget landed inside — seen in part, and the
    most dangerous case, because the model has enough of it to reason about
    and not enough to be right.
    """

    diff_chars: int
    sent_chars: int
    files_sent: int
    files_unseen: list[str]
    file_cut: str | None = None
    # From the PR object, not derived here — coverage() only ever sees the
    # diff text, never the original file list. A display fact only (the
    # receipt's "N of M files"): `complete` does not compare against it,
    # because changed_files counts files that structurally never produce
    # a diff header (genuine binaries), which files_sent could never
    # match. None = not tracked (old callers).
    changed_files: int | None = None
    files_dropped: list[str] = Field(default_factory=list)
    # Content-hash index over the hunks that were actually SENT — the
    # Walked Out convergence identity (docs/design/walked-out/). Keyed by
    # path; ordered sha256 list per file; only files whose whole chunk
    # arrived within the budget appear (file_cut and unseen files do not),
    # so a stored index bakes this read's coverage in. None = not computed
    # (rows from before migration 12).
    hunks: dict[str, list[str]] | None = None

    @property
    def complete(self) -> bool:
        # files_dropped, not changed_files == files_sent: a genuinely
        # binary file (caller excludes it from files_dropped) never
        # produces a diff header at all, so files_sent could never equal
        # changed_files on an ordinary PR that touches one. changed_files
        # is a display fact (the receipt's "N of M"), not part of this
        # check.
        return self.sent_chars >= self.diff_chars and not self.files_dropped

    @property
    def fraction(self) -> float:
        return 1.0 if not self.diff_chars else self.sent_chars / self.diff_chars


def _chunk_content_end(matches: list, pos: int, diff_len: int) -> int:
    """Where chunk `pos`'s patch text ends. THE one home for the geometry:
    review.py joins chunks with exactly CHUNK_SEPARATOR, so content runs to
    that separator before the next header, or to the end of the diff for the
    final file. coverage() and _sent_file_patches both read this — a format
    change updated in one place cannot silently disagree with the other
    (the drift Doug's own review of this change flagged).
    """
    if pos + 1 < len(matches):
        return matches[pos + 1].start() - len(CHUNK_SEPARATOR)
    return diff_len


def _chunk_patch(diff: str, matches: list, pos: int, sent_len: int) -> str | None:
    """Chunk `pos`'s patch text, or None unless it arrived IN FULL within the
    sent slice. The cut file's content end lies past the slice point by
    construction, so it is never returned."""
    m = matches[pos]
    content_end = _chunk_content_end(matches, pos, len(diff))
    if content_end > sent_len:
        return None
    return diff[m.end() + 1 : content_end] if m.end() + 1 <= content_end else ""


def coverage(
    diff: str,
    *,
    changed_files: int | None = None,
    files_dropped: list[str] | None = None,
    budget: int | None = None,
) -> Coverage:
    """Observe the truncation _user_text performs. Pure over `diff` and the
    selected budget; sends nothing. `changed_files`/`files_dropped` are
    supplied by the caller, not derived here — they describe files that never
    reached this function's input at all (fetch_pr drops files GitHub returns without a
    patch: binary, or too large to inline), which is a different hole from
    the budget truncation this function observes directly.

    Files are counted from the diff's own `### path (status, +a/-d)` headers
    rather than from a PR's file list, for the same reason: a file with no
    patch never produces a header, so it cannot appear in files_unseen.
    """
    sent = _sent_slice(diff, budget=budget)
    matches = list(_FILE_HEADER.finditer(diff))
    all_files = [m.group(1) for m in matches]
    # A header counts as sent only if it arrived in full — a header cut
    # mid-line never matches _FILE_HEADER's `$` at all, so it is correctly
    # absent from `seen` and its file lands in files_unseen below.
    seen = [m for m in matches if m.end() <= len(sent)]
    names = [m.group(1) for m in seen]
    seen_names = set(names)
    cut = None
    if len(sent) < len(diff) and seen:
        last = len(seen) - 1
        # review.py joins chunks with exactly CHUNK_SEPARATOR, so the last
        # seen file's real content ends CHUNK_SEPARATOR chars before the
        # next header starts (or at len(diff), if it's the final file).
        # Only call this file "cut" when the missing span is bigger than
        # that separator — otherwise the budget landed cleanly between two
        # whole files, and nothing about this one was actually partial.
        next_start = matches[last + 1].start() if last + 1 < len(matches) else len(diff)
        if next_start - len(sent) > len(CHUNK_SEPARATOR):
            cut = names[-1]
    # Hunk index over the SENT slice only. _chunk_patch returns None for any
    # chunk that did not arrive in full, so file_cut and unseen files are
    # never indexed, and a clean between-files cut leaves the last whole
    # file indexed.
    index: dict[str, list[str]] = {}
    for pos, m in enumerate(matches):
        patch = _chunk_patch(diff, matches, pos, len(sent))
        if patch is not None:
            index[m.group(1)] = [hunks.hash_hunk(h) for h in hunks.split_hunks(patch)]
    return Coverage(
        diff_chars=len(diff),
        sent_chars=len(sent),
        files_sent=len(names),
        # Membership via set; iteration order preserved from all_files so
        # pinned files_unseen sequences in test_coverage stay bit-identical.
        files_unseen=[f for f in all_files if f not in seen_names],
        file_cut=cut,
        changed_files=changed_files,
        files_dropped=files_dropped or [],
        hunks=index,
    )


def hunk_index(diff: str, *, budget: int | None = None) -> dict[str, list[str]]:
    """The hunk index for `diff` under `budget` — coverage()'s, verbatim.

    A wrapper rather than a second derivation: the index the ledger stores
    and the index an offline caller computes from the same text must be the
    same function or the eval grades labels the product never produced.
    """
    cov = coverage(diff, budget=budget)
    assert cov.hunks is not None
    return cov.hunks


def truncation_reason(cov: Coverage) -> Reason | None:
    """A loud line on the verdict when the read was partial, or None.

    Deliberately outside the `reader:` namespace: patterns.from_rule only
    canonicalises `reader:` rules, so this shares the findings table with
    real defect patterns without ever being counted as one. A meta-fact
    about the read is not a defect pattern, and pooling the two would
    corrupt the precision table it feeds.
    """
    if cov.complete:
        return None
    unseen = cov.files_unseen[:3]
    tail = f" (+{len(cov.files_unseen) - 3} more)" if len(cov.files_unseen) > 3 else ""
    label = (
        f"Partial read: {cov.fraction:.0%} of the diff "
        f"({cov.sent_chars:,} of {cov.diff_chars:,} chars)."
        + (f" Cut inside {cov.file_cut}." if cov.file_cut else "")
        + (f" Never sent: {', '.join(unseen)}{tail}." if unseen else "")
        + (f" Never fetched: {', '.join(cov.files_dropped)}." if cov.files_dropped else "")
        + " Findings below cover only what was sent; a clear is not evidence"
        " about the rest."
    )
    return Reason(rule="read-truncated", label=label, weight=0.0)


def _capture_coverage(pr, diff: str) -> CoverageV0:
    observed = coverage(
        diff,
        changed_files=getattr(pr, "changed_files", None),
        files_dropped=getattr(pr, "files_dropped", None),
    )
    return CoverageV0(
        diff_chars=observed.diff_chars,
        sent_chars=observed.sent_chars,
        files_sent=observed.files_sent,
        files_unseen=tuple(observed.files_unseen),
        file_cut=observed.file_cut,
        changed_files=observed.changed_files,
        files_dropped=tuple(observed.files_dropped),
    )


def _capture_usage(response) -> UsageV0:
    usage = getattr(response, "usage", None)
    return UsageV0(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
    )


def _failure(phase: str, exc: BaseException) -> FailureV0:
    safe_detail = {
        "preflight": "attempt stopped before an SDK request was created",
        "transport": "SDK request failed before a response was available",
        "stop_reason": "model response did not end with end_turn",
        "parse": "selected model text did not match the output schema",
    }[phase]
    error_type = type(exc).__name__[:120]
    return FailureV0(
        phase=phase,
        error_type=error_type,
        detail=f"{error_type}: {safe_detail}",
    )


def _record_attempt(
    *,
    attempt_kind: str,
    pr,
    diff: str,
    request_bytes: bytes | None,
    raw_output_bytes: bytes | None,
    parsed_output: dict | None,
    response,
    started_ns: int,
    model_call_made: bool,
    failure: FailureV0 | None,
    fallback_state: str,
    system: str,
    schema: dict,
    request_error_type: str | None = None,
) -> None:
    """One best-effort boundary: no capture error may escape into a read."""
    if (
        not example_pack_capture.capture_requested()
        or example_pack_capture.capture_suppressed()
    ):
        return
    try:
        example_pack_capture.record_attempt(
            attempt_kind=attempt_kind,
            request_bytes=request_bytes,
            request_error_type=request_error_type,
            evidence_bytes=diff.encode("utf-8"),
            raw_output_bytes=raw_output_bytes,
            parsed_output=parsed_output,
            coverage=_capture_coverage(pr, diff),
            usage=(
                _capture_usage(response)
                if response is not None
                else UsageV0(input_tokens=None, output_tokens=None)
            ),
            latency_ms=max(0, (time.monotonic_ns() - started_ns) // 1_000_000),
            model_call_made=model_call_made,
            failure=failure,
            fallback_state=fallback_state,
            provider=provider_name(),
            model=MODEL,
            max_output_tokens=MAX_TOKENS,
            effort=EFFORT,
            inference_parameters=INFERENCE_PARAMETERS,
            mechanical_parameters=mechanical_parameters(),
            system_prompt_bytes=system.encode("utf-8"),
            output_schema_bytes=canonical_json_bytes(schema),
            diff_budget=DIFF_BUDGET,
        )
    except Exception as exc:  # noqa: BLE001 - defense in depth around capture
        active = example_pack_capture.current_scope()
        run_id = (
            f"{active.run_id_prefix}:{attempt_kind}" if active is not None else "unscoped"
        )
        print(
            f"doug: example-pack capture failed run_id={run_id} "
            f"error={type(exc).__name__}",
            file=sys.stderr,
        )


def read_diff(pr, diff: str, *, scope: str, client=None) -> ReaderVerdict:
    """The risk read. `scope` is who pays for it, and is required rather
    than defaulted: a default is how the next caller silently becomes
    un-metered, which is the bug this cap exists to close."""
    started_ns = time.monotonic_ns()
    try:
        _charge(scope)
    except SpendCapExceeded as exc:
        _record_attempt(
            attempt_kind="risk",
            pr=pr,
            diff=diff,
            request_bytes=None,
            raw_output_bytes=None,
            parsed_output=None,
            response=None,
            started_ns=started_ns,
            model_call_made=False,
            failure=_failure("preflight", exc),
            fallback_state="spend_capped",
            system=SYSTEM,
            schema=SCHEMA,
        )
        raise
    if client is None:
        try:
            client = _client()
        except Exception as exc:  # noqa: BLE001 - preserve existing exception
            _record_attempt(
                attempt_kind="risk",
                pr=pr,
                diff=diff,
                request_bytes=None,
                raw_output_bytes=None,
                parsed_output=None,
                response=None,
                started_ns=started_ns,
                model_call_made=False,
                failure=_failure("preflight", exc),
                fallback_state="deterministic_expected",
                system=SYSTEM,
                schema=SCHEMA,
            )
            raise
    request = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "output_config": {
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        "system": SYSTEM,
        "messages": [{"role": "user", "content": _user_text(pr, diff)}],
    }
    request_bytes, request_error_type = example_pack_capture.prepare_request_bytes(
        request, attempt_kind="risk"
    )
    try:
        response = client.messages.create(**request)
    except Exception as e:  # noqa: BLE001 — every transport failure is a ReaderError
        _record_attempt(
            attempt_kind="risk",
            pr=pr,
            diff=diff,
            request_bytes=request_bytes,
            request_error_type=request_error_type,
            raw_output_bytes=None,
            parsed_output=None,
            response=None,
            started_ns=started_ns,
            model_call_made=True,
            failure=_failure("transport", e),
            fallback_state="deterministic_expected",
            system=SYSTEM,
            schema=SCHEMA,
        )
        # Anything the SDK raises — billing, rate limit, timeout, 5xx — is a
        # failed read, and this module's contract is that a failed read falls
        # back loudly rather than propagating. Letting these escape meant one
        # exhausted balance 500'd every customer's CI, reported as success
        # because the workflow step is continue-on-error.
        raise ReaderError(f"{type(e).__name__}: {e}") from e
    _report_cost(response, kind="risk", scope=scope, pr=pr)
    text = next((b.text for b in response.content if b.type == "text"), "")
    raw_output_bytes = text.encode("utf-8")
    if response.stop_reason != "end_turn":
        exc = ReaderError(f"read stopped with {response.stop_reason}")
        _record_attempt(
            attempt_kind="risk",
            pr=pr,
            diff=diff,
            request_bytes=request_bytes,
            request_error_type=request_error_type,
            raw_output_bytes=raw_output_bytes,
            parsed_output=None,
            response=response,
            started_ns=started_ns,
            model_call_made=True,
            failure=_failure("stop_reason", exc),
            fallback_state="deterministic_expected",
            system=SYSTEM,
            schema=SCHEMA,
        )
        raise exc
    try:
        verdict = ReaderVerdict.model_validate_json(text)
    except ValueError as e:
        exc = ReaderError(f"unparseable reader output: {e}")
        _record_attempt(
            attempt_kind="risk",
            pr=pr,
            diff=diff,
            request_bytes=request_bytes,
            request_error_type=request_error_type,
            raw_output_bytes=raw_output_bytes,
            parsed_output=None,
            response=response,
            started_ns=started_ns,
            model_call_made=True,
            failure=_failure("parse", exc),
            fallback_state="deterministic_expected",
            system=SYSTEM,
            schema=SCHEMA,
        )
        raise exc from e
    _record_attempt(
        attempt_kind="risk",
        pr=pr,
        diff=diff,
        request_bytes=request_bytes,
        request_error_type=request_error_type,
        raw_output_bytes=raw_output_bytes,
        parsed_output=verdict.model_dump(mode="json"),
        response=response,
        started_ns=started_ns,
        model_call_made=True,
        failure=None,
        fallback_state="none",
        system=SYSTEM,
        schema=SCHEMA,
    )
    return verdict


class DeviationFinding(BaseModel):
    type: str
    description: str
    severity: str


class IntentReaderVerdict(ReaderVerdict):
    intent_alignment: int
    deviation_findings: list[DeviationFinding]


def _intent_text(pr, diff: str, docs) -> str:
    """Decisions first, then the diff — same ordering the probe validated."""
    block = "\n\n".join(
        f"[{d.id}] {d.title}\n{d.body}" for d in docs
    )
    return (
        "Recorded architecture decisions this team considers binding:\n"
        f"{block}\n\n---\n" + _user_text(pr, diff)
    )


def read_with_decisions(pr, diff: str, docs, *, scope: str, client=None) -> IntentReaderVerdict:
    """The intent read. Never called with an empty `docs` — a read with no
    decisions in it is the diff-only read, and asking the model to compare
    against nothing invites invented findings.

    Charges the same `scope` the risk read does, so one PR costs two units:
    one knob per tenant, and no ambiguity about which read exhausted it.
    The empty-docs refusal above comes first — it sends nothing, so it must
    cost nothing.
    """
    if not docs:
        raise ReaderError("no decision records to read against")
    started_ns = time.monotonic_ns()
    try:
        _charge(scope)
    except SpendCapExceeded as exc:
        _record_attempt(
            attempt_kind="intent",
            pr=pr,
            diff=diff,
            request_bytes=None,
            raw_output_bytes=None,
            parsed_output=None,
            response=None,
            started_ns=started_ns,
            model_call_made=False,
            failure=_failure("preflight", exc),
            fallback_state="spend_capped",
            system=DECISION_INTENT_SYSTEM,
            schema=INTENT_SCHEMA,
        )
        raise
    if client is None:
        try:
            client = _client()
        except Exception as exc:  # noqa: BLE001 - preserve existing exception
            _record_attempt(
                attempt_kind="intent",
                pr=pr,
                diff=diff,
                request_bytes=None,
                raw_output_bytes=None,
                parsed_output=None,
                response=None,
                started_ns=started_ns,
                model_call_made=False,
                failure=_failure("preflight", exc),
                fallback_state="intent_unavailable",
                system=DECISION_INTENT_SYSTEM,
                schema=INTENT_SCHEMA,
            )
            raise
    request = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "output_config": {
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": INTENT_SCHEMA},
        },
        "system": DECISION_INTENT_SYSTEM,
        "messages": [{"role": "user", "content": _intent_text(pr, diff, docs)}],
    }
    request_bytes, request_error_type = example_pack_capture.prepare_request_bytes(
        request, attempt_kind="intent"
    )
    try:
        response = client.messages.create(**request)
    except Exception as exc:  # noqa: BLE001 - preserve the existing SDK exception
        _record_attempt(
            attempt_kind="intent",
            pr=pr,
            diff=diff,
            request_bytes=request_bytes,
            request_error_type=request_error_type,
            raw_output_bytes=None,
            parsed_output=None,
            response=None,
            started_ns=started_ns,
            model_call_made=True,
            failure=_failure("transport", exc),
            fallback_state="intent_unavailable",
            system=DECISION_INTENT_SYSTEM,
            schema=INTENT_SCHEMA,
        )
        raise
    _report_cost(response, kind="intent", scope=scope, pr=pr)
    text = next((b.text for b in response.content if b.type == "text"), "")
    raw_output_bytes = text.encode("utf-8")
    if response.stop_reason != "end_turn":
        exc = ReaderError(f"intent read stopped with {response.stop_reason}")
        _record_attempt(
            attempt_kind="intent",
            pr=pr,
            diff=diff,
            request_bytes=request_bytes,
            request_error_type=request_error_type,
            raw_output_bytes=raw_output_bytes,
            parsed_output=None,
            response=response,
            started_ns=started_ns,
            model_call_made=True,
            failure=_failure("stop_reason", exc),
            fallback_state="intent_unavailable",
            system=DECISION_INTENT_SYSTEM,
            schema=INTENT_SCHEMA,
        )
        raise exc
    try:
        verdict = IntentReaderVerdict.model_validate_json(text)
    except ValueError as e:
        exc = ReaderError(f"unparseable intent output: {e}")
        _record_attempt(
            attempt_kind="intent",
            pr=pr,
            diff=diff,
            request_bytes=request_bytes,
            request_error_type=request_error_type,
            raw_output_bytes=raw_output_bytes,
            parsed_output=None,
            response=response,
            started_ns=started_ns,
            model_call_made=True,
            failure=_failure("parse", exc),
            fallback_state="intent_unavailable",
            system=DECISION_INTENT_SYSTEM,
            schema=INTENT_SCHEMA,
        )
        raise exc from e
    _record_attempt(
        attempt_kind="intent",
        pr=pr,
        diff=diff,
        request_bytes=request_bytes,
        request_error_type=request_error_type,
        raw_output_bytes=raw_output_bytes,
        parsed_output=verdict.model_dump(mode="json"),
        response=response,
        started_ns=started_ns,
        model_call_made=True,
        failure=None,
        fallback_state="none",
        system=DECISION_INTENT_SYSTEM,
        schema=INTENT_SCHEMA,
    )
    return verdict


def verdict_from_reader(rv: ReaderVerdict, threshold: float | None = None) -> Verdict:
    thr = reader_threshold() if threshold is None else threshold
    band = Band.FLAGGED if rv.risk_score >= thr else Band.CLEARED
    reasons = [
        Reason(
            rule=f"reader:{f.category_slug}",
            label=f.description,
            weight=0.0,
            severity=f.severity,
            file=f.file,
        )
        for f in rv.findings
    ]
    return Verdict(
        score=round(rv.risk_score / 100, 2),
        band=band,
        threshold=thr / 100,
        reasons=reasons,
    )


# --- Attribution tier (ADR-0015; Walked Out) -------------------------------
#
# One small charged call after a reader-tier read: map each finding to the
# numbered hunks of its cited file's sent diff. The task shape is EXACTLY the
# one the pre-registered span-verification pass validated (0/84 state flips
# across identical double runs, 42/42 controls, 0/25 danger-class
# contradictions; docs/design/walked-out/span-verification.md): closed-choice
# attribution over enumerated hunks, code validating every number. The model
# picks; code converts picks to content hashes from Coverage.hunks and stores
# them on the finding row — classify consumes stored hashes only and never
# re-derives. Fails soft on everything: a failed or abstained call stores
# nothing, and a missing attribution is an abstention downstream, never a
# wrong answer. SYSTEM/SCHEMA above are untouched; this tier carries its own
# frozen pair and hash.

ATTRIBUTION_SYSTEM = (
    "You are attributing code-review findings to the diff hunks they rest "
    "on. Each file's hunks are numbered exactly as sent to the reviewer. "
    "For each FINDING id, decide which hunk number(s) the finding is about "
    "- the hunks whose changed lines the finding describes. Judge only from "
    "the hunk text shown. If a finding is about the file as a whole, or you "
    "cannot tell which hunk(s), return an empty list for it. Return every "
    "FINDING id exactly once."
)

ATTRIBUTION_SCHEMA = {
    "type": "object",
    "properties": {
        "attributions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding": {"type": "integer"},
                    "hunks": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["finding", "hunks"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["attributions"],
    "additionalProperties": False,
}

ATTRIBUTION_PROMPT_HASH = hashlib.sha256(
    (ATTRIBUTION_SYSTEM + repr(ATTRIBUTION_SCHEMA)).encode()
).hexdigest()

ATTRIBUTION_MAX_TOKENS = 2000


def _sent_file_patches(diff: str, cov: Coverage) -> dict[str, str] | None:
    """Per-file patch text for every fully-sent file, or None on drift.

    Re-derives the same geometry coverage() used (same slice point, same
    header regex, same separator), then self-checks: the hashes of what this
    parse yields must equal the stored index, or the attribution prompt
    would number hunks the index does not describe — that mismatch fails
    soft rather than storing a wrong mapping.
    """
    if cov.hunks is None:
        return None
    matches = list(_FILE_HEADER.finditer(diff))
    patches: dict[str, str] = {}
    for pos, m in enumerate(matches):
        name = m.group(1)
        if name not in cov.hunks:
            continue
        patch = _chunk_patch(diff, matches, pos, cov.sent_chars)
        if patch is not None:
            patches[name] = patch
    for name, patch in patches.items():
        derived = [hunks.hash_hunk(h) for h in hunks.split_hunks(patch)]
        if derived != cov.hunks.get(name):
            return None
    if set(patches) != set(cov.hunks):
        return None
    return patches


def attribute_findings(reasons: list, diff: str, cov: Coverage, *, scope: str, client=None) -> int:
    """Attach validated hunk attributions to reader-finding Reasons, in place.

    Returns how many findings gained an attribution. Fails soft on
    everything — spend cap, transport, stop reason, parse, out-of-range
    numbers, index drift — because the model only ever picks from an
    enumerated list and code owns the conversion: a bad pick must cost an
    abstention downstream, never a wrong stored mapping (the posture
    ground_findings established for the verify tier).
    """
    candidates = [
        r
        for r in reasons
        if r.rule.startswith("reader:")
        and getattr(r, "file", None)
        and cov.hunks is not None
        and len(cov.hunks.get(r.file) or []) >= 1
    ]
    if not candidates:
        return 0
    patches = _sent_file_patches(diff, cov)
    if patches is None:
        return 0
    try:
        _charge(scope)
        if client is None:
            client = _verify_client()
        lines: list[str] = []
        by_file: dict[str, list[int]] = {}
        for i, r in enumerate(candidates):
            by_file.setdefault(r.file, []).append(i)
        for name, indices in by_file.items():
            lines.append(f"## FILE {name}")
            hunk_texts = hunks.split_hunks(patches[name])
            for n, h in enumerate(hunk_texts, 1):
                lines.append(f"### Hunk {n}")
                lines.append(h)
            lines.append("### Findings on this file")
            for i in indices:
                r = candidates[i]
                lines.append(f"- FINDING id={i} [{r.rule}]: {r.label}")
            lines.append("")
        request = {
            "model": MECHANICAL_MODEL,
            "max_tokens": ATTRIBUTION_MAX_TOKENS,
            "output_config": {
                "effort": MECHANICAL_EFFORT,
                "format": {"type": "json_schema", "schema": ATTRIBUTION_SCHEMA},
            },
            "system": ATTRIBUTION_SYSTEM,
            "messages": [{"role": "user", "content": "\n".join(lines)}],
        }
        response = client.messages.create(**request)
        _report_cost(
            response, kind="attribution", scope=scope, pr=None, model=MECHANICAL_MODEL
        )
        if response.stop_reason != "end_turn":
            return 0
        text = next((b.text for b in response.content if b.type == "text"), "")
        parsed = json.loads(text)
        attributed = 0
        seen: set[int] = set()
        for row in parsed.get("attributions", []):
            i = row.get("finding")
            picks = row.get("hunks")
            if not isinstance(i, int) or i in seen or not (0 <= i < len(candidates)):
                continue
            seen.add(i)
            if not isinstance(picks, list) or not picks:
                continue  # abstained: stores nothing
            r = candidates[i]
            hashes = cov.hunks[r.file]
            if not all(isinstance(n, int) and 1 <= n <= len(hashes) for n in picks):
                continue  # out-of-range pick: the validation contract failed
            r.hunks = [hashes[n - 1] for n in picks]
            attributed += 1
        return attributed
    except Exception as e:  # noqa: BLE001 — fail soft; abstention beats a wrong row
        print(
            f"doug: attribution failed ({type(e).__name__}: {str(e)[:120]}); "
            "findings stay unattributed",
            file=sys.stderr,
        )
        return 0
