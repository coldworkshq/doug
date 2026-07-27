"""HTTP surface. Routes stay thin: the product lives in features.py and scoring.py."""

import hmac
import json
import os
from importlib import resources

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from githubkit.webhooks import verify as verify_webhook

from . import __version__
from .models import Band, PRMetadata, QueueItem, QueueResponse, QueueSummary, Verdict
from .scoring import default_threshold, score

app = FastAPI(title="Magpie", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("MAGPIE_CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str | bool]:
    return {"ok": True, "version": __version__}


@app.post("/v1/score")
def score_pr(pr: PRMetadata) -> Verdict:
    return score(pr)


def _load_fixture() -> list[PRMetadata]:
    raw = resources.files("magpie").joinpath("fixtures/queue.json").read_text()
    return [PRMetadata.model_validate(item) for item in json.loads(raw)]


@app.get("/v1/queue")
def queue(threshold: float | None = None) -> QueueResponse:
    thr = default_threshold() if threshold is None else threshold
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
