"""OpenTelemetry setup — partial, see OBS-001 and OBS-002.

Content attributes (gen_ai.prompt / gen_ai.completion) are never emitted here.
Enabling them is a per-workspace decision, and the collector strips them again
as a second line of defence.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

from nexus.config import Settings

# OpenTelemetry GenAI semantic conventions. Using the standard names means any
# OTel-compatible backend reads our LLM spans without custom mapping.
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_FINISH_REASONS = "gen_ai.response.finish_reasons"

# Platform-specific attributes stay in their own namespace.
NEXUS_WORKSPACE = "nexus.workspace_id"
NEXUS_COST_USD = "nexus.cost_usd"
NEXUS_FALLBACK_COUNT = "nexus.fallback_count"
NEXUS_POLICY_VERSION = "nexus.policy_version"


def setup_telemetry(settings: Settings) -> None:
    if not settings.telemetry.enabled:
        return

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.telemetry.service_name,
                "deployment.environment": settings.env,
            }
        ),
        sampler=TraceIdRatioBased(settings.telemetry.sample_rate),
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.telemetry.otlp_endpoint,
                                            insecure=True))
    )
    trace.set_tracer_provider(provider)


def get_tracer(name: str = "nexus") -> trace.Tracer:
    return trace.get_tracer(name)


def record_llm_span(span: trace.Span, **kwargs: Any) -> None:
    """Attach GenAI convention attributes to a provider-call span."""
    mapping = {
        "system": GEN_AI_SYSTEM,
        "request_model": GEN_AI_REQUEST_MODEL,
        "response_model": GEN_AI_RESPONSE_MODEL,
        "input_tokens": GEN_AI_INPUT_TOKENS,
        "output_tokens": GEN_AI_OUTPUT_TOKENS,
        "finish_reason": GEN_AI_FINISH_REASONS,
        "workspace_id": NEXUS_WORKSPACE,
        "cost_usd": NEXUS_COST_USD,
        "fallback_count": NEXUS_FALLBACK_COUNT,
    }
    for key, value in kwargs.items():
        attr = mapping.get(key)
        if attr and value is not None:
            span.set_attribute(attr, value)
