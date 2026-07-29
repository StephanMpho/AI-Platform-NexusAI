"""Domain 1 — Identity & Access (migration 001).

Only the tables the gateway needs on day one. The remaining four in this domain
(roles, role_assignments, api_keys, user_sessions) land with AUTH-001/AUTH-002.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base, Timestamps, UUIDPrimaryKey

CLEARANCE_LEVELS = ("public", "internal", "confidential", "restricted")
LOGGING_MODES = ("full", "redacted", "metadata_only")


class Workspace(UUIDPrimaryKey, Timestamps, Base):
    """The tenancy boundary. Every business record belongs to exactly one."""

    __tablename__ = "workspaces"

    slug: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)

    # Governs what gateway_messages stores. See GW-008.
    logging_mode: Mapped[str] = mapped_column(String(20), default="redacted")

    monthly_budget_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    data_residency: Mapped[str | None] = mapped_column(String(20))
    # FALSE forces routing to self-hosted deployments only.
    allow_external_providers: Mapped[bool] = mapped_column(Boolean, default=True)

    settings: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    memberships: Mapped[list[WorkspaceMembership]] = relationship(back_populates="workspace")


class User(UUIDPrimaryKey, Timestamps, Base):
    """Provisioned on first SSO login. Matched on (issuer, external_subject),
    never on email — people change email addresses."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    external_subject: Mapped[str | None] = mapped_column(String(255), index=True)
    issuer: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(String(500))

    default_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id")
    )
    # Matched against document sensitivity during retrieval (KB-005).
    clearance: Mapped[str] = mapped_column(String(20), default="internal")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None]

    __table_args__ = (UniqueConstraint("issuer", "external_subject", name="subject"),)


class WorkspaceMembership(UUIDPrimaryKey, Base):
    __tablename__ = "workspace_memberships"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    joined_at: Mapped[datetime]

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")

    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="membership"),)
