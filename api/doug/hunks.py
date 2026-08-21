"""Content-hash index over unified diff hunks.

The Walked Out convergence redesign identifies a finding's file-delta by the
multiset of its hunks' content hashes (docs/design/walked-out/design-lock.md;
convergence-design.md "Rule 5 replaced"). A hunk's identity is its `+`/`-`
lines and nothing else: `@@` header numbers move whenever unrelated code above
shifts, and context lines change whenever neighbors change — neither says
anything about THIS change, and reading them would break by-construction
carry-forward on every rebase.

Pure text functions, no imports beyond the standard library. The eval's
`index_from_git` (script-side) feeds `git diff` text through these same
functions so the product and its evaluation compute one function, not two.
"""

import hashlib

__all__ = ["split_hunks", "hash_hunk", "index_from_patches"]


def split_hunks(patch: str) -> list[str]:
    """Split unified patch text into hunk texts, in order.

    A hunk starts at a line beginning `@@` and runs to the next such line or
    the end of the text. Anything before the first `@@` is ignored — that is
    where `git diff` carries its `diff --git`/`index`/`---`/`+++` file
    headers, which GitHub `patch` fields do not have; skipping the preamble
    lets one parser serve both shapes. Content lines inside a hunk begin
    with `+`, `-`, a space, or `\\` — a line beginning `@@` cannot be
    content, so the split is unambiguous.
    """
    current: list[str] | None = None
    out: list[list[str]] = []
    for line in patch.splitlines():
        if line.startswith("@@"):
            if current is not None:
                out.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        out.append(current)
    return ["\n".join(h) for h in out]


def hash_hunk(hunk: str) -> str:
    """sha256 hex over the hunk's `+` and `-` lines only, newline-joined.

    Exclusions are the point: the `@@` header (line numbers and section
    heading), context lines (leading space), and `\\ No newline at end of
    file` markers all vary under edits elsewhere in the file. Only the
    changed lines are this hunk's own content.
    """
    changed = [
        line
        for line in hunk.splitlines()
        if (line.startswith("+") or line.startswith("-")) and not line.startswith("@@")
    ]
    return hashlib.sha256(
        "\n".join(changed).encode("utf-8", "surrogateescape")
    ).hexdigest()


def index_from_patches(patches: dict[str, str]) -> dict[str, list[str]]:
    """{path: ordered hunk-hash list} over per-file patch texts.

    The value is a multiset carried as a list: duplicates are kept because
    COUNT matching upstream depends on them, and order is kept so a stored
    index is byte-stable for replay. An empty patch yields a PRESENT key
    with `[]` — absence means "never sent", and only the caller knows that.
    """
    return {
        path: [hash_hunk(h) for h in split_hunks(patch)]
        for path, patch in patches.items()
    }
