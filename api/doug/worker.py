"""The job pipeline — one claimed job in, one check run out.

Everything the webhook must not do inline lives here: minting an
installation token, fetching the PR, scoring it, persisting it, posting
the check run. The handler's whole job is to make the work durable and
return 202; a delivery must never wait on a paid model read.

Failure policy differs from the CI-token review path's on purpose. There, a
down ledger must not fail somebody's CI, so save_review's exception becomes
a reason on the response and the review still "succeeds" (api.py's
late /v1/review handler, retired in Task 9). Here the durable row IS the deliverable — a job
marked done having written nothing is a green checkmark over an empty
ledger — so save_review raising propagates, failing the job, and
ingest.fail decides whether to retry. save_deviations keeps the same
swallow api.py's handler uses for it: it is a genuinely separate write
(ADR-0007), and by the time it runs here the verdict it hangs off is
already durable, so a failure there must not cost the job that already
succeeded.
"""

import os
import platform
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version

from . import app_auth, check_run, example_pack_capture, ingest, reader, review, store
from .example_pack import CaptureScopeV0, NameVersionV0, PackScopeV0
from .models import Band, Reason, Verdict

_EXAMPLE_PACK_VERIFIER_VERSIONS = (
    NameVersionV0(name="import-settlement", version="v0"),
    NameVersionV0(name="schema-settlement", version="v0"),
)


def _tool_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unavailable"


def _example_pack_scope(job: dict) -> CaptureScopeV0 | None:
    """Build only evidence-backed identity; never invent a missing base."""
    base_sha = job.get("base_sha")
    head_sha = job.get("head_sha")
    if not isinstance(base_sha, str) or not base_sha:
        return None
    if not isinstance(head_sha, str) or not head_sha:
        return None
    return CaptureScopeV0(
        run_id_prefix=(
            f"review-job:{job['id']}:claim:{job['claim_generation']}"
        ),
        review_job_id=job["id"],
        scope=PackScopeV0(
            installation_id=job["installation_id"],
            github_repository_id=job["github_repo_id"],
            repository_full_name=job["repo_full_name"],
            pull_number=job["pr_number"],
            admitted_base_sha=base_sha,
            admitted_head_sha=head_sha,
        ),
        read_order=review.READ_ORDER,
        input_policy_version=reader.INPUT_POLICY_VERSION,
        coverage_policy_version=reader.COVERAGE_POLICY_VERSION,
        verifier_versions=_EXAMPLE_PACK_VERIFIER_VERSIONS,
        tool_versions=(
            NameVersionV0(name="anthropic-sdk", version=_tool_version("anthropic")),
            NameVersionV0(name="pydantic", version=_tool_version("pydantic")),
            NameVersionV0(name="python", version=platform.python_version()),
        ),
        application_revision=os.environ.get("DOUG_APPLICATION_REVISION") or None,
        runtime_revision=(
            os.environ.get("DOUG_RUNTIME_REVISION")
            or os.environ.get("K_REVISION")
            or None
        ),
    )


def _replay_recorded(
    job: dict,
    gh,
    owner: str,
    name: str,
    existing: dict,
    *,
    discarded_paid_read: bool = False,
) -> int:
    """Post the already-durable verdict. Shared by the pre-read hit and the
    migration-005 race floor (save_review returned a peer's id)."""
    verdict = Verdict(
        score=existing["score"],
        band=Band(existing["band"]),
        threshold=existing["threshold"],
        reasons=[Reason(**r) for r in existing["reasons"]],
    )
    cov = reader.Coverage(**existing["coverage"]) if existing["coverage"] else None
    # Both reads truncate the same diff at the same DIFF_BUDGET (see
    # store.find_verdict_by_identity), so the risk read's stored
    # coverage is also what the intent read saw — reused rather than
    # invented. Without it there is nothing to hedge a replayed
    # deviation with, so the section is left out entirely rather than
    # rendered as if the read had been complete (ADR-0007's "a partial
    # read must never render as a whole one" cuts both ways here).
    intent_read = None
    if existing["intent_alignment"] is not None and cov is not None:
        intent_read = review.IntentRead(
            alignment=existing["intent_alignment"],
            refs=existing["intent_refs"],
            findings=[reader.DeviationFinding(**d) for d in existing["deviations"]],
            coverage=cov,
        )
    title, summary = check_run.render(existing["tier"], verdict, intent_read, cov)
    # complete before post: a lost claim must not emit a check run that a
    # second holder will also post via this path.
    if not ingest.complete(
        job["id"], existing["id"], claim_generation=job["claim_generation"]
    ):
        print(
            f"doug: job {job['id']} complete rejected (claim lost; skipping check run)",
            file=sys.stderr,
        )
        return existing["id"]
    # Two callers share this path and must not share wording: the pre-read
    # hit bought nothing; the race loser already paid for a read that could
    # not become the durable row. Confusing those makes spend unauditable.
    if discarded_paid_read:
        print(
            f"doug: raced {job['repo_full_name']}#{job['pr_number']}"
            f"@{job['head_sha'][:12]} (paid read discarded; peer owns identity) "
            f"tier={existing['tier']} band={existing['band']} "
            f"risk={existing['score']:.2f} verdict={existing['id']}",
            file=sys.stderr,
        )
    else:
        print(
            f"doug: replayed {job['repo_full_name']}#{job['pr_number']}"
            f"@{job['head_sha'][:12]} (already recorded, nothing bought) "
            f"tier={existing['tier']} band={existing['band']} "
            f"risk={existing['score']:.2f} verdict={existing['id']}",
            file=sys.stderr,
        )
    check_run.post(gh, owner, name, job["head_sha"], title, summary)
    return existing["id"]


def process_job(job: dict) -> int | None:
    """Run one job. Returns the verdict id — the recorded one on a replay,
    a freshly scored one otherwise — or None when the job's head SHA no
    longer matches the PR's: that job lands 'superseded', not 'done', and
    the current head is enqueued in its place.

    Each of those three outcomes prints one line to stderr, and they are
    worded so that no two of them can be mistaken for each other. Only the
    freshly scored one says "paid read", because only it bought one; the
    check run is the sole surface a review has now that Task 9 has retired
    doug-review.yml, so silence in the log must not be the only difference
    between "reviewed" and "never ran".
    """
    gh = app_auth.installation_client(job["installation_id"])
    owner, name = job["repo_full_name"].split("/", 1)

    # Idempotency read, before anything else — including the head-freshness
    # check below, not only the paid calls past it. reclaim_stalled() (or
    # ingest.fail(), if ingest.complete itself raises) can re-pend a
    # 'running' job whose save_review already landed but whose check-run
    # post or ingest.complete never ran: the worker died somewhere in
    # between. A naive retry would re-score from scratch — a second paid
    # score_one/read_intent. Migration 005's unique index stops a second
    # verdicts row; this pre-read is still the cheap path that avoids buying
    # the second read. Ordering ahead of the head-freshness check matters:
    # a job with an already-durable verdict must replay it regardless of
    # whether the PR has since moved on, or the head check below would
    # supersede this row — leaving a verdict in the ledger whose job never
    # reached 'done' and whose check run never posted, for a commit that
    # really was read.
    existing = store.find_verdict_by_identity(
        job["installation_id"], job["github_repo_id"], job["pr_number"], job["head_sha"]
    )
    if existing is not None:
        return _replay_recorded(job, gh, owner, name, existing)

    # Read the PR's current head before spending anything on it. A job can
    # sit in the queue behind a backlog, or be re-pended by a retry, long
    # enough for the branch to move — and fetch_pr would then read the NEW
    # diff while every identity column, the unique index and the check run
    # still said the old SHA. That mislabels a read rather than losing one,
    # which is worse: the verdict looks like evidence about a commit it
    # never saw. The SHA that overtook this one gets its own job.
    current_pr = gh.rest.pulls.get(
        owner=owner, repo=name, pull_number=job["pr_number"]
    ).parsed_data
    current = getattr(getattr(current_pr, "head", None), "sha", None)
    if not isinstance(current, str) or not current:
        raise RuntimeError("GitHub pull response carried no usable head.sha")
    if current != job["head_sha"]:
        current_base = getattr(getattr(current_pr, "base", None), "sha", None)
        if not isinstance(current_base, str) or not current_base:
            # Do not retire the only durable job until its replacement has a
            # complete captured identity. drain's ordinary failure path keeps
            # this claim retryable.
            raise RuntimeError(
                "GitHub pull response carried no usable base.sha for stale-head replacement"
            )
        ingest.supersede(job["id"], claim_generation=job["claim_generation"])
        ingest.enqueue(
            job["installation_id"],
            job["github_repo_id"],
            job["repo_full_name"],
            job["pr_number"],
            current,
            base_sha=current_base,
        )
        # No verdict named here, because none was reached: this job opened
        # nothing. A line that carried a tier or a score would be describing
        # a read of a commit nobody made.
        print(
            f"doug: superseded {job['repo_full_name']}#{job['pr_number']}"
            f"@{job['head_sha'][:12]} (nothing read, nothing bought) "
            f"head is now {current[:12]}, which has its own job",
            file=sys.stderr,
        )
        return None

    meta, diff = review.fetch_pr(gh, owner, name, job["pr_number"])
    # The one paid entry point that has tenancy, so it is the one that
    # charges a real tenant: both reads below come out of this
    # installation's monthly budget rather than the shared sentinel one.
    scope = reader.installation_scope(job["installation_id"])
    # Settle resolution findings against the reviewed head — not the PR tip
    # pulls.get might now show (we already refused a moved head above).
    def resolve(path: str) -> str | None:
        return review.head_file_text(gh, owner, name, job["head_sha"], path)

    pack_context = example_pack_capture.capture_scope_if_enabled(
        lambda: _example_pack_scope(job),
        run_id_prefix=(
            f"review-job:{job.get('id', 'unknown')}:"
            f"claim:{job.get('claim_generation', 'unknown')}"
        ),
        installation_id=job["installation_id"],
        github_repository_id=job["github_repo_id"],
    )
    with pack_context:
        tier, verdict, rv, cov = review.score_one(
            meta, diff, scope=scope, resolve_file=resolve, resolve_schema=store.columns_of
        )
        intent_result = review.read_intent(gh, owner, name, meta, diff, scope=scope)
    intent_read: review.IntentRead | None
    if isinstance(intent_result, review.IntentFailure):
        verdict.reasons.append(
            Reason(rule=intent_result.rule, label=intent_result.detail, weight=0.0)
        )
        intent_read = None
    else:
        intent_read = intent_result

    created: list[bool] = []
    verdict_id = store.save_review(
        job["repo_full_name"],
        job["pr_number"],
        tier,
        verdict,
        rv,
        model=reader.MODEL if tier == "reader" else None,
        prompt_hash=reader.PROMPT_HASH if tier == "reader" else None,
        diff_budget=reader.DIFF_BUDGET if tier == "reader" else None,
        read_order=review.READ_ORDER if tier == "reader" else None,
        pr_meta=meta.model_dump(mode="json"),
        coverage=cov,
        github_repo_id=job["github_repo_id"],
        installation_id=job["installation_id"],
        head_sha=job["head_sha"],
        source="app",
        created=created,
    )
    # Race floor: a peer already owns this identity. Do not hang our local
    # deviations or a locally rendered check run on their row — replay theirs.
    # `created == [False]` only — an empty list means storage was disabled
    # (save_review returned without marking), which must not look like a race.
    if created == [False]:
        peer = store.find_verdict_by_identity(
            job["installation_id"],
            job["github_repo_id"],
            job["pr_number"],
            job["head_sha"],
        ) or store.find_verdict_by_id(verdict_id)
        if peer is None:
            raise RuntimeError(
                f"save_review reported an existing identity for "
                f"{job['repo_full_name']}#{job['pr_number']}@{job['head_sha'][:12]} "
                f"(id={verdict_id}) but neither identity nor id lookup found it"
            )
        return _replay_recorded(
            job, gh, owner, name, peer, discarded_paid_read=True
        )

    if intent_read is not None:
        try:
            store.save_deviations(
                verdict_id,
                intent_read.findings,
                intent_read.refs,
                intent_read.alignment,
            )
        except Exception as e:  # noqa: BLE001 — the verdict is already saved
            verdict.reasons.append(
                Reason(rule="deviations-unrecorded", label=str(e)[:200], weight=0.0)
            )

    title, summary = check_run.render(tier, verdict, intent_read, cov)
    # The one outcome of the three that bought a model read, and the only
    # line that says "paid read" — see the replay branch above for why those
    # two must not read alike. Emitted before ingest.complete, not after:
    # the read is already paid for and the verdict already durable by this
    # point, so a lost claim (complete returns False) or a raise must not
    # erase the record of what the attempt cost. It is not a complete spend
    # ledger even so: a read that dies before save_review commits leaves
    # only drain's failure line.
    print(
        f"doug: reviewed {job['repo_full_name']}#{job['pr_number']}"
        f"@{job['head_sha'][:12]} (paid read) "
        f"tier={tier} band={verdict.band.value} "
        f"risk={verdict.score:.2f} verdict={verdict_id}",
        file=sys.stderr,
    )
    # complete before post — see the identity-replay path above. The job's
    # head SHA, never meta's: by now pulls.get may already be returning a
    # newer commit, and that commit has its own job.
    if not ingest.complete(
        job["id"], verdict_id, claim_generation=job["claim_generation"]
    ):
        print(
            f"doug: job {job['id']} complete rejected (claim lost; skipping check run)",
            file=sys.stderr,
        )
        return verdict_id
    check_run.post(gh, owner, name, job["head_sha"], title, summary)
    return verdict_id


def drain(max_jobs: int = 20) -> int:
    """Claim and run up to max_jobs. Returns how many were attempted.

    Bounded because this runs inside a request's background task: an
    unbounded drain on a busy morning would hold a Cloud Run instance for
    minutes past the response it belongs to. The next delivery kicks it
    again, and reconcile catches anything neither ever reaches.

    One job's failure must not strand the queue behind it — the whole
    queue is FIFO-ish and a poison job would otherwise block every PR
    opened after it.

    Calls ingest.reclaim_stalled() once, before the first claim — not per
    job. A worker that claims a job and then dies (a deploy, a scale-down,
    an OOM) leaves the row 'running' forever: REVIVABLE deliberately
    excludes that status, so no enqueue can ever bring it back on its own,
    and the SHA is silently never reviewed again. reclaim_stalled() is a
    no-op on a ledger-less deployment, exactly like claim(), so this needs
    no try/except around it either.

    The seen-set can end a pass early with pending work still queued, not
    only at max_jobs: a stale-head requeue enqueued mid-pass, or a revive,
    or a reclaim, can sort behind a job this pass already ran (claim()
    orders by enqueued_at), so the lap gets detected — and the pass stops —
    before every pending row has been looked at. That is fine: the row is
    exactly as durable as it was before drain ran, and the next delivery's
    kick reaches it.
    """
    reclaimed = ingest.reclaim_stalled()
    if reclaimed:
        print(f"doug: reclaimed {reclaimed} stalled job(s)", file=sys.stderr)

    attempted = 0
    seen: set[int] = set()
    while attempted < max_jobs:
        job = ingest.claim()
        if job is None:
            break
        if job["id"] in seen:
            # Lapped the queue: this exact job id already ran once this
            # pass. Four ways to land here, and hitting the set is the
            # ordinary end of a pass rather than a fault to report — though
            # two of the four do follow a failed attempt. ingest.fail
            # re-pends a job below the attempt cap, so retrying it here
            # would not be a retry (nothing has had time to change) and
            # would burn the whole attempt budget against one transient
            # fault in under a second. A force-push ping-pong revives a
            # superseded row in place. A reclaim re-pends a stalled
            # 'running' row in place. And process_job's stale-head catch-up
            # re-enqueues the PR's real head on LIVE terms, which revives a
            # row that already burned every attempt when that head is the
            # SHA it gave up on — the one way in which the id coming back
            # belongs to a row that reached 'failed'. All four keep the
            # row's original id, which is the only property the seen-set
            # depends on, so it catches every one of them with no special
            # case.
            ingest.release(job["id"], claim_generation=job["claim_generation"])
            break
        seen.add(job["id"])
        attempted += 1
        try:
            process_job(job)
        except Exception as e:  # noqa: BLE001 — ingest.fail decides retry vs give up
            print(
                f"doug: job {job['id']} failed ({type(e).__name__}: {e})",
                file=sys.stderr,
            )
            ingest.fail(job["id"], str(e), claim_generation=job["claim_generation"])
    return attempted


def _skip_reason(p) -> str | None:
    """Why this open PR must not be enqueued, or None.

    The same gate the pull_request webhook applies in api.py. Duplicated
    rather than shared on purpose: the two callers hold different objects —
    a githubkit model here, a parsed webhook payload there — and githubkit
    models an absent field as the UNSET sentinel, not None, so `if p.draft`
    is not the same test as `p.draft is True`. If the webhook's gate
    changes, this changes with it.

    "The same gate" is two properties, and they are the ones to check when
    either side moves: an unknown draft state — absent, null, not a
    boolean — is "draft" on both sides, and repo ids that are not both
    integers are "fork" on both sides rather than something to compare.
    They diverged once already, when the webhook read a missing `draft` key
    as "not a draft" and compared two absent ids as equal; the webhook was
    the newer code, so this docstring was the thing that became false.
    """
    # Only an explicit draft=False proceeds. True, the UNSET sentinel, and a
    # genuinely missing field all fall through to "skip" — the same
    # safe-direction-is-skip choice the fork check below makes for its own
    # UNSET/missing case, applied here too rather than defaulting an unknown
    # draft state to "safe to review".
    if getattr(p, "draft", True) is not False:
        return "draft"
    head_id = getattr(getattr(getattr(p, "head", None), "repo", None), "id", None)
    base_id = getattr(getattr(getattr(p, "base", None), "repo", None), "id", None)
    # A fork's raw diff enters the prompt (_user_text, reader.py:179-187),
    # so an outside contributor must not be able to drive spend. UNSET or
    # missing ids are treated as a fork: the safe direction to be wrong in
    # is "skip".
    if not isinstance(head_id, int) or not isinstance(base_id, int):
        return "fork"
    return "fork" if head_id != base_id else None


# Hard ceiling on how many open PRs reconcile will look at per repo. No
# repo Doug expects to sit behind has anywhere near this many open at once;
# hitting it is itself a signal something is wrong (a runaway bot, a
# misconfigured install), logged rather than looping unboundedly or
# truncating without a trace. Bounds the per-repo cost so one install with
# a pathological number of open PRs cannot hang reconcile_all() for every
# other tenant behind it.
_MAX_OPEN_PRS_PER_REPO = 1000


def reconcile_installation(installation_id: int, *, trigger: ingest.Trigger = "live") -> int:
    """Enqueue every reviewable open PR this installation can see.

    `trigger` is the terms a collision with a 'failed' row comes back on, and
    it is a parameter rather than a constant because repetition is a property
    of the caller: deciding it here would hand every caller the brake that
    belongs to whichever of them repeats itself. Both of today's callers ask
    for 'reconcile', and for the same reason — reconcile_all is the startup
    sweep, and api.py's _reconcile_then_drain runs on installation.created,
    which GitHub will redeliver on request or on retry. Each re-derives every
    open PR whether or not anything about it changed, which is what
    FAILED_REVIVE_COOLOFF_SECONDS is charged to.

    The 'live' default is for the caller that does not yet exist: one reacting
    to a single head change, which has one event's worth of spend behind it
    and no repetition to brake. Being a default is also what makes it safe —
    an unrecognized trigger and a forgotten argument both land on the terms
    that review too eagerly rather than the terms that might not review at
    all (ingest._revive says why that is the right direction to fail in). The
    price is that a caller which does repeat itself has to say so, out loud,
    at the call site.

    The healing path for missed deliveries. GitHub retries a *failed*
    delivery, but a delivery this service 202s and then loses to a restart
    is never retried, and the redelivery window is not a guarantee — so
    recovery does not trust webhooks at all, it re-derives the world from
    the API and lets the queue's unique index throw away what it already
    has.

    Deliberately pulls.list rather than review.fetch_open_prs: that helper
    also fetches per-PR files to build PRMetadata, which is one extra
    request per open PR for data reconcile never reads. The worker fetches
    the diff when the job actually runs.

    Paginates rather than trusting a single page: GitHub caps one page at
    100, and "every open PR" (the promise above) would quietly become "the
    newest 100" on a busy repo otherwise, silently and permanently — the
    kind of gap between a docstring's claim and what the code does that
    this codebase's reviewers now check for. _MAX_OPEN_PRS_PER_REPO is the
    one place that promise still has an edge, and it's logged when hit.

    Does not call ingest.reclaim_stalled(): that sweep is installation-
    agnostic (whole queue, by lease age, not by tenant), so calling it here
    would reclaim other tenants' stranded rows as a side effect of
    reconciling one of them — Task 6 calls this function alone, from the
    installation.created handler, and that call must not have a blast
    radius past the one installation it names. reconcile_all is where the
    stalled-claim sweep belongs; see its docstring.
    """
    gh = app_auth.installation_client(installation_id)
    count = 0
    for repo_id, full_name in store.active_repos(installation_id):
        owner, _, name = full_name.partition("/")
        pulls: list = []
        page = 1
        try:
            while True:
                batch = gh.rest.pulls.list(
                    owner=owner, repo=name, state="open", per_page=100, page=page
                ).parsed_data
                pulls.extend(batch)
                if len(batch) < 100 or len(pulls) >= _MAX_OPEN_PRS_PER_REPO:
                    break
                page += 1
        except Exception as e:  # noqa: BLE001 — one unreadable repo is not fatal
            print(
                f"doug: reconcile skipped {full_name} ({type(e).__name__}: {e})",
                file=sys.stderr,
            )
            continue
        if len(pulls) >= _MAX_OPEN_PRS_PER_REPO:
            # A full page can overshoot the cap by up to per_page - 1 (the
            # break above only checks after a whole page lands), so trim
            # back to the cap exactly — the log line below must describe
            # what actually got reconciled, not what almost did.
            pulls = pulls[:_MAX_OPEN_PRS_PER_REPO]
            print(
                f"doug: reconcile capped at {_MAX_OPEN_PRS_PER_REPO} open PRs for "
                f"{full_name}; the rest were not reconciled this pass",
                file=sys.stderr,
            )
        for p in pulls:
            reason = _skip_reason(p)
            if reason is not None:
                print(
                    f"doug: reconcile skipped {full_name}#{p.number} ({reason})",
                    file=sys.stderr,
                )
                continue
            head_sha = getattr(getattr(p, "head", None), "sha", None)
            if not isinstance(head_sha, str):
                continue
            base = getattr(p, "base", None)
            base_sha = getattr(base, "sha", None)
            if not isinstance(base_sha, str) or not base_sha:
                print(
                    f"doug: reconcile skipped {full_name}#{p.number} (missing base.sha)",
                    file=sys.stderr,
                )
                continue
            # installation_repos' full_name can go stale: a repo can be
            # deleted and its name picked up by an unrelated one. repo_id
            # (github_repo_id) is the fact the store's tenancy actually keys
            # on and the only one GitHub still guarantees, so a PR whose
            # base repo id disagrees with it belongs to a different repo
            # than the one this installation was granted — reviewing it
            # under this installation's identity would be wrong, not just
            # imprecise.
            base_id = getattr(getattr(base, "repo", None), "id", None)
            if base_id != repo_id:
                print(
                    f"doug: reconcile skipped {full_name}#{p.number} "
                    f"(base repo id {base_id} != installation_repos' {repo_id})",
                    file=sys.stderr,
                )
                continue
            # enqueue has two outcomes on a collision here, not one. A row
            # already 'pending', 'running', or 'done' at this head SHA
            # collides and returns None — the ordinary dedupe reconcile
            # exists for, since the unique index carries no status column.
            # A row that is 'failed' or 'superseded' at this SHA is instead
            # REVIVED by ingest._revive: reset to status='pending',
            # attempts=0, and its (non-None) id comes back, so it counts
            # here too. That's deliberate — a PR that burned every attempt
            # before a restart is healed rather than staying dead forever —
            # but it isn't free: a revived job pays for up to max_attempts
            # model reads again. `trigger` is what bounds the repetition, and
            # it comes from the caller: reconcile_all is the startup sweep, so
            # a 'failed' row it meets inside FAILED_REVIVE_COOLOFF_SECONDS is
            # left alone and the same broken PR costs one budget per cooloff
            # window rather than one per restart. A live caller revives it at
            # once instead.
            job_id = ingest.enqueue(
                installation_id,
                repo_id,
                full_name,
                p.number,
                head_sha,
                base_sha=base_sha,
                trigger=trigger,
            )
            if job_id is not None:
                count += 1
                continue
            # None covers both outcomes above, and only one of them is worth
            # an operator's attention: a PR this sweep is deliberately waiting
            # on looks exactly like one already reviewed. The skips above both
            # log, so this was the only way a PR could go unreviewed with
            # nothing said about it. Costs one indexed read per collision, and
            # only on the branch that already paid for a failed insert.
            held = ingest.cooloff_hold_remaining(installation_id, repo_id, p.number, head_sha)
            if held is not None:
                print(
                    f"doug: reconcile held back {full_name}#{p.number} "
                    f"(review failed; {held}s of the cooloff left)",
                    file=sys.stderr,
                )
    return count


def reconcile_all() -> int:
    """Reconcile every active installation. Returns total jobs enqueued.

    This is the startup reconcile path (Task 7's amendment). Two things it
    does that reconcile_installation deliberately does not: it calls
    ingest.reclaim_stalled() once, up front, before the per-installation
    enqueue sweep below runs for anyone; and it is the caller that claims
    trigger='reconcile', because the cooloff brakes a caller that repeats
    itself and this is the one that does — it re-derives every open PR on
    every process start, whether or not anything changed.

    A missed *delivery* is healed by re-deriving the world from the API and
    letting enqueue's unique index dedupe against it — that's
    reconcile_installation. A *crash-stranded claim* is a different failure:
    the row is still 'running', and REVIVABLE deliberately excludes that
    status (reviving it out from under a worker that might still be alive
    would pay for a second read of the same SHA), so enqueue collides with
    it and returns None — forever, on every subsequent startup — unless
    something first puts the row back to 'pending'. reclaim_stalled() is
    that something, and reconcile without it is structurally unable to fix
    the case it's named for: "a Cloud Run instance dying mid-review", which
    is the same failure class as "a deploy that wiped the App credentials"
    but the most likely instance of it, and startup is exactly the event
    that follows it.

    Reclaiming runs before the sweep below, not after and not
    per-installation, and the order is observable, not just a defensive
    nicety: enqueue's supersede-after-insert step (ingest.py) only retires
    rows that are already 'pending' at this (installation, repo, pr) with a
    different head_sha — it cannot touch a row that is still 'running'. So
    when a stranded claim's PR is force-pushed while the claim is stuck,
    reclaiming first is what lets the sweep's insert of the new head SHA
    supersede the stale one in the same pass; reclaiming after would leave
    both the stale SHA and the new one 'pending' — the stale one live work
    a worker will claim and then have to supersede itself, instead of the
    sweep having already retired it.
    test_reconcile_all_supersedes_a_stranded_claim_whose_pr_moved_on pins
    that case behaviorally. test_reconcile_all_calls_reclaim_stalled_before_the_enqueue_sweep
    pins the call order directly on top of it, for the (also real, just not
    behaviorally distinguishable on its own) case where the PR's head SHA
    never changed and the two orderings converge to the same final row
    state either way.

    reclaim_stalled() sweeps by lease age across the whole queue, not by
    tenant, which is exactly why it belongs here and not inside
    reconcile_installation: called there, it would reclaim every other
    tenant's stranded rows as a side effect of reconciling just one
    installation.
    """
    reclaimed = ingest.reclaim_stalled()
    if reclaimed:
        print(f"doug: reconcile reclaimed {reclaimed} stalled job(s)", file=sys.stderr)

    total = 0
    for installation_id in store.active_installations():
        try:
            total += reconcile_installation(installation_id, trigger="reconcile")
        except Exception as e:  # noqa: BLE001 — one bad tenant must not stop the rest
            print(
                f"doug: reconcile failed for installation {installation_id} "
                f"({type(e).__name__}: {e})",
                file=sys.stderr,
            )
    return total


# Bounded by TIME, not count: an installation's OPEN PRs are naturally
# bounded (reconcile_installation's _MAX_OPEN_PRS_PER_REPO exists only as a
# backstop against a pathological repo), but "every closed PR" grows
# without bound over a repo's lifetime. sort=updated,direction=desc lets a
# reconcile pass stop the moment a page's oldest PR falls outside the
# window, so a healthy repo costs one page, not its whole history.
_MERGE_RECONCILE_LOOKBACK = timedelta(days=14)

# Backstop for a repo that closes an implausible number of PRs inside the
# lookback window — the outcome lane's sibling of _MAX_OPEN_PRS_PER_REPO,
# logged the same way when hit.
_MAX_CLOSED_PRS_PER_REPO = 300


def _aware(dt: datetime) -> datetime:
    """githubkit's ISO-8601 timestamps come back tz-aware in every field
    checked against the installed schema (PullRequestSimple.merged_at,
    .updated_at). Normalised defensively anyway — the same guard
    api.py's _payload_timestamp applies to the webhook's own copy of the
    same fact — so a future githubkit upgrade that ever changes this
    cannot turn into a naive/aware TypeError here."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def reconcile_outcomes(installation_id: int) -> int:
    """Enqueue outcome-observation windows for every merge this
    installation's webhook may have missed.

    The outcome lane's analogue of reconcile_installation, healing the same
    failure it heals: "a delivery this service 202s and then loses to a
    restart is never retried" (reconcile_installation's own docstring).
    _record_merge (api.py) is the ONLY other path that ever writes an
    outcome_jobs row, and it runs exclusively off the pull_request/closed
    webhook — there is no drain, no claim, no revive to fall back on the
    way review_jobs has, so a lost delivery here is healed by nothing else
    in this codebase today. This re-derives recently-closed PRs from the
    API and lets enqueue_outcome_jobs's ON CONFLICT DO NOTHING
    (store.py's uq_outcome_job) throw away what it already has — the
    identical "never trust the webhook alone" principle, applied to the
    one lane that has never had it.

    No draft/fork gate: _record_merge applies neither
    (publication-preregistration.md §2.4 — "no fork gate, no draft gate,
    no verdict-existence check"), and a merged PR is never a draft, so
    mirroring reconcile_installation's _skip_reason here would silently
    exclude merges the webhook path itself would have recorded.

    pulls.list's PullRequestSimple carries no merge_commit_sha (githubkit
    v2026_03_10 does not model that field, though GitHub's own OpenAPI
    description text for pulls.get — reproduced verbatim in its own
    docstring — still names it), so each merge candidate costs a second
    call, pulls.get, read from its raw response body rather than the typed
    model. That is the one place this function is not cheap; it is still
    bounded by the same lookback window and cap as everything else here.
    """
    gh = app_auth.installation_client(installation_id)
    cutoff = datetime.now(UTC) - _MERGE_RECONCILE_LOOKBACK
    count = 0
    for repo_id, full_name in store.active_repos(installation_id):
        owner, _, name = full_name.partition("/")
        pulls: list = []
        page = 1
        exhausted = True
        try:
            while True:
                batch = gh.rest.pulls.list(
                    owner=owner, repo=name, state="closed",
                    sort="updated", direction="desc",
                    per_page=100, page=page,
                ).parsed_data
                if not batch:
                    break
                pulls.extend(batch)
                oldest = getattr(batch[-1], "updated_at", None)
                stale = isinstance(oldest, datetime) and _aware(oldest) < cutoff
                exhausted = stale or len(batch) < 100
                if exhausted or len(pulls) >= _MAX_CLOSED_PRS_PER_REPO:
                    break
                page += 1
        except Exception as e:  # noqa: BLE001 — one unreadable repo is not fatal
            print(
                f"doug: outcome reconcile skipped {full_name} ({type(e).__name__}: {e})",
                file=sys.stderr,
            )
            continue
        # Truncation only loses PRs when there are more than the cap, or when
        # pagination stopped at the cap with pages still unread. Exactly-at-cap
        # with the listing exhausted drops nothing, and claiming otherwise
        # would have an operator hunting a tail that does not exist.
        if len(pulls) > _MAX_CLOSED_PRS_PER_REPO or (
            len(pulls) == _MAX_CLOSED_PRS_PER_REPO and not exhausted
        ):
            pulls = pulls[:_MAX_CLOSED_PRS_PER_REPO]
            # Not "this pass": pagination always sorts updated_at desc, so the
            # same excluded tail sorts last on every future pass too — a repo
            # that hits this cap once never reconciles that tail on any pass.
            print(
                f"doug: outcome reconcile capped at {_MAX_CLOSED_PRS_PER_REPO} closed PRs "
                f"for {full_name}; the excluded tail is not reconciled by this or any "
                "later pass",
                file=sys.stderr,
            )
        for p in pulls:
            updated_at = getattr(p, "updated_at", None)
            if isinstance(updated_at, datetime) and _aware(updated_at) < cutoff:
                continue
            merged_at = getattr(p, "merged_at", None)
            if merged_at is None:
                continue  # closed without merging
            if not isinstance(merged_at, datetime):
                continue  # UNSET sentinel or a malformed field, not a real timestamp
            merged_at = _aware(merged_at)
            # The window is on the MERGE, not on updated_at. updated_at only
            # bounds pagination; a PR merged years ago and touched yesterday
            # (a comment, a label) sorts inside the listing window while its
            # merge sits far outside it. Enqueueing that one would hand the
            # adjudicator a row whose due_at is already long past — an
            # instant verdict on a merge Doug never reviewed, and one more
            # pre-install merge in the denominator (see api.py's note on
            # publication-preregistration.md §2.4).
            if merged_at < cutoff:
                continue
            number = getattr(p, "number", None)
            base = getattr(p, "base", None)
            base_ref = getattr(base, "ref", None)
            base_repo_id = getattr(getattr(base, "repo", None), "id", None)
            if not isinstance(number, int):
                continue
            if base_repo_id != repo_id:
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    f"(base repo id {base_repo_id} != installation_repos' {repo_id})",
                    file=sys.stderr,
                )
                continue
            if not isinstance(base_ref, str) or not base_ref:
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    "(missing base.ref)",
                    file=sys.stderr,
                )
                continue
            try:
                detail = gh.rest.pulls.get(owner=owner, repo=name, pull_number=number)
                merge_sha = detail.raw_response.json().get("merge_commit_sha")
            except Exception as e:  # noqa: BLE001 — one unreadable PR is not fatal
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    f"(pulls.get failed or its response was unreadable: "
                    f"{type(e).__name__}: {e})",
                    file=sys.stderr,
                )
                continue
            if not isinstance(merge_sha, str) or not merge_sha:
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    "(missing merge_commit_sha)",
                    file=sys.stderr,
                )
                continue
            merged_head_sha = getattr(getattr(p, "head", None), "sha", None)
            if not isinstance(merged_head_sha, str):
                merged_head_sha = None
            inserted = store.enqueue_outcome_jobs(
                installation_id, repo_id, number, merge_sha, merged_at, base_ref,
                merged_head_sha=merged_head_sha,
            )
            count += len(inserted)
    return count


def reconcile_all_outcomes() -> int:
    """The outcome lane's analogue of reconcile_all — every active
    installation, and one bad tenant must not stop the rest.

    Deliberately does NOT call ingest.reclaim_stalled(): that sweep exists
    for review_jobs' claim/lease model (a row stuck 'running' because the
    worker holding it died), and outcome_jobs has no such state to
    reclaim — enqueue_outcome_jobs's only two outcomes are 'inserted' and
    'already there' (ON CONFLICT DO NOTHING), never a claim to strand.
    """
    total = 0
    for installation_id in store.active_installations():
        try:
            total += reconcile_outcomes(installation_id)
        except Exception as e:  # noqa: BLE001 — one bad tenant must not stop the rest
            print(
                f"doug: outcome reconcile failed for installation {installation_id} "
                f"({type(e).__name__}: {e})",
                file=sys.stderr,
            )
    return total
