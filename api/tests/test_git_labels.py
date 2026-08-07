from doug.backtest.git_labels import (
    Commit,
    parse_revert_targets,
    parse_revert_targets_dated,
    parse_revert_targets_evidenced,
    pr_numbers_by_sha,
    pr_titles_from_subjects,
)


def test_squash_title_map_ignores_reverts_and_merges():
    subjects = [
        "Add rate limiter (#40)",
        'Revert "Add rate limiter" (#44)',
        "Merge pull request #99 from alice/branch",
        "Fix typo (#41)",
    ]
    assert pr_titles_from_subjects(subjects) == {
        "Add rate limiter": 40,
        "Fix typo": 41,
    }


def test_title_map_keeps_newest_on_collision():
    # git log order: newest first.
    subjects = [
        "Fix flaky test (#300)",
        "Fix flaky test (#100)",
    ]
    assert pr_titles_from_subjects(subjects)["Fix flaky test"] == 300


def test_quoted_title_resolves_via_map():
    subjects = [
        "Add rate limiter (#40)",
        'Revert "Add rate limiter" (#44)',
    ]
    titles = pr_titles_from_subjects(subjects)
    assert parse_revert_targets(subjects, titles) == {40}


def test_quoted_title_with_inner_pr_number():
    subjects = [
        'Revert "Add caching (#100)" (#101)',
    ]
    assert parse_revert_targets(subjects, {}) == {100}


def test_trailing_paren_on_quoted_revert_is_not_the_target():
    subjects = ['Revert "Something vague" (#99)']
    assert parse_revert_targets(subjects, {}) == set()


def test_bare_hash_revert():
    subjects = ["Revert #7, broke prod"]
    assert parse_revert_targets(subjects, {}) == {7}


def test_feature_pr_titled_revert_to_is_not_a_label():
    subjects = ["Revert to legacy config (#77)"]
    assert parse_revert_targets(subjects, {}) == set()
    # Still a normal shippable PR — belongs in the title map.
    assert pr_titles_from_subjects(subjects)["Revert to legacy config"] == 77


def test_see_issue_ref_on_revert_line_is_not_a_target():
    subjects = ["Revert workaround for slow CI, see #456"]
    assert parse_revert_targets(subjects, {}) == set()


def test_non_revert_subjects_ignored():
    subjects = [
        "Follow-up similar to #1 (#2)",
        "Ship feature (#3)",
    ]
    assert parse_revert_targets(subjects, pr_titles_from_subjects(subjects)) == set()


def test_dated_targets_report_when_the_label_became_knowable():
    # git log is newest-first.
    entries = [
        Commit(date="2026-05-01T00:00:00+00:00", subject='Revert "Add rate limiter" (#44)'),
        Commit(date="2026-01-02T00:00:00+00:00", subject="Add rate limiter (#40)"),
    ]
    titles = pr_titles_from_subjects([c.subject for c in entries])
    assert parse_revert_targets_dated(entries, titles) == {
        40: "2026-05-01T00:00:00+00:00"
    }


def test_dated_targets_keep_the_earliest_revert():
    # A re-revert (re-land, then revert again) must not push the label's
    # knowable-from date later — the first revert is when we could have known.
    entries = [
        Commit(date="2026-06-01T00:00:00+00:00", subject='Revert "Add caching (#100)" (#103)'),
        Commit(date="2026-03-01T00:00:00+00:00", subject='Revert "Add caching (#100)" (#101)'),
    ]
    dated = parse_revert_targets_dated(entries, {})
    assert dated == {100: "2026-03-01T00:00:00+00:00"}


def test_undated_wrapper_still_returns_bare_numbers():
    subjects = ["Add rate limiter (#40)", 'Revert "Add rate limiter" (#44)']
    assert parse_revert_targets(subjects, pr_titles_from_subjects(subjects)) == {40}


# --- sha-based revert resolution ------------------------------------------
# Grafana-style reverts quote a title with no PR number, so the title map is
# the only fallback and it misses 36% of them. `This reverts commit <sha>` is
# in 75% of those bodies and resolves exactly.


def test_sha_resolves_revert_whose_subject_has_no_number():
    commits = [
        Commit(
            sha="b" * 40,
            date="2026-05-01T00:00:00+00:00",
            subject='Revert "Wire up config metrics correctly"',
            body="This reverts commit " + "a" * 40 + ".",
        ),
        Commit(
            sha="a" * 40,
            date="2026-01-02T00:00:00+00:00",
            subject="Wire up config metrics (#77)",
        ),
    ]
    # Title map cannot help — the quoted title differs from the PR title.
    assert parse_revert_targets_dated(commits, {}) == {77: "2026-05-01T00:00:00+00:00"}


def test_abbreviated_sha_resolves():
    full = "c" * 40
    commits = [
        Commit(sha="d" * 40, date="2026-05-01T00:00:00+00:00",
               subject='Revert "Thing"', body=f"This reverts commit {full[:8]}."),
        Commit(sha=full, date="2026-01-01T00:00:00+00:00", subject="Thing (#5)"),
    ]
    assert parse_revert_targets_dated(commits, {}) == {5: "2026-05-01T00:00:00+00:00"}


def test_ambiguous_sha_prefix_is_not_guessed():
    # Two commits share a 7-char prefix; resolving either would be a coin flip.
    commits = [
        Commit(sha="e" * 40, date="2026-05-01T00:00:00+00:00",
               subject='Revert "Thing"', body="This reverts commit " + "f" * 7 + "."),
        Commit(sha="f" * 7 + "1" * 33, date="2026-01-01T00:00:00+00:00", subject="A (#1)"),
        Commit(sha="f" * 7 + "2" * 33, date="2026-01-01T00:00:00+00:00", subject="B (#2)"),
    ]
    assert parse_revert_targets_dated(commits, {}) == {}


def test_sha_of_a_commit_with_no_pr_number_resolves_nothing():
    commits = [
        Commit(sha="1" * 40, date="2026-05-01T00:00:00+00:00",
               subject='Revert "Direct push"', body="This reverts commit " + "2" * 40 + "."),
        Commit(sha="2" * 40, date="2026-01-01T00:00:00+00:00", subject="Direct push, no PR"),
    ]
    assert parse_revert_targets_dated(commits, {}) == {}


def test_body_marker_alone_is_not_treated_as_a_revert():
    # "Reland X" carries the marker but is the opposite of a revert.
    commits = [
        Commit(sha="3" * 40, date="2026-05-01T00:00:00+00:00",
               subject="Reland: Add caching", body="This reverts commit " + "4" * 40 + "."),
        Commit(sha="4" * 40, date="2026-01-01T00:00:00+00:00", subject="Revert caching (#9)"),
    ]
    assert parse_revert_targets_dated(commits, {}) == {}


def test_the_evidenced_variant_keeps_the_reverting_commit_the_dated_one_drops():
    # The receipt is promised a revert sha (product-spec.md:39) and
    # parse_revert_targets_dated returns only a date. Live-≡-backtest
    # equivalence for this variant, and the instant/tie-break amendments it
    # carries, are pinned in test_adjudicate.py.
    revert = Commit(sha="7" * 40, date="2026-05-01T00:00:00+00:00",
                    subject='Revert "Wire up config metrics correctly"',
                    body="This reverts commit " + "8" * 40 + ".")
    commits = [revert, Commit(sha="8" * 40, date="2026-01-02T00:00:00+00:00",
                              subject="Wire up config metrics (#77)")]
    assert parse_revert_targets_evidenced(commits, {}) == {77: revert}


def test_pr_numbers_by_sha_maps_only_squash_subjects():
    commits = [
        Commit(sha="a" * 40, subject="Add thing (#12)"),
        Commit(sha="b" * 40, subject="Direct commit, no PR"),
    ]
    assert pr_numbers_by_sha(commits) == {"a" * 40: 12}
