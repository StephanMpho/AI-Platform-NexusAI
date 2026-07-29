"""OpenAI adapter — TODO(GW-001).

The shape is here and the error mapping is the part that matters; fill in the
HTTP calls. Keep every provider-specific detail inside this file.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx

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


class OpenAIProvider:
    slug = "openai"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 timeout_ms: int = 60_000) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_ms / 1000,
        )

    def _translate_error(self, exc: Exception) -> Exception:
        """Map provider failures onto the normalised classes.

        Everything downstream depends on this being right, so it is worth a test
        per branch rather than a glance.
        """
        if isinstance(exc, httpx.TimeoutException):
            return ProviderTimeoutError(str(exc), provider=self.slug)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            body = exc.response.text.lower()
            if status == 429:
                retry_after = exc.response.headers.get("retry-after")
                return RateLimitError(
                    str(exc),
                    provider=self.slug,
                    retry_after=float(retry_after) if retry_after else None,
                )
            if status in (401, 403):
                return AuthError(str(exc), provider=self.slug, status_code=status)
            if status == 400 and "context_length" in body:
                return ContextLengthError(str(exc), provider=self.slug, status_code=status)
            if status == 400 and "content_filter" in body:
                return ContentFilterError(str(exc), provider=self.slug, status_code=status)
            if status >= 500:
                return ProviderUnavailableError(str(exc), provider=self.slug, status_code=status)
        if isinstance(exc, httpx.RequestError):
            return ProviderUnavailableError(str(exc), provider=self.slug)
        return exc

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        started = time.perf_counter()
        payload = {
            "model": request.model,
            "messages": [m.model_dump(exclude_none=True) for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stop": request.stop,
        }
        try:
            response = await self._client.post(
                "/chat/completions", json={k: v for k, v in payload.items() if v is not None}
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, then normalised
            raise self._translate_error(exc) from exc

        data = response.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return CompletionResult(
            text=choice["message"].get("content") or "",
            model=data.get("model", request.model),
            provider=self.slug,
            finish_reason=choice.get("finish_reason"),
            tool_calls=choice["message"].get("tool_calls", []) or [],
            usage=TokenUsage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                cached_tokens=usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
            ),
            provider_request_id=data.get("id"),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        raise NotImplementedError("TODO(GW-005): SSE streaming")
        yield CompletionChunk()  # pragma: no cover - satisfies the generator protocol

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise NotImplementedError("TODO(KB-003): embeddings")

    async def health(self) -> ProviderHealth:
        try:
            started = time.perf_counter()
            response = await self._client.get("/models")
            response.raise_for_status()
            return ProviderHealth(
                status="healthy", latency_ms=int((time.perf_counter() - started) * 1000)
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(status="unavailable", detail=str(exc))
