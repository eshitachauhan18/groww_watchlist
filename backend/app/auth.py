from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict

PBKDF2_ITERATIONS = 200_000
SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 100

RATE_LIMIT_WINDOW_SECONDS = 300
RATE_LIMIT_MAX_ATTEMPTS = 5
_attempts: dict[str, list[float]] = defaultdict(list)
_attempts_lock = threading.Lock()


def validate_username(username: str) -> bool:
    return bool(USERNAME_RE.match(username))


def validate_password(password: str) -> bool:
    return MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


def new_session_token() -> tuple[str, str]:
    """Returns (raw_token_for_client, hash_for_storage)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def check_rate_limit(key: str) -> bool:
    """Sliding-window limiter for login/register attempts (brute-force /
    account-spam protection). Returns True if this attempt is allowed (and
    records it); False if the key has hit the limit within the window."""
    now = time.time()
    with _attempts_lock:
        attempts = _attempts[key]
        attempts[:] = [t for t in attempts if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if len(attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
            return False
        attempts.append(now)
        return True


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()