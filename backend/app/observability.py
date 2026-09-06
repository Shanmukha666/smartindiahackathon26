import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from opentelemetry import metrics, propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from .config import Settings

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
METER = metrics.get_meter("ip_sakti.pipeline")
STAGE_DURATION = METER.create_histogram("ip_sakti.stage.duration", unit="s", description="Pipeline stage latency")
STAGE_REQUESTS = METER.create_counter("ip_sakti.stage.requests", description="Pipeline stage attempts")
STAGE_ERRORS = METER.create_counter("ip_sakti.stage.errors", description="Pipeline stage failures")
ESCALATIONS = METER.create_counter("ip_sakti.escalations", description="Escalations created")
CITATION_FAILURES = METER.create_counter("ip_sakti.citation_validation_failures", description="Invalid model citations")


class JsonFormatter(logging.Formatter):
    """Emit bounded operational fields only; never request bodies, credentials, or tokens."""
    allowed_fields = (
        "method", "path", "status_code", "stage", "outcome", "provider", "error_type",
        "result_count", "candidate_count", "invalid_citation_count", "model_confidence",
        "max_reranker_score", "tracking_id", "priority", "language", "category",
    )

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        span = trace.get_current_span()
        span_context = span.get_span_context()
        if span_context.is_valid:
            event["trace_id"] = format(span_context.trace_id, "032x")
            event["span_id"] = format(span_context.span_id, "016x")
        if record.exc_info:
            event["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        for key in self.allowed_fields:
            if hasattr(record, key):
                event[key] = getattr(record, key)
        return json.dumps(event, separators=(",", ":"))


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def configure_tracing(settings: Settings, app: Any) -> None:
    resource = Resource.create({"service.name": settings.otel_service_name, "service.version": settings.service_version,
                                "deployment.environment": settings.deployment_environment})
    if settings.otel_traces_exporter.lower() != "none":
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)))
        trace.set_tracer_provider(provider)
    if settings.otel_metrics_exporter.lower() != "none":
        reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=settings.otel_exporter_otlp_endpoint),
                                               export_interval_millis=settings.otel_metric_export_interval_ms)
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    FastAPIInstrumentor.instrument_app(app)


def outbound_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Inject W3C trace context and request correlation without copying inbound credentials."""
    carrier = dict(headers or {})
    propagate.inject(carrier)
    carrier["X-Request-ID"] = request_id_context.get()
    return carrier


@contextmanager
def stage(name: str, **attributes: str | float | bool) -> Iterator[trace.Span]:
    """Create a stage span and low-cardinality latency/error metrics."""
    metric_attributes = {"stage": name, **{key: str(value) for key, value in attributes.items()
                                             if key in {"provider", "jurisdiction", "input_type"}}}
    STAGE_REQUESTS.add(1, metric_attributes)
    started = time.perf_counter()
    with trace.get_tracer("ip_sakti.pipeline").start_as_current_span(name) as span:
        span.set_attribute("app.request_id", request_id_context.get())
        for key, value in attributes.items():
            if key in {"provider", "jurisdiction", "input_type", "mode", "priority", "task_type", "complete",
                       "document_count", "input_count"}:
                span.set_attribute(f"app.{key}", value)
        try:
            yield span
        except Exception as error:
            STAGE_ERRORS.add(1, {**metric_attributes, "error_type": type(error).__name__})
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            raise
        finally:
            STAGE_DURATION.record(time.perf_counter() - started, metric_attributes)


def record_escalation(priority: str, reason: str) -> None:
    # `reason` is caller-controlled; it belongs in the audited database record, not telemetry labels.
    ESCALATIONS.add(1, {"priority": priority})


def record_citation_failure() -> None:
    CITATION_FAILURES.add(1)


def annotate_request(request_id: str) -> None:
    """Attach the application correlation ID to the inbound HTTP span."""
    trace.get_current_span().set_attribute("app.request_id", request_id)


def new_request_id() -> str:
    return str(uuid4())
