"""Where decision records come from.

One provider today: ADR-format markdown in the repo under review, fetched
with the per-request GitHub token CI already supplies. That choice is
ADR-0006 — it needs no new credential, works on private repos, reads
`status` straight from the file so superseded records can be excluded,
and generalises to any repo that keeps ADRs.

A lema-backed provider would sit behind the same `fetch` signature. It is
deliberately absent: lema's hosted interface is search-only with no status
filter, so it cannot answer "is this decision still binding", which is the
one question this module exists to answer correctly.
"""

import os
import re
import sys

from githubkit.exception import RequestFailed

from .intent import IntentDoc

_ID = re.compile(r"^[A-Za-z]+-\d+")

# Where ADR-style records conventionally live. Checked in order; the first
# directory that yields records wins.
CANDIDATE_PATHS = ("docs/decisions", "docs/adr", "doc/adr", "docs/architecture/decisions")


def adr_paths() -> tuple[str, ...]:
    override = os.environ.get("DOUG_ADR_PATH")
    return (override,) if override else CANDIDATE_PATHS


def _is_missing(exc: BaseException) -> bool:
    """A directory that isn't there is the common case, not a failure."""
    return isinstance(exc, RequestFailed) and exc.response.status_code == 404


def parse_record(path: str, text: str) -> IntentDoc | None:
    """One ADR file -> IntentDoc, or None if it is not a decision record.

    Frontmatter is a contract (docs/decisions/README.md), but files in
    these directories are written by hand and some of them are READMEs or
    templates. Anything without parseable frontmatter is skipped silently
    rather than guessed at — a mis-parsed record would be fed to the model
    as policy.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    front, body = text[3:end], text[end + 4 :]

    meta: dict[str, str] = {}
    for line in front.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip().strip("\"'")

    status = meta.get("status")
    title = meta.get("title")
    if not status or not title:
        return None

    # "ADR-0004-llm-reader-in-the-scoring-path.md" -> "ADR-0004"; anything
    # that does not follow the convention keeps its whole filename.
    stem = path.rsplit("/", 1)[-1].removesuffix(".md")
    match = _ID.match(stem)
    return IntentDoc(
        id=match.group(0) if match else stem,
        title=title,
        body=body.strip(),
        status=status,
        date=meta.get("date"),
        ref=path,
    )


def fetch(gh, owner: str, repo: str, ref: str | None = None) -> list[IntentDoc]:
    """Every parseable decision record in the repo. [] when there are none.

    A repo without an ADR directory is the common case, not an error: the
    intent read simply does not happen. Auth, rate-limit, and transport
    failures are re-raised so the caller can log-and-skip — collapsing
    them to [] would make a broken credential look like "no ADRs".
    """
    for directory in adr_paths():
        try:
            listing = gh.rest.repos.get_content(
                owner=owner, repo=repo, path=directory,
                **({"ref": ref} if ref else {}),
            ).parsed_data
        except Exception as e:  # noqa: BLE001 — classify below
            if _is_missing(e):
                continue
            raise
        if not isinstance(listing, list):
            continue

        docs = []
        for entry in listing:
            name = getattr(entry, "name", "")
            if getattr(entry, "type", "") != "file" or not name.endswith(".md"):
                continue
            path = getattr(entry, "path", f"{directory}/{name}")
            try:
                text = _read_file(gh, owner, repo, path, ref)
            except Exception as e:  # noqa: BLE001 — one unreadable file is not fatal
                print(
                    f"doug: decision record unread ({path}: {type(e).__name__}: {e})",
                    file=sys.stderr,
                )
                continue
            doc = parse_record(path, text)
            if doc is not None:
                docs.append(doc)
        if docs:
            return docs
    return []


def _read_file(gh, owner: str, repo: str, path: str, ref: str | None) -> str:
    import base64

    data = gh.rest.repos.get_content(
        owner=owner, repo=repo, path=path, **({"ref": ref} if ref else {})
    ).parsed_data
    content = getattr(data, "content", "") or ""
    if getattr(data, "encoding", "") == "base64":
        return base64.b64decode(content).decode("utf-8", errors="replace")
    return content
