"""Domain 2 — Gateway & Routing (migration 002).

Providers and models are data, not code: adding a provider is a row plus an
adapter class reference, which is what keeps GW-001 open for extension.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base, Timestamps, UUIDPrimaryKey

MODEL_TIERS = ("cheap", "standard", "strong", "embedding")
REQUEST_STATUSES = ("in_flight", "success", "error", "rejected", "cancelled")


class Provider(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "providers"

    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    # Import path of the LLMProvider implementation.
    adapter_class: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str | None] = mapped_column(String(500))
    # Key into the secret resolver — never the credential itself.
    credential_ref: Mapped[str | None] = mapped_column(String(200))

    # Data policies gate on this. FALSE for self-hosted.
    is_external: Mapped[bool] = mapped_column(Boolean, default=True)
    region: Mapped[str | None] = mapped_column(String(20))

    default_timeout_ms: Mapped[int] = mapped_column(Integer, default=60_000)
    max_concurrency: Mapped[int] = mapped_column(SmallInteger, default=20)

    health_status: Mapped[str] = mapped_column(String(20), default="unknown")
    health_checked_at: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    models: Mapped[list[Model]] = relationship(back_populates="provider")


class Model(UUIDPrimaryKey, Timestamps, Base):
    """A model as the platform names it, decoupled from the provider's name.

    Callers ask for `fast-general`; which upstream model that resolves to is a
    routing decision the platform owns.
    """

    __tablename__ = "models"

    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id"), index=True
    )
    provider_model_name: Mapped[str] = mapped_column(String(200))
    family: Mapped[str | None] = mapped_column(String(50))
    tier: Mapped[str] = mapped_column(String(20), index=True)
    modality: Mapped[str] = mapped_column(String(20), default="text")

    context_window: Mapped[int] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_json_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_dimensions: Mapped[int | None] = mapped_column(SmallInteger)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deprecated_at: Mapped[datetime | None]

    provider: Mapped[Provider] = relationship(back_populates="models")


class GatewayRequest(UUIDPrimaryKey, Base):
    """One row per request through the gateway. Partition by day once volume
    justifies it — see migration 010 in the schema specification."""

    __tablename__ = "gateway_requests"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )

    requested_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("models.id")
    )
    # What actually served the request. Differs from requested when routing or
    # fallback intervened, which is exactly what callers need to be able to see.
    resolved_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("models.id"), index=True
    )

    status: Mapped[str] = mapped_column(String(20), default="in_flight", index=True)
    error_class: Mapped[str | None] = mapped_column(String(40), index=True)
    error_detail: Mapped[str | None] = mapped_column(Text)

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_input_tokens: Mapped[int | None] = mapped_column(Integer)

    fallback_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)

    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # The difference between these two is gateway overhead, and someone will ask.
    provider_duration_ms: Mapped[int | None] = mapped_column(Integer)

    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), index=True)
    request_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    is_streaming: Mapped[bool] = mapped_column(Boolean, default=False)
    client_ip: Mapped[str | None] = mapped_column(INET)

    created_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]
