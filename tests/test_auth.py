"""Credential handling. These are the tests worth having before anything else
depends on the Principal being correct."""

from __future__ import annotations

import pytest

from nexus.auth.tokens import (
    detect_credential_kind,
    generate_api_key,
    generate_session_token,
    hash_token,
    verify_token,
)


def test_api_keys_are_unique_and_prefixed() -> None:
    first, first_hash, prefix = generate_api_key("live")
    second, second_hash, _ = generate_api_key("live")
    assert first != second
    assert first_hash != second_hash
    assert first.startswith("nx_live_")
    assert prefix == first[:12]


def test_only_the_hash_would_be_stored() -> None:
    key, key_hash, prefix = generate_api_key("test")
    # The stored artefacts must not contain enough to reconstruct the key.
    assert key not in key_hash
    assert key[12:] not in prefix
    assert verify_token(key, key_hash)
    assert not verify_token(key + "x", key_hash)


def test_session_token_and_hash_agree() -> None:
    token, token_hash = generate_session_token()
    assert hash_token(token) == token_hash
    assert verify_token(token, token_hash)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("nx_live_abc123", "api_key"),
        ("nx_test_abc123", "api_key"),
        ("some-opaque-session-token", "session"),
        ("", "unknown"),
    ],
)
def test_credential_kind_detection(value: str, expected: str) -> None:
    assert detect_credential_kind(value) == expected
