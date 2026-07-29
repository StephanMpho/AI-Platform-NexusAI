"""Permission matching and the shape of a denial."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from nexus.auth.permissions import SYSTEM_ROLES, matches
from nexus.auth.principal import Principal


@pytest.mark.parametrize(
    ("granted", "required", "expected"),
    [
        ("*", "governance.audit.read", True),
        ("gateway.*", "gateway.chat.write", True),
        ("gateway.*", "knowledge.ask.write", False),
        ("gateway.chat.write", "gateway.chat.write", True),
        ("gateway.chat.write", "gateway.chat.read", False),
        # A trailing wildcard must only match at a segment boundary, otherwise
        # `gateway.*` would quietly grant a future `gateways.*` module.
        ("gateway.*", "gateways.chat.write", False),
    ],
)
def test_wildcard_matching(granted: str, required: str, expected: bool) -> None:
    assert matches(granted, required) is expected


def _principal(*permissions: str) -> Principal:
    return Principal(
        type="user",
        workspace_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        permissions=frozenset(permissions),
    )


def test_viewer_cannot_write_and_owner_can_do_everything() -> None:
    viewer = _principal(*SYSTEM_ROLES["viewer"])
    owner = _principal(*SYSTEM_ROLES["owner"])

    assert viewer.has("gateway.request.read")
    assert not viewer.has("gateway.chat.write")
    assert not viewer.has("governance.audit.read")
    assert owner.has("governance.pii.reveal")


def test_analyst_cannot_read_the_audit_log() -> None:
    # Reading customer prompts and reading the audit log are different powers,
    # and the analyst role should hold neither.
    analyst = _principal(*SYSTEM_ROLES["analyst"])
    assert not analyst.has("governance.audit.read")
    assert not analyst.has("gateway.content.read")


def test_require_raises_with_the_permission_named() -> None:
    with pytest.raises(PermissionError) as exc:
        _principal("gateway.request.read").require("gateway.chat.write")
    assert "gateway.chat.write" in str(exc.value)


async def test_permissions_endpoint_documents_each_role(client: AsyncClient) -> None:
    response = await client.get("/auth/permissions")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(SYSTEM_ROLES)
    assert body["owner"] == ["*"]


async def test_me_reports_the_resolved_principal(client: AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["type"] == "user"
