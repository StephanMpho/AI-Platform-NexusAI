"""The internal request shape every provider adapter translates to and from.

No provider-specific field is allowed to leak into these types. If something is
only meaningful to one provider it belongs in `extra`, and routing must not
depend on it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class CompletionRequest(BaseModel):
    messages: list[ChatMessage]
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: Literal["text", "json"] = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)

    def estimated_input_tokens(self) -> int:
        """Cheap pre-call estimate used for routing decisions only.

        Billing always uses the real count returned by the provider. An estimator
        good enough to route is not good enough to invoice.
        """
        chars = sum(len(m.content) for m in self.messages)
        return max(1, chars // 4)


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


class CompletionResult(BaseModel):
    text: str
    model: str
    provider: str
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    provider_request_id: str | None = None
    latency_ms: int = 0


class CompletionChunk(BaseModel):
    delta: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None


class ProviderHealth(BaseModel):
    status: Literal["healthy", "degraded", "unavailable"]
    latency_ms: int | None = None
    detail: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Every adapter implements this and nothing more."""

    slug: str

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]: ...

    async def embed(self, texts: list[str], model: str) -> list[list[float]]: ...

    async def health(self) -> ProviderHealth: ...
