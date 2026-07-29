"""Session lifecycle and credential resolution.

Resolution order and caching policy are the two things worth being careful
about here, and both are documented inline rather than left to be inferred.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.auth.permissions import DEFAULT_SERVICE_SCOPES, SYSTEM_ROLES
from nexus.auth.principal import Principal
from nexus.auth.tokens import generate_session_token, hash_token
from nexus.cache import get_redis
from nexus.config import get_settings
from nexus.db.models.access import ApiKey, Role, RoleAssignment, UserSession
from nexus.db.models.identity import User, WorkspaceMembership

REVOKED_CACHE_TTL_SECONDS = 30
_REVOKED_KEY = "nexus:revoked:{hash}"


# --------------------------------------------------------------------------- sessions


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, UserSession]:
    """Return (raw_token, session). The raw token leaves in a cookie and is
    never stored anywhere."""
    settings = get_settings()
    token, token_hash = generate_session_token()
    now = datetime.now(UTC)

    session = UserSession(
        user_id=user_id,
        token_hash=token_hash,
        workspace_id=workspace_id,
        ip_address=ip_address,
        user_agent=user_agent,
        status="active",
        expires_at=now + timedelta(hours=settings.auth.session_hours),
        last_active_at=now,
        created_at=now,
    )
    db.add(session)
    await db.flush()
    return token, session


async def revoke_session(db: AsyncSession, token: str, reason: str = "user_logout") -> None:
    token_hash = hash_token(token)
    await db.execute(
        update(UserSession)
        .where(UserSession.token_hash == token_hash)
        .values(status="revoked", revoke_reason=reason)
    )
    # Publish the revocation so other replicas stop honouring it immediately
    # rather than up to one cache TTL later.
    await get_redis().setex(
        _REVOKED_KEY.format(hash=token_hash), REVOKED_CACHE_TTL_SECONDS, "1"
    )


async def revoke_all_sessions_for_user(
    db: AsyncSession, user_id: uuid.UUID, reason: str = "admin_force"
) -> int:
    result = await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.status == "active")
        .values(status="revoked", revoke_reason=reason)
        .returning(UserSession.token_hash)
    )
    hashes = list(result.scalars())
    redis = get_redis()
    for token_hash in hashes:
        await redis.setex(_REVOKED_KEY.format(hash=token_hash), REVOKED_CACHE_TTL_SECONDS, "1")
    return len(hashes)


# ------------------------------------------------------------------------ permissions


async def _permissions_for(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Union of every non-expired role the user holds in this workspace."""
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(Role)
            .join(RoleAssignment, RoleAssignment.role_id == Role.id)
            .where(
                RoleAssignment.user_id == user_id,
                RoleAssignment.workspace_id == workspace_id,
                (RoleAssignment.expires_at.is_(None)) | (RoleAssignment.expires_at > now),
            )
        )
    ).scalars().all()

    permissions: set[str] = set()
    names: list[str] = []
    for role in rows:
        names.append(role.name)
        permissions.update(role.permissions or SYSTEM_ROLES.get(role.name, []))
    return frozenset(permissions), tuple(sorted(names))


# ------------------------------------------------------------------------- resolution


async def resolve_session(
    db: AsyncSession, token: str, *, workspace_override: uuid.UUID | None = None
) -> Principal | None:
    token_hash = hash_token(token)

    # Fast negative check. A hit means "definitely revoked"; a miss means
    # "unknown", which falls through to the database rather than to trust.
    if await get_redis().get(_REVOKED_KEY.format(hash=token_hash)):
        return None

    session = await db.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash, UserSession.status == "active"
        )
    )
    if session is None:
        return None

    if session.expires_at <= datetime.now(UTC):
        session.status = "expired"
        return None

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None

    workspace_id = workspace_override or session.workspace_id or user.default_workspace_id
    if workspace_id is None:
        return None

    # Switching workspace requires membership of the target, or the session
    # becomes a way to read a tenant you were never added to.
    member = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    if member is None:
        return None

    permissions, roles = await _permissions_for(db, user.id, workspace_id)

    # Sliding refresh, written at most once a minute.
    now = datetime.now(UTC)
    if session.last_active_at is None or (now - session.last_active_at) > timedelta(minutes=1):
        session.last_active_at = now
        session.workspace_id = workspace_id

    return Principal(
        type="user",
        workspace_id=workspace_id,
        user_id=user.id,
        session_id=session.id,
        permissions=permissions,
        roles=roles,
        clearance=user.clearance,
        display_name=user.display_name,
    )


async def resolve_api_key(
    db: AsyncSession, raw_key: str, *, ip_address: str | None = None
) -> Principal | None:
    key_hash = hash_token(raw_key)

    if await get_redis().get(_REVOKED_KEY.format(hash=key_hash)):
        return None

    key = await db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if key is None or not key.is_usable:
        return None

    now = datetime.now(UTC)
    if key.expires_at is not None and key.expires_at <= now:
        return None

    if key.last_used_at is None or (now - key.last_used_at) > timedelta(minutes=1):
        key.last_used_at = now
        key.last_used_ip = ip_address
        key.request_count += 1

    return Principal(
        type="service",
        workspace_id=key.workspace_id,
        api_key_id=key.id,
        permissions=frozenset(key.scopes or DEFAULT_SERVICE_SCOPES),
        display_name=key.label,
    )


async def revoke_api_key(db: AsyncSession, key: ApiKey, revoked_by: uuid.UUID | None) -> None:
    key.revoked_at = datetime.now(UTC)
    key.revoked_by = revoked_by
    await get_redis().setex(
        _REVOKED_KEY.format(hash=key.key_hash), REVOKED_CACHE_TTL_SECONDS, "1"
    )
