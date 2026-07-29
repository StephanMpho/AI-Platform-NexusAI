"""Anthropic adapter — TODO(GW-001).

Differences from OpenAI worth remembering when you fill this in: the system
prompt is a top-level field rather than a message, max_tokens is required, and
usage comes back as input_tokens / output_tokens. All of that stays in here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from nexus.providers.base import (
    CompletionChunk,
    CompletionRequest,
    CompletionResult,
    ProviderHealth,
)
from nexus.providers.errors import (
    AuthError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)


class AnthropicProvider:
    slug = "anthropic"

    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com/v1",
                 timeout_ms: int = 60_000) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=timeout_ms / 1000,
        )

    def _translate_error(self, exc: Exception) -> Exception:
        if isinstance(exc, httpx.TimeoutException):
            return ProviderTimeoutError(str(exc), provider=self.slug)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status == 429:
                return RateLimitError(str(exc), provider=self.slug)
            if status in (401, 403):
                return AuthError(str(exc), provider=self.slug, status_code=status)
            if status >= 500:
                return ProviderUnavailableError(str(exc), provider=self.slug, status_code=status)
        if isinstance(exc, httpx.RequestError):
            return ProviderUnavailableError(str(exc), provider=self.slug)
        return exc

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise NotImplementedError("TODO(GW-001): implement Anthropic completion")

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        raise NotImplementedError("TODO(GW-005): SSE streaming")
        yield CompletionChunk()  # pragma: no cover

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise NotImplementedError("Anthropic does not serve embeddings; route elsewhere")

    async def health(self) -> ProviderHealth:
        return ProviderHealth(status="healthy")
