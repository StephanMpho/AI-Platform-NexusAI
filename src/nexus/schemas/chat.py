"""Public API contracts. Deliberately separate from the internal provider types
so the wire format can stay stable while the internals change."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from nexus.providers.base import ChatMessage


class ChatRequest(BaseModel):
    model_config = {"extra": "forbid"}  # reject unknown fields rather than ignoring them

    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None
    policy: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32_000)
    stop: list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: Literal["text", "json"] = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False

    @model_validator(mode="after")
    def exactly_one_target(self) -> ChatRequest:
        """Pin a model or name a policy — never both, never neither.

        Accepting both would make the routing decision ambiguous, and silently
        preferring one is the kind of behaviour nobody can debug later.
        """
        if bool(self.model) == bool(self.policy):
            raise ValueError("provide exactly one of 'model' or 'policy'")
        return self


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float | None = None


class ChatResponse(BaseModel):
    request_id: str
    content: str
    model_used: str
    provider: str
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: Usage
    fallback_count: int = 0
    duration_ms: int


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    database: str
    providers: list[str]
