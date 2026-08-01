"""The job pipeline — one claimed job in, one check run out.

Everything the webhook must not do inline lives here: minting an
installation token, fetching the PR, scoring it, persisting it, posting
the check run. The handler's whole job is to make the work durable and
return 202; a delivery must never wait on a paid model read.

Failure policy differs from the CI-token review path's on purpose. There, a
down ledger must not fail somebody's CI, so save_review's exception becomes
a reason on the response and the review still "succeeds" (api.py's
/v1/review handler). Here the durable row IS the deliverable — a job
marked done having written nothing is a green checkmark over an empty
ledger — so save_review raising propagates, failing the job, and
ingest.fail decides whether to retry. save_deviations keeps the same
swallow api.py's handler uses for it: it is a genuinely separate write
(ADR-0007), and by the time it runs here the verdict it hangs off is
already durable, so a failure there must not cost the job that already
succeeded.
"""

import sys

from . import app_auth, check_run, ingest, reader, review, store
from .models import Reason


def process_job(job: dict) -> int | None:
    """Run one job end to end and mark it done. Returns the verdict id."""
    gh = app_auth.installation_client(job["installation_id"])
    owner, name = job["repo_full_name"].split("/", 1)

    # Read the PR's current head before spending anything on it. A job can
    # sit in the queue behind a backlog, or be re-pended by a retry, long
    # enough for the branch to move — and fetch_pr would then read the NEW
    # diff while every identity column, the unique index and the check run
    # still said the old SHA. That mislabels a read rather than losing one,
    # which is worse: the verdict looks like evidence about a commit it
    # never saw. The SHA that overtook this one gets its own job.
    current = gh.rest.pulls.get(
        owner=owner, repo=name, pull_number=job["pr_number"]
    ).parsed_data.head.sha
    if current != job["head_sha"]:
        ingest.supersede(job["id"])
        ingest.enqueue(
            job["installation_id"],
            job["github_repo_id"],
            job["repo_full_name"],
            job["pr_number"],
            current,
        )
        return None

    meta, diff = review.fetch_pr(gh, owner, name, job["pr_number"])
    tier, verdict, rv, cov = review.score_one(meta, diff)
    intent_read = review.read_intent(gh, owner, name, meta, diff)

    verdict_id = store.save_review(
        job["repo_full_name"],
        job["pr_number"],
        tier,
        verdict,
        rv,
        model=reader.MODEL if tier == "reader" else None,
        pr_meta=meta.model_dump(mode="json"),
        coverage=cov,
        github_repo_id=job["github_repo_id"],
        installation_id=job["installation_id"],
        head_sha=job["head_sha"],
        source="app",
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
    # The job's head SHA, never meta's: by now pulls.get may already be
    # returning a newer commit, and that commit has its own job.
    check_run.post(gh, owner, name, job["head_sha"], title, summary)
    ingest.complete(job["id"], verdict_id)
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
            # Lapped the queue: ingest.fail re-pends a job below the attempt
            # cap, so the only thing left to claim is something this pass
            # already failed. Retrying it here is not a retry — nothing has
            # had time to change — and it would burn the whole attempt
            # budget against one transient fault in under a second. A
            # reclaimed job lands here the same way: it re-enters the
            # pending pool with the same id it always had, so the seen-set
            # treats it like any other re-pended job with no special case.
            ingest.release(job["id"])
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
            ingest.fail(job["id"], str(e))
    return attempted
