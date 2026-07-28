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


def _log_subjects(clone: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(clone), "log", "--all", "--format=%s"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return out.stdout.splitlines()


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


def parse_revert_targets(
    subjects: list[str], titles: dict[str, int] | None = None
) -> set[int]:
    """PR numbers that a later commit claims to revert.

    On squash-merge repos, `Revert "Add x" (#99)` uses (#99) for the
    *revert* PR. The original is recovered from the quoted title (or from
    a `#N` nested inside the quotes). Bare `Revert #12` keeps 12 as the
    target. Feature PRs titled "Revert to legacy…" are ignored.
    """
    titles = titles if titles is not None else pr_titles_from_subjects(subjects)
    defects: set[int] = set()

    for subject in subjects:
        if _QUOTED_REVERT.search(subject):
            for q in _QUOTED.findall(subject):
                defects.update(int(m.group(1)) for m in _PR_PAREN.finditer(q))
                defects.update(int(m.group(1)) for m in _PR_HASH.finditer(q))
                key = _normalize_title(q)
                if key in titles:
                    defects.add(titles[key])
            continue

        if m := _BARE_TARGET.match(subject):
            defects.add(int(m.group(1)))

    return defects


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

    clone_dir = cache_dir / "clones" / f"{owner}-{repo}.git"
    print(f"  treeless clone of {owner}/{repo}…", flush=True)
    clone_treeless(owner, repo, clone_dir, token=token)
    subjects = _log_subjects(clone_dir)
    titles = pr_titles_from_subjects(subjects)
    defects = parse_revert_targets(subjects, titles)

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(sorted(defects), indent=1))
    return defects
