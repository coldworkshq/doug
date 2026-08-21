"""Tests for doug.hunks — the content-hash index over unified hunks.

Intent (design-lock, Walked Out): a hunk's identity is its +/- lines and
nothing else. Line numbers move when unrelated code above shifts; context
lines change when neighbors change; neither is evidence about THIS change.
If the hash ever starts reading them, by-construction carry-forward breaks
on every rebase — these tests are what fails first.
"""

from doug import hunks, reader

PATCH_A = (
    "@@ -10,7 +10,8 @@ def f():\n"
    " ctx_before\n"
    "-old_line\n"
    "+new_line\n"
    "+added_line\n"
    " ctx_after\n"
)

# Same +/- lines: shifted @@ numbers, different function context, different
# context lines. The change itself is byte-identical.
PATCH_A_SHIFTED = (
    "@@ -110,6 +110,7 @@ def other():\n"
    " different_ctx_before\n"
    "-old_line\n"
    "+new_line\n"
    "+added_line\n"
    " different_ctx_after\n"
    "\\ No newline at end of file\n"
)

PATCH_B = (
    "@@ -10,7 +10,8 @@ def f():\n"
    " ctx_before\n"
    "-old_line\n"
    "+entirely_different\n"
    " ctx_after\n"
)


def test_hash_ignores_hunk_header_numbers_and_context():
    ha = [hunks.hash_hunk(h) for h in hunks.split_hunks(PATCH_A)]
    hb = [hunks.hash_hunk(h) for h in hunks.split_hunks(PATCH_A_SHIFTED)]
    assert ha == hb
    assert len(ha) == 1


def test_hash_reads_the_changed_lines():
    ha = [hunks.hash_hunk(h) for h in hunks.split_hunks(PATCH_A)]
    hb = [hunks.hash_hunk(h) for h in hunks.split_hunks(PATCH_B)]
    assert ha != hb


def test_split_hunks_ignores_git_file_headers():
    # git-diff text carries diff --git/index/---/+++ before the first @@;
    # GitHub patch fields do not. One parser must serve both (the eval's
    # index_from_git feeds git text through the same functions).
    git_text = (
        "diff --git a/x.py b/x.py\n"
        "index 111..222 100644\n"
        "--- a/x.py\n"
        "+++ b/x.py\n" + PATCH_A + PATCH_B
    )
    assert [hunks.hash_hunk(h) for h in hunks.split_hunks(git_text)] == [
        hunks.hash_hunk(h) for h in hunks.split_hunks(PATCH_A + PATCH_B)
    ]


def test_multiset_keeps_duplicates():
    # Two byte-identical hunks are two entries — COUNT matching upstream
    # depends on the multiset, not a set.
    two = hunks.split_hunks(PATCH_A + PATCH_A)
    assert len(two) == 2
    assert hunks.hash_hunk(two[0]) == hunks.hash_hunk(two[1])


def test_empty_patch_is_an_empty_list():
    # A sent file with an empty delta has a PRESENT key with [] upstream;
    # absent-key-means-unseen only works if empty really is [].
    assert hunks.split_hunks("") == []


def test_index_from_patches():
    idx = hunks.index_from_patches({"a.py": PATCH_A, "b.py": PATCH_B, "c.py": ""})
    assert set(idx) == {"a.py", "b.py", "c.py"}
    assert idx["a.py"] == [hunks.hash_hunk(h) for h in hunks.split_hunks(PATCH_A)]
    assert idx["c.py"] == []
    # 64-hex sha256, so a stored index is self-describing about its function
    assert all(len(h) == 64 for hs in idx.values() for h in hs)


# --- Coverage.hunks: the index is over the SENT slice only -----------------


def _diff(*files):
    return reader.CHUNK_SEPARATOR.join(
        reader.diff_chunk(name, "modified", 1, 1, patch) for name, patch in files
    )


def test_index_over_sent_slice_only():
    d = _diff(("a.py", PATCH_A), ("b.py", PATCH_B), ("c.py", PATCH_A))
    # Budget lands inside b.py: a.py is whole, b.py is the cut file, c.py unseen.
    header_b = d.index("### b.py")
    cov = reader.coverage(d, budget=header_b + 40)
    assert cov.file_cut == "b.py"
    assert cov.hunks is not None
    assert set(cov.hunks) == {"a.py"}          # cut file absent, unseen absent
    assert cov.hunks["a.py"] == [hunks.hash_hunk(h) for h in hunks.split_hunks(PATCH_A)]


def test_index_complete_read_covers_every_file():
    d = _diff(("a.py", PATCH_A), ("b.py", PATCH_B))
    cov = reader.coverage(d)
    assert cov.complete
    assert set(cov.hunks) == {"a.py", "b.py"}


def test_clean_between_files_cut_keeps_the_last_whole_file():
    d = _diff(("a.py", PATCH_A), ("b.py", PATCH_B))
    # Budget ends exactly at a.py's content end: no file is cut, a.py whole.
    a_end = d.index("### b.py") - len(reader.CHUNK_SEPARATOR)
    cov = reader.coverage(d, budget=a_end)
    assert cov.file_cut is None
    assert set(cov.hunks) == {"a.py"}


def test_hunk_index_is_coverages_index_verbatim():
    d = _diff(("a.py", PATCH_A), ("b.py", PATCH_B))
    assert reader.hunk_index(d) == reader.coverage(d).hunks
