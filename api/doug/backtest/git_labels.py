"""Dense defect labels from git history — zero GitHub API quota.

Squash-merge subjects embed PR numbers (`Ship feature (#1234)`). A
treeless clone (`--filter=tree:0`) plus commit-subject parsing lets us
resolve revert → original PR across *all* history without listing PRs
over the REST API. The API is then reserved for feature harvest only.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple


class Commit(NamedTuple):
    """One commit's identity, timing, and message."""

    sha: str = ""
    date: str = ""
    subject: str = ""
    body: str = ""

_PR_PAREN = re.compile(r"\(#(\d+)\)")
_PR_HASH = re.compile(r"(?:^|[\s:])#(\d+)\b")
# Quoted-title revert: Revert "…" / Reverted: "…"
_QUOTED_REVERT = re.compile(r'^\s*revert(?:s|ed)?\b[^"]*"', re.IGNORECASE)
# Bare-target form: "Revert #7" / "Reverts (#12)" — number is the original.
_BARE_TARGET = re.compile(
    r"^\s*revert(?:s|ed)?\s*[:(]?\s*[#(](\d+)\)?\b",
    re.IGNORECASE,
)
_QUOTED = re.compile(r'"([^"]+)"')
_MERGE_PR = re.compile(r"Merge pull request #(\d+)\b", re.IGNORECASE)
_TRAILING_PR = re.compile(r"\s*\(#\d+\)\s*$")
# git writes this into every revert it generates. It is an *exact* pointer to
# the reverted commit, unlike the quoted-title fallback, which fails whenever
# the revert subject doesn't reproduce the PR title verbatim.
_REVERTS_COMMIT = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.IGNORECASE)
_SHORT_SHA = 7


def clone_treeless(owner: str, repo: str, dest: Path, token: str | None = None) -> Path:
    """Bare treeless clone. Reuses dest if it already looks healthy."""
    if (dest / "HEAD").exists():
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--prune", "--filter=tree:0", "origin"],
            check=False,
            capture_output=True,
            timeout=300,
        )
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)

    url = f"https://github.com/{owner}/{repo}.git"
    if token:
        url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"

    subprocess.run(
        [
            "git",
            "clone",
            "--bare",
            "--filter=tree:0",
            "--single-branch",
            url,
            str(dest),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(dest),
            "remote",
            "set-url",
            "origin",
            f"https://github.com/{owner}/{repo}.git",
        ],
        check=False,
        capture_output=True,
    )
    return dest


# A commit message can contain anything; the unit and record separators cannot.
_LOG_SEP = "\x1f"
_LOG_REC = "\x1e"


def _log_records(clone: Path) -> list[Commit]:
    """Every commit, newest first. Bodies included — they carry the revert sha."""
    out = subprocess.run(
        [
            "git", "-C", str(clone), "log", "--all",
            f"--format=%H{_LOG_SEP}%cI{_LOG_SEP}%s{_LOG_SEP}%b{_LOG_REC}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    commits = []
    for record in out.stdout.split(_LOG_REC):
        if not record.strip():
            continue
        parts = record.lstrip("\n").split(_LOG_SEP)
        if len(parts) < 3:
            continue
        sha, date, subject = parts[0], parts[1], parts[2]
        commits.append(Commit(sha, date, subject, parts[3] if len(parts) > 3 else ""))
    return commits


def pr_numbers_by_sha(commits: list[Commit]) -> dict[str, int]:
    """Squash-commit sha → the PR number in its subject."""
    out: dict[str, int] = {}
    for c in commits:
        if not c.sha:
            continue
        if m := _PR_PAREN.search(c.subject):
            out[c.sha] = int(m.group(1))
    return out


def _resolve_sha(sha: str, by_sha: dict[str, int]) -> int | None:
    """Look up a possibly-abbreviated sha. Ambiguous prefixes resolve to None —
    a coin-flip between two PRs is a mislabel, which is what we are here to fix."""
    if (hit := by_sha.get(sha)) is not None:
        return hit
    if len(sha) < _SHORT_SHA:
        return None
    matches = {pr for full, pr in by_sha.items() if full.startswith(sha)}
    return matches.pop() if len(matches) == 1 else None


def _normalize_title(title: str) -> str:
    return _TRAILING_PR.sub("", title).strip()


def _is_revert_subject(subject: str) -> bool:
    return bool(_QUOTED_REVERT.search(subject) or _BARE_TARGET.match(subject))


def pr_titles_from_subjects(subjects: list[str]) -> dict[str, int]:
    """Map normalized squash titles → PR number.

    `git log` emits newest-first; first writer wins so the map keeps the
    most recent PR for a reused title (dependency bumps, "Fix typo").
    Feature PRs titled "Revert to legacy…" are kept — they are not
    revert anchors.
    """
    titles: dict[str, int] = {}
    for subject in subjects:
        if _MERGE_PR.search(subject) or _is_revert_subject(subject):
            continue
        if m := _PR_PAREN.search(subject):
            key = _normalize_title(subject)
            if key and key not in titles:
                titles[key] = int(m.group(1))
    return titles


def parse_revert_targets_dated(
    commits: list[Commit], titles: dict[str, int] | None = None
) -> dict[int, str]:
    """PR number → the date its defect label first became knowable.

    On squash-merge repos, `Revert "Add x" (#99)` uses (#99) for the
    *revert* PR. The original is recovered three ways, in descending order of
    reliability: a `#N` nested inside the quotes, the `This reverts commit
    <sha>` pointer in the body, and finally the quoted title matched against
    the squash-title map. The sha path matters — on grafana the title fallback
    alone resolved 64% of reverts, because its revert subjects quote a title
    that does not reproduce the PR title.

    The subject still gates what counts as a revert. A body marker alone is
    not enough: "Reland X" carries `This reverts commit …` and is the
    opposite of a revert.

    The date is the reverting commit's, not the reverted PR's: nobody —
    including a live Doug — could have known the PR was bad until the
    revert landed. On a re-revert the *earliest* date wins.
    """
    if titles is None:
        titles = pr_titles_from_subjects([c.subject for c in commits])
    by_sha = pr_numbers_by_sha(commits)
    dated: dict[int, str] = {}

    def mark(number: int, date: str) -> None:
        if number not in dated or date < dated[number]:
            dated[number] = date

    for c in commits:
        if _QUOTED_REVERT.search(c.subject):
            for q in _QUOTED.findall(c.subject):
                for m in _PR_PAREN.finditer(q):
                    mark(int(m.group(1)), c.date)
                for m in _PR_HASH.finditer(q):
                    mark(int(m.group(1)), c.date)
                key = _normalize_title(q)
                if key in titles:
                    mark(titles[key], c.date)
            for m in _REVERTS_COMMIT.finditer(c.body):
                if (pr := _resolve_sha(m.group(1).lower(), by_sha)) is not None:
                    mark(pr, c.date)
            continue

        if m := _BARE_TARGET.match(c.subject):
            mark(int(m.group(1)), c.date)

    return dated


def parse_revert_targets(
    subjects: list[str], titles: dict[str, int] | None = None
) -> set[int]:
    """Undated, subject-only view of `parse_revert_targets_dated`."""
    return set(parse_revert_targets_dated([Commit(subject=s) for s in subjects], titles))


def find_reverted_prs_dated(
    owner: str,
    repo: str,
    cache_dir: Path,
    token: str | None = None,
) -> dict[int, str]:
    """Clone (or reuse) and map reverted PR number → revert-commit date.

    The dates are what let a rolling learner train on only the labels that
    existed at a given moment; without them a backtest silently assumes the
    product knew about reverts that had not happened yet.
    """
    cache = cache_dir / f"{owner}-{repo}-git-defects-dated.json"
    if cache.exists():
        return {int(k): v for k, v in json.loads(cache.read_text()).items()}

    clone_dir = cache_dir / "clones" / f"{owner}-{repo}.git"
    print(f"  treeless clone of {owner}/{repo}…", flush=True)
    clone_treeless(owner, repo, clone_dir, token=token)
    commits = _log_records(clone_dir)
    titles = pr_titles_from_subjects([c.subject for c in commits])
    dated = parse_revert_targets_dated(commits, titles)

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({str(k): dated[k] for k in sorted(dated)}, indent=1))
    return dated


def find_reverted_prs(
    owner: str,
    repo: str,
    cache_dir: Path,
    token: str | None = None,
) -> set[int]:
    """Clone (or reuse) and return the set of PR numbers later reverted."""
    cache = cache_dir / f"{owner}-{repo}-git-defects.json"
    if cache.exists():
        return set(json.loads(cache.read_text()))

    defects = set(find_reverted_prs_dated(owner, repo, cache_dir, token=token))
    cache.write_text(json.dumps(sorted(defects), indent=1))
    return defects
