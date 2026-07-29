from doug.backtest.git_labels import (
    parse_revert_targets,
    parse_revert_targets_dated,
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
        ("2026-05-01T00:00:00+00:00", 'Revert "Add rate limiter" (#44)'),
        ("2026-01-02T00:00:00+00:00", "Add rate limiter (#40)"),
    ]
    titles = pr_titles_from_subjects([s for _, s in entries])
    assert parse_revert_targets_dated(entries, titles) == {
        40: "2026-05-01T00:00:00+00:00"
    }


def test_dated_targets_keep_the_earliest_revert():
    # A re-revert (re-land, then revert again) must not push the label's
    # knowable-from date later — the first revert is when we could have known.
    entries = [
        ("2026-06-01T00:00:00+00:00", 'Revert "Add caching (#100)" (#103)'),
        ("2026-03-01T00:00:00+00:00", 'Revert "Add caching (#100)" (#101)'),
    ]
    dated = parse_revert_targets_dated(entries, {})
    assert dated == {100: "2026-03-01T00:00:00+00:00"}


def test_undated_wrapper_still_returns_bare_numbers():
    subjects = ["Add rate limiter (#40)", 'Revert "Add rate limiter" (#44)']
    assert parse_revert_targets(subjects, pr_titles_from_subjects(subjects)) == {40}
