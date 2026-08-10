"""Signed, short-lived state for the GitHub installation round trip."""

import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass

_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_FIELDS = {"v", "nonce", "exp", "sub", "installation_id", "pkce_retried"}


class InstallFlowError(ValueError):
    """A deliberately non-enumerating install-flow refusal."""

    def __init__(self) -> None:
        super().__init__("invalid install flow")


class InstallFlowConfigurationError(RuntimeError):
    """The shared signing key is absent or below its security floor."""

    def __init__(self) -> None:
        super().__init__("install flow not configured")


@dataclass(frozen=True)
class InstallFlow:
    nonce: bytes
    expires_at: int
    subject: str | None
    installation_id: int | None
    pkce_retried: bool


def _secret(value: str | None) -> bytes:
    resolved = value if value is not None else os.getenv("DOUG_INSTALL_FLOW_SECRET")
    if not isinstance(resolved, str) or len(resolved.encode()) < 32:
        raise InstallFlowConfigurationError
    return resolved.encode()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise InstallFlowError
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64encode(decoded) != value:
        raise InstallFlowError
    return decoded


def _valid_payload(payload: object) -> tuple[bytes, int, str | None, int | None, bool]:
    if not isinstance(payload, dict) or set(payload) != _FIELDS or payload.get("v") != 1:
        raise InstallFlowError
    nonce_text = payload.get("nonce")
    if not isinstance(nonce_text, str) or _NONCE_PATTERN.fullmatch(nonce_text) is None:
        raise InstallFlowError
    nonce = _b64decode(nonce_text)
    if len(nonce) != 32:
        raise InstallFlowError
    expires_at = payload.get("exp")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int) or expires_at <= 0:
        raise InstallFlowError
    subject = payload.get("sub")
    if subject is not None and (not isinstance(subject, str) or not subject):
        raise InstallFlowError
    installation_id = payload.get("installation_id")
    if installation_id is not None and (
        isinstance(installation_id, bool)
        or not isinstance(installation_id, int)
        or installation_id <= 0
    ):
        raise InstallFlowError
    pkce_retried = payload.get("pkce_retried")
    if not isinstance(pkce_retried, bool):
        raise InstallFlowError
    return nonce, expires_at, subject, installation_id, pkce_retried


def seal_install_flow(
    *,
    nonce: bytes,
    expires_at: int,
    subject: str | None,
    pkce_retried: bool,
    installation_id: int | None = None,
    secret: str | None = None,
) -> str:
    signing_secret = _secret(secret)
    payload = {
        "v": 1,
        "nonce": _b64encode(nonce),
        "exp": expires_at,
        "sub": subject,
        "installation_id": installation_id,
        "pkce_retried": pkce_retried,
    }
    _valid_payload(payload)
    segment = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64encode(
        hmac.new(signing_secret, segment.encode(), hashlib.sha256).digest()
    )
    return f"{segment}.{signature}"


def verify_install_flow(
    token: str,
    *,
    now: int | None = None,
    expected_subject: str | None = None,
    expected_installation_id: int | None = None,
    secret: str | None = None,
) -> InstallFlow:
    signing_secret = _secret(secret)
    try:
        if not isinstance(token, str):
            raise InstallFlowError
        parts = token.split(".")
        if len(parts) != 2:
            raise InstallFlowError
        segment, supplied_signature = parts
        signature = _b64decode(supplied_signature)
        expected_signature = hmac.new(
            signing_secret, segment.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise InstallFlowError
        payload = json.loads(_b64decode(segment))
        nonce, expires_at, subject, installation_id, pkce_retried = _valid_payload(payload)
        current_time = int(time.time()) if now is None else now
        if expires_at <= current_time:
            raise InstallFlowError
        if expected_subject is not None and subject != expected_subject:
            raise InstallFlowError
        if (
            expected_installation_id is not None
            and installation_id != expected_installation_id
        ):
            raise InstallFlowError
        return InstallFlow(
            nonce=nonce,
            expires_at=expires_at,
            subject=subject,
            installation_id=installation_id,
            pkce_retried=pkce_retried,
        )
    except InstallFlowError:
        raise
    except Exception:
        raise InstallFlowError from None
