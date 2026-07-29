"""Domain 1 continued — roles, assignments, API keys, sessions (migration 002)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base, Timestamps, UUIDPrimaryKey

SESSION_STATUSES = ("active", "expired", "revoked", "logged_out")
REVOKE_REASONS = ("user_logout", "admin_force", "suspicious_activity", "expired")


class Role(UUIDPrimaryKey, Timestamps, Base):
    """A named permission bundle. workspace_id NULL means a system role shared
    by every workspace."""

    __tablename__ = "roles"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="role_name"),
    )


class RoleAssignment(UUIDPrimaryKey, Base):
    __tablename__ = "role_assignments"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    # Time-bounded elevation: grant admin for an afternoon, not forever.
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime]

    role: Mapped[Role] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "role_id", name="role_assignment"),
    )


class ApiKey(UUIDPrimaryKey, Base):
    """Service credentials. Scoped to exactly one workspace — a key that could
    reach two tenants is a key that will eventually reach the wrong one."""

    __tablename__ = "api_keys"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(10))
    label: Mapped[str] = mapped_column(String(100))
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    # Written at most once a minute; on a hot key this would otherwise be a
    # write on every single request for information nobody reads that often.
    last_used_at: Mapped[datetime | None]
    last_used_ip: Mapped[str | None] = mapped_column(INET)
    request_count: Mapped[int] = mapped_column(Integer, default=0)

    expires_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None] = mapped_column(index=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime]

    @property
    def is_usable(self) -> bool:
        return self.revoked_at is None


class UserSession(UUIDPrimaryKey, Base):
    """Browser sessions, with the revocation state that makes logout mean
    something on the server as well as the client."""

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id")
    )
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(50))
    expires_at: Mapped[datetime] = mapped_column(index=True)
    last_active_at: Mapped[datetime | None]
    created_at: Mapped[datetime]
