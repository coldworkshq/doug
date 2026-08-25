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

from . import (
    app_auth,
    check_run,
    example_pack_capture,
    ingest,
    pr_comment,
    reader,
    review,
    store,
)
from .example_pack import CaptureScopeV0, NameVersionV0, PackScopeV0
from .models import Band, Reason, Verdict, is_bot_author

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


def _pr_comment_outcome(
    gh, owner: str, name: str, job: dict, summary: str, *, fresh: bool
) -> str:
    """Decide and perform this job's sticky-comment write, returning the
    outcome token for the log line. May raise; `_post_pr_comment` owns that.

    The refusal token NAMES its cause (#173). One word for every refusal made
    "why is this repo silent?" unanswerable from the logs, and removing the
    install allowlist made that worse rather than better: it deleted the
    loudest cause and left the three that actually need investigating still
    sharing a token.

    ONE gate: the repository's own `pr_comment` column, the toggle a tenant
    can actually see and set beside the flag line on the dashboard. The
    interim install allowlist (D3a) was removed with issue #144, so there is
    no longer a second, invisible switch that can hold a repo dark while its
    visible one reads "on" — which is exactly the state D8 exists to refuse,
    and the state that made "why is this repo silent?" unanswerable from the
    dashboard. `store.repo_pr_comment` is False for an absent or 'removed'
    row on purpose (see its docstring): that is exactly the set of repos a
    tenant cannot see or toggle on the dashboard, and a repo nobody can see
    must not get a comment nobody can turn off.
    """
    inst, repo_id, pr = job["installation_id"], job["github_repo_id"], job["pr_number"]
    state = store.repo_pr_comment_state(inst, repo_id)
    if state != store.PR_COMMENT_ON:
        # `skipped:off` is a tenant's wish; `skipped:no-active-row` is a
        # reconciliation fault; `skipped:no-ledger` is a deployment fault.
        # Only the first is a state anyone should be content to see.
        return f"skipped:{state}"
    # Replay only. process_job's fresh path has already fetched this PR and
    # checked BOTH halves of the target — the head sha (it supersedes when
    # they disagree) and `base.repo.id` against this job's github_repo_id (it
    # retires the job when they disagree) — so the target is verified by the
    # time it posts; spending a second pulls.get there would buy nothing.
    # Head equality alone would not have been enough: it verifies the commit,
    # while the call itself is addressed by repo_full_name, which is
    # display-only and stale after a rename. _replay_recorded runs BEFORE both
    # checks, so on that path the PR number alone could address another repo's
    # conversation.
    if not fresh and not pr_comment.target_matches(gh, owner, name, pr, repo_id):
        return "skipped-target"
    body = pr_comment.render(
        summary,
        head_sha=job["head_sha"],
        seq=job["id"],
        links=pr_comment.receipt_links(owner, name, pr),
    )
    outcome = pr_comment.upsert(
        gh,
        owner,
        name,
        pr,
        body,
        installation_id=inst,
        github_repo_id=repo_id,
        seq=job["id"],
    )
    # Exact tokens only. `upsert` returns seven, and the four that are
    # neither a 403 nor a landed write (`skipped-stale`, `failed:<code>`,
    # `failed:net`, `failed:page-bound`) are evidence of neither permission
    # lost nor permission regained, so they must leave the marker alone —
    # clearing it on a 500 would hide a live denial behind a transient fault.
    if outcome == "denied:403":
        store.mark_pr_comment_denied(inst, datetime.now(UTC))
    elif outcome in ("created", "updated"):
        store.mark_pr_comment_denied(inst, None)
    return outcome


def _post_pr_comment(
    gh, owner: str, name: str, job: dict, summary: str, *, fresh: bool
) -> None:
    """The sticky PR comment mirroring the check run (spec 2026-08-19).

    Posted from both review paths, immediately after `check_run.post` and
    therefore only after `ingest.complete` returned True — a lost claim must
    not write a comment the second holder's replay will write too, which on
    this surface means notifying every reviewer on the PR twice for one
    review. `retry_unposted_comments` is the third caller, repairing the
    consequence of that same ordering: by the time this runs the job is
    already 'done', which no enqueue can revive, so `ingest.complete`'s
    `owed` marker and the outcome written here are the only things that can
    bring a lost comment back without waiting for a new head SHA (issue
    #154). Recording is therefore not bookkeeping — it is how the marker gets
    cleared, and a path out of here that skips it is a comment the sweep will
    write a second time.

    Its own stderr line, rather than fields appended to the reviewed/replayed
    lines: those are printed BEFORE `ingest.complete` on purpose (so a lost
    claim cannot erase the record of what the attempt cost) and cannot carry
    an outcome that has not happened yet.

    Everything is caught. `check_run.post`'s contract applies with more force
    here: by this point the read is paid for, the verdict durable and the job
    marked done, and this surface is advisory — a raise would hand the job to
    `ingest.fail`, re-pending a row whose work is finished. `upsert` is
    deliberately narrow about what it swallows (its own docstring: a blanket
    except there would report its own bugs as `failed` on 100% of PRs), and
    `target_matches` reads githubkit's model shape with plain attribute
    access, so a schema change raises AttributeError rather than returning
    False. The line drawn is loudness, not scope: a caught error prints its
    exception type and message, so a bug here is visible on the first PR
    rather than after a month of comment-less reviews, and the outcome token
    on the line below says `failed:internal` rather than reading as a skip.
    """
    outcome = "failed:internal"
    try:
        outcome = _pr_comment_outcome(gh, owner, name, job, summary, fresh=fresh)
    except Exception as e:  # noqa: BLE001 — advisory surface; the verdict is durable
        print(
            f"doug: comment internal error on job {job['id']} "
            f"({type(e).__name__}: {e})",
            file=sys.stderr,
        )
    finally:
        _record_and_log(job, outcome)


def _record_and_log(job: dict, outcome: str) -> None:
    """Clear the `owed` marker with what actually happened, then say so.

    Reached from `_post_pr_comment`'s `finally`, which is the enforcement
    rather than a formality. Correctness here rests on EVERY path out of that
    function recording something — the marker `ingest.complete` stamped is
    cleared by this call and by nothing else, so a path that returns without
    it leaves a job that commented looking like one that never did, and the
    sweep writes the comment a second time. Held as a convention, the next
    early return added inside that try (a feature-flag short circuit, a new
    guard clause) breaks it silently. Held in a `finally`, it cannot.

    Records BEFORE it logs. The ordering used to be the other way round, to
    keep the log line ahead of a write that could fail during a database
    outage; it bought nothing, because the write below swallows and logs its
    own failure, and it cost the sweep a real budget — a raise from the
    f-string between them, an unrenderable job field, spent a retry and left
    the marker standing with nothing recorded.

    The write has its own try for the same reason `_post_pr_comment` has one:
    the verdict is durable and the job is already marked done, so nothing in
    this file may hand it back to `ingest.fail`. A record that fails leaves
    `owed` in place and the sweep re-posts a comment that may already be
    live — an in-place edit of the same body, which GitHub does not notify
    on. That is the cheap side of this trade to be wrong on.
    """
    try:
        store.record_pr_comment_outcome(job["id"], outcome)
    except Exception as e:  # noqa: BLE001 — the comment is written; the job is done
        print(
            f"doug: comment outcome not recorded for job {job['id']} "
            f"({type(e).__name__}: {e})",
            file=sys.stderr,
        )
    print(
        f"doug: comment {outcome} {job['repo_full_name']}"
        f"#{job['pr_number']}@{job['head_sha'][:12]}",
        file=sys.stderr,
    )


def _render_recorded(job: dict, existing: dict) -> tuple[str, str]:
    """Rebuild one durable verdict's check-run title and summary.

    Shared by `_replay_recorded` and `retry_unposted_comments`, which need
    the same two strings for different halves of the same delivery — the
    replay posts both surfaces, the comment retry re-posts only the one that
    did not land. Sharing the reconstruction is what keeps ADR-0014's central
    claim true on the repair path too: the comment's middle is the check
    run's summary byte for byte, so a retry that rendered its own would mean
    a PR whose comment and check run disagree about the same verdict.
    """
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
    return check_run.render(
        existing["tier"], verdict, intent_read, cov, instrument=_instrument(job),
        convergence=(
            store.convergence_for(existing["id"]) if existing["tier"] == "reader" else None
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
    title, summary = _render_recorded(job, existing)
    # complete before post: a lost claim must not emit a check run that a
    # second holder will also post via this path.
    if not ingest.complete(
        job["id"],
        existing["id"],
        claim_generation=job["claim_generation"],
        owes_comment=True,
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
    _post_pr_comment(gh, owner, name, job, summary, fresh=False)
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

    # ...and check it is the right REPO, not just the right commit. This call
    # is addressed by `repo_full_name`, which is display-only and goes stale
    # on a rename (there is no `repository` webhook handler), so a rename plus
    # a reuse of the old name inside one installation points this PR number at
    # another repo — and a supersede-then-requeue chain can reach head
    # equality against it. Reading on would put this repo's findings and
    # receipt link on that repo's PR, the same misdirection
    # `pr_comment.target_matches` closes on the replay path. Retired rather
    # than requeued: this job has no way to name the repo it meant, and
    # 'superseded' is revivable, so the next webhook (which carries a current
    # name) re-queues it.
    base_repo = getattr(getattr(current_pr, "base", None), "repo", None)
    base_repo_id = getattr(base_repo, "id", None)
    if not isinstance(base_repo_id, int) or isinstance(base_repo_id, bool):
        # Unreadable is not mismatched. Retiring below is right when the
        # response NAMES another repo — the next webhook carries a current
        # name and re-queues the row — but an id we cannot read names
        # nothing, so treating it as a mismatch would spend the only durable
        # job on a response we failed to parse. Same posture as the missing
        # base.sha guard below: drain's ordinary failure path keeps this
        # claim retryable.
        raise RuntimeError("GitHub pull response carried no usable base.repo.id")
    if base_repo_id != job["github_repo_id"]:
        ingest.supersede(job["id"], claim_generation=job["claim_generation"])
        print(
            f"doug: retired {job['repo_full_name']}#{job['pr_number']}"
            f"@{job['head_sha'][:12]} (nothing read, nothing bought) "
            f"base repo is {base_repo_id!r}, not this job's "
            f"{job['github_repo_id']} — the name is stale",
            file=sys.stderr,
        )
        return None
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
    # The repo's own needs-you line, read INSIDE the job at scoring time (not
    # at admission) so the line in effect when Doug scores is the one stamped.
    threshold = store.repo_threshold(job["installation_id"], job["github_repo_id"])
    # Read in the same breath and at the same moment as the line, because the
    # two settings are read together and can move together: turning the deep
    # read off on a repo with no line of its own also moves the band from
    # DOUG_READER_THRESHOLD to DOUG_THRESHOLD.
    deep_read = store.repo_deep_read(job["installation_id"], job["github_repo_id"])
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
            meta,
            diff,
            scope=scope,
            threshold=threshold,
            deep_read=deep_read,
            resolve_file=resolve,
            resolve_schema=store.columns_of,
        )
        intent_result = review.read_intent(
            gh, owner, name, meta, diff, scope=scope, deep_read=deep_read
        )
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

    title, summary = check_run.render(
        tier, verdict, intent_read, cov, instrument=_instrument(job),
        convergence=(
            store.convergence_for(verdict_id)
            if tier == "reader" and verdict_id is not None
            else None
        ),
    )
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
        f"risk={verdict.score:.2f} line={verdict.threshold:.2f} "
        f"line_source={'repo' if threshold is not None else 'default'} "
        f"verdict={verdict_id}",
        file=sys.stderr,
    )
    # complete before post — see the identity-replay path above. The job's
    # head SHA, never meta's: by now pulls.get may already be returning a
    # newer commit, and that commit has its own job.
    if not ingest.complete(
        job["id"],
        verdict_id,
        claim_generation=job["claim_generation"],
        # Only when there is a durable verdict to replay from. The marker
        # promises a repair, and a repair renders its body through
        # `_render_recorded`, which needs the verdict row — so stamping a
        # completion that has none promises something no sweep can keep, and
        # spends a pass writing `skipped:no-verdict` to say so. `complete`
        # accepts a None verdict_id ("a skipped PR is finished, not failed"),
        # so this is the honest reading of that contract rather than a
        # defence against a path that exists today.
        owes_comment=verdict_id is not None,
    ):
        print(
            f"doug: job {job['id']} complete rejected (claim lost; skipping check run)",
            file=sys.stderr,
        )
        return verdict_id
    check_run.post(gh, owner, name, job["head_sha"], title, summary)
    _post_pr_comment(gh, owner, name, job, summary, fresh=True)
    return verdict_id


# The sticky comment's retry policy. Here rather than in store because store
# owns the selection and this owns what "worth retrying" means — the same
# split `ingest.MAX_ATTEMPTS` keeps for the review lane.
#
# Two repairs on top of the write `process_job` already made: a comment
# failing for a reason no retry fixes must stop costing GitHub calls.
# Fifteen minutes settled, because the gap between `ingest.complete` and the
# outcome write belongs to a worker that may still be alive inside it, and
# two drainers are the deployed configuration — sweeping a row still in that
# gap is how one review notifies a PR twice. The number is deliberately
# `ingest.STALL_LEASE_SECONDS`'s: this codebase has already decided how long
# a worker may be silent before it is presumed dead, and answering that
# question twice with two numbers would mean one of them is wrong. Copied
# rather than imported, because the lease is tuned for a claim holding a paid
# read and must be free to move without silently retuning this. Twenty-four
# hours of lookback,
# because a comment is worth repairing while the PR is still what people are
# looking at, and because an unbounded window turns every cold start into a
# walk of the ledger's whole history.
#
# The settle period NARROWS the window in which a first worker is still
# writing; it does not close it. Time is a heuristic for liveness, not a
# fence — a long GitHub backoff or a paused container can outlast it — and
# what remains past it is `pr_comment.upsert`'s own priced trade: a listing
# that cannot yet see a create falls through to create, because the
# alternative is a comment that never appears at all. ADR-0014 records that
# residual. A real fence would have to be held by the original writer, and
# the only one available is `claim_pr_comment`, whose loser is specified to
# create rather than skip for exactly that reason.
PR_COMMENT_MAX_RETRIES = 2
PR_COMMENT_SETTLED_SECONDS = 900
PR_COMMENT_RETRY_WINDOW_SECONDS = 86_400
PR_COMMENT_RETRY_BATCH = 20


def retry_unposted_comments(limit: int = PR_COMMENT_RETRY_BATCH) -> int:
    """Re-post sticky comments that never landed. Returns how many were tried.

    The hole this closes: `_post_pr_comment` runs after `ingest.complete` has
    marked the job 'done', `REVIVABLE` is ('failed', 'superseded'), and the
    unique index means the next delivery for that SHA collides rather than
    re-queueing. So a comment lost to a process death, a 5xx or a dropped
    connection stayed lost until somebody pushed a new commit — and since
    ADR-0014 the comment is the surface GitHub actually shows (a neutral
    check run stays folded), so that was a lost review, not a missing badge.

    What it selects on is a POSITIVE marker — `ingest.complete`'s `owed`,
    still standing where an outcome should be — and not the absence of one. A
    row with no outcome at all came from a revision that did not stamp the
    marker; nothing knows whether it commented, and a repair that guesses is
    a duplicate on a live PR.

    It repairs the comment ALONE rather than re-pending the job, and that is
    the whole reason this function exists instead of a status flip. Re-pending
    would reach the comment through `_replay_recorded`, which also calls
    `check_run.post` — and that is `checks.create`, so every repair of an
    advisory surface would leave a second check run on the commit. Damaging
    the surface that worked to heal the one that did not is not a repair.

    Nothing here is paid: `find_verdict_by_id` reads the durable row this job
    already completed against, and `_render_recorded` rebuilds the same
    strings the original post used. The GitHub cost is `target_matches`' one
    `pulls.get` plus the write, which is what the replay path already spends.

    `fresh=False` is not a formality. The retry runs long after
    `process_job` verified this job's target, on a `repo_full_name` that is
    display-only and stale after a rename, so it re-verifies before writing —
    exactly the case `pr_comment.target_matches` exists for.

    Selecting a row is not owning it. The read is unlocked and both deployed
    instances sweep the same candidates on the same pass, so every repair
    goes through `store.claim_pr_comment_retry` first — which spends the
    attempt in the statement that wins it, before any GitHub call.

    Best-effort per job, and every path out of one records or claims: a
    repair that neither wins a claim nor writes an outcome would be re-swept
    on the next drain, and on every drain after it until the window closed.
    Whole-job try, including the post: `_post_pr_comment` swallows everything
    today, but a sweep that lets one job's raise skip the rest of the batch
    would make the repair's reach depend on a contract held elsewhere. The
    recovery is fenced on whether that call was entered, for the mirror image
    of the same reason — once it owns the outcome, a raise from anywhere past
    that point must not overwrite what it recorded with `failed:internal`,
    which is retriable and would schedule another write for a comment that
    already landed.

    Rows here are whole `review_jobs` rows. That is a superset of what
    `_post_pr_comment`, `_render_recorded` and `_instrument` read between
    them — the identity columns, the head SHA and the job id — and it is
    deliberately NOT routed through `_replay_recorded`, the one helper that
    needs a value `ingest.claim` derives rather than selects
    (`claim_generation`, which only fences `ingest.complete`, and this sweep
    completes nothing).
    """
    jobs = store.jobs_with_unposted_pr_comment(
        max_retries=PR_COMMENT_MAX_RETRIES,
        settled_for_seconds=PR_COMMENT_SETTLED_SECONDS,
        within_seconds=PR_COMMENT_RETRY_WINDOW_SECONDS,
        limit=limit,
    )
    attempted = 0
    for job in jobs:
        where = f"{job['repo_full_name']}#{job['pr_number']}@{job['head_sha'][:12]}"
        # `_post_pr_comment` records before it logs, so entering it is the
        # point past which the outcome is owned. See the recovery below.
        posting = False
        try:
            existing = (
                store.find_verdict_by_id(job["verdict_id"])
                if job["verdict_id"] is not None
                else None
            )
            if existing is None:
                # A 'done' row always carries the id ingest.complete wrote,
                # so this is a verdict that went away underneath it. Terminal
                # rather than `failed:*`: there is nothing for a later pass to
                # find, and a retry that cannot converge is noise. Recorded
                # without claiming — nothing is written to GitHub, so there is
                # no write for a second sweeper to duplicate, and whichever of
                # them records it first records the same thing.
                print(f"doug: comment skipped:no-verdict {where}", file=sys.stderr)
                store.record_pr_comment_outcome(job["id"], "skipped:no-verdict")
                continue
            if not store.claim_pr_comment_retry(
                job["id"], attempts=job["pr_comment_attempts"]
            ):
                # The other instance owns this repair, or the original worker
                # landed its outcome between the select and here. Ordinary,
                # not a fault: silent, the way ingest.claim's lost race is.
                continue
            print(
                f"doug: retrying comment for job {job['id']} {where} "
                f"(retry {job['pr_comment_attempts'] + 1} of "
                f"{PR_COMMENT_MAX_RETRIES}, "
                f"last {job['pr_comment_outcome'] or 'unrecorded'})",
                file=sys.stderr,
            )
            gh = app_auth.installation_client(job["installation_id"])
            owner, name = job["repo_full_name"].split("/", 1)
            _, summary = _render_recorded(job, existing)
            attempted += 1
            posting = True
            _post_pr_comment(gh, owner, name, job, summary, fresh=False)
        except Exception as e:  # noqa: BLE001 — one bad job must not stop the sweep
            print(
                f"doug: comment retry internal error on job {job['id']} "
                f"({type(e).__name__}: {e})",
                file=sys.stderr,
            )
            if posting:
                # `_post_pr_comment` owns the outcome from the moment it is
                # entered, and it has already written one. Overwriting it with
                # `failed:internal` would put a landed comment back in the
                # retry set and buy a second write of a body that is already
                # on the PR.
                continue
            try:
                store.record_pr_comment_outcome(job["id"], "failed:internal")
            except Exception as inner:  # noqa: BLE001 — the ledger is the fault here
                print(
                    f"doug: comment outcome not recorded for job {job['id']} "
                    f"({type(inner).__name__}: {inner})",
                    file=sys.stderr,
                )
    return attempted


def drain(max_jobs: int = 20) -> int:
    """Claim and run up to max_jobs. Returns how many were attempted.

    Bounded because this runs inside a request's background task: an
    unbounded drain on a busy morning would hold a Cloud Run instance for
    minutes past the response it belongs to. The next delivery kicks it
    again, and reconcile catches anything neither ever reaches.

    One job's failure must not strand the queue behind it — the whole
    queue is FIFO-ish and a poison job would otherwise block every PR
    opened after it.

    Ends by calling retry_unposted_comments() once, after the claim loop —
    the cadence for issue #154's repair. A comment written after
    `ingest.complete` and then lost has no other way back: the row is 'done',
    'done' is not REVIVABLE, and the next delivery for that SHA collides on
    the unique index. Here rather than only in reconcile because a delivery
    kicks this on every push, so a comment lost at 10:00 comes back on the
    next PR's delivery rather than at the next cold start.

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
    # After the claim loop, not before it, and in its own try. After,
    # because the reviews are what this pass is for and the installation
    # token's rate limit is shared — the same order `api._startup_reconcile`
    # puts the outcome sweep in, for the same reason. Its own try, because a
    # repair of an advisory surface must never stop the queue from being
    # worked: this sweep is how a lost comment comes back, but a ledger fault
    # inside it taking down `drain` would be how every REVIEW stops.
    try:
        retried = retry_unposted_comments()
        if retried:
            print(f"doug: retried {retried} unposted comment(s)", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — repair must not cost the queue
        print(
            f"doug: comment retry sweep failed ({type(e).__name__}: {e})",
            file=sys.stderr,
        )
    return attempted


def _skip_reason(p) -> str | None:
    """Why this open PR must not be enqueued, or None.

    The same gate the pull_request webhook applies in api.py. Duplicated
    rather than shared on purpose: the two callers hold different objects —
    a githubkit model here, a parsed webhook payload there — and githubkit
    models an absent field as the UNSET sentinel, not None, so `if p.draft`
    is not the same test as `p.draft is True`. If the webhook's gate
    changes, this changes with it.

    "The same gate" is three properties, and they are the ones to check when
    either side moves: an unknown draft state — absent, null, not a
    boolean — is "draft" on both sides, repo ids that are not both
    integers are "fork" on both sides rather than something to compare, and
    a GitHub App author (`user.type == "Bot"` or login ending in `[bot]`)
    is "bot" on both sides. A missing user is not a bot: truncated
    payloads proceed, matching review.py. They diverged once already, when
    the webhook read a missing `draft` key as "not a draft" and compared
    two absent ids as equal; the webhook was the newer code, so this
    docstring was the thing that became false.
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
    if not isinstance(head_id, int) or not isinstance(base_id, int) or head_id != base_id:
        return "fork"
    # Same-repo Dependabot (and every other GitHub App) passes the fork
    # gate. A deep read of that diff is spend against the plan cap for a
    # change nobody asked Doug to grade. Detection is models.is_bot_author,
    # shared with review.py and the webhook gate. A missing user is not a
    # bot — truncated payloads proceed.
    user = getattr(p, "user", None)
    if user and is_bot_author(getattr(user, "type", None), getattr(user, "login", None)):
        return "bot"
    return None


def _instrument(job: dict):
    """Ledger counters for the check-run footer. None when there is no ledger.

    Degrades to None (footer omitted) on any store error: by the time this
    runs the model read is paid and the verdict durable, so a transient DB
    failure over a cosmetic footer must not abort the check-run post — the
    same contract save_deviations gets in process_job.
    """
    try:
        return store.instrument_snapshot(job["installation_id"], job["github_repo_id"])
    except Exception as e:  # noqa: BLE001 — advisory footer; verdict already durable
        print(
            f"doug: instrument snapshot skipped for job {job['id']} "
            f"({type(e).__name__}: {e})",
            file=sys.stderr,
        )
        return None


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
            # Same length guard api.py's _text applies to the webhook's copy
            # of this fact, and for the same reason: base_ref is VARCHAR(200)
            # while GitHub allows a longer branch name, and Postgres answers
            # an over-long INSERT with StringDataRightTruncation. Here that
            # exception would escape both try blocks and unwind the whole
            # installation — every repo after this one skipped, on this pass
            # and every later one. sqlite stores the long value happily, so a
            # green local suite is not evidence about this.
            if len(base_ref) > store.outcome_jobs.c.base_ref.type.length:
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    f"(base.ref is {len(base_ref)} chars, longer than the column)",
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
            if (
                not isinstance(merge_sha, str)
                or not merge_sha
                or len(merge_sha) > store.outcome_jobs.c.merge_commit_sha.type.length
            ):
                print(
                    f"doug: outcome reconcile skipped {full_name}#{number} "
                    "(missing or over-long merge_commit_sha)",
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
