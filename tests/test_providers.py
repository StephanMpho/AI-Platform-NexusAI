"""Error normalisation is the contract everything downstream depends on, so it
gets a test per branch rather than a glance."""

from __future__ import annotations

import pytest

from nexus.providers import CompletionRequest
from nexus.providers.errors import (
    AuthError,
    ContentFilterError,
    ContextLengthError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)
from nexus.providers.mock import MockProvider


def _request(**extra: object) -> CompletionRequest:
    return CompletionRequest(
        messages=[{"role": "user", "content": "hello"}],  # type: ignore[list-item]
        model="mock-fast",
        extra=dict(extra),
    )


async def test_same_prompt_gives_same_answer() -> None:
    provider = MockProvider(latency_ms=0)
    first = await provider.complete(_request())
    second = await provider.complete(_request())
    assert first.text == second.text


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("rate_limit", RateLimitError),
        ("timeout", ProviderTimeoutError),
        ("unavailable", ProviderUnavailableError),
        ("context_length", ContextLengthError),
        ("content_filter", ContentFilterError),
        ("auth", AuthError),
    ],
)
async def test_each_failure_mode_maps_to_its_error(mode: str, expected: type) -> None:
    provider = MockProvider(latency_ms=0)
    with pytest.raises(expected):
        await provider.complete(_request(mock_fail=mode))


async def test_retry_and_fallback_flags_match_intent() -> None:
    # A content filter or auth failure must never be retried or shopped around
    # to another provider; a rate limit or outage should fall back.
    assert RateLimitError("x", provider="mock").should_fallback is True
    assert ProviderUnavailableError("x", provider="mock").should_fallback is True
    assert ContentFilterError("x", provider="mock").should_fallback is False
    assert AuthError("x", provider="mock").retryable is False


async def test_streaming_ends_with_usage() -> None:
    provider = MockProvider(latency_ms=0)
    chunks = [c async for c in provider.stream(_request())]
    assert chunks[-1].usage is not None
    assert chunks[-1].finish_reason == "stop"
    assert "".join(c.delta for c in chunks).strip()


async def test_embeddings_are_normalised_and_sized() -> None:
    vectors = await MockProvider().embed(["alpha", "beta"], model="mock-embed")
    assert len(vectors) == 2
    assert all(len(v) == 1536 for v in vectors)
    assert abs(sum(x * x for x in vectors[0]) ** 0.5 - 1.0) < 1e-6
