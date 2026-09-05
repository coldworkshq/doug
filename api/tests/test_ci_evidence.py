"""Which gates ran green at head (#307) — the workflow parse, the check-run
match, and the ruff-configuration walk. Every miss must fall on the side
that keeps a finding published."""

from doug import ci_evidence as ci
from doug.ci_evidence import CheckResult, Job, Step

DOUG_CI = """\
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  api:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: api
    steps:
      # Full history: a comment between steps.
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run pytest

  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: npm ci
      - run: npm run lint --workspace=web
      - run: npm test --workspace=web
      - run: npm run build --workspace=web

  api-image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: docker build -t doug-api-candidate api
      - name: The image carries the binaries its workloads shell out to
        run: docker run --rm doug-api-candidate git --version
"""


def _check(name, conclusion="success", app="github-actions"):
    return CheckResult(name=name, conclusion=conclusion, app=app)


# ---------------------------------------------------------------------------
# The parser.


def test_parses_dougs_own_workflow():
    jobs = {j.check_name: j for j in ci.parse_workflow(DOUG_CI)}
    assert set(jobs) == {"api", "web", "api-image"}
    api = jobs["api"]
    assert [s.command for s in api.steps] == [
        "uv sync --locked",
        "uv run ruff check .",
        "uv run pytest",
    ]
    # `defaults.run.working-directory` reaches every step of the job.
    assert {s.working_directory for s in api.steps} == {"api"}
    web = jobs["web"]
    assert {s.working_directory for s in web.steps} == {""}
    assert "docker run --rm doug-api-candidate git --version" in [
        s.command for s in jobs["api-image"].steps
    ]


def test_job_name_overrides_key_and_an_expression_leaves_the_job_unnamed():
    text = """\
jobs:
  lint:
    name: "Lint (python)"
    steps:
      - run: ruff check .
  test:
    name: test ${{ matrix.os }}
    steps:
      - run: pytest
"""
    jobs = ci.parse_workflow(text)
    assert [j.check_name for j in jobs] == ["Lint (python)"]


def test_matrix_jobs_are_marked_and_reusable_workflows_are_skipped():
    text = """\
jobs:
  test:
    strategy:
      matrix:
        python: ["3.12", "3.13"]
    steps:
      - run: ruff check .
  shared:
    uses: org/repo/.github/workflows/x.yml@main
"""
    jobs = ci.parse_workflow(text)
    assert [(j.check_name, j.matrix) for j in jobs] == [("test", True)]


def test_block_scalar_run_and_step_level_working_directory():
    text = """\
defaults:
  run:
    working-directory: services
jobs:
  build:
    steps:
      - name: Build it
        run: |
          npm ci
          npm run build
        working-directory: services/web
      - run: >
          ruff check
          .
"""
    (job,) = ci.parse_workflow(text)
    assert job.steps[0] == Step(command="npm ci\nnpm run build", working_directory="services/web")
    # Workflow-level default applies when the step names none.
    assert job.steps[1] == Step(command="ruff check\n.", working_directory="services")


def test_a_working_directory_expression_drops_the_step_not_the_job():
    text = """\
jobs:
  build:
    steps:
      - run: npm run build
        working-directory: ${{ matrix.dir }}
      - run: ruff check .
"""
    (job,) = ci.parse_workflow(text)
    assert [s.command for s in job.steps] == ["ruff check ."]


def test_comments_and_quotes_inside_commands():
    text = """\
jobs:
  j:
    steps:
      - run: echo "# not a comment" # a real one
      - run: 'ruff check src'
"""
    (job,) = ci.parse_workflow(text)
    assert [s.command for s in job.steps] == ['echo "# not a comment"', "ruff check src"]


def test_garbage_parses_to_nothing():
    assert ci.parse_workflow("") == []
    assert ci.parse_workflow("just a line") == []
    assert ci.parse_workflow("jobs: nope") == []
    assert ci.parse_workflow("jobs:\n  - a\n  - b\n") == []


# ---------------------------------------------------------------------------
# Falsifier kinds and roots.


def test_kinds_of_commands():
    assert ci.kinds_of("uv run ruff check .") == {ci.RUFF}
    assert ci.kinds_of("ruff format .") == set()
    assert ci.kinds_of("npm run lint --workspace=web") == {ci.JS_LINT}
    assert ci.kinds_of("npx eslint .") == {ci.JS_LINT}
    assert ci.kinds_of("npm run build --workspace=web") == {ci.JS_BUILD}
    assert ci.kinds_of("npx tsc --noEmit") == {ci.JS_BUILD}
    assert ci.kinds_of("pnpm build") == {ci.JS_BUILD}
    assert ci.kinds_of("yarn lint && yarn build") == {ci.JS_LINT, ci.JS_BUILD}
    assert ci.kinds_of("uv run pytest") == set()
    assert ci.kinds_of("docker build -t x api") == set()


def test_evidence_scopes_a_green_kind_to_the_roots_it_ran_over():
    jobs = ci.parse_workflow(DOUG_CI)
    ev = ci.evidence(jobs, [_check("api"), _check("web"), _check("api-image")])
    assert ev.settled_by == {
        ci.RUFF: ("api",),
        ci.JS_LINT: ("web",),
        ci.JS_BUILD: ("web",),
    }
    assert ev.covers(ci.RUFF, "api/doug/worker.py")
    # ruff ran in api/; a script outside it was never checked.
    assert not ev.covers(ci.RUFF, "scripts/probe.py")
    # `--workspace=web` narrows the root to web/, so console/ is uncovered.
    assert ev.covers(ci.JS_BUILD, "web/app/page.tsx")
    assert not ev.covers(ci.JS_BUILD, "console/app/page.tsx")
    assert not ev.covers(ci.JS_LINT, "console/app/page.tsx")


def test_every_job_of_a_kind_must_be_green():
    jobs = [
        Job("web", (Step("npm run build --workspace=web", ""),)),
        Job("console", (Step("npm run build --workspace=console", ""),)),
    ]
    green = ci.evidence(jobs, [_check("web"), _check("console")])
    assert green.covers(ci.JS_BUILD, "web/x.ts")
    # One red build makes the kind not-green everywhere, including the
    # workspace whose own job passed: "all green" means all.
    red = ci.evidence(jobs, [_check("web"), _check("console", conclusion="failure")])
    assert not red.green(ci.JS_BUILD)
    pending = ci.evidence(jobs, [_check("web"), _check("console", conclusion=None)])
    assert not pending.green(ci.JS_BUILD)
    missing = ci.evidence(jobs, [_check("web")])
    assert not missing.green(ci.JS_BUILD)


def test_only_github_actions_check_runs_count():
    jobs = [Job("api", (Step("ruff check .", ""),))]
    other_app = ci.evidence(jobs, [_check("api", app="some-other-bot")])
    assert not other_app.green(ci.RUFF)


def test_matrix_check_runs_match_by_prefix_only_for_matrix_jobs():
    matrix = [Job("test", (Step("ruff check .", ""),), matrix=True)]
    assert ci.evidence(matrix, [_check("test (3.12)"), _check("test (3.13)")]).green(ci.RUFF)
    assert not ci.evidence(
        matrix, [_check("test (3.12)"), _check("test (3.13)", conclusion="failure")]
    ).green(ci.RUFF)
    plain = [Job("test", (Step("ruff check .", ""),))]
    assert not ci.evidence(plain, [_check("test (3.12)")]).green(ci.RUFF)


def test_two_workflows_sharing_a_job_name_need_both_green():
    jobs = [
        Job("test", (Step("ruff check .", ""),)),
        Job("test", (Step("pytest", ""),)),
    ]
    checks = [_check("test"), _check("test", conclusion="failure")]
    assert not ci.evidence(jobs, checks).green(ci.RUFF)


def test_a_pnpm_filter_names_a_package_not_a_directory():
    jobs = [Job("build", (Step("pnpm build --filter web", ""),))]
    ev = ci.evidence(jobs, [_check("build")])
    assert ev.green(ci.JS_BUILD)
    # Green, but with no root it can state — so it covers nothing.
    assert not ev.covers(ci.JS_BUILD, "web/x.ts")
    # A flag between the tool and the script is a form the matcher does not
    # read, which is the safe miss: no kind, no evidence, finding kept.
    assert ci.kinds_of("pnpm --filter web build") == set()


# ---------------------------------------------------------------------------
# Does ruff, as configured at head, report F821 here?


def _fs(files: dict[str, str]):
    return lambda path: files.get(path)


def test_no_config_anywhere_means_ruffs_defaults_which_select_f():
    assert ci.f821_selected("api/doug/x.py", _fs({})) is True


def test_nearest_config_governs_and_pyproject_without_tool_ruff_is_skipped():
    files = {
        "pyproject.toml": '[tool.ruff]\nlint.select = ["E"]\n',
        "api/pyproject.toml": "[project]\nname = 'api'\n",
    }
    # api/pyproject.toml has no [tool.ruff]; the root config governs and
    # selects only E.
    assert ci.f821_selected("api/doug/x.py", _fs(files)) is False
    files["api/ruff.toml"] = 'select = ["F"]\n'
    assert ci.f821_selected("api/doug/x.py", _fs(files)) is True
    # .ruff.toml beats ruff.toml in the same directory.
    files["api/.ruff.toml"] = 'select = ["E"]\n'
    assert ci.f821_selected("api/doug/x.py", _fs(files)) is False


def test_select_prefixes_and_ignores():
    def with_lint(body):
        return _fs({"pyproject.toml": f"[tool.ruff.lint]\n{body}"})

    assert ci.f821_selected("x.py", with_lint('select = ["F8"]\n')) is True
    assert ci.f821_selected("x.py", with_lint('select = ["F821"]\n')) is True
    assert ci.f821_selected("x.py", with_lint('select = ["ALL"]\n')) is True
    assert ci.f821_selected("x.py", with_lint('select = ["E"]\nextend-select = ["F"]\n')) is True
    assert ci.f821_selected("x.py", with_lint('select = ["F"]\nignore = ["F821"]\n')) is False
    assert ci.f821_selected("x.py", with_lint('select = ["F"]\nextend-ignore = ["F8"]\n')) is False
    # Top-level (deprecated) keys still count.
    top_level = _fs({"pyproject.toml": '[tool.ruff]\nselect = ["E"]\n'})
    assert ci.f821_selected("x.py", top_level) is False


def test_exclude_and_per_file_ignores_keep_the_finding():
    cfg = (
        '[tool.ruff]\nexclude = ["generated/"]\n'
        '[tool.ruff.lint.per-file-ignores]\n"scripts/*" = ["F821"]\n"tests/*" = ["E501"]\n'
    )
    fs = _fs({"pyproject.toml": cfg})
    assert ci.f821_selected("generated/model.py", fs) is False
    assert ci.f821_selected("scripts/probe.py", fs) is False
    assert ci.f821_selected("tests/test_x.py", fs) is True
    assert ci.f821_selected("src/x.py", fs) is True
    # ruff's default excludes apply with no config at all.
    assert ci.f821_selected("build/lib/x.py", _fs({})) is False
    assert ci.f821_selected("node_modules/x/y.py", _fs({})) is False


def test_an_extending_or_unparseable_config_cannot_tell():
    assert ci.f821_selected("x.py", _fs({"ruff.toml": 'extend = "../base.toml"\n'})) is None
    assert ci.f821_selected("x.py", _fs({"ruff.toml": "select = [\n"})) is None


# ---------------------------------------------------------------------------
# Doug's own reads of #314, each turned into a pin.


def test_a_line_the_subset_cannot_read_unreads_the_whole_document():
    """First read, `reader:fragile-parser`: a merge key used to truncate the
    job's mapping silently, keeping the steps before it and losing the
    working-directory after it — a mis-parse that settles wrongly. Now the
    workflow yields nothing."""
    merge_key = """\
jobs:
  api:
    steps:
      - run: ruff check .
    <<: *defaults
    defaults:
      run:
        working-directory: api
"""
    assert ci.parse_workflow(merge_key) == []
    for text in (
        "jobs:\n  api: &shared\n    steps:\n      - run: ruff check .\n",
        "jobs:\n  api:\n    steps: *steps\n",
        "jobs:\n  api:\n    steps:\n      - run: ruff check .\n    tagged: !!str x\n",
        "jobs:\n  api:\n    steps:\n      - run: ruff check .\n      bare scalar line\n",
    ):
        assert ci.parse_workflow(text) == [], text


def test_the_parser_terminates_and_never_raises_on_mangled_input():
    """Second read, `reader:parser-infinite-loop` and
    `reader:unhandled-exception-in-optional-path`: every loop either
    advances or returns, and every exception the subset can raise is
    caught. Pinned by mangling the real workflow a few hundred ways."""
    import random

    rng = random.Random(314)
    lines = DOUG_CI.splitlines()
    junk = [
        "- ", ":", "  - run:", "jobs:", "<<: *x", "&a", "*a", "  |", "  >", "\t",
        "- - -", "key: [", "{",
    ]  # fmt: skip
    for _ in range(400):
        mangled = list(lines)
        for _ in range(rng.randint(1, 6)):
            op = rng.randrange(4)
            at = rng.randrange(len(mangled))
            if op == 0:
                mangled[at] = " " * rng.randint(0, 12) + mangled[at].lstrip()
            elif op == 1:
                mangled.insert(at, " " * rng.randint(0, 10) + rng.choice(junk))
            elif op == 2:
                del mangled[at]
            else:
                other = -1 - at % len(mangled)
                mangled[at], mangled[other] = mangled[other], mangled[at]
        result = ci.parse_workflow("\n".join(mangled))
        assert isinstance(result, list)


def test_conditional_and_tolerated_steps_are_not_evidence():
    """Second read, `reader:false-settlement`: a job concludes success with
    an `if:` step skipped or a `continue-on-error` step failed."""
    text = """\
jobs:
  api:
    steps:
      - run: ruff check .
        if: github.event_name == 'push'
      - run: npm run lint
        continue-on-error: true
      - run: npm run build
  tolerated:
    continue-on-error: true
    steps:
      - run: ruff check .
"""
    jobs = ci.parse_workflow(text)
    assert [(j.check_name, [s.command for s in j.steps]) for j in jobs] == [
        ("api", ["npm run build"])
    ]


def test_explicit_paths_narrow_the_root_and_unknown_flags_remove_it():
    """First read, both `reader:over-broad-heuristic` findings: `ruff check
    api/doug` at the root checked api/doug and nothing else; `ruff check
    --select E .` reports something other than the configuration says."""

    def roots(command, wd=""):
        ev = ci.evidence([Job("j", (Step(command, wd),))], [_check("j")])
        return ev.roots

    assert roots("uv run ruff check api/doug scripts/x.py") == {
        ci.RUFF: ("api/doug", "scripts/x.py")
    }
    assert roots("uv run ruff check .", wd="api") == {ci.RUFF: ("api",)}
    assert roots("uv run ruff check doug", wd="api") == {ci.RUFF: ("api/doug",)}
    assert roots("ruff check --no-cache -q --output-format=github .") == {ci.RUFF: ("",)}
    for flagged in (
        "ruff check --select E .",
        "ruff check --ignore F821 .",
        "ruff check --config ruff.toml .",
        "ruff check --exit-zero .",
        "ruff check --extend-select B .",
        "ruff format .",  # not a check at all
    ):
        assert roots(flagged) in ({ci.RUFF: ()}, {}), flagged
    # eslint reads the same way; a scripted lint keeps the workspace rule.
    assert roots("npx eslint web/src") == {ci.JS_LINT: ("web/src",)}
    assert roots("npx eslint --max-warnings=0 .") == {ci.JS_LINT: ("",)}
    assert roots("npx eslint --ext .ts .") == {ci.JS_LINT: ()}
    assert roots("npm run lint --workspace=web") == {ci.JS_LINT: ("web",)}
    # Several commands in one step are read one at a time.
    assert roots("uv sync && uv run ruff check api/doug\nnpm run build -w web") == {
        ci.RUFF: ("api/doug",),
        ci.JS_BUILD: ("web",),
    }
    ev = ci.evidence([Job("j", (Step("ruff check api/doug", ""),))], [_check("j")])
    assert ev.covers(ci.RUFF, "api/doug/x.py")
    assert not ev.covers(ci.RUFF, "api/tests/test_x.py")
    ev = ci.evidence([Job("j", (Step("ruff check scripts/x.py", ""),))], [_check("j")])
    assert ev.covers(ci.RUFF, "scripts/x.py")
    assert not ev.covers(ci.RUFF, "scripts/y.py")
