"""Langfuse tracing for the four paid model calls. ADR-0031.

This is a VIEWING surface, not a record. The example-pack lane
(`example_pack_capture`) is the record: it is hashed, cohort-scoped,
schema-frozen, and adjudicated. Nothing here is allowed to become evidence,
and no decision in this repository may cite a Langfuse trace — a span that a
network hiccup can drop is not a thing anyone should be able to reason from.
Where the two disagree, the pack is right.

Opt-in twice over, the same shape as the reader's own gate: DOUG_TRACING=1 AND
both Langfuse keys present. Either half missing and every function here is a
no-op that constructs nothing, imports nothing, and starts no threads.

WHAT LEAVES THE BOUNDARY, stated plainly because a public repository should
say so: with tracing on, a span carries the exact bytes the model was sent —
the system prompt and the diff slice under DIFF_BUDGET — and the exact text it
sent back. That is tenant source code, held by a third party. ADR-0031 records
the decision and names the conditions on it.

FAIL-SOFT IS ABSOLUTE. A read must never fail, slow, or change because tracing
did. The Langfuse SDK is already well behaved about this — a missing key logs
and disables the client rather than raising — but "already well behaved" is a
property of a version, not a contract, so `create` guards on top of it and
every other entry point swallows its own exceptions. The failure mode this
prevents is the one the reader's whole design is built around: a soft fallback
that reads as "the model is down" when the real cause is somewhere else
entirely. Adding a second such cause would be a poor trade for a dashboard.

THE SEAM IS THE REQUEST DICT, NOT THE CLIENT. `create` takes the request the
caller already built and passes it to the SDK unchanged; it reads `model`,
`system` and `messages` out of that same dict rather than being told them
separately. Two consequences, both deliberate:

  1. Tracing cannot become the path by which the frozen instrument moves.
     ADR-0002 and ADR-0012 freeze what reaches the wire, and a wrapper that
     built its own kwargs would be one refactor away from disagreeing with
     the caller. `test_the_request_reaches_the_sdk_unchanged` pins it.
  2. A pass that changes its model or its prompt cannot forget to update its
     tracing, because there is nothing separate to update.

Wrapping `_build_client` was the obvious alternative and is worse: a proxy
sees the exception but not `stop_reason`, not the parsed output, and not the
spend cap — and every reader test injects `client=`, so the proxy would be the
one part of this that never ran under test.
"""

import os
import sys
import time
from contextlib import contextmanager

# Which env var turns this on. A separate switch from DOUG_READER on purpose:
# turning the reader off must not depend on remembering to turn tracing off
# too, and turning tracing off during an incident must not touch the reader.
TRACING_ENV = "DOUG_TRACING"
PUBLIC_KEY_ENV = "LANGFUSE_PUBLIC_KEY"
SECRET_KEY_ENV = "LANGFUSE_SECRET_KEY"

# Both keys, never either-or. A half-configured client is one that constructs
# and then fails on every export, which spends a thread and a retry budget to
# produce nothing — and does it quietly, because export failures are logged at
# a level nobody reads. Missing one key means the environment was not
# configured for tracing, and "off" is the honest reading of that.
_REQUIRED_KEYS = (PUBLIC_KEY_ENV, SECRET_KEY_ENV)

# Set once, on first use, and never reset. `False` is the sentinel for "we
# tried to construct one and could not" — distinct from `None`, which means
# "not tried yet" — so a broken configuration costs one construction attempt
# per process rather than one per read.
_CLIENT: object | None = None


def enabled() -> bool:
    """Is tracing on for this process?

    Read from the environment on every call rather than cached at import,
    matching `reader.enabled()` and `reader.transport()`. The reason is the
    same one ADR-0028 item 6 gave for the transport: an operator who needs
    tracing off — because it is noisy, because a key leaked, because the
    vendor is having an outage — should get that from an env change on the
    running service, not from a deploy.
    """
    if os.environ.get(TRACING_ENV) != "1":
        return False
    return all(os.environ.get(name) for name in _REQUIRED_KEYS)


def _client():
    """The memoized Langfuse client, or None if tracing is off or broken.

    Imported inside the function, like `anthropic` in `reader._build_client`
    and `google.oauth2` in `reader._google_identity_token`, so that nothing
    about a local checkout, a test run, or an image that never traces depends
    on the OpenTelemetry stack being importable at module load.

    Construction installs a global OTel tracer provider as a side effect. That
    is tolerable here because nothing else in this codebase uses OpenTelemetry,
    and it is the reason this is lazy rather than module-level: an image with
    DOUG_TRACING unset should never reach this code at all.
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT or None
    try:
        from langfuse import Langfuse

        _CLIENT = Langfuse()
    except Exception as exc:  # noqa: BLE001 - tracing may not break a read
        _diagnostic(f"client construction failed: {type(exc).__name__}")
        _CLIENT = False
        return None
    return _CLIENT


def _diagnostic(message: str) -> None:
    """One stderr line, the same channel `_report_cost` and capture use.

    Tracing failures are reported and then dropped. They are not raised, not
    retried, and not counted — a dashboard that is down is not an incident,
    and treating it like one is how a viewing surface acquires the power to
    stop a review.
    """
    print(f"doug: tracing {message}", file=sys.stderr)


def _system_text(request: dict) -> str:
    """The system prompt as a string, whatever shape the request used.

    All four passes send a plain string today. Blocks are accepted anyway
    because the SDK accepts them, and a caller that switches to a cached
    block list should get a readable trace rather than `[{'type': 'text'...`.
    """
    system = request.get("system")
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n".join(
            block.get("text", "") for block in system if isinstance(block, dict)
        )
    return ""


def _messages_input(request: dict) -> list:
    """The messages array, as-is. The diff slice lives in here."""
    messages = request.get("messages")
    return messages if isinstance(messages, list) else []


def _response_text(response) -> str:
    """The model's text, selected exactly the way all four callers select it.

    Kept identical to the `next((b.text for b in response.content ...))` line
    each caller runs, so the trace shows the string the code actually parsed
    rather than a second, differently-assembled one. A trace that disagrees
    with the code about what came back is worse than no trace.
    """
    content = getattr(response, "content", None) or []
    return next((b.text for b in content if getattr(b, "type", None) == "text"), "")


def _usage_details(response) -> dict | None:
    """Token counts for cost attribution, or None when there are none.

    None rather than `{}` or a zeroed pair, for the reason `_report_cost`
    prints `?` rather than `0`: a read of unknown cost summed in as a free one
    understates the bill, and this is the surface someone will size a budget
    from. `_safe_update` drops None fields, so an unknown count leaves the
    span saying nothing about tokens instead of claiming there were none.
    """
    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "input_tokens", None)
    tokens_out = getattr(usage, "output_tokens", None)
    details = {}
    if isinstance(tokens_in, int):
        details["input"] = tokens_in
    if isinstance(tokens_out, int):
        details["output"] = tokens_out
    return details or None


def create(client, request: dict, *, kind: str, scope: str, pr=None):
    """Run one paid model call, traced. Returns exactly what the SDK returns.

    `request` is forwarded unchanged — this function reads it and never writes
    to it, and the kwargs the SDK receives are the caller's own dict. See the
    module docstring for why that is the whole point.

    Exceptions from the SDK propagate untouched, so each caller's existing
    ReaderError contract is unaffected; the span is closed and marked ERROR on
    the way past. Exceptions from Langfuse are swallowed, which is the
    asymmetry the fail-soft rule requires.

    A response that stopped for any reason other than `end_turn` is marked
    WARNING rather than left looking clean. Every caller treats that as a
    failed read, and it is billed for every token it produced, so a trace that
    showed it as an ordinary success would hide the most expensive reads there
    are — the same defect `_report_cost`'s ordering exists to avoid.
    """
    lf = _client() if enabled() else None
    if lf is None:
        return client.messages.create(**request)

    output_config = request.get("output_config") or {}
    model_parameters = {
        "max_tokens": request.get("max_tokens"),
        "effort": output_config.get("effort"),
    }
    metadata = {
        "doug.kind": kind,
        "doug.scope": scope,
        "doug.pr_number": getattr(pr, "number", None),
        "doug.head_sha": getattr(pr, "head_sha", None),
    }
    started = time.monotonic()
    span, generation = _open(
        lf,
        what=f"span kind={kind}",
        name=f"reader.{kind}",
        as_type="generation",
        model=request.get("model"),
        model_parameters=model_parameters,
        metadata=metadata,
        input={
            "system": _system_text(request),
            "messages": _messages_input(request),
        },
    )
    if span is None:
        return client.messages.create(**request)

    try:
        response = client.messages.create(**request)
    except BaseException as exc:
        _safe_update(
            generation,
            level="ERROR",
            status_message=f"{type(exc).__name__}: {exc}"[:400],
            metadata={**metadata, "doug.latency_s": _elapsed(started)},
        )
        _close(span, exc)
        raise
    stop_reason = getattr(response, "stop_reason", None)
    _safe_update(
        generation,
        output=_response_text(response),
        usage_details=_usage_details(response),
        level=None if stop_reason == "end_turn" else "WARNING",
        status_message=(
            None if stop_reason == "end_turn" else f"stopped with {stop_reason}"
        ),
        metadata={
            **metadata,
            "doug.stop_reason": stop_reason,
            "doug.latency_s": _elapsed(started),
        },
    )
    _close(span, None)
    return response


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 3)


def _open(lf, *, what: str, **fields):
    """Start a span and enter it, or return (None, None). Never raises.

    Split into an explicit open/close pair rather than written as a `with`
    because BOTH halves can fail independently — `start_as_current_observation`
    builds the span, and entering it is what pushes the OpenTelemetry context —
    and a `with` statement gives no way to tolerate a failure in the second
    half without also swallowing whatever the body raised. Swallowing the body
    is the one thing this module must never do.
    """
    try:
        span = lf.start_as_current_observation(**fields)
        return span, span.__enter__()
    except Exception as exc:  # noqa: BLE001 - tracing may not break a read
        _diagnostic(f"{what} start failed error={type(exc).__name__}")
        return None, None


def _close(span, exc: BaseException | None) -> None:
    """End a span, reporting `exc` to it if the body raised. Never raises."""
    try:
        span.__exit__(type(exc) if exc else None, exc, exc.__traceback__ if exc else None)
    except Exception as inner:  # noqa: BLE001 - tracing may not break a read
        _diagnostic(f"span close failed error={type(inner).__name__}")


def _safe_update(generation, **fields) -> None:
    """Write to a span, or print one line and carry on."""
    if generation is None:
        return
    try:
        generation.update(**{k: v for k, v in fields.items() if v is not None})
    except Exception as exc:  # noqa: BLE001 - tracing may not break a read
        _diagnostic(f"span update failed error={type(exc).__name__}")


@contextmanager
def job(*, job_id, installation_id, repo_full_name: str, pr_number, head_sha: str):
    """The trace root for one review job. Yields nothing; use it as a scope.

    Without this, every model call is its own trace and a review that ran a
    risk read, an intent read and three verify calls arrives as five unrelated
    rows. With it they nest under one span named for the PR, which is the
    question anyone actually asks of this data: what did Doug do on this PR.

    `session_id` is the head SHA rather than the PR number, so re-pushing to a
    PR opens a new session rather than appending to the old one. A second push
    is a second review of different bytes, and grouping the two would make
    "what did the reader see" unanswerable for either.

    Yields on every path, including a Langfuse failure, and yields exactly
    once. A `with` block that can decline to run its body is a `with` block
    that can skip a review — the job would be marked attempted, land 'done',
    and never be read, with nothing anywhere saying so.

    The two scopes are entered independently because they fail independently:
    losing `propagate_attributes` costs the session grouping and nothing else,
    so a review still traces rather than not tracing at all.
    """
    lf = _client() if enabled() else None
    if lf is None:
        yield
        return

    span, _ = _open(
        lf,
        what="job span",
        name=f"review {repo_full_name}#{pr_number}",
        as_type="span",
        input={
            "repo": repo_full_name,
            "pr_number": pr_number,
            "head_sha": head_sha,
        },
        metadata={
            "doug.job_id": job_id,
            "doug.installation_id": installation_id,
        },
    )
    attributes = _open_attributes(
        session_id=str(head_sha), tags=[f"repo:{repo_full_name}"]
    )
    try:
        yield
    except BaseException as exc:
        # The body raised. Both scopes close on the way past and the exception
        # goes on to worker.drain, which is what decides retry versus give up.
        # Nothing is caught here.
        _close_if_open(attributes, exc)
        _close_if_open(span, exc)
        raise
    _close_if_open(attributes, None)
    _close_if_open(span, None)


def _open_attributes(**attrs):
    """Enter propagate_attributes, or return None. Never raises."""
    try:
        from langfuse import propagate_attributes

        scope = propagate_attributes(**attrs)
        scope.__enter__()
        return scope
    except Exception as exc:  # noqa: BLE001 - tracing may not break a review
        _diagnostic(f"trace attributes failed error={type(exc).__name__}")
        return None


def _close_if_open(scope, exc: BaseException | None) -> None:
    if scope is not None:
        _close(scope, exc)


def flush() -> None:
    """Ship whatever is queued. Called at a batch boundary, never per read.

    Langfuse exports on a background thread and on a timer, neither of which
    is reliable on Cloud Run: after a request's background task finishes, the
    instance's CPU is throttled and a queued batch can sit unsent until the
    next request happens to wake it. `worker.drain` ends by calling this, so a
    drain's spans leave while there is still CPU to send them with.

    NOT called on the synchronous read route. That request already spends its
    whole Cloud Run --timeout 300 budget on a 240s read bound plus backoff,
    and a blocking flush is exactly the kind of tail latency that turns the
    reader-unavailable fallback into a platform 504.

    It blocks, and against an unreachable Langfuse it blocks for a while:
    measured at about 4s for a single span and 10s for a job's worth, bounded
    by the OpenTelemetry exporter's own retry budget and NOT by the client
    `timeout` — 2 and 5 produced the same figure. That is the price of this
    being once per drain rather than once per read, and it is paid on a
    background task after the response has already gone out.
    """
    lf = _client() if enabled() else None
    if lf is None:
        return
    try:
        lf.flush()
    except Exception as exc:  # noqa: BLE001 - tracing may not break a drain
        _diagnostic(f"flush failed error={type(exc).__name__}")


def _reset_for_tests() -> None:
    """Drop the memoized client. Tests only, and named so that is obvious."""
    global _CLIENT
    _CLIENT = None
