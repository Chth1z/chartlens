"""OpenTelemetry tracing bootstrap — opt-in via EYEX_OTEL_ENABLED=true.

When disabled (the default), get_tracer() returns the OTel no-op tracer so all
span creation calls are zero-cost no-ops. When enabled, a real TracerProvider is
configured with either an OTLP gRPC exporter or a console exporter for local dev.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.trace import Tracer

_initialized = False


def init_telemetry() -> None:
    """Initialize the OTel TracerProvider once at app startup."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    from app.core.settings import settings

    if not settings.otel_enabled:
        return

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    if settings.otel_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def get_tracer(name: str = "eyex") -> Tracer:
    """Return a tracer. Returns a no-op tracer when OTel is not configured."""
    return trace.get_tracer(name)
