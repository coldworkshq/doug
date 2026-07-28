"""Defect labeling via revert anchors.

A merged PR is labeled defect-inducing if a later merged PR reverts it —
detected through GitHub's auto-generated "Reverts owner/repo#N" body
line, explicit #N references in revert-titled PRs, or a quoted-title
match ('Revert "original title"').

Reverts under-count real defects (plenty of bad changes get fixed
forward), but they are high-precision anchors and this bias is
conservative: a capture curve built on them understates absolute defect
counts, not the ranking quality being measured.
"""

import re

from .harvest import HarvestedPR

_REVERT_REF = re.compile(r"revert(?:s|ed)?\b[^#]{0,80}#(\d+)", re.IGNORECASE)
_REVERT_TITLE = re.compile(r"^\s*revert\b", re.IGNORECASE)
_QUOTED_TITLE = re.compile(r'"([^"]+)"')


def label_defects(
    prs: list[HarvestedPR],
    extra_reverts: list[tuple[str, str]] | None = None,
) -> set[int]:
    """Return the numbers of harvested PRs that were later reverted.

    extra_reverts: (title, body) pairs of revert PRs found outside the
    harvest window (e.g. via the search API), so labels don't depend on
    the revert landing inside the window.
    """
    numbers = {p.number for p in prs}
    by_title = {p.title.strip(): p.number for p in prs}
    defects: set[int] = set()

    candidates: list[tuple[str, str, int | None]] = [
        (p.title, p.body, p.number) for p in prs
    ]
    candidates += [(t, b, None) for t, b in extra_reverts or []]

    for title, body, own_number in candidates:
        is_revert = bool(_REVERT_TITLE.search(title))

        for m in _REVERT_REF.finditer(f"{title}\n{body}"):
            ref = int(m.group(1))
            if ref in numbers and ref != own_number:
                defects.add(ref)

        if is_revert:
            for quoted in _QUOTED_TITLE.findall(title):
                target = by_title.get(quoted.strip())
                if target is not None and target != own_number:
                    defects.add(target)

    return defects
