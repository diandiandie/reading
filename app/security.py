from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from uuid import UUID

from .config import SESSION_SECRET


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000)
    return f"pbkdf2_sha256${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt_b64, digest_b64 = stored.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_session_token(user_id: UUID) -> str:
    issued_at = str(int(time.time()))
    payload = f"{user_id}.{issued_at}"
    signature = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_session_token(token: str, max_age_seconds: int = 60 * 60 * 24 * 30) -> str | None:
    try:
        user_id, issued_at, signature = token.split(".", 2)
        payload = f"{user_id}.{issued_at}"
        expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(time.time()) - int(issued_at) > max_age_seconds:
            return None
        return user_id
    except Exception:
        return None
