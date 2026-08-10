"""Executable contract for the production session-isolation proof.

The fake sits at the external HTTP boundary.  The shell script itself remains
real: it validates its inputs, decodes the fixture claims, sequences the human
pause, calls curl, evaluates jq predicates, and aggregates the nine gates.
"""

from __future__ import annotations

import ast
import base64
import json
import os
import re
import select
import signal
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = API_ROOT / "deploy" / "prove-session-isolation.sh"
API_SOURCE = API_ROOT / "doug" / "api.py"
RESPONSE_SECRET = "server-response-body-must-stay-private"


def _jwt(payload: dict[str, object], signature: str) -> str:
    def encode(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{encode({'alg': 'RS256', 'typ': 'JWT'})}.{encode(payload)}.{signature}"


@pytest.fixture
def proof_env() -> dict[str, str]:
    return {
        "DOUG_URL": "https://doug-proof.test",
        "A_SESSION_JWT": _jwt(
            {"sub": "user-shared", "org_id": "org-a"}, "a-signature"
        ),
        "A_INSTALLATION_ID": "101",
        "B_SESSION_JWT": _jwt(
            {"sub": "user-shared", "org_id": "org-b"}, "b-signature"
        ),
        "B_INSTALLATION_ID": "202",
        "ONE_REPO_SESSION_JWT": _jwt(
            {"sub": "user-limited", "org_id": "org-a"}, "one-signature"
        ),
        "ONE_REPO_ALLOWED": "alpha/allowed",
        "ONE_REPO_FORBIDDEN": "alpha/forbidden",
        "ORGLESS_SESSION_JWT": _jwt({"sub": "user-orgless"}, "orgless-signature"),
        "EXPIRED_SESSION_JWT": _jwt(
            {"sub": "user-shared", "org_id": "org-a", "exp": 1},
            "expired-signature",
        ),
        "UNMAPPED_ORG_SESSION_JWT": _jwt(
            {"sub": "user-unmapped", "org_id": "org-unmapped"},
            "unmapped-signature",
        ),
        "READ_ONLY_SESSION_JWT": _jwt(
            {"sub": "user-read-only"}, "read-only-signature"
        ),
        "READ_ONLY_INSTALLATION_ID": "303",
        "DOUG_SESSION_PROOF_ACK": (
            "I ACCEPT SCORE SPEND AND DISPOSABLE BIND 303"
        ),
    }


FAKE_CURL = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

args = sys.argv[1:]
method = "GET"
output = None
data = ""
headers = []
url = ""
connect_timeout = None
max_time = None
i = 0
while i < len(args):
    arg = args[i]
    if arg == "-X":
        method = args[i + 1]
        i += 2
    elif arg == "-o":
        output = args[i + 1]
        i += 2
    elif arg == "-w":
        i += 2
    elif arg == "-H":
        headers.append(args[i + 1])
        i += 2
    elif arg == "-d":
        data = args[i + 1]
        i += 2
    elif arg == "--connect-timeout":
        connect_timeout = args[i + 1]
        i += 2
    elif arg == "--max-time":
        max_time = args[i + 1]
        i += 2
    elif arg.startswith("https://"):
        url = arg
        i += 1
    else:
        i += 1

if not output or not url:
    raise SystemExit(91)

authorization = ""
header_names = []
for header in headers:
    name, _, value = header.partition(":")
    header_names.append(name.strip().lower())
    if name.strip().lower() == "authorization":
        authorization = value.strip()
token = authorization.removeprefix("Bearer ")

known = {
    os.environ[name]: kind
    for name, kind in {
        "A_SESSION_JWT": "a",
        "B_SESSION_JWT": "b",
        "ONE_REPO_SESSION_JWT": "one",
        "ORGLESS_SESSION_JWT": "orgless",
        "EXPIRED_SESSION_JWT": "expired",
        "UNMAPPED_ORG_SESSION_JWT": "unmapped",
        "READ_ONLY_SESSION_JWT": "read_only",
    }.items()
}
kind = known.get(token, "tampered")
mode = os.environ.get("FAKE_MODE", "success")
parsed = urlsplit(url)
path = parsed.path + (("?" + parsed.query) if parsed.query else "")
query = parse_qs(parsed.query)
log_path = Path(os.environ["FAKE_CURL_LOG"])
prior = []
if log_path.exists():
    prior = [json.loads(line) for line in log_path.read_text().splitlines() if line]


def run_body(installation_id, repo):
    return {
        "items": [
            {
                "installation_id": installation_id,
                "repo": name,
                "verdict_id": index + 1,
            }
            for index, name in enumerate(repo if isinstance(repo, list) else [repo])
        ],
        "limit": 100,
        "offset": 0,
        "proof_secret": os.environ["FAKE_RESPONSE_SECRET"],
    }


status = 500
body = {"detail": os.environ["FAKE_RESPONSE_SECRET"]}
if parsed.path == "/v1/sessions/connections":
    status = 200
    if kind == "read_only":
        bound = mode == "bind_success" and Path(os.environ["FAKE_BIND_STATE"]).exists()
        body = {
            "connections": [
                {
                    "provider": "github",
                    "installation_id": int(os.environ["READ_ONLY_INSTALLATION_ID"]),
                    "organization_id": "org-bound" if bound else None,
                    "account_login": "read-only-fixture",
                    "account_type": "Organization",
                    "status": "ready" if bound else "setup_required",
                    "label": None,
                    "repositories": [
                        {"github_repo_id": 30301, "full_name": "read-only/repo"}
                    ],
                }
            ],
            "proof_secret": os.environ["FAKE_RESPONSE_SECRET"],
        }
    else:
        body = {
            "connections": [],
            "proof_secret": os.environ["FAKE_RESPONSE_SECRET"],
        }
elif parsed.path == "/v1/sessions/runs":
    repo = query.get("repo", ["all"])[0]
    a_all_count = sum(
        1
        for item in prior
        if item["kind"] == "a" and item["path"] == "/v1/sessions/runs?repo=all"
    )
    if kind == "a":
        if repo == "all":
            if mode == "pre_suspend_failure" and a_all_count == 1:
                status = 500
            elif a_all_count == 2:
                status = 200 if mode == "suspended_success" else 401
            elif mode == "never_restore" and a_all_count >= 3:
                status = 401
            elif mode == "delayed_restore" and a_all_count == 3:
                status = 401
            else:
                status = 200
                body = run_body(
                    int(os.environ["A_INSTALLATION_ID"]),
                    [os.environ["ONE_REPO_ALLOWED"], os.environ["ONE_REPO_FORBIDDEN"]],
                )
                if mode == "a_row_leak" and a_all_count == 0:
                    body["items"].append(
                        {
                            "installation_id": int(os.environ["B_INSTALLATION_ID"]),
                            "repo": "beta/repo",
                            "verdict_id": 99,
                        }
                    )
        elif repo == os.environ["ONE_REPO_FORBIDDEN"]:
            status = 200
            body = run_body(int(os.environ["A_INSTALLATION_ID"]), repo)
        else:
            status = 404
    elif kind == "b":
        status = 200
        body = run_body(int(os.environ["B_INSTALLATION_ID"]), "beta/repo")
        if mode == "b_row_leak":
            body["items"].append(
                {
                    "installation_id": int(os.environ["A_INSTALLATION_ID"]),
                    "repo": os.environ["ONE_REPO_ALLOWED"],
                    "verdict_id": 98,
                }
            )
    elif kind == "one":
        if repo in ("all", os.environ["ONE_REPO_ALLOWED"]):
            status = 200
            body = run_body(int(os.environ["A_INSTALLATION_ID"]), os.environ["ONE_REPO_ALLOWED"])
            if mode == "one_repo_leak" and repo == "all":
                body["items"].append(
                    {
                        "installation_id": int(os.environ["A_INSTALLATION_ID"]),
                        "repo": os.environ["ONE_REPO_FORBIDDEN"],
                        "verdict_id": 97,
                    }
                )
        else:
            status = 404
            if mode == "forbidden_body_mismatch" and repo == os.environ["ONE_REPO_FORBIDDEN"]:
                body = {"detail": "different-denial-envelope"}
    elif kind == "orgless":
        status = 200 if mode == "orgless_data_success" else 401
        if status == 200:
            body = run_body(int(os.environ["A_INSTALLATION_ID"]), os.environ["ONE_REPO_ALLOWED"])
    elif kind in ("tampered", "expired"):
        status = 200 if mode == "invalid_token_success" else 401
        if status == 200:
            body = run_body(int(os.environ["A_INSTALLATION_ID"]), os.environ["ONE_REPO_ALLOWED"])
    elif kind == "unmapped":
        status = 200 if mode == "unmapped_org_success" else 401
        if status == 200:
            body = run_body(int(os.environ["A_INSTALLATION_ID"]), os.environ["ONE_REPO_ALLOWED"])
elif parsed.path == "/v1/installations/bind" and method == "POST":
    if mode == "bind_success":
        status = 204
        Path(os.environ["FAKE_BIND_STATE"]).touch()
    elif mode == "bind_hidden_side_effect":
        status = 404
        Path(os.environ["FAKE_WORKOS_SIDE_EFFECT"]).touch()
    else:
        status = 404
elif parsed.path in {
    "/v1/score/read",
    "/v1/runs",
    "/v1/runs/1",
    "/v1/health",
    "/v1/jobs",
    "/v1/patterns",
}:
    status = 401
    if parsed.path == "/v1/score/read":
        try:
            score_body = json.loads(data)
        except json.JSONDecodeError:
            score_body = None
        if score_body != {
            "pr": {
                "number": 1,
                "title": "session-isolation-proof",
                "author": "proof",
            },
            "diff": "",
        }:
            status = 422
    if mode == "operator_route_success" and parsed.path == "/v1/health":
        status = 200

record = {
    "method": method,
    "path": path,
    "kind": kind,
    "status": status,
    "output": output,
    "connect_timeout": connect_timeout,
    "max_time": max_time,
    "header_names": sorted(header_names),
    "data": data,
}
with log_path.open("a") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\n")
Path(output).write_text(json.dumps(body))
print(status, end="", flush=True)
'''


def _proof_process_env(
    tmp_path: Path,
    proof_env: dict[str, str],
    *,
    mode: str = "success",
    overrides: dict[str, str | None] | None = None,
) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(FAKE_CURL.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
    fake_curl.chmod(0o755)
    log = tmp_path / "curl.jsonl"
    env = os.environ.copy()
    env.update(proof_env)
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_MODE": mode,
            "FAKE_CURL_LOG": str(log),
            "FAKE_BIND_STATE": str(tmp_path / "bound"),
            "FAKE_WORKOS_SIDE_EFFECT": str(tmp_path / "workos-side-effect"),
            "FAKE_RESPONSE_SECRET": RESPONSE_SECRET,
        }
    )
    for name, value in (overrides or {}).items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env, log


def _run_proof(
    tmp_path: Path,
    proof_env: dict[str, str],
    *,
    mode: str = "success",
    overrides: dict[str, str | None] | None = None,
    stdin: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]]]:
    env, log = _proof_process_env(
        tmp_path, proof_env, mode=mode, overrides=overrides
    )
    completed = subprocess.run(
        [str(SCRIPT)],
        cwd=API_ROOT,
        env=env,
        input=stdin
        if stdin is not None
        else (
            f"SUSPENDED {proof_env['A_INSTALLATION_ID']}\n"
            f"RESTORED {proof_env['A_INSTALLATION_ID']}\n"
        ),
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    requests = (
        [json.loads(line) for line in log.read_text().splitlines() if line]
        if log.exists()
        else []
    )
    return completed, requests


def _combined(completed: subprocess.CompletedProcess[str]) -> str:
    return completed.stdout + completed.stderr


def _signal_at_prompt(
    tmp_path: Path,
    proof_env: dict[str, str],
    *,
    prompt: str,
    signal_number: signal.Signals,
    stdin_before_prompt: str = "",
) -> tuple[int, str, list[dict[str, object]]]:
    env, log = _proof_process_env(tmp_path, proof_env)
    process = subprocess.Popen(
        [str(SCRIPT)],
        cwd=API_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stderr is not None
    if stdin_before_prompt:
        process.stdin.write(stdin_before_prompt.encode())
        process.stdin.flush()
    prompt_bytes = prompt.encode()
    stderr_before_signal = b""
    while prompt_bytes not in stderr_before_signal:
        ready, _, _ = select.select([process.stderr], [], [], 5)
        assert ready, f"proof never reached prompt: {prompt}"
        chunk = os.read(process.stderr.fileno(), 4096)
        assert chunk, f"proof exited before prompt: {prompt}"
        stderr_before_signal += chunk

    os.kill(process.pid, signal_number)
    stdout_after, stderr_after = process.communicate(timeout=5)
    requests = (
        [json.loads(line) for line in log.read_text().splitlines() if line]
        if log.exists()
        else []
    )
    assert process.returncode is not None
    output = stdout_after + stderr_before_signal + stderr_after
    return process.returncode, output.decode(errors="replace"), requests


def test_success_proves_nine_gates_without_leaking_secrets(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """Removing any complete gate or printing a body/token breaks this receipt."""
    completed, requests = _run_proof(tmp_path, proof_env)

    assert completed.returncode == 0, _combined(completed)
    lines = _combined(completed).splitlines()
    assert len([line for line in lines if line.startswith("PASS  gate ")]) == 9
    assert not [line for line in lines if line.startswith("FAIL  gate ")]
    assert "9 passed, 0 failed" in _combined(completed)
    assert "CONTROLLED-ADVERSARIAL PROBE" in _combined(completed)
    assert "ACKNOWLEDGEMENT IS NOT PRODUCTION APPROVAL" in _combined(completed)
    assert "read-only" not in _combined(completed).lower()
    assert proof_env["DOUG_SESSION_PROOF_ACK"] not in _combined(completed)
    assert RESPONSE_SECRET not in _combined(completed)
    for secret in [*proof_env.values(), RESPONSE_SECRET]:
        if "JWT" not in secret and not secret.count(".") == 2:
            continue
        assert secret not in _combined(completed)

    a_reads = [
        item["status"]
        for item in requests
        if item["kind"] == "a" and item["path"] == "/v1/sessions/runs?repo=all"
    ]
    assert a_reads == [200, 200, 401, 200]
    response_files = {str(item["output"]) for item in requests}
    assert len(response_files) == 1
    assert not Path(response_files.pop()).exists()
    assert {item["connect_timeout"] for item in requests} == {"5"}
    assert {item["max_time"] for item in requests} == {"20"}


@pytest.mark.parametrize(
    ("mode", "failed_gate"),
    [
        ("a_row_leak", 1),
        ("b_row_leak", 2),
        ("one_repo_leak", 3),
        ("orgless_data_success", 4),
        ("suspended_success", 5),
        ("invalid_token_success", 6),
        ("unmapped_org_success", 7),
        ("operator_route_success", 8),
        ("bind_success", 9),
    ],
)
def test_each_hostile_boundary_fails_only_its_named_gate(
    tmp_path: Path,
    proof_env: dict[str, str],
    mode: str,
    failed_gate: int,
) -> None:
    """Weakening a gate cannot be hidden by another subcheck's aggregate."""
    completed, _ = _run_proof(tmp_path, proof_env, mode=mode)
    output = _combined(completed)

    assert completed.returncode != 0
    assert f"FAIL  gate {failed_gate} " in output
    assert len([line for line in output.splitlines() if line.startswith("FAIL  gate ")]) == 1
    assert len([line for line in output.splitlines() if line.startswith("PASS  gate ")]) == 8
    assert "8 passed, 1 failed" in output
    assert RESPONSE_SECRET not in output
    for name in (
        "A_SESSION_JWT",
        "B_SESSION_JWT",
        "ONE_REPO_SESSION_JWT",
        "ORGLESS_SESSION_JWT",
        "EXPIRED_SESSION_JWT",
        "UNMAPPED_ORG_SESSION_JWT",
        "READ_ONLY_SESSION_JWT",
    ):
        assert proof_env[name] not in output


@pytest.mark.parametrize(
    "overrides",
    [
        {"A_SESSION_JWT": None},
        {"DOUG_SESSION_PROOF_ACK": None},
        {"DOUG_SESSION_PROOF_ACK": "I ACCEPT SCORE SPEND"},
        {
            "DOUG_SESSION_PROOF_ACK": (
                "I ACCEPT SCORE SPEND AND DISPOSABLE BIND 999"
            )
        },
        {"DOUG_URL": "http://doug-proof.test"},
        {"DOUG_URL": "https://doug-proof.test/"},
        {"DOUG_URL": "https://user@doug-proof.test"},
        {"DOUG_URL": "https://doug-proof.test?redirect=elsewhere"},
        {"DOUG_URL": "https://doug-proof.test#fragment"},
        {"A_INSTALLATION_ID": "0"},
        {"B_INSTALLATION_ID": "not-an-id"},
        {"READ_ONLY_INSTALLATION_ID": "-3"},
        {"A_INSTALLATION_ID": "202"},
        {"ORGLESS_SESSION_JWT": "not-a-jwt"},
        {
            "ORGLESS_SESSION_JWT": _jwt(
                {"sub": "user-orgless", "org_id": "org-a"},
                "orgless-with-org",
            )
        },
        {"ORGLESS_SESSION_JWT": _jwt({"sub": ""}, "orgless-empty-sub")},
        {
            "UNMAPPED_ORG_SESSION_JWT": _jwt(
                {"sub": "user-unmapped"}, "unmapped-without-org"
            )
        },
        {
            "UNMAPPED_ORG_SESSION_JWT": _jwt(
                {"sub": "user-unmapped", "org_id": "org-a"},
                "unmapped-a-org",
            )
        },
        {
            "UNMAPPED_ORG_SESSION_JWT": _jwt(
                {"sub": "user-unmapped", "org_id": "org-b"},
                "unmapped-b-org",
            )
        },
        {
            "EXPIRED_SESSION_JWT": _jwt(
                {"sub": "user-shared", "org_id": "org-a", "exp": 4_102_444_800},
                "expired-future",
            )
        },
        {
            "EXPIRED_SESSION_JWT": _jwt(
                {"sub": "wrong-user", "org_id": "org-a", "exp": 1},
                "expired-wrong-sub",
            )
        },
        {
            "EXPIRED_SESSION_JWT": _jwt(
                {"sub": "user-shared", "org_id": "org-b", "exp": 1},
                "expired-wrong-org",
            )
        },
        {
            "EXPIRED_SESSION_JWT": _jwt(
                {"sub": "user-shared", "org_id": "org-a", "exp": "old"},
                "expired-string-exp",
            )
        },
        {
            "B_SESSION_JWT": _jwt(
                {"sub": "different-user", "org_id": "org-b"}, "wrong-sub"
            )
        },
        {
            "B_SESSION_JWT": _jwt(
                {"sub": "user-shared", "org_id": "org-a"}, "same-org"
            )
        },
        {
            "ONE_REPO_SESSION_JWT": _jwt(
                {"sub": "user-shared", "org_id": "org-a"}, "same-user"
            )
        },
        {"ONE_REPO_ALLOWED": "not-a-full-name"},
    ],
)
def test_preflight_rejects_bad_fixtures_before_any_http_request(
    tmp_path: Path,
    proof_env: dict[str, str],
    overrides: dict[str, str | None],
) -> None:
    """A malformed authority fixture must never reach the production origin."""
    completed, requests = _run_proof(tmp_path, proof_env, overrides=overrides)

    assert completed.returncode != 0
    assert requests == []
    assert RESPONSE_SECRET not in _combined(completed)


def _operator_only_routes() -> set[tuple[str, str]]:
    tree = ast.parse(API_SOURCE.read_text())
    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls_operator_gate = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "_operator_only"
            for child in ast.walk(node)
        )
        if not calls_operator_gate:
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                concrete_path = re.sub(r"\{[^}]+\}", "1", decorator.args[0].value)
                routes.add((decorator.func.attr.upper(), concrete_path))
    return routes


def test_operator_inventory_is_derived_from_api_and_exercised_with_bearer_only(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """Adding/removing an operator-only caller makes the executable inventory drift."""
    completed, requests = _run_proof(tmp_path, proof_env)
    assert completed.returncode == 0, _combined(completed)

    start = next(
        index + 1
        for index, item in enumerate(requests)
        if item["kind"] == "unmapped" and item["path"] == "/v1/sessions/runs?repo=all"
    )
    end = next(
        index
        for index, item in enumerate(requests[start:], start=start)
        if item["kind"] == "read_only"
        and item["path"] == "/v1/sessions/connections"
    )
    exercised = {
        (str(item["method"]), urlsplit(str(item["path"])).path)
        for item in requests[start:end]
    }

    assert exercised == _operator_only_routes()
    assert len(exercised) == 6
    assert all(item["kind"] == "a" for item in requests[start:end])
    assert all("authorization" in item["header_names"] for item in requests)
    assert all("x-doug-token" not in item["header_names"] for item in requests)
    assert all(
        set(item["header_names"]) <= {"authorization", "content-type"}
        for item in requests
    )
    score_probe = next(
        item for item in requests[start:end] if item["path"] == "/v1/score/read"
    )
    assert json.loads(str(score_probe["data"])) == {
        "pr": {"number": 1, "title": "session-isolation-proof", "author": "proof"},
        "diff": "",
    }


def test_confirmation_typos_retry_without_making_an_api_request(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """A typo cannot advance either human boundary or trigger its next read."""
    completed, requests = _run_proof(
        tmp_path,
        proof_env,
        stdin=(
            "WRONG\n"
            f"SUSPENDED {proof_env['A_INSTALLATION_ID']}\n"
            "STILL WRONG\n"
            f"RESTORED {proof_env['A_INSTALLATION_ID']}\n"
        ),
    )

    assert completed.returncode == 0, _combined(completed)
    assert _combined(completed).count("reason=confirmation-retry") == 2
    a_reads = [
        item["status"]
        for item in requests
        if item["kind"] == "a" and item["path"] == "/v1/sessions/runs?repo=all"
    ]
    assert a_reads == [200, 200, 401, 200]


def test_failed_restore_check_loops_until_a_nonempty_scoped_read_succeeds(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """A literal restore claim alone cannot clear the suspended cleanup state."""
    installation_id = proof_env["A_INSTALLATION_ID"]
    completed, requests = _run_proof(
        tmp_path,
        proof_env,
        mode="delayed_restore",
        stdin=(
            f"SUSPENDED {installation_id}\n"
            f"RESTORED {installation_id}\n"
            f"RESTORED {installation_id}\n"
        ),
    )

    assert completed.returncode == 0, _combined(completed)
    assert "reason=restoration-not-observed" in _combined(completed)
    a_reads = [
        item["status"]
        for item in requests
        if item["kind"] == "a" and item["path"] == "/v1/sessions/runs?repo=all"
    ]
    assert a_reads == [200, 200, 401, 401, 200]


def test_eof_after_suspension_exits_with_unresolved_restoration_warning(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """Closed stdin cannot turn an unverified restoration into normal completion."""
    completed, _ = _run_proof(
        tmp_path,
        proof_env,
        stdin=f"SUSPENDED {proof_env['A_INSTALLATION_ID']}\n",
    )

    assert completed.returncode != 0
    assert "RESTORATION REQUIRED" in _combined(completed)
    assert "reason=input-ended" in _combined(completed)
    assert "EXIT GATE: PROVEN" not in _combined(completed)


def test_eof_at_suspend_prompt_warns_and_executes_no_later_gate(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """The human instruction itself arms recovery before confirmation exists."""
    completed, requests = _run_proof(tmp_path, proof_env, stdin="")
    output = _combined(completed)

    assert completed.returncode != 0
    assert "RESTORATION REQUIRED" in output
    assert "reason=input-ended" in output
    assert "SIGKILL" in completed.stderr
    assert "terminal loss" in completed.stderr
    assert "operator disappearance" in completed.stderr
    assert "manual recovery" in completed.stderr
    assert completed.stderr.index("SIGKILL") < completed.stderr.index(
        "type exactly: SUSPENDED"
    )
    assert not any(
        item["kind"] in {"tampered", "expired", "unmapped", "read_only"}
        for item in requests
    )
    assert all(f"gate {number}" not in output for number in range(6, 10))


@pytest.mark.parametrize(
    ("signal_number", "signal_name"),
    [(signal.SIGINT, "INT"), (signal.SIGTERM, "TERM")],
)
def test_signal_at_suspend_prompt_warns_and_executes_no_later_gate(
    tmp_path: Path,
    proof_env: dict[str, str],
    signal_number: signal.Signals,
    signal_name: str,
) -> None:
    """INT and TERM at the first mutation instruction cannot exit silently."""
    returncode, output, requests = _signal_at_prompt(
        tmp_path,
        proof_env,
        prompt="type exactly: SUSPENDED",
        signal_number=signal_number,
    )

    assert returncode != 0
    assert "RESTORATION REQUIRED" in output
    assert f"reason=signal-{signal_name}" in output
    assert "SIGKILL" in output
    assert not any(
        item["kind"] in {"tampered", "expired", "unmapped", "read_only"}
        for item in requests
    )
    assert all(f"gate {number}" not in output for number in range(6, 10))


def test_failed_pre_suspend_read_never_arms_or_prints_mutation_instruction(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """Without a clean A read, the proof gives the human no suspension instruction."""
    completed, _ = _run_proof(
        tmp_path,
        proof_env,
        mode="pre_suspend_failure",
        stdin="",
    )
    output = _combined(completed)

    assert completed.returncode != 0
    assert "type exactly: SUSPENDED" not in output
    assert "RESTORATION REQUIRED" not in output
    assert "SIGKILL" not in output


@pytest.mark.parametrize(
    ("signal_number", "signal_name"),
    [(signal.SIGINT, "INT"), (signal.SIGTERM, "TERM")],
)
def test_signal_after_suspension_warns_that_restoration_is_unresolved(
    tmp_path: Path,
    proof_env: dict[str, str],
    signal_number: signal.Signals,
    signal_name: str,
) -> None:
    """INT and TERM cannot silently abandon a confirmed suspension."""
    returncode, output, _ = _signal_at_prompt(
        tmp_path,
        proof_env,
        prompt="type exactly: RESTORED",
        signal_number=signal_number,
        stdin_before_prompt=f"SUSPENDED {proof_env['A_INSTALLATION_ID']}\n",
    )

    assert returncode != 0
    assert "RESTORATION REQUIRED" in output
    assert f"reason=signal-{signal_name}" in output
    assert "EXIT GATE: PROVEN" not in output


def test_fake_that_never_restores_cannot_reach_a_successful_exit(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """Repeated 401 cleanup reads keep the exit gate unresolved and nonzero."""
    installation_id = proof_env["A_INSTALLATION_ID"]
    completed, _ = _run_proof(
        tmp_path,
        proof_env,
        mode="never_restore",
        stdin=(
            f"SUSPENDED {installation_id}\n"
            f"RESTORED {installation_id}\n"
        ),
    )

    assert completed.returncode != 0
    assert "RESTORATION REQUIRED" in _combined(completed)
    assert "reason=input-ended" in _combined(completed)
    assert "EXIT GATE: PROVEN" not in _combined(completed)


def test_forbidden_repo_denial_must_match_absent_repo_canonical_body(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """A distinct denial envelope is an existence leak even when both statuses are 404."""
    completed, _ = _run_proof(tmp_path, proof_env, mode="forbidden_body_mismatch")
    output = _combined(completed)

    assert completed.returncode != 0
    assert "FAIL  gate 3 " in output
    assert len([line for line in output.splitlines() if line.startswith("FAIL  gate ")]) == 1
    assert RESPONSE_SECRET not in output
    assert "different-denial-envelope" not in output


def test_denied_bind_acknowledges_unobservable_hidden_workos_side_effect(
    tmp_path: Path, proof_env: dict[str, str]
) -> None:
    """A 404 brackets Doug state but cannot prove WorkOS stayed untouched."""
    completed, _ = _run_proof(tmp_path, proof_env, mode="bind_hidden_side_effect")

    assert completed.returncode == 0, _combined(completed)
    assert (tmp_path / "workos-side-effect").exists()
    assert "CONTROLLED-ADVERSARIAL PROBE" in _combined(completed)
    assert "DISPOSABLE" in proof_env["DOUG_SESSION_PROOF_ACK"]
