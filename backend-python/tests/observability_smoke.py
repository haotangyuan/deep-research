from __future__ import annotations

from agentscope.middleware._tracing._setup import _get_tracer as agentscope_tracer
from agentscope.middleware._tracing._trace import _check_tracing_enabled
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.config import get_settings
from app.infrastructure.observability import export_headers, resolved_endpoint


def main() -> None:
    settings = get_settings()
    endpoint = resolved_endpoint()
    assert settings.research_observability_enabled, "observability is disabled"
    assert endpoint, "observability endpoint is not configured"

    memory = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "deep-research-observability-smoke"}))
    provider.add_span_processor(SimpleSpanProcessor(memory))
    trace.set_tracer_provider(provider)
    assert _check_tracing_enabled(), "AgentScope cannot see the OpenTelemetry SDK provider"

    app_tracer = provider.get_tracer("deep-research.workflow")
    with app_tracer.start_as_current_span("deep_research.workflow"):
        with app_tracer.start_as_current_span("deep_research.stage ObservabilitySmoke"):
            with agentscope_tracer().start_as_current_span("invoke_agent ObservabilitySmoke"):
                with agentscope_tracer().start_as_current_span("chat observability-smoke-model"):
                    pass

    spans = memory.get_finished_spans()
    assert len(spans) == 4
    assert len({span.context.trace_id for span in spans}) == 1
    by_name = {span.name: span for span in spans}
    assert by_name["deep_research.stage ObservabilitySmoke"].parent.span_id == by_name["deep_research.workflow"].context.span_id
    assert by_name["invoke_agent ObservabilitySmoke"].parent.span_id == by_name["deep_research.stage ObservabilitySmoke"].context.span_id
    assert by_name["chat observability-smoke-model"].parent.span_id == by_name["invoke_agent ObservabilitySmoke"].context.span_id

    exporter = OTLPSpanExporter(endpoint=endpoint, headers=export_headers(), timeout=15)
    result = exporter.export(spans)
    exporter.shutdown()
    provider.shutdown()
    assert result == SpanExportResult.SUCCESS, f"OTLP export failed: {result}"
    print("observability-smoke: passed provider=langfuse spans=4 export=SUCCESS")


if __name__ == "__main__":
    main()
