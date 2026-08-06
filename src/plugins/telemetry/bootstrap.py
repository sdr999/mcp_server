"""OpenTelemetry bootstrap and lifecycle manager.

Called from ASGI lifespan post-fork. Safe for multi-worker Gunicorn/Uvicorn deployments.
"""
from __future__ import annotations

import logging
from typing import Optional

from .config import TelemetryConfig

log = logging.getLogger("MCP_logger")

_tracer_provider = None
_meter_provider = None
_initialized = False


def init_telemetry(config: Optional[TelemetryConfig] = None) -> bool:
    global _tracer_provider, _meter_provider, _initialized

    if _initialized:
        return True

    if config is None:
        config = TelemetryConfig.from_env()

    if not config.enabled:
        log.info("Telemetry is disabled via config")
        return False

    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
    except ImportError:
        log.warning("opentelemetry packages not installed — telemetry disabled")
        return False

    resource = Resource.create({"service.name": config.service_name})
    _tracer_provider = TracerProvider(resource=resource)

    # Try OTLP gRPC exporter
    exporter = None
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint, insecure=True)
        log.info("Configured OTLPSpanExporter -> %s", config.otlp_endpoint)
    except Exception as exc:
        log.warning("Could not initialize OTLPSpanExporter: %s; falling back to console", exc)
        if config.export_to_console:
            exporter = ConsoleSpanExporter()

    if exporter:
        span_processor = BatchSpanProcessor(
            exporter,
            max_queue_size=config.max_queue_size,
            max_export_batch_size=config.batch_size,
            schedule_delay_millis=int(config.flush_interval_seconds * 1000),
        )
        _tracer_provider.add_span_processor(span_processor)

    trace.set_tracer_provider(_tracer_provider)

    # Meter provider
    _meter_provider = MeterProvider(resource=resource)
    metrics.set_meter_provider(_meter_provider)

    _initialized = True
    log.info("OpenTelemetry successfully initialized for service %r", config.service_name)
    return True


def shutdown_telemetry() -> None:
    global _tracer_provider, _meter_provider, _initialized
    if not _initialized:
        return

    if _tracer_provider and hasattr(_tracer_provider, "shutdown"):
        try:
            _tracer_provider.shutdown()
        except Exception as exc:
            log.warning("Error shutting down TracerProvider: %s", exc)

    if _meter_provider and hasattr(_meter_provider, "shutdown"):
        try:
            _meter_provider.shutdown()
        except Exception as exc:
            log.warning("Error shutting down MeterProvider: %s", exc)

    _initialized = False
    log.info("OpenTelemetry telemetry shut down cleanly")


def get_tracer(name: str = "mcp-server"):
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return None


def get_meter(name: str = "mcp-server"):
    try:
        from opentelemetry import metrics
        return metrics.get_meter(name)
    except ImportError:
        return None
