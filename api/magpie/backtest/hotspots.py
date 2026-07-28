"""Train-half learned path hotspots — no label leakage into the test half.

Builds a small set of path segments / bigrams that co-occur with revert
labels more often than chance on a training window. Used only as an
*extra* signal on top of the static HOTSPOT_SEGMENTS in features.py.
"""

from __future__ import annotations

from collections import Counter

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
