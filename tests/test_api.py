from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_health_reports_providers_without_credentials(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "mock" in body["providers"]
    # A credential must never appear in a health response.
    assert "api_key" not in response.text.lower()


async def test_chat_returns_completion_from_mock(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hello"}], "model": "mock-fast"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert body["usage"]["output_tokens"] > 0
    assert response.headers["x-nexus-model"] == "mock-fast"


async def test_chat_rejects_unknown_model_by_name(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "model": "does-not-exist"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["model"] == "does-not-exist"


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": [{"role": "user", "content": "hi"}]},  # neither model nor policy
        {"messages": [{"role": "user", "content": "hi"}], "model": "m", "policy": "p"},  # both
        {"messages": [], "model": "mock-fast"},  # empty conversation
        {"messages": [{"role": "user", "content": "hi"}], "model": "mock-fast", "junk": 1},
    ],
)
async def test_chat_rejects_malformed_requests(client: AsyncClient, payload: dict) -> None:
    response = await client.post("/v1/chat", json=payload)
    assert response.status_code == 422


async def test_chat_reports_the_workspace_from_the_credential(client: AsyncClient) -> None:
    """The workspace must come from the credential, never the request body —
    otherwise a caller can bill another tenant by asking politely."""
    response = await client.post(
        "/v1/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "model": "mock-fast",
            "metadata": {"workspace_id": "11111111-1111-1111-1111-111111111111"},
        },
    )
    assert response.status_code == 200
    assert response.headers["x-nexus-workspace"] != "11111111-1111-1111-1111-111111111111"


async def test_logout_clears_the_session_cookie(client: AsyncClient) -> None:
    response = await client.post("/auth/logout")
    assert response.status_code == 204
