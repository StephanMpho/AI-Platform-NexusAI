"""The gateway endpoint — GW-002.

Every application in the organisation calls this instead of calling a model
provider directly. The pipeline below is an explicit ordered list so that the
later tasks (quotas, policy, redaction) slot in as stages rather than rewrites
of this handler.

    authenticate -> resolve workspace -> quota -> pre-request policy
    -> route -> provider call -> usage and cost -> log -> respond
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from nexus.api.deps import require
from nexus.auth.principal import Principal
from nexus.providers import CompletionRequest, ProviderError, get_registry
from nexus.schemas import ChatRequest, ChatResponse, Usage

router = APIRouter(prefix="/v1", tags=["gateway"])

# TODO(GW-003): replace with the routing policy engine reading routing_rules.
# Until then a static map keeps the endpoint honest and the tests meaningful.
_STATIC_ROUTES: dict[str, tuple[str, str]] = {
    "mock-fast": ("mock", "mock-fast"),
    "mock-strong": ("mock", "mock-strong"),
}


def _resolve(request: ChatRequest) -> tuple[str, str]:
    """Return (provider_slug, provider_model_name)."""
    if request.policy:
        # TODO(GW-003): evaluate routing_rules in order, first match wins.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="routing policies land in GW-003; pin a model for now",
        )
    assert request.model is not None  # guaranteed by ChatRequest validation
    route = _STATIC_ROUTES.get(request.model)
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_model", "model": request.model,
                    "available": sorted(_STATIC_ROUTES)},
        )
    return route


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    response: Response,
    principal: Annotated[Principal, Depends(require("gateway.chat.write"))],
) -> ChatResponse:
    request_id = uuid.uuid4()
    started = time.perf_counter()

    # The workspace comes from the credential, never from the request body:
    # a caller must not be able to bill another tenant by asking nicely.
    workspace_id = principal.workspace_id

    # TODO(GW-007): quota and rate-limit check, before any provider call.
    # TODO(GOV-002): pre-request policy evaluation.
    # TODO(GW-002): write gateway_requests with status='in_flight' here, so a
    #               crashed request leaves a record rather than a silence.

    provider_slug, provider_model = _resolve(request)
    provider = get_registry().get(provider_slug)

    completion_request = CompletionRequest(
        messages=request.messages,
        model=provider_model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        stop=request.stop,
        tools=request.tools,
        response_format=request.response_format,
        metadata=request.metadata,
    )

    try:
        result = await provider.complete(completion_request)
    except ProviderError as exc:
        # TODO(GW-004): retry and fallback by exc.retryable / exc.should_fallback
        #               before surfacing the failure to the caller.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": exc.error_class, "provider": exc.provider, "message": str(exc)},
        ) from exc

    # TODO(GW-006): write cost_entries against the rate effective at request time.
    # TODO(GW-008): write gateway_messages subject to workspace logging_mode.

    duration_ms = int((time.perf_counter() - started) * 1000)

    # Callers need to see when routing sent them somewhere other than they asked.
    response.headers["x-nexus-request-id"] = str(request_id)
    response.headers["x-nexus-workspace"] = str(workspace_id)
    response.headers["x-nexus-model"] = result.model

    return ChatResponse(
        request_id=str(request_id),
        content=result.text,
        model_used=result.model,
        provider=result.provider,
        finish_reason=result.finish_reason,
        tool_calls=result.tool_calls,
        usage=Usage(
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cached_tokens=result.usage.cached_tokens,
        ),
        duration_ms=duration_ms,
    )
