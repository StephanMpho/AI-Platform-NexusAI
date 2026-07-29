"""Request dependencies.

`get_principal` is the single place either credential type is resolved. Whatever
authenticated — a browser session or a service API key — routers see one object.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, status

from nexus.config import Settings, get_settings

DEV_WORKSPACE = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER = uuid.UUID("00000000-0000-0000-0000-000000000002")


@dataclass(slots=True)
class Principal:
    type: Literal["user", "service"]
    workspace_id: uuid.UUID
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    roles: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)

    def has(self, permission: str) -> bool:
        return permission in self.scopes or "owner" in self.roles


async def get_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    # TODO(AUTH-001): resolve OIDC sessions and hashed API keys against the database.
    if settings.auth.dev_bypass and settings.env == "local":
        return Principal(
            type="user",
            workspace_id=DEV_WORKSPACE,
            user_id=DEV_USER,
            roles=["owner"],
            scopes=["*"],
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication is not configured yet — see AUTH-001",
    )


def require(permission: str):  # noqa: ANN201 - returns a FastAPI dependency
    """Name the missing permission in the 403.

    A generic 'forbidden' is useless when you are debugging a policy at 11pm.
    """

    async def _check(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not principal.has(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "permission_denied", "missing_permission": permission},
            )
        return principal

    return _check
