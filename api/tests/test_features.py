from doug import features
from doug.features import extract_features
from doug.models import AuthorType, PRMetadata


def _pr(**kw) -> PRMetadata:
    base = dict(number=1, title="t", author="dev")
    base.update(kw)
    return PRMetadata.model_validate(base)


def test_migration_detected_by_path():
    f = extract_features(_pr(files=["migrations/0001_init.sql"]))
    assert f.migration


def test_schema_dir_counts_as_migration():
    f = extract_features(_pr(files=["db/schema/users.rb"]))
    assert f.migration


def test_sensitive_path_segment():
    f = extract_features(_pr(files=["auth/session/context.go"]))
    assert f.sensitive_path


def test_sensitive_accesscontrol_and_rbac():
    assert extract_features(_pr(files=["pkg/services/accesscontrol/api.go"])).sensitive_path
    assert extract_features(_pr(files=["pkg/services/rbac/roles.go"])).sensitive_path


def test_sensitive_filename_substring():
    # grafana#123834 — secrets in the filename, not as a directory segment.
    assert extract_features(
        _pr(files=["pkg/setting/setting_secrets_manager.go"])
    ).sensitive_path


def test_sensitive_requires_whole_segment():
    # "authors" contains "auth" but is not an auth path.
    f = extract_features(_pr(files=["blog/authors/list.py"]))
    assert not f.sensitive_path


def test_lockfile_and_manifest():
    f = extract_features(_pr(files=["package.json", "package-lock.json"]))
    assert f.lockfile
    assert f.manifest


def test_test_files_counted():
    f = extract_features(_pr(files=["a_test.go", "src/app.spec.ts", "lib/core.py"]))
    assert f.test_files == 2
    assert f.code_files == 1


def test_bot_suffix_counts_as_agent():
    f = extract_features(_pr(author="patchbot[bot]", author_type=AuthorType.HUMAN))
    assert f.agent_authored


def test_runtime_dep_and_hotspot_and_config_flag():
    f = extract_features(
        _pr(
            title="Bump py deps",
            files=[
                "pyproject.toml",
                "src/sentry/preprod/api.py",
                "src/sentry/features/temporary.py",
            ],
        )
    )
    assert f.runtime_dep
    assert f.hotspot_path
    assert f.config_flag
    assert not f.dev_tool_dep


def test_dev_tool_title_detected():
    f = extract_features(_pr(title="chore(ui): Upgrade jest to 30.4", files=["package.json"]))
    assert f.dev_tool_dep


# --- v4 light-diff features --------------------------------------------------


def test_refactor_title_detected():
    pr = PRMetadata(number=1, title="ref(modal): use standard backdrop", author="d")
    assert extract_features(pr).refactor_title


def test_plain_fix_title_is_not_refactor():
    pr = PRMetadata(number=1, title="fix(api): handle null repo", author="d")
    assert not extract_features(pr).refactor_title


def test_pure_modification_requires_known_statuses():
    # files_modified unknown (old cache / no details fetched) must never
    # count as pure modification — unknown is never guessed as a signal.
    pr = PRMetadata(number=1, title="t", author="d", files=["a.py"], additions=30)
    assert not extract_features(pr).pure_modification


def test_pure_modification_all_files_modified():
    pr = PRMetadata(
        number=1, title="t", author="d", files=["a.py", "b.py"],
        additions=25, deletions=5, files_added=0, files_modified=2,
    )
    assert extract_features(pr).pure_modification


def test_new_file_breaks_pure_modification():
    pr = PRMetadata(
        number=1, title="t", author="d", files=["a.py", "b.py"],
        additions=25, deletions=5, files_added=1, files_modified=1,
    )
    assert not extract_features(pr).pure_modification


def test_deletion_leaning():
    pr = PRMetadata(number=1, title="t", author="d", additions=10, deletions=40)
    assert extract_features(pr).deletion_leaning


def test_small_deletions_not_deletion_leaning():
    pr = PRMetadata(number=1, title="t", author="d", additions=2, deletions=8)
    assert not extract_features(pr).deletion_leaning


def test_committed_data_under_docs_routes_as_prose_but_real_config_does_not(monkeypatch):
    """Evidence fixtures under docs/ are things a review reads ABOUT, not
    program text it reasons OVER — the same argument the docstring already
    makes for lockfiles.

    They reached tier 0 because the prose suffix list stops at .md/.txt/.rst.
    That is not merely a mislabel: read_order sorts (tier, len(patch))
    ascending, so a large fixture sorted last inside tier 0 and became the
    likeliest file to be cut, displacing code that would otherwise have fit.
    Measured on the 30 first-parent commits ending 2026-08-23 — 6fa1633
    reported a code-tier miss whose only "code" files were the two below, on a
    429,126-char diff (issue #182).

    The negatives are the load-bearing half. The rule is scoped to the docs/
    ROOT, not to the suffix, because .json is also how real config ships. A
    suffix rule would demote package.json, tsconfig.json and every migration
    fixture — trading a routing bug for a much worse one. web/docs/ is
    deliberately NOT covered: this names the repo's documentation root, not any
    directory that happens to be called docs.
    """
    assert features._is_prose("docs/design/walked-out/phase0_units.json")
    assert features._is_prose("docs/design/walked-out/span-verification/barb_evidence.json")
    assert features._is_prose("docs/findings-log.jsonl")
    assert features._is_prose("docs/data/measurements.CSV")  # case-insensitive

    assert not features._is_prose("web/package.json")
    assert not features._is_prose("tsconfig.json")
    assert not features._is_prose("api/tests/fixtures/data.json")
    assert not features._is_prose("web/docs/thing.json")
    assert not features._is_prose("docs/scripts/gen.py")

    # docs/ is not a private directory. Doug reviews other people's repos,
    # where a published contract under docs/ is load-bearing config — demoting
    # it would cut a customer's API surface out of the read without notice.
    # The first draft of this rule reasoned only from THIS repo's layout, which
    # Doug flagged on b767f2e. These stay tier 0 wherever they live.
    assert not features._is_prose("docs/openapi.json")
    assert not features._is_prose("docs/api/openapi.v2.json")   # versioned stem
    assert not features._is_prose("docs/reference/swagger.json")
    assert not features._is_prose("docs/schema.yaml")
    assert not features._is_prose("docs/graphql.json")
    # ...but a contract-shaped WORD inside a longer name is not a contract.
    assert features._is_prose("docs/design/schema-migration-notes.json")

    # Routing only, asserted as a property rather than trusted. ADR-0012's
    # tiering decides which files reach the model, never what the score says,
    # and the docstring's "routing-only exceptions" claim is only true while
    # extract_features does not consult this helper. Breaking _is_prose
    # entirely must leave the features byte-identical; if this ever fails, a
    # routing change has silently become a scoring change.
    files = ["docs/design/walked-out/phase0_units.json", "api/doug/tenancy.py"]
    real = extract_features(_pr(files=files))
    monkeypatch.setattr(features, "_is_prose", lambda path: True)
    assert extract_features(_pr(files=files)) == real
    monkeypatch.setattr(features, "_is_prose", lambda path: False)
    assert extract_features(_pr(files=files)) == real


def test_prose_covers_docs_and_lockfiles_but_not_their_manifests():
    """The reader is asked for logic errors, unsafe migrations, concurrency
    hazards, error-handling gaps and contract mismatches (reader.SYSTEM).
    The accepted routing policy ranks prose and generated lockfiles after
    code and tests for that review task.

    A manifest carries real dependency decisions, including conventional
    requirements/constraints variants and CMake's build file despite their
    suffix. These files stay code."""
    assert features._is_prose("docs/design/outcome-loop/ROADMAP.md")
    assert features._is_prose("README.rst")
    assert features._is_prose("notes.txt")
    assert features._is_prose("web/package-lock.json")
    assert features._is_prose("uv.lock")
    assert features._is_prose("api/CHANGELOG.MD")  # case-insensitive

    assert not features._is_prose("web/package.json")
    assert not features._is_prose("api/pyproject.toml")
    assert not features._is_prose("api/requirements.txt")
    assert not features._is_prose("api/requirements-dev.txt")
    assert not features._is_prose("api/constraints.txt")
    assert not features._is_prose("native/CMakeLists.txt")
    assert not features._is_prose("api/doug/tenancy.py")
    assert not features._is_prose("api/deploy/gcp.sh")

    cmake = extract_features(_pr(files=["native/CMakeLists.txt"]))
    assert not cmake.manifest
    assert not cmake.runtime_dep
    assert not cmake.dep_only
