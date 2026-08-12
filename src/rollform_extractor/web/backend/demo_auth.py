"""Small, dependency-free customer-demo authentication boundary."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque


COOKIE_NAME = "rollform_demo_session"
_failed_logins: dict[str, deque[float]] = defaultdict(deque)


def enabled() -> bool:
    return str(os.environ.get("DEMO_AUTH_ENABLED", "false")).lower() in {"1", "true", "yes"}


def _secret() -> bytes:
    return os.environ.get("DEMO_SESSION_SECRET", "").encode("utf-8")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return "pbkdf2_sha256$310000$%s$%s" % (
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def valid_password_hash(encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256" or int(iterations) < 200_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        digest = base64.urlsafe_b64decode(digest_text.encode())
        return len(salt) >= 16 and len(digest) >= 32
    except (TypeError, ValueError):
        return False


def configuration_errors() -> list[str]:
    if not enabled():
        return []
    errors: list[str] = []
    username = os.environ.get("DEMO_USERNAME", "")
    password_hash = os.environ.get("DEMO_PASSWORD_HASH", "")
    session_secret = os.environ.get("DEMO_SESSION_SECRET", "")
    if not username.strip():
        errors.append("DEMO_USERNAME is required when demo auth is enabled")
    if not valid_password_hash(password_hash):
        errors.append("DEMO_PASSWORD_HASH must be a valid PBKDF2-SHA256 hash")
    if len(session_secret.encode("utf-8")) < 32:
        errors.append("DEMO_SESSION_SECRET must contain at least 32 bytes")
    try:
        ttl = int(os.environ.get("DEMO_SESSION_TTL_SECONDS", "28800"))
        if ttl < 300 or ttl > 86400:
            errors.append("DEMO_SESSION_TTL_SECONDS must be between 300 and 86400")
    except ValueError:
        errors.append("DEMO_SESSION_TTL_SECONDS must be an integer")
    return errors


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def login_allowed(ip: str, now: float | None = None) -> bool:
    now = now or time.time()
    attempts = _failed_logins[ip]
    while attempts and attempts[0] <= now - 600:
        attempts.popleft()
    return len(attempts) < 5


def record_failed_login(ip: str, now: float | None = None) -> None:
    _failed_logins[ip].append(now or time.time())


def issue_session(username: str, now: int | None = None) -> str:
    timestamp = int(now or time.time())
    nonce = secrets.token_urlsafe(24)
    payload = f"{username}:{timestamp}:{nonce}"
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()


def valid_session(value: str | None, now: int | None = None) -> bool:
    if not value or not _secret():
        return False
    try:
        decoded = base64.urlsafe_b64decode(value.encode()).decode()
        username, timestamp_text, nonce, signature = decoded.split(":", 3)
        timestamp = int(timestamp_text)
        if not username or not nonce:
            return False
        ttl = int(os.environ.get("DEMO_SESSION_TTL_SECONDS", "28800"))
        current = int(now or time.time())
        if timestamp > current + 30 or current - timestamp > ttl:
            return False
        payload = f"{username}:{timestamp}:{nonce}"
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (ValueError, TypeError, UnicodeDecodeError):
        return False
