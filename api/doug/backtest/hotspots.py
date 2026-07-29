"""Learned path hotspots — no label leakage into the scored set.

Builds a small set of path segments / bigrams that co-occur with revert
labels more often than chance on a training window. Used only as an
*extra* signal on top of the static HOTSPOT_SEGMENTS in features.py.

`rolling_window` picks that training window as of a moment in time, so the
learned set can be refreshed as the repo's risk moves instead of being
learned once and frozen. Hotspots drift fast — learning on the older half of
an 86-day sentry window yields `integrations/*`, `agents/hooks`, `mcp`, while
the newer half's real hotspots were `seer/*`.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from .harvest import HarvestedPR

# Too generic to be useful even at high lift — they fire on a huge fraction
# of the repo and burn the flag budget.
_STOP = {
    "src",
    "sentry",
    "static",
    "app",
    "components",
    "views",
    "utils",
    "tests",
    "test",
    "api",
    "endpoints",
    "models",
    "fixtures",
    "types",
    "private",
    "unit",
    "tsx",
    "py",
    "js",
    "ts",
}


def rolling_window(
    prs: list[HarvestedPR],
    labels: dict[int, str],
    as_of: str,
    *,
    min_defects: int = 12,
    max_days: int = 90,
) -> tuple[list[HarvestedPR], set[int]]:
    """The PRs and labels a learner could legitimately use at `as_of`.

    Walks backwards from `as_of` and stops at whichever comes first: enough
    known defects to learn from, or `max_days` of history. Both bounds earn
    their place — repos differ hugely in label density (sentry produces ~22
    revert-labeled defects a month, grafana ~2.7), so a fixed calendar window
    starves the sparse one and a fixed PR count reaches back past a drift
    boundary on the dense one.

    `labels` maps PR number → the date its revert landed. A defect counts
    only once its revert is in the past: at `as_of` nobody knows the PR was
    bad, so training on it would be measuring clairvoyance.
    """
    cutoff = datetime.fromisoformat(as_of)
    floor = cutoff - timedelta(days=max_days)

    window: list[HarvestedPR] = []
    defects: set[int] = set()
    # Newest first, so the walk can stop as soon as it has enough.
    for pr in sorted(prs, key=lambda p: p.merged_at, reverse=True):
        merged = datetime.fromisoformat(pr.merged_at)
        if merged >= cutoff:
            continue
        if merged < floor:
            break
        window.append(pr)
        reverted_at = labels.get(pr.number)
        if reverted_at is not None and datetime.fromisoformat(reverted_at) < cutoff:
            defects.add(pr.number)
            if len(defects) >= min_defects:
                break

    return window, defects


def _segments(files: list[str]) -> set[str]:
    out: set[str] = set()
    for f in files:
        parts = [p.lower() for p in f.split("/") if p and p not in _STOP]
        for p in parts:
            if p not in _STOP and "." not in p:  # skip filenames
                out.add(p)
        for a, b in zip(parts, parts[1:], strict=False):
            if a in _STOP or b in _STOP:
                continue
            if "." in b:  # skip …/file.py bigrams
                continue
            out.add(f"{a}/{b}")
    return out


def learn_hotspot_segments(
    prs: list[HarvestedPR],
    defects: set[int],
    *,
    min_defects: int = 2,
    min_lift: float = 3.0,
    max_segments: int = 25,
) -> set[str]:
    """Return path segments with elevated revert density on this window."""
    n = len(prs)
    n_def = sum(1 for p in prs if p.number in defects)
    if n == 0 or n_def == 0:
        return set()

    def_seg: Counter[str] = Counter()
    all_seg: Counter[str] = Counter()
    for p in prs:
        segs = _segments(p.files)
        all_seg.update(segs)
        if p.number in defects:
            def_seg.update(segs)

    scored: list[tuple[float, int, str]] = []
    for seg, c in def_seg.items():
        if c < min_defects:
            continue
        base = all_seg[seg]
        lift = (c / n_def) / (base / n) if base else 0.0
        if lift >= min_lift:
            scored.append((lift, c, seg))

    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return {seg for _, _, seg in scored[:max_segments]}
