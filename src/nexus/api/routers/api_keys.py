"""API key management — AUTH-001."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexus.api.deps import DbSession, require
from nexus.auth.permissions import DEFAULT_SERVICE_SCOPES, PERMISSIONS
from nexus.auth.principal import Principal
from nexus.auth.sessions import revoke_api_key
from nexus.auth.tokens import generate_api_key
from nexus.db.models.access import ApiKey

router = APIRouter(prefix="/v1/api-keys", tags=["admin"])


class CreateApiKeyRequest(BaseModel):
    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1, max_length=100)
    environment: Literal["live", "test"] = "test"
    scopes: list[str] | None = None
    expires_at: datetime | None = None


class ApiKeyRecord(BaseModel):
    id: uuid.UUID
    label: str
    key_prefix: str
    environment: str
    scopes: list[str]
    last_used_at: datetime | None
    request_count: int
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class CreatedApiKey(ApiKeyRecord):
    key: str
    warning: str = "Store this key now. It is hashed at rest and cannot be shown again."


@router.get("", response_model=list[ApiKeyRecord])
async def list_keys(
    db: DbSession,
    principal: Annotated[Principal, Depends(require("admin.apikey.write"))],
) -> list[ApiKeyRecord]:
    rows = (
        await db.execute(
            select(ApiKey)
            .where(ApiKey.workspace_id == principal.workspace_id)
            .order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()
    return [
        ApiKeyRecord(
            id=k.id,
            label=k.label,
            key_prefix=k.key_prefix,
            environment=k.environment,
            scopes=k.scopes or DEFAULT_SERVICE_SCOPES,
            last_used_at=k.last_used_at,
            request_count=k.request_count,
            expires_at=k.expires_at,
            revoked_at=k.revoked_at,
            created_at=k.created_at,
        )
        for k in rows
    ]


@router.post("", response_model=CreatedApiKey, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: CreateApiKeyRequest,
    db: DbSession,
    principal: Annotated[Principal, Depends(require("admin.apikey.write"))],
) -> CreatedApiKey:
    """Returns the key once. It is stored as a SHA-256 hash and is not
    recoverable afterwards, by design."""
    if body.scopes:
        unknown = [
            s for s in body.scopes
            if s not in PERMISSIONS and not s.endswith(".*") and s != "*"
        ]
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"error": "unknown_scopes", "scopes": unknown},
            )
        # A key must not be able to grant itself more than its creator holds.
        for scope in body.scopes:
            if not principal.has(scope):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    detail={"error": "cannot_grant_unheld_permission", "scope": scope},
                )

    full_key, key_hash, key_prefix = generate_api_key(body.environment)
    record = ApiKey(
        workspace_id=principal.workspace_id,
        key_prefix=key_prefix,
        key_hash=key_hash,
        environment=body.environment,
        label=body.label,
        scopes=body.scopes or list(DEFAULT_SERVICE_SCOPES),
        created_by=principal.user_id,
        expires_at=body.expires_at,
        created_at=datetime.now(UTC),
    )
    db.add(record)
    await db.flush()

    return CreatedApiKey(
        id=record.id,
        label=record.label,
        key_prefix=record.key_prefix,
        environment=record.environment,
        scopes=record.scopes or [],
        last_used_at=None,
        request_count=0,
        expires_at=record.expires_at,
        revoked_at=None,
        created_at=record.created_at,
        key=full_key,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: uuid.UUID,
    db: DbSession,
    principal: Annotated[Principal, Depends(require("admin.apikey.write"))],
) -> None:
    key = await db.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.workspace_id == principal.workspace_id
        )
    )
    if key is None:
        # Same response as a key that never existed — a 403 here would confirm
        # that a key with this ID exists in some other workspace.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="api key not found")
    if key.revoked_at is None:
        await revoke_api_key(db, key, revoked_by=principal.user_id)
