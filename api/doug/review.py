"""Review a repo's OPEN pull requests — the dogfood surface.

`doug-review owner/repo` pulls the open PRs, scores each through the
reader tier when it's enabled (DOUG_READER=1 + credential; see reader.py),
falls back to the deterministic scorer otherwise, and prints the routed
queue. Read-only: it never comments, labels, or blocks — posting an
opinion to a PR is a product decision, not a side effect of scoring.

Open PRs have no approval history yet, so approval-shaped deterministic
rules simply don't fire here; the reader doesn't use them at all.

    uv run doug-review grafana/grafana --limit 10
    DOUG_READER=1 uv run doug-review drewjst/doug
"""

import argparse
import base64
import functools
import sys
from dataclasses import dataclass

from pydantic import BaseModel

from . import ci_evidence, features, intent, intent_providers, reader, settle
from .backtest.harvest import resolve_token
from .models import AuthorType, Band, PRMetadata, Reason, Verdict, is_bot_author
from .scoring import score

print = functools.partial(print, flush=True)  # noqa: A001


class ReviewItem(BaseModel):
    pr: PRMetadata
    verdict: Verdict


@dataclass(frozen=True)
class IntentFailure:
    """The intent read was attempted and failed.

    Distinct from None (feature off / no docs / nothing relevant): ADR-0007
    requires a failed read to be recorded differently from "nothing found",
    or precision and operators cannot tell a broken path from a quiet repo.
    Never raises into the review — callers surface a weight-0 reason.

    `rule` is the name that reason carries, and it is a field rather than a
    constant for the same reason the risk tier has two names: a read that
    broke and a read this tenant could not afford need different responses
    from whoever is on call.
    """

    detail: str
    rule: str = "intent-unavailable"


def _html_url(p) -> str | None:
    """PR permalink, tolerant of what the field actually is.

    githubkit models absent fields as the UNSET sentinel rather than None,
    and cached payloads from earlier harvests predate the field entirely.
    Anything that is not a string is no link — api.py reconstructs one from
    the repo and number in that case.
    """
    url = getattr(p, "html_url", None)
    return url if isinstance(url, str) else None


GITHUB_MAX_PR_FILES = 3000  # GitHub's own documented list_files cap
_MAX_PAGES = GITHUB_MAX_PR_FILES // 100


def _list_all_files(gh, owner: str, repo: str, number: int) -> list:
    """Every changed file, not just the first page.

    A single per_page=100 call silently drops everything past file 100 —
    a 250-file PR reads (and scores, and reports coverage) as if it had
    100. GitHub signals the last page by returning fewer than per_page
    rows, not by a cursor; looping on that is standard REST pagination.

    Bounded at GitHub's own file cap: past that, GitHub itself would stop
    returning more, so a full page at the bound means the PR has hit
    GitHub's limit, not that this loop gave up early. Without the bound, a
    client bug or a misbehaving mock that never returns a short page spins
    forever.
    """
    files = []
    for page in range(1, _MAX_PAGES + 1):
        batch = gh.rest.pulls.list_files(
            owner=owner, repo=repo, pull_number=number, per_page=100, page=page
        ).parsed_data
        files.extend(batch)
        if len(batch) < 100:
            break
    return files


def _dropped_files(files: list) -> list[str]:
    """Files GitHub reported changed but sent no patch for — excluding
    genuine binaries, which never had reviewable content to miss.

    GitHub cannot count lines in a binary file, so a real binary comes
    back with additions == deletions == 0 alongside patch=None. A large
    text file GitHub declines to inline for size still carries the real
    line counts it computed — that file WAS reviewable and is not here,
    which is the gap this list exists to catch. Flagging binaries the
    same way would mark most ordinary PRs incomplete (a screenshot, a
    lockfile) and bury the signal that matters.
    """
    return [f.filename for f in files if not f.patch and (f.additions or f.deletions)]


def _read_tier(filename: str) -> int:
    """Lower tiers reach the model first. See ADR-0012."""
    if features._is_prose(filename):
        return 2
    if features._is_test(filename):
        return 1
    return 0


def read_order(files: list) -> list:
    """The order files reach the model, highest-value first.

    DIFF_BUDGET cuts the assembled diff linearly, so order *is* selection:
    whatever sorts last is what the reader never sees. Two keys — tier
    (code, then tests, then prose) and patch size ascending. Python's sort
    is stable, so files with equal keys keep GitHub's own order; that
    stability is the deterministic tiebreak and is pinned by test.

    Patch length is a cheap proxy for the assembled chunk length; header
    overhead can invert contrived near-ties. Smallest-patch-first usually
    maximises how many files arrive WHOLE, which is what lets the reader
    reason correctly rather than half-correctly. It also makes the largest
    file in a tier the likeliest to be cut or dropped — that file is named
    in coverage.file_cut or coverage.files_unseen and rendered on the check
    run by truncation_reason, so the cost is visible rather than silent.

    Deliberately NOT risk-ordered. features._is_sensitive and _MIGRATION_RE
    fire on zero files in the PRs that motivated this work (tenancy.py,
    keyformat.py, migrations.py all False), and inventing new path
    vocabulary to fix that is the move that already failed replication:
    hotspot_path and config_flag fire zero times across all 12,000 grafana
    PRs because both dictionaries are sentry vocabulary (THESIS.md §1a).
    """
    return sorted(files, key=lambda f: (_read_tier(f.filename), len(f.patch or "")))


# Names the ordering read_order() actually applies, so the value recorded on a
# verdict cannot drift from the behaviour that produced it. Bump this string in
# the same commit as any change to how the diff is ordered — a receipt that
# says "tiered" about a linear read is worse than one that says nothing.
READ_ORDER = "tiered"
def fetch_open_prs(gh, owner: str, repo: str, limit: int) -> list[tuple[PRMetadata, str]]:
    pulls = gh.rest.pulls.list(
        owner=owner, repo=repo, state="open", sort="created", direction="desc",
        per_page=min(limit, 100),
    ).parsed_data[:limit]
    out = []
    for p in pulls:
        files = _list_all_files(gh, owner, repo, p.number)
        meta = PRMetadata(
            number=p.number,
            title=p.title,
            author=p.user.login if p.user else "unknown",
            author_type=(
                AuthorType.AGENT
                if p.user and is_bot_author(p.user.type, p.user.login)
                else AuthorType.HUMAN
            ),
            # pulls.list omits additions/deletions; per-file stats carry them.
            additions=sum(f.additions for f in files),
            deletions=sum(f.deletions for f in files),
            files=[f.filename for f in files],
            approvals=0,
            approval_latency_s=None,
            days_since_last_human_commit=None,
            files_added=sum(1 for f in files if f.status == "added"),
            files_modified=sum(1 for f in files if f.status == "modified"),
            url=_html_url(p),
            # PullRequestSimple (what pulls.list returns) has no
            # changed_files field — additions/deletions are absent for the
            # same reason. The paginated count is the only source here,
            # and it is trustworthy precisely because pagination is now
            # complete.
            changed_files=len(files),
            files_dropped=_dropped_files(files),
        )
        diff = reader.CHUNK_SEPARATOR.join(
            reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
            for f in read_order(files)
            if f.patch
        )
        out.append((meta, diff))
    return out


def _review_state(gh, owner: str, repo: str, number: int, opened_at) -> tuple[int, float | None]:
    """Current approval count and seconds to the first approval, from the
    PR's own review history.

    A reviewer's LATEST decision is what counts — approve, then a later
    changes-requested from the same person, leaves them not-approved,
    exactly like GitHub's own PR page. COMMENTED/DISMISSED reviews carry
    no decision and are excluded from that tally. Latency is measured to
    the first approval event ever recorded, regardless of any later
    change of heart: the rubber-stamp rule it feeds is about whether a
    fast approval happened, not about the PR's current state.
    """
    reviews = gh.rest.pulls.list_reviews(
        owner=owner, repo=repo, pull_number=number, per_page=100
    ).parsed_data
    latest_decision: dict[str, str] = {}
    for r in reviews:
        if r.user is None or r.state not in ("APPROVED", "CHANGES_REQUESTED"):
            continue
        latest_decision[r.user.login] = r.state
    approvals = sum(1 for state in latest_decision.values() if state == "APPROVED")
    approval_times = sorted(
        r.submitted_at for r in reviews if r.state == "APPROVED" and r.submitted_at is not None
    )
    latency = (approval_times[0] - opened_at).total_seconds() if approval_times else None
    return approvals, latency


def fetch_pr(gh, owner: str, repo: str, number: int) -> tuple[PRMetadata, str]:
    p = gh.rest.pulls.get(owner=owner, repo=repo, pull_number=number).parsed_data
    files = _list_all_files(gh, owner, repo, number)
    try:
        approvals, approval_latency_s = _review_state(gh, owner, repo, number, p.created_at)
    except Exception as e:  # noqa: BLE001 — advisory signal, never fails the fetch
        # Files and diff are the load-bearing return value; approvals feed
        # one deterministic rule (rubber-stamp). A malformed review payload
        # — a naive timestamp mixed with an aware one, a transport error —
        # must cost that signal, not the PR fetch it rides along with.
        print(f"doug: review-state fetch skipped ({type(e).__name__}: {e})", file=sys.stderr)
        approvals, approval_latency_s = 0, None
    meta = PRMetadata(
        number=p.number,
        title=p.title,
        author=p.user.login if p.user else "unknown",
        author_type=(
            AuthorType.AGENT
            if p.user and is_bot_author(p.user.type, p.user.login)
            else AuthorType.HUMAN
        ),
        additions=sum(f.additions for f in files),
        deletions=sum(f.deletions for f in files),
        files=[f.filename for f in files],
        approvals=approvals,
        approval_latency_s=approval_latency_s,
        # No deterministic rule reads this today (scoring.py: "usually
        # unknown ... bot authorship alone is the reachable signal") — a
        # commits-list call to populate it would be speculative work
        # against a signal nothing consumes yet.
        days_since_last_human_commit=None,
        files_added=sum(1 for f in files if f.status == "added"),
        files_modified=sum(1 for f in files if f.status == "modified"),
        url=_html_url(p),
        head_sha=p.head.sha,
        # The PR object's own count — authoritative regardless of
        # pagination, unlike fetch_open_prs which has to derive it.
        changed_files=p.changed_files,
        files_dropped=_dropped_files(files),
    )
    diff = reader.CHUNK_SEPARATOR.join(
        reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
        for f in read_order(files)
        if f.patch
    )
    return meta, diff


def _is_not_found(e: BaseException) -> bool:
    response = getattr(e, "response", None)
    return getattr(response, "status_code", None) == 404


def head_file_text(
    gh, owner: str, repo: str, sha: str, path: str, *, missing_ok: bool = False
) -> str | None:
    """File body at `sha`, or None when GitHub will not give us text.

    Used only to settle resolution findings against the repo (see settle.py).
    A missing/binary/unreadable file must not invent a settlement — returning
    None keeps the finding. `missing_ok` silences the log line for a plain
    404: the CI settlement probes for ruff configuration files that mostly
    do not exist, and each miss is the expected answer, not a skipped fetch.
    """
    try:
        content = gh.rest.repos.get_content(
            owner=owner, repo=repo, path=path, ref=sha
        ).parsed_data
    except Exception as e:  # noqa: BLE001 — settlement is advisory
        if not (missing_ok and _is_not_found(e)):
            print(
                f"doug: settle fetch skipped for {path} ({type(e).__name__}: {e})",
                file=sys.stderr,
            )
        return None
    # githubkit returns a list for directories; those are not settle targets.
    if isinstance(content, list):
        return None
    raw = getattr(content, "content", None)
    encoding = getattr(content, "encoding", None)
    if not isinstance(raw, str) or encoding != "base64":
        return None
    try:
        return base64.b64decode(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


# One page of check runs. A head with more than this many is not read at
# all rather than read partially: the check that failed could be the one
# past the page, and "all green" must mean all.
_CHECK_RUNS_PAGE = 100


def head_ci_evidence(gh, owner: str, repo: str, sha: str) -> ci_evidence.CiEvidence | None:
    """Which gates ran green at `sha`, or None when that cannot be said.

    Reads `.github/workflows/*.yml` at the reviewed head and the check runs
    at that same SHA (see ci_evidence.py). Every failure to read is None —
    the settlement it feeds is advisory, and None settles nothing.
    """
    try:
        listing = gh.rest.repos.get_content(
            owner=owner, repo=repo, path=".github/workflows", ref=sha
        ).parsed_data
    except Exception as e:  # noqa: BLE001 — settlement is advisory
        if not _is_not_found(e):
            print(
                f"doug: ci evidence skipped, workflows unread ({type(e).__name__}: {e})",
                file=sys.stderr,
            )
        return None
    if not isinstance(listing, list):
        return None
    jobs: list[ci_evidence.Job] = []
    for entry in listing:
        name = getattr(entry, "name", "") or ""
        if getattr(entry, "type", "") != "file" or not name.endswith((".yml", ".yaml")):
            continue
        path = getattr(entry, "path", None) or f".github/workflows/{name}"
        text = head_file_text(gh, owner, repo, sha, path)
        if text is not None:
            jobs.extend(ci_evidence.parse_workflow(text))
    if not jobs:
        return None
    try:
        page = gh.rest.checks.list_for_ref(
            owner=owner, repo=repo, ref=sha, per_page=_CHECK_RUNS_PAGE
        ).parsed_data
    except Exception as e:  # noqa: BLE001 — settlement is advisory
        print(
            f"doug: ci evidence skipped, check runs unread ({type(e).__name__}: {e})",
            file=sys.stderr,
        )
        return None
    runs = list(getattr(page, "check_runs", None) or [])
    if (getattr(page, "total_count", 0) or 0) > len(runs):
        return None
    checks = [
        ci_evidence.CheckResult(
            name=getattr(r, "name", "") or "",
            conclusion=getattr(r, "conclusion", None),
            app=getattr(getattr(r, "app", None), "slug", None),
        )
        for r in runs
    ]
    return ci_evidence.evidence(jobs, checks)


def score_one(
    meta: PRMetadata,
    diff: str,
    *,
    scope: str,
    threshold: float | None = None,
    deep_read: bool = True,
    resolve_file: settle.ResolveFile | None = None,
    resolve_schema: settle.ResolveSchema | None = None,
    resolve_ci: settle.ResolveCI | None = None,
):
    """Tier dispatch: (tier, verdict, reader_verdict|None, coverage|None).

    Reader failures fall back loudly — the deterministic verdict says
    reader-unavailable. Reader *successes* can also be partial, and say so
    the same way: coverage rides out with the verdict rather than being
    recomputed by whoever remembers to, because forgetting is how a 44% read
    came to look exactly like a whole one. None on the deterministic tier,
    which never opens the diff.

    `scope` is who the read is charged to, and every caller must name one:
    a default here is how the next entry point silently becomes un-metered.
    A scope out of budget falls back like any other failed read rather than
    raising — a PR left silently unreviewed is the failure mode this whole
    codebase is built to avoid — but under its own rule name, because
    "top up the budget" and "page someone, the reader is broken" are not
    the same instruction.

    `threshold` is the repo's own needs-you line in 0..1 (store.repo_threshold),
    or None for the process defaults. It reaches EVERY exit below — the reader
    (as round(t*100): 0.55*100 is 55.00000000000001 and risk_score is an
    integer compared with >=) and all three deterministic fallbacks — because
    a capped read on a 0.9 repo must not quietly band at 0.62.

    `deep_read` is the repo's own reader toggle (store.repo_deep_read). It
    NARROWS ONLY: `reader.enabled()` is the service's master switch and the
    spend control, and a True here cannot turn a read on where that is off.
    False takes the deterministic tier deliberately, under its own rule name
    — see the branch below for why that is not the same exit as a service
    with no reader configured.

    `resolve_file`, when given, settles import/undefined-name findings
    against the full file at head (REVIEWING.md resolution rule). It does
    not change what the model was shown — ADR-0012's five-constant freeze
    stands.

    `resolve_schema`, when given, settles unmigrated-column/schema-dependency
    findings against the live database schema (same rule, same doc — 5/5
    disproved, see settle.py's module docstring). Independent of head_sha:
    schema is schema, not tied to a git commit, so this settles even when
    `resolve_file` is None.

    `resolve_ci`, when given with `resolve_file`, settles findings that
    predict a failure a green check at the reviewed head already rules out
    (#307, settle.py's third class). Called lazily, at most once, and only
    when a finding of that class is present.
    """
    reader_line = None if threshold is None else round(threshold * 100)
    if reader.enabled() and not deep_read:
        # A DELIBERATE opt-out, named as one. The bare fallthrough at the end
        # of this function is what "this service has no reader" looks like,
        # and the two must not be spelled the same way on the verdict: one is
        # a setting somebody chose on this repository and can undo from
        # /dashboard/settings, the other is a deployment fact they cannot see.
        # Same distinction store.repo_pr_comment_state draws between `off` and
        # `no-active-row`, for the same reason — and it matters more here,
        # because with an unset flag line this exit also moves the band from
        # DOUG_READER_THRESHOLD to DOUG_THRESHOLD.
        verdict = score(meta, threshold=threshold)
        verdict.reasons.append(
            Reason(
                rule="deep-read-off",
                label="deep read is off for this repository",
                weight=0.0,
            )
        )
        return "deterministic", verdict, None, None
    if reader.enabled():
        try:
            rv = reader.read_diff(meta, diff, scope=scope)
            dropped: list[reader.ReaderFinding] = []
            if resolve_file is not None:
                rv, dropped = settle.drop_disproved_import_findings(rv, resolve_file)
                if dropped:
                    rules = ", ".join(f"reader:{d.category_slug}" for d in dropped)
                    print(
                        f"doug: settled {len(dropped)} missing-import finding(s) "
                        f"against head file ({rules})",
                        file=sys.stderr,
                    )
            schema_dropped: list[reader.ReaderFinding] = []
            if resolve_schema is not None:
                rv, schema_dropped = settle.drop_disproved_schema_findings(
                    rv, resolve_schema
                )
                if schema_dropped:
                    rules = ", ".join(
                        f"reader:{d.category_slug}" for d in schema_dropped
                    )
                    print(
                        f"doug: settled {len(schema_dropped)} schema-dependency "
                        f"finding(s) against the live schema ({rules})",
                        file=sys.stderr,
                    )
            ci_dropped: list[reader.ReaderFinding] = []
            ci_seen: list[ci_evidence.CiEvidence | None] = []
            if resolve_ci is not None and resolve_file is not None:

                def _resolve_ci_once() -> ci_evidence.CiEvidence | None:
                    if not ci_seen:
                        ci_seen.append(resolve_ci())
                    return ci_seen[0]

                try:
                    rv, ci_dropped = settle.drop_disproved_ci_findings(
                        rv, _resolve_ci_once, resolve_file
                    )
                except Exception as e:  # noqa: BLE001 — settlement is advisory
                    # A hand-rolled parser over tenant-authored YAML and a
                    # config walk over tenant-authored TOML must never be
                    # able to fail a review (Doug's second read of #314,
                    # `reader:unhandled-exception-in-optional-path`). The
                    # read stands as the model returned it.
                    ci_dropped = []
                    print(
                        f"doug: ci settlement skipped ({type(e).__name__}: {e})",
                        file=sys.stderr,
                    )
                if ci_dropped:
                    rules = ", ".join(f"reader:{d.category_slug}" for d in ci_dropped)
                    print(
                        f"doug: settled {len(ci_dropped)} finding(s) against a green "
                        f"check at head ({rules})",
                        file=sys.stderr,
                    )
            # The installation is derived from `scope` rather than passed
            # separately, for the same reason intent.enabled_for does it: who
            # pays and who opted in must be the same party, and two arguments
            # can drift apart where one cannot.
            verify_installation = reader.installation_from_scope(scope)
            if reader.verify_enabled_for(verify_installation) and resolve_file is not None:
                # verify_scope is derived from the SAME string the risk read
                # charged, via installation_from_scope's inverse, so the two can
                # never disagree about whose review this is. The prefix differs,
                # which is what keeps this spend off the customer's published
                # `deep reads N/200` meter (design-lock, Task 5).
                rv, grounded = reader.ground_findings(
                    rv,
                    head_sha=meta.head_sha,
                    resolve_file=resolve_file,
                    scope=reader.verify_scope(verify_installation),
                )
                if grounded:
                    print(
                        f"doug: grounded {grounded} finding(s) against head",
                        file=sys.stderr,
                    )
            verdict = reader.verdict_from_reader(rv, threshold=reader_line)
            if settled := settle.settlement_notice(dropped):
                verdict.reasons.append(settled)
            if schema_settled := settle.schema_settlement_notice(schema_dropped):
                verdict.reasons.append(schema_settled)
            if ci_settled := settle.ci_settlement_notice(
                ci_dropped, ci_seen[0] if ci_seen else None
            ):
                verdict.reasons.append(ci_settled)
            cov = reader.coverage(
                diff, changed_files=meta.changed_files, files_dropped=meta.files_dropped
            )
            if notice := reader.truncation_reason(cov):
                verdict.reasons.append(notice)
            if reader.attribution_enabled():
                # One batched call per read (ADR-0015); its own scope prefix
                # keeps it off the published meter, and it fails soft — a
                # dark or failed pass costs abstentions downstream, never a
                # wrong stored mapping.
                attributed = reader.attribute_findings(
                    verdict.reasons,
                    diff,
                    cov,
                    scope=reader.attribution_scope(reader.installation_from_scope(scope)),
                )
                if attributed:
                    print(
                        f"doug: attributed {attributed} finding(s) to sent hunks",
                        file=sys.stderr,
                    )
            return "reader", verdict, rv, cov
        except reader.SpendCapExceeded as e:
            # Before ReaderError: SpendCapExceeded is a subclass of it, so a
            # broader clause first would relabel every capped read as a
            # broken one.
            verdict = score(meta, threshold=threshold)
            verdict.reasons.append(Reason(rule="reader-capped", label=str(e), weight=0.0))
            return "deterministic", verdict, None, None
        except reader.ReaderError as e:
            # The verdict row is quiet by contract; this line is the loud half
            # the alert watches. See reader.FALLBACK_LOG_TOKEN.
            print(
                f"doug: {reader.FALLBACK_LOG_TOKEN} (reader-unavailable): {e}",
                file=sys.stderr,
            )
            verdict = score(meta, threshold=threshold)
            verdict.reasons.append(
                Reason(rule="reader-unavailable", label=str(e), weight=0.0)
            )
            return "deterministic", verdict, None, None
    return "deterministic", score(meta, threshold=threshold), None, None


class IntentRead(BaseModel):
    """The intent tier's output. Separate from Verdict by design (ADR-0007).

    Carries its own `coverage` rather than trusting a caller to notice it
    matches the risk read's: read_with_decisions() truncates the identical
    diff at the identical DIFF_BUDGET, so a deviation finding built from a
    partial read is exactly as unverifiable past the cut as a risk finding
    is — it just wasn't saying so.
    """

    alignment: int
    refs: list[str]
    findings: list[reader.DeviationFinding]
    coverage: reader.Coverage


def read_intent(
    gh,
    owner: str,
    repo: str,
    meta: PRMetadata,
    diff: str,
    *,
    scope: str,
    deep_read: bool = True,
) -> IntentRead | IntentFailure | None:
    """Judge the change against the repo's binding decisions.

    None — no read happened (feature off, no docs, nothing relevant).
    IntentFailure — a read was attempted and failed (surface on the risk
    verdict; do not treat as "quietly healthy").
    IntentRead — success.

    None of these may move the risk score or band (ADR-0007).

    `scope` is the same one the risk read charged: both reads come out of
    one budget, so a PR costs two units and an operator has one number to
    reason about rather than two. It is also who this tier is switched on
    for — the flag reads the scope rather than taking the installation id
    separately, so "who pays" and "who opted in" cannot drift apart.

    `deep_read` is the repo's reader toggle, and it gates this tier too. A
    repository whose owner turned the LLM read off has turned OFF THE LLM,
    not off one of the two things Doug asks it — leaving intent running
    would keep charging that repo for a read it opted out of, and would keep
    posting deviation findings written by the model it declined. None here,
    not IntentFailure: nothing was attempted, so there is nothing to
    surface on the risk verdict (ADR-0007).
    """
    if not (
        deep_read
        and intent.enabled_for(reader.installation_from_scope(scope))
        and reader.enabled()
    ):
        return None
    try:
        docs = intent_providers.fetch(gh, owner, repo)
        chosen = [intent.truncate(d) for d in intent.select(docs, meta.title, meta.files)]
        if not chosen:
            return None
        rv = reader.read_with_decisions(meta, diff, chosen, scope=scope)
    except reader.SpendCapExceeded as e:
        # Its own rule, for the same reason score_one gives the risk read
        # one: an exhausted budget is not a broken read. Caught ahead of
        # the blanket clause below, which would otherwise swallow it.
        print(f"doug: intent read skipped ({e})", file=sys.stderr)
        return IntentFailure(detail=str(e)[:200], rule="intent-capped")
    except Exception as e:  # noqa: BLE001 — advisory path, never fails a review
        # Distinct from None: a read that fails every time must not look
        # like a repo that keeps no records (ADR-0007).
        print(f"doug: intent read skipped ({type(e).__name__}: {e})", file=sys.stderr)
        return IntentFailure(detail=f"{type(e).__name__}: {e}"[:200])
    return IntentRead(
        alignment=rv.intent_alignment,
        refs=[d.id for d in chosen],
        findings=rv.deviation_findings,
        coverage=reader.coverage(
            diff, changed_files=meta.changed_files, files_dropped=meta.files_dropped
        ),
    )


def review_repo(gh, owner: str, repo: str, limit: int) -> list[ReviewItem]:
    items = []
    for meta, diff in fetch_open_prs(gh, owner, repo, limit):
        # The CLI holds no installation — it runs on a developer's own
        # token — so its reads charge the sentinel scope, alongside the
        # other two un-tenanted callers. Dogfooding locally usually has no
        # ledger at all, in which case nothing counts anything.
        _, verdict, _, _ = score_one(meta, diff, scope=reader.SENTINEL_SCOPE)
        items.append(ReviewItem(pr=meta, verdict=verdict))
    items.sort(key=lambda i: i.verdict.score, reverse=True)
    return items


def render(items: list[ReviewItem]) -> str:
    lines = []
    flagged = [i for i in items if i.verdict.band is Band.FLAGGED]
    lines.append(
        f"{len(items)} open PRs · {len(flagged)} flagged · {len(items) - len(flagged)} cleared"
    )
    for i in items:
        mark = "▲" if i.verdict.band is Band.FLAGGED else "·"
        lines.append(f"{mark} {i.verdict.score:>4.2f}  #{i.pr.number:<6} {i.pr.title[:70]}")
        for r in i.verdict.reasons:
            lines.append(f"         - {r.rule}: {r.label[:90]}")
    return "\n".join(lines)


def main() -> int:
    from githubkit import GitHub

    parser = argparse.ArgumentParser(description="Score a repo's open PRs")
    parser.add_argument("repo", help="owner/repo")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    owner, repo = args.repo.split("/", 1)
    gh = GitHub(resolve_token(None))
    tier = "reader" if reader.enabled() else "deterministic (set DOUG_READER=1 for the reader)"
    print(f"scoring open PRs on {args.repo} · tier: {tier}")
    print(render(review_repo(gh, owner, repo, args.limit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
