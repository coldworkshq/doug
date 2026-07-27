from magpie.features import extract_features
from magpie.models import AuthorType, PRMetadata


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
