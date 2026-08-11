"""LLM diff-reader — descended from the tier the Phase-1 probes validated.

SYSTEM, SCHEMA, MODEL, EFFORT, and MAX_TOKENS remain byte-identical to
scripts/llm_probe.py as of commit 0064e6b. The probe's AUC 0.687 sentry /
0.668 grafana and its ReDef polarity result belong to its 30k diff-budget
configuration. The shipped DIFF_BUDGET is 100k under ADR-0012 and its files
are tier-ordered, so those AUC figures do not validate the larger, reordered
live read. The five frozen parameters are load-bearing evidence — changing
one is a new experiment, not a tweak.

Opt-in twice over: DOUG_READER=1 AND a resolvable Anthropic credential.
Callers fall back to the deterministic score when either is missing or a
read fails, and the fallback verdict says so in its reasons. The flag
threshold (default 30) sits at the ~75-80th percentile of clean-PR risk
scores on both probe repos — roughly the top quarter gets flagged.

Every read is charged to a caller-named scope against a monthly cap before
anything is sent (see _charge). On a deployment with a ledger that is a
real ceiling on spend; without one — local dogfooding, the open-source
path — store.record_deep_read returns True and reads are uncapped by
design.
"""

import hashlib
import os
import re
import sys
import time

from pydantic import BaseModel, Field

from . import example_pack_capture
from .example_pack import (
    CoverageV0,
    FailureV0,
    NameVersionV0,
    UsageV0,
    canonical_json_bytes,
)
from .models import Band, Reason, Verdict

MODEL = "claude-opus-5"
MAX_TOKENS = 6000
EFFORT = "medium"
# chars. Governed by ADR-0012's coverage bar, NOT by the probe — the
# probe's own DIFF_BUDGET stays at the 30,000 it measured. 100,000 is
# where code+tests coverage saturates (100%/97% over 30 first-parent
# commits) at +$0.019 mean per read; the budget is a ceiling, not a
# spend, and 63% of PRs already fit under 30,000.
DIFF_BUDGET = 100_000
DEFAULT_READER_THRESHOLD = 30  # risk_score points, 0-100
DEFAULT_READ_TIMEOUT_S = 120  # seconds, whole read incl. retries' backoff
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


_SCOPE_PREFIX = "installation:"


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


def cap_for(scope: str) -> int:
    return SENTINEL_MONTHLY_READ_CAP if scope == SENTINEL_SCOPE else INSTALLATION_MONTHLY_READ_CAP


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


def _report_cost(response, *, kind: str, scope: str, pr) -> None:
    """One stderr line per paid read: what it cost and what bought it.

    Emitted here because this is the only place `response.usage` exists —
    and before the stop_reason check below, because a read that stops at
    max_tokens is billed for every one of those tokens and then thrown
    away. Reporting cost on the success path alone would hide the most
    expensive reads there are.

    `model` rides on every line even though MODEL is a single constant
    today: the moment anyone splits it per read, a line that silently
    changed meaning is this repo's recurring defect.

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
        f"kind={kind} scope={scope} model={MODEL} "
        f"in={tokens_in if tokens_in is not None else '?'} "
        f"out={tokens_out if tokens_out is not None else '?'}",
        file=sys.stderr,
    )


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


def read_timeout() -> float:
    return float(os.environ.get("DOUG_READ_TIMEOUT_S", DEFAULT_READ_TIMEOUT_S))


def _client():
    """A client with a bounded timeout, never the SDK default.

    The SDK defaults to a 600s timeout, and both read entry points run
    synchronously on Starlette's shared request thread pool (~40 workers,
    /healthz included). At the default, one stalled upstream connection
    parks a worker for ten minutes; forty of them and the whole service
    reads as down. 120s is well above any legitimate read and turns the
    same stall into a contained ReaderError fallback instead.
    """
    import anthropic

    return anthropic.Anthropic(timeout=read_timeout())


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
# ADR-0012's coverage bar; SYSTEM, SCHEMA, MODEL, EFFORT, and MAX_TOKENS
# remain frozen to the validated probe. A partial read therefore stops
# looking like a complete one.


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
    )


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
            provider="anthropic",
            model=MODEL,
            max_output_tokens=MAX_TOKENS,
            effort=EFFORT,
            inference_parameters=INFERENCE_PARAMETERS,
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
        )
        for f in rv.findings
    ]
    return Verdict(
        score=round(rv.risk_score / 100, 2),
        band=band,
        threshold=thr / 100,
        reasons=reasons,
    )
