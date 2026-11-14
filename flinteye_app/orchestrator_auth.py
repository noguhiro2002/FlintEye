from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Literal

from flinteye_app.orchestrator_models import AuthConfig


SESSION_VERSION = 1
PBKDF2_ALG = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 390000

Role = Literal["viewer", "admin"]


@dataclass
class AuthIdentity:
    username: str
    role: Role
    provider: str


def generate_session_secret() -> str:
    return secrets.token_urlsafe(48)


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_ALG}${iterations}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != PBKDF2_ALG:
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(_pad_b64(salt_b64))
        expected = base64.urlsafe_b64decode(_pad_b64(digest_b64))
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def authenticate_local_user(auth: AuthConfig, username: str, password: str) -> AuthIdentity | None:
    normalized = username.strip()
    if not normalized:
        return None

    admin = auth.local.admin
    if normalized == admin.username and admin.password_hash and verify_password(password, admin.password_hash):
        return AuthIdentity(username=admin.username, role="admin", provider="local")

    viewer = auth.local.viewer
    if (
        auth.viewer_auth_required
        and normalized == viewer.username
        and viewer.password_hash
        and verify_password(password, viewer.password_hash)
    ):
        return AuthIdentity(username=viewer.username, role="viewer", provider="local")

    return None


def local_auth_is_configured(auth: AuthConfig) -> bool:
    return bool(auth.session_secret and auth.local.admin.password_hash)


def create_session_value(secret: str, identity: AuthIdentity, ttl_sec: int) -> str:
    payload = {
        "v": SESSION_VERSION,
        "sub": identity.username,
        "role": identity.role,
        "provider": identity.provider,
        "iat": int(time.time()),
        "exp": int(time.time() + ttl_sec),
    }
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64encode(signature)}"


def parse_session_value(secret: str, value: str | None) -> AuthIdentity | None:
    if not secret or not value or "." not in value:
        return None
    try:
        payload_b64, sig_b64 = value.split(".", 1)
        expected_sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
        provided_sig = base64.urlsafe_b64decode(_pad_b64(sig_b64))
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(_pad_b64(payload_b64)).decode("utf-8"))
        if payload.get("v") != SESSION_VERSION:
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        role = payload.get("role")
        if role not in {"viewer", "admin"}:
            return None
        username = str(payload.get("sub", "")).strip()
        provider = str(payload.get("provider", "")).strip() or "local"
        if not username:
            return None
        return AuthIdentity(username=username, role=role, provider=provider)
    except Exception:
        return None


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _pad_b64(value: str) -> str:
    return value + "=" * (-len(value) % 4)
