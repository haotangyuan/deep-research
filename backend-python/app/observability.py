from __future__ import annotations

import base64
import re
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from .config import get_settings


@dataclass
class ResearchTraceMetadata:
    research_id: str
    user_id: int
    model_id: str
    budget_level: str
    agent_framework: str


def init_observability() -> None:
    settings = get_settings()
    endpoint = resolved_endpoint()
    if not settings.research_observability_enabled or not endpoint:
        return
    exporter = OTLPSpanExporter(endpoint=endpoint, headers=export_headers())
    provider = TracerProvider(resource=Resource.create({"service.name": "deep-research"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def shutdown_observability() -> None:
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()


def resolved_endpoint() -> str:
    settings = get_settings()
    if settings.research_observability_endpoint.strip():
        return settings.research_observability_endpoint.strip()
    if is_langfuse_provider():
        return "https://cloud.langfuse.com/api/public/otel/v1/traces"
    return ""


def is_langfuse_provider() -> bool:
    settings = get_settings()
    provider = settings.research_observability_provider.strip().lower()
    return provider == "langfuse" or bool(settings.langfuse_public_key and settings.langfuse_secret_key)


def export_headers() -> dict[str, str]:
    settings = get_settings()
    headers: dict[str, str] = {}
    if is_langfuse_provider() and settings.langfuse_public_key and settings.langfuse_secret_key:
        raw = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        headers["x-langfuse-ingestion-version"] = settings.langfuse_ingestion_version
    return headers


def summarize(value: str | None) -> str | None:
    settings = get_settings()
    if not settings.research_observability_capture_io or not value:
        return None
    sanitized = re.sub(r"(?i)authorization\s*[:=]\s*(?:bearer\s+)?[^\s]+", "authorization=[redacted]", value)
    sanitized = re.sub(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S+", r"\1=[redacted]", sanitized)
    max_chars = max(0, settings.research_observability_io_max_chars)
    return sanitized if max_chars <= 0 or len(sanitized) <= max_chars else sanitized[:max_chars]


def tracer():
    return trace.get_tracer("deep-research.workflow")


def _value(value: Any) -> str:
    return "" if value is None else str(value)


def _set_common(span: Span, state: Any | None) -> None:
    metadata = getattr(state, "trace_metadata", None)
    span.set_attribute("research.id", _value(getattr(metadata, "research_id", None)))
    user_id = getattr(metadata, "user_id", None)
    span.set_attribute("user.id", int(user_id or 0))
    span.set_attribute("model.id", _value(getattr(metadata, "model_id", None)))
    span.set_attribute("budget.level", _value(getattr(metadata, "budget_level", None)))
    span.set_attribute("agent.framework", _value(getattr(metadata, "agent_framework", None)))
    span.set_attribute("workflow.status", _value(getattr(state, "status", None)))


@contextmanager
def workflow_span(state: Any) -> Iterator[Span]:
    with tracer().start_as_current_span("deep_research.workflow") as span:
        _set_common(span, state)
        try:
            yield span
            _set_common(span, state)
            span.set_attribute("gen_ai.usage.input_tokens", int(getattr(state, "total_input_tokens", 0) or 0))
            span.set_attribute("gen_ai.usage.output_tokens", int(getattr(state, "total_output_tokens", 0) or 0))
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@asynccontextmanager
async def stage_span(name: str, state: Any) -> AsyncIterator[Span]:
    with tracer().start_as_current_span(f"deep_research.stage {name}") as span:
        span.set_attribute("gen_ai.operation.name", "agent.stage")
        span.set_attribute("agent.stage", name)
        _set_common(span, state)
        try:
            yield span
            _set_common(span, state)
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@asynccontextmanager
async def tool_span(tool_name: str, stage: str, state: Any, span_name: str | None = None) -> AsyncIterator[Span]:
    with tracer().start_as_current_span(span_name or f"deep_research.tool {tool_name}") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("agent.stage", stage)
        span.set_attribute("gen_ai.tool.call.count", 1)
        _set_common(span, state)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@asynccontextmanager
async def model_span(model_name: str, framework: str, request_summary: str | None, tool_count: int) -> AsyncIterator[Span]:
    with tracer().start_as_current_span(f"deep_research.model {model_name}") as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model_name)
        span.set_attribute("agent.framework", framework)
        span.set_attribute("gen_ai.request.tools.count", tool_count)
        summary = summarize(request_summary)
        if summary:
            span.set_attribute("gen_ai.request.summary", summary)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
