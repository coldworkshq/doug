"""HTTP surface. Routes stay thin: the product lives in features.py and scoring.py."""

import hmac
import json
import os
from importlib import resources

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from githubkit.webhooks import verify as verify_webhook
from pydantic import BaseModel

from . import __version__, precision, reader, review, store
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


class ReviewResponse(Verdict):
    """The risk verdict, plus the intent tier when it ran.

    Subclasses Verdict so the wire shape stays a superset: existing CI
    workflows parse band/score/threshold/reasons at the top level and keep
    working untouched. `deviations` is absent-or-empty for every repo that
    keeps no decision records, which is most of them.
    """

    deviations: list[reader.DeviationFinding] = []
    intent_alignment: int | None = None
    intent_refs: list[str] = []


@app.post("/v1/review")
def review_pr(
    req: ReviewRequest,
    x_doug_token: str = Header(""),
    x_github_token: str = Header(""),
) -> ReviewResponse:
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
    intent_read = review.read_intent(gh, owner, name, meta, diff)
    verdict_id = None
    try:
        verdict_id = store.save_review(
            req.repo, req.pr_number, tier, verdict, rv,
            model=reader.MODEL if tier == "reader" else None,
            pr_meta=meta.model_dump(mode="json"),
        )
        if intent_read is not None:
            store.save_deviations(
                verdict_id, intent_read.findings,
                intent_read.refs, intent_read.alignment,
            )
    except Exception as e:  # noqa: BLE001 — a down ledger must not fail CI
        verdict.reasons.append(
            Reason(rule="ledger-unavailable", label=str(e)[:200], weight=0.0)
        )
    return ReviewResponse(
        **verdict.model_dump(),
        deviations=intent_read.findings if intent_read else [],
        intent_alignment=intent_read.alignment if intent_read else None,
        intent_refs=intent_read.refs if intent_read else [],
    )


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


def _with_url(row: dict) -> PRMetadata:
    """PR metadata with a link back to the pull request.

    Rows written before `url` was captured — every backfilled probe row and
    everything scored up to now — have none. The ledger knows the repo and
    the number, which is all a GitHub PR URL needs, so they are repaired on
    read rather than by rewriting 654 rows.
    """
    meta = PRMetadata.model_validate(row["pr_meta"])
    if meta.url:
        return meta
    return meta.model_copy(
        update={"url": f"https://github.com/{row['repo']}/pull/{row['pr_number']}"}
    )


def _banding_threshold(items: list[QueueItem], fallback: float) -> float:
    """The line these rows were actually banded at.

    Rows can disagree — a reader row is banded at 0.30, a deterministic
    fallback row at 0.62 — in which case no single line is honest and the
    most common one is the least wrong. The per-item thresholds stay
    authoritative either way; this only decides where the dashboard draws.
    """
    if not items:
        return fallback
    seen: dict[float, int] = {}
    for i in items:
        seen[i.verdict.threshold] = seen.get(i.verdict.threshold, 0) + 1
    return max(seen, key=lambda t: (seen[t], -t))


@app.get("/v1/queue")
def queue(threshold: float | None = None, repo: str | None = None) -> QueueResponse:
    thr = default_threshold() if threshold is None else threshold
    if store.enabled():
        items = [
            QueueItem(
                pr=_with_url(row),
                verdict=Verdict(
                    score=row["score"],
                    band=Band(row["band"]),
                    threshold=row["threshold"],
                    reasons=[
                        Reason(
                            rule=f["rule"],
                            label=f["label"],
                            weight=f["weight"],
                            severity=f["severity"],
                        )
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

    if threshold is None:
        # Report the line the rows were actually banded at, not the
        # deterministic default. Ledger rows carry the reader's threshold
        # (0.30); reporting 0.62 made the dashboard draw its cut line above
        # PRs it was simultaneously showing as flagged.
        thr = _banding_threshold(items, thr)
    else:
        # An explicit threshold has to re-band, or the parameter changes the
        # number in the summary while the rows keep contradicting it.
        items = [
            QueueItem(
                pr=i.pr,
                verdict=i.verdict.model_copy(
                    update={
                        "threshold": thr,
                        "band": Band.FLAGGED if i.verdict.score >= thr else Band.CLEARED,
                    }
                ),
            )
            for i in items
        ]

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


class PatternRow(BaseModel):
    pattern: str
    prs: int
    defects: int
    precision: float
    ci_low: float
    ci_high: float
    lift: float
    clears_base: bool


class PatternsResponse(BaseModel):
    prs: int
    defects: int
    base_rate: float
    patterns_seen: int  # before the min_prs cut — the long tail's size
    rows: list[PatternRow]
    caveat: str


PATTERNS_CAVEAT = (
    "precision is within these ledger rows only. The seed corpus is an "
    "enriched sample (all known defects plus a clean subsample), so its base "
    "rate is far above any repo's true defect rate — compare lift, not "
    "precision. clears_base is uncorrected for multiplicity."
)


@app.get("/v1/patterns")
def patterns_precision(
    repo: str | None = None,
    min_prs: int = 5,
    x_doug_token: str = Header(""),
) -> PatternsResponse:
    """Per-pattern precision from the findings x outcomes join.

    Token-gated on the same shared secret as /v1/review: this is the
    unpublished half of the evidence base, and the caveat travels in the
    response body so a number cannot be lifted out of it by accident.
    """
    expected = os.environ.get("DOUG_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DOUG_API_TOKEN not configured")
    if not hmac.compare_digest(x_doug_token, expected):
        raise HTTPException(status_code=401, detail="bad token")
    if not store.enabled():
        raise HTTPException(status_code=503, detail="no ledger configured")

    is_defect, carriers = precision.fold(store.pattern_join(repo=repo))
    rows, base = precision.corpus_table(is_defect, carriers, min_prs=min_prs)
    return PatternsResponse(
        prs=len(is_defect),
        defects=sum(is_defect.values()),
        base_rate=base,
        patterns_seen=len(carriers),
        rows=[PatternRow(**r) for r in rows],
        caveat=PATTERNS_CAVEAT,
    )


@app.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
) -> Response:
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        # Fail closed, matching /v1/review and /v1/patterns. Accepting
        # unverified payloads was survivable while this endpoint discarded
        # everything; under the App a delivery triggers a paid model read.
        raise HTTPException(
            status_code=503, detail="GITHUB_WEBHOOK_SECRET not configured"
        )
    body = await request.body()
    # githubkit's verify() reads the digest from the signature prefix, not
    # from the header name, so an attacker-supplied "sha1=" would downgrade
    # the comparison. Pin it.
    if not x_hub_signature_256.startswith("sha256="):
        raise HTTPException(status_code=401, detail="bad signature")
    if not verify_webhook(secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="bad signature")

    # Phase 2 (the Live Gate) will parse pull_request events here, extract
    # features, score, and post a check run. Accepting and discarding is
    # deliberate until then.
    return Response(status_code=202)
