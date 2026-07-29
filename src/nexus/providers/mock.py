"""Deterministic provider for tests, CI and offline development.

This exists so the entire request path — routing, retry, fallback, cost
accounting, tracing — is exercisable without a network call or a cent of spend.
It can also be told to fail with any normalised error, which is the only
practical way to test fallback behaviour.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator

from nexus.providers.base import (
    CompletionChunk,
    CompletionRequest,
    CompletionResult,
    ProviderHealth,
    TokenUsage,
)
from nexus.providers.errors import (
    AuthError,
    ContentFilterError,
    ContextLengthError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)

_FAILURE_MODES = {
    "rate_limit": RateLimitError,
    "timeout": ProviderTimeoutError,
    "unavailable": ProviderUnavailableError,
    "context_length": ContextLengthError,
    "content_filter": ContentFilterError,
    "auth": AuthError,
}


class MockProvider:
    slug = "mock"

    def __init__(self, *, latency_ms: int = 40, fail_with: str | None = None) -> None:
        self.latency_ms = latency_ms
        self.fail_with = fail_with

    def _maybe_fail(self, request: CompletionRequest) -> None:
        # Per-request override wins, so a single test can force one failure.
        mode = request.extra.get("mock_fail") or self.fail_with
        if mode:
            exc = _FAILURE_MODES.get(str(mode))
            if exc is None:
                raise ValueError(f"unknown mock failure mode: {mode}")
            raise exc(f"mock provider forced failure: {mode}", provider=self.slug)

    @staticmethod
    def _answer(request: CompletionRequest) -> str:
        """Same prompt, same answer — snapshot tests need a stable response."""
        seed = "|".join(f"{m.role}:{m.content}" for m in request.messages)
        digest = hashlib.sha256(seed.encode()).hexdigest()[:8]
        last = request.messages[-1].content if request.messages else ""
        return f"[mock:{request.model}:{digest}] responding to: {last[:160]}"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self._maybe_fail(request)
        await asyncio.sleep(self.latency_ms / 1000)
        text = self._answer(request)
        return CompletionResult(
            text=text,
            model=request.model,
            provider=self.slug,
            finish_reason="stop",
            usage=TokenUsage(
                input_tokens=request.estimated_input_tokens(),
                output_tokens=max(1, len(text) // 4),
            ),
            provider_request_id=f"mock-{hashlib.md5(text.encode()).hexdigest()[:12]}",
            latency_ms=self.latency_ms,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        self._maybe_fail(request)
        text = self._answer(request)
        for word in text.split(" "):
            await asyncio.sleep(self.latency_ms / 1000 / 20)
            yield CompletionChunk(delta=word + " ")
        yield CompletionChunk(
            finish_reason="stop",
            usage=TokenUsage(
                input_tokens=request.estimated_input_tokens(),
                output_tokens=max(1, len(text) // 4),
            ),
        )

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Hash-derived unit vectors. Deterministic, and similar strings land
        nowhere near each other — useful for plumbing tests, useless for
        retrieval quality, which is the honest trade-off here."""
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha512(text.encode()).digest()
            raw = [(b - 128) / 128 for b in digest]
            vec = (raw * (1536 // len(raw) + 1))[:1536]
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out

    async def health(self) -> ProviderHealth:
        return ProviderHealth(status="healthy", latency_ms=self.latency_ms)
