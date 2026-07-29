"""Credential generation and hashing.

Both session tokens and API keys are opaque random strings stored only as a
SHA-256 hash. Two consequences worth being deliberate about:

- A database dump does not contain usable credentials.
- We cannot show an API key twice, so the creation endpoint returns it once and
  says so. That is a feature, not a limitation to work around.

SHA-256 rather than bcrypt here: these are 256 bits of entropy, not passwords.
There is no dictionary to attack, and key resolution happens on every single API
request — a deliberately slow hash would be a self-inflicted latency problem.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Literal

SESSION_TOKEN_BYTES = 32
API_KEY_BYTES = 32
KEY_PREFIX_LENGTH = 12


def generate_session_token() -> tuple[str, str]:
    """Return (token, token_hash). Only the hash is ever persisted."""
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    return token, hash_token(token)


def generate_api_key(environment: Literal["live", "test"]) -> tuple[str, str, str]:
    """Return (full_key, key_hash, key_prefix).

    The prefix is stored in clear so the console can identify a key in a list
    without holding anything that could be used to authenticate with it.
    """
    body = secrets.token_hex(API_KEY_BYTES)
    full_key = f"nx_{environment}_{body}"
    return full_key, hash_token(full_key), full_key[:KEY_PREFIX_LENGTH]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, expected_hash: str) -> bool:
    """Constant-time comparison. Timing differences on credential checks are a
    small leak, but a free one to close."""
    return hmac.compare_digest(hash_token(token), expected_hash)


def detect_credential_kind(value: str) -> Literal["api_key", "session", "unknown"]:
    if value.startswith(("nx_live_", "nx_test_")):
        return "api_key"
    if value:
        return "session"
    return "unknown"
