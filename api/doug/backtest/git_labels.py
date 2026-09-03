"""Dense defect labels from git history — zero GitHub API quota.

Squash-merge subjects embed PR numbers (`Ship feature (#1234)`). A
treeless clone (`--filter=tree:0`) plus commit-subject parsing lets us
resolve revert → original PR across *all* history without listing PRs
over the REST API. The API is then reserved for feature harvest only.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple


class Commit(NamedTuple):
    """One commit's identity, timing, and message."""

    sha: str = ""
    date: str = ""
    subject: str = ""
    body: str = ""


# The slack on the *lower* end of a revert window: a revert dated up to this
# many days before the merge is still that merge's revert. It lives here, in
# the only detector (design-lock.md:29), because the backtest scripts and the
# live adjudicator have to drop the same labels or "live labels and backtest
# labels are the same event" is a promise instead of a property.
#
# Why a lower bound exists at all: a revert cannot land before the PR it
# reverts, yet some do in our label set — 6/67 on sentry, 6/54 on grafana —
# because `pr_titles_from_subjects` is newest-wins, so a revert of an *older*
# PR with a reused squash title ("Fix typo", a dependency bump) is attributed
# to a newer one. Those labels are impossible, not merely surprising.
#
# Why it is not zero: sub-day negatives are committer-date vs `merged_at`
# clock skew on same-day reverts, not mislabels — so a strict `>= merged_at`
# would throw away real misses, and would diverge from the corpora that
# validated the detector, which is the opposite of the error this constant
# fixes. `scripts/label_precision_delta.py` is where that was measured.
#
# The ruling and its cost — dropping impossible labels can only *lower* a
# published miss rate — are recorded in
# `docs/design/outcome-loop/publication-preregistration.md` §6.1.
TOLERANCE_DAYS = 1

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


def _git_auth_env(token: str | None) -> dict[str, str]:
    """Authenticate to GitHub without putting a credential in argv or config.

    Git's environment-backed config exists only for the child process. The
    repository keeps its public origin URL, and ``CalledProcessError`` can
    safely render the command that failed without rendering the token.
    """
    env = os.environ.copy()
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
            }
        )
    return env


def clone_treeless(owner: str, repo: str, dest: Path, token: str | None = None) -> Path:
    """Bare treeless clone. A reused clone must refresh successfully."""
    auth_env = _git_auth_env(token)
    if (dest / "HEAD").exists():
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--prune", "--filter=tree:0", "origin"],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
            env=auth_env,
        )
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)

    subprocess.run(
        [
            "git",
            "clone",
            "--bare",
            "--filter=tree:0",
            "--single-branch",
            f"https://github.com/{owner}/{repo}.git",
            str(dest),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
        env=auth_env,
    )
    return dest


# A commit message can contain anything; the unit and record separators cannot.
_LOG_SEP = "\x1f"
_LOG_REC = "\x1e"


def _log_records(clone: Path, token: str | None = None) -> list[Commit]:
    """Every commit, newest first. Bodies included — they carry the revert sha.

    The log is a network operation on a treeless clone. ``git log --all``
    simplifies history by comparing each merge's tree with its parents', and
    ``--filter=tree:0`` left those trees behind, so git fetches them lazily
    from the promisor remote *during the log*. That fetch must carry the same
    credential as the clone: anonymous, it succeeds on a public repository
    and exits 128 (``could not read Username``) on a private one, which is
    how every private-repo outcome job failed its evidence read (doug#270).
    """
    out = subprocess.run(
        [
            "git", "-C", str(clone), "log", "--all",
            f"--format=%H{_LOG_SEP}%cI{_LOG_SEP}%s{_LOG_SEP}%b{_LOG_REC}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        env=_git_auth_env(token),
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


def commit_instant(date: str) -> datetime:
    """A `%cI` committer date → the aware UTC instant it names.

    Raises `ValueError` on anything it cannot turn into an aware instant, in
    two ways that are worth telling apart:

    * **An offset outside ±24h**, which `_log_records` really does emit. git
      records whatever offset the committing environment declared and prints
      it back verbatim, so `GIT_COMMITTER_DATE="@1772000000 +2400"` reaches
      `%cI` as `2026-02-26T06:13:20+24:00`, and `fromisoformat` rejects it —
      before the naive check below ever runs. Rare, but a real corpus is
      allowed to contain one and nothing upstream filters it.
    * **No offset at all**, i.e. a date that parses and comes back naive
      (`"2026-03-01T00:00:00"`). `%cI` always writes an offset, so this one
      arrives from a hand-built `Commit` rather than from a clone. Refused
      rather than guessed at: `astimezone(UTC)` on a naive datetime reads it
      as *local* time, which is right by accident on a UTC container and
      silently wrong by hours anywhere else.

    The guess is the dangerous branch, which is why neither case gets one: a
    wrong instant does not raise, it moves a revert across a window boundary
    and changes a published label. `adjudicate.adjudicate` catches this
    `ValueError` once per job, so a commit git wrote strangely fails the jobs
    that actually depend on it instead of the whole batch.
    """
    try:
        instant = datetime.fromisoformat(date)
    except ValueError as exc:
        # `fromisoformat`'s own message names the offset it rejected but never
        # the string it came from, and the string is the only thing that leads
        # back to the commit.
        raise ValueError(f"unparseable commit date {date!r}: {exc}") from exc
    if instant.tzinfo is None:
        raise ValueError(f"commit date carries no UTC offset: {date!r}")
    return instant.astimezone(UTC)


def _earlier_by_string(candidate: Commit, incumbent: Commit) -> bool:
    """The backtest's original rule: raw `%cI` string order, ties keep the
    incumbent — and on a tie the two dates are equal, so which commit that is
    comes from `git log`'s ordering rather than from anything chronological."""
    return candidate.date < incumbent.date


def _earlier_by_instant(candidate: Commit, incumbent: Commit) -> bool:
    """The adjudicator's rule — publication-preregistration.md §6.1's declared
    amendment, and §10's tie-break.

    Across differing UTC offsets, string order is not chronological order:
    `2026-03-01T02:00:00-05:00` sorts before `2026-03-01T09:00:00+09:00` and
    happens seven hours after it. Ties on the instant break to the
    lexicographically smallest sha, so a re-revert cannot leave two
    implementations publishing different shas for the same event.
    """
    return (commit_instant(candidate.date), candidate.sha) < (
        commit_instant(incumbent.date),
        incumbent.sha,
    )


def _attribute_reverts(
    commits: list[Commit],
    titles: dict[str, int] | None,
    *,
    earlier: Callable[[Commit, Commit], bool],
) -> dict[int, Commit]:
    """PR number → the reverting commit that first made its defect label
    knowable, under whichever "first" rule `earlier` implements.

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
    revert landed. On a re-revert the *earliest* revert wins.

    `earlier` is the only thing the two public parsers differ by, which is
    what makes "same detector both sides" (design-lock.md:15) a structural
    fact rather than a promise: attribution — which PRs are marked at all —
    is this one function for both.
    """
    if titles is None:
        titles = pr_titles_from_subjects([c.subject for c in commits])
    by_sha = pr_numbers_by_sha(commits)
    marked: dict[int, Commit] = {}

    def mark(number: int, commit: Commit) -> None:
        incumbent = marked.get(number)
        if incumbent is None or earlier(commit, incumbent):
            marked[number] = commit

    for c in commits:
        if _QUOTED_REVERT.search(c.subject):
            for q in _QUOTED.findall(c.subject):
                for m in _PR_PAREN.finditer(q):
                    mark(int(m.group(1)), c)
                for m in _PR_HASH.finditer(q):
                    mark(int(m.group(1)), c)
                key = _normalize_title(q)
                if key in titles:
                    mark(titles[key], c)
            for m in _REVERTS_COMMIT.finditer(c.body):
                if (pr := _resolve_sha(m.group(1).lower(), by_sha)) is not None:
                    mark(pr, c)
            continue

        if m := _BARE_TARGET.match(c.subject):
            mark(int(m.group(1)), c)

    return marked


def parse_revert_targets_dated(
    commits: list[Commit], titles: dict[str, int] | None = None
) -> dict[int, str]:
    """PR number → the date its defect label first became knowable.

    The backtest's view, and deliberately unchanged: it compares raw `%cI`
    strings, and the cached corpora under `.backtest-cache/` were computed
    that way. Callers that need a chronologically-correct "earliest" — or
    the reverting commit's sha — want `parse_revert_targets_evidenced`.
    """
    return {
        number: c.date
        for number, c in _attribute_reverts(
            commits, titles, earlier=_earlier_by_string
        ).items()
    }


def parse_revert_targets_evidenced(
    commits: list[Commit], titles: dict[str, int] | None = None
) -> dict[int, Commit]:
    """PR number → the whole reverting commit, not just its date.

    `parse_revert_targets_dated` discards the sha, and the receipt is
    promised one (`product-spec.md:39`, design-lock.md:15's "anchor sha,
    revert sha"). Same attribution — literally the same pass — with two
    declared differences, both from publication-preregistration.md:

    * the winning commit survives whole, so `detail` can name it;
    * "earliest" is decided on parsed instants and not on raw strings (§6.1),
      with ties broken by the lexicographically smallest sha (§10).

    Dates are parsed lazily and only where they decide something: `mark`
    consults `earlier` only once a PR already has an incumbent, so a corpus
    that attributes every PR exactly once never calls `commit_instant` at all
    and hands its dates back exactly as git wrote them. This function
    therefore does **not** guarantee that every commit it returns carries a
    parseable date, and it deliberately does not validate them to make the
    guarantee true — a raise here would fail the whole repository's map over
    one strange commit, where `adjudicate.adjudicate` parses the winner's date
    per job and fails only the jobs that depend on it.

    The subject-only `parse_revert_targets` still routes through the dated
    form for the older reason: its `Commit`s carry no date at all.
    """
    return _attribute_reverts(commits, titles, earlier=_earlier_by_instant)


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
    commits = _log_records(clone_dir, token=token)
    titles = pr_titles_from_subjects([c.subject for c in commits])
    dated = parse_revert_targets_dated(commits, titles)

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({str(k): dated[k] for k in sorted(dated)}, indent=1))
    return dated


def find_reverted_prs_evidenced(
    owner: str,
    repo: str,
    cache_dir: Path,
    token: str | None = None,
) -> dict[int, Commit]:
    """Clone (or refresh) and retain the evidence commit for every revert.

    The scheduled adjudicator needs the revert SHA and parsed instant for its
    receipt. This is intentionally a thin public adapter over the same log
    reader and ``parse_revert_targets_evidenced`` attribution pass the pure
    adjudicator fixtures exercise; there is no live-only matcher to drift.
    """
    clone_dir = cache_dir / "clones" / f"{owner}-{repo}.git"
    clone_treeless(owner, repo, clone_dir, token=token)
    commits = _log_records(clone_dir, token=token)
    titles = pr_titles_from_subjects([commit.subject for commit in commits])
    return parse_revert_targets_evidenced(commits, titles)


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
