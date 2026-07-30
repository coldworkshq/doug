"""HTTP surface. Routes stay thin: the product lives in features.py and scoring.py."""

import hmac
import json
import os
from importlib import resources

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from githubkit.webhooks import verify as verify_webhook
from pydantic import BaseModel

from . import __version__, reader, review, store
from .models import (
    Band,
    PRMetadata,
    QueueItem,
    QueueResponse,
    QueueSummary,
    ReadScoreRequest,
    Reason,
    Verdict,
)
from .scoring import default_threshold, score

app = FastAPI(title="Doug", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("DOUG_CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str | bool]:
    return {"ok": True, "version": __version__}


@app.post("/v1/score")
def score_pr(pr: PRMetadata) -> Verdict:
    return score(pr)


class ReviewRequest(BaseModel):
    repo: str  # owner/name
    pr_number: int


@app.post("/v1/review")
def review_pr(
    req: ReviewRequest,
    x_doug_token: str = Header(""),
    x_github_token: str = Header(""),
) -> Verdict:
    """CI-facing review: fetch the PR, score through the reader tier, persist.

    Auth is a shared token (DOUG_API_TOKEN); the GitHub token arrives
    per-request from the caller's CI so this service holds no repo
    credentials of its own. Unconfigured deployments refuse rather than
    run open.
    """
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if not hmac.compare_digest(x_doug_token, expected):
        raise HTTPException(status_code=401, detail="bad token")
    try:
        owner, name = req.repo.split("/", 1)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="repo must be owner/name") from e

    from githubkit import GitHub

    gh = GitHub(x_github_token or None)
    meta, diff = review.fetch_pr(gh, owner, name, req.pr_number)
    tier, verdict, rv = review.score_one(meta, diff)
    try:
        store.save_review(
            req.repo, req.pr_number, tier, verdict, rv,
            model=reader.MODEL if tier == "reader" else None,
            pr_meta=meta.model_dump(mode="json"),
        )
    except Exception as e:  # noqa: BLE001 — a down ledger must not fail CI
        verdict.reasons.append(
            Reason(rule="ledger-unavailable", label=str(e)[:200], weight=0.0)
        )
    return verdict


@app.post("/v1/score/read")
def score_pr_read(req: ReadScoreRequest) -> Verdict:
    """Reader-tier scoring: LLM diff-read when enabled, deterministic otherwise.

    A failed read never 500s — it falls back to the deterministic verdict
    and says so in the reasons, because a silent downgrade would corrupt
    any calibration built on this endpoint's output.
    """
    if not reader.enabled():
        return score(req.pr)
    try:
        return reader.verdict_from_reader(reader.read_diff(req.pr, req.diff))
    except reader.ReaderError as e:
        fallback = score(req.pr)
        fallback.reasons.append(
            Reason(rule="reader-unavailable", label=str(e), weight=0.0)
        )
        return fallback


def _load_fixture() -> list[PRMetadata]:
    raw = resources.files("doug").joinpath("fixtures/queue.json").read_text()
    return [PRMetadata.model_validate(item) for item in json.loads(raw)]


@app.get("/v1/queue")
def queue(threshold: float | None = None, repo: str | None = None) -> QueueResponse:
    thr = default_threshold() if threshold is None else threshold
    if store.enabled():
        items = [
            QueueItem(
                pr=PRMetadata.model_validate(row["pr_meta"]),
                verdict=Verdict(
                    score=row["score"],
                    band=Band(row["band"]),
                    threshold=row["threshold"],
                    reasons=[
                        Reason(rule=f["rule"], label=f["label"], weight=f["weight"])
                        for f in row["findings"]
                    ],
                ),
            )
            for row in store.latest_reviews(repo=repo)
            if row["pr_meta"]
        ]
    else:
        # No ledger configured — the fixture keeps the demo path alive.
        items = [QueueItem(pr=pr, verdict=score(pr, thr)) for pr in _load_fixture()]
    items.sort(key=lambda i: i.verdict.score, reverse=True)
    flagged = sum(1 for i in items if i.verdict.band is Band.FLAGGED)
    return QueueResponse(
        summary=QueueSummary(
            open=len(items),
            flagged=flagged,
            cleared=len(items) - flagged,
            threshold=thr,
        ),
        items=items,
    )


@app.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
) -> Response:
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    body = await request.body()
    if secret:
        if not x_hub_signature_256 or not verify_webhook(secret, body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="bad signature")
    elif not hmac.compare_digest(x_hub_signature_256, ""):
        # A signature arrived but no secret is configured: refuse rather than
        # silently accept unverified payloads.
        raise HTTPException(status_code=401, detail="webhook secret not configured")

    # Phase 2 (the Live Gate) will parse pull_request events here, extract
    # features, score, and post a check run. Accepting and discarding is
    # deliberate until then.
    return Response(status_code=202)
