"""Minimal HS256 JWT verification for authenticated API routes."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status

from .config import get_settings


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_test_token(subject: str, expires_in_seconds: int = 3600, roles: list[str] | None = None) -> str:
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64(json.dumps({"sub": subject, "exp": int(time.time()) + expires_in_seconds, "roles": roles or []}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(get_settings().jwt_signing_key.get_secret_value().encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


async def current_user(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    try:
        header, payload, signature = authorization[7:].split(".")
        decoded_header = json.loads(_unb64(header))
        if decoded_header != {"alg": "HS256", "typ": "JWT"} or len(payload) > 8192:
            raise ValueError
        expected = _b64(hmac.new(get_settings().jwt_signing_key.get_secret_value().encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        claims = json.loads(_unb64(payload))
        subject, expiry = claims.get("sub"), claims.get("exp")
        if (not hmac.compare_digest(signature, expected) or not isinstance(subject, str) or not subject or
                len(subject) > 256 or not isinstance(expiry, (int, float)) or expiry <= time.time()):
            raise ValueError
        return subject
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from None


async def optional_current_user(request: Request) -> str | None:
    """Return an authenticated subject when supplied, without requiring public endpoints to log in."""
    if not request.headers.get("Authorization"):
        return None
    return await current_user(request)


def require_role(role: str) -> Callable[[Request], Awaitable[str]]:
    async def dependency(request: Request) -> str:
        user_id = await current_user(request)
        payload = request.headers["Authorization"][7:].split(".")[1]
        claims = json.loads(_unb64(payload))
        roles = claims.get("roles", [])
        if not isinstance(roles, list) or not all(isinstance(item, str) for item in roles) or role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user_id
    return dependency
