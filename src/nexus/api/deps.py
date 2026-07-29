"""Request dependencies.

`get_principal` is the only place either credential type is read. Routers depend
on it and never inspect headers or cookies themselves.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.auth.permissions import Permission
from nexus.auth.principal import Principal
from nexus.auth.sessions import resolve_api_key, resolve_session
from nexus.auth.tokens import detect_credential_kind
from nexus.config import Settings, get_settings
from nexus.db.session import get_session

SESSION_COOKIE = "nexus_session"
WORKSPACE_HEADER = "x-nexus-workspace"

# Fixed IDs so seeded local data and the dev bypass agree with each other.
DEV_WORKSPACE = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER = uuid.UUID("00000000-0000-0000-0000-000000000002")

DbSession = Annotated[AsyncSession, Depends(get_session)]


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def get_principal(
    request: Request,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    nexus_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    x_nexus_workspace: Annotated[str | None, Header()] = None,
) -> Principal:
    """Resolve a browser session or a service API key into one Principal.

    Order matters: an explicit Authorization header wins over an ambient cookie,
    so a script running in an authenticated browser context cannot accidentally
    borrow the user's session.
    """
    if settings.auth.dev_bypass and settings.env == "local":
        return Principal(
            type="user",
            workspace_id=DEV_WORKSPACE,
            user_id=DEV_USER,
            permissions=frozenset({"*"}),
            roles=("owner",),
            clearance="restricted",
            display_name="Local Developer",
        )

    workspace_override: uuid.UUID | None = None
    if x_nexus_workspace:
        try:
            workspace_override = uuid.UUID(x_nexus_workspace)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{WORKSPACE_HEADER} must be a UUID",
            ) from None

    principal: Principal | None = None

    if authorization:
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() != "bearer" or not credential:
            raise _unauthorised("expected 'Authorization: Bearer <token>'")
        kind = detect_credential_kind(credential)
        if kind == "api_key":
            principal = await resolve_api_key(db, credential, ip_address=_client_ip(request))
        else:
            principal = await resolve_session(
                db, credential, workspace_override=workspace_override
            )
    elif nexus_session:
        principal = await resolve_session(
            db, nexus_session, workspace_override=workspace_override
        )

    if principal is None:
        raise _unauthorised("invalid, expired or revoked credential")

    # A workspace override that survived resolution has already been checked for
    # membership; one that did not is a 403 rather than a silent fallback.
    if workspace_override and principal.workspace_id != workspace_override:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "workspace_forbidden", "workspace_id": str(workspace_override)},
        )

    return principal


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(permission: Permission) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency factory that names the missing permission in the 403.

    A generic "forbidden" tells whoever is debugging a policy nothing at all,
    and they are usually debugging it under time pressure.
    """

    async def _check(principal: CurrentPrincipal) -> Principal:
        if not principal.has(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "permission_denied",
                    "missing_permission": permission,
                    "principal_type": principal.type,
                },
            )
        return principal

    return _check
