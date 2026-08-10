import base64
import hashlib
import hmac
import json

import pytest

from doug import install_flow

FIXTURE_SECRET = "install-flow-fixture-secret-32-bytes"
FIXTURE_NONCE = bytes(range(32))
FIXTURE_TOKEN = (
    "eyJ2IjoxLCJub25jZSI6IkFBRUNBd1FGQmdjSUNRb0xEQTBPRHhBUkVoTVVGUllYR0JrYUd4d2RIaDgi"
    "LCJleHAiOjIwMDAwMDAwMDAsInN1YiI6InVzZXJfMDFBQkMiLCJpbnN0YWxsYXRpb25faWQiOjEwMDF9"
    ".uvB2k7PQLLXOjVmscQyZ4PJo20ay1VsmfR9LZ_p34Sg"
)


def _signed(payload: dict) -> str:
    segment = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=")
    signature = base64.urlsafe_b64encode(
        hmac.new(FIXTURE_SECRET.encode(), segment, hashlib.sha256).digest()
    ).rstrip(b"=")
    return f"{segment.decode()}.{signature.decode()}"


def test_python_and_typescript_share_one_exact_install_flow_fixture():
    token = install_flow.seal_install_flow(
        nonce=FIXTURE_NONCE,
        expires_at=2_000_000_000,
        subject="user_01ABC",
        installation_id=1001,
        secret=FIXTURE_SECRET,
    )
    assert token == FIXTURE_TOKEN

    flow = install_flow.verify_install_flow(
        FIXTURE_TOKEN,
        now=1_999_999_999,
        expected_subject="user_01ABC",
        expected_installation_id=1001,
        secret=FIXTURE_SECRET,
    )
    assert flow.nonce == FIXTURE_NONCE
    assert flow.subject == "user_01ABC"
    assert flow.installation_id == 1001
    assert flow.expires_at == 2_000_000_000


def test_pre_auth_flow_may_have_no_subject_but_cannot_satisfy_an_expected_subject():
    token = install_flow.seal_install_flow(
        nonce=FIXTURE_NONCE,
        expires_at=2_000_000_000,
        subject=None,
        installation_id=1001,
        secret=FIXTURE_SECRET,
    )
    flow = install_flow.verify_install_flow(
        token, now=1_999_999_999, secret=FIXTURE_SECRET
    )
    assert flow.subject is None

    with pytest.raises(install_flow.InstallFlowError, match="^invalid install flow$"):
        install_flow.verify_install_flow(
            token,
            now=1_999_999_999,
            expected_subject="user_01ABC",
            secret=FIXTURE_SECRET,
        )


@pytest.mark.parametrize(
    ("token", "now", "subject", "installation_id"),
    [
        (FIXTURE_TOKEN[:-1] + "A", 1_999_999_999, "user_01ABC", 1001),
        (FIXTURE_TOKEN, 2_000_000_000, "user_01ABC", 1001),
        (FIXTURE_TOKEN, 1_999_999_999, "user_attacker", 1001),
        (FIXTURE_TOKEN, 1_999_999_999, "user_01ABC", 1002),
        (
            _signed(
                {
                    "v": 2,
                    "nonce": base64.urlsafe_b64encode(FIXTURE_NONCE).rstrip(b"=").decode(),
                    "exp": 2_000_000_000,
                    "sub": "user_01ABC",
                    "installation_id": 1001,
                }
            ),
            1_999_999_999,
            "user_01ABC",
            1001,
        ),
        (
            _signed(
                {
                    "v": 1,
                    "nonce": "dG9vLXNob3J0",
                    "exp": 2_000_000_000,
                    "sub": "user_01ABC",
                    "installation_id": 1001,
                }
            ),
            1_999_999_999,
            "user_01ABC",
            1001,
        ),
    ],
)
def test_flow_verification_refuses_every_untrusted_boundary(
    token, now, subject, installation_id
):
    with pytest.raises(install_flow.InstallFlowError, match="^invalid install flow$"):
        install_flow.verify_install_flow(
            token,
            now=now,
            expected_subject=subject,
            expected_installation_id=installation_id,
            secret=FIXTURE_SECRET,
        )


def test_missing_secret_and_errors_never_echo_sensitive_flow_material(monkeypatch):
    monkeypatch.delenv("DOUG_INSTALL_FLOW_SECRET", raising=False)
    secret = "secret-that-must-not-appear"
    raw_nonce = "raw-nonce-that-must-not-appear"
    bad_token = f"{FIXTURE_TOKEN}.{raw_nonce}.{secret}"

    with pytest.raises(install_flow.InstallFlowError) as caught:
        install_flow.verify_install_flow(bad_token)

    message = str(caught.value)
    assert message == "invalid install flow"
    assert FIXTURE_TOKEN not in message
    assert raw_nonce not in message
    assert secret not in message
