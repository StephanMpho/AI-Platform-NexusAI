"""Authentication routes — AUTH-001."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import SESSION_COOKIE, CurrentPrincipal, DbSession
from nexus.auth.oidc import OidcClaims, OidcClient, OidcError
from nexus.auth.permissions import SYSTEM_ROLES
from nexus.auth.sessions import create_session, revoke_session
from nexus.config import Settings, get_settings
from nexus.db.models.access import Role, RoleAssignment
from nexus.db.models.identity import User, Workspace, WorkspaceMembership

router = APIRouter(prefix="/auth", tags=["auth"])


class MeResponse(BaseModel):
    type: str
    user_id: uuid.UUID | None
    workspace_id: uuid.UUID
    display_name: str
    roles: list[str]
    permissions: list[str]
    clearance: str


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,                       # not readable from JavaScript
        secure=settings.env != "local",      # plain HTTP only ever locally
        samesite="lax",                      # survives the OIDC redirect back
        max_age=settings.auth.session_hours * 3600,
        path="/",
    )


@router.get("/login")
async def login(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    next: Annotated[str, Query()] = "/",
) -> RedirectResponse:
    # Only relative paths, or /auth/login becomes an open redirect that lends
    # our domain's credibility to someone else's page.
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    redirect_uri = str(request.url_for("callback"))
    url = await OidcClient(settings).start(redirect_uri, next_path=next)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/callback", name="callback")
async def callback(
    db: DbSession,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> RedirectResponse:
    try:
        claims, next_path = await OidcClient(settings).complete(code, state)
    except OidcError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await _provision_user(db, claims)
    token, _ = await create_session(
        db,
        user_id=user.id,
        workspace_id=user.default_workspace_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    response = RedirectResponse(next_path, status_code=status.HTTP_302_FOUND)
    _set_session_cookie(response, token, settings)
    return response


async def _provision_user(db: DbSession, claims: OidcClaims) -> User:
    """Match on (issuer, subject) rather than email.

    People change email addresses, and two identity providers can legitimately
    issue the same subject string. The pair is the stable identity.
    """
    user = await db.scalar(
        select(User).where(User.issuer == claims.issuer, User.external_subject == claims.subject)
    )
    if user is None:
        user = await db.scalar(select(User).where(User.email == claims.email))
        if user is not None:
            # Existing local account being linked to SSO for the first time.
            user.issuer = claims.issuer
            user.external_subject = claims.subject

    if user is None:
        user = User(
            email=claims.email,
            issuer=claims.issuer,
            external_subject=claims.subject,
            display_name=claims.name,
            avatar_url=claims.picture,
            clearance="internal",
        )
        db.add(user)
        await db.flush()
        await _attach_to_default_workspace(db, user)

    user.last_login_at = datetime.now(UTC)
    await db.flush()
    return user


async def _attach_to_default_workspace(db: DbSession, user: User) -> None:
    """New users land in the default workspace as a viewer.

    Least privilege on arrival: someone has to deliberately grant more, and that
    grant is audited.
    """
    workspace = await db.scalar(select(Workspace).where(Workspace.slug == "default"))
    if workspace is None:
        return

    db.add(
        WorkspaceMembership(
            workspace_id=workspace.id, user_id=user.id, joined_at=datetime.now(UTC)
        )
    )
    viewer = await db.scalar(
        select(Role).where(Role.name == "viewer", Role.workspace_id.is_(None))
    )
    if viewer is not None:
        db.add(
            RoleAssignment(
                workspace_id=workspace.id,
                user_id=user.id,
                role_id=viewer.id,
                created_at=datetime.now(UTC),
            )
        )
    user.default_workspace_id = workspace.id


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    db: DbSession,
    response: Response,
    nexus_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    """Revokes server-side as well as clearing the cookie. Clearing only the
    cookie leaves a token that still works if anyone copied it."""
    if nexus_session:
        await revoke_session(db, nexus_session, reason="user_logout")
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=MeResponse)
async def me(principal: CurrentPrincipal) -> MeResponse:
    return MeResponse(
        type=principal.type,
        user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        display_name=principal.display_name,
        roles=list(principal.roles),
        permissions=sorted(principal.permissions),
        clearance=principal.clearance,
    )


@router.get("/permissions", response_model=dict[str, list[str]])
async def available_roles(_: CurrentPrincipal) -> dict[str, list[str]]:
    """What each system role grants. Useful in the console when assigning one,
    and it means nobody has to read the source to find out."""
    return dict(SYSTEM_ROLES)
