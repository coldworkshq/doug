"""Pins that the deploy script still names the identities it claims to use.

A comment saying doug-web has its own SA is not a capability — the next
web() deploy either passes --service-account or silently runs as the
default compute SA (roles/editor on doug-prod0). Same shape as the intent
allowlist pin in test_deviations.py.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

GCP_PATH = Path(__file__).resolve().parents[1] / "deploy" / "gcp.sh"
GCP = GCP_PATH.read_text()
DEPLOY_WORKFLOW = GCP_PATH.parents[2] / ".github" / "workflows" / "deploy.yml"


def _active_lines() -> list[str]:
    return [ln for ln in GCP.splitlines() if not ln.lstrip().startswith("#")]


def _function_body(name: str) -> str:
    """Active (non-comment) lines of `name() { … }` up to the next top-level fn."""
    lines = _active_lines()
    body: list[str] = []
    in_fn = False
    for ln in lines:
        if ln.startswith(f"{name}()"):
            in_fn = True
            continue
        if in_fn:
            # Top-level sibling function: `foo() {` at column 0.
            if ln.endswith("() {") and not ln.startswith((" ", "\t")):
                break
            body.append(ln)
    return "\n".join(body)


def test_web_deploy_runs_as_doug_web_sa():
    """The browser-facing service must not inherit the default compute SA."""
    body = _function_body("web")
    assert "--service-account" in body
    assert "doug-web-sa@$PROJECT.iam.gserviceaccount.com" in body
    assert "compute@developer.gserviceaccount.com" not in body


def test_setup_creates_doug_web_sa_and_binds_only_its_front_door_secrets(tmp_path):
    """The public service gets AuthKit's four values and the purpose-scoped
    flow signer. Any API/operator secret expands its blast radius."""
    setup = _function_body("setup")
    assert "service-accounts create doug-web-sa" in setup
    after_web = setup.split("service-accounts create doug-web-sa", 1)[1].split(
        "service-accounts create doug-console-sa", 1
    )[0]
    assert "roles/cloudsql.client" not in after_web
    lines = _run_gcp(tmp_path, "setup")
    web_bindings = [
        line
        for line in lines
        if line.startswith("secrets add-iam-policy-binding")
        and "doug-web-sa@doug-prod0.iam.gserviceaccount.com" in line
    ]
    assert web_bindings == [
        "secrets add-iam-policy-binding doug-workos-client-id --project doug-prod0 "
        "--member=serviceAccount:doug-web-sa@doug-prod0.iam.gserviceaccount.com "
        "--role=roles/secretmanager.secretAccessor",
        "secrets add-iam-policy-binding doug-workos-api-key --project doug-prod0 "
        "--member=serviceAccount:doug-web-sa@doug-prod0.iam.gserviceaccount.com "
        "--role=roles/secretmanager.secretAccessor",
        "secrets add-iam-policy-binding doug-workos-cookie-password --project doug-prod0 "
        "--member=serviceAccount:doug-web-sa@doug-prod0.iam.gserviceaccount.com "
        "--role=roles/secretmanager.secretAccessor",
        "secrets add-iam-policy-binding doug-workos-redirect-uri --project doug-prod0 "
        "--member=serviceAccount:doug-web-sa@doug-prod0.iam.gserviceaccount.com "
        "--role=roles/secretmanager.secretAccessor",
        "secrets add-iam-policy-binding doug-install-flow-secret --project doug-prod0 "
        "--member=serviceAccount:doug-web-sa@doug-prod0.iam.gserviceaccount.com "
        "--role=roles/secretmanager.secretAccessor",
    ]


def test_web_deploy_carries_only_its_front_door_secrets_and_plain_slug(tmp_path):
    """The runtime binding is independent of IAM. Sending an API/operator
    secret to this --allow-unauthenticated service leaks it even if the web
    service account cannot read it."""
    lines = _run_gcp(tmp_path, "web")
    [deploy] = [line for line in lines if line.startswith("run deploy doug-web")]
    expected_secrets = (
        "WORKOS_CLIENT_ID=doug-workos-client-id:latest,"
        "WORKOS_API_KEY=doug-workos-api-key:latest,"
        "WORKOS_COOKIE_PASSWORD=doug-workos-cookie-password:latest,"
        "NEXT_PUBLIC_WORKOS_REDIRECT_URI=doug-workos-redirect-uri:latest,"
        "DOUG_INSTALL_FLOW_SECRET=doug-install-flow-secret:latest"
    )
    secret_argument = deploy.split("--set-secrets ", 1)[1].split(" --", 1)[0]
    assert secret_argument == expected_secrets
    assert (
        "--set-env-vars "
        "DOUG_API_URL=,WORKOS_COOKIE_MAX_AGE=28800,DOUG_GITHUB_APP_SLUG=dougs-review"
        in deploy
    )


def test_setup_generates_the_install_flow_secret_and_binds_exact_api_allowlist(tmp_path):
    """Both services must share one dedicated signer; no operator or provider
    credential may be substituted for it, and setup must bind it to the API
    identity rather than relying on project-wide access."""
    lines = _run_gcp(tmp_path, "setup")
    assert "secrets create doug-install-flow-secret --data-file=- --project doug-prod0" in lines
    api_bindings = [
        line
        for line in lines
        if line.startswith("secrets add-iam-policy-binding")
        and "doug-api-sa@doug-prod0.iam.gserviceaccount.com" in line
    ]
    expected_secrets = [
        "doug-database-url",
        "doug-api-token",
        "doug-anthropic-key",
        "doug-webhook-secret",
        "doug-github-app-key",
        "doug-token-pepper",
        "doug-workos-api-key",
        "doug-workos-client-id",
        "doug-install-flow-secret",
    ]
    assert api_bindings == [
        f"secrets add-iam-policy-binding {secret} --project doug-prod0 "
        "--member=serviceAccount:doug-api-sa@doug-prod0.iam.gserviceaccount.com "
        "--role=roles/secretmanager.secretAccessor"
        for secret in expected_secrets
    ]


def test_api_deploy_carries_the_showcase_repo():
    """The public pages 404 without it, so it belongs on doug-api and
    nowhere else."""
    assert "DOUG_SHOWCASE_REPO=" in _function_body("deploy")


def test_deploy_smokes_the_showcase_route_before_promoting_and_on_first_deploy():
    """DOUG_SHOWCASE_REPO reaches the service only through this deploy. If
    it is wrong, /v1/showcase/queue 404s while /openapi.json and / both
    still return 200 regardless — nothing else in the pipeline catches a
    bad pin. Smoked on the candidate before promote_if_healthy takes it to
    100% traffic, and on the live URL on a service's first deploy (which
    has no candidate to stage against — see promote_if_healthy's own
    comment above it)."""
    body = _function_body("deploy")
    # The exact promote line, all three routes on the one call: substring
    # checks alone are satisfiable by the first-deploy smoke lines, which
    # would let a gate that dropped openapi or queue pass unnoticed.
    assert (
        'promote_if_healthy "$SERVICE" '
        "/openapi.json /v1/showcase/queue /v1/showcase/scoreboard" in body
    )
    assert 'smoke "$(api_url)/v1/showcase/queue"' in body
    assert 'smoke "$(api_url)/v1/showcase/scoreboard"' in body


def test_api_deploy_still_runs_as_doug_api_sa():
    """Don't accidentally move the API off its dedicated SA while touching web."""
    body = _function_body("deploy")
    assert "doug-api-sa@$PROJECT.iam.gserviceaccount.com" in body


def test_console_is_never_deployed_unauthenticated():
    """The console spans every installation. Deploying it open publishes
    both tenants' PR titles, job errors and coverage gaps. A comment is not
    a control — this is the control."""
    body = _function_body("console")
    assert "--no-allow-unauthenticated" in body
    assert "--allow-unauthenticated" not in body.replace("--no-allow-unauthenticated", "")
    # --no-allow-unauthenticated only blocks the default deploy-time policy.
    # A later `services add-iam-policy-binding ... --member=allUsers` — in
    # console() or in setup() — would leave both assertions above passing
    # while the service is world-readable, so this checks the whole script,
    # not just console()'s body.
    assert "allUsers" not in GCP
    assert "allAuthenticatedUsers" not in GCP


def test_console_runs_as_its_own_service_account():
    body = _function_body("console")
    assert "--service-account" in body
    assert "doug-console-sa@$PROJECT.iam.gserviceaccount.com" in body
    assert "compute@developer.gserviceaccount.com" not in body


def test_setup_creates_doug_console_sa_and_binds_only_the_api_token():
    """The console talks to doug-api over HTTP. It needs no Cloud SQL
    client, no App key, no Anthropic key."""
    setup = _function_body("setup")
    assert "service-accounts create doug-console-sa" in setup
    after = setup.split("service-accounts create doug-console-sa", 1)[1].split(
        "service-accounts create doug-adjudicator-sa", 1
    )[0]
    assert "doug-api-token" in after
    assert "doug-database-url" not in after
    assert "doug-github-app-key" not in after
    assert "doug-anthropic-key" not in after
    assert "roles/cloudsql.client" not in after


def test_example_pack_setup_creates_private_bucket_and_exact_runtime_capabilities(tmp_path):
    lines = _run_gcp(
        tmp_path,
        "example-pack-setup",
        {"DOUG_EXAMPLE_PACK_BUCKET": "doug-private-evidence"},
    )

    assert any(
        line.startswith("services enable storage.googleapis.com secretmanager.googleapis.com")
        for line in lines
    )
    assert any(
        line.startswith("storage buckets create gs://doug-private-evidence")
        and "--location=us-central1" in line
        and "--uniform-bucket-level-access" in line
        and "--public-access-prevention" in line
        for line in lines
    )
    assert any(
        line.startswith("storage buckets update gs://doug-private-evidence")
        and "--lifecycle-file=" in line
        for line in lines
    )
    assert any(
        line.startswith("storage buckets describe gs://doug-private-evidence")
        and "--raw" in line
        for line in lines
    )
    bucket_bindings = [
        line
        for line in lines
        if line.startswith(
            "storage buckets add-iam-policy-binding gs://doug-private-evidence"
        )
    ]
    assert bucket_bindings == [
        "storage buckets add-iam-policy-binding gs://doug-private-evidence "
        "--project doug-prod0 --member=serviceAccount:"
        "doug-api-sa@doug-prod0.iam.gserviceaccount.com "
        "--role=roles/storage.objectCreator",
        "storage buckets add-iam-policy-binding gs://doug-private-evidence "
        "--project doug-prod0 --member=serviceAccount:"
        "doug-api-sa@doug-prod0.iam.gserviceaccount.com "
        "--role=roles/storage.objectViewer",
    ]
    assert not any("doug-console-sa" in line for line in bucket_bindings)
    secret_bindings = [
        line
        for line in lines
        if line.startswith(
            "secrets add-iam-policy-binding doug-example-pack-token"
        )
    ]
    assert len(secret_bindings) == 2
    assert any("doug-api-sa@" in line for line in secret_bindings)
    assert any("doug-console-sa@" in line for line in secret_bindings)
    assert '"matchesPrefix":["cohorts/"]' in GCP


def test_example_pack_setup_rejects_an_existing_bucket_with_unsafe_posture(tmp_path):
    result, lines = _invoke_gcp(
        tmp_path,
        "example-pack-setup",
        {
            "DOUG_EXAMPLE_PACK_BUCKET": "doug-private-evidence",
            "GCLOUD_UNSAFE_EXAMPLE_PACK_BUCKET": "1",
        },
    )

    assert result.returncode != 0
    assert any(
        line.startswith("storage buckets describe gs://doug-private-evidence")
        for line in lines
    )
    assert not any("storage buckets add-iam-policy-binding" in line for line in lines)


def _clean_source_repo(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    (source / "receipt.txt").write_text("clean\n")
    subprocess.run(["git", "add", "receipt.txt"], cwd=source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Doug Test",
            "-c",
            "user.email=doug@example.invalid",
            "commit",
            "-q",
            "-m",
            "clean source",
        ],
        cwd=source,
        check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source, revision


def _example_pack_enable_env(source: Path, revision: str) -> dict[str, str]:
    return {
        "DOUG_EXAMPLE_PACK_SOURCE_ROOT": str(source),
        "DOUG_EXAMPLE_PACK_BUCKET": "doug-private-evidence",
        "DOUG_EXAMPLE_PACK_COHORT": "doug-dogfood-2026-08",
        "DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT": "2026-08-10T18:00:00Z",
        "DOUG_EXAMPLE_PACK_CAPTURE_UNTIL": "2026-08-17T18:00:00Z",
        "DOUG_EXAMPLE_PACK_INSTALLATION_IDS": "150424894",
        "DOUG_EXAMPLE_PACK_REPOSITORY_IDS": "987654321",
        "DOUG_EXAMPLE_PACK_ADJUDICATOR": "andrew",
        "DOUG_APPLICATION_REVISION": revision,
    }


def test_example_pack_enable_updates_only_api_capture_and_both_purpose_secrets(tmp_path):
    source, revision = _clean_source_repo(tmp_path)
    lines = _run_gcp(
        tmp_path,
        "example-pack-enable",
        {
            "DOUG_EXAMPLE_PACK_SOURCE_ROOT": str(source),
            "DOUG_EXAMPLE_PACK_BUCKET": "doug-private-evidence",
            "DOUG_EXAMPLE_PACK_COHORT": "doug-dogfood-2026-08",
            "DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT": "2026-08-10T18:00:00Z",
            "DOUG_EXAMPLE_PACK_CAPTURE_UNTIL": "2026-08-17T18:00:00Z",
            "DOUG_EXAMPLE_PACK_INSTALLATION_IDS": "150424894",
            "DOUG_EXAMPLE_PACK_REPOSITORY_IDS": "987654321",
            "DOUG_EXAMPLE_PACK_ADJUDICATOR": "andrew",
            "DOUG_APPLICATION_REVISION": revision,
        },
    )

    updates = [line for line in lines if line.startswith("run services update")]
    assert len(updates) == 2
    [api_update] = [line for line in updates if line.startswith("run services update doug-api")]
    [console_update] = [
        line for line in updates if line.startswith("run services update doug-console")
    ]
    assert "DOUG_EXAMPLE_PACK_CAPTURE=1" in api_update
    assert "DOUG_EXAMPLE_PACK_BUCKET=doug-private-evidence" in api_update
    assert f"DOUG_APPLICATION_REVISION={revision}" in api_update
    assert "DOUG_EXAMPLE_PACK_TOKEN=doug-example-pack-token:latest" in api_update
    assert "DOUG_EXAMPLE_PACK_TOKEN=doug-example-pack-token:latest" in console_update
    assert "DOUG_EXAMPLE_PACK_CAPTURE" not in console_update


def test_example_pack_enable_fails_before_cloud_mutation_when_contract_is_incomplete(tmp_path):
    result, lines = _invoke_gcp(
        tmp_path,
        "example-pack-enable",
        {"DOUG_EXAMPLE_PACK_BUCKET": "doug-private-evidence"},
    )

    assert result.returncode != 0
    assert not [line for line in lines if line.startswith("run services update")]


def test_example_pack_enable_rejects_runtime_invalid_identity_before_cloud_mutation(
    tmp_path,
):
    source, revision = _clean_source_repo(tmp_path)
    invalid_values = (
        ("DOUG_EXAMPLE_PACK_COHORT", "Doug.Dogfood"),
        ("DOUG_EXAMPLE_PACK_COHORT", "a" * 64),
        ("DOUG_EXAMPLE_PACK_INSTALLATION_IDS", "0"),
        ("DOUG_EXAMPLE_PACK_REPOSITORY_IDS", "987654321,987654321"),
    )

    for index, (name, value) in enumerate(invalid_values):
        case_root = tmp_path / f"invalid-{index}"
        case_root.mkdir()
        env = _example_pack_enable_env(source, revision)
        env[name] = value
        result, lines = _invoke_gcp(case_root, "example-pack-enable", env)

        assert result.returncode != 0, f"{name}={value!r} was accepted"
        assert lines == []


def test_api_deploy_preserves_closed_cohort_reads_without_reenabling_capture(tmp_path):
    lines = _run_gcp(
        tmp_path,
        "deploy",
        {"GCLOUD_EXAMPLE_PACK_CONFIG": "1"},
    )
    [api_deploy] = [
        line for line in lines if line.startswith("run deploy doug-api --source .")
    ]

    assert "DOUG_EXAMPLE_PACK_BUCKET=doug-private-evidence" in api_deploy
    assert "DOUG_EXAMPLE_PACK_COHORT=doug-dogfood-2026-08" in api_deploy
    assert "DOUG_EXAMPLE_PACK_ADJUDICATOR=andrew" in api_deploy
    assert "DOUG_EXAMPLE_PACK_TOKEN=doug-example-pack-token:latest" in api_deploy
    assert "DOUG_EXAMPLE_PACK_CAPTURE" not in api_deploy


def test_console_deploy_preserves_existing_example_pack_purpose_token(tmp_path):
    lines = _run_gcp(
        tmp_path,
        "console",
        {"GCLOUD_EXAMPLE_PACK_CONFIG": "1"},
    )
    [console_deploy] = [
        line for line in lines if line.startswith("run deploy doug-console")
    ]

    assert "DOUG_EXAMPLE_PACK_TOKEN=doug-example-pack-token:latest" in console_deploy
    assert "DOUG_EXAMPLE_PACK_BUCKET" not in console_deploy
    assert "DOUG_EXAMPLE_PACK_CAPTURE" not in console_deploy


def test_example_pack_disable_changes_only_the_capture_flag(tmp_path):
    lines = _run_gcp(tmp_path, "example-pack-disable")
    updates = [line for line in lines if line.startswith("run services update")]
    assert updates == [
        "run services update doug-api --project doug-prod0 --region us-central1 "
        "--update-env-vars DOUG_EXAMPLE_PACK_CAPTURE=0"
    ]


def test_web_deploy_is_still_the_only_public_service():
    """Guard against the console being folded back into web()."""
    assert "--allow-unauthenticated" in _function_body("web")
    assert "--source ../console" not in _function_body("web")


def test_node_deploys_build_images_from_the_monorepo_root():
    """npm workspaces put the lockfile at the repo root; Cloud Run
    `--source ../web` cannot see it. Both Node deploys must build via
    Cloud Build from REPO_ROOT, then `gcloud run deploy --image`."""
    web = _function_body("web")
    console = _function_body("console")
    assert "build_node_image web/Dockerfile doug-web" in web
    assert "build_node_image console/Dockerfile doug-console" in console
    assert "--source ../web" not in web
    assert "--source ../console" not in console
    assert "--image \"$image\"" in web
    assert "--image \"$image\"" in console
    build = _function_body("build_node_image")
    assert "cloudbuild-node.yaml" in build
    assert 'gcloud builds submit "$REPO_ROOT"' in build
    # stdout is captured as the image tag — submit logs must not land there.
    assert "--suppress-logs" in build
    # Repo create is setup-only; deploy must fail closed if the repo is missing.
    assert "require_node_artifact_repo >&2" in build
    assert "ensure_node_artifact_repo" not in build
    setup = _function_body("setup")
    assert "ensure_node_artifact_repo" in setup


def test_root_gcloudignore_tracks_dockerignore_for_node_builds():
    """gcloud builds submit ignores via .gcloudignore, not .dockerignore.
    The two files must stay paired or Cloud Build uploads a different
    context than the docker builds CI already exercised."""
    root = Path(__file__).resolve().parents[2]
    dockerignore = (root / ".dockerignore").read_text()
    gcloudignore = (root / ".gcloudignore").read_text()
    # Strip comment lines — the gcloud file carries an extra why-header.
    def body(text: str) -> list[str]:
        return [line for line in text.splitlines() if line and not line.startswith("#")]

    assert body(dockerignore) == body(gcloudignore)


def test_gcloudignore_keeps_every_tracked_web_source_file_in_the_upload():
    """Byte-identity with .dockerignore (above) is necessary but NOT
    sufficient, and on its own it shipped a 404 to production.

    .gcloudignore is gitignore syntax, where a bare `docs` matches a
    directory named docs at ANY depth. .dockerignore anchors bare patterns
    to the context root. Identical text, different meaning: the shared
    `docs` line excluded only ./docs from every local and CI `docker build`
    while additionally stripping web/app/docs/** and web/components/docs/**
    from the Cloud Build upload — the one context nothing exercised.

    The failure was silent by construction. The pages and the components
    they import disappeared together, so no import dangled and `next build`
    went green on 11 routes instead of 21; the deploy's smoke test only
    probes `/`. site-header.tsx is not under a docs/ directory, so the
    header's Docs link shipped and pointed at a route that had never been
    compiled. /docs 404'd in production from #101 until someone opened it.

    So: assert the invariant the images actually depend on — every tracked
    file the web/console builds compile survives the upload filter — rather
    than a spelling. Markdown is excluded on purpose (`**/*.md`) and is not
    compiled, so it is exempt.
    """
    root = Path(__file__).resolve().parents[2]
    # -z, not .split(): git C-quotes unusual paths and .split() breaks on any
    # whitespace, so `web/app/case study/page.tsx` would silently become two
    # fragments that match nothing and pass — dropping the very file this pin
    # is meant to cover instead of failing.
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "web", "console"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    compiled = [p for p in tracked if p and not p.endswith(".md")]
    # Guard the guard: an empty list would make every assertion below vacuous.
    assert len(compiled) > 100, f"expected a real source tree, got {len(compiled)}"
    assert any(p.startswith("web/app/docs/") for p in compiled), \
        "web/app/docs/ is not tracked — this pin can no longer see the regression"

    # Use git as the gitignore oracle: same engine gcloud's .gcloudignore
    # follows, so this cannot drift from real matching semantics the way a
    # hand-rolled matcher would.
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=scratch, check=True)
        # The oracle must see .gcloudignore and NOTHING else. A scratch repo
        # still inherits the developer's global core.excludesFile (and any
        # info/exclude an init.templateDir dropped in), so a global gitignore
        # holding a bare `docs`/`out`/`dist` would report real web sources as
        # stripped and fail this test on that machine while CI stayed green.
        (scratch / ".git" / "info" / "exclude").write_text("")
        (scratch / ".gitignore").write_text((root / ".gcloudignore").read_text())
        for rel in compiled:
            target = scratch / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        # check-ignore prints the paths it WOULD exclude; 0 = some ignored,
        # 1 = none, anything else is a real error. Reading stdout alone would
        # turn a git failure into an empty list and a silent pass — the exact
        # cannot-fail mode this pin exists to prevent.
        proc = subprocess.run(
            ["git", "-c", "core.excludesFile=/dev/null", "check-ignore", "-z", "--stdin"],
            cwd=scratch, input="\0".join(compiled),
            capture_output=True, text=True,
        )
        assert proc.returncode in (0, 1), (
            f"git check-ignore failed ({proc.returncode}), so this pin proved "
            f"nothing: {proc.stderr.strip()}"
        )
        ignored = [p for p in proc.stdout.split("\0") if p]

    assert not ignored, (
        "these tracked sources would be stripped from the Cloud Build upload "
        "and silently vanish from the deployed image — anchor the offending "
        f".gcloudignore entry with a leading slash: {sorted(ignored)}"
    )


def test_api_deploy_source_is_api_dir_not_repo_root():
    """Root .gcloudignore excludes `api/`. That is safe only because the
    API deploy uploads from inside api/ (`--source .` after cd API_DIR),
    so gcloud resolves api/.gcloudignore — not the root file."""
    deploy = _function_body("deploy")
    assert "--source ." in deploy
    assert "--source .." not in deploy
    assert "--source ../api" not in deploy
    # The script cds to API_DIR before the case dispatch; pin that the
    # deploy body never rebinds CWD to the repo root.
    assert "cd \"$REPO_ROOT\"" not in deploy


def _fake_gcloud(tmp_path: Path) -> tuple[Path, Path]:
    """Deterministic external boundaries: record argv, fake Cloud Run state,
    and report that the Scheduler resource does not exist yet."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "gcloud.log"
    log.touch()
    cwd_log = tmp_path / "gcloud.cwd.log"
    cwd_log.touch()
    gcloud = fake_bin / "gcloud"
    gcloud.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$GCLOUD_LOG"
printf '%s\\n' "$PWD" >> "$GCLOUD_CWD_LOG"
previous=
format=
raw=0
for argument in "$@"; do
  if [ "$previous" = "--args" ] && [ "${argument#-}" != "$argument" ]; then
    printf '%s\\n' 'ERROR: argument --args: expected one argument' >&2
    exit 2
  fi
  case "$argument" in
    --format=*) format=${argument#--format=} ;;
    --raw) raw=1 ;;
  esac
  previous=$argument
done
if [ "$1 $2 $3" = "storage buckets create" ] \\
    && [ "${GCLOUD_UNSAFE_EXAMPLE_PACK_BUCKET:-}" = "1" ]; then
  exit 1
fi
if [ "$1 $2 $3" = "storage buckets describe" ]; then
  if [ "$raw" != "1" ]; then
    printf '%s%s\\n' '{"location":"us-central1","storage_class":"STANDARD",' \\
      '"public_access_prevention":"enforced","uniform_bucket_level_access":true}'
    exit 0
  fi
  if [ "${GCLOUD_UNSAFE_EXAMPLE_PACK_BUCKET:-}" = "1" ]; then
    printf '%s%s%s\\n' '{"location":"EUROPE-WEST1","storageClass":"NEARLINE",' \\
      '"iamConfiguration":{"uniformBucketLevelAccess":{"enabled":false},' \\
      '"publicAccessPrevention":"inherited"}}'
  else
    printf '%s%s%s\\n' '{"location":"US-CENTRAL1","storageClass":"STANDARD",' \\
      '"iamConfiguration":{"uniformBucketLevelAccess":{"enabled":true},' \\
      '"publicAccessPrevention":"enforced"}}'
  fi
  exit 0
fi
if [ "$1 $2 $3 $4" = "run services describe doug-api" ] \
    || [ "$1 $2 $3 $4" = "run services describe doug-web" ] \\
    || [ "$1 $2 $3 $4" = "run services describe doug-console" ]; then
  case "$format" in
    json)
      if [ "${GCLOUD_EXAMPLE_PACK_CONFIG:-}" = "1" ]; then
        printf '%s\\n' '{"status":{"traffic":[{"tag":"candidate","url":"https://candidate.invalid"}]},"spec":{"template":{"spec":{"containers":[{"env":[{"name":"DOUG_EXAMPLE_PACK_CAPTURE","value":"1"},{"name":"DOUG_EXAMPLE_PACK_BUCKET","value":"doug-private-evidence"},{"name":"DOUG_EXAMPLE_PACK_COHORT","value":"doug-dogfood-2026-08"},{"name":"DOUG_EXAMPLE_PACK_ADJUDICATOR","value":"andrew"},{"name":"DOUG_EXAMPLE_PACK_TOKEN","valueFrom":{"secretKeyRef":{"name":"doug-example-pack-token","key":"latest"}}}]}]}}}}'
      else
        printf '%s\\n' '{"status":{"traffic":[{"tag":"candidate","url":"https://candidate.invalid"}]}}'
      fi
      ;;
    'value(spec.template.spec.containers[0].image)')
      printf '%s\\n' 'us-docker.pkg.dev/doug-prod0/cloud-run-source-deploy/doug-api@sha256:abc123'
      ;;
  esac
  exit 0
fi
if [ "$1 $2 $3 $4" = "sql instances describe doug-ledger" ] \
    && [ "$format" = "value(state)" ]; then
  printf '%s\n' 'RUNNABLE'
  exit 0
fi
if [ "$1 $2 $3" = "scheduler jobs describe" ]; then
  exit 1
fi
if [ "$1 $2 $3" = "iam service-accounts describe" ] \
    && [ "$4" = "${GCLOUD_TRANSIENT_SA:-}" ] \
    && [ ! -f "$GCLOUD_STATE" ]; then
  : > "$GCLOUD_STATE"
  exit 1
fi
exit 0
"""
    )
    gcloud.chmod(0o755)

    curl_log = tmp_path / "curl.log"
    curl_log.touch()
    curl = fake_bin / "curl"
    curl.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$CURL_LOG"
printf '%s' '200'
"""
    )
    curl.chmod(0o755)
    return fake_bin, log


def _invoke_gcp(
    tmp_path: Path,
    command: str,
    extra_env: dict[str, str] | None = None,
    *,
    gcp_path: Path = GCP_PATH,
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_bin, log = _fake_gcloud(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GCLOUD_LOG": str(log),
        "GCLOUD_CWD_LOG": str(tmp_path / "gcloud.cwd.log"),
        "CURL_LOG": str(tmp_path / "curl.log"),
        "GCLOUD_STATE": str(tmp_path / "gcloud.state"),
        "PROJECT": "doug-prod0",
        "REGION": "us-central1",
        **(extra_env or {}),
    }
    result = subprocess.run(
        ["bash", str(gcp_path), command],
        cwd=cwd or gcp_path.parent.parent,
        env=env,
        capture_output=True,
        text=True,
    )
    return result, log.read_text().splitlines()


def _run_gcp(
    tmp_path: Path, command: str, extra_env: dict[str, str] | None = None
) -> list[str]:
    result, lines = _invoke_gcp(tmp_path, command, extra_env)
    assert result.returncode == 0, result.stdout + result.stderr
    return lines


def test_prereg_hash_is_computed_in_exactly_one_place():
    """Two copies of the sha256 one-liner could compute two different answers
    for 'which document is in force' if ever edited independently — exactly
    the failure the hash exists to prevent."""
    assert GCP.count("hashlib.sha256") == 1


def test_api_deploy_carries_the_prereg_hash_env_var(tmp_path):
    """gcp.sh stamped DOUG_PREREG_HASH onto the adjudicator Job only (Task 3).
    Receipts (Task 8) need the api service to report the hash currently in
    force too, so it must see the same env var."""
    lines = _run_gcp(tmp_path, "deploy")
    [api_deploy] = [
        line for line in lines if line.startswith("run deploy doug-api --source .")
    ]
    prereg = GCP_PATH.parents[2] / "docs/design/outcome-loop/publication-preregistration.md"
    expected_hash = hashlib.sha256(prereg.read_bytes()).hexdigest()
    assert f"DOUG_PREREG_HASH={expected_hash}" in api_deploy


def test_showcase_smoke_failure_blocks_promotion(tmp_path):
    """/openapi.json returns 200 regardless of DOUG_SHOWCASE_REPO, so it
    alone would happily promote a candidate whose showcase route is
    broken. This makes the fake curl 404 ONLY on /v1/showcase/queue and
    proves that: (1) the deploy fails, and (2) update-traffic — which
    would move real traffic onto the bad candidate — never runs. A smoke
    that runs after traffic already moved would protect nothing."""
    fake_bin, log = _fake_gcloud(tmp_path)
    curl = fake_bin / "curl"
    curl.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$CURL_LOG"
case "$*" in
  *v1/showcase/queue*) printf '%s' '404' ;;
  *) printf '%s' '200' ;;
esac
"""
    )
    curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GCLOUD_LOG": str(log),
        "GCLOUD_CWD_LOG": str(tmp_path / "gcloud.cwd.log"),
        "CURL_LOG": str(tmp_path / "curl.log"),
        "GCLOUD_STATE": str(tmp_path / "gcloud.state"),
        "PROJECT": "doug-prod0",
        "REGION": "us-central1",
    }
    result = subprocess.run(
        ["bash", str(GCP_PATH), "deploy"],
        cwd=GCP_PATH.parent.parent,
        env=env,
        capture_output=True,
        text=True,
    )
    lines = log.read_text().splitlines()

    assert result.returncode != 0, result.stdout + result.stderr
    assert "v1/showcase/queue" in (tmp_path / "curl.log").read_text()
    assert not [
        line for line in lines if line.startswith("run services update-traffic doug-api")
    ]


def test_adjudicator_deploys_the_live_api_image_with_the_bounded_job_contract(tmp_path):
    """Building a second source image could fork the live detector; platform
    retries would spend several of the ten attempts on one calendar day."""
    lines = _run_gcp(tmp_path, "adjudicator")
    [deploy] = [line for line in lines if line.startswith("run jobs deploy doug-adjudicator")]
    assert (
        "--image us-docker.pkg.dev/doug-prod0/cloud-run-source-deploy/"
        "doug-api@sha256:abc123" in deploy
    )
    assert "--memory 2Gi" in deploy
    assert "--cpu 1" in deploy
    assert "--tasks 1" in deploy
    assert "--max-retries 0" in deploy
    assert "--task-timeout 3600s" in deploy
    assert "--command python" in deploy
    assert "--args=-m,doug.outcome_worker" in deploy
    assert "--service-account doug-adjudicator-sa@doug-prod0.iam.gserviceaccount.com" in deploy
    assert "DATABASE_URL=doug-database-url:latest" in deploy
    assert "GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest" in deploy

    prereg = GCP_PATH.parents[2] / "docs/design/outcome-loop/publication-preregistration.md"
    expected_hash = hashlib.sha256(prereg.read_bytes()).hexdigest()
    assert f"DOUG_PREREG_HASH={expected_hash}" in deploy


def test_reconcile_job_deploys_the_live_api_image_under_the_adjudicator_sa_with_no_prereg_hash(
    tmp_path,
):
    """Mirrors test_adjudicator_deploys_the_live_api_image_with_the_bounded_job_contract
    for the outcome reconciler: same live image, same runtime identity and
    secret allowlist as the adjudicator (no new SA), but it must NOT carry
    DOUG_PREREG_HASH anywhere in its arguments — reconciliation only enqueues
    outcome_jobs rows, it never adjudicates or publishes anything, so the
    hash preflight the adjudicator requires does not apply here (see
    reconcile_job()'s own comment in gcp.sh)."""
    lines = _run_gcp(tmp_path, "reconcile-job")
    [deploy] = [
        line for line in lines if line.startswith("run jobs deploy doug-outcome-reconciler")
    ]
    assert (
        "--image us-docker.pkg.dev/doug-prod0/cloud-run-source-deploy/"
        "doug-api@sha256:abc123" in deploy
    )
    assert "--memory 512Mi" in deploy
    assert "--cpu 1" in deploy
    assert "--tasks 1" in deploy
    assert "--max-retries 0" in deploy
    # The adjudicator's hour, not a smaller number sized to what one sweep
    # looks like it needs: a task killed at the timeout has no resume point
    # and active_installations() has no ORDER BY, so the tenants that sort
    # last would simply never be reconciled, and --max-retries 0 means
    # nothing re-runs to catch them.
    assert "--task-timeout 3600s" in deploy
    assert "--command python" in deploy
    assert "--args=-m,doug.reconcile_worker" in deploy
    assert "--service-account doug-adjudicator-sa@doug-prod0.iam.gserviceaccount.com" in deploy

    expected_secrets = (
        "DATABASE_URL=doug-database-url:latest,"
        "GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest"
    )
    actual_secrets = deploy.split("--set-secrets ", 1)[1].split(" --", 1)[0]
    assert actual_secrets == expected_secrets

    # The one thing that must NOT be here: this is what distinguishes the
    # reconciler's deploy from the adjudicator's, which does carry it.
    assert "DOUG_PREREG_HASH" not in deploy


def test_adjudicator_resolves_the_locked_preregistration_from_its_own_location(tmp_path):
    """An absolute script invocation must hash the lock, not caller-relative text."""
    prereg = GCP_PATH.parents[2] / "docs/design/outcome-loop/publication-preregistration.md"
    expected_hash = hashlib.sha256(prereg.read_bytes()).hexdigest()
    callers = {
        "repo-root": GCP_PATH.parents[2],
        "unrelated": tmp_path / "unrelated-caller",
    }

    for name, caller_cwd in callers.items():
        caller_cwd.mkdir(exist_ok=True)
        case = tmp_path / name
        case.mkdir()
        result, lines = _invoke_gcp(case, "adjudicator", cwd=caller_cwd)

        assert result.returncode == 0, result.stdout + result.stderr
        [deploy] = [
            line for line in lines if line.startswith("run jobs deploy doug-adjudicator")
        ]
        assert f"DOUG_PREREG_HASH={expected_hash}" in deploy


def test_full_deploy_normalizes_to_api_before_the_fake_cloud_boundary(tmp_path):
    """Relative --source paths must keep naming api/ from every caller CWD."""
    callers = {
        "repo-root": GCP_PATH.parents[2],
        "unrelated": tmp_path / "unrelated-caller",
    }
    expected_cwd = str(GCP_PATH.parent.parent.resolve())

    for name, caller_cwd in callers.items():
        caller_cwd.mkdir(exist_ok=True)
        case = tmp_path / name
        case.mkdir()
        result, lines = _invoke_gcp(case, "deploy", cwd=caller_cwd)

        assert result.returncode == 0, result.stdout + result.stderr
        assert any(line.startswith("run deploy doug-api --source .") for line in lines)
        assert set((case / "gcloud.cwd.log").read_text().splitlines()) == {expected_cwd}


def test_relative_script_symlink_resolves_the_lock_and_api_working_directory(tmp_path):
    """A portable launcher can link to gcp.sh without changing its deployment root."""
    link_dir = tmp_path / "launchers"
    link_dir.mkdir()
    script_link = link_dir / "gcp.sh"
    script_link.symlink_to(os.path.relpath(GCP_PATH, link_dir))
    caller_cwd = tmp_path / "unrelated-caller"
    caller_cwd.mkdir()
    case = tmp_path / "symlink-case"
    case.mkdir()

    result, lines = _invoke_gcp(
        case, "deploy", gcp_path=script_link, cwd=caller_cwd
    )

    prereg = GCP_PATH.parents[2] / "docs/design/outcome-loop/publication-preregistration.md"
    expected_hash = hashlib.sha256(prereg.read_bytes()).hexdigest()
    assert result.returncode == 0, result.stdout + result.stderr
    [adjudicator] = [
        line for line in lines if line.startswith("run jobs deploy doug-adjudicator")
    ]
    assert f"DOUG_PREREG_HASH={expected_hash}" in adjudicator
    assert any(line.startswith("run deploy doug-api --source .") for line in lines)
    assert set((case / "gcloud.cwd.log").read_text().splitlines()) == {
        str(GCP_PATH.parent.parent.resolve())
    }


def test_full_deploy_hashes_the_lock_from_an_apostrophe_checkout_path(tmp_path):
    """A valid checkout path is data, never Python source used to hash the lock."""
    checkout = tmp_path / "doug's-copy"
    gcp_path = checkout / "api/deploy/gcp.sh"
    gcp_path.parent.mkdir(parents=True)
    shutil.copy2(GCP_PATH, gcp_path)
    source_prereg = (
        GCP_PATH.parents[2]
        / "docs/design/outcome-loop/publication-preregistration.md"
    )
    prereg = checkout / "docs/design/outcome-loop/publication-preregistration.md"
    prereg.parent.mkdir(parents=True)
    shutil.copy2(source_prereg, prereg)
    caller_cwd = tmp_path / "unrelated-caller"
    caller_cwd.mkdir()
    case = tmp_path / "apostrophe-case"
    case.mkdir()

    result, lines = _invoke_gcp(
        case, "deploy", gcp_path=gcp_path, cwd=caller_cwd
    )

    assert result.returncode == 0, result.stdout + result.stderr
    api_deploy = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("run deploy doug-api --source .")
    )
    api_promotion = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("run services update-traffic doug-api")
    )
    job_deploy = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("run jobs deploy doug-adjudicator")
    )
    assert api_deploy < api_promotion < job_deploy
    expected_hash = hashlib.sha256(prereg.read_bytes()).hexdigest()
    assert f"DOUG_PREREG_HASH={expected_hash}" in lines[job_deploy]
    assert set((case / "gcloud.cwd.log").read_text().splitlines()) == {
        str((checkout / "api").resolve())
    }


def test_missing_preregistration_refuses_deploy_with_a_read_error(tmp_path):
    """A missing lock is an operator path failure, not an unlocked contract."""
    gcp_path = tmp_path / "api/deploy/gcp.sh"
    gcp_path.parent.mkdir(parents=True)
    shutil.copy2(GCP_PATH, gcp_path)

    result, lines = _invoke_gcp(tmp_path, "deploy", gcp_path=gcp_path)

    assert result.returncode != 0
    assert "ERROR: cannot read publication pre-registration:" in result.stderr
    assert "not LOCKED" not in result.stderr
    assert lines == []
    assert (tmp_path / "curl.log").read_text() == ""


def test_unlocked_preregistration_refuses_adjudicator_deploy(tmp_path):
    """A mutable publication contract must never be stamped onto a runnable Job."""
    gcp_path = tmp_path / "api/deploy/gcp.sh"
    gcp_path.parent.mkdir(parents=True)
    shutil.copy2(GCP_PATH, gcp_path)
    prereg = tmp_path / "docs/design/outcome-loop/publication-preregistration.md"
    prereg.parent.mkdir(parents=True)
    prereg.write_text(
        "# Publication pre-registration — the outcome loop\n\n"
        "**Status:** DRAFT test fixture\n"
    )

    result, lines = _invoke_gcp(tmp_path, "adjudicator", gcp_path=gcp_path)

    assert result.returncode != 0
    assert result.stderr == (
        "ERROR: publication pre-registration is not LOCKED; "
        "refusing adjudicator deploy.\n"
    )
    assert not [line for line in lines if line.startswith("run jobs deploy doug-adjudicator")]


def test_unlocked_preregistration_refuses_full_deploy_before_any_external_call(tmp_path):
    """An unlocked contract must not leave the API and Job on different images."""
    gcp_path = tmp_path / "api/deploy/gcp.sh"
    gcp_path.parent.mkdir(parents=True)
    shutil.copy2(GCP_PATH, gcp_path)
    prereg = tmp_path / "docs/design/outcome-loop/publication-preregistration.md"
    prereg.parent.mkdir(parents=True)
    prereg.write_text(
        "# Publication pre-registration — the outcome loop\n\n"
        "**Status:** DRAFT test fixture\n"
    )

    result, lines = _invoke_gcp(tmp_path, "deploy", gcp_path=gcp_path)

    assert result.returncode != 0
    assert result.stderr == (
        "ERROR: publication pre-registration is not LOCKED; "
        "refusing adjudicator deploy.\n"
    )
    assert lines == []
    assert (tmp_path / "curl.log").read_text() == ""


def test_schedule_creates_one_daily_utc_trigger_with_a_scheduler_identity(tmp_path):
    """The runtime account reads code and secrets; granting it invocation
    authority too would collapse two unrelated identities."""
    lines = _run_gcp(tmp_path, "schedule")
    [binding] = [line for line in lines if line.startswith("run jobs add-iam-policy-binding")]
    assert "--member=serviceAccount:doug-scheduler-sa@doug-prod0.iam.gserviceaccount.com" in binding
    assert "--role=roles/run.invoker" in binding
    assert "doug-adjudicator-sa" not in binding

    [create] = [line for line in lines if line.startswith("scheduler jobs create http")]
    assert "--schedule 0 3 * * *" in create
    assert "--time-zone Etc/UTC" in create
    assert "--http-method POST" in create
    assert (
        "--oauth-service-account-email "
        "doug-scheduler-sa@doug-prod0.iam.gserviceaccount.com" in create
    )
    assert "/locations/us-central1/jobs/doug-adjudicator:run" in create


def test_schedule_reconcile_creates_a_6h_utc_trigger_with_the_scheduler_identity(tmp_path):
    """Mirrors test_schedule_creates_one_daily_utc_trigger_with_a_scheduler_identity
    for the outcome reconciler's own scheduler entry: doug-scheduler-sa
    invokes doug-outcome-reconciler (not doug-adjudicator-sa, and not the
    adjudicator's Job), every 6 hours rather than daily."""
    lines = _run_gcp(tmp_path, "schedule-reconcile")
    [binding] = [line for line in lines if line.startswith("run jobs add-iam-policy-binding")]
    assert binding.startswith("run jobs add-iam-policy-binding doug-outcome-reconciler ")
    assert "--member=serviceAccount:doug-scheduler-sa@doug-prod0.iam.gserviceaccount.com" in binding
    assert "--role=roles/run.invoker" in binding
    assert "doug-adjudicator-sa" not in binding

    [create] = [line for line in lines if line.startswith("scheduler jobs create http")]
    assert create.startswith("scheduler jobs create http doug-outcome-reconciler-6h ")
    assert "--schedule 0 */6 * * *" in create
    assert "--time-zone Etc/UTC" in create
    assert "--http-method POST" in create
    assert (
        "--oauth-service-account-email "
        "doug-scheduler-sa@doug-prod0.iam.gserviceaccount.com" in create
    )
    assert "/locations/us-central1/jobs/doug-outcome-reconciler:run" in create


def test_api_deploy_also_refreshes_the_adjudicator_from_its_promoted_image():
    """A later detector change must not deploy to the API while the outcome
    worker keeps running an older image."""
    assert "adjudicator" in _function_body("deploy")


def test_preregistration_change_refreshes_the_adjudicator_hash():
    """The Job receives the document hash at deploy time. A docs-only change
    must therefore enter the API deploy path even when no Python changed."""
    workflow = DEPLOY_WORKFLOW.read_text()
    change_filter = workflow.split('files=$(git diff --name-only', 1)[1].split(
        'echo "api=$api"', 1
    )[0]
    assert "docs/design/outcome-loop/publication-preregistration.md" in change_filter


def test_web_deploy_runs_the_auth_entry_smoke_after_promotion():
    """A root-only 200 missed the production dashboard cookie crash and the
    absent sign-in route. The deploy must invoke the executable smoke that
    proves all three public front-door boundaries."""
    workflow = DEPLOY_WORKFLOW.read_text()
    web_confirmation = workflow.split("- name: Confirm the live URL after promotion", 2)[2]
    assert 'bash web/scripts/smoke-auth-entry.sh "$url"' in web_confirmation


def test_setup_owns_scheduler_and_adjudicator_identities():
    setup = _function_body("setup")
    assert "adjudicator_setup" in setup
    adjudicator = _function_body("adjudicator_setup")
    assert "cloudscheduler.googleapis.com" in adjudicator
    assert "service-accounts create doug-adjudicator-sa" in adjudicator
    assert "service-accounts create doug-scheduler-sa" in adjudicator
    assert "doug-database-url" in adjudicator
    assert "doug-github-app-key" in adjudicator
    assert "doug-anthropic-key" not in adjudicator


def test_adjudicator_setup_is_narrow_and_never_rotates_the_database(tmp_path):
    """The broad setup command resets the production SQL password. M3 needs
    IAM and APIs only, so its operator command must be structurally unable to
    touch a SQL user or publish a new database-secret version."""
    lines = _run_gcp(tmp_path, "adjudicator-setup")
    emitted = "\n".join(lines)

    assert "services enable" in emitted
    assert "cloudscheduler.googleapis.com" in emitted
    assert "iam service-accounts create doug-adjudicator-sa" in emitted
    assert "iam service-accounts create doug-scheduler-sa" in emitted
    assert "roles/cloudsql.client" in emitted
    assert "doug-database-url" in emitted
    assert "doug-github-app-key" in emitted
    assert "sql users" not in emitted
    assert "sql databases" not in emitted
    assert "secrets versions add doug-database-url" not in emitted


def test_adjudicator_setup_waits_for_new_service_account_visibility(tmp_path):
    """IAM creation can succeed before describe sees the account. Retrying
    only the read avoids a false setup failure without replaying mutations."""
    scheduler = "doug-scheduler-sa@doug-prod0.iam.gserviceaccount.com"
    lines = _run_gcp(
        tmp_path,
        "adjudicator-setup",
        extra_env={"GCLOUD_TRANSIENT_SA": scheduler},
    )

    describes = [
        line
        for line in lines
        if line.startswith(f"iam service-accounts describe {scheduler}")
    ]
    assert len(describes) == 2


def test_api_deploy_carries_exact_secret_allowlist_including_flow_signer(tmp_path):
    """The completion endpoint needs the shared signer, but no web session
    cookie secret. Exactness prevents future credentials drifting in."""
    lines = _run_gcp(tmp_path, "deploy")
    [api_deploy] = [
        line for line in lines if line.startswith("run deploy doug-api --source .")
    ]
    expected = (
        "DATABASE_URL=doug-database-url:latest,"
        "DOUG_API_TOKEN=doug-api-token:latest,"
        "ANTHROPIC_API_KEY=doug-anthropic-key:latest,"
        "GITHUB_WEBHOOK_SECRET=doug-webhook-secret:latest,"
        "GITHUB_APP_PRIVATE_KEY=doug-github-app-key:latest,"
        "DOUG_TOKEN_PEPPER=doug-token-pepper:latest,"
        "WORKOS_API_KEY=doug-workos-api-key:latest,"
        "WORKOS_CLIENT_ID=doug-workos-client-id:latest,"
        "DOUG_INSTALL_FLOW_SECRET=doug-install-flow-secret:latest"
    )
    actual = api_deploy.split("--set-secrets ", 1)[1].split(" --", 1)[0]
    assert actual == expected
    assert "DOUG_GITHUB_APP_SLUG" not in api_deploy


def test_setup_keeps_workos_identity_secrets_off_the_console_service_account():
    """A --set-secrets flag without a matching secretAccessor binding fails at
    runtime on the first request, long after the deploy went green. The web
    service gets AuthKit's four values (pinned above); the operator console
    needs none of them and must not inherit identity-data access."""
    setup = _function_body("setup")
    assert "doug-workos-api-key" in setup
    assert "doug-workos-client-id" in setup
    after_console = setup.split("service-accounts create doug-console-sa", 1)[1]
    assert "doug-workos-api-key" not in after_console
    assert "doug-workos-client-id" not in after_console
    assert "doug-workos-cookie-password" not in after_console
    assert "doug-workos-redirect-uri" not in after_console
    after_web = setup.split("service-accounts create doug-web-sa", 1)[1].split(
        "service-accounts create doug-console-sa", 1
    )[0]
    assert "doug-workos-api-key" in after_web
    assert "doug-workos-client-id" in after_web
    assert "doug-workos-api-key" not in _function_body("console")
